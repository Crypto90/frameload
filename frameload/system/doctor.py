"""Self-test: checks, on the headset, every assumption FrameLoad makes about the Steam Frame.

`frameload doctor` prints the result; the dashboard shows it under System. Each check reports what
it found, so a failing one says what to look at instead of leaving a game that silently won't start.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import platform
import re
import shutil
import socket
from typing import Any, Dict, List

from ..config import ANCHOR_DIR, HOME, STEAM_DIR
from .steamos import CONTAINERS_CONF, get_os_release, is_steam_frame, is_steam_running, lepton_status, storage_info

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


def _check(name: str, state: str, detail: str) -> Dict[str, str]:
    return {"name": name, "state": state, "detail": detail}


def _cameras() -> List[str]:
    names = []
    for path in sorted(glob.glob("/sys/class/video4linux/*/name")):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                names.append(f"{os.path.basename(os.path.dirname(path))}: {f.read().strip()}")
        except OSError:
            continue
    return names


def run_checks() -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    osr = get_os_release()
    os_label = f"{osr.get('NAME', platform.system())} {osr.get('VERSION_ID', '')} {osr.get('BUILD_ID', '')} ({platform.machine()})".strip()
    on_frame = is_steam_frame()
    checks.append(_check("Device", OK if on_frame else WARN,
                         os_label if on_frame else f"{os_label} - not SteamOS on ARM64, so this is not a Steam Frame."))

    lepton = lepton_status()
    checks.append(_check("Lepton", OK if lepton["installed"] else FAIL,
                         lepton["path"] if lepton["installed"]
                         else "Not found in any Steam library. It ships with the Frame; Steam can reinstall it (app 3029110)."))

    podman = shutil.which("podman")
    checks.append(_check("podman", OK if podman else FAIL, podman or "Not found; Lepton's containers need it."))
    keyring = False
    try:
        with open(CONTAINERS_CONF, "r", encoding="utf-8") as f:
            keyring = bool(re.search(r"^\s*keyring\s*=\s*false", f.read(), re.M))
    except OSError:
        pass
    checks.append(_check("podman keyring fix", OK if keyring else WARN,
                         "keyring = false is set." if keyring
                         else "Not set: after about 200 game starts per boot every container fails. System > Apply Podman Keyring Leak Fix."))

    missing = [tool for tool in ("bash", "flock", "setsid", "find") if not shutil.which(tool)]
    checks.append(_check("Launcher tools", FAIL if missing else OK,
                         "Missing: " + ", ".join(missing) if missing else "bash, flock, setsid and find are available."))

    users = glob.glob(os.path.join(STEAM_DIR, "userdata", "*", "config"))
    checks.append(_check("Steam library", OK if users else WARN,
                         f"{STEAM_DIR} ({len(users)} user(s)); Steam is {'running' if is_steam_running() else 'not running'}."
                         if users else f"No Steam user found under {STEAM_DIR}; shortcuts cannot be added."))

    try:
        from ..manager.installed import InstalledManager
        games = InstalledManager.list_installed()
    except Exception as e:
        games = []
        checks.append(_check("Installed games", FAIL, f"Could not read the library: {e}"))
    lepton_games = [g for g in games if g.get("kind") in ("quest", "flat")]
    no_apk = [g["package"] for g in lepton_games if not g.get("apk_present")]
    unported = [g["title"] for g in lepton_games if (g.get("compat") or {}).get("level") == "needs_port"]
    blocked = [g["title"] for g in lepton_games if (g.get("compat") or {}).get("level") == "blocked"]
    state = FAIL if no_apk else (WARN if unported or blocked else OK)
    detail = f"{len(games)} installed in {ANCHOR_DIR}."
    if no_apk:
        detail += " Missing game.apk: " + ", ".join(no_apk) + "."
    if unported:
        detail += " Need porting: " + ", ".join(unported) + "."
    if blocked:
        detail += " Cannot run: " + ", ".join(blocked) + "."
    checks.append(_check("Installed games", state, detail))

    try:
        from ..installer import porting
        port = porting.status()
        ready = port["installed"] and port["tools_ready"]
        checks.append(_check("Quest porting (FramePort)", OK if ready else INFO,
                             f"FramePort {port['version']} with its tools. {port.get('limited', '')}".strip() if ready
                             else "FramePort is installed; its tools are not." if port["installed"]
                             else "Not set up. Needed only for Quest games that are not ported yet."))
    except Exception as e:
        checks.append(_check("Quest porting (FramePort)", WARN, str(e)))
    venv_ok = all(importlib.util.find_spec(m) for m in ("venv", "ensurepip"))
    checks.append(_check("Python", OK if venv_ok else WARN,
                         f"{platform.python_version()}" + ("" if venv_ok else "; venv/ensurepip missing, so FramePort cannot be installed automatically.")))

    store = storage_info()
    checks.append(_check("Storage", OK if store["free_gb"] >= 5 else WARN, f"{store['free_gb']} GB free in {HOME}."))

    cameras = _cameras()
    checks.append(_check("Cameras", INFO,
                         "; ".join(cameras) if cameras else "No video devices are visible to this user."))
    runtime = os.path.expanduser("~/.config/openxr/1/active_runtime.json")
    checks.append(_check("Hand tracking", INFO,
                         "Controller-driven (XR_EXT_hand_tracking from the controllers' finger sensors). "
                         "The Frame has no camera hand tracking." + (f" OpenXR runtime: {os.path.realpath(runtime)}." if os.path.exists(runtime) else "")))

    node = socket.gethostname()
    checks.append(_check("Dashboard address", INFO,
                         f"Reachable by IP address, http://localhost:5050 or http://{node}.local:5050. "
                         "Other host names: frameload allow-host <name>."))

    worst = FAIL if any(c["state"] == FAIL for c in checks) else (WARN if any(c["state"] == WARN for c in checks) else OK)
    return {"state": worst, "on_frame": on_frame, "checks": checks}


def format_report(report: Dict[str, Any]) -> str:
    marks = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]", INFO: "[info]"}
    return "\n".join(f"{marks[c['state']]} {c['name']}: {c['detail']}" for c in report["checks"])
