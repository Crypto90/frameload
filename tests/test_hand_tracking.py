"""Hand input: the mapping to FrameBridge's controller_fix and the status the dashboard shows."""
from __future__ import annotations

import os
import unittest

from frameload.installer import hand_tracking

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frameload", "web")


class TestHandInput(unittest.TestCase):
    def test_controller_fix_mapping(self):
        self.assertEqual(hand_tracking.controller_fix_for("controllers", "required"), 1)
        self.assertEqual(hand_tracking.controller_fix_for("hands", "none"), 0)
        self.assertEqual(hand_tracking.controller_fix_for("auto", "required"), 0)
        # Automatic leaves games that merely support hands on whatever the port was built with.
        self.assertIsNone(hand_tracking.controller_fix_for("auto", "optional"))
        self.assertIsNone(hand_tracking.controller_fix_for("auto", "none"))

    def test_effective_mode(self):
        self.assertEqual(hand_tracking.effective_mode("auto", "required"), "hands")
        self.assertEqual(hand_tracking.effective_mode("auto", "none"), "game")
        self.assertEqual(hand_tracking.effective_mode("controllers", "required"), "controllers")
        self.assertEqual(hand_tracking.effective_mode("nonsense", "none"), "game")

    def test_status_report_is_honest_about_the_hardware(self):
        report = hand_tracking.status_report([
            {"package": "a.vr", "title": "A", "kind": "quest", "is_vr": True, "hand_tracking": "required",
             "framebridge": True, "settings": {}},
            {"package": "b.vr", "title": "B", "kind": "quest", "is_vr": True, "hand_tracking": "none",
             "framebridge": False, "settings": {"hand_input": "hands"}},
            {"package": "c.flat", "title": "C", "kind": "flat", "is_vr": False},
            {"package": "d.win", "title": "D", "kind": "pcvr", "is_vr": True},
        ])
        self.assertFalse(report["optical_supported"])
        self.assertEqual(report["skeleton_source"], "controllers")
        self.assertEqual(report["runtime_extension"], "XR_EXT_hand_tracking")
        self.assertEqual([g["package"] for g in report["games"]], ["a.vr", "b.vr"])
        self.assertEqual(report["games"][0]["effective"], "hands")
        self.assertEqual(report["games"][1]["effective"], "hands")
        self.assertEqual(report["games_requiring_hands"], 1)
        self.assertEqual(hand_tracking.status_report()["games"], [])

    def test_dashboard_no_longer_ships_the_fake_hand_engine(self):
        with open(os.path.join(WEB, "static", "js", "gamepad.js"), "r", encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(WEB, "templates", "index.html"), "r", encoding="utf-8") as f:
            page = f.read()
        for removed in ("VRHandTrackingEngine", "VRInputManager", "Optical Hand Tracking"):
            self.assertNotIn(removed, js)
        for removed in ("toggleVRInputMode", "setVRInputMode", "tune-spoof-profile", "Monado Mercury"):
            self.assertNotIn(removed, page)


if __name__ == "__main__":
    unittest.main()
