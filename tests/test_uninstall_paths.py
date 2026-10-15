"""The documented ways to remove FrameLoad and to open its window: uninstall.sh, `frameload uninstall-app`,
System > Clean Uninstallation and `frameload window`."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from frameload import cli
from frameload.manager.uninstaller import Uninstaller
from frameload.system import shortcuts
from frameload.system.steam_vdf import shortcut_appid, vdf_decode, vdf_encode

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*argv):
    with patch.object(sys, "argv", ["frameload", *argv]):
        cli.main()


def read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as f:
        return f.read()


class TestCliCommands(unittest.TestCase):
    def test_uninstall_app_runs_without_a_question_and_keeps_backups_by_default(self):
        with patch.object(cli.Uninstaller, "uninstall_frameload_app", return_value={"success": True}) as uninstall:
            run_cli("uninstall-app", "--yes")
            uninstall.assert_called_once_with(purge_games=False, keep_backups=True)
            uninstall.reset_mock()
            run_cli("uninstall-app", "-y", "--purge-games", "--purge-backups")
            uninstall.assert_called_once_with(purge_games=True, keep_backups=False)
        with self.assertRaises(SystemExit):  # contradicting each other
            run_cli("uninstall-app", "--yes", "--keep-backups", "--purge-backups")

    def test_window_gets_its_own_arguments(self):
        with patch("frameload.web.window.available_backend", return_value="qt"), \
                patch("frameload.web.window.main") as window_main:
            run_cli("window", "--url", "http://127.0.0.1:5051", "--fullscreen")
        window_main.assert_called_once_with(["--url", "http://127.0.0.1:5051", "--fullscreen"])

    def test_window_without_a_toolkit_says_what_to_do(self):
        with patch("frameload.web.window.available_backend", return_value=""), \
                patch("frameload.web.window.main") as window_main, \
                self.assertRaises(SystemExit) as stop:
            run_cli("window")
        self.assertEqual(stop.exception.code, 2)
        window_main.assert_not_called()

    def test_pywebview_alone_does_not_count_as_a_window_on_linux(self):
        # It draws with Qt or GTK there; counting it made run.sh skip Chrome and Firefox and open nothing.
        from frameload.web import window
        import importlib.util
        real = importlib.util.find_spec
        with patch.object(window.sys, "platform", "linux"), \
                patch("importlib.util.find_spec", side_effect=lambda name, *a: object() if name == "webview" else None if name.startswith(("PyQt", "PySide", "gi")) else real(name, *a)):
            self.assertEqual(window.available_backend(), "")

    def test_release_archive_carries_the_uninstaller(self):
        build = read(os.path.join("scripts", "build_release.py"))
        self.assertIn('"install.sh", "run.sh", "uninstall.sh"', build)
        # An archive without it must still install.
        self.assertIn('[[ -f "$TARGET_DIR/uninstall.sh" ]] && chmod +x "$TARGET_DIR/uninstall.sh" || true', build)

    def test_installer_adds_the_keyring_line_without_a_second_containers_table(self):
        install = read("install.sh")
        self.assertIn("ensure_host_podman_fixes()", install)
        self.assertNotIn("printf '[containers]", install)
        self.assertNotIn("pip install --user --quiet pywebview", install)


class TestHeadsetOnlyRoutes(unittest.TestCase):
    """What only someone at the headset may change, and an update that would end a running game."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from frameload.server import FrameLoadApiHandler
        for p in (patch.object(FrameLoadApiHandler, "client_is_local", return_value=False),
                  patch.object(FrameLoadApiHandler, "authorized", return_value=True),
                  patch("frameload.config.Config.save")):
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body):
        import http.client
        import json
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            payload = json.dumps(body).encode()
            conn.request("POST", path, body=payload, headers={"Content-Type": "application/json",
                                                              "Content-Length": str(len(payload))})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read() or b"{}")
        finally:
            conn.close()

    def test_a_paired_device_cannot_change_sources_through_the_config(self):
        from frameload.config import Config
        before = Config.get().raw.get("app_sources")
        status, _ = self.post("/api/config", {"app_sources": {"custom": [{"id": "u1", "url": "https://evil.example/repo"}]}})
        self.assertEqual(status, 403)
        self.assertEqual(Config.get().raw.get("app_sources"), before)

    def test_an_update_waits_for_running_games(self):
        with patch("frameload.manager.guard.running_games", return_value=[{"title": "Neon Drift"}]), \
                patch("frameload.manager.updates.UpdateManager.perform_app_update") as update:
            status, res = self.post("/api/updates/app", {})
        self.assertFalse(res["success"])
        self.assertIn("Close Neon Drift first", res["error"])
        update.assert_not_called()


