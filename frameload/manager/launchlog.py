"""Reads a game's launch.log and says, in plain words, why it did not start.

The patterns are messages Lepton itself prints (liblepton/*.sh) and ones FramePort documents for the
Steam Frame; anything else is shown as the raw log.
"""
from __future__ import annotations

import json
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
    # Not "CreateInstance ... failed": Unity asks for OpenXR 1.1 first, the loader logs "chained CreateInstance
    # call failed" and Unity goes on with 1.0, in games that run fine.
    (r"XR_ERROR_API_VERSION_UNSUPPORTED", "error", "The game asks for OpenXR 1.1",
     "The Frame's runtime accepts OpenXR 1.0. Porting the game with FramePort adds an adapter that handles this."),
    (r"RuntimeData is null|unable to load from url : jar:file:\S*!/assets/aa/settings\.json|"
     r"(?:No|Unable to (?:find|open|mount)) (?:the )?OBB|OBB (?:file )?not found", "error",
     "The game's data files are missing",
     "Its OBB data is not where Android looks for it (Android/obb/<package>). Install the game again from the "
     "catalog, or copy the release's <package> folder into lepton-app/obb of the game."),
    (r"null cannot be cast to non-null type android\.[\w.]+Manager", "error",
     "The app needs an Android service that Lepton does not have",
     "It asked Android for a system service (for example NsdManager, which finds media servers on the network) "
     "and got none, so it stopped while starting. Lepton's Android does not include that service; the app can "
     "only start on the Frame once Lepton or the app changes."),
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
    (r"logcat: Unexpected EOF!|Logcat read failure", "warn", "Lepton stopped copying the game's log",
     "The game itself may have kept running; its later lines are missing here. FrameLoad then asks the game's "
     "container directly whether it shows a picture. Its later lines are missing here. If you only heard the game while it ran, Show on its page brings it in front."),
]

# The last line steam_ui writes to dashboard.log: "result: <what happened to Steam's menu>".
DASHBOARD_RESULTS = {
    "no-frames": ("info", "FrameLoad saw no VR picture from the game",
                  "So Steam's menu and FrameLoad's window were left in front of it. If you only heard the game, press "
                  "Show {title} in FrameLoad (in its header or on the game's page). If the headset then stays black, "
                  "the game itself does not draw."),
    "player": ("info", "You opened Steam's menu yourself",
               "FrameLoad stops closing Steam's menu once you press the Steam button, so it stayed open."),
    "keeps-reopening": ("warn", "Steam's menu kept coming back over the game",
                        "FrameLoad closed it ten times within seconds. Turn on \"Close FrameLoad's window when a VR game "
                        "shows its first picture\" under System > Starting Games, or start the game from your Steam library."),
    "error": ("info", "Steam's menu could not be closed from here",
              "FrameLoad could not reach Steam's interface. Press the Steam button on your controller to get to the game."),
}
NO_FRAMEBRIDGE = (" This game was not ported, so it does not report its first picture: FrameLoad cannot close "
                  "Steam's menu for it by itself.")


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
    findings = diagnose(lines) + session_findings(base, dep)
    if len(findings) > 1:  # "nothing known" is only true when nothing else was found
        findings = [f for f in findings if f["title"] != NOTHING_FOUND]
    return {
        "package": package_name,
        "exists": True,
        "modified": os.path.getmtime(path),
        "lines": [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines[-MAX_LINES:]],
        "truncated": len(lines) > MAX_LINES,
        "findings": findings,
    }


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_text_file(path: str, limit: int = 4096) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _started_at(base: str) -> float:
    """When launch.sh last started the game (.last_played), 0 if unknown."""
    try:
        with open(os.path.join(base, ".last_played"), "r", encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def session_findings(base: str, dep: Dict[str, Any]) -> List[Dict[str, str]]:
    """What the last start's other files say: how FrameLoad started it (.last_launch) and what became
    of Steam's menu over it (the result line steam_ui ends dashboard.log with)."""
    findings: List[Dict[str, str]] = []
    title = dep.get("title") or dep.get("package") or "the game"
    started = _started_at(base)
    if not started:  # games FramePort installed write plays.log instead of .last_played
        from . import sessions
        started = float(sessions.current_start(dict(dep, base=base, anchor=dep.get("anchor") or base)) or 0)

    error = _read_text_file(os.path.join(base, ".launch_error"))
    try:
        fresh = os.path.getmtime(os.path.join(base, ".launch_error")) >= started - 5
    except OSError:
        fresh = False
    if error.strip() and fresh:  # launch.sh stopped before Lepton ran, so launch.log is an older start's
        findings.append({"severity": "error", "title": "The launcher could not start the game",
                         "advice": error.strip()[:300] + " The log below is from an earlier start."})

    launch = _read_json(os.path.join(base, ".last_launch"))
    # Only when that record belongs to the last start: a start from the Steam library writes none.
    if launch.get("via") == "direct" and (not started or 0 <= started - float(launch.get("time") or 0) <= 120):
        findings.append({
            "severity": "info", "title": "Started directly (Steam had not loaded it)",
            "advice": "It was installed or moved while Steam was running, so Steam has no entry for it yet: Steam shows "
                      "no Resume or Exit for it. End it with Stop in FrameLoad. After Steam restarts, Play starts it "
                      "through Steam."})

    path = os.path.join(base, "dashboard.log")
    try:
        if started and os.path.getmtime(path) < started - 5:
            return findings  # from an earlier start
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            results = [line.strip()[len("result:"):].strip() for line in f if line.strip().startswith("result:")]
    except OSError:
        return findings
    if not results:
        return findings
    kind = results[-1].split(" ", 1)[0]
    if kind in DASHBOARD_RESULTS:
        severity, head, advice = DASHBOARD_RESULTS[kind]
        if kind == "no-frames" and dep.get("is_vr", True) and dep.get("xr_runtime") not in (None, "", "framebridge"):
            advice += NO_FRAMEBRIDGE
        findings.append({"severity": severity, "title": head, "advice": advice.format(title=title)})
    return findings


NOTHING_FOUND = "No known problem found in the log"


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
        findings.append({"severity": "info", "title": NOTHING_FOUND,
                         "advice": "If the game does not work, the raw log below is what to share when asking for help."})
    return findings
