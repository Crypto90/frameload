"""Steam shortcut state, save backups, access control, uploads, updater integrity, logs and artwork."""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from frameload.catalog.fdroid import FDroidCatalog  # noqa: E402
from frameload.catalog.models import CatalogGame  # noqa: E402
from frameload.installer import artwork  # noqa: E402
from frameload.manager import files as file_manager  # noqa: E402
from frameload.manager import launchlog, updates  # noqa: E402
from frameload.manager.backup import SaveBackupManager  # noqa: E402
from frameload.manager.installed import InstalledManager  # noqa: E402
from frameload.manager.launcher import GameLauncher  # noqa: E402
from frameload.manager.storage import StorageManager  # noqa: E402
from frameload.server import FrameLoadApiHandler  # noqa: E402
from frameload.system import access, fsutil, steam_session  # noqa: E402


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
        with open(path, "wb" if isinstance(data, bytes) else "w") as f:
            f.write(data)
        return path


class TestSteamSession(TempCase):
    def setUp(self):
        super().setUp()
        self.patch(steam_session, "STATE_FILE", os.path.join(self.tmp, "steam.json"))
        self.script = self.write("game", "launch.sh")

    def test_shortcut_written_after_steam_started_is_pending(self):
        steam_session.note_written(self.script, "New Game")
        now = time.time()
        self.assertEqual(steam_session.pending(started=now - 60), [{"launch_script": self.script, "title": "New Game"}])
        self.assertEqual(steam_session.pending(started=now + 60), [])  # Steam restarted since: it has it
        with patch.object(steam_session, "steam_started_at", return_value=None):
            self.assertEqual(steam_session.pending(), [])  # Steam not running
            self.assertFalse(steam_session.status()["restart_needed"])
        with patch.object(steam_session, "steam_started_at", return_value=now - 60), \
                patch.object(steam_session, "can_restart", return_value=True):
            status = steam_session.status()
            self.assertEqual((status["restart_needed"], status["pending"], status["can_restart"]), (True, ["New Game"], True))
        steam_session.forget(self.script)
        self.assertEqual(steam_session.pending(started=now - 60), [])

    def test_restart_refuses_without_the_steam_service(self):
        with patch.object(steam_session, "can_restart", return_value=False), patch("subprocess.run") as run:
            self.assertFalse(steam_session.restart_steam()["success"])
            run.assert_not_called()

    def test_game_steam_does_not_know_is_started_directly(self):
        anchor = os.path.dirname(self.script)
        dep = {"package": "a.b", "title": "New Game", "appid": 123, "anchor": anchor}
        self.patch(InstalledManager, "get_game", return_value=dep)
        self.patch("frameload.system.steamos.is_steam_running", return_value=True)
        popen = self.patch("subprocess.Popen")

        with patch.object(steam_session, "is_pending", return_value=True):
            res = GameLauncher.launch("a.b")
        self.assertFalse(res["launched_via_steam"])
        self.assertEqual(popen.call_args[0][0], ["bash", self.script])
        self.assertEqual(popen.call_args[1]["env"]["FRAMELOAD_DETACHED"], "1")

        popen.reset_mock()
        with patch.object(steam_session, "is_pending", return_value=False):
            res = GameLauncher.launch("a.b")
        self.assertTrue(res["launched_via_steam"])
        self.assertTrue(popen.call_args[0][0][-1].startswith("steam://rungameid/"))


