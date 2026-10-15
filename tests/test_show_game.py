"""A VR game that plays its sound behind FrameLoad's window: Show <game>, the automatic hide of
Steam's menu at the first frame, closing FrameLoad's window, and what the Launch Log says about it."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from frameload.config import Config
from frameload.manager import launchlog
from frameload.manager.installed import InstalledManager
from frameload.manager.launcher import GameLauncher
from frameload.server import FrameLoadApiHandler
from frameload.system import steam_session, steam_ui

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIDE = "SteamClient.OpenVR.VROverlay.HideDashboard()"
VISIBLE = "SteamClient.OpenVR.VROverlay.IsDashboardVisible()"
PRESS = "[ToggleDashboard] toggle_dashboard_action\n"


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def patch(self, *args, **kwargs):
        p = patch(*args, **kwargs) if isinstance(args[0], str) else patch.object(*args, **kwargs)
        mock = p.start()
        self.addCleanup(p.stop)
        return mock

    def write(self, *parts, data="x"):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(data, bytes) else "w", encoding=None if isinstance(data, bytes) else "utf-8") as f:
            f.write(data)
        return path


class Dashboard:
    """Steam's dashboard as steam_ui sees it through `evaluate`: open `reopen` more times after each hide."""

    def __init__(self, reopen=0):
        self.visible, self.reopen, self.calls = True, reopen, []

    def __call__(self, expression):
        self.calls.append(expression)
        if expression == VISIBLE:
            return self.visible
        if expression == HIDE:
            self.visible = self.reopen > 0
            self.reopen -= 1
        return None


class TestFirstFrame(TempCase):
    def worker(self, log_text, evaluate, **kwargs):
        log = self.write("launch.log", data=log_text)
        self.ui_log = self.write("ui.txt", data="")
        lines = []
        kwargs = {"wait_start": 2, "window": 1, "poll": 0.02, "ui_log": self.ui_log, "logcat_every": 0.02, **kwargs}
        hidden = steam_ui.dashboard_worker(log, os.getpid(), evaluate=evaluate, say=lines.append, **kwargs)
        return hidden, lines

    def test_launch_log_and_container_log_formats_both_count(self):
        frame = steam_ui.FIRST_FRAME_RE
        self.assertTrue(frame.search(b"10-15 12:00:00.001  4321  4350 I FrameBridge: new layer: 0x1 1832x1920"))
        self.assertTrue(frame.search(b"I/FrameBridge( 4321): new layer: 0x1"))
        self.assertTrue(frame.search(b"I/FrameBridge(  77): pacing: 72 fps"))
        self.assertFalse(frame.search(b"I/FrameBridge( 4321): config loaded from settings.conf"))

    def test_the_container_log_stands_in_for_a_silent_launch_log(self):
        answers = [b"", b"--------- beginning of main\nI/FrameBridge( 4321): new layer: 0x1\n"]
        dashboard = Dashboard()
        hidden, lines = self.worker("lepton: started\nlogcat: Unexpected EOF!\n", dashboard,
                                    logcat=lambda: answers.pop(0) if answers else b"")
        self.assertEqual(hidden, 1)
        self.assertTrue(any("first VR frame" in line and "container" in line for line in lines), lines)
        self.assertEqual(lines[-1], "result: hidden 1")

        def broken():
            raise subprocess.TimeoutExpired("podman", 5)
        hidden, lines = self.worker("lepton: started\n", Dashboard(), wait_start=0.2, logcat=broken)
        self.assertEqual((hidden, lines[-1]), (0, "result: no-frames"))

    def test_presses_while_the_game_starts_do_not_stop_the_hide(self):
        log = self.write("launch.log", data="lepton: installing\n")
        ui_log = self.write("ui.txt", data="")

        def game_starts():
            time.sleep(0.15)
            with open(ui_log, "a", encoding="utf-8") as f:
                f.write(PRESS)  # the player presses the Steam button while Lepton boots
            time.sleep(0.25)
            with open(log, "a", encoding="utf-8") as f:
                f.write("10-15 12:00:00.001  4321  4350 I FrameBridge: new layer: 0x1\n")
        threading.Thread(target=game_starts, daemon=True).start()
        lines = []
        hidden = steam_ui.dashboard_worker(log, os.getpid(), wait_start=3, window=1, poll=0.02, ui_log=ui_log,
                                           evaluate=Dashboard(), say=lines.append)
        self.assertEqual(hidden, 1, lines)
        self.assertEqual(lines[-1], "result: hidden 1")

        # A press once the game draws still leaves the menu to the player.
        def press_while_hiding(expression, dashboard=Dashboard(reopen=5)):
            with open(self.ui_log, "a", encoding="utf-8") as f:
                f.write(PRESS)
            return dashboard(expression)
        hidden, lines = self.worker("FrameBridge: pacing: 72 fps\n", press_while_hiding)
        self.assertEqual((hidden, lines[-1]), (1, "result: player"))

    def test_a_menu_that_keeps_coming_back_is_reported_and_closes_the_window(self):
        tries = [False, True]  # the window was not there at the first frame, it is now

        def close_window():
            return tries.pop(0)
        dashboard = Dashboard(reopen=100)
        hidden, lines = self.worker("FrameBridge: new layer: 0x1\n", dashboard, window=5, poll=0.01,
                                    close_window=close_window)
        self.assertEqual(tries, [])  # asked at the first frame and again when the menu kept coming back
        self.assertEqual(lines[-1], "result: keeps-reopening")
        self.assertIn("closed FrameLoad's window", " ".join(lines))
        self.assertEqual(hidden, 11)  # ten, and one more once the window is gone

        # The same number of hides spread over a longer time is not a bounce.
        hidden, lines = self.worker("FrameBridge: new layer: 0x1\n", Dashboard(reopen=100), window=5, poll=0.01,
                                    bounce_seconds=0)
        self.assertEqual((hidden, lines[-1]), (10, "result: hidden 10"))

    def test_the_window_closes_at_the_first_frame_when_asked_to(self):
        order = []
        dashboard = Dashboard()

        def evaluate(expression):
            order.append("hide" if expression == HIDE else "look")
            return dashboard(expression)
        hidden, lines = self.worker("FrameBridge: new layer: 0x1\n", evaluate,
                                    close_window=lambda: order.append("close") or True)
        self.assertEqual(order[0], "close")
        self.assertEqual(order.count("close"), 1)
        self.assertEqual(lines[-1], "result: hidden 1")

    def test_every_run_ends_with_one_result_line(self):
        cases = [
            ("boot only\n", Dashboard(), "result: no-frames"),
            ("FrameBridge: pacing: 72 fps\n", lambda e: False, "result: hidden 0"),
            ("FrameBridge: pacing: 72 fps\n", lambda e: (_ for _ in ()).throw(OSError("connection\nrefused")),
             "result: error connection refused"),
        ]
        for text, evaluate, last in cases:
            _, lines = self.worker(text, evaluate, wait_start=0.2)
            self.assertEqual(lines[-1], last)
            self.assertEqual(sum(line.startswith("result:") for line in lines), 1)


