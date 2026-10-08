"""Porting through FramePort's command line, migration of old installs, and the self-test."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from axml_builder import manifest, write_apk  # noqa: E402

from frameload.installer import porting  # noqa: E402
from frameload.installer.lepton_quest import LeptonInstaller  # noqa: E402
from frameload.manager import migrate  # noqa: E402
from frameload.manager.installed import InstalledManager  # noqa: E402
from frameload.manager.tuning import DEFAULTS, TuningManager  # noqa: E402
from frameload.system import doctor  # noqa: E402

VR = "com.oculus.intent.category.VR"
INFO = "android.intent.category.INFO"
FAKE_CLI = [sys.executable, os.path.join(HERE, "fake_frameport.py")]


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def edit_json(path, change):
    data = json.loads(read_text(path))
    change(data)
    write_text(path, json.dumps(data))


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.anchor_root = os.path.join(self.tmp, "quest-frame")

        def get_game(package_name):
            path = os.path.join(self.anchor_root, package_name, "deployment.json")
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                dep = json.load(f)
            dep.setdefault("anchor", os.path.dirname(path))
            dep.setdefault("base", os.path.dirname(path))
            return dep

        def list_installed():
            games = []
            if os.path.isdir(self.anchor_root):
                for name in sorted(os.listdir(self.anchor_root)):
                    dep = get_game(name)
                    if dep:
                        dep["apk_present"] = os.path.isfile(os.path.join(dep["base"], "lepton-app", "game.apk"))
                        dep["is_running"] = name in self.running
                        games.append(dep)
            return games

        self.running = set()
        for p in (
            patch.object(InstalledManager, "get_game", side_effect=get_game),
            patch.object(InstalledManager, "list_installed", side_effect=list_installed),
            patch.object(TuningManager, "get_global_tuning", side_effect=lambda: DEFAULTS.copy()),
            patch("frameload.installer.lepton_quest.register_game_in_steam", return_value={"success": True}),
            patch.object(porting, "FRAMEPORT_HOME", os.path.join(self.tmp, "fp-home")),
            patch.object(porting, "STAGING_DIR", os.path.join(self.tmp, "stage")),
            patch.object(porting, "OUTPUT_DIR", os.path.join(self.tmp, "out")),
            patch.object(porting, "find_cli", return_value=FAKE_CLI),
        ):
            p.start()
            self.addCleanup(p.stop)

    def install_unported(self, package="com.studio.questgame"):
        apk = write_apk(os.path.join(self.tmp, f"{package}.apk"),
                        manifest_node=manifest(package, categories=("android.intent.category.LAUNCHER", VR)),
                        libs=["libOVRPlugin.so", "libunity.so"])
        return LeptonInstaller.install_quest_game(package_name=package, title="Quest Game", apk_path=apk,
                                                  target_anchor=self.anchor_root)

    def path(self, package, *parts):
        return os.path.join(self.anchor_root, package, *parts)


class TestPorting(LibraryTestCase):
    def test_status_and_setup(self):
        before = porting.status()
        self.assertTrue(before["installed"])
        self.assertEqual(before["version"], "9.9.9")
        self.assertFalse(before["tools_ready"])
        lines = []
        after = porting.setup(lines.append)
        self.assertTrue(after["tools_ready"])  # the optional Revive tool does not count
        self.assertTrue(any("tools install" in line for line in lines))

    def test_port_installed_game_replaces_apk_and_keeps_the_original(self):
        pkg = "com.studio.questgame"
        res = self.install_unported(pkg)
        self.assertEqual(res["compat"]["level"], "needs_port")
        TuningManager.save_game_tuning(pkg, {"scale": 1.2})
        obb = self.path(pkg, "lepton-app", "obb", "main.1.obb")
        with open(obb, "wb") as f:
            f.write(b"obb")

        lines = []
        result = porting.port_installed_game(pkg, lines.append)

        self.assertTrue(result["framebridge"])
        self.assertEqual(result["compat"]["level"], "ready")
        self.assertTrue(os.path.isfile(self.path(pkg, "unported.apk")))
        self.assertEqual([n for n in os.listdir(self.path(pkg, "lepton-app")) if n.endswith(".apk")], ["game.apk"])
        self.assertTrue(os.path.isfile(obb))
        # The setting made before porting now reaches the adapter.
        self.assertIn("scale=1.20", read_text(self.path(pkg, "settings.conf")))
        self.assertTrue(any(line.startswith(f"{pkg}: OK ->") for line in lines))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "stage", pkg)))

        # Porting again starts from the kept original, not from the already ported build.
        again = porting.port_installed_game(pkg, lines.append)
        self.assertTrue(again["framebridge"])

    def test_failed_build_leaves_the_game_untouched(self):
        pkg = "com.studio.failing"
        self.install_unported(pkg)
        before = os.path.getsize(self.path(pkg, "lepton-app", "game.apk"))
        with patch.dict(os.environ, {"FAKE_FRAMEPORT_FAIL": "1"}):
            with self.assertRaises(porting.PortingError):
                porting.port_installed_game(pkg, lambda line: None)
        self.assertEqual(os.path.getsize(self.path(pkg, "lepton-app", "game.apk")), before)
        self.assertFalse(os.path.exists(self.path(pkg, "unported.apk")))

    def test_build_without_adapter_is_rejected(self):
        pkg = "com.studio.noadapter"
        self.install_unported(pkg)
        with patch.dict(os.environ, {"FAKE_FRAMEPORT_NO_ADAPTER": "1"}):
            with self.assertRaises(porting.PortingError):
                porting.port_installed_game(pkg, lambda line: None)

    def test_refuses_games_that_are_not_installed_quest_games(self):
        with self.assertRaises(porting.PortingError):
            porting.port_installed_game("com.not.installed", lambda line: None)

    def test_jobs_run_in_background_and_one_at_a_time(self):
        pkg = "com.studio.job"
        self.install_unported(pkg)
        porting.PortingJobs._jobs.clear()
        job = porting.PortingJobs.start("port", lambda log: porting.port_installed_game(pkg, log), package=pkg)
        with self.assertRaises(porting.PortingError):
            porting.PortingJobs.start("setup", porting.setup)
        for _ in range(200):
            current = porting.PortingJobs.get(job["id"])
            if current["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(current["status"], "done", current)
        self.assertEqual(current["result"]["package"], pkg)
        self.assertTrue(current["log"])
        self.assertIsNone(porting.PortingJobs.active())

        failing = porting.PortingJobs.start("port", lambda log: porting.port_installed_game("nope", log))
        for _ in range(200):
            current = porting.PortingJobs.get(failing["id"])
            if current["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(current["status"], "error")
        self.assertIn("not an installed Quest game", current["error"])


class TestInstallWithoutCompiler(unittest.TestCase):
    """SteamOS has no C compiler, and one FramePort dependency has no ready-made ARM64 package."""

    def test_second_attempt_skips_only_the_dependency_that_needs_a_compiler(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        calls = []

        def fake_run(cmd, log, timeout):
            calls.append(cmd)
            return 0, ""

        class Listing:
            stdout = "\n".join(["flet>=1.0", "UnityPy>=1.20", "PyYAML>=6.0", "typer>=0.12", 'pytest>=8; extra == "dev"'])
            stderr = ""

        lines = []
        marker = os.path.join(tmp, "limited.txt")
        with patch.object(porting, "_run", side_effect=fake_run), patch.object(porting, "LIMITED_MARKER", marker):
            with patch.object(porting.subprocess, "run", return_value=Listing()):
                code, _ = porting._install_without_optional(["pip", "install"], "python", "frameport.whl", lines.append)
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["pip", "install", "--no-deps", "frameport.whl"])
        self.assertEqual(calls[1], ["pip", "install", "flet>=1.0", "PyYAML>=6.0", "typer>=0.12"])
        self.assertIn("UnityPy", read_text(marker))
        self.assertTrue(any("without" in line for line in lines))


class TestAutomaticPorting(LibraryTestCase):
    def wait(self, job):
        for _ in range(300):
            current = porting.PortingJobs.get(job["id"])
            if current["status"] in ("done", "error"):
                return current
            time.sleep(0.05)
        self.fail("job did not finish")

    def setUp(self):
        super().setUp()
        porting.PortingJobs._jobs.clear()
        auto = patch.object(porting, "is_auto", return_value=True)
        auto.start()
        self.addCleanup(auto.stop)

    def test_ports_right_after_install_when_porting_is_set_up(self):
        porting.setup(lambda line: None)
        res = self.install_unported("com.studio.auto")
        outcome = porting.auto_port(res)
        self.assertTrue(outcome["needed"] and outcome["started"])
        self.assertEqual(self.wait(outcome["job"])["status"], "done")
        self.assertEqual(InstalledManager.get_game("com.studio.auto")["compat"]["level"], "ready")

    def test_two_installs_in_a_row_are_ported_one_after_the_other(self):
        porting.setup(lambda line: None)
        first = porting.auto_port(self.install_unported("com.studio.one"))
        second = porting.auto_port(self.install_unported("com.studio.two"))
        self.assertTrue(first["started"] and second["started"])
        self.assertEqual(self.wait(first["job"])["status"], "done")
        self.assertEqual(self.wait(second["job"])["status"], "done")
        for pkg in ("com.studio.one", "com.studio.two"):
            self.assertTrue(InstalledManager.get_game(pkg)["framebridge"])

    def test_waits_for_setup_instead_of_downloading_tools_unasked(self):
        res = self.install_unported("com.studio.waiting")
        outcome = porting.auto_port(res)
        self.assertEqual((outcome["needed"], outcome["started"], outcome["reason"]), (True, False, "not_set_up"))
        self.assertEqual([g["package"] for g in porting.pending_games()], ["com.studio.waiting"])
        self.assertIsNone(porting.PortingJobs.active())

        # Finishing the one-time setup ports what was waiting.
        result = porting.setup_and_port_pending(lambda line: None)
        self.assertEqual(result["ported"], ["com.studio.waiting"])
        self.assertEqual(porting.pending_games(), [])
        self.assertEqual(InstalledManager.get_game("com.studio.waiting")["compat"]["level"], "ready")

    def test_nothing_happens_for_games_that_do_not_need_it_or_when_switched_off(self):
        porting.setup(lambda line: None)
        apk = write_apk(os.path.join(self.tmp, "flat.apk"), manifest_node=manifest("org.example.flat"))
        flat = LeptonInstaller.install_quest_game(package_name="org.example.flat", title="Flat", apk_path=apk,
                                                  target_anchor=self.anchor_root)
        self.assertEqual(porting.auto_port(flat), {"needed": False, "started": False})

        res = self.install_unported("com.studio.manual")
        with patch.object(porting, "is_auto", return_value=False):
            outcome = porting.auto_port(res)
            self.assertEqual((outcome["started"], outcome["reason"]), (False, "disabled"))
            self.assertEqual(porting.setup_and_port_pending(lambda line: None).get("ported"), None)
        self.assertEqual(InstalledManager.get_game("com.studio.manual")["compat"]["level"], "needs_port")


class TestMigration(LibraryTestCase):
    def make_legacy(self, pkg):
        self.install_unported(pkg)
        base = self.path(pkg)
        def legacy(dep):
            dep.pop("layout_version")
            dep["settings"] = {"spoof_profile": "quest3", "resolution_scale": 1.25}

        edit_json(os.path.join(base, "deployment.json"), legacy)
        nested = os.path.join(base, "lepton-app", "obb", pkg)
        os.makedirs(nested)
        write_text(os.path.join(nested, f"main.3.{pkg}.obb"), "obb")
        for rel in ("hand_tracking.json", "framebridge_hands.conf", "lepton-data/local.prop"):
            write_text(os.path.join(base, rel), "stale")
        write_text(os.path.join(base, "launch.sh"), "#!/bin/bash\nexport LEPTON_SPOOF_MODEL='Quest 3'\n")
        return base

    def test_old_install_is_brought_to_the_current_layout(self):
        pkg = "com.studio.legacy"
        base = self.make_legacy(pkg)
        report = migrate.migrate_installs()
        self.assertIn(pkg, report)
        self.assertTrue(os.path.isfile(os.path.join(base, "lepton-app", "obb", f"main.3.{pkg}.obb")))
        self.assertFalse(os.path.exists(os.path.join(base, "lepton-app", "obb", pkg)))
        for rel in ("hand_tracking.json", "framebridge_hands.conf", "lepton-data/local.prop"):
            self.assertFalse(os.path.exists(os.path.join(base, rel)), rel)
        launch = read_text(os.path.join(base, "launch.sh"))
        self.assertNotIn("LEPTON_SPOOF_MODEL", launch)
        self.assertIn("STEAM_COMPAT_INSTALL_PATH", launch)
        # Done once: a second start changes nothing.
        self.assertEqual(migrate.migrate_installs(), {})

    def test_running_games_and_other_tools_installs_are_skipped(self):
        running = "com.studio.running"
        base = self.make_legacy(running)
        self.running.add(running)

        foreign = "com.studio.frameport"
        other = self.make_legacy(foreign)
        edit_json(os.path.join(other, "deployment.json"), lambda dep: dep.update(installed_by="frameport"))

        self.assertEqual(migrate.migrate_installs(), {})
        self.assertTrue(os.path.isdir(os.path.join(base, "lepton-app", "obb", running)))
        self.assertIn("LEPTON_SPOOF_MODEL", read_text(os.path.join(other, "launch.sh")))

        self.running.clear()
        self.assertEqual(list(migrate.migrate_installs()), [running])


class TestDoctor(LibraryTestCase):
    def test_report_covers_every_assumption_and_flags_unported_games(self):
        self.install_unported("com.studio.questgame")
        report = doctor.run_checks()
        by_name = {c["name"]: c for c in report["checks"]}
        for name in ("Device", "Lepton", "podman", "Launcher tools", "Steam library", "Installed games",
                     "Quest porting (FramePort)", "Python", "Storage", "Cameras", "Hand tracking", "Dashboard address"):
            self.assertIn(name, by_name)
        self.assertEqual(by_name["Installed games"]["state"], "warn")
        self.assertIn("Quest Game", by_name["Installed games"]["detail"])
        self.assertIn("no camera hand tracking", by_name["Hand tracking"]["detail"])
        self.assertIn(report["state"], ("ok", "warn", "fail"))
        self.assertIn("on_frame", report)
        text = doctor.format_report(report)
        self.assertEqual(len(text.splitlines()), len(report["checks"]))


if __name__ == "__main__":
    unittest.main()