class TestFrameLoadShortcutOnly(unittest.TestCase):
    def test_games_on_a_drive_named_frameload_are_never_taken_for_frameload(self):
        app = tempfile.mkdtemp(prefix="fl-app-")
        self.addCleanup(shutil.rmtree, app, True)
        os.makedirs(os.path.join(app, "frameload"))
        open(os.path.join(app, "frameload", "cli.py"), "w").close()
        renamed = {"appname": "My Sideloader", "Exe": f'"{app}/run.sh"'}
        game_on_card = {"appname": "Beat Saber", "Exe": '"/run/media/deck/FrameLoad/quest-frame/com.beatgames.beatsaber/launch.sh"'}
        game_home = {"appname": "FrameLoad", "Exe": '"/home/deck/Applications/quest-frame/com.frameload.demo/launch.sh"'}
        other = {"appname": "Emulator", "Exe": "/usr/bin/frameload-like-tool"}
        self.assertTrue(shortcuts.is_frameload_itself({"appname": "FrameLoad", "Exe": '"/home/deck/Applications/FrameLoad/run.sh"'}))
        self.assertTrue(shortcuts.is_frameload_itself(renamed))
        for entry in (game_on_card, game_home, other):
            self.assertFalse(shortcuts.is_frameload_itself(entry), entry)


