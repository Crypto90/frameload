"""Unit tests for Steam Frame VR Tuning, Quest 3 Hardware Spoofing, and Supersampling."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from frameload.manager.tuning import TuningManager, PRESETS, SPOOF_PROFILES
from frameload.manager.installed import InstalledManager


class TestSteamFrameTuning(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp_dir, ignore_errors=True))

        # Create mock installed Quest game
        self.pkg = "com.beatgames.beatsaber"
        self.game_dir = os.path.join(self.tmp_dir, self.pkg)
        os.makedirs(self.game_dir, exist_ok=True)

        self.launch_sh = os.path.join(self.game_dir, "launch.sh")
        with open(self.launch_sh, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\nexport SteamAppId=12345\nchild=''\nsetsid lepton start\n")
        os.chmod(self.launch_sh, 0o755)

        self.dep = {
            "package": self.pkg,
            "title": "Beat Saber",
            "appid": 12345,
            "base": self.game_dir,
            "anchor": self.game_dir,
            "is_vr": True,
            "engine": "Unity",
            "settings": {}
        }
        with open(os.path.join(self.game_dir, "deployment.json"), "w", encoding="utf-8") as f:
            json.dump(self.dep, f, indent=2)

    def test_presets_and_spoof_profiles(self):
        presets = TuningManager.get_presets()
        self.assertIn("steam_frame_turbo", presets)
        self.assertIn("max_visuals", presets)
        self.assertIn("high_fps_120", presets)
        self.assertIn("battery_saver", presets)

        spoofs = TuningManager.get_spoof_profiles()
        self.assertIn("quest3", spoofs)
        self.assertEqual(spoofs["quest3"]["device"], "eureka")
        self.assertEqual(spoofs["quest3"]["model"], "Quest 3")
        self.assertIn("quest_pro", spoofs)
        self.assertIn("steam_frame", spoofs)

    def test_apply_tuning_to_game(self):
        with patch.object(InstalledManager, "get_game", return_value=self.dep):
            tuning = {
                "spoof_profile": "quest3",
                "resolution_scale": 1.30,
                "refresh_rate": 90,
                "foveated_rendering": "dynamic",
                "msaa": 4,
                "anisotropic_filtering": 8,
                "cpu_level": 4,
                "gpu_level": 4,
                "controller_models": "steam_frame_roy",
                "haptic_multiplier": 1.2
            }
            res = TuningManager.apply_tuning_to_game(self.pkg, tuning)
            self.assertTrue(res)

            # Check settings.conf
            settings_conf = os.path.join(self.game_dir, "settings.conf")
            self.assertTrue(os.path.isfile(settings_conf))
            with open(settings_conf, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("spoof_model=Quest 3", content)
            self.assertIn("resolution_scale=1.30", content)
            self.assertIn("refresh_rate=90", content)
            self.assertIn("dynamic_foveation=1", content)
            self.assertIn("anisotropic_filtering=8", content)

            # Check Hand Tracking config files
            self.assertTrue(os.path.isfile(os.path.join(self.game_dir, "hand_tracking.json")))
            self.assertTrue(os.path.isfile(os.path.join(self.game_dir, "framebridge_hands.conf")))

            # Check local.prop (Android Bionic properties)
            local_prop = os.path.join(self.game_dir, "lepton-data", "local.prop")
            self.assertTrue(os.path.isfile(local_prop))
            with open(local_prop, "r", encoding="utf-8") as f:
                prop_content = f.read()
            self.assertIn("ro.product.model=Quest 3", prop_content)
            self.assertIn("ro.product.device=eureka", prop_content)
            self.assertIn("debug.oculus.textureWidthRatio=1.30", prop_content)

            # Check launch.sh has tuning env block
            with open(self.launch_sh, "r", encoding="utf-8") as f:
                sh_content = f.read()
            self.assertIn("# === BEGIN STEAM FRAME TUNING ===", sh_content)
            self.assertIn("export LEPTON_SPOOF_MODEL='Quest 3'", sh_content)
            self.assertIn("export LEPTON_VR_RESOLUTION_SCALE=1.30", sh_content)
            self.assertIn("export LEPTON_FOVEATED_RENDERING=dynamic", sh_content)
            self.assertIn("export ANDROID_PROPERTY_OVERRIDE=", sh_content)

    def test_apply_preset(self):
        with patch.object(InstalledManager, "get_game", return_value=self.dep):
            updated = TuningManager.apply_preset(self.pkg, "max_visuals")
            self.assertEqual(updated["spoof_profile"], "quest3")
            self.assertEqual(updated["resolution_scale"], 1.45)
            self.assertEqual(updated["anisotropic_filtering"], 16)
            self.assertEqual(updated["foveated_rendering"], "dynamic")

    def test_unreal_engine_tweaks(self):
        ue_dep = self.dep.copy()
        ue_dep["engine"] = "Unreal"
        with patch.object(InstalledManager, "get_game", return_value=ue_dep):
            TuningManager.apply_tuning_to_game(self.pkg, {
                "spoof_profile": "quest3",
                "resolution_scale": 1.25,
                "msaa": 4
            })
            ue_ini = os.path.join(self.game_dir, "lepton-data/external/Android/data", self.pkg, "files/UE4Game/Engine/Config/ConsoleVariables.ini")
            self.assertTrue(os.path.isfile(ue_ini))
            with open(ue_ini, "r", encoding="utf-8") as f:
                ini_content = f.read()
            self.assertIn("r.ScreenPercentage=125", ini_content)
            self.assertIn("vr.EyeBufferResolutionScale=1.25", ini_content)
            self.assertIn("r.MotionBlurQuality=0", ini_content)
