"""Freeze guard: ends a game before it takes the whole headset down with it.

Two kinds of freezes are seen on the Frame. A game that leaks memory (FramePort's notes record games
growing by gigabytes until the headset swaps, then nothing responds, not even the Steam button) runs the
system out of memory. A game that hangs, often the graphics processor with it, leaves a picture that
moves with the head; one such freeze ended in a restart of the headset. Three independent switches,
for games started through FrameLoad's launcher:

1. A memory limit on the game's container (`podman update`), a little below the headset's RAM, so the
   kernel ends the game when it reaches the limit instead of stalling everything.
2. A memory watchdog that samples memory pressure (PSI) and free memory every 2 s while a game runs
   and stops the game when the headset is about to stall.
3. Stopping a game whose picture froze (on by default, after 30 s). FrameBridge writes a `pacing:` line
   about every 5 s while the game draws. FrameLoad waits while the headset is asleep, the Steam menu is
   open or the game is in the background, and while the game still keeps the graphics processor busy
   (a loading screen, a logcat mirror that ended). VR games without FrameBridge are judged by their GPU
   time alone and only stopped when the headset is known to be in use; 2D apps are never judged.
   With the switch off, a frozen picture is still reported.

Ages use time.monotonic(): a clock change or a suspended headset does not age a game.

Every game session that ends is handed to sessions.finalize(), whatever the switches say, for the
"What happened" dialog.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from ..config import HOME, STEAM_DIR
from ..system import perf
from . import sessions as records

# FrameBridge's pacing line (every 5 s while xrEndFrame runs) and its focus log (session_fixes.c), and
# the 2 s pacing line of games bridged from VrApi.
FRAME_RE = re.compile(rb"FrameBridge: (?:pacing: ([0-9.]+) fps|focus: (lost|back after|session ending))"
                      rb"|OVRPortVrApi: pacing 2s: waits=([1-9]\d*)")
HMD_STATE_RE = re.compile(rb"\[CCVTrackedHmdDriver\] in State(\w+)")
CONTAINER_PREFIX = "lepton-steamlaunch-"
PSI_FULL_LIMIT = 20.0     # % of the last 10 s in which every task waited for memory
PSI_SAMPLES = 3           # consecutive samples (2 s apart) above the limit
LOW_MEMORY_SHARE = 0.03   # available memory below 3 % of RAM ...
SWAP_FULL_SHARE = 0.85    # ... with swap (if any) this full
RESERVE_BYTES = int(2.5 * 1024 ** 3)  # left to SteamVR, Steam and the system when a game is limited
DEFAULT_SETTINGS = {"enabled": True, "memory_limit": True, "stop_frozen": True, "frozen_seconds": 30,
                    "report_crashes": True}
FROZEN_CHOICES = (15, 30, 60, 120)
SETTINGS_VERSION = 2
# v1.3.5-1.3.7 saved these two with every change (off, 90 s); version 2 gives them the new defaults once.
RESET_BEFORE_V2 = ("stop_frozen", "frozen_seconds")
MAX_LOG_READ = 1 << 20    # bytes of launch.log read per tick; a larger backlog is skipped to its end
GAP_GRACE = 10.0          # s between two ticks after which every game gets a fresh start
FOCUS_WAIT_MAX = 120      # s a game in the background is waited for (a frozen one never logs "back")
GPU_ALIVE = 0.05          # share of the GPU's time a drawing game keeps it busy, at least
GPU_IDLE = 0.01           # below this a game draws nothing
GPU_DRAW_TICKS = 3        # ticks in a row above GPU_ALIVE before a game without FrameBridge counts as drawing
SWEEP_SECONDS = 30        # how often ends the guard did not see are looked for
ASLEEP = "the headset is asleep"
STEAM_MENU = "the Steam menu is open"


def snap_frozen_seconds(value: Any) -> int:
    """One of FROZEN_CHOICES: the nearest, a tie going to the longer wait; 30 for anything unusable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 30
    if not math.isfinite(number) or number <= 0:
        return 30
    return min(FROZEN_CHOICES, key=lambda c: (abs(c - number), -c))


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
    """package, title, appid, folder, VR or not and FrameBridge or not of every installed game, without
    asking podman."""
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
                              "title": dep.get("title") or "", "appid": dep.get("appid"), "base": base,
                              "vr": bool(dep.get("is_vr", dep.get("kind", "quest") == "quest")),
                              "framebridge": bool(dep.get("framebridge"))})
    return games


MIRROR_DEAD_RE = re.compile(rb"logcat: Unexpected EOF!|Logcat read failure")


