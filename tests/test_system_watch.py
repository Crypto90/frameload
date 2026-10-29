"""CPU/memory readings, keeping the headset awake, and the freeze guard."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from collections import deque
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from frameload.manager import guard
from frameload.manager.guard import FreezeGuard
from frameload.system import perf, power

MEMINFO = """MemTotal:       16000000 kB
MemFree:          500000 kB
MemAvailable:    8000000 kB
SwapTotal:       4000000 kB
SwapFree:        3000000 kB
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


class TestPerf(Case):
    def test_cpu_memory_pressure_temperatures_and_gpu(self):
        proc, sys_root = os.path.join(self.tmp, "proc"), os.path.join(self.tmp, "sys")
        self.write("proc/stat", "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3 4\n")
        self.write("proc/meminfo", MEMINFO)
        self.write("proc/pressure/memory", "some avg10=12.50 avg60=3.00 avg300=1.00 total=1\n"
                                           "full avg10=4.25 avg60=1.00 avg300=0.50 total=1\n")
        for i, (kind, milli) in enumerate([("cpu-0-0-0", "41000"), ("cpu-1-2-0", "57500"), ("gpuss-0", "48000"),
                                           ("ddr", "39000"), ("max1720x", "31000"), ("pm8550_tz", "45000")]):
            self.write(f"sys/class/thermal/thermal_zone{i}/type", kind + "\n")
            self.write(f"sys/class/thermal/thermal_zone{i}/temp", milli + "\n")
        self.write("sys/class/devfreq/3d00000.gpu/cur_freq", "680000000\n")
        self.write("sys/class/devfreq/3d00000.gpu/max_freq", "1100000000\n")

        with patch.object(perf, "_cpu_prev", None), patch.object(perf, "time") as clock:
            clock.time.side_effect = [1000.0, 1000.0, 1000.2, 1001.0, 1001.0]
            self.assertEqual(perf.cpu_percent(proc), 0.0)  # the first call measures a quiet 0.2 s
            self.write("proc/stat", "cpu  250 0 150 900 0 0 0 0 0 0\n")  # 200 busy of 300 more
            self.assertAlmostEqual(perf.cpu_percent(proc), 66.7)

        mem = perf.memory(proc)
        self.assertEqual(mem["total"], 16000000 * 1024)
        self.assertEqual(mem["used"], 8000000 * 1024)
        self.assertEqual(mem["swap_used"], 1000000 * 1024)
        self.assertEqual(perf.memory_pressure(proc), {"some": 12.5, "full": 4.25})
        self.assertEqual(perf.temperatures(sys_root), {"cpu": 57.5, "gpu": 48.0, "memory": 39.0, "battery": 31.0})
        self.assertEqual(perf.gpu(sys_root), {"mhz": 680, "max_mhz": 1100})

    def test_missing_sources_give_nothing(self):
        empty = os.path.join(self.tmp, "nothing")
        self.assertIsNone(perf.cpu_percent(empty))
        self.assertIsNone(perf.memory(empty))
        self.assertIsNone(perf.memory_pressure(empty))
        self.assertEqual(perf.temperatures(empty), {})
        self.assertEqual(perf.gpu(empty), {})


class FakeInhibitor:
    started = []

    def __init__(self, args, **kwargs):
        FakeInhibitor.started.append(args)
        self.args, self.running = args, True
        self.stdin = self

    def poll(self):
        return None if self.running else 0

    def close(self):  # stdin closed: cat ends
        self.running = False

    def wait(self, timeout=None):
        return 0


class TestKeepAwake(unittest.TestCase):
    def setUp(self):
        FakeInhibitor.started = []
        power.KeepAwake._proc, power.KeepAwake._reason, power.KeepAwake.manual_until = None, "", 0.0
        self.addCleanup(power.KeepAwake._release)

    def test_held_while_busy_and_released_after(self):
        with patch.object(power.shutil, "which", return_value="/usr/bin/systemd-inhibit"), \
                patch.object(power.subprocess, "Popen", FakeInhibitor):
            power.KeepAwake.update("Downloading Beat Saber")
            power.KeepAwake.update("Installing Beat Saber")  # the same inhibitor carries on
            self.assertEqual(len(FakeInhibitor.started), 1)
            args = FakeInhibitor.started[0]
            self.assertEqual(args[:2], ["systemd-inhibit", "--what=sleep:idle"])
            self.assertEqual(args[-1], "cat")  # ends with FrameLoad's server, as its input closes
            self.assertEqual(power.KeepAwake.status()["reason"], "Installing Beat Saber")
            power.KeepAwake.update("")
            self.assertFalse(power.KeepAwake.status()["held"])

            power.KeepAwake.set_manual(-1)  # until switched off
            power.KeepAwake.update("")
            status = power.KeepAwake.status()
            self.assertTrue(status["held"] and status["manual"])
            self.assertIsNone(status["manual_until"])
            power.KeepAwake.set_manual(0)
            power.KeepAwake.update("")
            self.assertFalse(power.KeepAwake.status()["held"])

    def test_without_systemd_inhibit_nothing_is_held(self):
        with patch.object(power.shutil, "which", return_value=None):
            power.KeepAwake.update("Downloading")
            self.assertFalse(power.KeepAwake.status()["held"])
            self.assertFalse(power.KeepAwake.status()["available"])

    def test_work_inside_a_request_counts_until_it_ends(self):
        from frameload.installer import porting
        with patch.object(porting.PortingJobs, "active_id", return_value=""):
            self.assertEqual(power.busy_reason(), "")
            with power.busy("Installing Moss"):
                self.assertEqual(power.busy_reason(), "Installing Moss")
            self.assertEqual(power.busy_reason(), "")
            with self.assertRaises(OSError), power.busy("Installing Moss"):
                raise OSError("disk full")
            self.assertEqual(power.busy_reason(), "")


