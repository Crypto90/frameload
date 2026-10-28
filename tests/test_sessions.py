"""How a game's session ended ("What happened"): the launcher's record, the outcome, the kept evidence,
the report Copy Log hands out, and the routes the dialog uses."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from frameload import __version__
from frameload.installer import lepton_quest
from frameload.installer.lepton_quest import LAUNCH_SCRIPT_TEMPLATE, LeptonInstaller
from frameload.manager import migrate, sessions
from frameload.manager.installed import InstalledManager
from frameload.manager.launcher import GameLauncher
from frameload.server import FrameLoadApiHandler
from frameload.system import access

PKG = "com.test.game"


def lc(sec, pid, level, tag, msg):
    """A logcat line as Lepton mirrors it (-v threadtime), sec seconds into the session."""
    minute, second = divmod(sec, 60)
    return f"10-15 12:{minute:02d}:{second:02d}.123  {pid:>5} {pid:>5} {level} {tag:<8}: {msg}"


START_PROC = lc(0, 500, "I", "ActivityManager", f"Start proc 1234:{PKG}/u0a95 for top-activity {{{PKG}/.Main}}")
PACING = lc(5, 1234, "I", "FrameBridge", "FrameBridge: pacing: 72.0 fps, displayTime vs predicted: avg 1.2 ms")
NATIVE_CRASH = lc(70, 1234, "F", "libc", "Fatal signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0 in tid 1250 "
                                         f"(RenderThread), pid 1234 ({PKG})")
TOMBSTONE = [lc(71, 1300, "F", "DEBUG", m) for m in (
    "*** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***",
    "Build fingerprint: 'lepton/lepton/lepton:14/x/y:user/release-keys'",
    f"pid: 1234, tid: 1250, name: RenderThread  >>> {PKG} <<<",
    "signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0",
    "backtrace:",
    "      #00 pc 000000000004f9b8  /vendor/lib64/dri/libgallium_dri.so (BuildId: 1a2b)",
    "      #01 pc 00000000000a1b2c  /data/app/~~x/lib/arm64/libunity.so",
)]


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.base = os.path.join(self.tmp, "quest-frame", PKG)
        os.makedirs(self.base)
        self.dump = os.path.join(self.tmp, "logs", "lepton-logcats", "steamlaunch-4242")
        self.dep = {"package": PKG, "title": "Test Game", "appid": 4242, "base": self.base, "anchor": self.base,
                    "kind": "quest", "is_vr": True, "framebridge": True, "engine": "Unity", "version_name": "1.2.3",
                    "version_code": 45, "xr_runtime": "framebridge", "installed_by": "frameload",
                    "compat": {"level": "ok", "label": "Ported with FramePort"}}
        self.kernel = []
        for p in (patch.object(sessions, "SESSION_DIR", os.path.join(self.tmp, "sessions")),
                  patch.object(InstalledManager, "get_game", side_effect=lambda pkg: dict(self.dep) if pkg == PKG else None),
                  patch.object(sessions, "kernel_lines", side_effect=lambda *a, **kw: list(self.kernel))):
            p.start()
            self.addCleanup(p.stop)
        self.records_since(time.time() - 30 * 86400)  # FrameLoad has kept records for a month

    def records_since(self, when):
        self.write(".created", f"{when}\n", base=sessions.SESSION_DIR)

    def write(self, rel, text, base=None):
        path = os.path.join(base or self.base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return path

    def session(self, lines, rc=0, crash=None, length=300, ago=10):
        """A finished session as launch.sh (layout 7) and Lepton leave it."""
        end = int(time.time()) - ago
        start = end - length
        self.write(".last_played", f"{start}\n")
        self.write(".session_end", f"{start} {end} {rc}\n")
        with open(os.path.join(self.base, ".playtime"), "a", encoding="utf-8") as f:
            f.write(f"{start} {end}\n")
        self.write("launch.log", "\n".join(lines + [f"Dumping logcat to {self.dump}", "Exited!"]) + "\n")
        if crash is not None:
            self.write("logcat-crash.log", "\r\n".join(crash) + "\r\n", base=self.dump)
        return start, end


class TestLauncherRecord(unittest.TestCase):
    def test_launcher_records_the_end_and_keeps_lepton_logs(self):
        body = LAUNCH_SCRIPT_TEMPLATE.split("stop() {{", 1)[1]
        # The exit status is gone after the first command, so it is taken first.
        self.assertEqual(body.strip().split(";", 1)[0], "local rc=$?")
        self.assertIn('"$started" "$ended" "$rc" > "$app_dir/.session_end"', body)
        self.assertIn("printf '%s %s\\n' \"$started\" \"$ended\" >> \"$app_dir/.playtime\"", body)  # still two fields
        self.assertIn("export LEPTON_DUMP_LOGCAT=1", LAUNCH_SCRIPT_TEMPLATE)
        self.assertIn('fail "Lepton runtime not found on this system."', LAUNCH_SCRIPT_TEMPLATE)
        self.assertGreaterEqual(migrate.LAYOUT_VERSION, 7)  # existing games get the new launcher (AGENTS.md 4a.15)


@unittest.skipIf(os.name == "nt" or not all(shutil.which(t) for t in ("bash", "flock", "setsid")),
                 "launch.sh runs on Linux")
class TestLauncherScript(unittest.TestCase):
    """Runs a real launch.sh with a stand-in Lepton and podman."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.base = os.path.join(self.tmp, "game")
        os.makedirs(os.path.join(self.base, "lepton-app"))
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(stubs)
        self.lepton = os.path.join(self.tmp, "lepton")
        scripts = {
            os.path.join(stubs, "podman"): "#!/bin/sh\nexit 0\n",
            self.lepton: "#!/bin/bash\necho \"Lepton fake (rootfs 1) starting up dump=$LEPTON_DUMP_LOGCAT\"\n"
                         "if [[ $FAKE_LEPTON == sleep ]]; then exec sleep 30; fi\nexit \"$FAKE_LEPTON\"\n",
        }
        for path, text in scripts.items():
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.chmod(path, 0o755)
        self.env = dict(os.environ, HOME=self.tmp, FRAMELOAD_DETACHED="1",
                        PATH=stubs + os.pathsep + os.environ.get("PATH", ""))

    def launch(self, mode, lepton=None, terminate=False):
        with patch.object(lepton_quest, "lepton_status", return_value={"path": lepton or self.lepton}):
            script = LeptonInstaller.write_launcher(self.base, self.base, "com.t", "T", 99)
        for name in ("launch.log", ".session_end"):  # left by the previous start
            if os.path.exists(os.path.join(self.base, name)):
                os.remove(os.path.join(self.base, name))
        proc = subprocess.Popen(["bash", script], env=dict(self.env, FAKE_LEPTON=mode), start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if terminate:
            log = os.path.join(self.base, "launch.log")
            deadline = time.time() + 20
            while time.time() < deadline and "starting up" not in (open(log).read() if os.path.exists(log) else ""):
                time.sleep(0.1)
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)
        return proc.returncode

    def ended(self):
        with open(os.path.join(self.base, ".session_end"), encoding="utf-8") as f:
            start, end, rc = f.read().split()
        self.assertLessEqual(int(start), int(end))
        return int(rc)

    def test_the_exit_status_is_recorded(self):
        self.assertEqual(self.launch("0"), 0)
        self.assertEqual(self.ended(), 0)
        with open(os.path.join(self.base, "launch.log"), encoding="utf-8") as f:
            self.assertIn("dump=1", f.read())  # Lepton was asked to keep its logs
        self.assertEqual(self.launch("3"), 3)
        self.assertEqual(self.ended(), 3)
        self.assertEqual(self.launch("sleep", terminate=True), 143)  # Steam's Exit game
        self.assertEqual(self.ended(), 143)
        with open(os.path.join(self.base, ".playtime"), encoding="utf-8") as f:
            self.assertTrue(all(len(line.split()) == 2 for line in f))

    def test_a_missing_lepton_leaves_the_reason(self):
        self.assertEqual(self.launch("0", lepton=os.path.join(self.tmp, "nowhere")), 1)
        with open(os.path.join(self.base, ".launch_error"), encoding="utf-8") as f:
            self.assertIn("Lepton runtime not found", f.read())
        self.assertFalse(os.path.exists(os.path.join(self.base, ".session_end")))
        self.launch("0")  # a start that works removes it
        self.assertFalse(os.path.exists(os.path.join(self.base, ".launch_error")))


