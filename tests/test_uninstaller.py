"""Unit tests for FrameLoad clean uninstaller."""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from frameload.manager.uninstaller import Uninstaller
from frameload.system.shortcuts import remove_shortcut_by_title_or_exe
from frameload.system.steam_vdf import shortcut_appid, vdf_decode, vdf_encode


class TestUninstaller(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="frameload_uninst_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_remove_shortcut_by_title_or_exe(self):
        # Create a mock shortcuts.vdf with FrameLoad and Superhot VR
        fl_appid = shortcut_appid("/usr/bin/frameload", "FrameLoad")
        sh_appid = shortcut_appid("/path/to/superhot", "Superhot VR")

        mock_root = {
            "shortcuts": {
                "0": {
                    "appid": fl_appid,
                    "appname": "FrameLoad",
                    "Exe": "\"/home/deck/Applications/FrameLoad/run.sh\"",
                    "StartDir": "/home/deck/Applications/FrameLoad"
                },
                "1": {
                    "appid": sh_appid,
                    "appname": "Superhot VR",
                    "Exe": "\"/home/deck/Applications/quest-frame/superhot/launch.sh\"",
                    "StartDir": "/home/deck/Applications/quest-frame/superhot"
                }
            }
        }

        vdf_path = os.path.join(self.test_dir, "shortcuts.vdf")
        with open(vdf_path, "wb") as f:
            f.write(vdf_encode(mock_root))

        # Remove FrameLoad
        removed = remove_shortcut_by_title_or_exe(vdf_path, title="FrameLoad", exe_substring="frameload")
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0], fl_appid)

        # Inspect resulting shortcuts.vdf
        with open(vdf_path, "rb") as f:
            data = f.read()
        decoded = vdf_decode(data)
        remaining = list(decoded.get("shortcuts", {}).values())

        # Superhot VR must remain, FrameLoad must be gone
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["appname"], "Superhot VR")

    def test_uninstall_frameload_app_sandbox(self):
        # Mock paths
        mock_home = os.path.join(self.test_dir, "home")
        mock_frameload_dir = os.path.join(mock_home, ".local/share/frameload")
        mock_service_dir = os.path.join(mock_home, ".config/systemd/user")
        mock_desktop_dir = os.path.join(mock_home, ".local/share/applications")

        os.makedirs(mock_frameload_dir, exist_ok=True)
        os.makedirs(os.path.join(mock_frameload_dir, "cache"), exist_ok=True)
        os.makedirs(os.path.join(mock_frameload_dir, "backups"), exist_ok=True)
        os.makedirs(mock_service_dir, exist_ok=True)
        os.makedirs(mock_desktop_dir, exist_ok=True)

        service_file = os.path.join(mock_service_dir, "frameload.service")
        desktop_file = os.path.join(mock_desktop_dir, "frameload.desktop")
        backup_save = os.path.join(mock_frameload_dir, "backups", "save_backup.tar.gz")

        with open(service_file, "w") as f:
            f.write("[Unit]\nDescription=FrameLoad\n")
        with open(desktop_file, "w") as f:
            f.write("[Desktop Entry]\nName=FrameLoad\n")
        with open(backup_save, "w") as f:
            f.write("save_data")

        with patch("frameload.manager.uninstaller.HOME", mock_home), \
             patch("frameload.manager.uninstaller.FRAMELOAD_DIR", mock_frameload_dir), \
             patch("frameload.manager.uninstaller.unregister_app_from_steam", return_value=True), \
             patch("subprocess.run") as mock_sub:

            # Test 1: keep_backups=True
            res = Uninstaller.uninstall_frameload_app(purge_games=False, keep_backups=True, purge_all_data=True, remove_install_dir=False)
            self.assertTrue(res["success"])
            self.assertFalse(os.path.exists(service_file))
            self.assertFalse(os.path.exists(desktop_file))
            self.assertFalse(os.path.exists(os.path.join(mock_frameload_dir, "cache")))
            self.assertTrue(os.path.exists(backup_save))  # Backup preserved!

            # Test 2: keep_backups=False (total purge)
            res2 = Uninstaller.uninstall_frameload_app(purge_games=False, keep_backups=False, purge_all_data=True, remove_install_dir=False)
            self.assertTrue(res2["success"])
            self.assertFalse(os.path.exists(mock_frameload_dir))  # All data purged


if __name__ == "__main__":
    unittest.main()
