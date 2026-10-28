import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.installer import apk_analysis, porting  # noqa: E402
from frameload.installer.lepton_quest import LAUNCH_SCRIPT_TEMPLATE, REFRESH_RATE_LINE  # noqa: E402
from frameload.manager import sessions  # noqa: E402
from frameload.manager.tuning import TuningManager  # noqa: E402
from frameload.system import steamvr_settings  # noqa: E402

PKG = "games.b4t.epicrollercoasters.oculus"


def apk(path, loader=None, framebridge=True):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"")
        if loader is not None:
            zf.writestr("lib/arm64-v8a/libopenxr_loader.so", loader)
        if framebridge:
            zf.writestr("lib/arm64-v8a/libframe_settings.so", b"\0")
    return path


class FakeVR:
    def __init__(self):
        self.calls, self.closed = [], False

    def set_refresh_rate(self, appid, rate):
        self.calls.append((appid, rate))

    def close(self):
        self.closed = True


class TestHeadsetIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_reads_the_name_ovrports_dispatcher_answers(self):
        old = apk(os.path.join(self.tmp, "a.apk"), b"\x7fELF...Oculus Quest2\0...")
        new = apk(os.path.join(self.tmp, "b.apk"), b"\x7fELF...Meta Quest 3\0\0...")
        s = apk(os.path.join(self.tmp, "c.apk"), b"\x7fELF...Meta Quest 3S\0...")
        self.assertEqual(apk_analysis.headset_identity(old), "quest2")
        self.assertEqual(apk_analysis.headset_identity(new), "quest3")
        self.assertEqual(apk_analysis.headset_identity(s), "quest3s")
        self.assertEqual(apk_analysis.headset_identity(apk(os.path.join(self.tmp, "d.apk"), b"\x7fELF")), "unknown")
        # Not ported (no FrameBridge) or a native OpenXR app: SteamVR answers for itself.
        self.assertEqual(apk_analysis.headset_identity(apk(os.path.join(self.tmp, "e.apk"), b"Oculus Quest2\0",
                                                            framebridge=False)), "")
        self.assertEqual(apk_analysis.headset_identity(apk(os.path.join(self.tmp, "f.apk"))), "")

    def test_quest2_games_are_ported_again_once_per_frameport(self):
        games = [{"package": PKG, "is_running": False}, {"package": "com.other.game", "is_running": False}]
        deps = {
            PKG: {"package": PKG, "title": "Epic Roller Coasters", "kind": "quest", "installed_by": "frameload",
                  "framebridge": True, "headset": "quest2"},
            "com.other.game": {"package": "com.other.game", "kind": "quest", "installed_by": "frameload",
                               "framebridge": True, "headset": "quest3"},
        }
        with patch("frameload.manager.installed.InstalledManager.list_installed", return_value=games), \
                patch("frameload.manager.installed.InstalledManager.get_game", side_effect=lambda p: deps.get(p)):
            self.assertEqual([g["package"] for g in porting.quest2_games("1.4.0")], [PKG])
            self.assertEqual(porting.quest2_games("1.3.0"), [])  # no headset_model patch yet
            deps[PKG]["identity_port_tried"] = "1.4.0"
            self.assertEqual(porting.quest2_games("1.4.0"), [])
            self.assertEqual(len(porting.quest2_games("1.4.1.dev714")), 1)  # a newer FramePort tries once more
            deps[PKG]["installed_by"] = "frameport"
            self.assertEqual(porting.quest2_games("1.5.0"), [])  # FramePort's own installs are its business

    def test_no_port_starts_while_a_game_runs(self):
        games = [{"package": PKG, "is_running": True}]
        dep = {"package": PKG, "title": "Epic Roller Coasters", "kind": "quest", "installed_by": "frameload",
               "framebridge": True, "headset": "quest2"}
        logged = []
        with patch("frameload.manager.installed.InstalledManager.list_installed", return_value=games), \
                patch("frameload.manager.installed.InstalledManager.get_game", return_value=dep), \
                patch.object(porting, "port_installed_game") as port:
            self.assertEqual(porting.port_as_quest3(logged.append, "1.4.0"), [])
        port.assert_not_called()
        self.assertIn("running", logged[0])


class TestRefreshRate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_launch_sh_asks_steamvr_before_lepton_starts(self):
        text = LAUNCH_SCRIPT_TEMPLATE
        self.assertLess(text.index("{refresh_rate}"), text.index('setsid "$lepton" start'))
        self.assertGreater(text.index("{refresh_rate}"), text.index("export SteamAppId="))
        self.assertIn("timeout 10s", REFRESH_RATE_LINE)
        self.assertIn('"$SteamAppId"', REFRESH_RATE_LINE)

    def test_sets_and_clears_only_its_own_key(self):
        vr = FakeVR()
        self.assertIn("nothing", steamvr_settings.apply(self.tmp, 3677036329, opener=lambda: vr))
        steamvr_settings.write_rate(self.tmp, 0)
        self.assertIn("left alone", steamvr_settings.apply(self.tmp, 3677036329, opener=lambda: vr))
        self.assertEqual(vr.calls, [])  # a rate the player set in SteamVR themselves stays
        steamvr_settings.write_rate(self.tmp, 90)
        self.assertIn("90 Hz", steamvr_settings.apply(self.tmp, 3677036329, opener=lambda: vr))
        steamvr_settings.write_rate(self.tmp, 0)
        self.assertIn("removed", steamvr_settings.apply(self.tmp, 3677036329, opener=lambda: vr))
        self.assertEqual(vr.calls, [(3677036329, 90.0), (3677036329, 0.0)])
        self.assertTrue(vr.closed)
        steamvr_settings.write_rate(self.tmp, 120)
        self.assertIn("not running", steamvr_settings.apply(self.tmp, 1, opener=lambda: None))

    def test_players_rate_wins_over_the_games(self):
        self.assertEqual(TuningManager.display_rate({"refresh_rate": 120}, {"game_refresh_rate": 90}), 120)
        self.assertEqual(TuningManager.display_rate({"refresh_rate": 0}, {"game_refresh_rate": 90}), 90)
        self.assertEqual(TuningManager.display_rate({"refresh_rate": 0}, {}), 0)

    def test_the_rate_a_game_asked_for_is_kept_for_its_next_start(self):
        lines = ["10-28 19:38:52.307  1212  1236 I FrameBridge: refresh rate: app asked for 90.0 Hz, "
                 "requested 90.0 Hz: result -1000101000",
                 "10-28 19:38:55.442  1212  1236 I FrameBridge: refresh rate: app asked for 72.0 Hz, "
                 "requested 72.0 Hz: result 0"]
        dep = {"package": PKG, "installed_by": "frameload", "anchor": self.tmp}
        with patch.object(TuningManager, "apply_tuning_to_game") as apply_tuning:
            self.assertEqual(sessions.learn_refresh_rate(PKG, dep, lines), 90)
            apply_tuning.assert_called_once()
            with open(os.path.join(self.tmp, "deployment.json")) as f:
                self.assertEqual(json.load(f)["game_refresh_rate"], 90)
            self.assertEqual(sessions.learn_refresh_rate(PKG, dep, lines), 90)
            apply_tuning.assert_called_once()  # unchanged: nothing rewritten
        self.assertEqual(sessions.learn_refresh_rate(PKG, {"package": PKG}, ["no request"]), 0)
        self.assertEqual(steamvr_settings.snap_rate(89.9), 90)
        self.assertEqual(steamvr_settings.snap_rate(119.88), 120)


if __name__ == "__main__":
    unittest.main()
