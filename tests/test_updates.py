"""Unit tests for FrameLoad Updates Manager."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from frameload.manager import updates
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


def _remove_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)  # git's object files are read-only, which stops rmtree on Windows
    func(path)


@unittest.skipUnless(shutil.which("git"), "needs git")
class TestGitInstallUpdate(unittest.TestCase):
    """A git install that cannot fast-forward reports why and changes nothing: no stash, no restart."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fl-git-update-")
        self.addCleanup(shutil.rmtree, self.tmp, onerror=_remove_readonly)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.org",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.org")
        origin, upstream, self.app = (os.path.join(self.tmp, n) for n in ("origin.git", "upstream", "app"))
        self.git(self.tmp, "init", "-q", "--bare", origin)
        os.makedirs(upstream)
        self.git(upstream, "init", "-q")
        self.git(upstream, "checkout", "-q", "-b", "main")
        self.write(upstream, "run.sh", "echo v1\n")
        self.write(upstream, "install.sh", "echo install\n")
        self.git(upstream, "add", ".")
        self.git(upstream, "commit", "-q", "-m", "v1")
        self.git(upstream, "push", "-q", origin, "main")
        self.git(self.tmp, "clone", "-q", "-b", "main", origin, self.app)
        self.write(upstream, "run.sh", "echo v2\n")  # the update the headset has not pulled yet
        self.git(upstream, "commit", "-q", "-am", "v2")
        self.git(upstream, "push", "-q", origin, "main")
        self.old_head = self.git(self.app, "rev-parse", "HEAD")

        # git really runs; install.sh and the service restart are only recorded.
        real_run, real_popen = subprocess.run, subprocess.Popen
        self.calls = []

        def run(args, **kwargs):
            if args[0] == "git":
                return real_run(args, **kwargs)
            self.calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")

        def popen(args, *more, **kwargs):  # subprocess.run starts git through Popen too
            if args[0] == "git":
                return real_popen(args, *more, **kwargs)
            self.calls.append(list(args))
            return MagicMock()
        for p in (patch.object(updates, "ROOT_DIR", self.app),
                  patch.object(updates.subprocess, "run", side_effect=run),
                  patch.object(updates.subprocess, "Popen", side_effect=popen)):
            p.start()
            self.addCleanup(p.stop)

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                               text=True).stdout.strip()

    def write(self, folder, name, text):
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read_run_sh(self):
        with open(os.path.join(self.app, "run.sh"), encoding="utf-8") as f:
            return f.read().strip()

    def ran(self):
        """(install.sh ran, the service restart was started)"""
        return (any(c[0] == "bash" and "--no-restart" in c for c in self.calls),
                any(c[:2] == ["bash", "-c"] for c in self.calls))

    def test_local_changes_block_the_update_and_are_named(self):
        self.write(self.app, "run.sh", "echo my own fix\n")
        res = UpdateManager.perform_app_update()
        self.assertFalse(res["success"])
        self.assertIn("Local changes", res["error"])
        self.assertIn("run.sh", res["error"])
        self.assertEqual(res["local_changes"], ["run.sh"])
        self.assertEqual(self.read_run_sh(), "echo my own fix")  # kept where it was, not stashed
        self.assertEqual(self.git(self.app, "stash", "list"), "")
        self.assertEqual(self.git(self.app, "rev-parse", "HEAD"), self.old_head)
        self.assertEqual(self.ran(), (False, False))

        self.git(self.app, "checkout", "--", "run.sh")
        res = UpdateManager.perform_app_update()
        self.assertTrue(res["success"], res)
        self.assertEqual(self.read_run_sh(), "echo v2")
        self.assertEqual(self.ran(), (True, True))

    def test_any_other_git_failure_is_reported_with_git_output(self):
        self.write(self.app, "notes.txt", "not in the way\n")  # an unrelated local file is not blamed
        self.git(self.app, "remote", "set-url", "origin", os.path.join(self.tmp, "missing.git"))
        res = UpdateManager.perform_app_update()
        self.assertFalse(res["success"])
        self.assertTrue(res["error"].startswith("git pull failed:"), res["error"])
        self.assertIn("missing.git", res["error"])
        self.assertEqual(self.git(self.app, "rev-parse", "HEAD"), self.old_head)
        self.assertEqual(self.ran(), (False, False))


if __name__ == "__main__":
    unittest.main()

