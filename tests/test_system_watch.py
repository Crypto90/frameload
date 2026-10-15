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


class TestFreezeGuard(Case):
    def setUp(self):
        super().setUp()
        FreezeGuard.sessions, FreezeGuard._games, FreezeGuard._games_at = {}, [], 0.0
        FreezeGuard._psi, FreezeGuard._last_stop = deque(maxlen=10), 0.0
        FreezeGuard.events.clear()
        self.proc = os.path.join(self.tmp, "proc")
        self.write("proc/meminfo", MEMINFO)
        self.write("proc/pressure/memory", "some avg10=0.00\nfull avg10=0.00\n")
        self.games = []
        for pkg in ("com.game.a", "com.game.b"):
            base = os.path.join(self.tmp, pkg)
            self.write(f"{pkg}/.launch.lock", "")
            self.write(f"{pkg}/launch.log", "boot\n")
            self.games.append({"package": pkg, "title": pkg.upper(), "appid": 7, "base": base})
        inode = os.stat(os.path.join(self.games[0]["base"], ".launch.lock")).st_ino
        self.write("proc/locks", f"1: POSIX  ADVISORY  WRITE 99 00:1a:555 0 EOF\n"
                                 f"2: FLOCK  ADVISORY  WRITE 1234 fd:01:{inode} 0 EOF\n"
                                 f"3: -> FLOCK  ADVISORY  WRITE 1300 fd:01:{inode} 0 EOF\n")
        self.stopped, self.limits = [], []
        self.settings = dict(guard.DEFAULT_SETTINGS)
        patch.object(guard, "installed_games", return_value=self.games).start()
        patch.object(FreezeGuard, "settings", side_effect=lambda: dict(self.settings)).start()
        patch.object(guard, "apply_memory_limit", side_effect=lambda name, total: self.limits.append(name) or "").start()
        self.addCleanup(patch.stopall)

    def check(self, now):
        return FreezeGuard.check(now=now, stop=self.stopped.append, proc=self.proc)

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

    def test_a_game_that_stops_drawing_is_reported_not_stopped(self):
        self.assertEqual(self.check(1000.0), [])
        self.assertEqual(self.check(1005.0), [])
        self.assertEqual(self.limits, ["lepton-steamlaunch-7"])  # once the container has had a moment
        with open(os.path.join(self.games[0]["base"], "launch.log"), "a") as f:
            f.write("FrameBridge: new layer: 0\nFrameBridge: pacing: 71.9 fps, displayTime vs predicted: avg 1.2 ms\n")
        self.check(1010.0)
        self.assertEqual(FreezeGuard.status()["games"][0]["fps"], 71.9)
        self.assertEqual(self.check(1060.0), [])  # 50 s without a frame: could be a loading screen
        events = self.check(1101.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "frozen")
        self.assertIn("press Stop", events[0]["message"])
        self.assertEqual(self.stopped, [])
        self.assertEqual(self.check(1200.0), [])  # reported once

        self.settings["stop_frozen"] = True
        with open(os.path.join(self.games[0]["base"], "launch.log"), "a") as f:
            f.write("FrameBridge: pacing: 72 fps\n")
        self.check(1300.0)
        events = self.check(1395.0)
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertIn("stopped", events[0]["message"])

    def test_memory_exhaustion_stops_the_game(self):
        self.check(1000.0)
        self.write("proc/pressure/memory", "some avg10=80.00\nfull avg10=35.00\n")
        self.assertEqual(self.check(1002.0), [])
        self.assertEqual(self.check(1004.0), [])
        events = self.check(1006.0)  # third sample in a row above the limit
        self.assertEqual(self.stopped, ["com.game.a"])
        self.assertEqual(events[0]["kind"], "memory")
        self.assertIn("would have frozen", events[0]["message"])

        # Nearly no memory left and swap full also counts, even before pressure builds up.
        self.write("proc/pressure/memory", "some avg10=0.00\nfull avg10=0.00\n")
        self.write("proc/meminfo", MEMINFO.replace("8000000 kB", "300000 kB").replace("SwapFree:        3000000", "SwapFree:         100000"))
        self.check(1040.0)
        self.assertEqual(self.stopped, ["com.game.a", "com.game.a"])

    def test_nothing_happens_without_a_running_game_or_when_switched_off(self):
        self.write("proc/locks", "")
        self.write("proc/pressure/memory", "some avg10=90.00\nfull avg10=90.00\n")
        for t in range(5):
            self.check(1000.0 + t * 2)
        self.assertEqual((self.stopped, self.limits), ([], []))
        self.settings["enabled"] = False
        self.assertEqual(self.check(2000.0), [])

    def test_memory_limit_keeps_room_for_the_headset(self):
        gib = 1024 ** 3
        self.assertEqual(guard.memory_limit_bytes(16 * gib), int(13.5 * gib))
        self.assertEqual(guard.memory_limit_bytes(5 * gib), 4 * gib)


if __name__ == "__main__":
    unittest.main()
