"""Unit tests for FrameLoad Updates Manager."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frameload.manager.updates import UpdateManager, parse_version


class TestUpdateManager(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("v2.10.4-beta1"), (2, 10, 4))
        self.assertEqual(parse_version("invalid"), (0, 0, 0))
        self.assertTrue(parse_version("v1.0.1") > parse_version("v1.0.0"))
        self.assertTrue(parse_version("v2.0.0") > parse_version("v1.9.9"))

    def test_check_app_update_structure(self):
        res = UpdateManager.check_app_update()
        self.assertIn("has_update", res)
        self.assertIn("current_version", res)
        self.assertIn("latest_version", res)
        self.assertIn("is_git", res)

    @patch("frameload.manager.installed.InstalledManager.list_installed")
    def test_check_game_updates_mock(self, mock_list):
        mock_list.return_value = [
            {
                "package": "com.test.game",
                "title": "Test Game",
                "installed_time": 1000,
                "settings": {"version_code": "1"}
            }
        ]

        mock_mirror = MagicMock()
        mock_cat_game = MagicMock()
        mock_cat_game.id = "test-id"
        mock_cat_game.package_name = "com.test.game"
        mock_cat_game.name = "Test Game"
        mock_cat_game.version_code = "2"  # newer version
        mock_cat_game.release_name = "Test.Game.v2"
        mock_cat_game.size_formatted = "1.2 GB"
        mock_cat_game.last_updated = "2026-10-01"

        mock_mirror.games_by_pkg = {"com.test.game": mock_cat_game}
        mock_mirror.games = [mock_cat_game]

        res = UpdateManager.check_game_updates(mock_mirror)
        self.assertEqual(res["updates_count"], 1)
        self.assertEqual(res["games"][0]["package"], "com.test.game")
        self.assertEqual(res["games"][0]["new_version_code"], "2")

    @patch("subprocess.Popen")
    @patch("subprocess.run")
    @patch("os.path.isdir")
    def test_perform_app_update_git(self, mock_isdir, mock_run, mock_popen):
        mock_isdir.return_value = True  # is_git
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Already up to date."
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = UpdateManager.perform_app_update()
        self.assertTrue(res["success"])
        self.assertIn("FrameLoad updated successfully", res["message"])
        # Verify install.sh was called with --no-restart
        install_calls = [c for c in mock_run.call_args_list if any("--no-restart" in str(arg) for arg in c[0])]
        self.assertTrue(len(install_calls) >= 1)


if __name__ == "__main__":
    unittest.main()

