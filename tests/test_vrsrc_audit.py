"""Unit tests for vrSrc mirror spoofing, catalog parsing, thumbnails, and security audit."""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from frameload.catalog.models import CatalogGame, DownloadTask
from frameload.catalog.vrp_mirror import VrpMirror
from frameload.catalog import vrsrc as _vrsrc
from frameload.installer.artwork import ArtworkManager
from frameload.server import FrameLoadApiHandler


class TestVrsrcAudit(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp_dir, ignore_errors=True))

    def test_vrsrc_make_env_preserves_rclone_tls_stack(self):
        env = _vrsrc._make_env()
        # Verify X-API-Key is set
        self.assertIn("RCLONE_HEADER", env)
        self.assertEqual(env["RCLONE_HEADER"], f"X-API-Key: {_vrsrc.VRSRC_API_KEY}")
        # Verify RCLONE_USER_AGENT is NOT forced to Chrome, preventing Cloudflare 403 mismatch
        self.assertNotIn("RCLONE_USER_AGENT", env)
        # Verify proxy vars are stripped
        for var in ("http_proxy", "https_proxy", "all_proxy"):
            self.assertNotIn(var, env)

    def test_gamelist_parsing_mb_and_ratings(self):
        # Create a mock GameList.txt with UTF-8 BOM and MB sizes
        mock_gamelist = os.path.join(self.tmp_dir, "GameList.txt")
        content = (
            "\ufeffGame Name;Release Name;Package Name;Version Code;Last Updated;Size (MB);Downloads;Rating;Rating Count\n"
            "Super VR;Super VR v10+1.0 -VRP;com.super.vr;10;2026-10-01 12:00 UTC;500;125;4.8;42\n"
            "Tiny Tool;Tiny Tool v1+0.1 -NiF;com.tiny.tool;1;2026-09-15 08:00 UTC;2.5;10;0;0\n"
        )
        with open(mock_gamelist, "w", encoding="utf-8") as f:
            f.write(content)

        mirror = VrpMirror()
        parsed = mirror.parse_gamelist_file(mock_gamelist)
        self.assertTrue(parsed)
        self.assertEqual(len(mirror.games), 2)

        g1 = mirror.games_by_pkg.get("com.super.vr")
        self.assertIsNotNone(g1)
        self.assertEqual(g1.name, "Super VR")
        self.assertEqual(g1.version_code, "10")
        # 500 MB converted to bytes
        self.assertEqual(g1.size_bytes, 500 * 1024 * 1024)
        self.assertIn("500.0 MB", g1.size_formatted)
        self.assertEqual(g1.downloads, 125)
        self.assertEqual(g1.rating, 4.8)
        self.assertEqual(g1.rating_count, 42)
        self.assertEqual(g1.thumbnail_url, "/api/thumbnail/com.super.vr")

        g2 = mirror.games_by_pkg.get("com.tiny.tool")
        self.assertIsNotNone(g2)
        self.assertEqual(g2.size_bytes, int(2.5 * 1024 * 1024))
        self.assertEqual(g2.downloads, 10)

    def test_get_game_notes(self):
        notes_dir = os.path.join(self.tmp_dir, ".meta/notes")
        os.makedirs(notes_dir, exist_ok=True)
        note_file = os.path.join(notes_dir, "Custom Game v1 -VRP.txt")
        with open(note_file, "w", encoding="utf-8") as f:
            f.write("Important: Recenter using left menu button.\nAll DLC unlocked.")

        mirror = VrpMirror()
        game = CatalogGame(
            name="Custom Game",
            release_name="Custom Game v1 -VRP",
            package_name="com.custom.game",
            version_code="1",
            last_updated="2026-10-01",
            size_bytes=1000,
        )
        mirror.games = [game]
        mirror.games_by_id = {game.id: game}

        with patch("frameload.catalog.vrp_mirror.DATA_DIR", self.tmp_dir):
            notes = mirror.get_game_notes(game.id)
            self.assertIn("Important: Recenter using left menu button.", notes)
            self.assertIn("All DLC unlocked.", notes)

    def test_artwork_case_insensitive_lookup(self):
        meta_thumb_dir = os.path.join(self.tmp_dir, ".meta/thumbnails")
        os.makedirs(meta_thumb_dir, exist_ok=True)
        # Create an uppercase thumbnail file
        thumb_file = os.path.join(meta_thumb_dir, "COM.TEST.GAME.jpg")
        with open(thumb_file, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

        output_dir = os.path.join(self.tmp_dir, "output_artwork")
        with patch("frameload.installer.artwork.DATA_DIR", self.tmp_dir):
            # Request lowercase package
            art = ArtworkManager.ensure_artwork("com.test.game", "Test Game", output_dir)
            self.assertTrue(os.path.isfile(art.get("poster.png", "")))

    def test_cors_options_preflight(self):
        handler = MagicMock()
        FrameLoadApiHandler.do_OPTIONS(handler)
        handler.send_response.assert_called_once()
        headers = [call[0] for call in handler.send_header.call_args_list]
        self.assertIn("Access-Control-Allow-Origin", [h[0] for h in headers])
        self.assertIn("Access-Control-Allow-Methods", [h[0] for h in headers])

    def test_config_get_descriptor_and_downloader_queue(self):
        from frameload.config import Config
        from frameload.catalog.downloader import Downloader

        # 1. Config.get() returns singleton
        cfg = Config.get()
        self.assertIsInstance(cfg, Config)
        # 2. cfg.get(key, default) returns dictionary value
        storage_cfg = cfg.get("storage", {})
        self.assertIsInstance(storage_cfg, dict)
        self.assertIn("default_device_id", storage_cfg)

        # 3. Downloader.add_to_queue resolves device_id without TypeError
        downloader = Downloader()
        game = CatalogGame(
            name="Queue Test Game",
            release_name="Queue.Test.Game.v1",
            package_name="com.queue.test",
            version_code="1",
            last_updated="2026-10-01",
            size_bytes=50000000,
        )
        task = downloader.add_to_queue(game)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "queued")
        self.assertEqual(task.device_id, "internal")
        self.assertIn("50000000", str(task.total_bytes))

    def test_catalog_downloads_and_ratings_sorting(self):
        mirror = VrpMirror()
        g1 = CatalogGame(name="Game A", release_name="Game.A.v1", package_name="com.a", version_code="1", last_updated="2026-01-01", size_bytes=100, downloads=10, rating=3.5)
        g2 = CatalogGame(name="Game B", release_name="Game.B.v1", package_name="com.b", version_code="1", last_updated="2026-01-02", size_bytes=200, downloads=5000, rating=4.9)
        g3 = CatalogGame(name="Game C", release_name="Game.C.v1", package_name="com.c", version_code="1", last_updated="2026-01-03", size_bytes=50, downloads=250, rating=4.2)
        mirror.games = [g1, g2, g3]

        # Sort by downloads descending (most downloads first)
        res_most = mirror.search(sort_by="downloads", sort_order="desc")
        names_most = [g["name"] for g in res_most["items"]]
        self.assertEqual(names_most, ["Game B", "Game C", "Game A"])

        # Sort by downloads ascending (least downloads first)
        res_least = mirror.search(sort_by="downloads", sort_order="asc")
        names_least = [g["name"] for g in res_least["items"]]
        self.assertEqual(names_least, ["Game A", "Game C", "Game B"])

        # Sort by rating descending
        res_rating = mirror.search(sort_by="rating", sort_order="desc")
        names_rating = [g["name"] for g in res_rating["items"]]
        self.assertEqual(names_rating, ["Game B", "Game C", "Game A"])


if __name__ == "__main__":
    unittest.main()
