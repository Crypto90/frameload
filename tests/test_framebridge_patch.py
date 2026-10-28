import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.installer import framebridge_patch as fb  # noqa: E402

ORIGINAL = b"\x7fELF framebridge 1.4.0"
PATCHED = b"\x7fELF framebridge 1.4.0 wait_balance: began and ended it empty"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFrameBridgePatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.venv = os.path.join(self.tmp, "venv")
        self.art = os.path.join(self.venv, "lib", "python3.13", "site-packages", "frameport", "_data", "artifacts")
        for abi in fb.ABIS:
            os.makedirs(os.path.join(self.art, abi))
            with open(os.path.join(self.art, abi, fb.ADAPTER), "wb") as f:
                f.write(ORIGINAL)
        self.calls = []
        self.releases = [
            {"tag_name": "framebridge-1.4.0-p1", "assets": [{"name": "SHA256SUMS"}, {"name": "ORIGINAL_SHA256SUMS"}]},
            {"tag_name": "framebridge-1.3.0-p4", "assets": []},
            {"tag_name": "v1.5.3", "assets": []},
        ]

        def urlopen(url, timeout=30):
            self.calls.append(url)
            if url == fb.RELEASES_API:
                return FakeResponse(json.dumps(self.releases).encode())
            name = url.rsplit("/", 1)[1]
            if name == "SHA256SUMS":
                return FakeResponse("".join(f"{sha(PATCHED)}  libopenxr_loader_generic-{a}.so\n" for a in fb.ABIS).encode())
            if name == "ORIGINAL_SHA256SUMS":
                return FakeResponse("".join(f"{sha(ORIGINAL)}  libopenxr_loader_generic-{a}.so\n" for a in fb.ABIS).encode())
            if name.endswith(".so"):
                return FakeResponse(PATCHED)
            raise OSError("404")

        for p in (patch.object(fb, "_urlopen", side_effect=urlopen),
                  patch.object(fb, "BUILDS_CACHE", os.path.join(self.tmp, "builds.json"))):
            p.start()
            self.addCleanup(p.stop)

    def adapter(self, abi="arm64-v8a"):
        with open(os.path.join(self.art, abi, fb.ADAPTER), "rb") as f:
            return f.read()

    def test_finds_the_newest_build_for_the_installed_framePort_and_keeps_the_answer(self):
        self.releases.append({"tag_name": "framebridge-1.4.0-p2",
                              "assets": [{"name": "SHA256SUMS"}, {"name": "ORIGINAL_SHA256SUMS"}]})
        build = fb.find_build("1.4.0", now=1000)
        self.assertEqual(build["tag"], "framebridge-1.4.0-p2")
        self.assertEqual(build["patched"]["arm64-v8a"], sha(PATCHED))
        calls = len(self.calls)
        self.assertEqual(fb.find_build("1.4.0", now=2000)["tag"], "framebridge-1.4.0-p2")
        self.assertEqual(len(self.calls), calls)  # cached
        self.assertIsNone(fb.find_build("1.4.1", now=1000))  # not built (yet)

    def test_swaps_in_the_patched_adapter_only_over_framePorts_own_and_puts_it_back(self):
        lines = []
        fb.ensure("1.4.0", self.venv, lines.append, cache=os.path.join(self.tmp, "cache"))
        self.assertEqual(self.adapter(), PATCHED)
        self.assertTrue(os.path.isfile(os.path.join(self.art, "arm64-v8a", fb.ADAPTER + fb.ORIGINAL_SUFFIX)))
        self.assertIn("patched (framebridge-1.4.0-p1)", lines[0])
        # FramePort updated itself (a new adapter, no build of ours yet): left as FramePort wrote it.
        with open(os.path.join(self.art, "arm64-v8a", fb.ADAPTER), "wb") as f:
            f.write(b"\x7fELF framebridge 1.4.1")
        fb.ensure("1.4.1", self.venv, lines.append, cache=os.path.join(self.tmp, "cache"))
        self.assertEqual(self.adapter(), b"\x7fELF framebridge 1.4.1")
        self.assertFalse(os.path.isfile(os.path.join(self.art, "arm64-v8a", fb.ADAPTER + fb.ORIGINAL_SUFFIX)))
        # No build to vouch for a file that still carries the patch (the armv7 one here): the original goes back.
        self.assertEqual(self.adapter("armeabi-v7a"), ORIGINAL)
        self.assertFalse(os.path.isfile(os.path.join(self.art, "armeabi-v7a", fb.ADAPTER + fb.ORIGINAL_SUFFIX)))

    def test_a_download_that_does_not_match_is_never_used(self):
        def bad(url, timeout=30):
            if url.endswith(".so"):
                return FakeResponse(b"something else")
            return self_urlopen(url, timeout)
        self_urlopen = fb._urlopen.side_effect
        with patch.object(fb, "_urlopen", side_effect=bad):
            lines = []
            fb.ensure("1.4.0", self.venv, lines.append, cache=os.path.join(self.tmp, "cache"))
        self.assertEqual(self.adapter(), ORIGINAL)
        self.assertIn("could not be downloaded", lines[0])

    def test_an_unknown_adapter_is_left_alone(self):
        with open(os.path.join(self.art, "arm64-v8a", fb.ADAPTER), "wb") as f:
            f.write(b"\x7fELF someone else's build")
        lines = []
        fb.ensure("1.4.0", self.venv, lines.append, cache=os.path.join(self.tmp, "cache"))
        self.assertEqual(self.adapter(), b"\x7fELF someone else's build")
        self.assertIn("left alone", lines[0])

    def test_has_patch_reads_the_ported_apk(self):
        import zipfile
        apk = os.path.join(self.tmp, "game.apk")
        with zipfile.ZipFile(apk, "w") as zf:
            zf.writestr(f"lib/arm64-v8a/{fb.ADAPTER}", PATCHED)
        self.assertTrue(fb.has_patch(apk))
        with zipfile.ZipFile(apk, "w") as zf:
            zf.writestr(f"lib/arm64-v8a/{fb.ADAPTER}", ORIGINAL)
        self.assertFalse(fb.has_patch(apk))


if __name__ == "__main__":
    unittest.main()
