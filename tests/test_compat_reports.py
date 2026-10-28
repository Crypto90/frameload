import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.manager import compat_reports  # noqa: E402

PKG = "com.VerticalRobot.RedMatter2"


class FakeConfig:
    def __init__(self, data=None):
        self.raw = data or {}

    def __getitem__(self, key):
        return self.raw.get(key, {})

    def __setitem__(self, key, value):
        self.raw[key] = value


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def record(**kw):
    base = {"package": PKG, "title": "Red Matter 2", "outcome": "stopped_player", "end": int(time.time()),
            "duration": 153, "frames": {"drew": True, "fps": 72.2}, "auto_fix": "", "kind": "vr",
            "lepton": "3.0.5 (rootfs 3.0.3)"}
    base.update(kw)
    return base


class TestCompatReports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.config = FakeConfig()
        self.sent = []
        compat_reports._state.update(list=None, fetched=0.0, tried=0.0, fetching=False, last_report=None)

        def urlopen(request, timeout):
            self.sent.append(request)
            if request.get_method() == "POST":
                return FakeResponse(json.dumps({"ok": True, "rating": "working", "status": "working"}).encode())
            return FakeResponse(json.dumps({"games": {PKG: {
                "status": "working", "label": "Working", "note": "Foveation off.",
                "settings_text": ["Foveated rendering: Off"], "reports": 4, "url": "https://x/game"}}}).encode())

        for p in (patch.object(compat_reports.Config, "get", return_value=self.config),
                  patch.object(compat_reports, "_urlopen", side_effect=urlopen),
                  patch.object(compat_reports, "CACHE_FILE", os.path.join(self.tmp, "compat_list.json"))):
            p.start()
            self.addCleanup(p.stop)

    def test_rating_matches_the_website(self):
        self.assertEqual(compat_reports.rating(record()), "working")
        self.assertEqual(compat_reports.rating(record(duration=40)), "partial")
        self.assertEqual(compat_reports.rating(record(auto_fix="foveation_off")), "partial")
        self.assertEqual(compat_reports.rating(record(outcome="gpu_hang", duration=38)), "broken")
        self.assertEqual(compat_reports.rating(record(outcome="gpu_hang", duration=90)), "partial")
        self.assertEqual(compat_reports.rating(record(outcome="start_failed", frames={})), "broken")
        self.assertEqual(compat_reports.rating(record(frames={"drew": False}, duration=600)), "partial")

    def test_nothing_is_sent_until_the_player_shares(self):
        dep = {"package": PKG, "title": "Red Matter 2", "version_code": "75", "engine": "Unreal", "framebridge": True}
        self.assertIsNone(compat_reports.send(record(), dep))
        self.assertEqual(self.sent, [])
        compat_reports.save_settings({"share": True})
        with patch("frameload.manager.tuning.TuningManager.effective_settings",
                   return_value={"scale": 1.0, "refresh_rate": 0, "foveation": "off", "hand_input": "auto"}):
            answer = compat_reports.send(record(), dep)
        self.assertEqual(answer["rating"], "working")
        body = json.loads(self.sent[0].data)
        self.assertEqual((body["package"], body["outcome"], body["drew"], body["version_code"]),
                         (PKG, "stopped_player", True, "75"))
        self.assertEqual(body["settings"], {"scale": 1.0, "refresh_rate": 0, "foveation": "off"})
        # One random id per headset, kept.
        self.assertEqual(body["install_id"], self.config.raw["compat"]["install_id"])
        self.assertEqual(len(body["install_id"]), 36)
        self.assertNotIn("home", json.dumps(body).lower())

        # A hang's report names the settings the session hung with, not the fix FrameLoad applied afterwards.
        with patch("frameload.manager.tuning.TuningManager.effective_settings", return_value={"foveation": "off"}):
            body = compat_reports.payload(record(outcome="gpu_hang", settings={"foveation": "gaze", "gpu_driver": "default"}), dep)
        self.assertEqual(body["settings"], {"foveation": "gaze", "gpu_driver": "default"})

    def write_art(self, state):
        art = os.path.join(self.tmp, "game", "artwork")
        os.makedirs(art, exist_ok=True)
        with open(os.path.join(art, "icon.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nicon")
        with open(os.path.join(art, "artwork.json"), "w") as f:
            json.dump({"icon": state}, f)
        return {"package": PKG, "title": "Red Matter 2", "anchor": os.path.join(self.tmp, "game")}

    def test_the_icon_goes_along_only_while_the_list_has_none(self):
        dep = self.write_art("composed")
        with patch("frameload.manager.tuning.TuningManager.effective_settings", return_value={}):
            body = compat_reports.payload(record(), dep)
            self.assertEqual(body["icon"], "iVBORw0KGgppY29u")
            compat_reports._state["list"] = {PKG: {"status": "working", "icon": "https://x/icon.php?package=" + PKG}}
            self.assertNotIn("icon", compat_reports.payload(record(), dep))
            compat_reports._state["list"] = {}
            # A placeholder FrameLoad drew from the title is not the game's icon.
            self.assertNotIn("icon", compat_reports.payload(record(), self.write_art("generated")))

    def test_library_gets_the_community_status_from_a_cached_list(self):
        games = [{"package": PKG}, {"package": "com.not.listed"}]
        compat_reports.annotate(games)  # first look: fetches in the background
        for _ in range(50):
            if compat_reports._state["list"]:
                break
            time.sleep(0.02)
        self.assertNotIn("packages", self.sent[0].full_url)  # never says which games are installed
        compat_reports.annotate(games)
        self.assertEqual(games[0]["community"]["status"], "working")
        self.assertNotIn("community", games[1])
        self.assertEqual(len(self.sent), 1)  # cached: no second fetch
        compat_reports.save_settings({"show": False})
        self.assertEqual(compat_reports.annotate([{"package": PKG}]), [{"package": PKG}])

    def test_recommended_settings_come_from_the_cached_list_only(self):
        compat_reports._state["list"] = {PKG: {"status": "working", "settings": {
            "foveation": "off", "gpu_driver": "sysmem", "min_frameload": "1.4.2",
            "scale": 1.5, "hide_space_warp": "yes"}},
            "com.bad.values": {"settings": {"foveation": "sideways", "gpu_driver": "rm -rf"}}}
        # Only settings that make a game run, with valid values; never taste such as the resolution.
        self.assertEqual(compat_reports.recommended(PKG),
                         {"foveation": "off", "gpu_driver": "sysmem", "hide_space_warp": True})
        self.assertEqual(compat_reports.recommended("com.bad.values"), {})
        self.assertEqual(compat_reports.recommended("com.not.listed"), {})
        self.assertEqual(self.sent, [])  # reading a recommendation never fetches
        compat_reports.save_settings({"recommended": False})
        self.assertEqual(compat_reports.recommended(PKG), {})

    def test_the_installed_versions_own_recommendation_comes_first(self):
        compat_reports._state["list"] = {PKG: {"settings": {"foveation": "off"}, "settings_by_version": {
            "75": {"foveation": "off", "gpu_driver": "sysmem"}, "80": {}}}}
        self.assertEqual(compat_reports.recommended(PKG, 75), {"foveation": "off", "gpu_driver": "sysmem"})
        self.assertEqual(compat_reports.recommended(PKG, "80"), {})  # reports say this version needs nothing
        self.assertEqual(compat_reports.recommended(PKG, "90"), {"foveation": "off"})  # unknown version: the game's
        self.assertEqual(compat_reports.recommended(PKG), {"foveation": "off"})

    def test_recommended_settings_sit_under_the_games_own(self):
        from frameload.manager.tuning import TuningManager
        compat_reports._state["list"] = {PKG: {"settings": {"foveation": "off", "gpu_driver": "sysmem"}}}
        with patch.object(TuningManager, "get_global_tuning", return_value={"foveation": "gaze", "gpu_driver": "default",
                                                                             "scale": 1.0}):
            dep = {"package": PKG, "settings": {}}
            self.assertEqual(TuningManager.effective_settings(dep),
                             {"foveation": "off", "gpu_driver": "sysmem", "scale": 1.0})
            dep["settings"] = {"foveation": "gaze"}  # the player chose otherwise: that wins
            self.assertEqual(TuningManager.effective_settings(dep)["foveation"], "gaze")
            self.assertEqual(TuningManager.effective_settings(dep)["gpu_driver"], "sysmem")

    def test_a_changed_recommendation_rewrites_the_launcher_once(self):
        from frameload.manager.installed import InstalledManager
        from frameload.manager.tuning import TuningManager
        dep = {"package": PKG, "kind": "quest", "settings": {}}
        compat_reports._state["list"] = {PKG: {"settings": {"gpu_driver": "sysmem"}}}
        with patch.object(InstalledManager, "get_game", return_value=dep), \
                patch.object(TuningManager, "_write_dep"), \
                patch.object(TuningManager, "apply_tuning_to_game") as apply:
            self.assertTrue(TuningManager.sync_recommended(PKG))
            self.assertFalse(TuningManager.sync_recommended(PKG))  # unchanged: the launcher stays
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(dep["recommended_applied"], {"gpu_driver": "sysmem"})
            dep["installed_by"] = "frameport"  # FramePort's launchers are left as they are
            compat_reports._state["list"] = {}
            self.assertFalse(TuningManager.sync_recommended(PKG))

    def test_the_installed_versions_own_status_wins_once_enough_headsets_played_it(self):
        compat_reports._state.update(list={PKG: {"status": "working", "label": "Working", "status_by_version": {
            "80": {"status": "broken", "reports": 3}, "79": {"status": "partial", "reports": 1}}}},
            fetched=time.time())
        games = [{"package": PKG, "version_code": "80"}, {"package": PKG, "version_code": 79},
                 {"package": PKG, "version_code": "75"}]
        compat_reports.annotate(games)
        self.assertEqual((games[0]["community"]["status"], games[0]["community"]["label"],
                          games[0]["community"]["version"]), ("broken", "Not working", "80"))
        self.assertEqual(games[1]["community"]["status"], "working")  # one headset decides nothing
        self.assertEqual(games[2]["community"]["status"], "working")  # an unreported version: the game's
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