class TestClassify(unittest.TestCase):
    def outcome(self, lines, **kw):
        kw.setdefault("start", 1000)
        kw.setdefault("end", 1300)
        return sessions.classify(PKG, "Test Game", lines, **kw)

    def test_a_native_crash_names_the_thread_and_the_graphics_driver(self):
        res = self.outcome([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE, end=1080)
        self.assertEqual(res["outcome"], "crashed")
        self.assertTrue(res["popup"])
        self.assertEqual(res["headline"], "Test Game crashed")
        self.assertEqual((res["signal"], res["thread"], res["library"]), ("SIGSEGV", "RenderThread", "libgallium_dri.so"))
        self.assertIn("graphics driver", res["cause"])
        self.assertIn("1 min 20 s after it started", res["cause"])
        self.assertIn(NATIVE_CRASH, res["evidence"])
        self.assertTrue(any("libgallium_dri.so" in ln for ln in res["evidence"]))

    def test_a_java_crash_names_the_exception(self):
        lines = [START_PROC] + [lc(3, 1234, "E", "AndroidRuntime", m) for m in (
            "FATAL EXCEPTION: main", f"Process: {PKG}, PID: 1234", "java.lang.IllegalStateException: no headset",
            "\tat com.test.Main.onCreate(Main.java:12)", "Caused by: java.lang.NullPointerException: x", "\t... 5 more")]
        res = self.outcome(lines)
        self.assertEqual(res["outcome"], "crashed")
        self.assertIn("java.lang.IllegalStateException", res["cause"])
        self.assertTrue(res["evidence"][-1].endswith("Caused by: java.lang.NullPointerException: x"))

    def test_a_lost_graphics_device_is_a_gpu_hang(self):
        lines = [START_PROC, PACING, lc(40, 1234, "E", "MESA", "error: ZINK: vkQueueSubmit failed (VK_ERROR_DEVICE_LOST)"),
                 lc(41, 1234, "F", "libc", f"Fatal signal 6 (SIGABRT), code -1 in tid 1234 (main), pid 1234 ({PKG})")]
        res = self.outcome(lines)
        self.assertEqual(res["outcome"], "gpu_hang")
        self.assertEqual(res["headline"], "Test Game stopped: the graphics processor hung")
        kernel = ["1790000100.1 kernel: msm_dpu: [drm:a6xx_hangcheck] hangcheck detected gpu lockup rb 0"]
        self.assertEqual(self.outcome([START_PROC, PACING], kernel=kernel)["outcome"], "gpu_hang")
        chatter = ["1790000100.1 kernel: kgsl kgsl-3d0: adreno_start: GPU clock set to 680 MHz"]
        self.assertEqual(self.outcome([START_PROC, PACING], kernel=chatter)["outcome"], "quit")

    def test_stops_are_told_by_their_markers(self):
        res = self.outcome([START_PROC, PACING], marker={"by": "player", "time": 1290})
        self.assertEqual((res["outcome"], res["popup"]), ("stopped_player", False))
        marker = {"by": "guard", "kind": "memory", "time": 1290,
                  "message": "The headset was about to freeze: the headset ran out of memory."}
        res = self.outcome([START_PROC, PACING, NATIVE_CRASH], marker=marker)  # whatever the log says after a kill
        self.assertEqual((res["outcome"], res["popup"]), ("guard_memory", True))
        self.assertIn("the headset ran out of memory", res["cause"])
        marker.update(kind="frozen", message="Its picture had not changed for 31 s.")
        self.assertEqual(self.outcome([START_PROC], marker=marker)["headline"], "Test Game froze and was stopped")
        old = {"by": "player", "time": 500}  # from an earlier session
        self.assertNotEqual(self.outcome([START_PROC, PACING], marker=old)["outcome"], "stopped_player")

    def test_steams_exit_is_not_a_crash(self):
        self.assertEqual(self.outcome([START_PROC, PACING], rc=143)["outcome"], "closed_by_steam")
        res = self.outcome([START_PROC, PACING, "Signal SIGTERM received, killing container..."])
        self.assertEqual((res["outcome"], res["popup"]), ("closed_by_steam", False))

    def test_a_game_lepton_could_not_start(self):
        res = self.outcome(["ERROR: APP_ACTIVITY is empty, check APK metadata?", "Early-exit"], rc=1, end=1004)
        self.assertEqual(res["outcome"], "start_failed")
        self.assertEqual(res["headline"], "Test Game could not start")
        self.assertEqual(res["cause"], "The APK has no launcher activity")
        self.assertIn("LAUNCHER", res["advice"])

    def test_a_vr_game_that_ends_within_seconds_without_a_picture(self):
        res = self.outcome([START_PROC, "Exited!"], end=1008)
        self.assertEqual((res["outcome"], res["popup"]), ("closed_early", True))
        self.assertIn("8 s after it started", res["cause"])
        self.assertEqual(self.outcome([START_PROC, PACING], end=1008)["outcome"], "quit")  # it drew
        self.assertEqual(self.outcome([START_PROC], end=1030, is_vr=False)["outcome"], "quit")  # 2D, 30 s

    def test_a_crash_while_quitting_is_a_normal_end(self):
        lines = [START_PROC, PACING, lc(100, 1234, "I", "Unity", "System.exit called, status: 0"),
                 lc(102, 1234, "F", "libc", f"Fatal signal 11 (SIGSEGV), code 1 in tid 1250 (UnityMain), pid 1234 ({PKG})")]
        res = self.outcome(lines)
        self.assertEqual((res["outcome"], res["popup"]), ("quit", False))
        self.assertEqual(res["quit_note"], "it crashed while closing")

    def test_another_process_crashing_is_not_the_games_crash(self):
        other = lc(50, 1500, "F", "libc", "Fatal signal 6 (SIGABRT), code -1 in tid 1501 (binder), pid 1500 (android.hardware.x)")
        unnamed = lc(51, 1600, "F", "libc", "Fatal signal 11 (SIGSEGV), code 1, fault addr 0x0")
        # An unfiltered mirror (Start proc lines present), and logcat's crash buffer, which is never filtered.
        res = self.outcome([START_PROC, PACING, other, unnamed], crash=[other, unnamed])
        self.assertEqual(res["outcome"], "quit")
        self.assertEqual(self.outcome([START_PROC, PACING], crash=[NATIVE_CRASH])["outcome"], "crashed")

    def test_the_kernel_ending_the_game_for_memory(self):
        kernel = [f"1790000100.2 kernel: Out of memory: Killed process 4321 ({PKG[-15:]}) total-vm:9000000kB",
                  "1790000100.3 kernel: Out of memory: Killed process 99 (chrome) total-vm:1kB"]
        res = self.outcome([START_PROC, PACING], kernel=kernel)
        self.assertEqual(res["outcome"], "out_of_memory")
        self.assertEqual(res["evidence"], kernel[:1])
        self.assertEqual(self.outcome([START_PROC, PACING], kernel=kernel[1:])["outcome"], "quit")


class TestRecords(SessionCase):
    def test_evidence_is_kept_when_the_next_start_erases_it(self):
        start, end = self.session(["Lepton 3.0.5 (rootfs 2026.09.1) starting up at Wed Oct 15", "\x1b[31m" + START_PROC + "\x1b[0m",
                                   PACING, NATIVE_CRASH], crash=TOMBSTONE)
        record = sessions.finalize(PKG, guard_state={"fps": 72.0, "last_frame_age": 3, "drew": True})
        self.assertEqual(record["outcome"], "crashed")
        self.assertEqual((record["start"], record["end"], record["rc"]), (start, end, 0))
        self.assertEqual(record["lepton"], "3.0.5 (rootfs 2026.09.1)")
        self.assertTrue(record["sources"]["crash_log"])
        kept = os.path.join(sessions.SESSION_DIR, PKG)
        with open(os.path.join(kept, "logcat-crash.log"), encoding="utf-8", newline="") as f:
            self.assertNotIn("\r", f.read())  # Lepton's dump runs podman exec -it
        shown = sessions.detail(PKG)
        self.assertNotIn("\x1b", "\n".join(shown["lines"]))

        # The player starts the game again: launch.log is truncated and Lepton deletes its dump.
        self.write("launch.log", "Lepton 3.0.5 (rootfs 2026.09.1) starting up\n")
        self.write(".last_played", f"{end + 60}\n")
        shutil.rmtree(self.dump)
        self.assertEqual(sessions.detail(PKG)["lines"], shown["lines"])
        self.assertIn("libgallium_dri.so", sessions.report_text(PKG))
        self.assertIsNone(sessions.finalize(PKG))  # recorded once

    def test_a_gpu_hang_turns_foveated_rendering_off_once(self):
        from frameload.manager.tuning import TuningManager
        hang = lc(40, 1234, "E", "MESA", "error: ZINK: vkQueueSubmit failed (VK_ERROR_DEVICE_LOST)")
        self.session([START_PROC, PACING, hang])
        with patch.object(TuningManager, "effective_settings", return_value={"foveation": "gaze"}), \
                patch.object(TuningManager, "save_game_tuning") as save:
            record = sessions.finalize(PKG)
        self.assertEqual(record["outcome"], "gpu_hang")
        save.assert_called_once_with(PKG, {"foveation": "off"})
        self.assertEqual(record["auto_fix"], "foveation_off")
        self.assertIn("turned off Foveated rendering", record["advice"])

        # Already off (or a launcher FramePort wrote): nothing to change, the usual advice.
        self.session([START_PROC, PACING, hang], ago=5)
        with patch.object(TuningManager, "effective_settings", return_value={"foveation": "off"}), \
                patch.object(TuningManager, "save_game_tuning") as save:
            record = sessions.finalize(PKG)
        save.assert_not_called()
        self.assertEqual(record["auto_fix"], "")
        self.dep["installed_by"] = "frameport"
        self.assertFalse(sessions._foveation_off_after_hang(PKG, self.dep))

    def test_a_stopped_games_log_comes_from_the_copy_stop_took(self):
        start, end = self.session([START_PROC])
        snapshot = self.write(".stop_logcat.log", lc(9, 1234, "E", "SRCENG", "Unable to load gameinfo.txt") + "\n")
        os.utime(snapshot, (end, end))
        record = sessions.finalize(PKG)
        self.assertTrue(record["sources"]["main_log"])
        self.assertIn("Unable to load gameinfo.txt", sessions.report_text(PKG, full=True))

    def test_uninstalling_forgets_the_mute_too(self):
        _, end = self.session([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE)
        sessions.finalize(PKG)
        sessions.acknowledge(PKG, end, mute=True)
        sessions.forget(PKG)
        self.assertNotIn(PKG, sessions._muted())

    def test_sessions_ended_while_the_dialog_was_off_never_pop_up(self):
        self.session([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE)
        with patch.object(sessions, "_dialog_on", return_value=False):
            record = sessions.finalize(PKG)
        self.assertEqual(record["outcome"], "crashed")
        self.assertFalse(record["popup"])
        self.assertEqual(sessions.pending(), [])

    def test_a_newer_start_leaves_the_log_alone(self):
        start, end = self.session([START_PROC, PACING, NATIVE_CRASH])
        self.write(".last_played", f"{end + 30}\n")  # started again before FrameLoad looked
        self.assertIsNone(sessions.finalize(PKG))

    def test_alerts_until_dismissed_muted_or_old(self):
        self.assertEqual(sessions.pending(), [])
        _, end = self.session([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE)
        sessions.finalize(PKG)
        alerts = sessions.pending()
        self.assertEqual([(a["package"], a["outcome"]) for a in alerts], [(PKG, "crashed")])
        self.assertEqual(sessions.pending(now=end + 3 * 86400 + 1), [])  # three days later nobody is asked
        self.assertTrue(sessions.acknowledge(PKG, end))
        self.assertEqual(sessions.pending(), [])
        self.assertTrue(sessions.summary(PKG)["abnormal"])  # its page still has What Happened

        sessions.acknowledge(PKG, mute=True)  # Don't Show for This Game
        self.session([START_PROC, PACING, NATIVE_CRASH], ago=5)
        self.assertEqual(sessions.finalize(PKG)["outcome"], "crashed")
        self.assertEqual(sessions.pending(), [])
        self.assertTrue(sessions.load(PKG)["muted"])
        sessions.acknowledge(PKG, mute=False)
        self.assertEqual(len(sessions.pending()), 1)

        _, end = self.session([START_PROC, PACING], ago=1)  # a normal end replaces it, without a dialog
        self.assertEqual(sessions.finalize(PKG)["outcome"], "quit")
        self.assertEqual(sessions.pending(), [])
        self.assertFalse(sessions.summary(PKG)["abnormal"])

    def test_a_player_stop_keeps_a_fresh_guard_marker(self):
        sessions.mark_stop(PKG, "guard", "frozen", "Its picture had not changed for 30 s.")
        self.assertFalse(sessions.mark_stop(PKG, "player"))  # the guard's own call to Stop
        with open(os.path.join(sessions.SESSION_DIR, f"{PKG}.stop.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["by"], "guard")
        self.assertTrue(sessions.mark_stop(PKG, "player", now=time.time() + 20))  # later: the player's own

    def test_stop_notes_who_stopped_the_game(self):
        running = {"lepton-steamlaunch-4242"}

        def fake_run(cmd, **kwargs):
            result = type("R", (), {"stdout": "", "returncode": 0})()
            if cmd[:2] == ["podman", "ps"]:
                result.stdout = "\n".join(running)
            elif cmd[:2] == ["podman", "kill"]:
                running.discard(cmd[2])
            return result

        with patch("subprocess.run", side_effect=fake_run), patch("time.sleep"):
            self.assertTrue(GameLauncher.stop(PKG)["stopped"])
        with open(os.path.join(sessions.SESSION_DIR, f"{PKG}.stop.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["by"], "player")
        start, end = self.session([START_PROC, PACING, NATIVE_CRASH], ago=0)
        record = sessions.finalize(PKG)
        self.assertEqual((record["outcome"], record["popup"]), ("stopped_player", False))
        self.assertFalse(os.path.exists(os.path.join(sessions.SESSION_DIR, f"{PKG}.stop.json")))  # used up

    def test_a_restart_in_the_middle_of_a_game(self):
        start, end = self.session([START_PROC, PACING])
        sessions.finalize(PKG)
        self.write(".last_played", f"{end + 100}\n")  # started again, and then the headset rebooted
        self.write("launch.log", START_PROC + "\n" + PACING + "\n")
        self.kernel = ["1790000100.1 kernel: msm_dpu: hangcheck detected gpu lockup"]
        self.assertIsNone(sessions.record_interrupted(PKG, boot=end + 50))  # booted before it started
        record = sessions.record_interrupted(PKG, boot=end + 400)
        self.assertEqual(record["outcome"], "interrupted")
        self.assertEqual(record["headline"], "Test Game was running when the headset restarted")
        self.assertIn("graphics processor hung", record["cause"])
        self.assertTrue(record["popup"])
        self.assertIsNone(sessions.record_interrupted(PKG, boot=end + 400))  # once

    def test_a_launcher_that_could_not_start_lepton(self):
        self.write(".launch_error", "Lepton runtime not found on this system.\n")
        record = sessions.finalize(PKG)
        self.assertEqual(record["outcome"], "start_failed")
        self.assertEqual(record["cause"], "Lepton runtime not found on this system.")
        self.assertIn("self-test under System", record["advice"])

    def test_sessions_from_before_frameload_kept_records_are_recorded_as_seen(self):
        shutil.rmtree(sessions.SESSION_DIR)  # the first start of a FrameLoad that keeps records
        self.session([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE)
        made = sessions.catch_up([{"package": PKG}], live=set())
        self.assertEqual(made[0]["outcome"], "crashed")
        self.assertEqual(sessions.pending(), [])  # an update does not greet the player with an old crash
        self.assertTrue(sessions.summary(PKG)["abnormal"])  # but its page has What Happened

        self.records_since(time.time() - 5)
        self.session([START_PROC, PACING, NATIVE_CRASH], ago=2)  # ended while FrameLoad was not running
        self.assertEqual(sessions.catch_up([{"package": PKG}], live={PKG}), [])  # a running game is left alone
        sessions.catch_up([{"package": PKG}], live=set())
        self.assertEqual(len(sessions.pending()), 1)

    def test_report_for_copying(self):
        home = sessions.HOME
        noise = "\n".join(f"12:00:{i % 60:02d} line {i} " + "x" * 90 for i in range(100000))  # about 10 MB
        self.session(["Lepton 3.0.5 (rootfs 2026.09.1) starting up", START_PROC, PACING,
                      f"\x1b[32mloading {home}/Applications/quest-frame/{PKG}/lepton-app/game.apk\x1b[0m",
                      "connected to 192.168.1.23:5050, mac aa:bb:cc:dd:ee:ff, steam 76561198012345678",
                      noise, NATIVE_CRASH], crash=TOMBSTONE)
        sessions.finalize(PKG)
        text = sessions.report_text(PKG)
        self.assertLessEqual(len(text), sessions.COPY_MAX_CHARS)
        for part in ("FrameLoad session report", f"FrameLoad {__version__}", "Test Game", PKG, "Ported with FramePort",
                     "Lepton: 3.0.5 (rootfs 2026.09.1)", "Test Game crashed", "libgallium_dri.so", "Crash backtrace:"):
            self.assertIn(part, text)
        full = sessions.report_text(PKG, full=True)
        self.assertGreater(len(full), sessions.COPY_MAX_CHARS)
        self.assertIn("~/Applications/quest-frame", full)
        for secret in (home + os.sep + "Applications", home + "/Applications", "192.168.1.23", "aa:bb:cc:dd:ee:ff",
                       "76561198012345678", "\x1b"):
            self.assertNotIn(secret, full)
            self.assertNotIn(secret, text)

    def test_report_of_the_current_log(self):
        self.write("launch.log", "Lepton 3.0.5 (rootfs 1) starting up\nApp installation failed!\n")
        text = sessions.report_text(PKG, source="live")
        self.assertIn("no finished session recorded", text)
        self.assertIn("Android refused to install the APK", text)
        self.assertIn("App installation failed!", text)


class TestSessionRoutes(SessionCase):
    def setUp(self):
        super().setUp()
        self.local = True
        for p in (patch.object(FrameLoadApiHandler, "client_is_local", side_effect=lambda: self.local),
                  patch.object(access, "PAIRED_FILE", os.path.join(self.tmp, "paired.json")),
                  patch("frameload.server.get_system_summary", return_value={}),
                  patch.object(sessions, "HOME", self.tmp)):
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        _, self.end = self.session([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE)
        sessions.finalize(PKG)

    def request(self, method, path, body=None, cookie=""):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Cookie": cookie} if cookie else {}
            if payload is not None:
                headers["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def test_dialog_routes(self):
        status, _, body = self.request("GET", "/api/system")
        self.assertEqual(status, 200)
        info = json.loads(body)
        self.assertTrue(info["session_dialog"])
        self.assertEqual([a["package"] for a in info["session_alerts"]], [PKG])

        self.assertEqual(self.request("GET", "/api/sessions/bad..pkg")[0], 400)
        self.assertEqual(self.request("GET", "/api/sessions/com.not.installed")[0], 404)
        status, _, body = self.request("GET", f"/api/sessions/{PKG}")
        detail = json.loads(body)
        self.assertEqual((status, detail["record"]["outcome"], detail["client_local"]), (200, "crashed", True))
        self.assertIn("Test Game crashed", detail["copy_text"])
        self.assertTrue(detail["excerpt"])
        live = json.loads(self.request("GET", f"/api/sessions/{PKG}?source=live")[2])
        self.assertFalse(live["session"])

        status, headers, body = self.request("GET", f"/api/sessions/{PKG}/report.txt")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertRegex(headers["Content-Disposition"], rf'^attachment; filename="frameload-{PKG}-\d{{8}}-\d{{6}}\.txt"$')
        self.assertEqual((headers["Cache-Control"], headers["X-Content-Type-Options"]), ("no-store", "nosniff"))
        self.assertIn(b"FrameLoad session report", body)

        status, _, body = self.request("POST", "/api/sessions/save", {"package": PKG})
        saved = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(os.path.dirname(saved["path"]), os.path.join(self.tmp, "Downloads"))
        self.assertTrue(os.path.isfile(saved["path"]))

        self.assertEqual(self.request("POST", "/api/sessions/seen", {"package": PKG, "end": "soon"})[0], 200)
        self.assertEqual(len(json.loads(self.request("GET", "/api/system")[2])["session_alerts"]), 1)  # not that one
        self.assertEqual(self.request("POST", "/api/sessions/seen", {"package": PKG, "end": self.end})[0], 200)
        self.assertEqual(json.loads(self.request("GET", "/api/system")[2])["session_alerts"], [])

    def test_other_devices(self):
        self.local = False
        self.assertEqual(self.request("GET", f"/api/sessions/{PKG}")[0], 401)
        self.assertEqual(self.request("GET", f"/api/sessions/{PKG}/report.txt")[0], 401)
        self.assertEqual(self.request("POST", "/api/sessions/seen", {"package": PKG})[0], 401)
        token = access.redeem(access.new_code()["code"], "Phone")
        cookie = f"{access.COOKIE_NAME}={token}"
        status, _, body = self.request("GET", f"/api/sessions/{PKG}", cookie=cookie)
        self.assertFalse(json.loads(body)["client_local"])  # the phone downloads report.txt instead
        self.assertEqual(self.request("GET", f"/api/sessions/{PKG}/report.txt", cookie=cookie)[0], 200)
        self.assertEqual(self.request("POST", "/api/sessions/save", {"package": PKG}, cookie=cookie)[0], 403)


if __name__ == "__main__":
    unittest.main()
