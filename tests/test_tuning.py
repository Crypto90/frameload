"""Per-game Lepton / FrameBridge settings: what is stored, and what reaches the launcher and conf files."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axml_builder import manifest, write_apk  # noqa: E402

from frameload.installer.lepton_quest import FLATSCREEN_MARKER, LeptonInstaller, find_obb_dir  # noqa: E402
from frameload.manager.installed import InstalledManager  # noqa: E402
from frameload.manager.tuning import (  # noqa: E402
    DEFAULTS, PRESETS, SETTINGS_SCHEMA, TuningManager, normalize_settings,
)

VR = "com.oculus.intent.category.VR"
LAUNCHER = "android.intent.category.LAUNCHER"


class TuningTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.anchor_root = os.path.join(self.tmp, "quest-frame")

        def get_game(package_name):
            path = os.path.join(self.anchor_root, package_name, "deployment.json")
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        for target, replacement in (
            (patch.object(InstalledManager, "get_game", side_effect=get_game), None),
            (patch.object(TuningManager, "get_global_tuning", side_effect=lambda: DEFAULTS.copy()), None),
            (patch("frameload.installer.lepton_quest.register_game_in_steam", return_value={"success": True}), None),
        ):
            target.start()
            self.addCleanup(target.stop)

    def install(self, package, libs=(), categories=(LAUNCHER, VR), features=None, force_flat=None, **kwargs):
        apk = write_apk(os.path.join(self.tmp, f"{package}.apk"),
                        manifest_node=manifest(package, categories=categories, features=features), libs=libs)
        return LeptonInstaller.install_quest_game(
            package_name=package, title="Test Game", apk_path=apk, target_anchor=self.anchor_root,
            force_flat=force_flat, **kwargs)

    def read(self, package, *parts):
        with open(os.path.join(self.anchor_root, package, *parts), "r", encoding="utf-8") as f:
            return f.read()

    def conf(self, package):
        path = os.path.join(self.anchor_root, package, "settings.conf")
        if not os.path.isfile(path):
            return {}
        return dict(line.split("=", 1) for line in self.read(package, "settings.conf").splitlines() if "=" in line)


class TestSettingsModel(unittest.TestCase):
    def test_schema_is_consistent(self):
        keys = [s["key"] for s in SETTINGS_SCHEMA]
        self.assertEqual(len(keys), len(set(keys)))
        for spec in SETTINGS_SCHEMA:
            self.assertIn(spec["scope"], ("vr", "flat"))
            if spec["type"] == "choice":
                self.assertIn(spec["default"], [c["value"] for c in spec["choices"]])
        for preset in PRESETS.values():
            self.assertEqual(normalize_settings(preset["settings"], keep_defaults=True), preset["settings"])

    def test_normalize_validates_and_clamps(self):
        self.assertEqual(normalize_settings({"scale": "9", "refresh_rate": "120", "foveation": "fixed"}),
                         {"scale": 2.0, "refresh_rate": 120, "foveation": "fixed"})
        self.assertEqual(normalize_settings({"refresh_rate": 75, "foveation": "bogus", "unknown": 1}), {})
        self.assertEqual(normalize_settings({"scale": 1.0}), {})
        self.assertEqual(normalize_settings({"scale": 1.0}, keep_defaults=True), {"scale": 1.0})
        self.assertEqual(normalize_settings("not a dict"), {})

    def test_settings_from_before_the_rewrite_are_dropped(self):
        legacy = {"spoof_profile": "quest3", "resolution_scale": 1.25, "refresh_rate": 90, "msaa": 4,
                  "hand_tracking": "synthetic"}
        self.assertEqual(normalize_settings(legacy), {})

    def test_launch_env(self):
        base = DEFAULTS.copy()
        self.assertEqual(TuningManager.launch_env(base, is_vr=True), {})
        self.assertEqual(TuningManager.launch_env({**base, "foveation": "fixed"}, True), {"FDM_DEBUG": "disable_offsets"})
        self.assertEqual(TuningManager.launch_env({**base, "foveation": "off"}, True), {"VK_INSTANCE_LAYERS": ""})
        flat = TuningManager.launch_env(base, is_vr=False)
        self.assertEqual(flat, {"LEPTON_GFXRECON_FRAMELOAD": "0\nqemu.hw.mainkeys=1"})
        self.assertEqual(TuningManager.launch_env({**base, "hide_navbar": False}, False), {})

    def test_framebridge_values_only_hold_non_defaults(self):
        base = DEFAULTS.copy()
        self.assertEqual(TuningManager.framebridge_values(base, "none"), {})
        self.assertEqual(TuningManager.framebridge_values(base, "required"), {"controller_fix": 0})
        values = TuningManager.framebridge_values(
            {**base, "hand_input": "controllers", "scale": 1.3, "refresh_rate": 120, "haptic_scale": 0.5,
             "hide_space_warp": True}, "required")
        self.assertEqual(values, {"controller_fix": 1, "scale": "1.30", "refresh_rate": 120,
                                  "haptic_scale": "0.50", "hide_space_warp": 1})


class TestInstallAndApply(TuningTestCase):
    def test_vr_install_writes_real_lepton_launcher(self):
        res = self.install("com.studio.vr", libs=["libopenxr_loader.so", "libframe_settings.so"])
        self.assertTrue(res["success"])
        self.assertTrue(res["is_vr"])
        self.assertTrue(res["framebridge"])

        launch = self.read("com.studio.vr", "launch.sh")
        for line in ('export STEAM_COMPAT_INSTALL_PATH="$app_dir/lepton-app"',
                     'export LEPTON_ENV_FRAMEBRIDGE_CONFIG="$app_dir/settings.conf"',
                     'setsid "$lepton" start'):
            self.assertIn(line, launch)
        # Variables Lepton never read must not come back.
        for fake in ("LEPTON_SPOOF", "ANDROID_PROPERTY_OVERRIDE", "LEPTON_WINDOW_WIDTH", "LEPTON_MSAA", "LEPTON_HAND_TRACKING"):
            self.assertNotIn(fake, launch)
        self.assertNotIn("\r", launch)

        app_dir = os.path.join(self.anchor_root, "com.studio.vr", "lepton-app")
        self.assertEqual([n for n in os.listdir(app_dir) if n.endswith(".apk")], ["game.apk"])
        self.assertFalse(os.path.exists(os.path.join(app_dir, FLATSCREEN_MARKER)))
        self.assertFalse(os.path.exists(os.path.join(self.anchor_root, "com.studio.vr", "lepton-data", "local.prop")))
        self.assertEqual(self.conf("com.studio.vr"), {})

    def test_flat_install_shows_window_and_hides_navbar(self):
        res = self.install("org.example.flat", categories=(LAUNCHER,))
        self.assertFalse(res["is_vr"])
        self.assertEqual(res["kind"], "flat")
        app_dir = os.path.join(self.anchor_root, "org.example.flat", "lepton-app")
        self.assertTrue(os.path.isfile(os.path.join(app_dir, FLATSCREEN_MARKER)))
        self.assertIn("qemu.hw.mainkeys=1", self.read("org.example.flat", "launch.sh"))

    def test_force_flat_overrides_a_vr_manifest(self):
        res = self.install("com.studio.forced", libs=["libopenxr_loader.so"], force_flat=True)
        self.assertFalse(res["is_vr"])

    def test_real_package_name_wins_over_the_given_one(self):
        apk = write_apk(os.path.join(self.tmp, "x.apk"), manifest_node=manifest("com.real.name"))
        res = LeptonInstaller.install_quest_game(package_name="com.guessed.name", title="", apk_path=apk,
                                                 target_anchor=self.anchor_root)
        self.assertEqual(res["package"], "com.real.name")
        self.assertTrue(os.path.isdir(os.path.join(self.anchor_root, "com.real.name")))

    def test_rejects_package_names_that_escape_the_library(self):
        apk = write_apk(os.path.join(self.tmp, "bad.apk"), raw_manifest=b"junk")
        with self.assertRaises(ValueError):
            LeptonInstaller.install_quest_game(package_name="../../evil", title="x", apk_path=apk,
                                               target_anchor=self.anchor_root)

    def test_obb_files_land_directly_in_obb_folder(self):
        dump = os.path.join(self.tmp, "dump", "Android", "obb", "com.studio.obb")
        os.makedirs(dump)
        with open(os.path.join(dump, "main.7.com.studio.obb.obb"), "wb") as f:
            f.write(b"obb")
        self.assertEqual(find_obb_dir(os.path.join(self.tmp, "dump"), "com.studio.obb"), dump)
        self.assertEqual(find_obb_dir(os.path.join(self.tmp, "dump", "Android", "obb"), "com.studio.obb"), dump)
        res = self.install("com.studio.obb", obb_path=os.path.join(self.tmp, "dump"))
        self.assertEqual(res["obb_files"], 1)
        self.assertTrue(os.path.isfile(os.path.join(
            self.anchor_root, "com.studio.obb", "lepton-app", "obb", "main.7.com.studio.obb.obb")))

    def test_saving_settings_updates_launcher_and_framebridge_conf(self):
        pkg = "com.studio.tuned"
        self.install(pkg, libs=["libframe_settings.so"])
        result = TuningManager.save_game_tuning(pkg, {
            "scale": 1.3, "refresh_rate": 120, "hand_input": "hands", "foveation": "fixed", "text_input": True})
        self.assertEqual(result["scale"], 1.3)
        self.assertEqual(result["hand_input_effective"], "hands")
        self.assertTrue(result["framebridge"])

        self.assertEqual(self.conf(pkg), {"controller_fix": "0", "scale": "1.30", "refresh_rate": "120"})
        files_conf = self.read(pkg, "lepton-data", "external", "Android", "data", pkg, "files", "framebridge.conf")
        self.assertIn("scale=1.30", files_conf)
        self.assertIn("export FDM_DEBUG=disable_offsets", self.read(pkg, "launch.sh"))
        self.assertTrue(os.path.isfile(os.path.join(self.anchor_root, pkg, "lepton-app", FLATSCREEN_MARKER)))

        # Back to defaults: FrameLoad removes its own keys and the env line, nothing else.
        with open(os.path.join(self.anchor_root, pkg, "settings.conf"), "a", encoding="utf-8") as f:
            f.write("passthrough_emul=1\n")
        TuningManager.save_game_tuning(pkg, {"scale": 1.0, "refresh_rate": 0, "hand_input": "auto",
                                             "foveation": "gaze", "text_input": False})
        self.assertEqual(self.conf(pkg), {"passthrough_emul": "1"})
        self.assertNotIn("FDM_DEBUG", self.read(pkg, "launch.sh"))
        self.assertFalse(os.path.exists(os.path.join(self.anchor_root, pkg, "lepton-app", FLATSCREEN_MARKER)))

    def test_game_requiring_hands_gets_them_automatically(self):
        pkg = "com.studio.handsonly"
        res = self.install(pkg, libs=["libframe_settings.so"], features={"oculus.software.handtracking": True})
        self.assertEqual(res["hand_tracking"], "required")
        self.assertEqual(self.conf(pkg), {"controller_fix": "0"})
        self.assertEqual(TuningManager.get_game_tuning(pkg)["hand_input_effective"], "hands")
        TuningManager.save_game_tuning(pkg, {"hand_input": "controllers"})
        self.assertEqual(self.conf(pkg), {"controller_fix": "1"})

    def test_reinstall_keeps_settings(self):
        pkg = "com.studio.update"
        self.install(pkg, libs=["libframe_settings.so"])
        TuningManager.save_game_tuning(pkg, {"scale": 1.5})
        self.install(pkg, libs=["libframe_settings.so"])
        self.assertEqual(TuningManager.get_game_tuning(pkg)["scale"], 1.5)
        self.assertEqual(self.conf(pkg), {"scale": "1.50"})

    def test_presets_and_batch(self):
        pkg = "com.studio.preset"
        self.install(pkg, libs=["libframe_settings.so"])
        self.assertEqual(TuningManager.apply_preset(pkg, "battery")["refresh_rate"], 72)
        self.assertEqual(self.conf(pkg), {"scale": "0.85", "refresh_rate": "72"})
        with self.assertRaises(ValueError):
            TuningManager.apply_preset(pkg, "steam_frame_turbo")
        res = TuningManager.batch_apply("default", [pkg, "com.not.installed"])
        self.assertEqual((res["applied_count"], res["total"]), (1, 2))
        self.assertEqual(self.conf(pkg), {})

    def test_rejects_invalid_values_and_unknown_games(self):
        pkg = "com.studio.invalid"
        self.install(pkg)
        with self.assertRaises(ValueError):
            TuningManager.save_game_tuning(pkg, {"refresh_rate": 75})
        with self.assertRaises(FileNotFoundError):
            TuningManager.get_game_tuning("com.not.installed")

    def test_legacy_launcher_and_settings_are_migrated(self):
        pkg = "com.studio.legacy"
        self.install(pkg)
        game_dir = os.path.join(self.anchor_root, pkg)
        dep = json.loads(self.read(pkg, "deployment.json"))
        dep["settings"] = {"spoof_profile": "quest3", "resolution_scale": 1.25, "refresh_rate": 90}
        for key in ("framebridge", "hand_tracking", "framebridge_keys"):
            dep.pop(key, None)
        with open(os.path.join(game_dir, "deployment.json"), "w", encoding="utf-8") as f:
            json.dump(dep, f)
        with open(os.path.join(game_dir, "launch.sh"), "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\nexport LEPTON_SPOOF_MODEL='Quest 3'\nexport ANDROID_PROPERTY_OVERRIDE=x\n")

        self.assertTrue(TuningManager.apply_tuning_to_game(pkg))
        self.assertNotIn("LEPTON_SPOOF_MODEL", self.read(pkg, "launch.sh"))
        tuning = TuningManager.get_game_tuning(pkg)
        self.assertEqual((tuning["scale"], tuning["refresh_rate"]), (1.0, 0))
        self.assertEqual(self.conf(pkg), {})

    def test_non_lepton_installs_are_left_alone(self):
        game_dir = os.path.join(self.anchor_root, "win.game")
        os.makedirs(game_dir)
        with open(os.path.join(game_dir, "deployment.json"), "w", encoding="utf-8") as f:
            json.dump({"package": "win.game", "kind": "pcvr", "base": game_dir, "anchor": game_dir}, f)
        with open(os.path.join(game_dir, "launch.sh"), "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\nexec proton\n")
        self.assertFalse(TuningManager.apply_tuning_to_game("win.game"))
        self.assertEqual(self.read("win.game", "launch.sh"), "#!/bin/bash\nexec proton\n")
        with self.assertRaises(ValueError):
            TuningManager.save_game_tuning("win.game", {"scale": 1.2})


if __name__ == "__main__":
    unittest.main()
