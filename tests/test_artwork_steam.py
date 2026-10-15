"""Steam artwork: the app's own icon from its APK, placeholders the dashboard redraws, and grid files
under the id Steam actually uses."""
from __future__ import annotations

import base64
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axml_builder import _string_pool, build_axml, manifest, ref  # noqa: E402
from frameload.installer import artwork  # noqa: E402
from frameload.installer.artwork import ArtworkManager, gradient_png  # noqa: E402
from frameload.installer.axml import read_manifest, resource_files  # noqa: E402
from frameload.system import shortcuts  # noqa: E402
from frameload.system.steam_vdf import vdf_decode, vdf_encode  # noqa: E402

ICON_ID, FG_ID, BG_ID = 0x7F020000, 0x7F030001, 0x7F030000
PNG_SMALL = gradient_png(48, 48, (10, 20, 30), (40, 50, 60))
PNG_LARGE = gradient_png(192, 192, (10, 20, 30), (40, 50, 60))


def build_arsc(entries):
    """entries: {(type_id, entry_id, density): string value}, all in package 0x7F."""
    strings = sorted(set(entries.values()))
    chunks = b""
    for type_id, density in sorted({(t, d) for t, _, d in entries}):
        items = {e: strings.index(v) for (t, e, d), v in entries.items() if t == type_id and d == density}
        count = max(items) + 1
        header = 20 + 64
        offsets, body = [], b""
        for e in range(count):
            if e in items:
                offsets.append(len(body))
                body += struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, 0x03, items[e])
            else:
                offsets.append(0xFFFFFFFF)
        start = header + 4 * count
        config = struct.pack("<I", 64) + b"\x00" * 10 + struct.pack("<H", density) + b"\x00" * 48
        chunks += (struct.pack("<HHIBBHII", 0x0201, header, start + len(body), type_id, 0, 0, count, start)
                   + config + struct.pack(f"<{count}I", *offsets) + body)
    package = struct.pack("<HHII", 0x0200, 288, 288 + len(chunks), 0x7F) + b"\x00" * 256 + b"\x00" * 20 + chunks
    payload = _string_pool(strings) + package
    return struct.pack("<HHII", 0x0002, 12, 12 + len(payload), 1) + payload


def apk(path, icon=ref(ICON_ID), arsc=None, files=None):
    node = manifest("com.art.game")
    if icon is not None:
        node[2][-1][1]["icon"] = icon  # <application android:icon=...>
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", build_axml(node))
        if arsc is not None:
            zf.writestr("resources.arsc", arsc)
        for name, data in (files or {}).items():
            zf.writestr(name, data)
    return path


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.art = os.path.join(self.tmp, "artwork")


