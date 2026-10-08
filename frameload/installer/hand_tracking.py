"""Hand tracking for Quest games on the Steam Frame.

What the headset really offers (FramePort's runtime survey, SteamOS build 20260922):

* The Frame has no camera-based (bare-hand) tracking. Nothing FrameLoad writes to disk can add it;
  that needs a tracking service inside SteamVR itself.
* SteamVR's Android OpenXR runtime does expose XR_EXT_hand_tracking, with the 26-joint skeleton
  driven by the controllers' capacitive finger sensors. A game that asks for hands gets them while
  the player holds the controllers.
* Games ported with FramePort carry the FrameBridge adapter, whose `controller_fix` setting decides
  which of the two the game sees: 1 reports Oculus Touch controllers and hides the hand skeleton,
  0 passes the skeleton through. That key is the only hand-tracking switch FrameLoad controls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

MODES = {
    "auto": "Automatic (hands only for games that require them)",
    "controllers": "Controllers (report Touch controllers, hide the hand skeleton)",
    "hands": "Hands (pass the controller-driven hand skeleton to the game)",
}
REQUIREMENTS = ("none", "optional", "required")


def controller_fix_for(mode: str, requirement: str = "none") -> Optional[int]:
    """FrameBridge's controller_fix value for a hand-input mode; None leaves the game's own value."""
    if mode == "controllers":
        return 1
    if mode == "hands":
        return 0
    return 0 if requirement == "required" else None


def effective_mode(mode: str, requirement: str = "none") -> str:
    fix = controller_fix_for(mode if mode in MODES else "auto", requirement)
    return "game" if fix is None else ("controllers" if fix else "hands")


def status_report(games: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Diagnostics for the dashboard: what the Frame supports and how each installed game is set up."""
    rows = []
    for g in games or []:
        if not g.get("is_vr", True) or g.get("kind") not in ("quest", None):
            continue
        requirement = g.get("hand_tracking", "none")
        mode = (g.get("settings") or {}).get("hand_input", "auto")
        rows.append({
            "package": g.get("package", ""),
            "title": g.get("title", ""),
            "requirement": requirement if requirement in REQUIREMENTS else "none",
            "framebridge": bool(g.get("framebridge")),
            "mode": mode if mode in MODES else "auto",
            "effective": effective_mode(mode, requirement),
        })
    return {
        "optical_supported": False,
        "skeleton_source": "controllers",
        "runtime_extension": "XR_EXT_hand_tracking",
        "joints": 26,
        "summary": ("The Steam Frame tracks hands through its controllers' finger sensors, not through "
                    "cameras. Games receive a full 26-joint OpenXR hand skeleton while you hold the controllers."),
        "modes": MODES,
        "games": rows,
        "games_requiring_hands": sum(1 for r in rows if r["requirement"] == "required"),
    }
