"""Unit tests for automated release notes and changelog extraction."""
from __future__ import annotations

import os
import tempfile
import unittest

from scripts.build_release import create_release_notes, extract_changelog_section, extract_git_commits


class TestReleaseNotes(unittest.TestCase):
    def test_extract_changelog_section_formats(self):
        sample_changelog = """# Changelog

## [v2.0.0] - 2026-10-09
### Added
- Super feature 2.0

---

## [1.9.0] - 2026-10-08
### Fixed
- Bug fix 1.9

## v1.8.0 - 2026-10-07
### Changed
- Refactored something

---
"""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8") as tf:
            tf.write(sample_changelog)
            tf_path = tf.name

        self.addCleanup(lambda: os.unlink(tf_path) if os.path.exists(tf_path) else None)

        sec_200 = extract_changelog_section("v2.0.0", tf_path)
        self.assertIsNotNone(sec_200)
        self.assertIn("Super feature 2.0", sec_200)
        self.assertFalse(sec_200.endswith("---"))

        sec_190 = extract_changelog_section("1.9.0", tf_path)
        self.assertIsNotNone(sec_190)
        self.assertIn("Bug fix 1.9", sec_190)

        sec_180 = extract_changelog_section("v1.8.0", tf_path)
        self.assertIsNotNone(sec_180)
        self.assertIn("Refactored something", sec_180)

        sec_missing = extract_changelog_section("v9.9.9", tf_path)
        self.assertIsNone(sec_missing)

    def test_root_changelog_contains_recent_versions(self):
        """Verifies that the repository's CHANGELOG.md contains authentic entries."""
        for v in ["v1.3.0", "v1.2.9", "v1.2.8", "v1.2.7", "v1.2.6"]:
            sec = extract_changelog_section(v)
            self.assertIsNotNone(sec, f"Missing changelog entry for {v}")
            self.assertGreater(len(sec.strip()), 20)

    def test_create_release_notes_generation(self):
        """Verifies that create_release_notes writes genuine version notes."""
        with tempfile.TemporaryDirectory() as tmp_dist:
            with unittest.mock.patch("scripts.build_release.DIST_DIR", tmp_dist):
                notes_path = create_release_notes("v1.3.0")
                self.assertTrue(os.path.isfile(notes_path))
                with open(notes_path, "r", encoding="utf-8") as f:
                    content = f.read()

                self.assertIn("FrameLoad v1.3.0", content)
                self.assertIn("Steam Frame Virtual Keyboard Auto-Trigger", content)
                self.assertIn("Multi-Word Search Tokenizer", content)
                # Verify it does NOT have the old obsolete static text
                self.assertNotIn("Storage Manager:** Multi-drive overview", content)