class TestClosingTheWindow(TempCase):
    def proc_entry(self, pid, *args):
        self.write("proc", str(pid), "cmdline", data=b"\0".join(a.encode() for a in args) + b"\0")

    def test_only_frameloads_own_run_sh_is_signalled(self):
        kill = self.patch("os.kill")
        pid_file = self.write("window.pid", data="4242\n")
        proc = os.path.join(self.tmp, "proc")
        self.proc_entry(4242, "bash", "/home/deck/Applications/FrameLoad/run.sh")
        self.assertTrue(steam_ui.close_frameload_window(pid_file, proc))
        kill.assert_called_once_with(4242, signal.SIGTERM)

        kill.reset_mock()
        self.proc_entry(4242, "/usr/bin/python3", "-m", "something.else")  # the pid was reused
        self.assertFalse(steam_ui.close_frameload_window(pid_file, proc))
        self.assertFalse(steam_ui.close_frameload_window(os.path.join(self.tmp, "missing.pid"), proc))
        self.write("window.pid", data="not a pid")
        self.assertFalse(steam_ui.close_frameload_window(pid_file, proc))
        kill.assert_not_called()

    def test_the_setting_is_off_unless_switched_on(self):
        config = os.path.join(self.tmp, "config.json")
        self.assertFalse(steam_ui.close_on_vr_start(config))  # no config yet
        for ui, expected in (({}, False), ({"close_on_vr_start": "yes"}, False), ({"close_on_vr_start": True}, True)):
            self.write("config.json", data=json.dumps({"ui": ui}))
            self.assertEqual(steam_ui.close_on_vr_start(config), expected, ui)
        self.write("config.json", data="{broken")
        self.assertFalse(steam_ui.close_on_vr_start(config))

    def test_launcher_helper_asks_the_container_only_for_games_with_framebridge(self):
        worker = self.patch(steam_ui, "dashboard_worker")

        def apk(name, libs):
            folder = os.path.join(self.tmp, name)
            os.makedirs(folder)
            with zipfile.ZipFile(os.path.join(folder, "game.apk"), "w") as zf:
                zf.writestr("AndroidManifest.xml", b"x")
                for lib in libs:
                    zf.writestr(f"lib/arm64-v8a/{lib}", b"\x7fELF")
            return folder

        ported = apk("ported", ["libframe_settings.so", "libopenxr_loader.so"])
        native = apk("native", ["libopenxr_loader.so"])
        for install, appid, asks in ((ported, "3000000001", True), (native, "3000000001", False), (ported, "0", False)):
            with patch.dict(os.environ, {"SteamAppId": appid, "STEAM_COMPAT_INSTALL_PATH": install}):
                steam_ui.main(["/game/launch.log", "123"])
            kwargs = worker.call_args[1]
            self.assertEqual(kwargs["logcat"] is not None, asks, (install, appid))
            self.assertIs(kwargs["close_window"], steam_ui.close_window_if_enabled)
        self.assertTrue(steam_ui.carries_framebridge(os.path.join(self.tmp, "nothing-here")))  # unknown: ask

    def test_framebridge_libraries_match_the_apk_inspection(self):
        from frameload.installer import apk_analysis
        self.assertEqual(steam_ui.FRAMEBRIDGE_LIBS, apk_analysis.FRAMEBRIDGE_LIBS)

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock") and shutil.which("bash"),
                         "run.sh needs bash, flock and /proc")
    def test_run_sh_records_its_window_and_closes_it_on_sigterm(self):
        home = os.path.join(self.tmp, "home")
        fakebin = os.path.join(self.tmp, "bin")
        os.makedirs(fakebin)
        browser_pid = os.path.join(self.tmp, "browser.pid")
        # The first browser run.sh looks for: stands in for the window.
        self.write("bin", "google-chrome-stable", data=f"#!/bin/sh\necho $$ > {browser_pid}\nexec sleep 30\n")
        os.chmod(os.path.join(fakebin, "google-chrome-stable"), 0o755)
        if os.path.exists("/usr/bin/python3") and subprocess.run(
                ["/usr/bin/python3", "-m", "frameload.web.window", "--check"], cwd=REPO, capture_output=True).returncode == 0:
            self.skipTest("a native window toolkit is installed; run.sh would open a real window")

        class Alive(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Alive)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        env = dict(os.environ, HOME=home, PATH=f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                   FRAMELOAD_PORT=str(server.server_address[1]))
        run = subprocess.Popen(["bash", os.path.join(REPO, "run.sh")], env=env, cwd=self.tmp,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: run.poll() is None and run.kill())
        pid_file = os.path.join(home, ".local", "share", "frameload", "window.pid")
        deadline = time.time() + 15
        while time.time() < deadline and not (os.path.exists(pid_file) and os.path.exists(browser_pid)):
            time.sleep(0.1)
        with open(pid_file, encoding="utf-8") as f:
            self.assertEqual(int(f.read()), run.pid)

        self.assertTrue(steam_ui.close_frameload_window(pid_file))
        self.assertEqual(run.wait(timeout=10), 0)
        self.assertFalse(os.path.exists(pid_file))
        with open(browser_pid, encoding="utf-8") as f:
            browser = int(f.read())
        time.sleep(0.2)
        with self.assertRaises(OSError):
            os.kill(browser, 0)  # the window went with it


