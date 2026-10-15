"""Unit tests for PackageLoader (APK, XAPK, ZIP bundles, and loose directories)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axml_builder import build_axml, manifest  # noqa: E402
from axml_builder import manifest as manifest_node  # noqa: E402

from frameload.installer.package_loader import PackageLoader


class TestPackageLoader(unittest.TestCase):
    def test_inspect_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a mock game folder with an APK and OBB folder
            game_folder = os.path.join(tmp_dir, "Beat_Saber_Quest")
            os.makedirs(game_folder)

            # Create dummy APK with a dummy zip structure
            apk_path = os.path.join(game_folder, "base.apk")
            with zipfile.ZipFile(apk_path, "w") as zf:
                zf.writestr("AndroidManifest.xml", build_axml(manifest("com.beatgames.beatsaber")))
                zf.writestr("lib/arm64-v8a/libunity.so", b"dummy")

            # Create matching OBB folder
            obb_folder = os.path.join(game_folder, "com.beatgames.beatsaber")
            os.makedirs(obb_folder)
            with open(os.path.join(obb_folder, "main.100.com.beatgames.beatsaber.obb"), "wb") as f:
                f.write(b"OBBDATA" * 50)

            res = PackageLoader.inspect_source(game_folder)
            self.assertEqual(res["source_type"], "directory")
            self.assertEqual(res["package_name"], "com.beatgames.beatsaber")
            self.assertTrue(res["has_obb"])
            self.assertEqual(res["matched_obb"], obb_folder)
            self.assertTrue(res["primary_apk"].endswith("base.apk"))

    def test_inspect_archive_bundle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a mock .xapk archive
            xapk_path = os.path.join(tmp_dir, "superhot.xapk")
            with zipfile.ZipFile(xapk_path, "w") as zf:
                manifest = {
                    "package_name": "com.superhot.vr",
                    "name": "SUPERHOT VR",
                    "version_code": 42
                }
                zf.writestr("manifest.json", json.dumps(manifest))
                zf.writestr("base.apk", b"PK\x05\x06" + b"\x00" * 18)
                zf.writestr("Android/obb/com.superhot.vr/main.42.com.superhot.vr.obb", b"OBBFILE")

            res = PackageLoader.inspect_source(xapk_path)
            self.assertEqual(res["source_type"], "archive")
            self.assertEqual(res["format"], "xapk")
            self.assertEqual(res["package_name"], "com.superhot.vr")
            self.assertEqual(res["title"], "SUPERHOT VR")
            self.assertTrue(res["has_obb"])
    def test_install_source_xapk(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as tmp_target:
            # Create a mock .xapk archive
            xapk_path = os.path.join(tmp_dir, "app.xapk")
            with zipfile.ZipFile(xapk_path, "w") as zf:
                manifest = {
                    "package_name": "com.test.xapkgame",
                    "name": "Test XAPK Game",
                    "version_code": 1
                }
                zf.writestr("manifest.json", json.dumps(manifest))
                # Create mini APK inside zip
                inner_apk = os.path.join(tmp_dir, "inner.apk")
                with zipfile.ZipFile(inner_apk, "w") as apk_zf:
                    apk_zf.writestr("AndroidManifest.xml", build_axml(manifest_node("com.test.xapkgame")))
                    apk_zf.writestr("lib/arm64-v8a/libopenxr_loader.so", b"dummy")
                with open(inner_apk, "rb") as f:
                    zf.writestr("base.apk", f.read())
                zf.writestr("Android/obb/com.test.xapkgame/main.1.com.test.xapkgame.obb", b"OBBBYTES" * 20)

            with patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}):
                res = PackageLoader.install_source(
                    source_path=xapk_path,
                    target_anchor=tmp_target,
                    device_id="internal"
                )
                self.assertTrue(res["success"])
                self.assertEqual(res["package"], "com.test.xapkgame")
                self.assertTrue(os.path.isdir(res["anchor"]))
                self.assertTrue(os.path.isfile(os.path.join(res["anchor"], "lepton-app/game.apk")))
                self.assertTrue(os.path.isfile(os.path.join(res["anchor"], "deployment.json")))
                # OBB files sit directly in lepton-app/obb, where Lepton looks for them.
                self.assertTrue(os.path.isfile(os.path.join(
                    res["anchor"], "lepton-app", "obb", "main.1.com.test.xapkgame.obb")))


    def test_loose_main_and_patch_obb_are_both_installed(self):
        """An APK uploaded or copied with main.<v>.<pkg>.obb and patch.<v>.<pkg>.obb beside it."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as tmp_target:
            pkg = "com.test.twoobb"
            apk = os.path.join(tmp_dir, "game.apk")
            with zipfile.ZipFile(apk, "w") as zf:
                zf.writestr("AndroidManifest.xml", build_axml(manifest_node(pkg)))
                zf.writestr("lib/arm64-v8a/libopenxr_loader.so", b"dummy")
            obbs = [f"main.3.{pkg}.obb", f"patch.3.{pkg}.obb"]
            for name in obbs + [f"main.1.{pkg}.demo.obb"]:  # another app's OBB in the same folder stays out
                with open(os.path.join(tmp_dir, name), "wb") as f:
                    f.write(b"OBB" * 10)

            for source in (apk, tmp_dir):  # the APK picked on its own, and the whole folder
                self.assertTrue(PackageLoader.inspect_source(source)["has_obb"], source)
                with patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}):
                    res = PackageLoader.install_source(source_path=source, target_anchor=tmp_target, device_id="internal")
                self.assertTrue(res["success"], res)
                self.assertEqual(sorted(os.listdir(os.path.join(res["anchor"], "lepton-app", "obb"))), obbs)


if __name__ == "__main__":
    unittest.main()

