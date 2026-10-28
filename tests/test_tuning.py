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

from frameload.installer.lepton_quest import FLATSCREEN_MARKER, LeptonInstaller, find_obb_dir, find_release_obb  # noqa: E402
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
        # Turnip's TU_DEBUG goes in as a boot property (Mesa reads debug.mesa.tu.debug on Android).
        env = TuningManager.launch_env({**base, "foveation": "off", "gpu_driver": "sysmem"}, True)
        self.assertEqual(env, {"VK_INSTANCE_LAYERS": "",
                               "LEPTON_GFXRECON_FRAMELOAD": "0\ndebug.mesa.tu.debug=sysmem,startup"})
        self.assertEqual(TuningManager.launch_env({**base, "gpu_driver": "sysmem"}, False),
                         {"LEPTON_GFXRECON_FRAMELOAD": "0\nqemu.hw.mainkeys=1"})

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

    def test_a_new_install_has_the_current_layout(self):
        from frameload.manager import migrate
        self.install("com.studio.layout")
        dep = json.loads(self.read("com.studio.layout", "deployment.json"))
        self.assertEqual(dep["layout_version"], migrate.LAYOUT_VERSION)  # else migrate rewrites it at once
        self.assertIn("LEPTON_DUMP_LOGCAT=1", self.read("com.studio.layout", "launch.sh"))

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

    def test_mirror_release_obb_folder_is_found_beside_the_apk(self):
        pkg = "com.studio.mirror"
        root = os.path.join(self.tmp, "Mirror Game v5+1.0 -VRP")
        release = os.path.join(root, "Mirror Game v5+1.0 -VRP")
        os.makedirs(os.path.join(release, pkg, "files", "Game_Data"))
        apk = os.path.join(release, f"{pkg}.apk")
        with open(apk, "wb") as f:
            f.write(b"apk")
        # A package folder with no .obb in it (Rick and Morty keeps a files/ folder) is still the OBB folder.
        self.assertEqual(find_release_obb(root, apk, pkg), os.path.join(release, pkg))
        self.assertEqual(find_release_obb(root, None, pkg), os.path.join(release, pkg))
        self.assertEqual(find_obb_dir(os.path.join(release, pkg), pkg), os.path.join(release, pkg))
        res = self.install(pkg, obb_path=find_release_obb(root, apk, pkg))
        self.assertTrue(os.path.isdir(os.path.join(self.anchor_root, pkg, "lepton-app", "obb", "files", "Game_Data")))
        self.assertEqual(res["obb_files"], 1)

    def test_loose_obb_beside_the_apk_and_no_obb(self):
        pkg = "com.studio.loose"
        release = os.path.join(self.tmp, "rel", "Loose v2+1 -JF")
        os.makedirs(release)
        apk = os.path.join(release, f"{pkg}.apk")
        for name in (f"{pkg}.apk", f"main.2.{pkg}.obb"):
            with open(os.path.join(release, name), "wb") as f:
                f.write(b"x")
        self.assertEqual(find_release_obb(os.path.join(self.tmp, "rel"), apk, pkg),
                         os.path.join(release, f"main.2.{pkg}.obb"))
        os.remove(os.path.join(release, f"main.2.{pkg}.obb"))
        self.assertIsNone(find_release_obb(os.path.join(self.tmp, "rel"), apk, pkg))

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
        # Presets combine: Sharper keeps 120 Hz, and neither touches foveation.
        TuningManager.save_game_tuning(pkg, {"foveation": "off"})
        TuningManager.apply_preset(pkg, "smooth")
        both = TuningManager.apply_preset(pkg, "sharp")
        self.assertEqual((both["scale"], both["refresh_rate"], both["foveation"]), (1.3, 120, "off"))
        res = TuningManager.batch_apply("default", [pkg, "com.not.installed"])
        self.assertEqual((res["applied_count"], res["total"]), (1, 2))
        self.assertEqual(self.conf(pkg), {})
        self.assertEqual(TuningManager.get_game_tuning(pkg)["foveation"], "off")

    def stored(self, package):
        return json.loads(self.read(package, "deployment.json"))["settings"]

    def test_defaults_still_reach_settings_a_game_did_not_change(self):
        pkg = "com.studio.defaults"
        self.install(pkg, libs=["libframe_settings.so"])
        defaults = DEFAULTS.copy()
        with patch.object(TuningManager, "get_global_tuning", side_effect=lambda: dict(defaults)):
            # The dialog sends every value it shows; only the one the player changed becomes the game's own.
            shown = TuningManager.get_game_tuning(pkg)
            sent = {s["key"]: shown[s["key"]] for s in SETTINGS_SCHEMA if s["scope"] == "vr"}
            TuningManager.save_game_tuning(pkg, dict(sent, scale=1.3))
            self.assertEqual(self.stored(pkg), {"scale": 1.3})

            # A later change of the defaults reaches the refresh rate, not the scale the player set.
            defaults.update(refresh_rate=90, scale=1.5)
            TuningManager.apply_tuning_to_game(pkg)  # what saving the defaults does for every game
            self.assertEqual(self.conf(pkg), {"scale": "1.30", "refresh_rate": "90"})

            # Back to the default: the game follows the defaults again.
            TuningManager.save_game_tuning(pkg, {"scale": 1.5, "refresh_rate": 90})
            self.assertEqual(self.stored(pkg), {})
            # The built-in value is the player's own choice while the defaults say otherwise.
            TuningManager.save_game_tuning(pkg, {"refresh_rate": 0})
            self.assertEqual(self.stored(pkg), {"refresh_rate": 0})
            self.assertEqual(self.conf(pkg), {"scale": "1.50"})

    def test_preset_stores_only_what_differs_from_the_defaults(self):
        pkg = "com.studio.presetdefaults"
        self.install(pkg, libs=["libframe_settings.so"])
        defaults = dict(DEFAULTS, refresh_rate=90)
        with patch.object(TuningManager, "get_global_tuning", side_effect=lambda: dict(defaults)):
            TuningManager.apply_preset(pkg, "sharp")  # scale 1.3; the 90 Hz default stays
            self.assertEqual(self.stored(pkg), {"scale": 1.3})
            self.assertEqual(self.conf(pkg), {"scale": "1.30", "refresh_rate": "90"})
            TuningManager.apply_preset(pkg, "default")
            self.assertEqual(self.stored(pkg), {"refresh_rate": 0})

    def test_settings_saved_by_older_versions_still_apply(self):
        # Up to v1.3.6 a saved dialog stored every value, the defaults included.
        pkg = "com.studio.everything"
        self.install(pkg, libs=["libframe_settings.so"])
        path = os.path.join(self.anchor_root, pkg, "deployment.json")
        dep = json.loads(self.read(pkg, "deployment.json"))
        dep["settings"] = dict(DEFAULTS, refresh_rate=120)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dep, f)
        self.assertEqual(TuningManager.get_game_tuning(pkg)["refresh_rate"], 120)
        TuningManager.save_game_tuning(pkg, {k: v for k, v in DEFAULTS.items() if k != "refresh_rate"})
        self.assertEqual(self.stored(pkg), {"refresh_rate": 120})
        self.assertEqual(self.conf(pkg), {"refresh_rate": "120"})

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
