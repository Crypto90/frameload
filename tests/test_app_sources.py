"""App sources for 2D apps: signed repository indexes, several sources in Browse, and where installed apps came from.

The fixtures in tests/fixtures/fdroid_repo/ were made by make_fixtures.py there, with throwaway keys:
FIXTURE_FINGERPRINT signs every index-v1*.jar, OTHER_FINGERPRINT adds the second signature of
index-v1-two-signers.jar.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from axml_builder import manifest, write_apk  # noqa: E402

from frameload import server  # noqa: E402
from frameload.catalog import app_sources, repo_index  # noqa: E402
from frameload.catalog.app_sources import AppSource, AppSources, FDroidCatalog, RepoCatalog  # noqa: E402
from frameload.catalog.downloader import DownloadConflict, Downloader  # noqa: E402
from frameload.catalog.models import CatalogGame, DownloadTask  # noqa: E402
from frameload.catalog.repo_index import IndexSignatureError, RepoIndexError, parse_index, verify_index_jar  # noqa: E402
from frameload.config import Config  # noqa: E402
from frameload.installer import porting  # noqa: E402
from frameload.installer.lepton_quest import LeptonInstaller  # noqa: E402
from frameload.installer.package_loader import PackageLoader  # noqa: E402
from frameload.manager.installed import InstalledManager  # noqa: E402
from frameload.server import FrameLoadApiHandler  # noqa: E402
from frameload.system import access  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "fdroid_repo")
FIXTURE_FINGERPRINT = "93a24cd3d79c799f00a8861dfb05c4ab073107964e49374787a6dbd51a52baab"
OTHER_FINGERPRINT = "a487bbf27c7d459a687b634663073df88bda0d1f71e6e6d25aa494d91ff7d1f0"
FIXTURE_TIMESTAMP = 1760000000000
REPO_URL = "https://repo.example.org/fdroid/repo"
MIRROR_URL = "https://mirror.example.net/fdroid/repo"
WEB = os.path.join(os.path.dirname(HERE), "frameload", "web")


def fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def fixture_index() -> dict:
    with open(os.path.join(FIXTURES, "index-v1.json"), encoding="utf-8") as f:
        return json.load(f)


def rezip(data: bytes, change) -> bytes:
    """The same JAR with change(name, bytes) applied to every entry (None drops it)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            content = change(name, src.read(name))
            if content is not None:
                dst.writestr(name, content)
    return out.getvalue()


def app(pkg, version, signer, name=None, categories=("Internet",)):
    """One app with one release, as an index-v1 document has it."""
    return ({"packageName": pkg, "suggestedVersionCode": str(version), "categories": list(categories),
             "lastUpdated": 1750000000000 + version, "localized": {"en-US": {"name": name or pkg}}},
            [{"versionCode": version, "versionName": f"{version}.0", "apkName": f"{pkg}_{version}.apk",
              "hash": hashlib.sha256(f"{pkg}{version}".encode()).hexdigest(), "hashType": "sha256", "size": 100,
              "signer": signer}])


def index_of(*apps):
    return {"repo": {"timestamp": 1}, "apps": [a for a, _ in apps], "packages": {a["packageName"]: r for a, r in apps}}


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.patch(app_sources, "SOURCES_DIR", os.path.join(self.tmp, "app_sources"))
        self.patch("frameload.catalog.fdroid.FDROID_CACHE_JSON", os.path.join(self.tmp, "fdroid_cache.json"))
        # Sources the player added live in the config (and its file, which the server reads again): restore both.
        cfg = Config.get()
        saved = json.loads(json.dumps(cfg.raw.get("app_sources", {})))
        self.addCleanup(lambda: cfg.__setitem__("app_sources", saved))

    def patch(self, *args, **kwargs):
        p = patch(*args, **kwargs) if isinstance(args[0], str) else patch.object(*args, **kwargs)
        mock = p.start()
        self.addCleanup(p.stop)
        return mock


# ----------------------------------------------------------------------------- built-in sources

class TestBuiltinSources(unittest.TestCase):
    def test_three_pinned_https_sources(self):
        ids = [s.id for s in app_sources.BUILTIN_SOURCES]
        self.assertEqual(ids, ["fdroid", "izzyondroid", "guardian"])
        for src in app_sources.BUILTIN_SOURCES:
            self.assertTrue(src.url.startswith("https://") and not src.url.endswith("/"), src.url)
            self.assertRegex(src.fingerprint, r"^[0-9a-f]{64}$")
            self.assertTrue(src.blurb and src.size_hint)
        # The keys F-Droid, IzzyOnDroid and Guardian Project publish.
        self.assertEqual(app_sources.BUILTIN["fdroid"].fingerprint,
                         "43238d512c1e5eb2d6569f4a3afbf5523418b82e0a3ed1552770abb9a9c9ccab")
        self.assertEqual(app_sources.BUILTIN["izzyondroid"].fingerprint,
                         "3bf0d6abfeae2f401707b6d966be743bf0eee49c2561b9ba39073711f628937a")

    def test_fdroid_catalog_is_the_fdroid_source(self):
        self.assertIs(FDroidCatalog.get(), AppSources.get().source("fdroid"))
        self.assertEqual(FDroidCatalog.get().source.url, "https://f-droid.org/repo")


# ----------------------------------------------------------------------------- the signed index