class TestLocalInstallKeepsAwake(unittest.TestCase):
    """Installing a file from the Install File tab or from a phone runs inside the request."""

    def setUp(self):
        from frameload.catalog.downloader import Downloader
        from frameload.installer import porting
        from frameload.server import FrameLoadApiHandler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        fd, self.apk = tempfile.mkstemp(suffix=".apk")
        os.close(fd)
        self.addCleanup(os.remove, self.apk)
        self.update = MagicMock()
        for p in (patch.object(porting.PortingJobs, "active_id", return_value=""),
                  patch.object(Downloader.get(), "get_all_tasks", return_value=[]),
                  patch.object(porting, "auto_port", return_value={"needed": False}),
                  patch("frameload.server.steam_session.status", return_value={}),
                  patch.object(power.KeepAwake, "update", self.update)):
            p.start()
            self.addCleanup(p.stop)

    def install(self, install_source):
        with patch("frameload.server.PackageLoader.install_source", side_effect=install_source):
            conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
            try:
                conn.request("POST", "/api/local/install", body=json.dumps({"source_path": self.apk, "title": "Moss"}),
                             headers={"Content-Type": "application/json"})
                return conn.getresponse().status
            finally:
                conn.close()

    def test_the_headset_stays_awake_while_installing_and_not_after(self):
        seen = []
        self.assertEqual(self.install(lambda **kw: seen.append(power.busy_reason()) or {"package": "com.moss"}), 200)
        self.assertEqual(seen, ["Installing Moss"])
        self.assertEqual(self.update.call_args_list[0].args, ("Installing Moss",))  # held right away
        self.assertEqual(power.busy_reason(), "")
        self.assertEqual(self.update.call_args_list[-1].args, ("",))  # and let go at the end

        def broken(**kw):
            raise OSError("disk full")
        self.update.reset_mock()
        self.assertEqual(self.install(broken), 500)
        self.assertEqual(power.busy_reason(), "")  # a failed install lets go too
        self.assertEqual(self.update.call_args_list[-1].args, ("",))


