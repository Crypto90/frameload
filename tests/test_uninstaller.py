"""Unit tests for FrameLoad clean uninstaller."""
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from frameload.manager.backup import SaveBackupManager
from frameload.manager.storage import StorageManager
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


class TestUninstallKeepsSaves(unittest.TestCase):
    """The dashboard says a game's save data is kept: a backup that fails must not delete the game."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fl-keep-saves-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.anchor = os.path.join(self.tmp, "quest-frame")
        self.backups = os.path.join(self.tmp, "backups")
        self.games = {}
        for pkg in ("com.saved.game", "com.fresh.game"):
            game = os.path.join(self.anchor, pkg)
            os.makedirs(os.path.join(game, "lepton-app"))
            with open(os.path.join(game, "deployment.json"), "w", encoding="utf-8") as f:
                json.dump({"package": pkg, "title": pkg.split(".")[1].title(), "appid": 0}, f)
            self.games[pkg] = game
        # Only one of them has saved anything yet.
        self.save = os.path.join(self.games["com.saved.game"], "lepton-data", "internal", "com.saved.game", "save.dat")
        os.makedirs(os.path.dirname(self.save))
        with open(self.save, "w", encoding="utf-8") as f:
            f.write("level 9")
        for p in (patch("frameload.manager.installed.ANCHOR_DIR", self.anchor),
                  patch("frameload.manager.uninstaller.ANCHOR_DIR", self.anchor),
                  patch("frameload.manager.storage.StorageManager.get_devices", return_value=[]),
                  patch("frameload.manager.backup.BACKUP_DIR", self.backups),
                  patch("frameload.system.fsutil.podman", return_value=None),
                  patch("frameload.manager.uninstaller.subprocess.run")):
            p.start()
            self.addCleanup(p.stop)
        unregister = patch("frameload.manager.uninstaller.unregister_game_from_steam", return_value=True)
        self.unregister = unregister.start()
        self.addCleanup(unregister.stop)

    def backup_fails_for_saved_game(self):
        real_backup = SaveBackupManager.backup_saves

        def backup(pkg):
            if pkg == "com.saved.game":
                raise OSError("disk full")
            return real_backup(pkg)
        return patch.object(SaveBackupManager, "backup_saves", side_effect=backup)

    def test_a_failed_backup_leaves_the_game_installed(self):
        for failure, why in (({"side_effect": OSError("Backup failed: tar: No space left on device")}, "No space left"),
                             ({"return_value": {"success": True, "complete": False}}, "could not be read")):
            with patch.object(SaveBackupManager, "backup_saves", **failure):
                res = Uninstaller.uninstall("com.saved.game", keep_saves=True)
            self.assertFalse(res["success"])
            self.assertTrue(res["backup_failed"])
            self.assertIn("Saved", res["error"])
            self.assertIn("not uninstalled", res["error"])
            self.assertIn(why, res["error"])
            self.assertTrue(os.path.isfile(self.save))
            self.unregister.assert_not_called()

        res = Uninstaller.uninstall("com.saved.game", keep_saves=True)  # the backup works this time
        self.assertTrue(res["success"], res)
        self.assertFalse(os.path.exists(self.games["com.saved.game"]))
        [archive] = os.listdir(self.backups)
        with tarfile.open(os.path.join(self.backups, archive)) as tar:
            self.assertIn("internal/com.saved.game/save.dat", tar.getnames())

    def test_a_game_that_never_saved_still_uninstalls(self):
        res = Uninstaller.uninstall("com.fresh.game", keep_saves=True)
        self.assertTrue(res["success"], res)
        self.assertFalse(os.path.exists(self.games["com.fresh.game"]))
        self.unregister.assert_called_once()

    def test_batch_uninstall_reports_the_game_it_kept(self):
        with patch("frameload.manager.storage.ANCHOR_DIR", self.anchor), self.backup_fails_for_saved_game():
            res = StorageManager.batch_uninstall(["com.saved.game", "com.fresh.game"], keep_saves=True)
        saved, fresh = res["results"]
        self.assertEqual(res["uninstalled_count"], 1)
        self.assertFalse(saved["success"])
        self.assertTrue(saved["backup_failed"])
        self.assertIn("disk full", saved["error"])
        self.assertEqual((saved["title"], saved["reclaimed_bytes"]), ("Saved", 0))
        self.assertTrue(fresh["success"])
        self.assertEqual(res["reclaimed_bytes"], fresh["reclaimed_bytes"])
        self.assertTrue(os.path.isfile(self.save))
        self.assertFalse(os.path.exists(self.games["com.fresh.game"]))

    def test_removing_frameload_with_its_games_keeps_a_game_whose_backup_failed(self):
        home = os.path.join(self.tmp, "home")
        with patch("frameload.manager.uninstaller.HOME", home), \
                patch("frameload.manager.uninstaller.FRAMELOAD_DIR", os.path.join(home, "data")), \
                patch("frameload.manager.uninstaller.unregister_app_from_steam", return_value=True), \
                patch("frameload.installer.porting.backup_signing_keys", return_value=""), \
                self.backup_fails_for_saved_game():
            res = Uninstaller.uninstall_frameload_app(purge_games=True, keep_backups=True, purge_all_data=False,
                                                      remove_install_dir=False, stop_service_last=True)
        self.assertEqual((res["games_removed_count"], res["games_kept_count"]), (1, 1))
        self.assertTrue(os.path.isfile(self.save))
        self.assertFalse(os.path.exists(self.games["com.fresh.game"]))
        self.assertTrue(any("Saved" in line and "disk full" in line for line in res["details"]), res["details"])


class TestWindowsAppSaves(unittest.TestCase):
    def test_a_windows_app_is_not_deleted_as_if_its_data_were_backed_up(self):
        from frameload.manager.backup import NoSaveData
        anchor = tempfile.mkdtemp(prefix="fl-win-")
        self.addCleanup(shutil.rmtree, anchor, True)
        os.makedirs(os.path.join(anchor, "pfx", "pfx", "drive_c"))
        dep = {"package": "win.game", "title": "Win Game", "kind": "pcvr", "anchor": anchor, "base": anchor, "appid": 0}
        with patch("frameload.manager.uninstaller.InstalledManager.get_game", return_value=dep), \
                patch("frameload.manager.backup.SaveBackupManager.backup_saves", side_effect=NoSaveData("none")):
            res = Uninstaller.uninstall("win.game", keep_saves=True)
        self.assertFalse(res["success"])
        self.assertTrue(res["backup_failed"])
        self.assertTrue(res["error"].endswith("."))
        self.assertTrue(os.path.isdir(os.path.join(anchor, "pfx")))


if __name__ == "__main__":
    unittest.main()
