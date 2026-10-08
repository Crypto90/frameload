"""Unit tests for FrameLoad Hand Tracking Bridge & Roy Capacitive Synthesis."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from frameload.installer.hand_tracking import (
    HandTrackingManager,
    OVRP_BONE_INDICES,
    XR_HAND_JOINTS,
    REST_SKELETON_OFFSETS_RIGHT,
)


class TestHandTracking(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp_dir, ignore_errors=True))

    def test_skeletal_hierarchy_definitions(self):
        # Must have 26 bones/joints matching Meta Quest / OpenXR
        self.assertGreaterEqual(len(OVRP_BONE_INDICES), 25)
        self.assertEqual(len(XR_HAND_JOINTS), 26)

        self.assertIn("Wrist_Root", OVRP_BONE_INDICES)
        self.assertIn("Thumb_3", OVRP_BONE_INDICES)
        self.assertIn("Index_Tip", OVRP_BONE_INDICES)
        self.assertIn("Middle_Tip", OVRP_BONE_INDICES)
        self.assertIn("Ring_Tip", OVRP_BONE_INDICES)
        self.assertIn("Pinky_Tip", OVRP_BONE_INDICES)

        # Offsets exist for anatomically correct rest pose
        self.assertIn("Wrist_Root", REST_SKELETON_OFFSETS_RIGHT)
        self.assertIn("Index_Tip", REST_SKELETON_OFFSETS_RIGHT)
        self.assertEqual(REST_SKELETON_OFFSETS_RIGHT["Wrist_Root"], (0.0, 0.0, 0.0))

    def test_synthetic_pinch_calculation(self):
        # Resting / no touch
        pinch_idle = HandTrackingManager.calculate_synthetic_pinch(
            trigger_touch=False, trigger_value=0.0, thumb_touch=False
        )
        self.assertFalse(pinch_idle["is_pinching"])
        self.assertGreater(pinch_idle["tip_distance_mm"], 20.0)

        # Full trigger pull = pinch
        pinch_pulled = HandTrackingManager.calculate_synthetic_pinch(
            trigger_touch=True, trigger_value=0.85, thumb_touch=True
        )
        self.assertTrue(pinch_pulled["is_pinching"])
        self.assertEqual(pinch_pulled["pinch_strength"], 0.85)
        self.assertLess(pinch_pulled["tip_distance_mm"], 10.0)

        # Capacitive touch pinch with partial trigger
        pinch_touch = HandTrackingManager.calculate_synthetic_pinch(
            trigger_touch=True, trigger_value=0.40, thumb_touch=True
        )
        self.assertTrue(pinch_touch["is_pinching"])

    def test_calculate_finger_curls(self):
        # Extended hand
        curls_open = HandTrackingManager.calculate_finger_curls(
            thumb_touch=False, trigger_value=0.0, grip_value=0.0
        )
        self.assertLess(curls_open["thumb"], 0.3)
        self.assertLess(curls_open["index"], 0.2)
        self.assertLess(curls_open["middle"], 0.2)

        # Fist grasp
        curls_fist = HandTrackingManager.calculate_finger_curls(
            thumb_touch=True, trigger_value=1.0, grip_value=1.0
        )
        self.assertGreater(curls_fist["thumb"], 0.5)
        self.assertEqual(curls_fist["index"], 1.0)
        self.assertEqual(curls_fist["middle"], 1.0)
        self.assertEqual(curls_fist["ring"], 1.0)
        self.assertEqual(curls_fist["pinky"], 1.0)

    def test_build_hand_tracking_config(self):
        config_synth = HandTrackingManager.build_hand_tracking_config(mode="synthetic")
        self.assertTrue(config_synth["enabled"])
        self.assertEqual(config_synth["mode"], "synthetic")
        self.assertEqual(config_synth["openxr_extension"], "XR_EXT_hand_tracking")
        self.assertIn("synthetic_profile", config_synth)

        config_disabled = HandTrackingManager.build_hand_tracking_config(mode="disabled")
        self.assertFalse(config_disabled["enabled"])
        self.assertEqual(config_disabled["mode"], "disabled")

    def test_generate_hand_tracking_files(self):
        pkg = "com.sample.questgame"
        app_dir = os.path.join(self.tmp_dir, pkg)
        lepton_game_files = os.path.join(app_dir, "lepton-data/external/Android/data", pkg, "files")
        os.makedirs(lepton_game_files, exist_ok=True)

        res = HandTrackingManager.generate_hand_tracking_files(
            app_dir=app_dir,
            package_name=pkg,
            mode="synthetic",
            pinch_sensitivity_mm=22.5
        )
        self.assertTrue(res)

        # Verify app_dir files
        json_path = os.path.join(app_dir, "hand_tracking.json")
        conf_path = os.path.join(app_dir, "framebridge_hands.conf")
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(conf_path))

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["mode"], "synthetic")
            self.assertEqual(data["pinch_sensitivity_mm"], 22.5)

        with open(conf_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn(f"package_name={pkg}", content)
            self.assertIn("hand_tracking_mode=synthetic", content)
            self.assertIn("roy_capacitive_synthesis=1", content)

        # Verify lepton internal files
        self.assertTrue(os.path.isfile(os.path.join(lepton_game_files, "framebridge_hands.conf")))
        self.assertTrue(os.path.isfile(os.path.join(lepton_game_files, "hand_tracking.json")))

    def test_get_diagnostic_report(self):
        report = HandTrackingManager.get_diagnostic_report(mode="synthetic")
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["controller_synthesis"])
        self.assertEqual(report["skeletal_joints"], 26)
        self.assertIn("WebXR Hand Input API", report["supported_runtimes"])

    def test_vr_input_switcher_frontend_assets(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = os.path.join(root_dir, "frameload/web/templates/index.html")
        css_path = os.path.join(root_dir, "frameload/web/static/css/style.css")
        js_path = os.path.join(root_dir, "frameload/web/static/js/gamepad.js")

        self.assertTrue(os.path.isfile(html_path))
        self.assertTrue(os.path.isfile(css_path))
        self.assertTrue(os.path.isfile(js_path))

        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
            self.assertIn("id=\"header-input-mode\"", html)
            self.assertIn("toggleVRInputMode()", html)
            self.assertIn("name=\"vr-input-mode\"", html)
            self.assertIn("value=\"auto\"", html)
            self.assertIn("value=\"controllers\"", html)
            self.assertIn("value=\"hands\"", html)

        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()
            self.assertIn(".telemetry-chip.input-mode", css)

        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
            self.assertIn("class VRInputManager", js)
            self.assertIn("window.setVRInputMode", js)
            self.assertIn("window.toggleVRInputMode", js)
            self.assertIn("updateHUDHandsMode", js)
            self.assertIn("pollControllersState", js)


if __name__ == "__main__":
    unittest.main()