class TestShowGame(TempCase):
    def test_show_closes_the_dashboard_and_checks_it_stayed_closed(self):
        dashboard = Dashboard()
        self.assertEqual(steam_ui.show_game(dashboard, settle=0), {"success": True, "visible": False})
        self.assertEqual(dashboard.calls, [HIDE, VISIBLE])

        # Steam gives no clear answer (its interface changed): that is no success either.
        self.assertFalse(steam_ui.show_game(lambda e: None, settle=0)["success"])
        res = steam_ui.show_game(Dashboard(reopen=1), settle=0)  # Steam opened it again
        self.assertEqual((res["success"], res["visible"]), (False, True))
        self.assertEqual(res["error"], "Steam's menu could not be closed from here. Press the Steam button on your controller.")

        res = steam_ui.show_game(lambda e: (_ for _ in ()).throw(ConnectionRefusedError("refused")), settle=0)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], steam_ui.MENU_LEFT_OPEN)

    def test_show_speaks_to_steams_devtools(self):
        seen = []

        class Devtools(socketserver.BaseRequestHandler):
            def handle(self):
                head = b""
                while b"\r\n\r\n" not in head:
                    head += self.request.recv(1024)
                port = self.server.server_address[1]
                if head.startswith(b"GET /json"):
                    body = json.dumps([{"title": "SharedJSContext",
                                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/S"}]).encode()
                    self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
                                         + b"\r\nConnection: close\r\n\r\n" + body)
                    return
                self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                _, second = self.request.recv(2)
                length = second & 0x7F
                if length == 126:
                    length = int.from_bytes(self.request.recv(2), "big")
                mask = self.request.recv(4)
                data = b""
                while len(data) < length:
                    data += self.request.recv(length - len(data))
                expression = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))["params"]["expression"]
                seen.append(expression)
                value = False if expression == VISIBLE else None
                payload = json.dumps({"id": 1, "result": {"result": {"value": value}}}).encode()
                self.request.sendall(bytes([0x81, len(payload)]) + payload)

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Devtools)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        res = steam_ui.show_game(lambda e: steam_ui.steam_js(e, address=server.server_address), settle=0)
        self.assertEqual(res, {"success": True, "visible": False})
        self.assertEqual(seen, [HIDE, VISIBLE])

    def test_only_a_running_vr_game_is_shown(self):
        game = {"package": "a.b", "title": "Neon Drift", "appid": 77, "is_vr": True}
        self.patch(InstalledManager, "get_game", side_effect=lambda pkg: game if pkg == "a.b" else None)
        running = self.patch(GameLauncher, "running_containers", return_value=[])
        show = self.patch(steam_ui, "show_game", return_value={"success": True, "visible": False})

        self.assertEqual(GameLauncher.show("a.b")["error"], "Neon Drift is not running.")
        self.assertFalse(GameLauncher.show("x.y")["success"])
        show.assert_not_called()

        running.return_value = ["lepton-steamlaunch-77"]
        res = GameLauncher.show("a.b")
        self.assertEqual((res["success"], res["running"], res["title"]), (True, True, "Neon Drift"))
        show.assert_called_once()

        game["is_vr"] = False  # a 2D app is a window of its own: hiding the dashboard would hide it
        self.assertFalse(GameLauncher.show("a.b")["success"])
        self.assertEqual(show.call_count, 1)