def launch_start(game: Dict[str, Any]) -> int:
    """When launch.sh last started the game (its .last_played), 0 if unknown: tells two sessions apart."""
    try:
        with open(os.path.join(game["base"], ".last_played"), "r", encoding="utf-8") as f:
            return int(float(f.read().strip() or 0))
    except (OSError, ValueError, KeyError):
        return 0


def container_pacing(appid: Any) -> Optional[bytes]:
    """FrameBridge's newest pacing line read from the game's container (None when it cannot be asked)."""
    if not appid:
        return None
    from ..system.steam_ui import container_logcat
    lines = [line for line in container_logcat(appid).splitlines() if b"pacing:" in line]
    return lines[-1] if lines else None


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


def hmd_state() -> Optional[str]:
    """The headset's state from SteamVR's vrserver.txt ("Active", "Standby", ...); None when unknown.
    The pattern is FramePort's (agent _hmd_state)."""
    for logs in (os.path.join(STEAM_DIR, "logs"), os.path.join(HOME, ".local/share/Steam/logs"),
                 os.path.join(HOME, ".steam/steam/logs")):
        path = os.path.join(logs, "vrserver.txt")
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 256 * 1024))
                states = HMD_STATE_RE.findall(f.read())
        except OSError:
            continue
        return states[-1].decode("ascii", "replace") if states else None
    return None


def dashboard_visible() -> Optional[bool]:
    """Whether the Steam menu is open in the headset (read-only); None when Steam cannot be asked."""
    from ..system import steam_ui
    return steam_ui.dashboard_visible(timeout=3)


def kernel_gpu_lines(since_wall: float) -> List[str]:
    """Kernel lines about GPU hangs and faults since a session started (at most 20)."""
    return records.gpu_hang_lines(records.kernel_lines(since_wall))[-20:]