class TestApkIcon(Case):
    def test_the_sharpest_launcher_icon_is_taken(self):
        arsc = build_arsc({(2, 0, 160): "res/mipmap-mdpi/app_icon.png", (2, 0, 640): "res/mipmap-xxxhdpi/app_icon.png"})
        path = apk(os.path.join(self.tmp, "a.apk"), arsc=arsc, files={
            "res/mipmap-mdpi/app_icon.png": PNG_SMALL, "res/mipmap-xxxhdpi/app_icon.png": PNG_LARGE})
        with zipfile.ZipFile(path) as zf:
            self.assertEqual(read_manifest(zf.read("AndroidManifest.xml")).icon_ref, ICON_ID)
        self.assertEqual(resource_files(arsc, ICON_ID),
                         [(640, "res/mipmap-xxxhdpi/app_icon.png"), (160, "res/mipmap-mdpi/app_icon.png")])
        saved = artwork.extract_apk_icon(path, self.art)
        self.assertTrue(saved.endswith("apk_icon.png"))
        with open(saved, "rb") as f:
            self.assertEqual(f.read(), PNG_LARGE)

    def test_an_adaptive_icon_gives_its_foreground(self):
        adaptive = build_axml(("adaptive-icon", {}, [("background", {"drawable": ref(BG_ID)}, []),
                                                     ("foreground", {"drawable": ref(FG_ID)}, [])]))
        arsc = build_arsc({(2, 0, 0xFFFE): "res/mipmap-anydpi-v26/ic_launcher.xml",
                           (3, 1, 480): "res/drawable-xxhdpi/ic_fg.webp", (3, 0, 480): "res/drawable-xxhdpi/ic_bg.png"})
        webp = b"RIFF\x10\x00\x00\x00WEBPVP8 fake"
        path = apk(os.path.join(self.tmp, "b.apk"), arsc=arsc, files={
            "res/mipmap-anydpi-v26/ic_launcher.xml": adaptive, "res/drawable-xxhdpi/ic_fg.webp": webp,
            "res/drawable-xxhdpi/ic_bg.png": PNG_SMALL})
        saved = artwork.extract_apk_icon(path, self.art)
        self.assertTrue(saved.endswith("apk_icon.webp"))

    def test_without_a_resource_table_the_usual_file_names_are_used(self):
        path = apk(os.path.join(self.tmp, "c.apk"), icon="res/missing.png", files={
            "res/mipmap-hdpi/ic_launcher.png": PNG_SMALL, "res/mipmap-xxhdpi/ic_launcher.png": PNG_LARGE,
            "res/drawable/splash.png": PNG_LARGE + b"bigger"})
        with open(artwork.extract_apk_icon(path, self.art), "rb") as f:
            self.assertEqual(f.read(), PNG_LARGE)
        self.assertIsNone(artwork.extract_apk_icon(apk(os.path.join(self.tmp, "d.apk"), icon=None), self.art))


