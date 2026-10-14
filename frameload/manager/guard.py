"""Freeze guard: ends a game before it takes the whole headset down with it.

The freezes seen on the Frame come from memory: a game that leaks (FramePort's notes record games
growing by gigabytes until the headset swaps, then nothing responds, not even the Steam button)
runs the system out of memory, and once the kernel thrashes swap only a hard power-off helps.
Two layers, both for games started through FrameLoad's launcher:

1. A memory limit on the game's container (`podman update`), a little below the headset's RAM,
   so the kernel ends the game when it reaches the limit instead of stalling everything.
2. A watchdog that samples memory pressure (PSI) and free memory every 2 s while a game runs and
   stops the game when the headset is about to stall.

A game that stops drawing (FrameBridge writes a `pacing:` line about every 5 s) is reported. It is
only stopped automatically when the player switched that on: a headset that is taken off pauses
rendering too.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from ..system import perf

PACING_RE = re.compile(rb"FrameBridge: pacing: ([0-9.]+) fps")
CONTAINER_PREFIX = "lepton-steamlaunch-"
PSI_FULL_LIMIT = 20.0     # % of the last 10 s in which every task waited for memory
PSI_SAMPLES = 3           # consecutive samples (2 s apart) above the limit
LOW_MEMORY_SHARE = 0.03   # available memory below 3 % of RAM ...
SWAP_FULL_SHARE = 0.85    # ... with swap (if any) this full
RESERVE_BYTES = int(2.5 * 1024 ** 3)  # left to SteamVR, Steam and the system when a game is limited
DEFAULT_SETTINGS = {"enabled": True, "memory_limit": True, "stop_frozen": False, "frozen_seconds": 90}


def held_flock_inodes(proc: str = "/proc") -> set:
    """Inodes of files someone holds an flock on. Reading /proc/locks takes no lock itself, so it
    can never make a launch.sh think its game is already starting."""
    inodes = set()
    try:
        with open(os.path.join(proc, "locks"), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.replace("->", " ").split()
                if len(parts) >= 6 and parts[1] == "FLOCK":
                    try:
                        inodes.add(int(parts[5].rsplit(":", 1)[-1]))
                    except ValueError:
                        continue
    except OSError:
        pass
    return inodes


def installed_games() -> List[Dict[str, Any]]:
    """package, title, appid and folder of every installed game, without asking podman."""
    from .installed import InstalledManager
    games = []
    try:
        anchors = InstalledManager.get_all_anchor_dirs()
    except Exception:
        anchors = []
    for anchor in anchors:
        for dep_path in glob.glob(os.path.join(anchor.get("path") or "", "*", "deployment.json")):
            try:
                with open(dep_path, "r", encoding="utf-8") as f:
                    dep = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(dep, dict):
                base = str(dep.get("base") or os.path.dirname(dep_path))
                games.append({"package": dep.get("package") or os.path.basename(os.path.dirname(dep_path)),
                              "title": dep.get("title") or "", "appid": dep.get("appid"), "base": base})
    return games


def running_games(games: List[Dict[str, Any]], proc: str = "/proc") -> List[Dict[str, Any]]:
    """The games whose launch.sh holds its launch lock right now."""
    held = held_flock_inodes(proc)
    if not held:
        return []
    out = []
    for game in games:
        try:
            if os.stat(os.path.join(game["base"], ".launch.lock")).st_ino in held:
                out.append(game)
        except OSError:
            continue
    return out


def memory_limit_bytes(total: int) -> int:
    return max(4 * 1024 ** 3, total - RESERVE_BYTES)


def apply_memory_limit(container: str, total: int) -> str:
    """Limits a game container's memory; '' on success, else why it could not be done."""
    limit = memory_limit_bytes(total)
    try:
        out = subprocess.run(["podman", "update", "--memory", str(limit), "--memory-swap", str(limit + 1024 ** 3),
                              container], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    if out.returncode != 0:
        return (out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout).strip() else "podman update failed"
    return ""


def memory_critical(mem: Optional[Dict[str, int]], psi: Optional[Dict[str, float]], history: Deque[float]) -> str:
    """Why the headset is about to stall, '' when it is not. history keeps recent PSI 'full' values."""
    if psi and "full" in psi:
        history.append(psi["full"])
        if len(history) >= PSI_SAMPLES and all(v >= PSI_FULL_LIMIT for v in list(history)[-PSI_SAMPLES:]):
            return f"the headset spent {psi['full']:.0f}% of its time waiting for memory"
    if mem and mem.get("total"):
        low = mem["available"] < mem["total"] * LOW_MEMORY_SHARE
        swap_full = not mem.get("swap_total") or mem["swap_used"] > mem["swap_total"] * SWAP_FULL_SHARE
        if low and swap_full:
            return "the headset ran out of memory"
    return ""


class FreezeGuard:
    _lock = threading.Lock()
    _thread: Optional[threading.Thread] = None
    events: Deque[Dict[str, Any]] = deque(maxlen=20)
    _event_id = 0
    sessions: Dict[str, Dict[str, Any]] = {}  # package -> state of its running session
    _games: List[Dict[str, Any]] = []
    _games_at = 0.0
    _psi: Deque[float] = deque(maxlen=10)
    _last_stop = 0.0

    @staticmethod
    def settings() -> Dict[str, Any]:
        try:
            from ..config import Config
            saved = Config.get().get("guard", {}) or {}
        except Exception:
            saved = {}
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: saved[k] for k in DEFAULT_SETTINGS if k in saved})
        return merged

    @staticmethod
    def save_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
        from ..config import Config
        cfg = Config.get()
        current = cfg.raw.setdefault("guard", {})
        for key, default in DEFAULT_SETTINGS.items():
            if key in changes:
                value = changes[key]
                current[key] = max(30, min(600, int(value))) if key == "frozen_seconds" else bool(value)
        cfg.save()
        return FreezeGuard.settings()

    @classmethod
    def record(cls, package: str, title: str, kind: str, message: str) -> Dict[str, Any]:
        with cls._lock:
            cls._event_id += 1
            event = {"id": cls._event_id, "time": time.time(), "package": package, "title": title,
                     "kind": kind, "message": message}
            cls.events.append(event)
        print(f"[FrameLoad] Freeze guard: {title or package}: {message}")
        return event

    @classmethod
    def _frames(cls, game: Dict[str, Any], session: Dict[str, Any], now: float) -> None:
        """Follows the game's launch.log for FrameBridge pacing lines."""
        path = os.path.join(game["base"], "launch.log")
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size < session.get("log_pos", 0):
            session["log_pos"] = 0  # a new launch truncated it
        if size > session.get("log_pos", 0):
            try:
                with open(path, "rb") as f:
                    f.seek(session.get("log_pos", 0))
                    data = f.read(min(size - session.get("log_pos", 0), 1 << 20))
            except OSError:
                return
            session["log_pos"] = session.get("log_pos", 0) + len(data)
            matches = PACING_RE.findall(data)
            if matches:
                session["fps"] = float(matches[-1])
                session["last_frame"] = now
                session["frozen_reported"] = False

    @classmethod
    def check(cls, now: Optional[float] = None, stop: Optional[Callable[[str], Any]] = None,
              proc: str = "/proc") -> List[Dict[str, Any]]:
        """One round of the watchdog. Returns the events it recorded."""
        now = now or time.time()
        cfg = cls.settings()
        recorded: List[Dict[str, Any]] = []
        if not cfg["enabled"]:
            cls.sessions.clear()
            return recorded
        if now - cls._games_at > 60 or not cls._games:
            cls._games, cls._games_at = installed_games(), now
        running = running_games(cls._games, proc)
        live = {g["package"] for g in running}
        for pkg in list(cls.sessions):
            if pkg not in live:
                del cls.sessions[pkg]
        if not running:
            cls._psi.clear()
            return recorded

        if stop is None:
            from .launcher import GameLauncher
            stop = GameLauncher.stop
        mem = perf.memory(proc)
        for game in running:
            session = cls.sessions.setdefault(game["package"], {"started": now, "limit": "", "limit_at": 0.0})
            # Lepton creates the container a few seconds into the launch: keep trying for a minute.
            if cfg["memory_limit"] and mem and session["limit"] != "applied" and 4 < now - session["started"] < 75 \
                    and now - session["limit_at"] >= 5:
                session["limit_at"] = now
                error = apply_memory_limit(f"{CONTAINER_PREFIX}{game['appid']}", mem["total"])
                session["limit"] = "applied" if not error else error
            cls._frames(game, session, now)

        reason = memory_critical(mem, perf.memory_pressure(proc), cls._psi)
        if reason and now - cls._last_stop > 30:
            cls._last_stop = now
            cls._psi.clear()
            for game in running:
                stop(game["package"])
                recorded.append(cls.record(game["package"], game["title"], "memory",
                                           f"stopped because {reason}; it would have frozen the headset"))
            return recorded

        for game in running:
            session = cls.sessions[game["package"]]
            last = session.get("last_frame")
            if not last or session.get("frozen_reported"):
                continue  # never drew yet (still loading), or already reported
            if now - last >= cfg["frozen_seconds"]:
                session["frozen_reported"] = True
                if cfg["stop_frozen"]:
                    stop(game["package"])
                    recorded.append(cls.record(game["package"], game["title"], "frozen",
                                               f"stopped: it had not drawn a frame for {int(now - last)} s"))
                else:
                    recorded.append(cls.record(game["package"], game["title"], "frozen",
                                               f"has not drawn a frame for {int(now - last)} s. If it is stuck, press Stop."))
        return recorded

    @classmethod
    def start(cls, interval: float = 2.0) -> None:
        if cls._thread and cls._thread.is_alive():
            return

        def loop() -> None:
            while True:
                try:
                    cls.check()
                except Exception as e:  # the guard must never take the server down
                    print(f"[FrameLoad] Freeze guard error: {e}")
                time.sleep(interval)

        cls._thread = threading.Thread(target=loop, name="freeze-guard", daemon=True)
        cls._thread.start()

    @classmethod
    def status(cls) -> Dict[str, Any]:
        mem = perf.memory()
        games = []
        for pkg, session in cls.sessions.items():
            title = next((g["title"] for g in cls._games if g["package"] == pkg), pkg)
            last = session.get("last_frame")
            games.append({"package": pkg, "title": title, "fps": session.get("fps"),
                          "frame_age": int(time.time() - last) if last else None,
                          "memory_limit": session.get("limit", "")})
        return {
            "settings": cls.settings(),
            "running": cls._thread is not None and cls._thread.is_alive(),
            "limit_bytes": memory_limit_bytes(mem["total"]) if mem else None,
            "games": games,
            "events": list(cls.events)[-10:],
            "last_event_id": cls._event_id,
        }
