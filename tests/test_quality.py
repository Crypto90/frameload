import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.manager import quality  # noqa: E402
from frameload.manager.tuning import TuningManager  # noqa: E402


def windows(*runs):
    """Pacing values: (fps, count) runs after two loading windows."""
    out = [20.0, 40.0]
    for fps, count in runs:
        out += [fps] * count
    return out


class TestAutomaticQuality(unittest.TestCase):
    def test_steady_with_headroom_goes_one_step_sharper_up_to_the_cap(self):
        new, why = quality.decide({}, windows((90.2, 30)), 0.31, "stopped_player", [], 90)
        self.assertEqual(new["scale"], 1.1)
        self.assertIn("90 Hz", why)
        new, _ = quality.decide({"scale": 1.3}, windows((90.2, 30)), 0.2, "quit", [], 90)
        self.assertEqual(new["scale"], 1.3)  # MAX_SCALE
        # A busy GPU, no GPU reading, too short a session or a crash: nothing goes up.
        for args in ((windows((90.2, 30)), 0.7, "quit"), (windows((90.2, 30)), None, "quit"),
                     (windows((90.2, 5)), 0.2, "quit"), (windows((90.2, 30)), 0.2, "crashed")):
            self.assertEqual(quality.decide({}, *args, [], 90)[1], "")

    def test_too_slow_steps_back_in_order(self):
        slow = windows((90.0, 10), (70.0, 20))  # two thirds of the time under 81 fps at 90 Hz
        new, why = quality.decide({"scale": 1.2}, slow, 0.9, "quit", [], 90)
        self.assertEqual(new["scale"], 1.1)  # first FrameLoad's own extra resolution
        new, why = quality.decide({"scale": 1.0}, slow, 0.9, "quit", [], 90)
        self.assertEqual(new["rate_cap"], 72)  # then the refresh rate
        self.assertIn("72 Hz", why)
        new, _ = quality.decide({"scale": 1.0, "rate_cap": 72}, windows((72.0, 5), (55.0, 20)), 0.9, "quit", [], 90)
        self.assertEqual(new["scale"], 0.9)  # then below 1.0x, down to MIN_SCALE
        self.assertEqual(quality.decide({"scale": 0.8, "rate_cap": 72}, windows((50.0, 25)), 0.9, "quit", [], 90)[1], "")

    def test_the_players_own_settings_are_never_touched(self):
        slow = windows((90.0, 10), (70.0, 20))
        self.assertEqual(quality.decide({"scale": 1.0}, slow, 0.9, "quit", ["scale", "refresh_rate"], 90)[1], "")
        self.assertEqual(quality.decide({}, windows((90.2, 30)), 0.2, "quit", ["scale"], 90)[1], "")

    def test_a_hang_after_a_raise_goes_back_to_1x(self):
        new, why = quality.decide({"scale": 1.2}, [], None, "gpu_hang", [], 90)
        self.assertEqual(new["scale"], 1.0)
        self.assertIn("gpu_hang", why)

    def test_it_sits_under_the_games_own_settings_and_can_be_switched_off(self):
        dep = {"package": "p", "auto_quality": {"scale": 1.2, "rate_cap": 72}, "game_refresh_rate": 90,
               "settings": {}}
        with patch.object(TuningManager, "recommended_settings", return_value={}), \
                patch.object(quality, "enabled", return_value=True):
            self.assertEqual(TuningManager.effective_settings(dep)["scale"], 1.2)
            self.assertEqual(TuningManager.display_rate({"refresh_rate": 0}, dep), 72)
            self.assertEqual(TuningManager.display_rate({"refresh_rate": 120}, dep), 120)
            dep["settings"] = {"scale": 1.0}
            self.assertEqual(TuningManager.effective_settings(dep)["scale"], 1.0)
        with patch.object(TuningManager, "recommended_settings", return_value={}), \
                patch.object(quality, "enabled", return_value=False):
            dep["settings"] = {}
            self.assertEqual(TuningManager.effective_settings(dep)["scale"], 1.0)
            self.assertEqual(TuningManager.display_rate({"refresh_rate": 0}, dep), 90)



class TestBackupBeforeChange(unittest.TestCase):
    def test_keeps_the_newest_three_automatic_backups_and_never_stops_an_install(self):
        import shutil
        import tempfile
        from frameload.manager import backup

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        made = []

        def fake_backup(pkg, anchor=""):
            name = f"{pkg}_save_2026102{len(made)}_120000.tar.gz"
            open(os.path.join(tmp, name), "w").close()
            made.append(name)
            return {"filename": name}

        manual = os.path.join(tmp, "p.game_save_20260101_000000.tar.gz")
        open(manual, "w").close()
        with patch.object(backup, "BACKUP_DIR", tmp), patch.object(backup, "AUTO_INDEX", os.path.join(tmp, "a.json")), \
                patch.object(backup.SaveBackupManager, "backup_saves", side_effect=fake_backup):
            for _ in range(5):
                backup.SaveBackupManager.backup_before_change("p.game")
        left = sorted(n for n in os.listdir(tmp) if n.endswith(".tar.gz"))
        self.assertEqual(left, sorted(made[-3:] + [os.path.basename(manual)]))  # a backup made by hand stays
        with patch.object(backup.SaveBackupManager, "backup_saves", side_effect=OSError("disk full")):
            self.assertIsNone(backup.SaveBackupManager.backup_before_change("p.game"))
        with patch.object(backup.SaveBackupManager, "backup_saves", side_effect=backup.NoSaveData("none")):
            self.assertIsNone(backup.SaveBackupManager.backup_before_change("p.game"))


if __name__ == "__main__":
    unittest.main()