class TestLauncherError(TempCase):
    def test_a_launcher_that_stopped_before_lepton_says_why(self):
        from frameload.manager import launchlog
        base = os.path.join(self.tmp, "game")
        os.makedirs(base)
        with open(os.path.join(base, ".last_played"), "w") as f:
            f.write(f"{int(time.time()) - 60}\n")
        with open(os.path.join(base, ".launch_error"), "w") as f:
            f.write("Lepton runtime not found\n")
        titles = [f["title"] for f in launchlog.session_findings(base, {"title": "Game", "package": "com.x"})]
        self.assertIn("The launcher could not start the game", titles)


class TestLastLaunch(TempCase):
    def test_how_the_game_was_started_is_kept(self):
        anchor = os.path.join(self.tmp, "anchor")
        base = os.path.join(self.tmp, "base")
        os.makedirs(anchor)
        os.makedirs(base)
        self.write("anchor", "launch.sh", data="#!/bin/bash\n")
        self.patch(InstalledManager, "get_game", return_value={"package": "a.b", "title": "G", "appid": 123,
                                                               "anchor": anchor, "base": base})
        self.patch("frameload.system.steamos.is_steam_running", return_value=True)
        self.patch("subprocess.Popen")

        for pending, via in ((True, "direct"), (False, "steam")):
            with patch.object(steam_session, "is_pending", return_value=pending):
                before = int(time.time())
                GameLauncher.launch("a.b")
            with open(os.path.join(base, ".last_launch"), encoding="utf-8") as f:
                record = json.load(f)
            self.assertEqual((record["via"], record["pending"]), (via, pending))
            self.assertGreaterEqual(record["time"], before)