class TestPlaceholders(Case):
    def test_placeholders_are_known_and_redrawn_pictures_kept(self):
        with patch.object(ArtworkManager, "_fetch_cover_art", return_value=None), \
                patch.object(ArtworkManager, "_local_thumbnail", return_value=None):
            ArtworkManager.ensure_artwork("com.art.game", "Art Game", self.art)
        info = artwork.artwork_info(self.art, "com.art.game", "Art Game")
        self.assertEqual(info["pending"], ["poster", "banner", "hero", "logo", "icon"])
        self.assertFalse(info["cover"] or info["icon"])

        # Installs from before artwork.json: placeholders are recognised by their exact pixels.
        os.remove(os.path.join(self.art, artwork.STATE_FILE))
        with open(os.path.join(self.art, "poster.png"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0 a real cover")
        os.rename(os.path.join(self.art, "poster.png"), os.path.join(self.art, "poster.jpg"))
        info = artwork.artwork_info(self.art, "com.art.game", "Art Game")
        self.assertTrue(info["cover"])
        self.assertEqual(info["pending"], ["banner", "hero", "logo", "icon"])
        self.assertEqual(artwork.read_state(self.art)["poster"], "downloaded")  # remembered

        with open(os.path.join(self.art, "hero.png"), "wb") as f:
            f.write(b"<svg xmlns='http://www.w3.org/2000/svg'/>")  # an old placeholder Steam cannot show
        os.remove(os.path.join(self.art, artwork.STATE_FILE))
        self.assertIn("hero", artwork.artwork_info(self.art, "com.art.game", "Art Game")["pending"])

        artwork.save_composed(self.art, "banner", b"\xff\xd8\xff\xe0 drawn")
        artwork.save_composed(self.art, "logo", PNG_SMALL)
        self.assertEqual(artwork.artwork_info(self.art, "com.art.game")["pending"], ["hero", "icon"])
        self.assertFalse(os.path.exists(os.path.join(self.art, "banner.png")))  # replaced, not doubled
        for slot, data in (("trailer", PNG_SMALL), ("icon", b"\xff\xd8\xff jpeg"), ("hero", b"<svg/>")):
            with self.assertRaises(ValueError):
                artwork.save_composed(self.art, slot, data)


class TestIconSource(Case):
    """The Steam icon is the app's own launcher icon whenever the APK has one, never a copy of the cover."""
    JPEG_COVER = b"\xff\xd8\xff\xe0 a real cover"

    def ensure(self, cover=True):
        cover_path = os.path.join(self.tmp, "cover.jpg")
        with open(cover_path, "wb") as f:
            f.write(self.JPEG_COVER)
        with patch.object(ArtworkManager, "_fetch_cover_art", return_value=None), \
                patch.object(ArtworkManager, "_local_thumbnail", return_value=cover_path if cover else None):
            ArtworkManager.ensure_artwork("com.art.game", "Art Game", self.art)
        return artwork.artwork_info(self.art, "com.art.game", "Art Game")

    def test_with_an_apk_icon_the_cover_stays_out_of_the_icon_slot(self):
        os.makedirs(self.art)
        with open(os.path.join(self.art, "apk_icon.png"), "wb") as f:
            f.write(PNG_LARGE)
        info = self.ensure()
        self.assertTrue(os.path.isfile(os.path.join(self.art, "poster.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.art, "icon.jpg")))
        self.assertEqual(artwork.read_state(self.art)["icon"], "generated")
        self.assertIn("icon", info["pending"])  # the dashboard draws it from apk_icon
        self.assertTrue(info["icon"] and info["cover"])
        self.assertEqual(artwork.steam_icon(self.art), os.path.join(self.art, "icon.png"))

    def test_without_an_icon_of_its_own_the_cover_is_the_icon(self):
        info = self.ensure()
        with open(os.path.join(self.art, "icon.jpg"), "rb") as f:
            self.assertEqual(f.read(), self.JPEG_COVER)
        self.assertNotIn("icon", info["pending"])
        self.assertEqual(artwork.steam_icon(self.art), os.path.join(self.art, "icon.jpg"))

    def test_older_installs_with_the_cover_as_icon_are_redrawn_from_the_apk_icon(self):
        os.makedirs(self.art)
        for name in ("poster.jpg", "icon.jpg"):  # what versions up to v1.3.6 wrote
            with open(os.path.join(self.art, name), "wb") as f:
                f.write(self.JPEG_COVER)
        artwork.write_state(self.art, {"poster": "downloaded", "icon": "downloaded"})
        self.assertNotIn("icon", artwork.artwork_info(self.art, "com.art.game")["pending"])  # no APK icon: keep it
        with open(os.path.join(self.art, "apk_icon.webp"), "wb") as f:
            f.write(b"RIFF\x10\x00\x00\x00WEBPVP8 fake")
        self.assertIn("icon", artwork.artwork_info(self.art, "com.art.game")["pending"])
        artwork.save_composed(self.art, "icon", PNG_SMALL)  # the dashboard's drawing replaces the copy
        self.assertFalse(os.path.exists(os.path.join(self.art, "icon.jpg")))
        self.assertNotIn("icon", artwork.artwork_info(self.art, "com.art.game")["pending"])

    def test_a_downloaded_icon_steam_cannot_show_is_redrawn(self):
        os.makedirs(self.art)
        with open(os.path.join(self.art, "icon.webp"), "wb") as f:
            f.write(b"RIFF\x10\x00\x00\x00WEBPVP8 fake")
        artwork.write_state(self.art, {"icon": "downloaded"})
        self.assertEqual(artwork.steam_icon(self.art), "")
        self.assertIn("icon", artwork.artwork_info(self.art, "com.art.game")["pending"])

    def test_an_install_points_the_shortcut_at_an_icon_that_exists(self):
        from frameload.installer.lepton_quest import LeptonInstaller
        from frameload.manager.tuning import DEFAULTS, TuningManager
        arsc = build_arsc({(2, 0, 640): "res/mipmap-xxxhdpi/app_icon.png"})
        path = apk(os.path.join(self.tmp, "game.apk"), arsc=arsc, files={"res/mipmap-xxxhdpi/app_icon.png": PNG_LARGE})
        cover_path = os.path.join(self.tmp, "cover.jpg")
        with open(cover_path, "wb") as f:
            f.write(self.JPEG_COVER)
        calls = []
        with patch("frameload.installer.lepton_quest.register_game_in_steam",
                   side_effect=lambda **kw: calls.append(kw) or {"success": True}), \
                patch.object(TuningManager, "get_global_tuning", side_effect=lambda: DEFAULTS.copy()), \
                patch.object(ArtworkManager, "_fetch_cover_art", return_value=None), \
                patch.object(ArtworkManager, "_local_thumbnail", return_value=cover_path):
            LeptonInstaller.install_quest_game(package_name="com.art.game", title="Art Game", apk_path=path,
                                               target_anchor=os.path.join(self.tmp, "quest-frame"))
        art = os.path.join(self.tmp, "quest-frame", "com.art.game", "artwork")
        self.assertEqual(calls[0]["icon_path"], os.path.join(art, "icon.png"))
        self.assertTrue(os.path.isfile(calls[0]["icon_path"]))
        self.assertIn("icon", artwork.artwork_info(art, "com.art.game")["pending"])


class TestSteamGrid(Case):
    def setUp(self):
        super().setUp()
        self.steam = os.path.join(self.tmp, "steam")
        os.makedirs(os.path.join(self.steam, "userdata", "111", "config"))
        self.vdf = os.path.join(self.steam, "userdata", "111", "config", "shortcuts.vdf")
        for target, value in ((shortcuts, "STEAM_DIR"),):
            p = patch.object(target, value, self.steam)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(shortcuts, "get_steam_users", return_value=["111"])
        p.start()
        self.addCleanup(p.stop)
        p = patch("frameload.system.steam_session.note_written")
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(self.art)
        for slot in ("poster.jpg", "banner.jpg", "hero.jpg", "logo.png", "icon.png"):
            with open(os.path.join(self.art, slot), "wb") as f:
                f.write(PNG_SMALL)

    def test_grid_files_use_the_id_the_shortcut_already_has(self):
        launch = os.path.join(self.tmp, "game", "launch.sh")
        # Made earlier under another title, so Steam keeps another id than the title gives now.
        with open(self.vdf, "wb") as f:
            f.write(vdf_encode({"shortcuts": {"0": {"appid": 3000000001, "appname": "Old Name", "Exe": f'"{launch}"'}}}))
        result = shortcuts.register_game_in_steam("New Name", launch, os.path.dirname(launch), artwork_dir=self.art)
        self.assertEqual(result["users"]["111"]["appid"], 3000000001)
        grid = sorted(os.listdir(os.path.join(self.steam, "userdata", "111", "config", "grid")))
        self.assertEqual(grid, ["3000000001.jpg", "3000000001_hero.jpg", "3000000001_icon.png",
                                "3000000001_logo.png", "3000000001p.jpg"])
        with open(self.vdf, "rb") as f:
            self.assertEqual(vdf_decode(f.read())["shortcuts"]["0"]["appname"], "New Name")

        # Redrawn artwork goes to the same files.
        os.remove(os.path.join(self.steam, "userdata", "111", "config", "grid", "3000000001_hero.jpg"))
        done = shortcuts.refresh_grid_artwork(launch, self.art)
        self.assertIn("_hero", done["111"])
        self.assertIsNone(shortcuts.refresh_grid_artwork(os.path.join(self.tmp, "other.sh"), self.art).get("111"))

    def test_a_rewrite_keeps_the_players_launch_options(self):
        # Set in Steam (game > Properties), e.g. to keep Steam's menu open; reinstalls and Restart Steam rewrite the entry.
        launch = os.path.join(self.tmp, "game", "launch.sh")
        with open(self.vdf, "wb") as f:
            f.write(vdf_encode({"shortcuts": {"0": {"appid": 3000000002, "appname": "Game", "Exe": f'"{launch}"',
                                                    "LaunchOptions": "FRAMELOAD_KEEP_DASHBOARD=1 %command%"}}}))
        shortcuts.register_game_in_steam("Game", launch, os.path.dirname(launch), artwork_dir=self.art)
        with open(self.vdf, "rb") as f:
            self.assertEqual(vdf_decode(f.read())["shortcuts"]["0"]["LaunchOptions"], "FRAMELOAD_KEEP_DASHBOARD=1 %command%")


    def test_restart_steam_writes_frameload_itself_and_every_game_again(self):
        # Steam writes back the list it read at its start when it exits, which can lack FrameLoad's
        # own entry (installed while Steam was running).
        from frameload.manager.installed import InstalledManager
        from frameload.system import steam_session
        app = os.path.join(self.tmp, "FrameLoad")
        assets = os.path.join(app, "frameload", "web", "static", "assets")
        os.makedirs(assets)
        open(os.path.join(app, "run.sh"), "w").close()
        for name in ("poster.png", "banner.png", "hero.png", "logo.png", "icon.png"):
            with open(os.path.join(assets, name), "wb") as f:
                f.write(PNG_SMALL)
        game = os.path.join(self.tmp, "quest-frame", "com.art.game")
        os.makedirs(game)
        open(os.path.join(game, "launch.sh"), "w").close()
        os.rename(self.art, os.path.join(game, "artwork"))
        os.rename(os.path.join(game, "artwork", "icon.png"), os.path.join(game, "artwork", "icon.jpg"))
        with patch.object(steam_session, "APP_DIR", app), \
                patch.object(InstalledManager, "list_installed", return_value=[
                    {"package": "com.art.game", "title": "Art Game", "anchor": game, "is_vr": True}]):
            self.assertEqual(steam_session.resync_shortcuts(), 2)
        with open(self.vdf, "rb") as f:
            entries = {e["appname"]: e for e in vdf_decode(f.read())["shortcuts"].values()}
        self.assertEqual(entries["FrameLoad"]["Exe"], '"' + os.path.join(app, "run.sh") + '"')
        self.assertEqual(entries["FrameLoad"]["icon"], os.path.join(assets, "icon.png"))
        self.assertEqual(entries["Art Game"]["icon"], os.path.join(game, "artwork", "icon.jpg"))  # the file that is there
        grid = os.listdir(os.path.join(self.steam, "userdata", "111", "config", "grid"))
        own = entries["FrameLoad"]["appid"]
        self.assertEqual(sorted(g for g in grid if g.startswith(str(own))),
                         sorted(f"{own}{s}.png" for s in ("p", "", "_hero", "_logo", "_icon")))


class TestUploadRoute(Case):
    def test_dashboard_drawn_artwork_is_stored_and_sent_to_steam(self):
        import http.client
        import json
        import threading
        from http.server import ThreadingHTTPServer
        from frameload.manager.installed import InstalledManager
        from frameload.server import FrameLoadApiHandler
        anchor = os.path.join(self.tmp, "com.art.game")
        os.makedirs(anchor)
        sent = []
        with patch.object(InstalledManager, "get_game", return_value={"anchor": anchor, "package": "com.art.game"}), \
                patch("frameload.system.shortcuts.refresh_grid_artwork", side_effect=lambda l, a: sent.append(l) or {"111": {}}):
            server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                body = json.dumps({"slots": {"icon": "data:image/png;base64," + base64.b64encode(PNG_SMALL).decode(),
                                             "poster": "data:image/png;base64,!!!not base64"}}).encode()
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                conn.request("POST", "/api/installed/artwork/com.art.game", body=body,
                             headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
                reply = json.loads(conn.getresponse().read())
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(reply["saved"], ["icon"])
        self.assertIn("poster", reply["errors"])
        self.assertTrue(os.path.isfile(os.path.join(anchor, "artwork", "icon.png")))
        self.assertEqual(sent, [os.path.join(anchor, "launch.sh")])


if __name__ == "__main__":
    unittest.main()
