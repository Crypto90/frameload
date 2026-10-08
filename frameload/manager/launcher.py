"""Game launch and termination coordinator for Steam Frame."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict

from ..config import ANCHOR_DIR
from ..system.steam_vdf import steam_gameid
from .installed import InstalledManager


class GameLauncher:
    @staticmethod
    def launch(package_name: str) -> Dict[str, Any]:
        """Launches a game via Steam rungameid or direct launch script."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        appid = dep.get("appid")
        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, package_name))
        launch_script = os.path.join(anchor, "launch.sh")

        if not os.path.isfile(launch_script):
            raise FileNotFoundError(f"Launch script not found: {launch_script}")

        # Try Steam launch first if Steam is running
        launched_via_steam = False
        gid = steam_gameid(appid) if appid else 0

        from ..system import steam_session
        from ..system.steamos import is_steam_running
        steam_running = is_steam_running()
        # Steam only knows shortcuts that existed when it started; a newer game is started directly.
        in_library = not steam_session.is_pending(launch_script)
        if steam_running and gid and in_library:
            try:
                subprocess.Popen(
                    ["steam", "-ifrunning", f"steam://rungameid/{gid}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                launched_via_steam = True
            except OSError:
                pass

        if not launched_via_steam:
            # Direct execution fallback
            subprocess.Popen(
                ["bash", launch_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=anchor,
                env=dict(os.environ, FRAMELOAD_DETACHED="1"),
                start_new_session=True
            )

        return {
            "success": True,
            "package": package_name,
            "title": dep.get("title", package_name),
            "launched_via_steam": launched_via_steam,
            "in_steam_library": in_library,
            "gameid": gid,
        }

    @staticmethod
    def stop(package_name: str) -> Dict[str, Any]:
        """Stops the running game and its container."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            return {"success": False, "error": "Game not found"}

        appid = dep.get("appid")
        if appid:
            try:
                subprocess.run(["podman", "kill", f"lepton-steamlaunch-{appid}"], capture_output=True)
            except OSError:
                pass

        return {"success": True, "package": package_name}
