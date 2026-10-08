"""Unit tests for FrameLoad core components."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axml_builder import build_axml, manifest  # noqa: E402
from frameload.catalog.models import CatalogGame, DownloadTask
from frameload.installer.apk_patcher import ApkPatcher
from frameload.installer.artwork import ArtworkManager


class TestFrameLoadCore(unittest.TestCase):
    def test_catalog_game_model(self):
        game = CatalogGame(
            name="Superhot VR",
            release_name="Superhot.VR.v1.0.Quest",
            package_name="com.superhot.vr",
            version_code="100",
            last_updated="2026-09-15",
            size_bytes=1024 * 1024 * 850  # 850 MB
        )
        self.assertTrue(len(game.id) > 0)
        self.assertIn("850.0 MB", game.size_formatted)
        d = game.to_dict()
        self.assertEqual(d["name"], "Superhot VR")
        self.assertEqual(d["package_name"], "com.superhot.vr")

    def test_download_task_model(self):
        game = CatalogGame(
            name="Demo Game",
            release_name="Demo.v1",
            package_name="com.demo",
            version_code="1",
            last_updated="2026-10-01",
            size_bytes=1000
        )
        task = DownloadTask(id=game.id, game=game, downloaded_bytes=500, total_bytes=1000)
        self.assertEqual(task.progress_percent, 0)
        task.progress = 0.5
        self.assertEqual(task.progress_percent, 50)

    def test_apk_inspect_synthetic(self):
        # Create a synthetic APK (zip file with AndroidManifest and native libs)
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path, "w") as zf:
                # Add mock OpenXR library
                zf.writestr("lib/arm64-v8a/libopenxr_loader.so", b"mock openxr")
                zf.writestr("lib/arm64-v8a/libil2cpp.so", b"mock unity")
                zf.writestr("AndroidManifest.xml", build_axml(manifest(
                    "com.example.testgame", categories=("android.intent.category.LAUNCHER", "com.oculus.intent.category.VR"))))

            analysis = ApkPatcher.inspect(tmp_path)
            self.assertTrue(analysis.is_vr)
            self.assertEqual(analysis.engine, "Unity")
            self.assertTrue(analysis.has_openxr)
            self.assertEqual(analysis.package_name, "com.example.testgame")
            self.assertEqual(analysis.abi, "arm64-v8a")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_artwork_fallback(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir, \
                patch.object(ArtworkManager, "_fetch_cover_art", return_value=None), \
                patch.object(ArtworkManager, "_local_thumbnail", return_value=None):
            art = ArtworkManager.ensure_artwork("com.test.app", "Test App Title", tmp_dir)
            # Every slot Steam shows gets a real PNG of the right size (SVG is not displayed by Steam).
            import struct
            for name, size in (("poster.png", (600, 900)), ("banner.png", (460, 215)),
                               ("hero.png", (1920, 620)), ("icon.png", (256, 256))):
                with open(os.path.join(tmp_dir, name), "rb") as f:
                    data = f.read(24)
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", name)
                self.assertEqual(struct.unpack(">II", data[16:24]), size, name)
                self.assertIn(name, art)
            self.assertFalse(os.path.exists(os.path.join(tmp_dir, "poster.svg")))


if __name__ == "__main__":
    unittest.main()