class TestIndexSignature(unittest.TestCase):
    def setUp(self):
        # The signed bytes as they are inside the jars (a checkout may give index-v1.json other line endings).
        with zipfile.ZipFile(io.BytesIO(fixture("index-v1.jar"))) as z:
            self.json_bytes = z.read("index-v1.json")
        self.assertEqual(json.loads(self.json_bytes), fixture_index())

    def test_every_signing_style_verifies(self):
        # SHA-1 with signed attributes (F-Droid, IzzyOnDroid), SHA-256, and no signed attributes (Guardian Project).
        for name in ("index-v1.jar", "index-v1-sha256.jar", "index-v1-noattr.jar"):
            found, content = verify_index_jar(fixture(name), fingerprint=FIXTURE_FINGERPRINT)
            self.assertEqual((found, content), (FIXTURE_FINGERPRINT, self.json_bytes), name)
        # Without a pinned key it reports the key it found; colons, spaces and case do not matter.
        self.assertEqual(verify_index_jar(fixture("index-v1.jar"))[0], FIXTURE_FINGERPRINT)
        spaced = ":".join(FIXTURE_FINGERPRINT[i:i + 2] for i in range(0, 64, 2)).upper()
        self.assertEqual(verify_index_jar(fixture("index-v1.jar"), fingerprint=spaced)[0], FIXTURE_FINGERPRINT)

    def test_another_key_is_refused(self):
        with self.assertRaisesRegex(IndexSignatureError, "different key"):
            verify_index_jar(fixture("index-v1.jar"), fingerprint=OTHER_FINGERPRINT)
        with self.assertRaises(IndexSignatureError):
            verify_index_jar(fixture("index-v1.jar"), fingerprint="1234")

    def test_a_changed_index_is_refused(self):
        for name in ("index-v1.jar", "index-v1-noattr.jar"):
            changed = rezip(fixture(name), lambda n, b: b.replace(b"Pocket Notes", b"Pocket Nates") if n == "index-v1.json" else b)
            with self.assertRaisesRegex(IndexSignatureError, "does not match"):
                verify_index_jar(changed, fingerprint=FIXTURE_FINGERPRINT)

    def test_a_changed_signature_file_is_refused(self):
        # With and without signed attributes: the .SF file is what the RSA signature covers.
        for name in ("index-v1.jar", "index-v1-noattr.jar"):
            changed = rezip(fixture(name), lambda n, b: b.replace(b"Signature-Version: 1.0", b"Signature-Version: 1.1") if n.endswith(".SF") else b)
            self.assertNotEqual(changed, fixture(name))
            with self.assertRaisesRegex(IndexSignatureError, "signature", msg=name):
                verify_index_jar(changed)

    def test_manifest_digest_falls_back_to_the_entry_section(self):
        # A changed main section breaks the whole-manifest digest, but the entry's own section still matches.
        changed = rezip(fixture("index-v1.jar"), lambda n, b: b.replace(b"Created-By: ", b"Created-By: x") if n.endswith("MANIFEST.MF") else b)
        self.assertEqual(verify_index_jar(changed, fingerprint=FIXTURE_FINGERPRINT)[1], self.json_bytes)
        # A changed entry digest in the manifest breaks both.
        bad = rezip(fixture("index-v1.jar"), lambda n, b: re.sub(rb"SHA1-Digest: \S+", b"SHA1-Digest: AAAAAAAAAAAAAAAAAAAAAAAAAAA=", b)
                    if n.endswith("MANIFEST.MF") else b)
        with self.assertRaises(IndexSignatureError):
            verify_index_jar(bad)
        # Other content with a manifest that lists its digest: the .SF file still holds the old section's digest.
        forged = self.json_bytes.replace(b"Pocket Notes", b"Pocket Nates")
        digest = base64.b64encode(hashlib.sha1(forged).digest())

        def forge(name, data):
            if name == "index-v1.json":
                return forged
            if name.endswith("MANIFEST.MF"):
                return re.sub(rb"SHA1-Digest: \S+", b"SHA1-Digest: " + digest, data)
            return data

        with self.assertRaisesRegex(IndexSignatureError, "manifest does not match"):
            verify_index_jar(rezip(fixture("index-v1.jar"), forge))

    def test_unsigned_and_twice_signed_jars_are_refused(self):
        unsigned = rezip(fixture("index-v1.jar"), lambda n, b: None if n.startswith("META-INF/") else b)
        with self.assertRaisesRegex(IndexSignatureError, "not signed"):
            verify_index_jar(unsigned)
        with self.assertRaisesRegex(IndexSignatureError, "exactly once"):
            verify_index_jar(fixture("index-v1-two-signers.jar"))
        with self.assertRaises(RepoIndexError):
            verify_index_jar(b"<html>not a jar</html>")

    def test_a_second_copy_of_the_index_is_refused(self):
        out = io.BytesIO(fixture("index-v1.jar"))
        with zipfile.ZipFile(out, "a") as z, self.assertWarns(UserWarning):
            z.writestr("index-v1.json", b'{"repo": {}, "apps": []}')
        with self.assertRaisesRegex(IndexSignatureError, "twice"):
            verify_index_jar(out.getvalue())

    def test_declared_size_over_the_cap_is_refused_before_reading(self):
        opened = []
        real_open = zipfile.ZipFile.open

        def spy(z, name, *args, **kwargs):
            opened.append(getattr(name, "filename", name))
            return real_open(z, name, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", spy), self.assertRaisesRegex(RepoIndexError, "larger"):
            verify_index_jar(fixture("index-v1.jar"), max_bytes=1000)
        self.assertEqual(opened, [])
        with self.assertRaises(RepoIndexError) as caught:
            repo_index.read_index_v1(fixture("index-v1.jar"), FIXTURE_FINGERPRINT, max_json=1000)
        self.assertNotIsInstance(caught.exception, IndexSignatureError)


# ----------------------------------------------------------------------------- the apps in an index

class TestParseIndex(unittest.TestCase):
    def setUp(self):
        self.games = parse_index(fixture_index(), base_url=REPO_URL, source="testrepo", source_name="Test Repo")

    def test_only_apps_lepton_can_run(self):
        # x86 only, microG's Google services, an Xposed module and an app that stops before Android 14 are left out.
        self.assertEqual([g.package_name for g in self.games], ["org.example.notes"])

    def test_addresses_point_below_the_repository(self):
        notes = self.games[0]
        self.assertEqual(notes.download_url, f"{REPO_URL}/org.example.notes_20.apk")
        self.assertEqual(notes.thumbnail_url, f"{REPO_URL}/org.example.notes/en-US/icon.png")
        self.assertEqual(notes.screenshots, [f"{REPO_URL}/org.example.notes/en-US/phoneScreenshots/1.png"])
        self.assertEqual((notes.version_code, notes.sha256, notes.signer), ("20", "a" * 64, "c" * 64))
        self.assertEqual((notes.source, notes.source_name), ("testrepo", "Test Repo"))

    def test_fdroid_ids_stay_and_other_sources_get_their_own(self):
        index = fixture_index()
        fdroid = parse_index(index)[0]
        izzy = parse_index(index, "https://apt.izzysoft.de/fdroid/repo", "izzyondroid", "IzzyOnDroid")[0]
        self.assertEqual(fdroid.id, hashlib.md5(b"org.example.notes\n").hexdigest())  # as before app sources
        self.assertNotEqual(fdroid.id, izzy.id)
        self.assertEqual(izzy.release_name, "izzyondroid/org.example.notes")

    def test_unsafe_file_names_are_not_used(self):
        index = fixture_index()
        releases = index["packages"]["org.example.notes"]
        for bad in ("../../etc/passwd", "https://evil.example/x.apk", "/abs.apk", "a?b.apk", "x#y.apk", "a\\b.apk"):
            releases[1]["apkName"] = bad  # the suggested release: the older, safe one is offered instead
            game = parse_index(index, REPO_URL, "testrepo")[0]
            self.assertEqual(game.download_url, f"{REPO_URL}/org.example.notes_19.apk", bad)
        index["apps"][0]["localized"]["en-US"]["icon"] = "../../icon.png"
        self.assertEqual(parse_index(index, REPO_URL, "testrepo")[0].thumbnail_url, "")

    def test_releases_without_sha256_are_not_offered(self):
        index = fixture_index()
        for release in index["packages"]["org.example.notes"]:
            release["hashType"] = "md5"
        self.assertEqual(parse_index(index, REPO_URL, "testrepo"), [])

    def test_mirrors_are_https_only(self):
        repo = fixture_index()["repo"]
        self.assertEqual(repo_index.repo_mirrors(repo, REPO_URL), [MIRROR_URL])
        repo["mirrors"] += ["https://abcdefghijklmnop.onion/fdroid/repo", REPO_URL + "/", "https://u:p@x.example/repo", 5]
        self.assertEqual(repo_index.repo_mirrors(repo, REPO_URL), [MIRROR_URL])


# ----------------------------------------------------------------------------- repository addresses

class TestRepositoryAddresses(unittest.TestCase):
    def test_accepted_forms(self):
        parse = app_sources.parse_repo_url
        self.assertEqual(parse(" https://Example.org/fdroid/repo/ "), ("https://example.org/fdroid/repo", ""))
        self.assertEqual(parse("https://example.org/fdroid/repo/index-v1.jar")[0], "https://example.org/fdroid/repo")
        url, fp = parse(f"fdroidrepos://example.org/fdroid/repo?fingerprint={FIXTURE_FINGERPRINT.upper()}")
        self.assertEqual((url, fp), ("https://example.org/fdroid/repo", FIXTURE_FINGERPRINT))
        self.assertEqual(parse("https://example.org:8443/repo")[0], "https://example.org:8443/repo")

    def test_refused_addresses(self):
        for bad in ("http://example.org/fdroid/repo", "fdroidrepo://example.org/repo", "file:///etc/passwd",
                    "ftp://example.org/repo", "https://user:secret@example.org/repo", "https://127.0.0.1/repo",
                    "https://127.0.0.1:8080/json", "https://10.0.0.5/repo", "https://192.168.1.20/repo",
                    "https://[::1]/repo", "https://169.254.169.254/latest", "https://example.org/a/../b", ""):
            with self.assertRaises(ValueError, msg=bad):
                app_sources.parse_repo_url(bad)

    def test_names_that_resolve_to_local_addresses_are_refused(self):
        def resolve(answer):
            return lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer, port))]

        for local in ("127.0.0.1", "10.1.2.3", "192.168.0.10", "100.64.0.1", "169.254.1.1"):
            with patch("socket.getaddrinfo", resolve(local)), self.assertRaises(app_sources.UnsafeAddressError, msg=local):
                app_sources.check_public_host("https://repo.example.org/fdroid/repo")
        with patch("socket.getaddrinfo", resolve("93.184.216.34")):
            app_sources.check_public_host("https://repo.example.org/fdroid/repo")

    def test_every_connection_is_checked_again(self):
        # DNS can change after a repository was added: the connection itself refuses local addresses.
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443))]
        with patch("socket.getaddrinfo", return_value=answer), patch("socket.socket") as sock, \
                self.assertRaises(app_sources.UnsafeAddressError):
            app_sources._public_create_connection(("repo.example.org", 443), 5)
        sock.assert_not_called()

    def test_redirects_away_from_https_are_refused(self):
        handler = app_sources._HttpsOnlyRedirect()
        req = urllib.request.Request("https://repo.example.org/fdroid/repo/index-v1.jar")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, "http://127.0.0.1:8080/json")
        self.assertIsNotNone(handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://cdn.example.org/x"))

    def test_apk_downloads_use_the_checked_connection(self):
        self.assertIsNone(app_sources.download_opener(""))
        self.assertIsNone(app_sources.download_opener("link"))
        custom = app_sources.download_opener("u12345678")
        self.assertTrue(any(isinstance(h, app_sources._PublicHTTPSHandler) for h in custom.handlers))
        builtin = app_sources.download_opener("fdroid")
        self.assertFalse(any(isinstance(h, app_sources._PublicHTTPSHandler) for h in builtin.handlers))


# ----------------------------------------------------------------------------- syncing a source

class FakeHttp:
    """Stands in for app_sources._http_get: answers by URL, records requests."""

    def __init__(self, answers):
        self.answers = answers  # url -> (status, headers, body) or an exception
        self.calls = []

    def __call__(self, url, headers, limit, public_only):
        self.calls.append((url, dict(headers), public_only))
        answer = self.answers.get(url)
        if answer is None:
            raise urllib.error.URLError("no route")
        if isinstance(answer, BaseException):
            raise answer
        return answer


class TestSync(TempCase):
    def setUp(self):
        super().setUp()
        self.patch(app_sources, "check_public_host", lambda url: None)
        self.source = AppSource("u0000test", "Test Repo", REPO_URL, FIXTURE_FINGERPRINT, builtin=False)
        self.catalog = RepoCatalog(self.source)
        self.jar = fixture("index-v1.jar")

    def sync(self, answers):
        fake = FakeHttp(answers)
        messages = []
        with patch.object(app_sources, "_http_get", fake):
            ok = self.catalog.sync(messages.append)
        return ok, fake.calls, messages

    def test_a_signed_index_is_kept_in_a_cache_of_its_own(self):
        ok, calls, messages = self.sync({f"{REPO_URL}/index-v1.jar": (200, {"ETag": '"v1"'}, self.jar)})
        self.assertTrue(ok, messages)
        self.assertEqual([c[0] for c in calls], [f"{REPO_URL}/index-v1.jar"])
        self.assertTrue(calls[0][2])  # an added repository: public addresses only
        self.assertEqual([g.package_name for g in self.catalog.games], ["org.example.notes"])
        self.assertEqual((self.catalog.repo_timestamp, self.catalog.mirrors, self.catalog.fingerprint, self.catalog.etag),
                         (FIXTURE_TIMESTAMP, [MIRROR_URL], FIXTURE_FINGERPRINT, '"v1"'))
        cache = os.path.join(app_sources.SOURCES_DIR, "u0000test.json")
        self.assertTrue(os.path.isfile(cache))
        reloaded = RepoCatalog(self.source)
        self.assertFalse(reloaded.loaded)  # read from disk only when something needs it
        self.assertEqual(reloaded.games[0].signer, "c" * 64)
        self.assertEqual(reloaded.repo_timestamp, FIXTURE_TIMESTAMP)
        self.assertIn("Test Repo", messages[-1])

    def test_not_modified_keeps_the_cache(self):
        self.sync({f"{REPO_URL}/index-v1.jar": (200, {"ETag": '"v1"'}, self.jar)})
        ok, calls, messages = self.sync({f"{REPO_URL}/index-v1.jar": (304, {}, b"")})
        self.assertTrue(ok)
        self.assertEqual(calls[0][1].get("If-None-Match"), '"v1"')
        self.assertEqual(len(self.catalog.games), 1)
        self.assertIn("up to date", messages[-1])

    def test_an_older_index_is_refused(self):
        self.catalog.repo_timestamp = FIXTURE_TIMESTAMP + 1
        ok, _, messages = self.sync({f"{REPO_URL}/index-v1.jar": (200, {}, self.jar)})
        self.assertFalse(ok)
        self.assertIn("older", messages[-1])
        self.assertEqual(self.catalog.games, [])
        self.assertFalse(os.path.exists(os.path.join(app_sources.SOURCES_DIR, "u0000test.json")))

    def test_an_index_signed_by_another_key_is_refused(self):
        self.catalog.source = AppSource("u0000test", "Test Repo", REPO_URL, OTHER_FINGERPRINT, builtin=False)
        ok, _, messages = self.sync({f"{REPO_URL}/index-v1.jar": (200, {}, self.jar)})
        self.assertFalse(ok)
        self.assertIn("different key", messages[-1])
        self.assertEqual(self.catalog.games, [])

    def test_a_mirror_is_used_when_the_repository_fails(self):
        self.catalog.mirrors = [MIRROR_URL]
        error = urllib.error.HTTPError(f"{REPO_URL}/index-v1.jar", 503, "Service Unavailable", {}, io.BytesIO())
        ok, calls, messages = self.sync({f"{REPO_URL}/index-v1.jar": error,
                                         f"{MIRROR_URL}/index-v1.jar": (200, {"ETag": '"mirror"'}, self.jar)})
        self.assertTrue(ok, messages)
        self.assertEqual([c[0] for c in calls], [f"{REPO_URL}/index-v1.jar", f"{MIRROR_URL}/index-v1.jar"])
        self.assertEqual(self.catalog.etag, "")  # a mirror's ETag means nothing to the repository
        # APKs still come from the repository itself.
        self.assertTrue(self.catalog.games[0].download_url.startswith(REPO_URL + "/"))

    def test_a_missing_index_is_reported_and_mirrors_are_not_tried(self):
        self.catalog.mirrors = [MIRROR_URL]
        missing = urllib.error.HTTPError(f"{REPO_URL}/index-v1.jar", 404, "Not Found", {}, io.BytesIO())
        ok, calls, messages = self.sync({f"{REPO_URL}/index-v1.jar": missing, f"{MIRROR_URL}/index-v1.jar": (200, {}, self.jar)})
        self.assertFalse(ok)
        self.assertEqual(len(calls), 1)
        self.assertIn("index-v1.jar", messages[-1])

    def test_no_answer_and_no_mirror_keeps_what_was_there(self):
        self.sync({f"{REPO_URL}/index-v1.jar": (200, {}, self.jar)})
        ok, _, messages = self.sync({})
        self.assertFalse(ok)
        self.assertIn("did not answer", messages[-1])
        self.assertEqual(len(self.catalog.games), 1)

    def test_one_index_at_a_time(self):
        self.assertTrue(app_sources._SYNC_LOCK.acquire(blocking=False))
        app_sources._syncing["id"] = "fdroid"
        try:
            ok, calls, messages = self.sync({f"{REPO_URL}/index-v1.jar": (200, {}, self.jar)})
        finally:
            app_sources._syncing["id"] = ""
            app_sources._SYNC_LOCK.release()
        self.assertFalse(ok)
        self.assertEqual(calls, [])
        self.assertIn("F-Droid catalog is still downloading", messages[-1])


class TestLegacyCache(TempCase):
    def test_the_fdroid_cache_of_older_versions_still_loads(self):
        from frameload.catalog import fdroid
        old = {"version": 2, "fields": 3, "last_sync": "2026-10-01T10:00:00", "etag": '"old"', "games": [
            {"name": "Notes", "release_name": "org.notes", "package_name": "org.notes", "version_code": "3",
             "last_updated": "2026-01-01", "size_bytes": 10, "id": hashlib.md5(b"org.notes\n").hexdigest(),
             "kind": "flat", "download_url": "https://f-droid.org/repo/org.notes_3.apk", "sha256": "a" * 64,
             "source": "fdroid", "screenshots": [], "retired_field": 1}]}
        with open(fdroid.FDROID_CACHE_JSON, "w", encoding="utf-8") as f:
            json.dump(old, f)
        catalog = FDroidCatalog()
        self.assertEqual([g.package_name for g in catalog.games], ["org.notes"])
        self.assertEqual(catalog.games[0].source_name, "F-Droid")
        self.assertEqual(catalog.last_sync, "2026-10-01T10:00:00")
        self.assertEqual(catalog.etag, "")  # fetched (and verified) again at the next sync


# ----------------------------------------------------------------------------- several sources

class SourcesCase(TempCase):
    """F-Droid and IzzyOnDroid with a package in both (signed by different keys) and one only in each."""

    A, B = "a" * 64, "b" * 64

    def setUp(self):
        super().setUp()
        Config.get().raw["app_sources"] = {"disabled": [], "custom": [], "order": ["fdroid", "izzyondroid", "guardian"]}
        self.sources = AppSources()
        self.load("fdroid", index_of(app("org.dup", 5, self.A, "Dup"), app("org.only.fd", 1, self.A)))
        self.load("izzyondroid", index_of(app("org.dup", 6, self.B, "Dup"), app("org.only.izzy", 1, self.B)))
        self.load("guardian", index_of())
        self.installed = {}
        self.patch(app_sources, "installed_apps", lambda: self.installed)

    def load(self, sid, index):
        catalog = self.sources.source(sid)
        catalog._set_games(parse_index(index, catalog.source.url, sid, catalog.source.name))
        catalog.last_sync = "2026-10-15T12:00:00"


class TestAllSources(SourcesCase):
    def test_duplicates_are_merged_in_source_order(self):
        res = self.sources.search("all", sort_by="name", sort_order="asc")
        self.assertEqual([(i["package_name"], i["source"]) for i in res["items"]],
                         [("org.dup", "fdroid"), ("org.only.fd", "fdroid"), ("org.only.izzy", "izzyondroid")])
        also = res["items"][0]["also_in"]
        self.assertEqual([(a["source"], a["version_name"], a["same_signer"]) for a in also], [("izzyondroid", "6.0", False)])
        self.assertEqual(res["last_sync"], "2026-10-15T12:00:00")
        self.assertEqual({c["name"]: c["count"] for c in self.sources.categories("all")["categories"]}, {"Internet": 3})

    def test_the_source_an_app_was_installed_from_is_shown(self):
        self.installed["org.dup"] = {"package": "org.dup", "kind": "flat", "version_code": "6",
                                     "origin": {"source": "izzyondroid", "signer": self.B}}
        dup = next(i for i in self.sources.search("all")["items"] if i["package_name"] == "org.dup")
        self.assertEqual((dup["source"], dup["installed_source"], dup["update_available"]), ("izzyondroid", "izzyondroid", False))
        fdroid = dup["also_in"][0]
        self.assertEqual(fdroid["source"], "fdroid")
        self.assertIn("signed by a different key", fdroid["blocked"])

    def test_one_source_alone(self):
        res = self.sources.search("izzyondroid")
        self.assertEqual({i["package_name"] for i in res["items"]}, {"org.dup", "org.only.izzy"})
        self.assertNotIn("also_in", res["items"][0])
        with self.assertRaises(KeyError):
            self.sources.search("nonexistent")

    def test_hidden_sources_are_left_out_of_all(self):
        self.sources.set_enabled("izzyondroid", False)
        self.assertEqual({i["source"] for i in self.sources.search("all")["items"]}, {"fdroid"})
        self.sources.set_enabled("fdroid", False)
        with self.assertRaisesRegex(ValueError, "At least one"):
            self.sources.set_enabled("guardian", False)

    def test_an_app_page_lists_the_other_sources(self):
        dup = self.sources.source("fdroid").games_by_pkg["org.dup"]
        page = self.sources.describe(dup)
        self.assertEqual([a["source"] for a in page["also_in"]], ["izzyondroid"])
        self.assertEqual(page["repo_url"], "https://f-droid.org/repo")


class TestUpdatesFollowOrigin(SourcesCase):
    def updates(self, *installed):
        with patch.object(InstalledManager, "list_installed", return_value=list(installed)):
            return [(u["package"], u["source"], u["new_version"]) for u in self.sources.available_updates()]

    def test_updates_come_only_from_the_origin_with_the_same_key(self):
        from_izzy = {"package": "org.dup", "kind": "flat", "version_code": "1", "version_name": "1.0",
                     "origin": {"source": "izzyondroid", "signer": self.B}}
        self.assertEqual(self.updates(from_izzy), [("org.dup", "izzyondroid", "6.0")])
        # F-Droid has it too (version 5, another key): never offered for the IzzyOnDroid install.
        from_izzy["version_code"] = "6"
        self.assertEqual(self.updates(from_izzy), [])
        # The source now signs it with another key: no update either.
        from_izzy.update(version_code="1", origin={"source": "izzyondroid", "signer": self.A})
        self.assertEqual(self.updates(from_izzy), [])

    def test_older_installs_are_fdroid_installs_and_files_get_none(self):
        old = {"package": "org.dup", "kind": "flat", "version_code": "1", "version_name": "1.0", "origin": None}
        self.assertEqual(self.updates(old), [("org.dup", "fdroid", "5.0")])
        from_file = dict(old, origin={"source": "file"})
        self.assertEqual(self.updates(from_file), [])
        vr_game = dict(old, kind="quest")
        self.assertEqual(self.updates(vr_game), [])

    def test_switching_sources_needs_the_same_key(self):
        izzy = self.sources.source("izzyondroid").games_by_pkg["org.dup"]
        installed = {"package": "org.dup", "kind": "flat", "origin": {"source": "fdroid", "signer": self.A}}
        reason = app_sources.switch_refusal(izzy, installed)
        self.assertIn("Installed from F-Droid", reason)
        self.assertIn("Uninstall it first", reason)
        self.assertEqual(app_sources.switch_refusal(izzy, dict(installed, origin={"source": "fdroid", "signer": self.B})), "")
        self.assertEqual(app_sources.switch_refusal(izzy, {"package": "org.dup", "kind": "flat"}), "")  # signer unknown
        self.assertEqual(app_sources.switch_refusal(izzy, None), "")


class TestCustomSources(TempCase):
    def setUp(self):
        super().setUp()
        Config.get().raw["app_sources"] = {"disabled": [], "custom": [], "order": ["fdroid", "izzyondroid", "guardian"]}
        self.patch(app_sources, "check_public_host", lambda url: None)
        self.sources = AppSources()

    def test_add_hide_and_remove(self):
        with self.assertRaisesRegex(ValueError, "Check the repository first"):
            self.sources.add_custom(REPO_URL, "")
        src = self.sources.add_custom(REPO_URL + "/", FIXTURE_FINGERPRINT, "Test Repo")
        self.assertEqual((src.id, src.url, src.builtin), (app_sources.custom_id(REPO_URL), REPO_URL, False))
        self.assertEqual([s.id for s in self.sources.all()][-1], src.id)
        with self.assertRaisesRegex(ValueError, "already in the list"):
            self.sources.add_custom(REPO_URL, FIXTURE_FINGERPRINT)
        with self.assertRaisesRegex(ValueError, "already in the list"):
            self.sources.add_custom("https://f-droid.org/repo", FIXTURE_FINGERPRINT)

        self.sources.set_enabled(src.id, False)
        self.assertNotIn(src.id, [s.id for s in self.sources.enabled()])
        with self.assertRaisesRegex(ValueError, "built in"):
            self.sources.remove_custom("fdroid")

        catalog = self.sources.source(src.id)
        catalog._set_games(parse_index(fixture_index(), REPO_URL, src.id, src.name))
        catalog.save_cache()
        self.assertTrue(os.path.isfile(catalog.cache_file))
        with patch.object(app_sources, "installed_apps", return_value={
                "org.example.notes": {"package": "org.example.notes", "title": "Pocket Notes", "kind": "flat",
                                      "origin": {"source": src.id}}}):
            lost = self.sources.remove_custom(src.id)
        self.assertEqual(lost, [{"package": "org.example.notes", "title": "Pocket Notes"}])
        self.assertIsNone(self.sources.find(src.id))
        self.assertFalse(os.path.exists(catalog.cache_file))

    def test_probe_checks_without_keeping_anything(self):
        fake = FakeHttp({f"{REPO_URL}/index-v1.jar": (200, {}, fixture("index-v1-noattr.jar"))})
        with patch.object(app_sources, "_http_get", fake):
            info = self.sources.probe(REPO_URL)
            self.assertEqual((info["fingerprint"], info["apps"], info["compatible"], info["pinned"], info["name"]),
                             (FIXTURE_FINGERPRINT, 6, 1, False, "FrameLoad Test Repo"))
            with self.assertRaisesRegex(IndexSignatureError, "different key"):
                self.sources.probe(REPO_URL, OTHER_FINGERPRINT)
        self.assertTrue(fake.calls[0][2])  # public addresses only
        self.assertEqual([s.id for s in self.sources.all()], ["fdroid", "izzyondroid", "guardian"])
        self.assertFalse(os.path.exists(app_sources.SOURCES_DIR))


# ----------------------------------------------------------------------------- installing

class TestInstallOrigin(TempCase):
    def setUp(self):
        super().setUp()
        self.anchor_root = os.path.join(self.tmp, "quest-frame")
        self.patch("frameload.installer.lepton_quest.register_game_in_steam", return_value={"success": True})
        self.patch(InstalledManager, "get_game", return_value=None)

    def apk(self, package):
        return write_apk(os.path.join(self.tmp, f"{package}.apk"),
                         manifest_node=manifest(package, categories=("android.intent.category.LAUNCHER",)))

    def dep(self, package):
        with open(os.path.join(self.anchor_root, package, "deployment.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_an_apk_for_another_package_is_refused_before_anything_is_written(self):
        with self.assertRaisesRegex(ValueError, r"\(org\.evil\.other\) is not the one the catalog listed"):
            LeptonInstaller.install_quest_game(package_name="org.example.notes", title="Notes",
                                               apk_path=self.apk("org.evil.other"), target_anchor=self.anchor_root,
                                               force_flat=True, expected_package="org.example.notes")
        self.assertFalse(os.path.exists(self.anchor_root))

    def test_the_origin_is_recorded_and_kept_by_a_reinstall(self):
        origin = {"source": "izzyondroid", "source_name": "IzzyOnDroid", "repo_url": "https://apt.izzysoft.de/fdroid/repo",
                  "signer": "b" * 64, "version_code": "7"}
        apk = self.apk("org.example.notes")
        LeptonInstaller.install_quest_game(package_name="org.example.notes", title="Notes", apk_path=apk,
                                           target_anchor=self.anchor_root, force_flat=True, origin=origin,
                                           expected_package="org.example.notes")
        self.assertEqual(self.dep("org.example.notes")["origin"], origin)
        LeptonInstaller.install_quest_game(package_name="org.example.notes", title="Notes", apk_path=apk,
                                           target_anchor=self.anchor_root, force_flat=True)  # a port, say
        self.assertEqual(self.dep("org.example.notes")["origin"], origin)
        with patch.object(InstalledManager, "get_all_anchor_dirs", return_value=[
                {"device_id": "internal", "device_name": "Internal", "path": self.anchor_root, "is_external": False}]), \
                patch.object(InstalledManager, "_get_running_lepton_containers", return_value=[]):
            listed = InstalledManager.list_installed()
        self.assertEqual(listed[0]["origin"], origin)

    def test_installs_from_a_file_record_it(self):
        with patch.object(LeptonInstaller, "install_quest_game", return_value={"success": True}) as install:
            PackageLoader.install_source(source_path=self.apk("org.example.notes"), target_anchor=self.anchor_root)
        self.assertEqual(install.call_args.kwargs["origin"], {"source": "file"})

    def test_a_finished_download_installs_with_its_origin(self):
        game = parse_index(fixture_index(), "https://apt.izzysoft.de/fdroid/repo", "izzyondroid", "IzzyOnDroid")[0]
        task = DownloadTask(id=game.id, game=game, target_apk=self.apk("org.example.notes"))
        self.patch(porting, "auto_port", return_value={})
        with patch.object(LeptonInstaller, "install_quest_game", return_value={"success": True}) as install:
            server.on_download_complete(task)
        kwargs = install.call_args.kwargs
        self.assertEqual(task.status, "completed")
        self.assertEqual(kwargs["expected_package"], "org.example.notes")
        self.assertEqual(kwargs["origin"], {"source": "izzyondroid", "source_name": "IzzyOnDroid",
                                            "repo_url": "https://apt.izzysoft.de/fdroid/repo", "signer": "c" * 64,
                                            "version_code": "20"})
        self.assertEqual(kwargs["icon_url"], game.thumbnail_url)

        # An added repository's pictures are not fetched by the server (its host could point at the headset).
        custom = parse_index(fixture_index(), REPO_URL, "u12345678", "Test Repo")[0]
        with patch.object(LeptonInstaller, "install_quest_game", return_value={"success": True}) as install:
            server.on_download_complete(DownloadTask(id=custom.id, game=custom, target_apk=task.target_apk))
        self.assertEqual((install.call_args.kwargs["icon_url"], install.call_args.kwargs["origin"]["source"]), ("", "u12345678"))

        link = CatalogGame(name="x", release_name="https://example.org/x.apk", package_name="link.download",
                           version_code="1", last_updated="", size_bytes=0, download_url="https://example.org/x.apk", source="link")
        with patch.object(LeptonInstaller, "install_quest_game", return_value={"success": True}) as install:
            server.on_download_complete(DownloadTask(id=link.id, game=link, target_apk=task.target_apk))
        self.assertEqual((install.call_args.kwargs["origin"], install.call_args.kwargs["expected_package"]), ({"source": "link"}, None))


class TestDownloadQueue(unittest.TestCase):
    def setUp(self):
        p = patch.object(Downloader, "_start_worker")  # nothing is downloaded here
        p.start()
        self.addCleanup(p.stop)
        self.downloader = Downloader()

    def game(self, source, package="org.example.notes"):
        return CatalogGame(name="Notes", release_name=f"{source}/{package}", package_name=package, version_code="1",
                           last_updated="", size_bytes=1, kind="flat", download_url="https://x/y.apk", source=source,
                           source_name=source.title())

    def test_a_second_download_of_the_same_app_is_refused(self):
        first = self.downloader.add_to_queue(self.game("fdroid"))
        self.assertIs(self.downloader.add_to_queue(self.game("fdroid")), first)  # the same entry again: the same task
        with self.assertRaisesRegex(DownloadConflict, "already being downloaded from Fdroid"):
            self.downloader.add_to_queue(self.game("izzyondroid"))
        first.status = "completed"
        self.downloader.add_to_queue(self.game("izzyondroid"))

    def test_link_downloads_do_not_block_each_other(self):
        for url in ("https://a.example/1.apk", "https://a.example/2.apk"):
            game = CatalogGame(name=url, release_name=url, package_name="link.download", version_code="1",
                               last_updated="", size_bytes=0, download_url=url, source="link")
            self.downloader.add_to_queue(game)
        self.assertEqual(len(self.downloader.tasks), 2)

    def test_apps_from_a_repository_must_come_over_https(self):
        game = self.game("u12345678")
        game.download_url = "http://repo.example.org/x.apk"
        with self.assertRaisesRegex(RuntimeError, "not https"):
            self.downloader._execute_direct_download(DownloadTask(id=game.id, game=game))


# ----------------------------------------------------------------------------- the API

class TestApi(TempCase):
    def setUp(self):
        super().setUp()
        Config.get().raw["app_sources"] = {"disabled": [], "custom": [], "order": ["fdroid", "izzyondroid", "guardian"]}
        self.patch(access, "PAIRED_FILE", os.path.join(self.tmp, "paired.json"))
        self.local = self.patch(FrameLoadApiHandler, "client_is_local", return_value=True)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, cookie=""):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Cookie": cookie} if cookie else {}
            if payload is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, json.loads(data) if data.startswith(b"{") else data
        finally:
            conn.close()

    def test_only_the_headset_changes_sources(self):
        self.local.return_value = False
        for route in ("probe", "add", "remove", "enable"):
            self.assertEqual(self.request("POST", f"/api/app-sources/{route}", {"url": REPO_URL})[0], 401, route)
        cookie = f"{access.COOKIE_NAME}={access.redeem(access.new_code()['code'], 'Phone')}"
        for route in ("probe", "add", "remove", "enable"):
            status, body = self.request("POST", f"/api/app-sources/{route}", {"url": REPO_URL, "id": "fdroid"}, cookie)
            self.assertEqual(status, 403, route)
            self.assertIn("headset", body["error"])
        status, body = self.request("GET", "/api/app-sources", cookie=cookie)  # a paired device may look
        self.assertEqual(status, 200)
        self.assertFalse(body["local"])
        self.assertEqual([s["id"] for s in body["sources"]], ["fdroid", "izzyondroid", "guardian"])

    def test_probe_refuses_local_and_plain_addresses(self):
        for url in ("https://127.0.0.1:8080/json", "https://192.168.1.5/fdroid/repo", "http://example.org/fdroid/repo"):
            status, body = self.request("POST", "/api/app-sources/probe", {"url": url})
            self.assertEqual(status, 400, url)
        self.assertIn("local network", self.request("POST", "/api/app-sources/probe", {"url": "https://10.0.0.1/repo"})[1]["error"])

    def test_check_add_hide_and_remove_a_repository(self):
        self.patch(app_sources, "check_public_host", lambda url: None)
        self.patch(app_sources, "_http_get", FakeHttp({f"{REPO_URL}/index-v1.jar": (200, {}, fixture("index-v1.jar"))}))
        status, info = self.request("POST", "/api/app-sources/probe", {"url": "fdroidrepos://repo.example.org/fdroid/repo"})
        self.assertEqual((status, info["fingerprint"], info["compatible"]), (200, FIXTURE_FINGERPRINT, 1))
        status, added = self.request("POST", "/api/app-sources/add", {"url": info["url"], "fingerprint": info["fingerprint"], "name": info["name"]})
        self.assertEqual(status, 200)
        sid = added["source"]["id"]
        listed = self.request("GET", "/api/app-sources")[1]["sources"]
        self.assertEqual([(s["id"], s["builtin"], s["fingerprint"]) for s in listed][-1], (sid, False, FIXTURE_FINGERPRINT))
        self.assertEqual(self.request("POST", "/api/app-sources/enable", {"id": sid, "enabled": False})[0], 200)
        self.assertFalse(self.request("GET", "/api/app-sources")[1]["sources"][-1]["enabled"])
        self.assertEqual(self.request("POST", "/api/app-sources/remove", {"id": "fdroid"})[0], 400)
        self.assertEqual(self.request("POST", "/api/app-sources/remove", {"id": sid})[0], 200)
        self.assertEqual(self.request("POST", "/api/app-sources/remove", {"id": sid})[0], 404)

    def test_the_catalog_reads_the_requested_source(self):
        with patch.object(AppSources, "search", return_value={"items": [], "total_count": 0, "last_sync": ""}) as search:
            status, body = self.request("GET", "/api/catalog?kind=flat&source=izzyondroid&q=notes")
        self.assertEqual((status, body["source"]), (200, "izzyondroid"))
        self.assertEqual((search.call_args.kwargs["source"], search.call_args.kwargs["query"]), ("izzyondroid", "notes"))
        with patch.object(AppSources, "search", return_value={"items": []}) as search:
            self.request("GET", "/api/catalog?kind=flat")
        self.assertEqual(search.call_args.kwargs["source"], "fdroid")  # the default, as before
        self.assertEqual(self.request("GET", "/api/catalog?kind=flat&source=../x")[0], 400)
        self.assertEqual(self.request("GET", "/api/catalog/categories?source=nope")[0], 400)

    def test_queue_refuses_another_key_and_a_second_download(self):
        izzy = parse_index(fixture_index(), "https://apt.izzysoft.de/fdroid/repo", "izzyondroid", "IzzyOnDroid")[0]
        self.patch(AppSources, "get_game", return_value=izzy)
        installed = self.patch(InstalledManager, "get_game", return_value={
            "package": "org.example.notes", "kind": "flat", "origin": {"source": "fdroid", "signer": "d" * 64}})
        queue = self.patch(Downloader, "add_to_queue", return_value=DownloadTask(id=izzy.id, game=izzy))
        status, body = self.request("POST", "/api/downloads/queue", {"game_id": izzy.id})
        self.assertEqual((status, body["code"]), (409, "different_signer"))
        self.assertIn("Installed from F-Droid", body["error"])
        queue.assert_not_called()

        installed.return_value = {"package": "org.example.notes", "kind": "flat", "origin": {"source": "fdroid", "signer": "c" * 64}}
        self.assertEqual(self.request("POST", "/api/downloads/queue", {"game_id": izzy.id})[0], 200)  # same key: switch
        queue.side_effect = DownloadConflict("Notes is already being downloaded.")
        status, body = self.request("POST", "/api/downloads/queue", {"game_id": izzy.id})
        self.assertEqual((status, body["code"]), (409, "already_downloading"))


# ----------------------------------------------------------------------------- the dashboard

def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def declaration(source, name):
    match = re.search(rf"^(?:async )?function {name}\(.*?^\}}$|^const {name} = .*?^\}};$", source, re.M | re.S)
    if not match:
        raise AssertionError(f"{name} not found in app.js")
    return match.group(0)


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.app = read(WEB, "static", "js", "app.js")
        self.page = read(WEB, "templates", "index.html")

    def test_browse_offers_2d_apps_from_a_chosen_source(self):
        self.assertIn('<option value="flat">2D Apps</option>', self.page)
        self.assertNotIn("2D Apps (F-Droid)", self.page)
        self.assertRegex(self.page, r'<select id="catalog-source-select"[^>]*aria-label="App source"')
        self.assertIn('id="app-sources-btn"', self.page)
        self.assertIn('id="app-updates-btn"', self.page)
        self.assertNotIn("fdroid-updates-btn", self.page + self.app)
        kind = declaration(self.app, "applyCatalogKind")
        self.assertIn('"catalog-source-select"', kind)
        self.assertIn('isFlat ? "" : "none"', kind)  # hidden for VR games
        self.assertIn("params.set(\"source\", state.catalog.source)", declaration(self.app, "loadCatalog"))

    def test_the_empty_catalog_names_the_source_and_its_size(self):
        empty = declaration(self.app, "catalogEmptyMessage")
        self.assertNotIn("10 MB", empty)
        self.assertIn("size_hint", empty)

    def test_the_chosen_source_is_remembered_safely(self):
        for name in ("savedAppSource", "rememberAppSource"):
            body = declaration(self.app, name)
            self.assertIn("localStorage", body)
            self.assertIn("try {", body)

    def test_no_browser_dialogs(self):
        for name in ("renderAppSourcesList", "checkAppRepository", "removeAppSource", "setAppSourceEnabled",
                     "loadAppSources", "renderAlsoIn", "renderAppSourceRow", "openAppSourcesModal"):
            body = declaration(self.app, name)
            self.assertIsNone(re.search(r"(?<![\w.])(confirm|alert)\(", body), name)
            self.assertNotIn("window.confirm", body)
        self.assertIn("confirmDialog(\"Add this repository?\"", declaration(self.app, "checkAppRepository"))
        self.assertIn("REPOSITORY_WARNING", declaration(self.app, "checkAppRepository"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_source_list_is_read_only_away_from_the_headset(self):
        sources = [
            {"id": "fdroid", "name": "F-Droid", "url": "https://f-droid.org/repo", "builtin": True, "enabled": True,
             "fingerprint": "43238d51" + "0" * 56, "last_sync": "2026-10-15T12:00:00", "app_count": 4645, "size_hint": "16 MB"},
            {"id": "u12345678", "name": "<b>Mine</b>", "url": "https://example.org/repo", "builtin": False, "enabled": False,
             "fingerprint": "", "last_sync": "", "app_count": 0, "size_hint": ""},
        ]
        script = "\n".join(declaration(self.app, n) for n in ("escapeHtml", "jsArg", "groupedFingerprint", "renderAppSourcesList"))
        script += """
const els = {};
["app-sources-list", "app-sources-readonly", "app-sources-add"].forEach(id => els[id] = { innerHTML: "", style: {} });
var document = { getElementById: (id) => els[id] || null };
var window = {};
var state = { appSources: { list: SOURCES, local: LOCAL, loaded: true } };
renderAppSourcesList();
process.stdout.write(JSON.stringify({ html: els["app-sources-list"].innerHTML, readonly: els["app-sources-readonly"].style.display,
  add: els["app-sources-add"].style.display }));
"""
        out = {}
        for local in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "sources.js")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(script.replace("SOURCES", json.dumps(sources)).replace("LOCAL", "true" if local else "false"))
                out[local] = json.loads(subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8",
                                                       check=True, timeout=60).stdout)
        away, here = out[False], out[True]
        self.assertEqual((away["readonly"], away["add"]), ("", "none"))
        self.assertEqual(away["html"].count("disabled"), 2)
        self.assertNotIn("removeAppSource", away["html"])
        self.assertEqual((here["readonly"], here["add"]), ("none", ""))
        self.assertEqual(here["html"].count("removeAppSource"), 1)  # only the repository that was added
        self.assertIn("&lt;b&gt;Mine&lt;/b&gt;", here["html"])
        self.assertIn("4323 8D51", here["html"])
        self.assertIn("not known yet", here["html"])


if __name__ == "__main__":
    unittest.main()
