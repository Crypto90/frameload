"""Unit tests for FrameLoad core components."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
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
                # Add synthetic manifest text
                zf.writestr("AndroidManifest.xml", b"\x00package\x00com.example.testgame\x00com.oculus.intent.category.VR\x00")

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
        with tempfile.TemporaryDirectory() as tmp_dir:
            ArtworkManager.ensure_artwork("com.test.app", "Test App Title", tmp_dir)
            self.assertTrue(os.path.isfile(os.path.join(tmp_dir, "poster.svg")))
            self.assertTrue(os.path.isfile(os.path.join(tmp_dir, "poster.png")))
            self.assertTrue(os.path.isfile(os.path.join(tmp_dir, "banner.png")))


if __name__ == "__main__":
    unittest.main()
