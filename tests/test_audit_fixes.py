"""Regression tests for bugs found in the v1.3.2 audit."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from axml_builder import manifest, write_apk  # noqa: E402

from frameload.installer.lepton_quest import LAUNCH_SCRIPT_TEMPLATE, LeptonInstaller  # noqa: E402
from frameload.manager.installed import InstalledManager  # noqa: E402
from frameload.manager.mods import ModManager  # noqa: E402
from frameload.manager.storage import StorageManager  # noqa: E402
from frameload.manager.tuning import DEFAULTS, TuningManager  # noqa: E402


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class AuditTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.internal = os.path.join(self.tmp, "internal", "quest-frame")
        self.card = os.path.join(self.tmp, "card", "quest-frame")

        def get_game(package_name):
            for root in (self.internal, self.card):
                path = os.path.join(root, package_name, "deployment.json")
                if os.path.isfile(path):
                    dep = json.loads(read_text(path))
                    dep.setdefault("anchor", os.path.dirname(path))
                    dep.setdefault("base", os.path.dirname(path))
                    return dep
            return None

        for p in (
            patch.object(InstalledManager, "get_game", side_effect=get_game),
            patch.object(TuningManager, "get_global_tuning", side_effect=lambda: DEFAULTS.copy()),
            patch("frameload.installer.lepton_quest.register_game_in_steam", return_value={"success": True}),
            patch("frameload.system.shortcuts.register_game_in_steam", return_value={"success": True}),
            patch.object(StorageManager, "resolve_anchor", side_effect=lambda dev=None: self.card if dev == "sd" else self.internal),
            patch.object(StorageManager, "get_devices", return_value=[]),
        ):
            p.start()
            self.addCleanup(p.stop)

    def install(self, package, **kwargs):
        apk = write_apk(os.path.join(self.tmp, f"{package}.apk"),
                        manifest_node=manifest(package, categories=("android.intent.category.LAUNCHER",
                                                                    "com.oculus.intent.category.VR")),
                        libs=["libopenxr_loader.so", "libframe_settings.so"])
        return LeptonInstaller.install_quest_game(package_name=package, title="Game", apk_path=apk,
                                                  target_anchor=self.internal, **kwargs)


class TestMods(AuditTestCase):
    def test_mod_paths_cannot_leave_the_games_data_folder(self):
        pkg = "com.studio.mods"
        self.install(pkg)
        victim = os.path.join(self.tmp, "victim")
        os.makedirs(victim)
        source = os.path.join(self.tmp, "song.txt")
        with open(source, "w", encoding="utf-8") as f:
            f.write("x")

        # A traversal in the id is reduced to its last component, so nothing outside is touched.
        self.assertFalse(ModManager.delete_mod(pkg, "mod:../../../../../../victim"))
        self.assertTrue(os.path.isdir(victim))
        for bad in ("mod:..", "song:", "mod:."):
            with self.assertRaises(ValueError):
                ModManager.delete_mod(pkg, bad)

        with self.assertRaises(ValueError):
            ModManager.inject_mod(pkg, source, target_subpath="../../../../outside")
        res = ModManager.inject_mod(pkg, source, mod_name="../../escape")
        self.assertTrue(os.path.abspath(res["destination"]).startswith(os.path.abspath(ModManager.get_game_data_dir(pkg))))
        self.assertTrue(ModManager.delete_mod(pkg, "mod:escape"))


class TestMove(AuditTestCase):
    def test_moving_a_lepton_game_keeps_its_settings(self):
        pkg = "com.studio.moved"
        self.install(pkg)
        TuningManager.save_game_tuning(pkg, {"foveation": "fixed", "scale": 1.3})
        res = StorageManager.move_game(pkg, "sd")
        self.assertTrue(res["moved"])
        launch = read_text(os.path.join(self.card, pkg, "launch.sh"))
        self.assertIn(shlex.quote(os.path.join(self.card, pkg)), launch)
        self.assertIn("FDM_DEBUG=disable_offsets", launch)
        self.assertIn("scale=1.30", read_text(os.path.join(self.card, pkg, "settings.conf")))

    def test_moving_a_linux_app_keeps_its_own_launcher(self):
        pkg = "linux.tool"
        old = os.path.join(self.internal, pkg)
        os.makedirs(old)
        with open(os.path.join(old, "deployment.json"), "w", encoding="utf-8") as f:
            json.dump({"package": pkg, "title": "Tool", "kind": "linux_native", "anchor": old, "appid": 5,
                       "device_id": "internal", "is_vr": False}, f)
        with open(os.path.join(old, "launch.sh"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"#!/usr/bin/env bash\napp_dir={shlex.quote(old)}\nexec \"$app_dir/bin/tool\"\n")

        StorageManager.move_game(pkg, "sd")
        launch = read_text(os.path.join(self.card, pkg, "launch.sh"))
        self.assertIn('exec "$app_dir/bin/tool"', launch)
        self.assertIn(f"app_dir={shlex.quote(os.path.join(self.card, pkg))}", launch)
        self.assertNotIn("lepton", launch.lower())


class TestLauncherAndScripts(unittest.TestCase):
    def test_games_started_by_frameload_survive_a_server_restart(self):
        self.assertIn('[[ -n "${{FRAMELOAD_DETACHED:-}}" ]] && parent=1', LAUNCH_SCRIPT_TEMPLATE)
        self.assertIn('FRAMELOAD_DETACHED="1"', read_text(os.path.join(REPO, "frameload", "manager", "launcher.py")))

    def test_every_cli_command_passes_through_run_sh(self):
        run_sh = read_text(os.path.join(REPO, "run.sh"))
        cli = read_text(os.path.join(REPO, "frameload", "cli.py"))
        import re
        passthrough = re.search(r"^\s+(serve\|[a-z|\-]+)\)$", run_sh, re.M).group(1).split("|")
        commands = re.findall(r'add_parser\("([a-z\-]+)"', cli)
        self.assertEqual(sorted(set(commands) - set(passthrough)), [])
        self.assertNotIn("\r", run_sh)

    def test_installer_provides_the_frameload_command(self):
        install_sh = read_text(os.path.join(REPO, "install.sh"))
        self.assertIn('"$HOME/.local/bin/frameload"', install_sh)
        self.assertIn('exec "$SCRIPT_DIR/run.sh" "\\$@"', install_sh)


if __name__ == "__main__":
    unittest.main()