def gpu_share(samples: Deque[Tuple[float, Optional[int]]], now: float, window: float) -> Optional[float]:
    """Share of the GPU's time a game used over the last `window` seconds; None when it cannot be told."""
    usable = [(t, ns) for t, ns in samples if ns is not None and t >= now - window - 1]
    if len(usable) < 2:
        return None
    (t0, ns0), (t1, ns1) = usable[0], usable[-1]
    if t1 - t0 < min(window, 10) / 2 or ns1 < ns0:
        return None
    return (ns1 - ns0) / ((t1 - t0) * 1e9)


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
    _last_tick = 0.0
    _swept_at = 0.0

    @staticmethod
    def run_async(target: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Session records copy logs and ask the kernel's journal: never inside the 2 s tick."""
        threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True, name="session-record").start()

    @staticmethod
    def settings() -> Dict[str, Any]:
        try:
            from ..config import Config
            saved = Config.get().get("guard", {}) or {}
        except Exception:
            saved = {}
        keys = [k for k in DEFAULT_SETTINGS if k in saved]
        if saved.get("version", 1) < SETTINGS_VERSION:
            keys = [k for k in keys if k not in RESET_BEFORE_V2]
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: saved[k] for k in keys})
        for key in DEFAULT_SETTINGS:
            merged[key] = snap_frozen_seconds(merged[key]) if key == "frozen_seconds" else bool(merged[key])
        return merged

    @staticmethod
    def save_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
        from ..config import Config
        cfg = Config.get()
        current = cfg.raw.setdefault("guard", {})
        if current.get("version", 1) < SETTINGS_VERSION:
            for key in RESET_BEFORE_V2:
                current.pop(key, None)
        for key in DEFAULT_SETTINGS:
            if key in changes:
                value = changes[key]
                current[key] = snap_frozen_seconds(value) if key == "frozen_seconds" else bool(value)
        current["version"] = SETTINGS_VERSION
        cfg.save()
        return FreezeGuard.settings()

    @classmethod
    def record(cls, package: str, title: str, kind: str, message: str, **extra: Any) -> Dict[str, Any]:
        with cls._lock:
            cls._event_id += 1
            event = {"id": cls._event_id, "time": time.time(), "package": package, "title": title,
                     "kind": kind, "message": message, **extra}
            cls.events.append(event)
        print(f"[FrameLoad] Freeze guard: {title or package}: {message}")
        return event

    @classmethod
    def _frames(cls, game: Dict[str, Any], session: Dict[str, Any], now: float) -> None:
        """Follows the game's launch.log for FrameBridge's pacing and focus lines."""
        path = os.path.join(game["base"], "launch.log")
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        pos = session.get("log_pos", 0)
        if size < pos:
            pos = 0  # a new launch truncated it
        if size <= pos:
            return
        skip_partial = size - pos > MAX_LOG_READ
        if skip_partial:
            pos = size - MAX_LOG_READ  # only the newest lines count; a backlog would make the game look stale
        try:
            with open(path, "rb") as f:
                f.seek(pos)
                data = f.read(size - pos)
        except OSError:
            return
        session["log_pos"] = pos + len(data)
        if skip_partial:
            data = data[data.find(b"\n") + 1:] if b"\n" in data else b""
        if MIRROR_DEAD_RE.search(data):
            session["mirror_dead"] = True  # its frames can only be seen in the container from now on
        for m in FRAME_RE.finditer(data):
            if m.group(1) or m.group(3):
                if m.group(1):
                    session["fps"] = float(m.group(1))
                session["last_frame"] = now
                session["frozen_reported"] = False
                session["paused"] = ""
            elif m.group(2) == b"back after":
                session["focus"] = "focused"
                session["last_frame"] = now  # the full wait starts again
            else:
                session["focus"] = "lost" if m.group(2) == b"lost" else "ended"
                session["focus_since"] = now

    @classmethod
    def _gpu(cls, game: Dict[str, Any], session: Dict[str, Any], now: float, proc: str) -> None:
        """Samples the GPU time of a VR game's processes. Process and device lists are kept for a while:
        finding them reads every process's name."""
        pids = session.get("pids") or []
        # Not found yet (Lepton still booting): look again every 10 s, not every tick.
        if now - session.get("pids_at", -1e9) >= (30 if pids else 10) or \
                (pids and not all(os.path.isdir(os.path.join(proc, str(p))) for p in pids)):
            new = perf.app_pids(game["package"], proc)
            if new != pids:
                session["gpu_samples"].clear()  # a new process starts its counter from zero
                session["fds"], session["fds_at"] = {}, -1e9
            session["pids"], session["pids_at"] = new, now
            pids = new
        fds = session.setdefault("fds", {})
        if now - session.get("fds_at", -1e9) >= (60 if any(fds.values()) else 10):
            fds = {pid: perf.render_fds(pid, proc) for pid in pids}
            session["fds"], session["fds_at"] = fds, now
        ns = perf.gpu_time_ns(fds, proc) if pids else None
        samples = session["gpu_samples"]
        if ns is not None and samples and samples[-1][1] is not None and ns >= samples[-1][1] and now > samples[-1][0]:
            session["gpu"] = (ns - samples[-1][1]) / ((now - samples[-1][0]) * 1e9)
        elif ns is None:
            session["gpu"] = None
        samples.append((now, ns))

    @classmethod
    def paused_reason(cls, session: Dict[str, Any], now: float) -> Tuple[str, Optional[str], Optional[bool]]:
        """Why a game that shows nothing new is not judged now: (reason, headset state, Steam menu open).
        Asked only when a game reaches the limit; an unknown state counts as awake."""
        state = hmd_state()
        if state and "standby" in state.lower():
            return ASLEEP, state, None
        if session.get("focus") in ("lost", "ended") and now - session.get("focus_since", now) < FOCUS_WAIT_MAX:
            return "it is in the background", state, None
        visible = dashboard_visible()
        if visible:
            return STEAM_MENU, state, visible
        return "", state, visible

    @classmethod
    def _waits(cls, session: Dict[str, Any], clock: str, now: float) -> Tuple[bool, Optional[str], Optional[bool]]:
        """At the limit: (still waiting, headset state, Steam menu open). `clock` is the session key the wait
        is counted from. The headset waking or the Steam menu closing is only seen at the next look, so
        the full wait starts again from there; a background game's 2 minutes are not extended."""
        reason, state, visible = cls.paused_reason(session, now)
        if reason or session.get("paused") in (ASLEEP, STEAM_MENU):
            session[clock], session["paused"] = now, reason
            return True, state, visible
        session["paused"] = ""
        return False, state, visible

    @classmethod
    def _stop(cls, game: Dict[str, Any], stop: Callable[[str], Any], kind: str, marker: str) -> bool:
        """Stops a game for the guard, leaving the marker the session's record is told by."""
        records.mark_stop(game["package"], "guard", kind, marker)
        try:
            result = stop(game["package"])
        except Exception as e:
            print(f"[FrameLoad] Freeze guard could not stop {game['package']}: {e}")
            result = {"success": False}
        # "It is not running." (podman did not list it) is no stop: the game may still run.
        ok = bool(result.get("success", True) and result.get("stopped", True)) if isinstance(result, dict) else True
        if not ok:
            records.clear_stop(game["package"])
        return ok

    @classmethod
    def _judge(cls, game: Dict[str, Any], session: Dict[str, Any], now: float, cfg: Dict[str, Any],
               stop: Callable[[str], Any]) -> List[Dict[str, Any]]:
        """Decides about one running VR game whose picture may have frozen."""
        pkg, title, limit = game["package"], game["title"], cfg["frozen_seconds"]
        if session.get("frozen_reported"):
            return []
        samples = session["gpu_samples"]
        if session.get("last_frame"):  # FrameBridge reports its frames
            last = session["last_frame"]
            if now - last < limit:
                return []
            waiting, state, visible = cls._waits(session, "last_frame", now)
            if waiting:
                return []
            share = gpu_share(samples, now, limit)
            if share is not None and share >= GPU_ALIVE:
                session["last_frame"] = now
                if session.get("gpu_noted"):
                    return []
                session["gpu_noted"] = True
                return [cls.record(pkg, title, "info", "FrameLoad no longer receives its frame reports, but it is "
                                                       "still drawing, so it keeps running.")]
            # Its own frame reports say it froze, unless Lepton stopped copying them and its GPU time is unknown.
            certain = not (session.get("mirror_dead") and share is None)
            silent = int(now - last)
        elif session.get("gpu_drawing"):  # judged by its GPU time alone (no FrameBridge, or no frame line seen)
            idle = session.get("gpu_active_at", now)
            if now - idle < limit:
                return []
            waiting, state, visible = cls._waits(session, "gpu_active_at", now)
            if waiting:
                return []
            share = gpu_share(samples, now, limit)
            certain = state is not None and visible is False and share is not None
            silent = int(now - idle)
        else:
            return []  # still loading: no frame yet

        session["frozen_reported"] = True
        evidence = {"frame_age": silent, "gpu_share": None if share is None else round(share, 3),
                    "hmd": state, "focus": session.get("focus", ""), "framebridge": bool(session.get("last_frame"))}
        kernel = kernel_gpu_lines(session.get("started_wall", time.time() - silent))
        hung = " The headset's graphics processor hung while it ran." if kernel else ""
        stopped = False
        if cfg["stop_frozen"] and certain:
            stopped = cls._stop(game, stop, "frozen", f"Its picture had not changed for {silent} s.{hung}")
            message = (f"was stopped: its picture had not changed for {silent} s.{hung}" if stopped else
                       f"could not be stopped after its picture had not changed for {silent} s. Press Stop.")
        elif session.get("last_frame"):
            message = f"has shown no new picture for {silent} s. If it is stuck, press Stop.{hung}"
        else:
            unsure = (" FrameLoad cannot see this game's frames and could not confirm that the headset is in use, "
                      "so it did not stop it.") if cfg["stop_frozen"] else ""
            message = f"has not drawn anything for {silent} s. If it is stuck, press Stop.{unsure}{hung}"
        return [cls.record(pkg, title, "frozen", message, stopped=stopped, evidence=evidence, kernel=kernel)]

    @classmethod
    def _session_ended(cls, pkg: str, state: Dict[str, Any], now: float) -> None:
        last = state.get("last_frame")
        guard_state = {"fps": state.get("fps"), "last_frame_age": int(now - last) if last else None,
                       "drew": bool(last or state.get("gpu_drawing")), "limit": state.get("limit", ""),
                       "gpu": state.get("gpu")}
        cls.run_async(records.finalize, pkg, guard_state)

    @classmethod
    def check(cls, now: Optional[float] = None, stop: Optional[Callable[[str], Any]] = None,
              proc: str = "/proc", wall: Optional[float] = None) -> List[Dict[str, Any]]:
        """One round of the watchdog. Returns the events it recorded. now is monotonic."""
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        cfg = cls.settings()
        recorded: List[Dict[str, Any]] = []
        if now - cls._games_at > 60 or not cls._games:
            cls._games, cls._games_at = installed_games(), now
        running = running_games(cls._games, proc)
        live = {g["package"] for g in running}
        # Ended sessions are recorded whatever the switches say: the crash dialog needs them.
        ended = set()
        for pkg in list(cls.sessions):
            if pkg not in live:
                ended.add(pkg)
                cls._session_ended(pkg, cls.sessions.pop(pkg), now)
        if now - cls._swept_at >= SWEEP_SECONDS:
            cls._swept_at = now
            cls.run_async(records.sweep, list(cls._games), set(live) | ended)
        gap = bool(cls._last_tick) and now - cls._last_tick > GAP_GRACE
        cls._last_tick = now
        if not running:
            cls._psi.clear()
            return recorded

        if stop is None:
            from .launcher import GameLauncher

            def stop(pkg: str) -> Dict[str, Any]:  # the guard's own marker is already written
                return GameLauncher.stop(pkg, by="")
        mem = perf.memory(proc)
        for game in running:
            start_id = launch_start(game)
            old = cls.sessions.get(game["package"])
            if old is not None and start_id and old.get("start_id") and old["start_id"] != start_id:
                # Ended and started again between two looks: the old session ends, the new one starts fresh
                # (its container has no memory limit yet and it has drawn nothing yet).
                cls._session_ended(game["package"], cls.sessions.pop(game["package"]), now)
            session = cls.sessions.setdefault(game["package"], {
                "started": now, "started_wall": wall, "limit": "", "limit_at": 0.0,
                "gpu_samples": deque(maxlen=80), "gpu_hot": 0, "start_id": start_id})
            if gap:  # the headset slept or the guard stalled: nobody could have drawn
                if session.get("last_frame"):
                    session["last_frame"] = now
                if session.get("gpu_active_at"):
                    session["gpu_active_at"] = now
                session["gpu_samples"].clear()
            # Lepton creates the container a few seconds into the launch: keep trying for a minute.
            if cfg["memory_limit"] and mem and session["limit"] != "applied" and 4 < now - session["started"] < 75 \
                    and now - session["limit_at"] >= 5:
                session["limit_at"] = now
                error = apply_memory_limit(f"{CONTAINER_PREFIX}{game['appid']}", mem["total"])
                session["limit"] = "applied" if not error else error
            cls._frames(game, session, now)
            if session.get("mirror_dead") and game.get("framebridge") and now - session.get("container_at", -1e9) >= 10:
                session["container_at"] = now
                last = container_pacing(game.get("appid"))
                if last is not None:
                    if session.get("container_pacing") is not None and last != session["container_pacing"]:
                        session["last_frame"] = now  # a new pacing line in the container: it still draws
                        session["frozen_reported"] = False
                    session["container_pacing"] = last
            if game.get("vr", True):
                cls._gpu(game, session, now, proc)
                share = session.get("gpu")
                if share is not None and share >= GPU_ALIVE:
                    session["gpu_hot"] += 1
                    if session["gpu_hot"] >= GPU_DRAW_TICKS:
                        session["gpu_drawing"] = True
                        if not session.get("last_frame"):
                            session["frozen_reported"] = False  # drawing again: a new freeze is reported again
                else:
                    session["gpu_hot"] = 0
                if share is not None and share >= GPU_IDLE:
                    session["gpu_active_at"] = now
                session.setdefault("gpu_active_at", now)

        if cfg["enabled"]:
            reason = memory_critical(mem, perf.memory_pressure(proc), cls._psi)
            if reason and now - cls._last_stop > 30:
                cls._last_stop = now
                cls._psi.clear()
                for game in running:
                    ok = cls._stop(game, stop, "memory", f"The headset was about to freeze: {reason}.")
                    message = (f"stopped because {reason}; it would have frozen the headset" if ok else
                               f"could not be stopped although {reason}. Press Stop.")
                    recorded.append(cls.record(game["package"], game["title"], "memory", message, stopped=ok))
                return recorded
        else:
            cls._psi.clear()

        for game in running:
            if game.get("vr", True):  # 2D apps have no frames to judge
                recorded += cls._judge(game, cls.sessions[game["package"]], now, cfg, stop)
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
    def status(cls, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.monotonic() if now is None else now
        mem = perf.memory()
        games = []
        for pkg, session in list(cls.sessions.items()):
            game = next((g for g in cls._games if g["package"] == pkg), {})
            last = session.get("last_frame")
            age = int(now - last) if last else None
            gpu = session.get("gpu")
            if session.get("paused"):
                state = "paused"
            elif last:
                state = "silent" if age is not None and age > 8 else "drawing"
            elif session.get("gpu_drawing"):
                state = "silent" if now - session.get("gpu_active_at", now) > 8 else "drawing"
            else:
                state = "loading"
            games.append({"package": pkg, "title": game.get("title") or pkg, "fps": session.get("fps"),
                          "frame_age": age, "memory_limit": session.get("limit", ""), "state": state,
                          "paused": session.get("paused", ""), "gpu": None if gpu is None else round(gpu * 100),
                          "framebridge": bool(game.get("framebridge") or last), "vr": bool(game.get("vr", True))})
        return {
            "settings": cls.settings(),
            "running": cls._thread is not None and cls._thread.is_alive(),
            "limit_bytes": memory_limit_bytes(mem["total"]) if mem else None,
            "games": games,
            "events": list(cls.events)[-10:],
            "last_event_id": cls._event_id,
        }
