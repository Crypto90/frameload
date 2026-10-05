"""Unit tests for newly merged features:
- Windows PCVR & Flat EXEs via Proton
- Linux Native ARM64 Binaries & AppImages
- Mod & Custom Content Injector (Beat Saber custom songs & mod packs)
- Flat Android Window Presets
- One-Click Deep Linking (frameload:// protocol handler)
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from frameload.installer.linux_native import LinuxNativeInstaller
from frameload.installer.windows_proton import WindowsProtonInstaller
from frameload.manager.mods import ModManager
from frameload.system.protocol import ProtocolHandler
from frameload.installer.package_loader import PackageLoader
from frameload.installer.lepton_quest import LeptonInstaller


class TestNewMergedFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp_dir, ignore_errors=True))

    def test_windows_proton_inspection_and_install(self):
        # 1. Create a mock Windows PCVR game directory
        win_game_dir = os.path.join(self.tmp_dir, "HalfLife_VR")
        os.makedirs(win_game_dir)
        exe_file = os.path.join(win_game_dir, "hlvr.exe")
        with open(exe_file, "wb") as f:
            f.write(b"MZ\x90\x00" + b"\x00" * 100)
        # Add openvr_api.dll to trigger VR detection
        with open(os.path.join(win_game_dir, "openvr_api.dll"), "wb") as f:
            f.write(b"MZ\x90\x00")

        # Inspect
        insp = WindowsProtonInstaller.inspect_windows_source(win_game_dir)
        self.assertEqual(insp["source_type"], "windows_proton")
        self.assertTrue(insp["is_vr"])
        self.assertTrue(insp["primary_exe"].endswith("hlvr.exe"))
        self.assertEqual(insp["title"], "HalfLife VR")

        # Install
        target_anchor = os.path.join(self.tmp_dir, "target_anchor")
        with patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}):
            res = WindowsProtonInstaller.install_windows_app(
                source_path=win_game_dir,
                target_anchor=target_anchor,
                title="HalfLife VR"
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["install_type"], "windows_proton")
            self.assertTrue(os.path.isfile(os.path.join(res["anchor"], "launch.sh")))
            self.assertTrue(os.path.isfile(os.path.join(res["anchor"], "deployment.json")))
            self.assertTrue(os.path.isfile(os.path.join(res["anchor"], "app/hlvr.exe")))

            # Check launch script contains Proton environment configuration
            with open(os.path.join(res["anchor"], "launch.sh"), "r") as f:
                script_content = f.read()
                self.assertIn("STEAM_COMPAT_DATA_PATH", script_content)
                self.assertIn("XR_RUNTIME_JSON", script_content)
                self.assertIn("hlvr.exe", script_content)

    def test_linux_native_inspection_and_install(self):
        # 1. Create a mock Linux AppImage
        appimage_path = os.path.join(self.tmp_dir, "RetroGame-arm64.AppImage")
        with open(appimage_path, "wb") as f:
            f.write(b"\x7fELF" + b"\x00" * 100)

        insp = LinuxNativeInstaller.inspect_linux_source(appimage_path)
        self.assertEqual(insp["source_type"], "linux_native")
        self.assertEqual(insp["format"], "appimage")
        self.assertEqual(insp["title"], "RetroGame arm64")

        # Install
        target_anchor = os.path.join(self.tmp_dir, "linux_anchor")
        with patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}):
            res = LinuxNativeInstaller.install_linux_app(
                source_path=appimage_path,
                target_anchor=target_anchor,
                title="RetroGame"
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["install_type"], "linux_native")
            launch_script = os.path.join(res["anchor"], "launch.sh")
            self.assertTrue(os.path.isfile(launch_script))
            # Verify executable permissions
            self.assertTrue(os.access(launch_script, os.X_OK))

    def test_mod_manager_beat_saber_song_injection(self):
        pkg = "com.beatgames.beatsaber"
        anchor = os.path.join(self.tmp_dir, "beatsaber_anchor")
        os.makedirs(anchor)

        # Mock installed deployment
        dep_data = {
            "package_name": pkg,
            "title": "Beat Saber",
            "anchor": anchor
        }
        with open(os.path.join(anchor, "deployment.json"), "w") as f:
            json.dump(dep_data, f)

        with patch("frameload.manager.installed.InstalledManager.get_game", return_value=dep_data):
            # Create a mock custom song zip
            song_zip = os.path.join(self.tmp_dir, "100bills.zip")
            with zipfile.ZipFile(song_zip, "w") as zf:
                zf.writestr("info.dat", json.dumps({"_songName": "100 Bills"}))
                zf.writestr("song.egg", b"OGG_SOUND_DATA")

            res = ModManager.inject_mod(pkg, song_zip, mod_name="100bills")
            self.assertTrue(res["success"])
            self.assertTrue(res["is_custom_song"])
            self.assertEqual(res["files_injected"], 2)

            # Check list_mods
            mods = ModManager.list_mods(pkg)
            self.assertEqual(len(mods), 1)
            self.assertEqual(mods[0]["name"], "100bills")
            self.assertEqual(mods[0]["type"], "custom_song")

            # Check delete_mod
            deleted = ModManager.delete_mod(pkg, mods[0]["id"])
            self.assertTrue(deleted)
            self.assertEqual(len(ModManager.list_mods(pkg)), 0)

    def test_protocol_handler(self):
        # 1. frameload://install
        with patch("frameload.catalog.downloader.Downloader.get") as mock_dl_get:
            mock_dl = mock_dl_get.return_value
            from unittest.mock import MagicMock
            mock_task = MagicMock()
            mock_task.id = "task_1"
            mock_dl.enqueue.return_value = mock_task
            res = ProtocolHandler.handle_url("frameload://install?url=http://example.com/test.zip&pkg=com.beatgames.beatsaber&title=Beat%20Saber")
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "install")
            self.assertEqual(res["package"], "com.beatgames.beatsaber")

        # 2. frameload://sideload
        dummy_file = os.path.join(self.tmp_dir, "mock_game.xapk")
        with open(dummy_file, "w") as f:
            f.write("mock")
        with patch("frameload.installer.package_loader.PackageLoader.install_source", return_value={"success": True}):
            res = ProtocolHandler.handle_url(f"frameload://sideload?path={dummy_file}&title=MockApp&flat=true&preset=tablet")
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "sideload")

        # 3. frameload://launch
        with patch("frameload.manager.launcher.GameLauncher.launch", return_value={"success": True}):
            res = ProtocolHandler.handle_url("frameload://launch?pkg=com.beatgames.beatsaber")
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "launch")

        # 4. frameload://sync
        with patch("frameload.catalog.vrp_mirror.VrpMirror.sync_catalog", return_value=True):
            res = ProtocolHandler.handle_url("frameload://sync")
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "sync")

    def test_flat_window_preset_configuration(self):
        target_anchor = os.path.join(self.tmp_dir, "flat_anchor")
        apk_path = os.path.join(self.tmp_dir, "flat_app.apk")
        with open(apk_path, "wb") as f:
            f.write(b"PK\x05\x06" + b"\x00" * 18)

        with patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}):
            res = LeptonInstaller.install_quest_game(
                package_name="com.test.flatapp",
                title="Flat App",
                apk_path=apk_path,
                target_anchor=target_anchor,
                force_flat=True,
                window_preset="phone"
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["window_preset"], "phone")

            # Verify lepton-window.json
            win_json_path = os.path.join(res["anchor"], "lepton-window.json")
            self.assertTrue(os.path.isfile(win_json_path))
            with open(win_json_path, "r") as f:
                win_cfg = json.load(f)
                self.assertEqual(win_cfg["preset"], "phone")
                self.assertEqual(win_cfg["width"], 900)
                self.assertEqual(win_cfg["height"], 1600)
                self.assertEqual(win_cfg["orientation"], "portrait")

            # Verify launch.sh contains the window environment variables
            with open(os.path.join(res["anchor"], "launch.sh"), "r") as f:
                launch_sh = f.read()
                self.assertIn("LEPTON_FLATSCREEN=1", launch_sh)
                self.assertIn("LEPTON_WINDOW_WIDTH=900", launch_sh)
                self.assertIn("LEPTON_WINDOW_HEIGHT=1600", launch_sh)
                self.assertIn("LEPTON_ORIENTATION=portrait", launch_sh)

if __name__ == "__main__":
    unittest.main()
