"""Unit tests for FrameLoad Storage Manager."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from frameload.manager.storage import MOVE_HEADROOM, StorageManager, format_size, get_dir_size


class TestStorageManager(unittest.TestCase):
    def test_format_size(self):
        self.assertEqual(format_size(500), "500 B")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(1024 * 1024 * 324.57), "324.57 MB")
        self.assertEqual(format_size(1024 * 1024 * 1024 * 64.62), "64.62 GB")
        self.assertEqual(format_size(1024 * 1024 * 1024 * 1024 * 1.5), "1.50 TB")

    def test_get_dir_size(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.bin")
            with open(file1, "wb") as f:
                f.write(b"0" * 1024)
            sub_dir = os.path.join(tmp_dir, "subdir")
            os.makedirs(sub_dir)
            file2 = os.path.join(sub_dir, "file2.bin")
            with open(file2, "wb") as f:
                f.write(b"0" * 2048)

            total = get_dir_size(tmp_dir)
            self.assertEqual(total, 3072)

    def test_get_devices(self):
        devices = StorageManager.get_devices()
        self.assertTrue(len(devices) >= 1)
        self.assertEqual(devices[0]["id"], "internal")
        self.assertTrue(devices[0]["is_default"])
        self.assertGreater(devices[0]["total_bytes"], 0)

    def test_get_storage_overview(self):
        overview = StorageManager.get_storage_overview()
        self.assertIn("devices", overview)
        self.assertIn("active_device", overview)
        self.assertIn("breakdown", overview)
        self.assertIn("games", overview)
        self.assertIn("cache", overview)
        bd = overview["breakdown"]
        self.assertIn("total_bytes", bd)
        self.assertIn("free_bytes", bd)
        self.assertIn("games_bytes", bd)
        self.assertIn("saves_bytes", bd)
        self.assertIn("shaders_bytes", bd)

    def test_clean_cache(self):
        with tempfile.TemporaryDirectory() as tmp_cache:
            with patch("frameload.manager.storage.CACHE_DIR", tmp_cache):
                sample_file = os.path.join(tmp_cache, "temp_download.zip")
                with open(sample_file, "wb") as f:
                    f.write(b"X" * 4096)
                res = StorageManager.clean_cache(clear_downloads=True)
                self.assertTrue(res["success"])
                self.assertEqual(res["reclaimed_bytes"], 4096)
                self.assertEqual(res["cleaned_files"], 1)

    def test_shader_caches_are_reset_on_every_drive(self):
        import json
        with tempfile.TemporaryDirectory() as tmp_home, tempfile.TemporaryDirectory() as tmp_sd:
            int_anchor = os.path.join(tmp_home, "Applications", "quest-frame")
            shader_dirs = []
            for anchor, pkg in ((int_anchor, "com.internal.game"), (os.path.join(tmp_sd, "quest-frame"), "com.card.game")):
                game = os.path.join(anchor, pkg)
                shaders = os.path.join(game, "lepton-shaders")
                os.makedirs(shaders)
                with open(os.path.join(shaders, "pipeline.bin"), "wb") as f:
                    f.write(b"S" * 1000)
                with open(os.path.join(game, "deployment.json"), "w") as f:
                    json.dump({"package": pkg, "title": pkg}, f)
                shader_dirs.append(shaders)
            devices = [
                {"id": "internal", "name": "Internal Storage", "path": tmp_home, "is_external": False},
                {"id": "ext_card", "name": "microSD Card (card)", "path": tmp_sd, "is_external": True, "is_sd_card": True},
            ]
            with patch("frameload.manager.installed.ANCHOR_DIR", int_anchor), \
                 patch("frameload.manager.storage.ANCHOR_DIR", int_anchor), \
                 patch("frameload.manager.storage.StorageManager.get_devices", return_value=devices), \
                 patch("frameload.system.fsutil.podman", return_value=None):
                res = StorageManager.clean_cache(clear_downloads=False, clear_shaders=True)
            self.assertEqual((res["reclaimed_bytes"], res["cleaned_files"]), (2000, 2))
            for shaders in shader_dirs:
                self.assertEqual(os.listdir(shaders), [])  # emptied; the folder stays for Lepton

    def test_resolve_anchor(self):
        # Default/internal
        internal_anchor = StorageManager.resolve_anchor("internal")
        self.assertTrue(os.path.isdir(internal_anchor))

        # Direct directory path
        with tempfile.TemporaryDirectory() as tmp_sd:
            sd_anchor = StorageManager.resolve_anchor(tmp_sd)
            self.assertTrue(os.path.isdir(sd_anchor))
            self.assertTrue(sd_anchor.endswith("quest-frame"))

    def test_move_game(self):
        with tempfile.TemporaryDirectory() as tmp_home, tempfile.TemporaryDirectory() as tmp_sd:
            int_anchor = os.path.join(tmp_home, "Applications/quest-frame")
            os.makedirs(int_anchor, exist_ok=True)
            pkg = "com.test.game"
            game_dir = os.path.join(int_anchor, pkg)
            os.makedirs(os.path.join(game_dir, "lepton-app"))
            os.makedirs(os.path.join(game_dir, "artwork"))

            # Create dummy deployment.json
            dep = {
                "package": pkg,
                "title": "Test Game",
                "appid": 999999,
                "anchor": game_dir,
                "base": game_dir,
                "device_id": "internal",
                "is_vr": True
            }
            import json
            with open(os.path.join(game_dir, "deployment.json"), "w") as f:
                json.dump(dep, f)

            with open(os.path.join(game_dir, "launch.sh"), "w") as f:
                f.write("#!/bin/bash\necho test\n")

            mock_devices = [
                {"id": "internal", "name": "Internal Storage", "path": tmp_home, "is_external": False, "total_bytes": 10**10, "free_bytes": 5*10**9, "used_bytes": 5*10**9},
                {"id": "ext_microsd", "name": "MicroSD Card", "path": tmp_sd, "is_external": True, "is_sd_card": True, "total_bytes": 10**10, "free_bytes": 8*10**9, "used_bytes": 2*10**9}
            ]

            with patch("frameload.manager.installed.ANCHOR_DIR", int_anchor), \
                 patch("frameload.manager.storage.StorageManager.get_devices", return_value=mock_devices), \
                 patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}):
                res = StorageManager.move_game(pkg, "ext_microsd")
                self.assertTrue(res["success"])
                self.assertTrue(res["moved"])
                self.assertEqual(res["to_device"], "ext_microsd")

                # Verify files were moved
                new_anchor = os.path.join(tmp_sd, "quest-frame", pkg)
                self.assertTrue(os.path.isdir(new_anchor))
                self.assertFalse(os.path.exists(game_dir))

                # Verify updated deployment.json
                with open(os.path.join(new_anchor, "deployment.json"), "r") as f:
                    new_dep = json.load(f)
                self.assertEqual(new_dep["device_id"], "ext_microsd")
                self.assertEqual(new_dep["anchor"], new_anchor)

    def test_move_targets_offer_the_other_drives_that_can_take_the_game(self):
        with tempfile.TemporaryDirectory() as game_dir:
            with open(os.path.join(game_dir, "game.apk"), "wb") as f:
                f.write(b"0" * 4096)
            dep = {"package": "com.test.game", "title": "Test Game", "anchor": game_dir, "device_id": "ext_sd"}
            room = MOVE_HEADROOM + 4096
            devices = [
                {"id": "internal", "name": "Internal Storage (Home)", "device_type": "internal", "free_bytes": room},
                {"id": "ext_sd", "name": "microSD Card (sd)", "device_type": "microsd", "free_bytes": 10 * room,
                 "supports_lepton": True},
                {"id": "ext_stick", "name": "USB Drive (stick)", "device_type": "usb", "free_bytes": 10 * room,
                 "filesystem": "exfat", "supports_lepton": False},
                {"id": "ext_small", "name": "USB Drive (small)", "device_type": "usb", "free_bytes": room - 1,
                 "supports_lepton": True},
            ]
            with patch("frameload.manager.storage.InstalledManager.get_game", return_value=dep), \
                 patch.object(StorageManager, "get_devices", return_value=devices):
                res = StorageManager.move_targets("com.test.game")

        self.assertEqual((res["device_id"], res["size_bytes"]), ("ext_sd", 4096))
        reasons = {d["id"]: d["unusable"] for d in res["devices"]}
        # The drive the game is on is not offered; the others say why they cannot take it.
        self.assertEqual(reasons, {
            "internal": "",
            "ext_stick": "Cannot hold games (exfat)",
            "ext_small": "Not enough free space",
        })

    def test_batch_uninstall_counts_the_space_of_games_on_a_card(self):
        with tempfile.TemporaryDirectory() as card:
            anchor = os.path.join(card, "quest-frame", "com.card.game")
            os.makedirs(anchor)
            with open(os.path.join(anchor, "game.bin"), "wb") as f:
                f.write(b"x" * 4096)
            with patch("frameload.manager.storage.InstalledManager.get_game", return_value={"anchor": anchor}), \
                    patch("frameload.manager.storage.Uninstaller.uninstall", return_value={"success": True}):
                res = StorageManager.batch_uninstall(["com.card.game"])
        self.assertEqual(res["results"][0]["reclaimed_bytes"], 4096)

    def test_move_targets_of_a_game_that_is_not_installed(self):
        with patch("frameload.manager.storage.InstalledManager.get_game", return_value=None):
            with self.assertRaises(FileNotFoundError):
                StorageManager.move_targets("com.not.installed")


if __name__ == "__main__":
    unittest.main()

