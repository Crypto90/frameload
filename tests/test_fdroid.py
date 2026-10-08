"""F-Droid store: index parsing, release selection, search, and checksum-verified downloads."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from frameload.catalog import downloader as downloader_module
from frameload.catalog.downloader import Downloader
from frameload.catalog.fdroid import FDROID_REPO, FDroidCatalog, parse_index, pick_release
from frameload.catalog.models import CatalogGame, DownloadTask

INDEX = {
    "apps": [
        {
            "packageName": "org.example.notes", "suggestedVersionCode": "20", "icon": "org.example.notes.20.png",
            "categories": ["Writing"], "license": "GPL-3.0-only", "lastUpdated": 1750000000000,
            "localized": {"en-US": {"name": "Pocket Notes", "summary": "Plain text notes", "description": "Long text"}},
        },
        {
            "packageName": "org.example.game", "suggestedVersionCode": "5", "categories": ["Games"],
            "lastUpdated": 1760000000000, "antiFeatures": ["NonFreeNet"],
            "localized": {"de": {"name": "Spiel"}, "en-US": {"name": "<img src=x onerror=alert(1)>", "icon": "icon.png"}},
        },
        {"packageName": "org.example.x86only", "suggestedVersionCode": "1", "name": "x86 Only"},
        {"packageName": "org.example.nopackages", "suggestedVersionCode": "1", "name": "Ghost"},
    ],
    "packages": {
        "org.example.notes": [
            {"versionCode": 21, "versionName": "2.1-beta", "apkName": "org.example.notes_21.apk", "hash": "b" * 64,
             "hashType": "sha256", "size": 2100, "minSdkVersion": 24},
            {"versionCode": 20, "versionName": "2.0", "apkName": "org.example.notes_20.apk", "hash": "a" * 64,
             "hashType": "sha256", "size": 2000, "minSdkVersion": 24},
            {"versionCode": 19, "versionName": "1.9", "apkName": "org.example.notes_19.apk", "hash": "9" * 64,
             "hashType": "sha256", "size": 1900},
        ],
        "org.example.game": [
            {"versionCode": 5, "versionName": "0.5", "apkName": "org.example.game_5.apk", "hash": "c" * 64,
             "hashType": "sha256", "size": 9000, "nativecode": ["armeabi-v7a"]},
            {"versionCode": 4, "versionName": "0.4", "apkName": "org.example.game_4.apk", "hash": "d" * 64,
             "hashType": "sha256", "size": 8000, "nativecode": ["armeabi-v7a", "arm64-v8a"]},
        ],
        "org.example.x86only": [
            {"versionCode": 1, "apkName": "x86_1.apk", "hash": "e" * 64, "size": 1, "nativecode": ["x86_64"]},
        ],
    },
}


class TestIndexParsing(unittest.TestCase):
    def setUp(self):
        self.games = {g.package_name: g for g in parse_index(INDEX)}

    def test_only_apps_lepton_can_run_are_listed(self):
        self.assertEqual(set(self.games), {"org.example.notes", "org.example.game"})

    def test_suggested_release_is_offered_not_the_beta(self):
        notes = self.games["org.example.notes"]
        self.assertEqual((notes.version_code, notes.version_name), ("20", "2.0"))
        self.assertEqual(notes.download_url, f"{FDROID_REPO}/org.example.notes_20.apk")
        self.assertEqual(notes.sha256, "a" * 64)
        self.assertEqual(notes.size_bytes, 2000)

    def test_falls_back_to_newest_arm64_release(self):
        game = self.games["org.example.game"]
        self.assertEqual(game.version_code, "4")
        self.assertEqual(game.sha256, "d" * 64)

    def test_metadata_and_icon_urls(self):
        notes, game = self.games["org.example.notes"], self.games["org.example.game"]
        self.assertEqual(notes.name, "Pocket Notes")
        self.assertEqual(notes.summary, "Plain text notes")
        self.assertEqual(notes.kind, "flat")
        self.assertEqual(notes.source, "fdroid")
        self.assertEqual(notes.categories, ["Writing"])
        self.assertEqual(notes.thumbnail_url, f"{FDROID_REPO}/icons-640/org.example.notes.20.png")
        self.assertEqual(game.thumbnail_url, f"{FDROID_REPO}/org.example.game/en-US/icon.png")
        self.assertEqual(game.anti_features, ["NonFreeNet"])

    def test_pick_release_without_usable_candidates(self):
        self.assertIsNone(pick_release({}, []))
        self.assertIsNone(pick_release({}, [{"versionCode": 1, "apkName": "a.apk", "minSdkVersion": 99}]))


class TestCatalogSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        cache = patch("frameload.catalog.fdroid.FDROID_CACHE_JSON", os.path.join(self.tmp, "fdroid_cache.json"))
        cache.start()
        self.addCleanup(cache.stop)
        self.catalog = FDroidCatalog()
        self.catalog._set_games(parse_index(INDEX))

    def test_search_category_and_sort(self):
        with patch.object(FDroidCatalog, "_installed_version_codes", return_value={"org.example.notes": "19"}):
            everything = self.catalog.search(sort_by="downloads")
            self.assertEqual([i["package_name"] for i in everything["items"]], ["org.example.game", "org.example.notes"])
            notes = everything["items"][1]
            self.assertTrue(notes["is_installed"])
            self.assertTrue(notes["update_available"])
            self.assertNotIn("description", notes)

            self.assertEqual(self.catalog.search(query="plain notes")["total_count"], 1)
            self.assertEqual(self.catalog.search(category="Games")["items"][0]["package_name"], "org.example.game")
            by_name = self.catalog.search(sort_by="name", sort_order="asc")["items"]
            self.assertEqual(by_name[1]["package_name"], "org.example.notes")
        self.assertEqual({c["name"] for c in self.catalog.categories()}, {"Games", "Writing"})

    def test_cache_round_trip(self):
        self.catalog.last_sync = "2026-10-08T12:00:00"
        self.catalog.save_cache()
        reloaded = FDroidCatalog()
        self.assertEqual(len(reloaded.games), 2)
        self.assertEqual(reloaded.get_game("org.example.notes").sha256, "a" * 64)
        self.assertEqual(reloaded.get_game(reloaded.games[0].id).package_name, reloaded.games[0].package_name)


class TestVerifiedDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        cache = patch.object(downloader_module, "CACHE_DIR", self.tmp)
        cache.start()
        self.addCleanup(cache.stop)
        self.downloader = Downloader()
        self.payload = b"apk bytes"

    def task(self, sha256):
        game = CatalogGame(name="App", release_name="org.app", package_name="org.app", version_code="1",
                           last_updated="", size_bytes=len(self.payload), kind="flat",
                           download_url="https://f-droid.org/repo/org.app_1.apk", sha256=sha256)
        return DownloadTask(id=game.id, game=game, total_bytes=game.size_bytes)

    def fake_download(self, url, dest, task, max_retries=3):
        with open(dest, "wb") as f:
            f.write(self.payload)
        return True

    def test_matching_checksum_installs_and_cleans_up(self):
        task = self.task(hashlib.sha256(self.payload).hexdigest())
        seen = {}

        def hook(t):
            seen["apk_exists"] = os.path.isfile(t.target_apk)
            t.status = "completed"

        self.downloader.set_complete_hook(hook)
        with patch.object(Downloader, "_download_file", side_effect=self.fake_download):
            self.downloader._execute_download(task)
        self.assertTrue(seen["apk_exists"])
        self.assertEqual(task.status, "completed")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, task.id)))

    def test_wrong_checksum_is_discarded_and_never_installed(self):
        task = self.task("0" * 64)
        self.downloader.set_complete_hook(lambda t: self.fail("must not install an unverified APK"))
        with patch.object(Downloader, "_download_file", side_effect=self.fake_download):
            with self.assertRaises(RuntimeError):
                self.downloader._execute_download(task)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, task.id, f"{task.id}.apk")))

    def test_failed_install_keeps_its_error_status(self):
        task = self.task(hashlib.sha256(self.payload).hexdigest())

        def hook(t):
            t.status = "error"
            t.error_message = "boom"

        self.downloader.set_complete_hook(hook)
        with patch.object(Downloader, "_download_file", side_effect=self.fake_download):
            self.downloader._execute_download(task)
        self.assertEqual((task.status, task.error_message), ("error", "boom"))


if __name__ == "__main__":
    unittest.main()
