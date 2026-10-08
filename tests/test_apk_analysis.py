"""APK inspection: binary manifest parsing and the Steam Frame compatibility verdict."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axml_builder import LABEL_RES_ID, build_arsc, build_axml, manifest, ref, write_apk  # noqa: E402

from frameload.installer.apk_analysis import inspect_apk  # noqa: E402
from frameload.installer.axml import AxmlError, read_manifest, resolve_string_resource  # noqa: E402

VR = "com.oculus.intent.category.VR"
INFO = "android.intent.category.INFO"
LAUNCHER = "android.intent.category.LAUNCHER"


class TestManifestParsing(unittest.TestCase):
    def test_reads_package_versions_and_launcher(self):
        info = read_manifest(build_axml(manifest("com.example.game", version_code=42, version_name="2.0.1")))
        self.assertEqual(info.package, "com.example.game")
        self.assertEqual(info.version_code, "42")
        self.assertEqual(info.version_name, "2.0.1")
        self.assertEqual(info.min_sdk, 29)
        self.assertEqual(info.launch_activity, "com.example.game.MainActivity")
        self.assertFalse(info.is_vr)

    def test_reads_manifest_whose_attribute_names_are_stripped(self):
        data = build_axml(manifest("com.example.stripped", categories=(LAUNCHER, VR)), strip_attr_names=True)
        info = read_manifest(data)
        self.assertEqual(info.version_code, "7")
        self.assertEqual(info.launch_activity, "com.example.stripped.MainActivity")
        self.assertTrue(info.is_vr)

    def test_quest_store_layout_has_no_launch_activity(self):
        info = read_manifest(build_axml(manifest("com.example.quest", categories=(INFO, VR))))
        self.assertEqual(info.launch_activity, "")
        self.assertEqual(info.info_activity, "com.example.quest.MainActivity")
        self.assertTrue(info.is_vr)

    def test_launcher_on_alias_is_not_a_launch_activity(self):
        info = read_manifest(build_axml(manifest("com.example.alias", alias_launcher=True)))
        self.assertEqual(info.launch_activity, "")
        self.assertEqual(info.alias_launcher, "com.example.alias.MainActivity")

    def test_hand_tracking_requirement(self):
        feature = "oculus.software.handtracking"
        required = read_manifest(build_axml(manifest("a.b", features={feature: True})))
        optional = read_manifest(build_axml(manifest("a.b", features={feature: False})))
        permission = read_manifest(build_axml(manifest("a.b", permissions=["com.oculus.permission.HAND_TRACKING"])))
        self.assertEqual(required.hand_tracking, "required")
        self.assertEqual(optional.hand_tracking, "optional")
        self.assertEqual(permission.hand_tracking, "optional")
        self.assertEqual(read_manifest(build_axml(manifest("a.b"))).hand_tracking, "none")

    def test_rejects_non_axml_and_survives_truncation(self):
        with self.assertRaises(AxmlError):
            read_manifest(b"<manifest package='text.xml'/>")
        data = build_axml(manifest("com.example.game"))
        for cut in (9, 40, len(data) // 2, len(data) - 3):
            try:
                read_manifest(data[:cut])
            except AxmlError:
                pass  # refusing is fine; crashing with another exception is not

    def test_resolves_label_from_resource_table(self):
        arsc = build_arsc("Beat Saber")
        self.assertEqual(resolve_string_resource(arsc, LABEL_RES_ID), "Beat Saber")
        self.assertEqual(resolve_string_resource(arsc, 0x7F020000), "")
        self.assertEqual(resolve_string_resource(arsc[:40], LABEL_RES_ID), "")


class TestCompatVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def apk(self, name="game.apk", **kwargs):
        return write_apk(os.path.join(self.tmp, name), **kwargs)

    def codes(self, analysis):
        return {i["code"] for i in analysis.compat["issues"]}

    def test_unported_quest_game_needs_porting(self):
        path = self.apk(
            manifest_node=manifest("com.studio.questgame", categories=(INFO, VR),
                                   features={"oculus.software.handtracking": True}),
            libs=["libOVRPlugin.so", "libil2cpp.so", "libunity.so", "libovrplatformloader.so"])
        a = inspect_apk(path)
        self.assertEqual(a.package_name, "com.studio.questgame")
        self.assertTrue(a.is_vr)
        self.assertEqual(a.engine, "Unity")
        self.assertEqual(a.xr_runtime, "meta")
        self.assertEqual(a.hand_tracking, "required")
        self.assertEqual(a.compat["level"], "needs_port")
        self.assertTrue({"meta_runtime", "no_launcher", "hand_tracking", "platform_sdk"} <= self.codes(a))

    def test_framebridge_ported_game_is_ready(self):
        path = self.apk(
            manifest_node=manifest("com.studio.ported", categories=(LAUNCHER, VR)),
            libs=["libopenxr_loader.so", "libopenxr_loader_original.so", "libframe_settings.so", "libOVRPlugin.so"])
        a = inspect_apk(path)
        self.assertTrue(a.framebridge)
        self.assertEqual(a.xr_runtime, "framebridge")
        self.assertEqual(a.compat["level"], "ready")
        self.assertNotIn("no_launcher", self.codes(a))

    def test_native_openxr_game_should_run(self):
        path = self.apk(manifest_node=manifest("org.example.openxr", categories=(LAUNCHER, VR)),
                        libs=["libopenxr_loader.so", "libgodot_android.so"])
        a = inspect_apk(path)
        self.assertEqual(a.engine, "Godot")
        self.assertEqual(a.compat["level"], "likely")

    def test_flat_app_with_resource_label(self):
        path = self.apk(manifest_node=manifest("org.example.flat", label=ref(LABEL_RES_ID)),
                        arsc=build_arsc("Pocket Notes"))
        a = inspect_apk(path)
        self.assertFalse(a.is_vr)
        self.assertEqual(a.label, "Pocket Notes")
        self.assertEqual(a.hand_tracking, "none")
        self.assertEqual(a.compat["level"], "ready")

    def test_32_bit_only_app_is_blocked(self):
        path = self.apk(manifest_node=manifest("org.example.old"), libs=["libmain.so"], abi="armeabi-v7a")
        a = inspect_apk(path)
        self.assertEqual(a.compat["level"], "blocked")
        self.assertIn("abi", self.codes(a))

    def test_legacy_vrapi_game_needs_porting(self):
        path = self.apk(manifest_node=manifest("com.old.vrapi", categories=(LAUNCHER, VR)), libs=["libvrapi.so"])
        a = inspect_apk(path)
        self.assertEqual(a.xr_runtime, "vrapi")
        self.assertEqual(a.compat["level"], "needs_port")

    def test_unreadable_manifest_falls_back_to_file_name(self):
        path = self.apk(name="com.vendor.title-v12.apk", raw_manifest=b"\x00garbage\x00")
        a = inspect_apk(path)
        self.assertFalse(a.manifest_parsed)
        self.assertEqual(a.package_name, "com.vendor.title")
        self.assertIn("manifest", self.codes(a))

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            inspect_apk(os.path.join(self.tmp, "nope.apk"))


if __name__ == "__main__":
    unittest.main()
