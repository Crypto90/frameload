"""What the running Steam client knows about FrameLoad's shortcuts.

Steam reads shortcuts.vdf once, when it starts, and writes its own copy back when it exits. A game
installed while Steam is running is therefore not in the library yet, `steam://rungameid` cannot
start it, and the entry can be overwritten on Steam's way out. FrameLoad tracks which shortcuts were
written after Steam started, launches those games itself, and can restart Steam the safe way:
stop it, write every shortcut again, start it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from ..config import FRAMELOAD_DIR

STATE_FILE = os.path.join(FRAMELOAD_DIR, "steam_shortcuts.json")
STEAM_UNIT = "steam.service"
_lock = threading.Lock()


def steam_pid() -> Optional[int]:
    try:
        out = subprocess.run(["pgrep", "-o", "-x", "steam"], capture_output=True, text=True, timeout=3)
        return int(out.stdout.split()[0]) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def process_start_time(pid: int) -> Optional[float]:
    """Wall-clock start time of a process, from /proc."""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as f:
            stat = f.read()
        ticks = int(stat[stat.rindex(")") + 2:].split()[19])  # field 22: starttime
        with open("/proc/stat", "r", encoding="utf-8") as f:
            boot = next(int(line.split()[1]) for line in f if line.startswith("btime"))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, StopIteration, AttributeError, IndexError):
        return None


def steam_started_at() -> Optional[float]:
    pid = steam_pid()
    return process_start_time(pid) if pid else None


def _load() -> Dict[str, Dict[str, Any]]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(STATE_FILE + ".tmp", STATE_FILE)
    except OSError:
        pass


def note_written(launch_script: str, title: str) -> None:
    """Records that a shortcut was (re)written now."""
    with _lock:
        data = _load()
        data[launch_script] = {"title": title, "time": time.time()}
        _save(data)


def forget(launch_script: str) -> None:
    with _lock:
        data = _load()
        if data.pop(launch_script, None) is not None:
            _save(data)


def pending(started: Optional[float] = None) -> List[Dict[str, Any]]:
    """Shortcuts written after the running Steam started: not in its library yet."""
    started = steam_started_at() if started is None else started
    if started is None:
        return []  # Steam is not running: it reads the file fresh on its next start
    with _lock:
        data = _load()
    return [{"launch_script": path, "title": entry.get("title", "")}
            for path, entry in data.items()
            if entry.get("time", 0) > started and os.path.isfile(path)]


def is_pending(launch_script: str) -> bool:
    return any(p["launch_script"] == launch_script for p in pending())


def resync_shortcuts() -> int:
    """Writes the shortcut of every installed game again. Run while Steam is stopped."""
    from ..manager.installed import InstalledManager
    from .shortcuts import register_game_in_steam

    count = 0
    for game in InstalledManager.list_installed():
        anchor = game.get("anchor", "")
        launch_script = os.path.join(anchor, "launch.sh")
        if not os.path.isfile(launch_script):
            continue
        art_dir = os.path.join(anchor, "artwork")
        icon = os.path.join(art_dir, "icon.png")
        result = register_game_in_steam(
            title=game.get("title", game["package"]), launch_script_path=launch_script, anchor_dir=anchor,
            icon_path=icon if os.path.isfile(icon) else "", artwork_dir=art_dir, is_vr=bool(game.get("is_vr", True)))
        count += 1 if result.get("success") else 0
    return count


def can_restart() -> bool:
    """True when Steam runs as the user service FrameLoad knows how to restart (the Frame's session)."""
    try:
        return subprocess.run(["systemctl", "--user", "cat", STEAM_UNIT], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restart_steam() -> Dict[str, Any]:
    """Stops Steam, rewrites every shortcut, starts Steam again, in a unit of its own.

    Anything Steam started (this dashboard's window, a running game) ends with it."""
    if not can_restart():
        return {"success": False, "error": "Steam does not run as a user service here. Restart Steam yourself to see new games."}
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    python = sys.executable or "/usr/bin/python3"
    script = (f"systemctl --user stop {STEAM_UNIT}; sleep 3; "
              f"'{python}' -m frameload.cli sync-shortcuts; "
              f"systemctl --user start {STEAM_UNIT}")
    cmd = ["systemd-run", "--user", "--collect", "--unit", f"frameload-steam-restart-{int(time.time())}",
           f"--working-directory={repo}", f"--setenv=PYTHONPATH={repo}", "bash", "-c", script]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return {"success": False, "error": str(e)}
    if proc.returncode:
        return {"success": False, "error": (proc.stderr or proc.stdout).strip()[-300:]}
    return {"success": True, "message": "Steam is restarting. New games will be in your library when it is back."}


def status() -> Dict[str, Any]:
    started = steam_started_at()
    waiting = pending(started)
    return {
        "running": started is not None,
        "started_at": started,
        "pending": [p["title"] for p in waiting],
        "restart_needed": bool(waiting),
        "can_restart": bool(waiting) and can_restart(),
    }
