"""Unit tests for FrameLoad Storage Manager."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from frameload.manager.storage import StorageManager, format_size, get_dir_size


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


if __name__ == "__main__":
    unittest.main()
