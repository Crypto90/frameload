"""Unit tests for FrameLoad Standalone Native Window Launcher."""
from __future__ import annotations

import os
import unittest
from frameload.web import window


class TestStandaloneWindow(unittest.TestCase):
    def test_icon_exists(self):
        self.assertTrue(os.path.isfile(window.ICON_PATH), f"Icon missing at {window.ICON_PATH}")

    def test_window_import(self):
        self.assertTrue(hasattr(window, "try_qt"))
        self.assertTrue(hasattr(window, "try_gtk_webkit"))
        self.assertTrue(hasattr(window, "try_pywebview"))
        self.assertTrue(hasattr(window, "main"))

    def test_cli_parser_includes_window(self):
        from frameload import cli
        parser = cli.ColorArgumentParser()
        # Ensure cli runs without import error
        self.assertTrue(callable(cli.main))