class TestGameGpuTime(Case):
    """A game's own GPU time, from the DRM fdinfo of its processes (what Freeze Guard judges games by
    when they have no FrameBridge, and what keeps a loading game from being stopped)."""

    def process(self, pid, comm, cmdline, fdinfo=None):
        self.write(f"proc/{pid}/comm", comm + "\n")
        self.write(f"proc/{pid}/cmdline", cmdline.replace(" ", "\0") + "\0")
        for fd, text in (fdinfo or {}).items():
            self.write(f"proc/{pid}/fdinfo/{fd}", text)

    def test_finds_the_apps_processes_and_their_gpu_time(self):
        proc = os.path.join(self.tmp, "proc")
        drm = "pos:\t0\nflags:\t02\ndrm-driver:\tmsm\ndrm-client-id:\t{id}\ndrm-engine-gpu:\t{ns} ns\n"
        # The kernel keeps 15 characters of a process name (".intotheblue.vr"); cmdline has all of it.
        pkg = "com.intotheblue.vr"
        self.process(321, pkg[-15:], pkg, {
            "3": "pos:\t0\nflags:\t0100002\n",            # an ordinary file
            "7": drm.format(id=11, ns=4_000_000_000),
            "8": drm.format(id=11, ns=4_000_000_000),     # the same device duplicated: counted once
            "9": drm.format(id=12, ns=1_000_000_000)})
        self.process(322, pkg[-15:], pkg + ":service", {"4": drm.format(id=20, ns=500)})
        self.process(400, pkg[-15:], "com.other.intotheblue.vr")  # the same short name, another app
        self.process(401, "bash", "bash -c x")
        self.assertEqual(perf.app_pids(pkg, proc), [321, 322])
        fds = {pid: perf.render_fds(pid, proc) for pid in perf.app_pids(pkg, proc)}
        self.assertEqual(fds, {321: ["7", "8", "9"], 322: ["4"]})
        self.assertEqual(perf.gpu_time_ns(fds, proc), 5_000_000_500)
        self.assertIsNone(perf.gpu_time_ns({321: ["3"]}, proc))  # nothing readable: no veto
        self.assertEqual(perf.app_pids(pkg, os.path.join(self.tmp, "nothing")), [])

    def test_an_unreal_game_with_a_renamed_main_thread_and_its_memory(self):
        proc = os.path.join(self.tmp, "proc")
        pkg = "co.yomune.gargantua"
        drm = ("drm-client-id:\t7\ndrm-engine-gpu:\t100 ns\ndrm-total-memory:\t2048 KiB\n"
               "drm-resident-memory:\t1024 KiB\n")
        self.process(1205, "MainThread-UE4", pkg, {"9": drm, "10": drm})  # Unreal renames the main thread
        self.process(1300, "MainThread-UE4", "com.other.unreal.game")
        self.write("proc/1205/status", "Name:\tMainThread-UE4\nVmRSS:\t  3000 kB\n")
        self.assertEqual(perf.app_pids(pkg, proc), [1205])
        mem = perf.game_memory({1205: ["9", "10"]}, proc)
        self.assertEqual(mem, {"rss": 3000 * 1024, "gpu": 1024 * 1024, "render_maps": None})  # same client once
        self.write("proc/1205/maps", "7f00-7f10 rw-s 0 00:05 9 /dev/dri/renderD128\n7f10-7f20 rw-p 0 0 0 [heap]\n")
        self.assertEqual(perf.game_memory({1205: []}, proc)["render_maps"], 1)

    def test_a_render_device_found_later_gives_no_share_spike(self):
        # Red Matter on the headset: a second render device appeared with its earlier GPU time -> "1972 %".
        fds = {"now": {1: ["7"]}}
        totals = {("7",): 0, ("7", "9"): 0}
        clock = {"t": 0.0}
        session = {"gpu_samples": deque(maxlen=80)}
        with patch.object(perf, "app_pids", return_value=[1]), \
                patch.object(perf, "render_fds", side_effect=lambda pid, proc: fds["now"][pid]), \
                patch.object(perf, "gpu_time_ns", side_effect=lambda f, proc: totals[tuple(f[1])]), \
                patch.object(guard.os.path, "isdir", return_value=True):
            for step in range(1, 15):
                clock["t"] = step * 5.0
                totals[("7",)] += int(2.5e9)  # 50 % of 5 s
                totals[("7", "9")] = totals[("7",)] + int(90e9)  # fd 9 has been busy for a long time
                if step == 13:
                    fds["now"] = {1: ["7", "9"]}
                FreezeGuard._gpu({"package": "com.x"}, session, clock["t"], "/proc")
                if session.get("gpu") is not None:
                    self.assertLessEqual(session["gpu"], 1.0, step)
        self.assertAlmostEqual(session["gpu"], 0.5)

    def test_boot_time(self):
        self.write("proc/stat", "cpu  1 2 3 4\nbtime 1790000000\nprocesses 5\n")
        self.assertEqual(perf.boot_time(os.path.join(self.tmp, "proc")), 1790000000)
        self.assertIsNone(perf.boot_time(os.path.join(self.tmp, "nothing")))


