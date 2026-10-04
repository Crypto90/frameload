"""Uninstallation coordinator for FrameLoad."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict

from ..config import ANCHOR_DIR
from ..system.shortcuts import unregister_game_from_steam
from .installed import InstalledManager


class Uninstaller:
    @staticmethod
    def uninstall(package_name: str, keep_saves: bool = False) -> Dict[str, Any]:
        """Completely uninstalls a game, container, and Steam shortcuts."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            # Check if directory exists even without deployment.json
            target = os.path.join(ANCHOR_DIR, package_name)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
                return {"success": True, "package": package_name, "message": "Cleaned up orphaned directory"}
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        appid = dep.get("appid")
        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, package_name))
        launch_script = os.path.join(anchor, "launch.sh")

        # 1. Stop container if running
        if appid:
            try:
                subprocess.run(["podman", "kill", f"lepton-steamlaunch-{appid}"], capture_output=True)
            except OSError:
                pass

        # 2. Optionally backup saves if requested
        if keep_saves:
            from .backup import SaveBackupManager
            try:
                SaveBackupManager.backup_saves(package_name)
            except Exception as e:
                print(f"[FrameLoad] Could not auto-backup saves before uninstall: {e}")

        # 3. Remove game directory
        if os.path.isdir(anchor):
            shutil.rmtree(anchor, ignore_errors=True)

        # 4. Unregister from Steam
        steam_removed = unregister_game_from_steam(launch_script, appid)

        return {
            "success": True,
            "package": package_name,
            "title": dep.get("title", package_name),
            "steam_shortcut_removed": steam_removed
        }
