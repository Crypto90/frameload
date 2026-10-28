"""Automatic quality: each game's resolution scale and refresh rate follow what it managed last time.

After a session (sessions._store) FrameLoad looks at FrameBridge's pacing lines (frames per second, every 5 s)
against the rate the game ran at, and at the game's own share of the graphics processor (guard.py, DRM fdinfo):

* steady at its rate with the GPU busy less than HEADROOM of the time: one step sharper (+0.1, up to MAX_SCALE);
* more than SLOW_SHARE of the windows under 90 % of its rate (FramePort's "slow-frames" rule): one step back,
  first the extra resolution FrameLoad gave it, then the refresh rate to 72 Hz, then below 1.0x (MIN_SCALE);
* a GPU hang, crash or frozen picture after FrameLoad raised the scale: back to 1.0x.

Only for VR games FrameLoad ported (FrameBridge reads the scale) and only for settings the player has not set
for the game. The result lives on the game (deployment.json `auto_quality`) and sits under its own settings in
TuningManager.inherited_settings / display_rate. System > Automatic quality switches it off.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..config import Config
from ..system.steamvr_settings import PANEL_RATES

PACING_RE = re.compile(r"FrameBridge: pacing: ([0-9.]+) fps")
STEP = 0.1
MAX_SCALE = 1.3
MIN_SCALE = 0.8
HEADROOM = 0.55
SLOW_SHARE = 0.3
SLOW_FACTOR = 0.9
MIN_WINDOWS = 18  # 18 pacing windows of 5 s after the first two: 1.5 minutes of play
CAPPED_RATE = 72
NORMAL_ENDS = ("quit", "stopped_player", "stopped_frameload", "closed_by_steam")
BAD_ENDS = ("gpu_hang", "crashed", "guard_frozen")


def enabled() -> bool:
    return bool(Config.get().raw.get("auto_quality", {}).get("enabled", True))


def set_enabled(on: bool) -> Dict[str, Any]:
    cfg = Config.get()
    cfg["auto_quality"] = {**cfg.raw.get("auto_quality", {}), "enabled": bool(on)}
    return {"enabled": enabled()}


def applied(dep: Dict[str, Any]) -> Dict[str, Any]:
    """The settings automatic quality gives this game now ({} when switched off or nothing learnt)."""
    auto = dep.get("auto_quality") or {}
    if not enabled() or not isinstance(auto, dict):
        return {}
    return {"scale": float(auto["scale"])} if auto.get("scale") and float(auto["scale"]) != 1.0 else {}


def rate_cap(dep: Dict[str, Any]) -> int:
    auto = dep.get("auto_quality") or {}
    return int(auto.get("rate_cap") or 0) if enabled() and isinstance(auto, dict) else 0


def pacing(lines: Iterable[str]) -> List[float]:
    return [float(m.group(1)) for m in map(PACING_RE.search, lines) if m]


def judge(fps: List[float]) -> Optional[Tuple[int, float]]:
    """(the rate the game ran at, share of its windows under 90 % of it), None with too little to judge. The
    first two windows (loading) are left out; the rate is the panel rate at or above the 90th percentile."""
    steady = fps[2:]
    if len(steady) < MIN_WINDOWS:
        return None
    p90 = sorted(steady)[int(0.9 * (len(steady) - 1))]
    target = min((r for r in PANEL_RATES if r >= p90 - 1.5), default=PANEL_RATES[-1])
    slow = sum(1 for v in steady if v < target * SLOW_FACTOR) / len(steady)
    return target, slow


def decide(current: Dict[str, Any], fps: List[float], gpu_p80: Optional[float], outcome: str,
           own: Iterable[str], asked_rate: int) -> Tuple[Dict[str, Any], str]:
    """The next auto_quality for a game and why ("" when nothing changes)."""
    own = set(own)
    scale = float(current.get("scale") or 1.0)
    cap = int(current.get("rate_cap") or 0)
    if outcome in BAD_ENDS and scale > 1.0 and "scale" not in own:
        return {**current, "scale": 1.0}, f"back to 1.0x resolution after the session ended badly ({outcome})"
    verdict = judge(fps)
    if not verdict or outcome not in NORMAL_ENDS + BAD_ENDS:
        return current, ""
    target, slow = verdict
    if slow > SLOW_SHARE:
        late = f"{slow:.0%} of the time under {target} Hz"
        if "scale" not in own and scale > 1.0:
            new = round(max(1.0, scale - STEP), 2)
            return {**current, "scale": new}, f"{late}: resolution down to {new:.1f}x"
        if "refresh_rate" not in own and target > CAPPED_RATE and (asked_rate or target) > CAPPED_RATE and not cap:
            return {**current, "rate_cap": CAPPED_RATE}, f"{late}: {CAPPED_RATE} Hz from its next start"
        if "scale" not in own and scale > MIN_SCALE:
            new = round(max(MIN_SCALE, scale - STEP), 2)
            return {**current, "scale": new}, f"{late}: resolution down to {new:.1f}x"
        return current, ""
    if outcome in NORMAL_ENDS and "scale" not in own and gpu_p80 is not None and gpu_p80 < HEADROOM \
            and scale < MAX_SCALE:
        new = round(min(MAX_SCALE, scale + STEP), 2)
        return {**current, "scale": new}, \
            f"steady at {target} Hz with the GPU busy {gpu_p80:.0%} of the time: resolution up to {new:.1f}x"
    return current, ""


def adjust(pkg: str, dep: Dict[str, Any], lines: List[str], gpu_p80: Optional[float], outcome: str,
           asked_rate: int = 0) -> str:
    """After a session: steps the game's automatic quality and rewrites its launcher. Returns why, or ""."""
    from .tuning import LEPTON_KINDS, TuningManager, normalize_settings

    if not enabled() or not dep.get("is_vr", True) or not dep.get("framebridge") \
            or dep.get("kind", "quest") not in LEPTON_KINDS or dep.get("installed_by", "frameload") != "frameload":
        return ""
    current = dep.get("auto_quality") if isinstance(dep.get("auto_quality"), dict) else {}
    own = normalize_settings(dep.get("settings", {}), keep_defaults=True)
    new, why = decide(current, pacing(lines), gpu_p80, outcome, own, asked_rate)
    if not why:
        return ""
    try:
        dep["auto_quality"] = {**new, "note": why, "time": int(time.time())}
        TuningManager._write_dep(dep)
        TuningManager.apply_tuning_to_game(pkg, dep=dep)
        print(f"[FrameLoad] Automatic quality for {pkg}: {why}")
    except Exception as e:
        print(f"[FrameLoad] Could not change the automatic quality of {pkg}: {e}")
        return ""
    return why
