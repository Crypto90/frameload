"""The compatibility list at frameload.crypto90.de (website/ in this repository).

Two separate switches under System:
* show: the library shows each game's community status. FrameLoad fetches the whole public list (it never
  says which games are installed) at most every few hours and keeps a copy.
* share: after each finished session the headset sends one anonymous report: the game, how long it ran,
  whether it showed its picture, how it ended and the settings it used, with a random id made once on this
  headset. No name, account or log. Off until the player turns it on.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from .. import __version__
from ..config import DATA_DIR, Config

SERVER = "https://frameload.crypto90.de"
CACHE_FILE = os.path.join(DATA_DIR, "compat_list.json")
REFRESH_SECONDS = 6 * 3600
RETRY_SECONDS = 15 * 60
TIMEOUT = 8
NORMAL_ENDS = ("quit", "stopped_player", "stopped_frameload", "closed_by_steam")
FAILED_STARTS = ("start_failed", "closed_early")
MIN_PLAY_SECONDS = 120

_lock = threading.Lock()
_state: Dict[str, Any] = {"list": None, "fetched": 0.0, "tried": 0.0, "fetching": False, "last_report": None}


def _urlopen(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)  # tests replace this


def settings() -> Dict[str, Any]:
    cfg = Config.get().raw.get("compat", {})
    return {"show": bool(cfg.get("show", True)), "share": bool(cfg.get("share", False)),
            "server": SERVER, "last_report": _state["last_report"],
            "list_updated": int(_state["fetched"]) or None}


def save_settings(body: Dict[str, Any]) -> Dict[str, Any]:
    cfg = Config.get()
    compat = dict(cfg.raw.get("compat", {}))
    for key in ("show", "share"):
        if key in body:
            compat[key] = bool(body[key])
    cfg["compat"] = compat
    return settings()


def _install_id() -> str:
    """A random id made once on this headset, so each headset's latest session counts once."""
    cfg = Config.get()
    compat = dict(cfg.raw.get("compat", {}))
    if not compat.get("install_id"):
        compat["install_id"] = str(uuid.uuid4())
        cfg["compat"] = compat
    return compat["install_id"]


def rating(record: Dict[str, Any]) -> str:
    """working, partial or broken: the same rule as the website (website/app/status.php)."""
    outcome = record.get("outcome", "")
    duration = int(record.get("duration") or 0)
    drew = bool((record.get("frames") or {}).get("drew"))
    fixed = bool(record.get("auto_fix"))
    if outcome in FAILED_STARTS or not drew:
        return "partial" if duration >= 300 and outcome not in FAILED_STARTS else "broken"
    if outcome in NORMAL_ENDS:
        return "working" if duration >= MIN_PLAY_SECONDS and not fixed else "partial"
    return "partial" if duration >= 60 or fixed else "broken"


def _os_build() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("BUILD_ID="):
                    return line.split("=", 1)[1].strip().strip('"')[:40]
    except OSError:
        pass
    return ""


def payload(record: Dict[str, Any], dep: Dict[str, Any]) -> Dict[str, Any]:
    from .tuning import TuningManager

    try:
        effective = TuningManager.effective_settings(dep)
    except Exception:
        effective = {}
    frames = record.get("frames") or {}
    return {
        "install_id": _install_id(),
        "package": record.get("package") or dep.get("package"),
        "title": dep.get("title") or record.get("title") or "",
        "version_code": str(dep.get("version_code") or ""),
        "version_name": str(dep.get("version_name") or "")[:40],
        "engine": dep.get("engine") or "",
        "outcome": record.get("outcome", ""),
        "session_end": int(record.get("end") or 0),
        "duration": int(record.get("duration") or 0),
        "drew": bool(frames.get("drew")),
        "fps": frames.get("fps"),
        "auto_fix": record.get("auto_fix") or "",
        "settings": {k: effective[k] for k in ("scale", "refresh_rate", "foveation") if k in effective},
        "framebridge": bool(dep.get("framebridge")),
        "frameload_version": __version__,
        "os_build": _os_build(),
        "lepton": (record.get("lepton") or "")[:60],
    }


def send(record: Dict[str, Any], dep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Sends one session report now; None when sharing is off or it could not be sent."""
    if not settings()["share"] or record.get("kind") not in (None, "vr", "2d"):
        return None
    body = json.dumps(payload(record, dep)).encode("utf-8")
    request = urllib.request.Request(f"{SERVER}/api/v1/report.php", data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"FrameLoad/{__version__}"})
    try:
        with _urlopen(request, TIMEOUT) as response:
            answer = json.loads(response.read(65536).decode("utf-8"))
    except Exception as e:
        _state["last_report"] = {"time": int(time.time()), "package": record.get("package"), "error": str(e)[:200]}
        return None
    _state["last_report"] = {"time": int(time.time()), "package": record.get("package"),
                             "rating": answer.get("rating"), "status": answer.get("status")}
    _state["tried"] = 0.0  # the list may have changed: fetch it again on the next look
    _state["fetched"] = 0.0
    return answer


def report(record: Dict[str, Any], dep: Dict[str, Any]) -> None:
    """After a session: sends its report in the background when the player shares them."""
    if settings()["share"]:
        threading.Thread(target=send, args=(record, dep), daemon=True, name="compat-report").start()


def _load_cache() -> None:
    if _state["list"] is not None:
        return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        _state["list"] = cached.get("games") or {}
        _state["fetched"] = float(cached.get("fetched") or 0)
    except (OSError, ValueError):
        _state["list"] = {}


def _fetch() -> None:
    try:
        request = urllib.request.Request(f"{SERVER}/api/v1/compat.php",
                                         headers={"User-Agent": f"FrameLoad/{__version__}"})
        with _urlopen(request, TIMEOUT) as response:
            games = json.loads(response.read(4 * 1024 * 1024).decode("utf-8")).get("games") or {}
        if not isinstance(games, dict):
            raise ValueError("unexpected answer")
        now = time.time()
        with _lock:
            _state["list"], _state["fetched"] = games, now
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched": now, "games": games}, f)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        print(f"[FrameLoad] Could not fetch the compatibility list: {e}")
    finally:
        _state["fetching"] = False


def community() -> Dict[str, Any]:
    """The cached list; a stale one is refreshed in the background, never while a page waits."""
    if not settings()["show"]:
        return {}
    with _lock:
        _load_cache()
        now = time.time()
        stale = now - _state["fetched"] > REFRESH_SECONDS and now - _state["tried"] > RETRY_SECONDS
        if stale and not _state["fetching"]:
            _state["fetching"], _state["tried"] = True, now
            threading.Thread(target=_fetch, daemon=True, name="compat-list").start()
        return _state["list"] or {}


def annotate(games: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Adds `community` (status, label, note, best settings, link) to the games the list knows."""
    listed = community()
    for game in games:
        entry = listed.get(game.get("package"))
        if isinstance(entry, dict) and entry.get("status"):
            game["community"] = {k: entry.get(k) for k in
                                 ("status", "label", "note", "settings_text", "reports", "url")}
    return games