class TestDashboardUninstall(unittest.TestCase):
    """System > Clean Uninstallation runs inside frameload.service: stopping the service ends the process."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="fl-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.data = os.path.join(self.home, ".local", "share", "frameload")
        self.keys = os.path.join(self.data, "frameport-home", "overport-workspace", "signatures")
        os.makedirs(self.keys)
        with open(os.path.join(self.keys, "com.example.game.keystore"), "wb") as f:
            f.write(b"key")
        os.makedirs(os.path.join(self.data, "cache"))
        for p in (patch("frameload.manager.uninstaller.HOME", self.home),
                  patch("frameload.manager.uninstaller.FRAMELOAD_DIR", self.data),
                  patch("frameload.manager.uninstaller.unregister_app_from_steam", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_service_is_disabled_first_and_stopped_last(self):
        calls = []
        with patch("frameload.manager.uninstaller.subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)), \
                patch("frameload.installer.porting.backup_signing_keys", return_value=""):
            Uninstaller.uninstall_frameload_app(keep_backups=True, remove_install_dir=False, stop_service_last=True)
        systemctl = [c[2:] for c in calls if c[:2] == ["systemctl", "--user"]]
        self.assertEqual(systemctl[0], ["disable", "frameload.service"])
        self.assertEqual(systemctl[-1], ["stop", "--no-block", "frameload.service"])
        self.assertEqual(sum(1 for c in systemctl if c[0] == "stop"), 1)

    def test_keys_that_could_not_be_saved_are_not_deleted(self):
        with patch("frameload.manager.uninstaller.subprocess.run"), \
                patch("frameload.installer.porting.backup_signing_keys", side_effect=OSError("Documents is read-only")):
            res = Uninstaller.uninstall_frameload_app(keep_backups=False, remove_install_dir=False)
        self.assertFalse(res["success"])
        self.assertTrue(os.path.isfile(os.path.join(self.keys, "com.example.game.keystore")))
        self.assertEqual(os.listdir(self.data), ["frameport-home"])


@unittest.skipIf(not os.path.isdir("/proc/self"), "needs /proc")
class TestStopsOnlyFrameLoadServers(unittest.TestCase):
    def test_a_server_started_without_systemd_is_found_by_its_command_line(self):
        server = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "frameload.cli", "serve"])
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "frameload.cli", "list"])
        self.addCleanup(other.kill)
        self.addCleanup(server.kill)
        time.sleep(0.3)
        Uninstaller._stop_server_started_without_systemd()
        self.assertIsNotNone(server.wait(timeout=10))
        self.assertIsNone(other.poll(), "only servers are stopped")


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "uninstall.sh runs on Linux")
class TestUninstallScript(unittest.TestCase):
    """Runs uninstall.sh against a throwaway home. systemctl, podman and pkill are stubbed, so a FrameLoad
    running on the machine that runs the tests is left alone."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="fl-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        stubs = os.path.join(self.home, "stubs")
        os.makedirs(stubs)
        for name in ("systemctl", "podman", "pkill", "update-desktop-database", "xdg-mime"):
            path = os.path.join(stubs, name)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.env = dict(os.environ, HOME=self.home, PATH=stubs + os.pathsep + os.environ.get("PATH", ""))
        self.env.pop("FRAMELOAD_INSTALL_DIR", None)

        # Steam's shortcut list: FrameLoad's own entry between other non-Steam games and FrameLoad games,
        # one of them on a card whose name contains "FrameLoad".
        self.config = os.path.join(self.home, ".steam", "steam", "userdata", "123", "config")
        os.makedirs(os.path.join(self.config, "grid"))
        app = os.path.join(self.home, "Applications")
        entries = [
            ("Emulator", "/usr/bin/emulator", ""),
            ("FrameLoad", f'"{app}/FrameLoad/run.sh"', "FrameLoad 2D"),
            ("Some Tool", "/opt/tool/run", ""),
            ("Beat Saber", f'"{app}/quest-frame/com.beatgames.beatsaber/launch.sh"', "FrameLoad VR"),
            ("Moss", '"/run/media/deck/FrameLoad/quest-frame/com.polyarcgames.moss/launch.sh"', "FrameLoad VR"),
            ("Last Game", "/opt/last/start", ""),
        ]
        shortcuts_vdf = {}
        for i, (title, exe, tag) in enumerate(entries):
            shortcuts_vdf[str(i)] = {"appid": shortcut_appid(exe, title), "appname": title, "Exe": exe,
                                     "tags": {"0": tag} if tag else {}}
        self.frameload_id = shortcuts_vdf["1"]["appid"]
        self.moss_id = shortcuts_vdf["4"]["appid"]
        with open(os.path.join(self.config, "shortcuts.vdf"), "wb") as f:
            f.write(vdf_encode({"shortcuts": shortcuts_vdf}))
        for appid in (self.frameload_id, self.moss_id):
            for suffix in ("p.png", ".png", "_hero.png"):
                open(os.path.join(self.config, "grid", f"{appid}{suffix}"), "wb").close()

        data = os.path.join(self.home, ".local", "share", "frameload")
        self.keys = os.path.join(data, "frameport-home", "overport-workspace", "signatures")
        os.makedirs(self.keys)
        with open(os.path.join(self.keys, "com.example.game.keystore"), "wb") as f:
            f.write(b"key")
        os.makedirs(os.path.join(data, "backups"))
        open(os.path.join(data, "backups", "com.example.game_save_1.tar.gz"), "wb").close()
        open(os.path.join(data, "config.json"), "w").close()
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        open(os.path.join(self.home, ".local", "bin", "frameload"), "w").close()

    def run_script(self, *args, stdin=None):
        return subprocess.run(["bash", os.path.join(REPO, "uninstall.sh"), *args], cwd=self.home, env=self.env,
                              input=stdin, capture_output=True, text=True, timeout=120, start_new_session=True)

    def remaining_titles(self):
        with open(os.path.join(self.config, "shortcuts.vdf"), "rb") as f:
            return [v["appname"] for v in vdf_decode(f.read())["shortcuts"].values()]

    def test_removes_only_frameload_itself(self):
        result = self.run_script("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.remaining_titles(), ["Emulator", "Some Tool", "Beat Saber", "Moss", "Last Game"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.config, "grid"))),
                         sorted(f"{self.moss_id}{s}" for s in ("p.png", ".png", "_hero.png")))
        saved = os.path.join(self.home, "Documents", "FrameLoad-signing-keys", "com.example.game.keystore")
        self.assertTrue(os.path.isfile(saved), "signing keys must be saved before the data is deleted")
        data = os.path.join(self.home, ".local", "share", "frameload")
        self.assertEqual(os.listdir(data), ["backups"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "frameload")))
        self.assertTrue(os.path.isfile(os.path.join(REPO, "frameload", "cli.py")), "a checkout elsewhere is never deleted")

    def test_piped_without_a_terminal_changes_nothing(self):
        result = self.run_script(stdin="y\ny\nn\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("--yes", result.stdout + result.stderr)
        self.assertEqual(len(self.remaining_titles()), 6)
        self.assertTrue(os.path.isdir(self.keys))


if __name__ == "__main__":
    unittest.main()