class TestFreezeGuard(Case):
    def setUp(self):
        super().setUp()
        FreezeGuard.sessions, FreezeGuard._games, FreezeGuard._games_at = {}, [], 0.0
        FreezeGuard._psi, FreezeGuard._last_stop = deque(maxlen=10), 0.0
        FreezeGuard._last_tick = FreezeGuard._swept_at = 0.0
        FreezeGuard.events.clear()
        self.proc = os.path.join(self.tmp, "proc")
        self.write("proc/meminfo", MEMINFO)
        self.write("proc/pressure/memory", "some avg10=0.00\nfull avg10=0.00\n")
        self.games = []
        for pkg in ("com.game.a", "com.game.b"):
            base = os.path.join(self.tmp, pkg)
            self.write(f"{pkg}/.launch.lock", "")
            self.write(f"{pkg}/launch.log", "boot\n")
            self.games.append({"package": pkg, "title": pkg.upper(), "appid": 7, "base": base,
                               "vr": True, "framebridge": True})
        self.lock_game(0)
        self.stopped, self.limits, self.finalized = [], [], []
        self.stop_result = {"success": True}
        self.settings = dict(guard.DEFAULT_SETTINGS)
        self.hmd, self.dash, self.gpu = None, None, None  # unknown headset state, no answer from Steam, no GPU time
        patch.object(guard, "installed_games", return_value=self.games).start()
        patch.object(FreezeGuard, "settings", side_effect=lambda: dict(self.settings)).start()
        patch.object(guard, "apply_memory_limit", side_effect=lambda name, total: self.limits.append(name) or "").start()
        patch.object(guard, "hmd_state", side_effect=lambda: self.hmd).start()
        patch.object(guard, "dashboard_visible", side_effect=lambda: self.dash).start()
        patch.object(guard, "kernel_gpu_lines", return_value=[]).start()
        patch.object(guard.perf, "app_pids", side_effect=lambda pkg, proc: [4321] if self.gpu is not None else []).start()
        patch.object(guard.perf, "render_fds", return_value=["7"]).start()
        patch.object(guard.perf, "gpu_time_ns", side_effect=lambda fds, proc: None if self.gpu is None else int(self.gpu)).start()
        patch.object(guard.records, "SESSION_DIR", os.path.join(self.tmp, "sessions")).start()
        patch.object(guard.records, "finalize", side_effect=lambda pkg, state: self.finalized.append((pkg, state))).start()
        patch.object(guard.records, "sweep", return_value=[]).start()
        patch.object(FreezeGuard, "run_async", side_effect=lambda target, *a, **kw: target(*a, **kw)).start()
        self.addCleanup(patch.stopall)

    def lock_game(self, *indexes):
        lines = ["1: POSIX  ADVISORY  WRITE 99 00:1a:555 0 EOF"]
        for n, i in enumerate(indexes):
            inode = os.stat(os.path.join(self.games[i]["base"], ".launch.lock")).st_ino
            lines.append(f"{n + 2}: FLOCK  ADVISORY  WRITE 1234 fd:01:{inode} 0 EOF")
            lines.append(f"{n + 2}: -> FLOCK  ADVISORY  WRITE 1300 fd:01:{inode} 0 EOF")
        self.write("proc/locks", "\n".join(lines) + "\n")

    def stop(self, pkg):
        self.stopped.append(pkg)
        return self.stop_result

    def check(self, now):
        return FreezeGuard.check(now=now, stop=self.stop, proc=self.proc, wall=1_790_000_000 + now)

    def log(self, text, game=0):
        with open(os.path.join(self.games[game]["base"], "launch.log"), "a") as f:
            f.write(text)

    def ticks(self, start, end, step=2.0, gpu_share=None, at=None):
        """Ticks every `step` s from start to end (inclusive); returns {time: events} of ticks that recorded
        something. gpu_share: the GPU's busy share the game uses meanwhile. at: {time: callable} run first."""
        out, t = {}, start
        while t <= end + 1e-9:
            if at and t in at:
                at[t]()
            if gpu_share is not None:
                self.gpu = (self.gpu or 0) + gpu_share * step * 1e9
            events = self.check(t)
            if events:
                out[t] = events
            t += step
        return out

    def test_lock_holders_are_read_without_taking_a_lock(self):
        inode = os.stat(os.path.join(self.games[0]["base"], ".launch.lock")).st_ino
        self.assertEqual(guard.held_flock_inodes(self.proc), {inode})
        self.assertEqual([g["package"] for g in guard.running_games(self.games, self.proc)], ["com.game.a"])

    @unittest.skipIf(os.name == "nt", "flock and /proc/locks are Linux")
    def test_a_real_flock_is_seen(self):
        import fcntl
        path = os.path.join(self.tmp, "real.lock")
        with open(path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn(os.stat(path).st_ino, guard.held_flock_inodes("/proc"))

    def test_with_stopping_off_a_frozen_picture_is_reported_once(self):
        self.settings["stop_frozen"] = False
        self.ticks(1000, 1008)
        self.assertEqual(self.limits, ["lepton-steamlaunch-7"])  # once the container has had a moment
        self.log("FrameBridge: new layer: 0\nFrameBridge: pacing: 71.9 fps, displayTime vs predicted: avg 1.2 ms\n")
        self.check(1010)
        self.assertEqual(FreezeGuard.status(now=1010)["games"][0]["fps"], 71.9)
        events = self.ticks(1012, 1100)
        self.assertEqual(sorted(events), [1040])  # 30 s without a new picture, then never again
        self.assertEqual(events[1040][0]["kind"], "frozen")
        self.assertIn("press Stop", events[1040][0]["message"])
        self.assertFalse(events[1040][0]["stopped"])
        self.assertEqual(self.stopped, [])
        self.log("FrameBridge: pacing: 72.0 fps\n")  # drawing again: a new freeze is reported again
        self.assertEqual(sorted(self.ticks(1102, 1140)), [1132])

    def test_by_default_a_frozen_picture_is_stopped_after_30_s(self):
        self.assertTrue(self.settings["stop_frozen"])
        self.assertEqual(self.settings["frozen_seconds"], 30)
        self.ticks(1000, 1008)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1010, 1038)
        self.assertEqual(self.stopped, [])  # 28 s: not yet
        events = self.check(1040)
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertTrue(events[0]["stopped"])
        self.assertIn("was stopped: its picture had not changed for 30 s", events[0]["message"])
        with open(os.path.join(self.tmp, "sessions", "com.game.a.stop.json"), encoding="utf-8") as f:
            marker = json.load(f)
        self.assertEqual((marker["by"], marker["kind"]), ("guard", "frozen"))

    def test_a_game_podman_does_not_list_is_not_counted_as_stopped(self):
        self.stop_result = {"success": True, "stopped": False, "message": "It is not running."}
        self.ticks(1000, 1008)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        events = self.ticks(1010, 1040)
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertFalse(events[1040][0]["stopped"])
        self.assertIn("could not be stopped", events[1040][0]["message"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sessions", "com.game.a.stop.json")))  # no stop to explain

    def test_the_guards_own_stop_leaves_its_marker_alone(self):
        from frameload.manager.launcher import GameLauncher
        calls = []
        patch.object(GameLauncher, "stop", side_effect=lambda pkg, by="player": calls.append((pkg, by)) or
                     {"success": True, "stopped": True}).start()
        self.ticks(1000, 1008)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        for t in range(1010, 1041, 2):
            FreezeGuard.check(now=float(t), proc=self.proc, wall=1_790_000_000 + t)  # the default stop
        self.assertEqual(calls, [("com.game.a", "")])
        self.assertFalse(guard.records.mark_stop("com.game.a", ""))  # an empty "by" writes nothing

    def test_a_dead_log_copy_alone_never_stops_a_game(self):
        # Lepton stopped copying the game's log: the container still shows new pacing lines.
        seen = iter(range(1000))
        patch.object(guard, "container_pacing", side_effect=lambda appid: f"pacing: {next(seen)}".encode()).start()
        self.ticks(1000, 1008)
        self.log("FrameBridge: pacing: 72.0 fps\nlogcat: Unexpected EOF!\n")
        self.assertEqual(self.ticks(1010, 1200), {})
        self.assertEqual(self.stopped, [])

    def test_a_log_copy_that_never_shows_frames_is_read_in_the_container(self):
        # Lepton's copy ended after "Waiting for app" without a word (SWORDS of GARGANTUA ran at 72 fps unseen).
        seen = iter(range(1000))
        patch.object(guard, "container_pacing",
                     # `logcat -v brief`, as container_logcat() asks for it
                     side_effect=lambda appid: f"I/FrameBridge( 1212): pacing: 72.{next(seen) % 10} fps".encode()).start()
        self.log("Waiting for app com.game.a to exit...\n")
        self.ticks(1000, 1030)
        state = next(g for g in FreezeGuard.status(now=1030.0)["games"] if g["package"] == "com.game.a")
        self.assertEqual(state["state"], "drawing")
        self.assertAlmostEqual(state["fps"], 72, delta=1)
        self.assertEqual(self.ticks(1032, 1200), {})  # new pacing lines keep coming: never frozen
        self.assertEqual(self.stopped, [])

    def test_a_dead_log_copy_and_unknown_gpu_time_only_report(self):
        patch.object(guard, "container_pacing", return_value=None).start()  # the container cannot be asked
        self.ticks(1000, 1008)
        self.log("FrameBridge: pacing: 72.0 fps\nLogcat read failure\n")
        events = self.ticks(1010, 1060)
        self.assertEqual(self.stopped, [])
        self.assertIn("press Stop", events[1040][0]["message"])
        self.assertFalse(events[1040][0]["stopped"])

    def test_a_game_started_again_between_two_looks_starts_afresh(self):
        base = self.games[0]["base"]
        self.write("com.game.a/.last_played", "100\n")
        self.ticks(1000, 1008)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.check(1010)
        self.write("com.game.a/.last_played", "200\n")  # ended and started again before the next look
        self.write("com.game.a/launch.log", "boot\n")
        self.check(1012)
        self.assertEqual([pkg for pkg, _ in self.finalized], ["com.game.a"])
        self.assertTrue(self.finalized[0][1]["drew"])
        self.assertIsNone(FreezeGuard.sessions["com.game.a"].get("last_frame"))  # nothing drawn yet
        self.ticks(1014, 1100)
        self.assertEqual(self.stopped, [])  # still loading: not judged by the old session's last picture
        self.assertEqual(self.limits, ["lepton-steamlaunch-7", "lepton-steamlaunch-7"])  # the new container too
        self.assertTrue(os.path.isdir(base))

    def test_15_s_never_stops_a_game_that_reports_every_5_s(self):
        self.settings["frozen_seconds"] = 15
        pacing = {float(t): (lambda: self.log("FrameBridge: pacing: 72.0 fps\n")) for t in range(1000, 1121, 5)}
        events = {}
        for t in range(1000, 1121):  # pacing lines every 5 s, guard ticks every 2 s
            if t in pacing:
                pacing[t]()
            if t % 2 == 0:
                events.update({t: e for e in [self.check(float(t))] if e})
        self.assertEqual(events, {})
        last_line = 1120
        events = self.ticks(1122, 1150)
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertTrue(15 <= min(events) - last_line <= 17, min(events))

    def test_a_game_in_the_background_is_waited_for_up_to_2_minutes(self):
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.check(1002)
        self.log("FrameBridge: focus: lost (state 4)\n")
        self.ticks(1004, 1100)
        self.assertEqual(self.stopped, [])  # a minute and more in the background: not frozen
        self.assertEqual(FreezeGuard.status(now=1100)["games"][0]["paused"], "it is in the background")
        self.ticks(1102, 1124)
        self.assertEqual(self.stopped, [])
        self.ticks(1126, 1156)  # after 2 minutes a game that never came back is judged
        self.assertEqual(self.stopped, ["com.game.a"])

    def test_coming_back_from_the_background_starts_the_wait_again(self):
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\nFrameBridge: focus: lost (state 4)\n")
        self.ticks(1002, 1018)
        self.log("FrameBridge: focus: back after 16000 ms (lost to state 4)\n")
        self.ticks(1020, 1048)
        self.assertEqual(self.stopped, [])
        self.check(1050)
        self.assertEqual(self.stopped, ["com.game.a"])

    def test_an_asleep_headset_is_never_stopped(self):
        self.hmd = "Standby"
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1002, 1300)
        self.assertEqual(self.stopped, [])
        self.assertEqual(FreezeGuard.sessions["com.game.a"]["paused"], "the headset is asleep")
        self.hmd = "Active"  # back on: the full wait again
        events = self.ticks(1302, 1340)
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertTrue(1302 < min(events) <= 1332, min(events))

    def test_an_open_steam_menu_is_never_stopped(self):
        self.dash = True
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1002, 1400)
        self.assertEqual(self.stopped, [])
        self.assertEqual(FreezeGuard.sessions["com.game.a"]["paused"], "the Steam menu is open")

    def test_a_long_gap_between_ticks_is_not_a_freeze(self):
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1002, 1020)
        self.assertEqual(self.check(1120), [])  # 100 s without a tick: the headset slept
        self.ticks(1122, 1148)
        self.assertEqual(self.stopped, [])
        self.check(1150)
        self.assertEqual(self.stopped, ["com.game.a"])

    def test_a_large_backlog_is_skipped_to_its_newest_lines(self):
        self.ticks(1000, 1000)
        self.log(("x" * 1023 + "\n") * 3 * 1024 + "FrameBridge: pacing: 64.0 fps\n")  # 3 MiB of spam, then a frame
        self.check(1002)
        self.assertEqual(FreezeGuard.sessions["com.game.a"]["fps"], 64.0)
        self.assertEqual(FreezeGuard.sessions["com.game.a"]["last_frame"], 1002)

    def test_a_game_still_drawing_without_frame_reports_is_not_stopped(self):
        self.gpu = 0.0
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        events = self.ticks(1002, 1200, gpu_share=0.10)  # the logcat mirror ended, the game draws on
        self.assertEqual(self.stopped, [])
        infos = [e for evs in events.values() for e in evs]
        self.assertEqual([e["kind"] for e in infos], ["info"])  # said once
        self.assertIn("still drawing", infos[0]["message"])

    def test_a_game_whose_gpu_went_quiet_is_stopped(self):
        self.gpu = 0.0
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1002, 1040, gpu_share=0.0)
        self.assertEqual(self.stopped, ["com.game.a"])

    def test_a_game_not_found_yet_is_looked_for_every_10_s(self):
        # Finding a game's processes reads the name of every process on the headset.
        self.ticks(1000, 1030)
        self.assertEqual(guard.perf.app_pids.call_count, 4)

    def test_without_gpu_readings_the_frames_decide(self):
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1002, 1040)
        self.assertIsNone(FreezeGuard.sessions["com.game.a"].get("gpu"))
        self.assertEqual(self.stopped, ["com.game.a"])

    def test_a_stop_that_failed_says_so(self):
        self.stop_result = {"success": False, "error": "The game's container could not be stopped."}
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        events = [e for evs in self.ticks(1002, 1040).values() for e in evs]
        self.assertIn("could not be stopped", events[0]["message"])
        self.assertFalse(events[0]["stopped"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sessions", "com.game.a.stop.json")))

    def test_2d_apps_are_never_judged(self):
        self.games[0]["vr"] = False
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.assertEqual(self.ticks(1002, 1300), {})
        self.assertEqual(self.stopped, [])

    def test_vr_games_without_framebridge_are_judged_by_their_gpu_time(self):
        self.games[0]["framebridge"] = False
        self.gpu = 0.0
        self.ticks(1000, 1010, gpu_share=0.02)  # loading, little drawing: not armed yet
        self.ticks(1012, 1020, gpu_share=0.30)  # three ticks and more of real drawing
        self.assertTrue(FreezeGuard.sessions["com.game.a"]["gpu_drawing"])
        # Frozen, but the headset's state is unknown: told, not stopped.
        events = self.ticks(1022, 1060, gpu_share=0.0)
        self.assertEqual(self.stopped, [])
        message = [e for evs in events.values() for e in evs][0]["message"]
        self.assertIn("has not drawn anything", message)
        self.assertIn("could not confirm", message)

        self.ticks(1062, 1070, gpu_share=0.30)  # drawing again
        self.hmd, self.dash = "Active", False  # in use, no Steam menu: sure enough to stop it
        self.ticks(1072, 1110, gpu_share=0.005)
        self.assertEqual(self.stopped, ["com.game.a"])

    def test_memory_exhaustion_stops_the_game_and_leaves_the_guards_marker_first(self):
        markers = []

        def stop(pkg):
            with open(os.path.join(self.tmp, "sessions", f"{pkg}.stop.json"), encoding="utf-8") as f:
                markers.append(json.load(f))
            self.stopped.append(pkg)
            return {"success": True}

        self.check(1000)
        self.write("proc/pressure/memory", "some avg10=80.00\nfull avg10=35.00\n")
        self.assertEqual(FreezeGuard.check(now=1002, stop=stop, proc=self.proc), [])
        self.assertEqual(FreezeGuard.check(now=1004, stop=stop, proc=self.proc), [])
        events = FreezeGuard.check(now=1006, stop=stop, proc=self.proc)  # third sample in a row above the limit
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertEqual((markers[0]["by"], markers[0]["kind"]), ("guard", "memory"))
        self.assertEqual(events[0]["kind"], "memory")
        self.assertIn("would have frozen", events[0]["message"])

        # Nearly no memory left and swap full also counts, even before pressure builds up.
        self.write("proc/pressure/memory", "some avg10=0.00\nfull avg10=0.00\n")
        self.write("proc/meminfo", MEMINFO.replace("8000000 kB", "300000 kB").replace("SwapFree:        3000000", "SwapFree:         100000"))
        FreezeGuard.check(now=1040, stop=stop, proc=self.proc)
        self.assertEqual(self.stopped, ["com.game.a", "com.game.a"])

    def test_the_three_switches_are_independent(self):
        self.settings.update(enabled=False, stop_frozen=False)  # memory watchdog off: the rest still works
        self.write("proc/pressure/memory", "some avg10=90.00\nfull avg10=90.00\n")
        self.ticks(1000, 1008)
        self.assertEqual(self.limits, ["lepton-steamlaunch-7"])
        self.log("FrameBridge: pacing: 72.0 fps\n")
        events = self.ticks(1010, 1040)
        self.assertEqual(self.stopped, [])
        self.assertEqual([e["kind"] for evs in events.values() for e in evs], ["frozen"])

        FreezeGuard.sessions.clear()
        self.limits.clear()
        self.settings.update(enabled=True, memory_limit=False)
        self.write("proc/pressure/memory", "some avg10=0.00\nfull avg10=0.00\n")
        self.ticks(1042, 1060)
        self.assertEqual(self.limits, [])

    def test_ended_sessions_are_recorded_even_with_every_switch_off(self):
        self.settings.update(enabled=False, memory_limit=False, stop_frozen=False)
        self.ticks(1000, 1000)
        self.log("FrameBridge: pacing: 72.0 fps\n")
        self.ticks(1002, 1010)
        self.write("proc/locks", "")  # the launcher let go of its lock: the game ended
        self.check(1012)
        self.assertEqual(len(self.finalized), 1)
        pkg, state = self.finalized[0]
        self.assertEqual(pkg, "com.game.a")
        self.assertEqual((state["fps"], state["drew"], state["last_frame_age"]), (72.0, True, 10))
        self.assertEqual(FreezeGuard.sessions, {})

    def test_nothing_happens_without_a_running_game(self):
        self.write("proc/locks", "")
        self.write("proc/pressure/memory", "some avg10=90.00\nfull avg10=90.00\n")
        self.ticks(1000, 1008)
        self.assertEqual((self.stopped, self.limits, self.finalized), ([], [], []))

    def test_memory_limit_keeps_room_for_the_headset(self):
        gib = 1024 ** 3
        self.assertEqual(guard.memory_limit_bytes(16 * gib), int(13.5 * gib))
        self.assertEqual(guard.memory_limit_bytes(5 * gib), 4 * gib)


class TestMemoryLimit(Case):
    def run_results(self, update_rc, pid="4242"):
        def run(cmd, **kwargs):
            if cmd[:2] == ["podman", "update"]:
                return MagicMock(returncode=update_rc, stdout="",
                                 stderr="Error: healthcheck-timeout must be at least 1 second\n")
            return MagicMock(returncode=0, stdout=pid + "\n", stderr="")
        return run

    def make_cgroup(self):
        cg = os.path.join(self.tmp, "cg", "user.slice", "libpod-abc.scope", "container")
        os.makedirs(cg)
        for name in ("memory.max", "memory.swap.max"):
            with open(os.path.join(cg, name), "w") as f:
                f.write("max\n")
        os.makedirs(os.path.join(self.tmp, "proc", "4242"))
        with open(os.path.join(self.tmp, "proc", "4242", "cgroup"), "w") as f:
            f.write("0::/user.slice/libpod-abc.scope/container\n")
        return cg

    def test_podman_update_refusal_falls_back_to_the_cgroup(self):
        cg = self.make_cgroup()
        real = guard.container_cgroup
        with patch.object(guard.subprocess, "run", side_effect=self.run_results(125)), \
                patch.object(guard, "container_cgroup",
                             side_effect=lambda c: real(c, os.path.join(self.tmp, "cg"), os.path.join(self.tmp, "proc"))):
            self.assertEqual(guard.apply_memory_limit("lepton-steamlaunch-1", 16 * 1024 ** 3), "")
        with open(os.path.join(cg, "memory.max")) as f:
            self.assertEqual(int(f.read()), guard.memory_limit_bytes(16 * 1024 ** 3))
        with open(os.path.join(cg, "memory.swap.max")) as f:
            self.assertEqual(int(f.read()), 1024 ** 3)

    def test_podman_error_is_reported_when_the_cgroup_is_unknown(self):
        with patch.object(guard.subprocess, "run", side_effect=self.run_results(125, pid="0")):
            self.assertIn("healthcheck-timeout", guard.apply_memory_limit("lepton-steamlaunch-1", 16 * 1024 ** 3))


class TestHeadsetState(Case):
    def test_headset_state_comes_from_steamvrs_log(self):
        steam = os.path.join(self.tmp, "steam")
        with patch.object(guard, "STEAM_DIR", steam), patch.object(guard, "HOME", self.tmp):
            self.assertIsNone(guard.hmd_state())  # no SteamVR log: unknown, which counts as awake
            self.write("steam/logs/vrserver.txt", "Thu Oct 15 2026 12:00:00.1 - [CCVTrackedHmdDriver] in StateActive\n"
                                                   "Thu Oct 15 2026 12:05:00.1 - [CCVTrackedHmdDriver] in StateStandby\n")
            self.assertEqual(guard.hmd_state(), "Standby")

    def test_the_steam_menu_is_only_asked_about(self):
        from frameload.system import steam_ui
        asked = []
        self.assertTrue(steam_ui.dashboard_visible(evaluate=lambda expr, timeout: asked.append(expr) or True))
        self.assertEqual(asked, ["SteamClient.OpenVR.VROverlay.IsDashboardVisible()"])  # never HideDashboard

        def unreachable(expr, timeout):
            raise ConnectionError("no devtools port")
        self.assertIsNone(steam_ui.dashboard_visible(evaluate=unreachable))
        self.assertIsNone(steam_ui.dashboard_visible(evaluate=lambda expr, timeout: {"error": "x"}))


class FakeConfig:
    def __init__(self, raw):
        self.raw, self.saves = raw, 0

    def get(self, key=None, default=None):
        return self.raw.get(key, default)

    def save(self):
        self.saves += 1


class TestFreezeGuardSettings(unittest.TestCase):
    def use(self, raw):
        from frameload.config import Config
        cfg = FakeConfig(raw)
        p = patch.object(Config, "get", return_value=cfg)
        p.start()
        self.addCleanup(p.stop)
        return cfg

    def test_defaults(self):
        self.use({})
        self.assertEqual(FreezeGuard.settings(), {"enabled": True, "memory_limit": True, "stop_frozen": True,
                                                  "frozen_seconds": 30, "report_crashes": True})

    def test_what_v135_to_v137_saved_gives_way_to_the_new_defaults_once(self):
        # Those versions saved every key on every change, so their "off, 90 s" is not a choice anyone made.
        cfg = self.use({"guard": {"enabled": True, "memory_limit": False, "stop_frozen": False, "frozen_seconds": 90}})
        settings = FreezeGuard.settings()
        self.assertEqual((settings["stop_frozen"], settings["frozen_seconds"]), (True, 30))
        self.assertFalse(settings["memory_limit"])  # other choices are kept

        FreezeGuard.save_settings({"memory_limit": True})  # a change to something else keeps the new default
        self.assertEqual(cfg.raw["guard"]["version"], 2)
        self.assertNotIn("stop_frozen", cfg.raw["guard"])
        self.assertTrue(FreezeGuard.settings()["stop_frozen"])

        FreezeGuard.save_settings({"stop_frozen": False, "frozen_seconds": 20})  # now an Off sticks
        settings = FreezeGuard.settings()
        self.assertEqual((settings["stop_frozen"], settings["frozen_seconds"]), (False, 15))
        self.assertEqual(cfg.saves, 2)

    def test_wait_is_one_of_the_offered_choices(self):
        for value, expected in (("", 30), (None, 30), (0, 30), (-5, 30), ("abc", 30), (float("nan"), 30),
                                (15, 15), (20, 15), (30, 30), (45, 60), (90, 120), (1000, 120), ("60", 60)):
            self.assertEqual(guard.snap_frozen_seconds(value), expected, value)


if __name__ == "__main__":
    unittest.main()
