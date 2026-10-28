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


if __name__ == "__main__":
    unittest.main()