class TestSteamDashboard(TempCase):
    """Steam's "Resume game" menu is hidden once the game draws, unless the player opened it."""

    def worker(self, log_text, evaluate, ui_text=None, **kwargs):
        from frameload.system import steam_ui
        log = self.write("launch.log", data=log_text)
        ui_log = os.path.join(self.tmp, "ui.txt")
        self.write("ui.txt", data="")
        if ui_text is not None:
            original = evaluate

            def evaluate(expression):  # the player presses the dashboard button while we watch
                with open(ui_log, "a") as f:
                    f.write(ui_text)
                return original(expression)
        lines = []
        hidden = steam_ui.dashboard_worker(log, os.getpid(), wait_start=1, window=1, poll=0.05, ui_log=ui_log,
                                           evaluate=evaluate, say=lines.append, **kwargs)
        return hidden, lines

    def test_hides_the_menu_after_the_first_frame(self):
        calls = []
        visible = [True, False, True, False]

        def evaluate(expression):
            calls.append(expression)
            if "IsDashboardVisible" in expression:
                return visible.pop(0) if visible else False
            return None

        hidden, lines = self.worker("boot\nFrameBridge: new layer: 0\n", evaluate)
        self.assertEqual(hidden, 2)
        self.assertEqual(calls.count("SteamClient.OpenVR.VROverlay.HideDashboard()"), 2)
        self.assertTrue(any("first VR frame" in line for line in lines))

    def test_leaves_the_menu_when_the_game_never_draws_or_the_player_opened_it(self):
        never = []
        hidden, lines = self.worker("boot only\n", lambda e: never.append(e))
        self.assertEqual((hidden, never), (0, []))
        self.assertIn("no VR frames logged", lines[0])

        hidden, lines = self.worker("FrameBridge: pacing: 72 fps\n", lambda e: True, max_hides=3,
                                    ui_text="[ToggleDashboard] toggle_dashboard_action\n")
        self.assertLessEqual(hidden, 1)  # at most the one before the press was seen
        self.assertTrue(any("leaving it to the player" in line for line in lines))

        hidden, lines = self.worker("FrameBridge: pacing: 72 fps\n", lambda e: (_ for _ in ()).throw(OSError("refused")))
        self.assertEqual(hidden, 0)  # no devtools port: give up quietly

    def test_steam_js_speaks_to_a_devtools_endpoint(self):
        import socketserver
        from frameload.system import steam_ui
        seen = {}

        class Devtools(socketserver.BaseRequestHandler):
            def handle(self):
                head = b""
                while b"\r\n\r\n" not in head:
                    head += self.request.recv(1024)
                port = self.server.server_address[1]
                if head.startswith(b"GET /json"):
                    body = json.dumps([{"title": "Steam Big Picture Mode", "webSocketDebuggerUrl": "ws://x/other"},
                                       {"title": "SharedJSContext",
                                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/ABC"}]).encode()
                    self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                                         + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
                    return
                seen["path"] = head.split(b" ")[1].decode()
                self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                first, second = self.request.recv(2)
                length = second & 0x7F
                if length == 126:
                    length = int.from_bytes(self.request.recv(2), "big")
                mask = self.request.recv(4)
                data = b""
                while len(data) < length:
                    data += self.request.recv(length - len(data))
                seen["message"] = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
                for reply in ({"method": "Runtime.somethingElse"},
                              {"id": 1, "result": {"result": {"type": "boolean", "value": True}}}):
                    payload = json.dumps(reply).encode()
                    self.request.sendall(bytes([0x81, len(payload)]) + payload)

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Devtools)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        value = steam_ui.steam_js("SteamClient.OpenVR.VROverlay.IsDashboardVisible()", address=server.server_address)
        self.assertIs(value, True)
        self.assertEqual(seen["path"], "/devtools/page/ABC")
        self.assertEqual(seen["message"]["method"], "Runtime.evaluate")
        self.assertEqual(seen["message"]["params"]["expression"], "SteamClient.OpenVR.VROverlay.IsDashboardVisible()")

    def test_vr_launcher_starts_the_helper_and_2d_apps_do_not(self):
        from frameload.installer.lepton_quest import LeptonInstaller
        anchor = os.path.join(self.tmp, "game")
        os.makedirs(anchor)
        vr = LeptonInstaller.write_launcher(anchor, anchor, "a.vr", "VR", 1, hide_dashboard=True)
        with open(vr, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("-m frameload.system.steam_ui", text)
        self.assertIn("FRAMELOAD_KEEP_DASHBOARD", text)
        self.assertLess(text.index("child=$!"), text.index("frameload.system.steam_ui"))
        flat = LeptonInstaller.write_launcher(anchor, anchor, "a.flat", "Flat", 2)
        with open(flat, encoding="utf-8") as f:
            self.assertNotIn("steam_ui", f.read())


class TestStop(TempCase):
    def test_stop_kills_the_games_container_and_reports_honestly(self):
        self.patch(InstalledManager, "get_game", return_value={"package": "a.b", "appid": 77})
        self.patch("time.sleep")
        running = {"lepton-steamlaunch-77", "lepton-steamlaunch-88", "some-other-container"}
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            result = type("R", (), {"stdout": "", "returncode": 0})()
            if cmd[:2] == ["podman", "ps"]:
                result.stdout = "\n".join(sorted(running))
            elif cmd[:2] == ["podman", "kill"]:
                running.discard(cmd[2])
            return result

        self.patch("subprocess.run", side_effect=fake_run)
        res = GameLauncher.stop("a.b")
        self.assertEqual((res["success"], res["stopped"]), (True, True))
        self.assertIn(["podman", "kill", "lepton-steamlaunch-77"], calls)

        again = GameLauncher.stop("a.b")
        self.assertEqual((again["success"], again["stopped"]), (True, False))  # already gone

        everything = GameLauncher.stop_all()
        self.assertEqual((everything["stopped"], everything["running"]), (1, 1))
        self.assertEqual(running, {"some-other-container"})  # only Lepton games are touched

    def test_container_that_survives_kill_is_removed(self):
        self.patch(InstalledManager, "get_game", return_value={"package": "a.b", "appid": 5})
        self.patch("time.sleep")
        running = {"lepton-steamlaunch-5"}

        def fake_run(cmd, **kwargs):
            result = type("R", (), {"stdout": "", "returncode": 0})()
            if cmd[:2] == ["podman", "ps"]:
                result.stdout = "\n".join(running)
            elif cmd[:3] == ["podman", "rm", "-f"]:
                running.discard(cmd[3])
            return result

        self.patch("subprocess.run", side_effect=fake_run)
        self.assertTrue(GameLauncher.stop("a.b")["stopped"])


class TestBackups(TempCase):
    def setUp(self):
        super().setUp()
        self.base = os.path.join(self.tmp, "game")
        self.patch(InstalledManager, "get_game", return_value={"package": "com.a", "base": self.base})
        self.patch("frameload.manager.backup.BACKUP_DIR", os.path.join(self.tmp, "backups"))
        self.patch(fsutil, "podman", return_value=None)
        self.write("game", "lepton-data", "internal", "com.a", "files", "save.dat", data="private save")
        self.write("game", "lepton-data", "external", "Android", "data", "com.a", "files", "song.dat", data="shared")
        self.write("game", "lepton-data", "external", "Android", "obb", "com.a", "main.obb", data="big game data")

    def test_backup_holds_private_and_shared_saves_but_not_game_data(self):
        res = SaveBackupManager.backup_saves("com.a")
        self.assertEqual(res["includes"], ["internal", "external"])
        with tarfile.open(res["path"]) as tar:
            names = tar.getnames()
        self.assertIn("internal/com.a/files/save.dat", names)
        self.assertIn("external/Android/data/com.a/files/song.dat", names)
        self.assertFalse(any("obb" in n for n in names))

        shutil.rmtree(os.path.join(self.base, "lepton-data", "internal"))
        self.assertTrue(SaveBackupManager.restore_backup("com.a", res["filename"]))
        with open(os.path.join(self.base, "lepton-data", "internal", "com.a", "files", "save.dat")) as f:
            self.assertEqual(f.read(), "private save")
        self.assertEqual([b["filename"] for b in SaveBackupManager.list_backups("com.a")], [res["filename"]])
        self.assertEqual(SaveBackupManager.list_backups("com"), [])  # another package's prefix

    def test_restore_refuses_foreign_and_tampered_archives(self):
        backups = os.path.join(self.tmp, "backups")
        os.makedirs(backups)
        evil = os.path.join(backups, "com.a_save_20260101_000000.tar.gz")
        with tarfile.open(evil, "w:gz") as tar:
            info = tarfile.TarInfo("../../escaped.txt")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(ValueError):
            SaveBackupManager.restore_backup("com.a", os.path.basename(evil))
        for name in ("com.b_save_20260101_000000.tar.gz", "../x.tar.gz", "com.a_save_x.tar.gz"):
            with self.assertRaises(ValueError):
                SaveBackupManager.restore_backup("com.a", name)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escaped.txt")))


class TestFsAndStorage(TempCase):
    def test_move_tree_copies_verifies_and_refuses_to_overwrite(self):
        self.patch(fsutil, "podman", return_value=None)
        src = os.path.join(self.tmp, "src")
        self.write("src", "a", "one.bin", data="111")
        dst = os.path.join(self.tmp, "dst", "game")
        with patch("os.rename", side_effect=OSError("cross-device")):
            fsutil.move_tree(src, dst)
        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.isfile(os.path.join(dst, "a", "one.bin")))
        self.write("src2", "f")
        with self.assertRaises(FileExistsError):
            fsutil.move_tree(os.path.join(self.tmp, "src2"), dst)

    def test_filesystem_lookup_and_unsupported_cards(self):
        mounts = {"/": "btrfs", "/run/media/steamos/CARD": "exfat", "/run/media/steamos/CARD2": "ext4"}
        if os.name != "nt":  # POSIX paths: Windows rewrites them with a drive letter
            self.assertEqual(fsutil.filesystem_of("/run/media/steamos/CARD/quest-frame", mounts), "exfat")
            self.assertEqual(fsutil.filesystem_of("/run/media/steamos/CARD2", mounts), "ext4")
            self.assertEqual(fsutil.filesystem_of("/home/steamos", mounts), "btrfs")
        self.assertFalse(fsutil.supports_lepton("exfat"))
        self.assertTrue(fsutil.supports_lepton("ext4"))

        devices = [{"id": "ext_CARD", "name": "MicroSD Card (CARD)", "path": self.tmp, "is_external": True,
                    "filesystem": "exfat", "supports_lepton": False}]
        with patch.object(StorageManager, "get_devices", return_value=devices):
            with self.assertRaises(OSError) as ctx:
                StorageManager.resolve_anchor("ext_CARD")
            self.assertIn("exfat", str(ctx.exception))
            with self.assertRaises(FileNotFoundError):
                StorageManager.resolve_anchor("ext_REMOVED")  # no silent switch to internal storage


class TestAccess(TempCase):
    def setUp(self):
        super().setUp()
        self.patch(access, "PAIRED_FILE", os.path.join(self.tmp, "paired.json"))
        access._code.update(value="", expires=0.0, attempts=0)

    def test_code_works_once_and_is_withdrawn_after_wrong_guesses(self):
        self.assertIsNone(access.redeem("123456"))  # no code issued
        code = access.new_code()["code"]
        self.assertRegex(code, r"^\d{6}$")
        token = access.redeem(code, "Phone")
        self.assertTrue(access.is_valid(token))
        self.assertIsNone(access.redeem(code))  # used
        self.assertFalse(access.is_valid("guess"))
        self.assertNotIn(token, open(access.PAIRED_FILE).read())  # only a hash is stored

        code = access.new_code()["code"]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(access.MAX_ATTEMPTS):
            self.assertIsNone(access.redeem(wrong))
        self.assertIsNone(access.redeem(code))  # withdrawn

        device = access.devices()[0]
        self.assertEqual(device["label"], "Phone")
        self.assertEqual(access.revoke(device["id"]), 1)
        self.assertFalse(access.is_valid(token))

    def test_loopback_detection(self):
        for local in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(access.is_loopback(local), local)
        for remote in ("192.168.1.20", "10.0.0.2", "fe80::1%wlan0", "nonsense"):
            self.assertFalse(access.is_loopback(remote), remote)


class TestRemoteDevices(TempCase):
    """The same server, as seen from another machine on the network."""

    def setUp(self):
        super().setUp()
        self.patch(access, "PAIRED_FILE", os.path.join(self.tmp, "paired.json"))
        self.patch(file_manager, "UPLOAD_DIR", os.path.join(self.tmp, "uploads"))
        self.remote = self.patch(FrameLoadApiHandler, "client_is_local", return_value=False)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, cookie="", raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            headers = {"Cookie": cookie} if cookie else {}
            if payload is not None:
                headers["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def test_unpaired_device_gets_the_pairing_page_and_nothing_else(self):
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"pairing-code", body)
        self.assertNotIn(b"sideload-form", body)
        self.assertEqual(self.request("GET", "/api/config")[0], 401)
        self.assertEqual(self.request("GET", "/api/installed")[0], 401)
        self.assertEqual(self.request("POST", "/api/system/uninstall-app", {"confirm": "UNINSTALL"})[0], 401)
        self.assertEqual(self.request("POST", "/api/upload?session=abcdef12&name=a.apk", raw=b"x")[0], 401)
        self.assertEqual(self.request("GET", "/static/css/style.css")[0], 200)

    def test_artwork_is_served_as_what_it_really_is(self):
        self.remote.return_value = True
        self.patch("frameload.server.ANCHOR_DIR", self.tmp)
        self.patch(InstalledManager, "get_game", return_value=None)
        # An older version saved an SVG placeholder under a .png name; the real icon follows it.
        self.write("a.game", "artwork", "poster.png", data=b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        self.write("a.game", "artwork", "icon.png", data=b"\xff\xd8\xff\xe0 jpeg saved as png")
        status, headers, body = self.request("GET", "/api/installed/artwork/a.game")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/jpeg"))
        self.assertTrue(body.startswith(b"\xff\xd8\xff"))

        self.write("b.game", "artwork", "poster.png", data=b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        self.assertEqual(self.request("GET", "/api/installed/artwork/b.game")[0], 404)  # the page shows its own fallback

    def test_downloads_poll_names_the_running_porting_job(self):
        from frameload.installer import porting
        self.remote.return_value = True
        self.patch(porting.PortingJobs, "_jobs", {"j1": {"id": "j1", "status": "done"}, "j2": {"id": "j2", "status": "queued"}})
        _, _, body = self.request("GET", "/api/downloads")
        self.assertEqual(json.loads(body)["porting_job"], "j2")
        porting.PortingJobs._jobs["j2"]["status"] = "failed"
        self.assertEqual(json.loads(self.request("GET", "/api/downloads")[2])["porting_job"], "")

    def test_pairing_with_the_headsets_code_grants_access(self):
        self.assertEqual(self.request("POST", "/api/pair", {"code": "000000"})[0], 403)
        code = access.new_code()["code"]
        status, headers, _ = self.request("POST", "/api/pair", {"code": code, "label": "Laptop"})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

        self.assertEqual(self.request("GET", "/api/tuning/presets", cookie=cookie)[0], 200)
        self.assertIn(b"sideload-form", self.request("GET", "/", cookie=cookie)[2])
        # A paired device still cannot let further devices in, or remove them.
        self.assertEqual(self.request("POST", "/api/access/code", {}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/access/revoke", {}, cookie=cookie)[0], 403)

        self.remote.return_value = True  # at the headset
        self.assertEqual(self.request("POST", "/api/access/revoke", {})[0], 200)
        self.remote.return_value = False
        self.assertEqual(self.request("GET", "/api/tuning/presets", cookie=cookie)[0], 401)

    def test_upload_from_a_paired_device_and_file_browser(self):
        token = access.redeem(access.new_code()["code"], "Phone")
        cookie = f"{access.COOKIE_NAME}={token}"
        payload = b"PK\x03\x04" + b"apk-bytes" * 1000
        status, _, body = self.request("POST", "/api/upload?session=abcdef12&name=My%20Game.apk", raw=payload, cookie=cookie)
        self.assertEqual(status, 200, body)
        info = json.loads(body)
        self.assertEqual(info["size"], len(payload))
        with open(info["path"], "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertTrue(info["path"].startswith(file_manager.UPLOAD_DIR))

        for bad in ("session=abcdef12&name=evil.sh", "session=../../x&name=a.apk", "session=abcdef12&name=..%2F..%2Fa.apk"):
            status, _, body = self.request("POST", f"/api/upload?{bad}", raw=b"x", cookie=cookie)
            if status == 200:  # a traversal in the name is reduced to its last component
                self.assertTrue(json.loads(body)["path"].startswith(file_manager.UPLOAD_DIR))
            else:
                self.assertEqual(status, 400, bad)

        listing = json.loads(self.request("GET", "/api/files", cookie=cookie)[2])
        self.assertIn("Received from other devices", [e["name"] for e in listing["entries"]])
        self.assertEqual(self.request("GET", "/api/files?path=/etc", cookie=cookie)[0], 403)
        self.assertEqual(file_manager.upload_session_of(info["path"]), os.path.dirname(os.path.realpath(info["path"])))
        file_manager.discard_upload(info["path"])
        self.assertFalse(os.path.exists(info["path"]))


class TestUpdater(TempCase):
    def tarball(self, entries):
        path = os.path.join(self.tmp, "frameload-v9.9.9-standalone.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            for name, data in entries.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path

    def test_checksum_lookup_and_safe_extraction(self):
        sums = "abc123  frameload-installer.sh\nDEF456 *dist/frameload-v9.9.9-standalone.tar.gz\n"
        self.assertEqual(updates.expected_sha256(sums, "frameload-v9.9.9-standalone.tar.gz"), "def456")
        self.assertEqual(updates.expected_sha256(sums, "other.tar.gz"), "")

        dest = os.path.join(self.tmp, "app")
        os.makedirs(dest)
        updates.safe_extract(self.tarball({"frameload/__init__.py": b"v = 1\n", "run.sh": b"#!/bin/bash\n"}), dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "frameload", "__init__.py")))
        with self.assertRaises(ValueError):
            updates.safe_extract(self.tarball({"../outside.py": b"x"}), dest)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "outside.py")))

    def test_update_with_wrong_checksum_changes_nothing(self):
        archive = self.tarball({"frameload/marker.txt": b"new"})
        with open(archive, "rb") as f:
            data = f.read()
        root = os.path.join(self.tmp, "install")
        os.makedirs(root)
        self.patch(updates, "ROOT_DIR", root)
        self.patch(updates, "CACHE_DIR", os.path.join(self.tmp, "cache"))
        status = {"latest_tag": "v9.9.9", "download_url": "https://example.org/frameload-v9.9.9-standalone.tar.gz",
                  "checksums_url": "https://example.org/SHA256SUMS"}
        self.patch(updates.UpdateManager, "check_app_update", return_value=status)
        self.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: io.BytesIO(data))
        popen = self.patch("subprocess.Popen")

        with patch.object(updates, "_fetch", return_value=b"0" * 64 + b"  frameload-v9.9.9-standalone.tar.gz\n"):
            res = updates.UpdateManager.perform_app_update()
        self.assertFalse(res["success"])
        self.assertIn("checksum", res["error"])
        self.assertEqual(os.listdir(root), [])
        popen.assert_not_called()

        good = hashlib.sha256(data).hexdigest().encode() + b"  frameload-v9.9.9-standalone.tar.gz\n"
        with patch.object(updates, "_fetch", return_value=good):
            res = updates.UpdateManager.perform_app_update()
        self.assertTrue(res["success"], res)
        self.assertTrue(os.path.isfile(os.path.join(root, "frameload", "marker.txt")))

        self.patch(updates.UpdateManager, "check_app_update", return_value={"latest_tag": "v9.9.9", "download_url": "x"})
        self.assertFalse(updates.UpdateManager.perform_app_update()["success"])  # no checksums: refuse

    def test_update_check_is_cached(self):
        updates._check_cache.update(time=0.0, data=None)
        with patch.object(updates.UpdateManager, "_check_app_update_now", return_value={"has_update": False}) as check:
            updates.UpdateManager.check_app_update()
            updates.UpdateManager.check_app_update()
            self.assertEqual(check.call_count, 1)
            updates.UpdateManager.check_app_update(force=True)
            self.assertEqual(check.call_count, 2)
        updates._check_cache.update(time=0.0, data=None)


class TestLaunchLog(TempCase):
    def test_diagnoses_known_failures(self):
        def titles(text):
            return [f["title"] for f in launchlog.diagnose(text.splitlines())]

        self.assertIn("The APK has no launcher activity", titles("boot\nERROR: APP_ACTIVITY is empty, check APK metadata?\nEarly-exit"))
        self.assertIn("podman ran out of kernel keyrings", titles("Error: create keyring: Disk quota exceeded"))
        self.assertIn("Android refused to install the APK", titles("App installation failed!"))
        self.assertEqual(titles("FrameBridge: pacing: 72 fps (x)\nFrameBridge: pacing: 90 fps (y)"), ["The game was running (90 fps)"])
        self.assertEqual(titles("nothing special"), ["No known problem found in the log"])
        # An error outranks an earlier sign of life.
        self.assertNotIn("The game was running (72 fps)", titles("FrameBridge: pacing: 72 fps\nFatal signal 11 (SIGSEGV)"))

    def test_started_but_never_drew_a_frame(self):
        titles = [f["title"] for f in launchlog.diagnose(["FrameBridge: adapter loaded", "FrameBridge: session FOCUSED"])]
        self.assertEqual(titles, ["The game started but has not shown a VR frame"])
        titles = [f["title"] for f in launchlog.diagnose(["FrameBridge: adapter loaded", "FrameBridge: pacing: 72 fps"])]
        self.assertEqual(titles, ["The game was running (72 fps)"])

    def test_reads_the_tail_of_the_log(self):
        base = os.path.join(self.tmp, "game")
        self.patch(InstalledManager, "get_game", return_value={"package": "a.b", "base": base})
        self.assertFalse(launchlog.read_log("a.b")["exists"])
        self.write("game", "launch.log", data="\n".join(f"line {i}" for i in range(1000)) + "\n\x1b[31mApp installation failed!\x1b[0m\n")
        log = launchlog.read_log("a.b")
        self.assertTrue(log["exists"] and log["truncated"])
        self.assertEqual(len(log["lines"]), launchlog.MAX_LINES)
        self.assertEqual(log["lines"][-1], "App installation failed!")
        self.assertEqual(log["findings"][0]["severity"], "error")


class TestArtworkAndUpdates(TempCase):
    def test_real_icon_is_used_and_misses_are_remembered(self):
        png = artwork.gradient_png(4, 4, (255, 0, 0), (0, 0, 255))
        self.assertEqual(artwork.image_extension(png), ".png")
        self.assertEqual(artwork.image_extension(b"\xff\xd8\xff\xe0rest"), ".jpg")
        self.assertEqual(artwork.image_extension(b"<svg/>"), "")
        self.patch(artwork, "THUMB_DIR", os.path.join(self.tmp, "thumbs"))
        artwork._misses.clear()

        with patch.object(artwork, "_download", return_value=png) as download:
            art = artwork.ArtworkManager.ensure_artwork("org.app", "App", os.path.join(self.tmp, "art"),
                                                        icon_url="https://f-droid.org/repo/icon.png")
        self.assertEqual(download.call_args_list[0][0][0], "https://f-droid.org/repo/icon.png")
        with open(art["icon.png"], "rb") as f:
            self.assertEqual(f.read(), png)

        with patch.object(artwork, "_download", return_value=None) as download:
            self.assertIsNone(artwork.ArtworkManager._fetch_cover_art("org.none", "x", self.tmp))
            first = download.call_count
            self.assertIsNone(artwork.ArtworkManager._fetch_cover_art("org.none", "x", self.tmp))
            self.assertEqual(download.call_count, first)  # not looked up again
        artwork._misses.clear()

    def test_fdroid_updates_for_installed_apps(self):
        self.patch("frameload.catalog.fdroid.FDROID_CACHE_JSON", os.path.join(self.tmp, "cache.json"))
        catalog = FDroidCatalog()
        catalog._set_games([CatalogGame(name="Notes", release_name="org.notes", package_name="org.notes",
                                        version_code="20", version_name="2.0", last_updated="", size_bytes=1,
                                        kind="flat", download_url="https://f-droid.org/repo/n.apk", source="fdroid")])
        installed = [{"package": "org.notes", "kind": "flat", "version_code": "19", "version_name": "1.9", "title": "Notes"},
                     {"package": "com.game", "kind": "quest", "version_code": "1"}]
        with patch.object(InstalledManager, "list_installed", return_value=installed):
            found = catalog.available_updates()
        self.assertEqual([(u["package"], u["installed_version"], u["new_version"]) for u in found], [("org.notes", "1.9", "2.0")])
        installed[0]["version_code"] = "20"
        with patch.object(InstalledManager, "list_installed", return_value=installed):
            self.assertEqual(catalog.available_updates(), [])


if __name__ == "__main__":
    unittest.main()
