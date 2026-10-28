import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.installer import release_script  # noqa: E402

PKG = "com.portalVR.source"
# PortalVR v1+1.12 -JF's install.txt, as the release on the headset has it.
PORTAL_SCRIPT = """# PortalVR - Quest standalone

adb shell pm uninstall com.portalVR.source
adb install -g -r "com.portalVR.source.apk"

adb shell mkdir -p /sdcard/source
adb shell mkdir -p /sdcard/source/hl2
adb shell mkdir -p /sdcard/source/platform
adb shell mkdir -p /sdcard/source/portal

adb install -r -g PortalVR.apk
adb shell appops set --uid com.portalVR.source MANAGE_EXTERNAL_STORAGE allow

adb push source/hl2 /sdcard/source/
adb push source/platform /sdcard/source/
adb push source/portal /sdcard/source/"""


class TestReleaseScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.release = os.path.join(self.tmp, "PortalVR v1+1.12 -JF")
        self.folder = os.path.join(self.release, "PortalVR v1+1.12 -JF")
        os.makedirs(self.folder)
        self.base = os.path.join(self.tmp, "quest-frame", PKG)
        os.makedirs(os.path.join(self.base, "lepton-data", "external", "Android"))
        os.makedirs(os.path.join(self.base, "lepton-app", "obb"))

    def write(self, rel, text, root=None):
        path = os.path.join(root or self.folder, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def external(self, *parts):
        return os.path.join(self.base, "lepton-data", "external", *parts)

    def test_portalvr_data_lands_in_sdcard_source(self):
        self.write("install.txt", PORTAL_SCRIPT)
        # The game files come packed in _bin (a zip here; the real one is a 7z).
        with zipfile.ZipFile(os.path.join(self.folder, "_bin.zip"), "w") as zf:
            zf.writestr("source/hl2/hl2_misc_dir.vpk", "hl2")
            zf.writestr("source/platform/platform_misc_dir.vpk", "platform")
            zf.writestr("source/portal/portal_pak_dir.vpk", "portal")
        record = release_script.run(self.release, PKG, self.base)
        for rel in (("hl2", "hl2_misc_dir.vpk"), ("platform", "platform_misc_dir.vpk"), ("portal", "portal_pak_dir.vpk")):
            path = self.external("source", *rel)
            self.assertTrue(os.path.isfile(path), path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o666)
        self.assertEqual(os.stat(self.external("source")).st_mode & 0o777, 0o777)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "_bin.zip")))
        self.assertEqual(record["failed"], [])
        self.assertEqual(record["permissions"],
                         ["adb shell appops set --uid com.portalVR.source MANAGE_EXTERNAL_STORAGE allow"])
        self.assertIn("adb install -r -g PortalVR.apk", record["skipped"])
        self.assertTrue(os.path.isfile(os.path.join(self.base, release_script.RECORD_NAME)))

    def test_obb_paths_and_escapes(self):
        self.write("install.txt", "\n".join([
            f"adb push {PKG} /sdcard/Android/obb/",
            "adb push data.bin /sdcard/../../../etc/passwd",
            "adb push ../outside.bin /sdcard/x/",
            "adb shell rm -rf /sdcard/",
        ]))
        self.write(os.path.join(PKG, "main.1.obb"), "obb")
        self.write("data.bin", "x")
        self.write("outside.bin", "x", root=self.release)
        record = release_script.run(self.release, PKG, self.base)
        self.assertTrue(os.path.isfile(os.path.join(self.base, "lepton-app", "obb", "main.1.obb")))
        self.assertEqual(len(record["failed"]), 2)
        self.assertEqual(record["skipped"], ["adb shell rm -rf /sdcard/"])
        self.assertTrue(os.path.isdir(self.external("Android")))

    def test_device_paths(self):
        self.assertEqual(release_script.device_path("/storage/emulated/0/source/hl2", self.base, PKG),
                         self.external("source", "hl2"))
        self.assertEqual(release_script.device_path(f"/sdcard/Android/obb/{PKG}/a.obb", self.base, PKG),
                         os.path.join(self.base, "lepton-app", "obb", "a.obb"))
        self.assertIsNone(release_script.device_path("/data/local/tmp/x", self.base, PKG))
        self.assertIsNone(release_script.device_path("/sdcard/../x", self.base, PKG))

    def test_release_without_script(self):
        self.assertIsNone(release_script.run(self.release, PKG, self.base))


if __name__ == "__main__":
    unittest.main()
