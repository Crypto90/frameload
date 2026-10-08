"""Reads a game's launch.log and says, in plain words, why it did not start.

The patterns are messages Lepton itself prints (liblepton/*.sh) and ones FramePort documents for the
Steam Frame; anything else is shown as the raw log.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from ..config import ANCHOR_DIR
from .installed import InstalledManager

MAX_LINES = 400

# (pattern, severity, title, advice); the first match of each is reported, most specific first.
RULES = [
    (r"APP_ACTIVITY is empty", "error", "The APK has no launcher activity",
     "Lepton only starts an activity with the LAUNCHER category. Port the game (Port for Steam Frame) or use a build made for the Frame."),
    (r"APP_PACKAGE_ID is empty", "error", "Lepton could not read the APK",
     "The APK is damaged or not an Android app. Install it again from a good copy."),
    (r"create keyring|Disk quota exceeded", "error", "podman ran out of kernel keyrings",
     "Restart the headset, then apply the Podman Keyring Leak Fix under System & Diagnostics so it does not return."),
    (r"App installation failed", "error", "Android refused to install the APK",
     "Usual causes: a 32-bit-only app, an app that needs a newer Android, or a broken signature. Run Inspect on the file under Sideload."),
    (r"Game files missing at|storage not mounted", "error", "The game's files were not found",
     "If the game is on a microSD card, check that the card is inserted and mounted."),
    (r"Lepton runtime not found", "error", "Lepton was not found",
     "Lepton ships with the Steam Frame. Run the self-test under System & Diagnostics."),
    (r"XR_ERROR_API_VERSION_UNSUPPORTED|CreateInstance.*failed", "error", "The game asks for OpenXR 1.1",
     "The Frame's runtime accepts OpenXR 1.0. Porting the game with FramePort adds an adapter that handles this."),
    (r"dlopen failed.*(libOVRPlugin|libvrapi|libovrplatform)|UnsatisfiedLinkError.*(OVR|vrapi)", "error",
     "The game needs Meta's runtime", "It was built for Quest and has not been ported. Use Port for Steam Frame."),
    (r"already starting or running", "warn", "The game was already starting",
     "A second launch while the first is still booting is ignored. Wait about ten seconds after pressing Play."),
    (r"FATAL EXCEPTION|Fatal signal \d+|SIGSEGV", "error", "The game crashed",
     "The lines around the crash are in the log below. Game-specific fixes come from FramePort's patches."),
    (r"FrameBridge: pacing: (\d+) fps", "ok", "The game was running",
     "FrameBridge reported frames being shown."),
    (r"Early-exit", "warn", "The container stopped early",
     "Lepton ended before the app was running. The lines above that message usually say why."),
]


def read_log(package_name: str) -> Dict[str, Any]:
    dep = InstalledManager.get_game(package_name)
    if not dep:
        raise FileNotFoundError(f"Game {package_name} is not installed.")
    base = dep.get("base") or dep.get("anchor") or os.path.join(ANCHOR_DIR, package_name)
    path = os.path.join(base, "launch.log")
    if not os.path.isfile(path):
        return {"package": package_name, "exists": False, "lines": [], "findings": [{
            "severity": "info", "title": "This game has not been started yet",
            "advice": "Start it once from your Steam library or with Launch; its log appears here."}]}

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise OSError(f"Could not read the launch log: {e}") from e
    return {
        "package": package_name,
        "exists": True,
        "modified": os.path.getmtime(path),
        "lines": [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines[-MAX_LINES:]],
        "truncated": len(lines) > MAX_LINES,
        "findings": diagnose(lines),
    }


def diagnose(lines: List[str]) -> List[Dict[str, str]]:
    text = "\n".join(lines)
    findings: List[Dict[str, str]] = []
    for pattern, severity, title, advice in RULES:
        match = None
        for match in re.finditer(pattern, text):
            pass  # keep the last occurrence
        if not match:
            continue
        finding = {"severity": severity, "title": title, "advice": advice}
        if match.groups():
            finding["title"] = f"{title} ({match.group(1)} fps)"
        findings.append(finding)
    if any(f["severity"] == "error" for f in findings):
        findings = [f for f in findings if f["severity"] != "ok"]
    if not findings:
        findings.append({"severity": "info", "title": "No known problem found in the log",
                         "advice": "If the game does not work, the raw log below is what to share when asking for help."})
    return findings
