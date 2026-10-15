"""Game launch and termination coordinator for Steam Frame."""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Dict, List

from ..config import ANCHOR_DIR
from ..system.steam_vdf import steam_gameid
from .installed import InstalledManager


CONTAINER_PREFIX = "lepton-steamlaunch-"
LAST_LAUNCH = ".last_launch"
SHOW_LOG = "show.log"          # <base>/show.log: every press of Show, for the game's report
SHOW_LOG_MAX = 32 * 1024


class GameLauncher:
    @staticmethod
    def play(package_name: str, requested: bool = True) -> Dict[str, Any]:
        """What Play in the dashboard and a frameload://launch link do: refuse an app that cannot run
        on the Frame, port a game built for Meta's runtime first, and start everything else.

        requested: a player pressed Play (Port & Play) in FrameLoad, which ports the game whatever the
        automatic switches say. A link from elsewhere passes False and follows the switches."""
        from ..installer import porting

        dep = InstalledManager.get_game(package_name)
        compat = (dep or {}).get("compat") or {}
        if compat.get("level") == "blocked":
            reasons = [i["message"] for i in compat.get("issues", []) if i.get("severity") == "error"]
            return {"success": False, "launched": False, "package": package_name,
                    "error": reasons[0] if reasons else "This app cannot run on the Steam Frame."}
        if dep and porting.needs_port(dep):
            outcome = porting.auto_port(dep, requested=requested)
            if outcome.get("started") or outcome.get("reason") in ("failed", "disabled", "not_set_up"):
                return {"success": True, "launched": False, "package": package_name,
                        "title": dep.get("title", package_name), "porting": outcome}
        return GameLauncher.launch(package_name)

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
        GameLauncher._note_launch(dep.get("base") or anchor, launched_via_steam, not in_library)

        return {
            "success": True,
            "package": package_name,
            "title": dep.get("title", package_name),
            "launched_via_steam": launched_via_steam,
            "in_steam_library": in_library,
            "gameid": gid,
        }

    @staticmethod
    def _note_launch(base: str, via_steam: bool, pending: bool) -> None:
        """How FrameLoad started the game last (<base>/.last_launch), for its Launch Log: a game
        started directly is one Steam does not know, so Steam shows no Resume or Exit for it."""
        record = {"time": int(time.time()), "via": "steam" if via_steam else "direct", "pending": pending}
        try:
            with open(os.path.join(base, LAST_LAUNCH), "w", encoding="utf-8") as f:
                json.dump(record, f)
        except OSError:
            pass

    @staticmethod
    def show(package_name: str) -> Dict[str, Any]:
        """Show <game>: closes SteamVR's dashboard, where FrameLoad's window lives, so the running VR
        game is in front. For when the game plays its sound behind FrameLoad."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            return {"success": False, "package": package_name, "error": "Game not found"}
        title = dep.get("title", package_name)
        base = {"package": package_name, "title": title}
        if not dep.get("is_vr", True):
            return {**base, "success": False, "error": f"{title} is a 2D app: it has a window of its own."}
        appid = dep.get("appid")
        if not appid or f"{CONTAINER_PREFIX}{appid}" not in GameLauncher.running_containers():
            return {**base, "success": False, "running": False, "error": f"{title} is not running."}
        from ..system import steam_ui
        res = steam_ui.show_game()
        from . import sessions
        GameLauncher._note_show(dep.get("base") or dep.get("anchor") or "", res, sessions.current_start(dep))
        # When Steam's menu cannot be closed (or closing it did not help), closing FrameLoad's own
        # window is what is left: the dashboard offers it when run.sh owns an open window.
        return {**base, "running": True, **res, "window_open": steam_ui.window_pid() is not None}

    @staticmethod
    def _note_show(base: str, res: Dict[str, Any], started: Any = None) -> None:
        """Appends one press of Show to <base>/show.log (kept short), with how the game was started."""
        if not base:
            return
        via = "steam library"  # a start from Steam's library writes no .last_launch
        try:
            with open(os.path.join(base, LAST_LAUNCH), "r", encoding="utf-8") as f:
                launch = json.load(f) or {}
            if not started or 0 <= float(started) - float(launch.get("time") or 0) <= 120:  # this start's
                via = launch.get("via", "?")
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        outcome = "ok" if res.get("success") else res.get("reason", "failed")
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} Show: {outcome}; started via {via}; "
                f"{'; '.join(res.get('steps') or [])}\n")
        path = os.path.join(base, SHOW_LOG)
        try:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    old = f.read()[-SHOW_LOG_MAX:]
            except OSError:
                old = ""
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(old[old.find("\n") + 1:] if len(old) >= SHOW_LOG_MAX else old)
                f.write(line)
        except OSError:
            pass

    @staticmethod
    def close_window() -> Dict[str, Any]:
        """Closes FrameLoad's window (run.sh) so a game it covers is in front; games keep running."""
        from ..system import steam_ui
        if steam_ui.close_frameload_window():
            return {"success": True}
        return {"success": False, "error": "FrameLoad's window is not one FrameLoad can close (it was not opened from Steam)."}

    @staticmethod
    def running_containers() -> List[str]:
        """Names of the Lepton game containers that are running right now."""
        try:
            out = subprocess.run(["podman", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return []
        return [name for name in out.stdout.split() if name.startswith(CONTAINER_PREFIX)]

    @staticmethod
    def _stop_container(name: str) -> bool:
        """Ends one game container. A game FrameLoad started itself has no "exit" in Steam, and a
        hung one ignores a polite request, so this kills it and removes it if it lingers."""
        try:
            subprocess.run(["podman", "kill", name], capture_output=True, timeout=20)
            for _ in range(10):
                if name not in GameLauncher.running_containers():
                    return True
                time.sleep(0.5)
            subprocess.run(["podman", "rm", "-f", name], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        return name not in GameLauncher.running_containers()

    @staticmethod
    def stop(package_name: str, by: str = "player") -> Dict[str, Any]:
        """Stops the running game and its container. `by` is noted first, so the session's record says
        who stopped it rather than calling it a crash (see sessions.mark_stop)."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            return {"success": False, "error": "Game not found"}
        appid = dep.get("appid")
        name = f"{CONTAINER_PREFIX}{appid}"
        if not appid or name not in GameLauncher.running_containers():
            return {"success": True, "package": package_name, "stopped": False, "message": "It is not running."}
        if by:
            from . import sessions
            sessions.mark_stop(package_name, by)
        stopped = GameLauncher._stop_container(name)
        if not stopped and by:
            from . import sessions
            sessions.clear_stop(package_name)
        return {"success": stopped, "package": package_name, "stopped": stopped,
                "error": "" if stopped else "The game's container could not be stopped."}

    @staticmethod
    def stop_all(by: str = "player") -> Dict[str, Any]:
        """Stops every running Lepton game, whoever started it."""
        names = GameLauncher.running_containers()
        if by and names:
            from . import sessions
            from .guard import installed_games
            for game in installed_games():
                if f"{CONTAINER_PREFIX}{game.get('appid')}" in names:
                    sessions.mark_stop(game["package"], by)
        stopped = [name for name in names if GameLauncher._stop_container(name)]
        return {"success": len(stopped) == len(names), "stopped": len(stopped), "running": len(names)}
