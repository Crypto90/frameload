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
     "Lepton only starts an activity with the LAUNCHER category. Port the game (Port & Play on its page) or use a build made for the Frame."),
    (r"APP_PACKAGE_ID is empty", "error", "Lepton could not read the APK",
     "The APK is damaged or not an Android app. Install it again from a good copy."),
    (r"create keyring|Disk quota exceeded", "error", "podman ran out of kernel keyrings",
     "Restart the headset, then press Apply Podman Keyring Leak Fix under System so it does not return."),
    (r"App installation failed", "error", "Android refused to install the APK",
     "Usual causes: a 32-bit-only app, an app that needs a newer Android, or a broken signature. Run Inspect on the file under Install File."),
    (r"Game files missing at|storage not mounted", "error", "The game's files were not found",
     "If the game is on a microSD card, check that the card is inserted and mounted."),
    (r"Lepton runtime not found", "error", "Lepton was not found",
     "Lepton ships with the Steam Frame. Run the self-test under System."),
    (r"XR_ERROR_API_VERSION_UNSUPPORTED|CreateInstance.*failed", "error", "The game asks for OpenXR 1.1",
     "The Frame's runtime accepts OpenXR 1.0. Porting the game with FramePort adds an adapter that handles this."),
    (r"dlopen failed.*(libOVRPlugin|libvrapi|libovrplatform)|UnsatisfiedLinkError.*(OVR|vrapi)", "error",
     "The game needs Meta's runtime", "It was built for Quest and has not been ported. Press Port & Play on its page."),
    (r"already starting or running", "warn", "The game was already starting",
     "A second launch while the first is still booting is ignored. Wait about ten seconds after pressing Play."),
    (r"zink.*DEVICE[_ ]LOST|VK_ERROR_DEVICE_LOST", "error", "The graphics processor hung",
     "The headset's graphics processor stopped responding while the game drew. This usually happens at the same "
     "point in a game; only a fix for that game helps."),
    # Zygote's "exited due to signal": only the signals of a crash (9 is a normal kill).
    (r"FATAL EXCEPTION|Fatal signal \d+|SIGSEGV|exited due to signal (?:4|5|6|7|8|11|31)\b", "error", "The game crashed",
     "The lines around the crash are in the log below. Game-specific fixes come from FramePort's patches."),
    (r"Signal SIG(?:TERM|INT) received", "info", "Closed by its launcher",
     "Steam's Exit game, or the system, told the game to end."),
    (r"FrameBridge: pacing: ([0-9.]+) fps", "ok", "The game was running",
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
        if match.groups():  # FrameBridge prints "%.1f fps"
            finding["title"] = f"{title} ({round(float(match.group(1)))} fps)"
        findings.append(finding)
    if "FrameBridge" in text and "pacing:" not in text and not any(f["severity"] == "error" for f in findings):
        findings.append({
            "severity": "warn", "title": "The game started but has not shown a VR frame",
            "advice": "If it stays on its loading screen with SteamVR showing \"Waiting\", the game may be checking "
                      "its own signature (a ported copy is re-signed) or waiting for a Meta service that does not "
                      "exist on the Frame. Such games cannot be made to run by porting."})
    if any(f["severity"] == "error" for f in findings):
        findings = [f for f in findings if f["severity"] != "ok"]
    if not findings:
        findings.append({"severity": "info", "title": "No known problem found in the log",
                         "advice": "If the game does not work, the raw log below is what to share when asking for help."})
    return findings