class TestLaunchLogExplains(TempCase):
    def setUp(self):
        super().setUp()
        self.base = os.path.join(self.tmp, "game")
        self.dep = {"package": "a.b", "title": "Neon Drift", "base": self.base, "is_vr": True, "xr_runtime": "framebridge"}
        self.patch(InstalledManager, "get_game", return_value=self.dep)
        self.write("game", "launch.log", data="lepton: started\n")

    def titles(self):
        return [f["title"] for f in launchlog.read_log("a.b")["findings"]]

    def test_a_dead_log_copy_is_named(self):
        for line in ("logcat: Unexpected EOF!", "E/logcat: Logcat read failure"):
            titles = [f["title"] for f in launchlog.diagnose(["boot", line])]
            self.assertEqual(titles, ["Lepton stopped copying the game's log"])

    def test_what_became_of_steams_menu(self):
        started = time.time()
        self.write("game", ".last_played", data=str(int(started)))
        for result, title in (("no-frames", "FrameLoad saw no VR picture from the game"),
                              ("player", "You opened Steam's menu yourself"),
                              ("keeps-reopening", "Steam's menu kept coming back over the game")):
            self.write("game", "dashboard.log", data=f"12:00:01 first VR frame\nresult: {result}\n")
            self.assertEqual(self.titles(), [title])
        self.write("game", "dashboard.log", data="12:00:01 first VR frame\n12:00:02 dashboard hidden\nresult: hidden 1\n")
        self.assertEqual(self.titles(), ["No known problem found in the log"])

        # An unported game never reports its first picture: say so.
        self.write("game", "dashboard.log", data="no VR frames logged; dashboard left as it is\nresult: no-frames\n")
        self.dep["xr_runtime"] = "openxr"
        advice = launchlog.read_log("a.b")["findings"][0]["advice"]
        self.assertIn("Show Neon Drift", advice)
        self.assertIn("not ported", advice)

        # A dashboard.log from an earlier start says nothing about this one.
        os.utime(os.path.join(self.base, "dashboard.log"), (started - 3600, started - 3600))
        self.assertEqual(self.titles(), ["No known problem found in the log"])

    def test_a_direct_start_is_named(self):
        now = time.time()
        self.write("game", ".last_launch", data=json.dumps({"time": int(now), "via": "direct", "pending": True}))
        self.write("game", ".last_played", data=str(int(now) + 1))
        self.assertEqual(self.titles(), ["Started directly (Steam had not loaded it)"])
        # Started from the Steam library later: that record is about an older start.
        self.write("game", ".last_played", data=str(int(now) + 3600))
        self.assertEqual(self.titles(), ["No known problem found in the log"])
        self.write("game", ".last_launch", data=json.dumps({"time": int(now) + 3600, "via": "steam", "pending": False}))
        self.assertEqual(self.titles(), ["No known problem found in the log"])


class TestRoutes(TempCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.patch(Config, "save")
        cfg = Config.get()
        saved = dict(cfg.raw.get("ui", {}))
        self.addCleanup(lambda: cfg.raw.__setitem__("ui", saved))

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            payload = json.dumps(body).encode()
            conn.request("POST", path, body=payload, headers={"Content-Type": "application/json",
                                                              "Content-Length": str(len(payload))})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read() or b"{}")
        finally:
            conn.close()

    def test_show_game_route(self):
        show = self.patch(GameLauncher, "show", return_value={"success": True, "visible": False})
        status, body = self.post("/api/installed/show-game", {"package": "a.b"})
        self.assertEqual((status, body["success"]), (200, True))
        show.assert_called_once_with("a.b")
        self.assertEqual(self.post("/api/installed/show-game", {"package": "../x"})[0], 400)

        # Another device on the network must be paired first, like every other route.
        with patch.object(FrameLoadApiHandler, "client_is_local", return_value=False):
            self.assertEqual(self.post("/api/installed/show-game", {"package": "a.b"})[0], 401)
        self.assertEqual(show.call_count, 1)

    def test_close_window_setting_is_saved(self):
        status, body = self.post("/api/ui/starting", {"close_on_vr_start": True})
        self.assertEqual((status, body["close_on_vr_start"]), (200, True))
        self.assertIs(Config.get().raw["ui"]["close_on_vr_start"], True)
        self.assertIs(self.post("/api/ui/starting", {"close_on_vr_start": "yes"})[1]["close_on_vr_start"], False)


class TestDashboardWiring(unittest.TestCase):
    """The dashboard offers Show while a VR game runs, and the toast after Play points at it."""

    @classmethod
    def setUpClass(cls):
        web = os.path.join(REPO, "frameload", "web")
        with open(os.path.join(web, "templates", "index.html"), encoding="utf-8") as f:
            cls.page = f.read()
        with open(os.path.join(web, "static", "js", "app.js"), encoding="utf-8") as f:
            cls.js = f.read()

    def test_chip_setting_and_toast(self):
        for needle in ('id="header-show-game"', 'id="close-on-vr-start"'):
            self.assertTrue(needle in self.page, needle)
        # Right beside the Stop chip.
        self.assertRegex(self.page, r'id="header-show-game"[^\n]*</button>\n\s*<button id="header-stop-game"')
        for needle in ("/api/installed/show-game", "/api/ui/starting", "If you only hear it, press Show ${name}.",
                       steam_ui.MENU_LEFT_OPEN):
            self.assertTrue(needle in self.js, needle)


if __name__ == "__main__":
    unittest.main()
