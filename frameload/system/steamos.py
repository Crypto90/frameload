"""SteamOS, hardware, and Lepton runtime discovery for Steam Frame."""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from ..config import ANCHOR_DIR, HOME, STEAM_DIR

LEPTON_APPID = "3029110"
CONTAINERS_CONF = os.path.join(HOME, ".config/containers/containers.conf")
POWER_SUPPLY = "/sys/class/power_supply"
CHARGER_TYPES = ("Mains", "USB", "USB_C", "USB_PD", "USB_PD_DRP", "USB_DCP", "USB_CDP", "USB_ACA", "Wireless")


def get_os_release() -> Dict[str, str]:
    info: Dict[str, str] = {}
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    k, _, v = line.strip().partition("=")
                    if k:
                        info[k] = v.strip('"')
        except OSError:
            pass
    return info


def is_steamos() -> bool:
    info = get_os_release()
    return "steamos" in info.get("ID", "").lower() or "steamos" in info.get("NAME", "").lower()


def is_steam_frame() -> bool:
    # Steam Frame running Linux on ARM64 or SteamOS with Lepton
    uname_m = os.uname().machine.lower()
    return uname_m in ("aarch64", "arm64") or is_steamos()


def steam_libraries() -> List[str]:
    libs = [os.path.join(STEAM_DIR, "steamapps")]
    vdf = os.path.join(STEAM_DIR, "steamapps/libraryfolders.vdf")
    if os.path.exists(vdf):
        try:
            with open(vdf, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            for path in re.findall(r'"path"\s+"([^"]+)"', text):
                p = os.path.join(path, "steamapps")
                if p not in libs and os.path.isdir(p):
                    libs.append(p)
        except OSError:
            pass
    return libs


def find_app(name_regex: str) -> Optional[Dict[str, str]]:
    for lib in steam_libraries():
        for acf in glob.glob(os.path.join(lib, "appmanifest_*.acf")):
            try:
                with open(acf, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            name_m = re.search(r'"name"\s+"([^"]*)"', text)
            if name_m and re.search(name_regex, name_m[1], re.IGNORECASE):
                appid_m = re.search(r'"appid"\s+"(\d+)"', text)
                installdir_m = re.search(r'"installdir"\s+"([^"]*)"', text)
                if appid_m and installdir_m:
                    return {
                        "appid": appid_m[1],
                        "name": name_m[1],
                        "dir": os.path.join(lib, "common", installdir_m[1])
                    }
    return None


def lepton_status() -> Dict[str, Any]:
    app = find_app(r"Lepton")
    candidates = []
    if app:
        candidates.append(os.path.join(app["dir"], "lepton"))
    candidates.extend([
        os.path.join(STEAM_DIR, "steamapps/common/Lepton/lepton"),
        os.path.join(HOME, ".local/share/Steam/steamapps/common/Lepton/lepton"),
        "/usr/bin/lepton",
    ])

    lepton_bin = None
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            lepton_bin = c
            break

    dev_app = find_app(r"Lepton Development")
    return {
        "installed": lepton_bin is not None,
        "path": lepton_bin,
        "appid": app["appid"] if app else LEPTON_APPID,
        "name": app["name"] if app else "Lepton",
        "has_dev_app": dev_app is not None,
    }


def install_lepton_request() -> bool:
    try:
        subprocess.Popen(
            ["steam", "-ifrunning", f"steam://install/{LEPTON_APPID}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True
    except OSError:
        return False


def proton_status() -> Dict[str, Any]:
    tools = []
    for lib in steam_libraries():
        for d in glob.glob(os.path.join(lib, "common/Proton*")):
            if os.path.isdir(d):
                tools.append(os.path.basename(d))
    return {
        "installed_tools": tools,
        "has_proton": len(tools) > 0,
    }


def ensure_host_podman_fixes() -> List[str]:
    """Prevent rootless podman leaking kernel session keyrings per container start."""
    changed = []
    text = ""
    if os.path.exists(CONTAINERS_CONF):
        try:
            with open(CONTAINERS_CONF, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            pass

    if not re.search(r"^\s*keyring\s*=", text, re.M):
        note = "# FrameLoad: prevent rootless podman keyring exhaustion leak on Lepton\n"
        if re.search(r"^\[containers\]\s*$", text, re.M):
            text = re.sub(
                r"^\[containers\]\s*$",
                "[containers]\n" + note + "keyring = false",
                text,
                count=1,
                flags=re.M
            )
        else:
            sep = "\n" if text and not text.endswith("\n") else ""
            text = text + sep + "[containers]\n" + note + "keyring = false\n"

        os.makedirs(os.path.dirname(CONTAINERS_CONF), exist_ok=True)
        try:
            with open(CONTAINERS_CONF, "w", encoding="utf-8") as f:
                f.write(text)
            changed.append("podman keyring=false configured")
        except OSError as e:
            print(f"[FrameLoad] Could not write containers.conf: {e}")
    return changed


def battery_state() -> Optional[Dict[str, Any]]:
    if not os.path.exists(POWER_SUPPLY):
        return None

    def read_sys(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    battery = None
    plugged = False
    try:
        for name in sorted(os.listdir(POWER_SUPPLY)):
            d = os.path.join(POWER_SUPPLY, name)
            kind = read_sys(os.path.join(d, "type"))
            cap = read_sys(os.path.join(d, "capacity"))
            status = read_sys(os.path.join(d, "status"))
            online = read_sys(os.path.join(d, "online"))

            if kind == "Battery" and battery is None and cap.isdigit():
                battery = {
                    "percent": int(cap),
                    "status": status,
                }
            elif kind in CHARGER_TYPES and online == "1":
                plugged = True
    except OSError:
        pass

    if battery is not None:
        battery["plugged"] = plugged or battery["status"] in ("Charging", "Full")
        battery["draining"] = battery["status"] == "Discharging"
    return battery


def storage_info() -> Dict[str, Any]:
    home_stat = os.statvfs(HOME)
    free_bytes = home_stat.f_bavail * home_stat.f_frsize
    total_bytes = home_stat.f_blocks * home_stat.f_frsize
    used_bytes = total_bytes - free_bytes

    return {
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_gb": round(free_bytes / (1024 ** 3), 1),
        "total_gb": round(total_bytes / (1024 ** 3), 1),
        "percent_used": round((used_bytes / max(total_bytes, 1)) * 100, 1),
    }


def is_steam_running() -> bool:
    res = subprocess.run(["pgrep", "-x", "steam"], capture_output=True, text=True)
    return res.returncode == 0


def is_desktop_mode() -> bool:
    res = subprocess.run(["pgrep", "-x", "plasmashell"], capture_output=True, text=True)
    return res.returncode == 0


def get_system_summary() -> Dict[str, Any]:
    osr = get_os_release()
    uname = os.uname()
    return {
        "hostname": uname.nodename,
        "arch": uname.machine,
        "os_name": osr.get("NAME", "Linux"),
        "os_version": osr.get("VERSION_ID", ""),
        "build_id": osr.get("BUILD_ID", ""),
        "is_steamos": is_steamos(),
        "is_steam_frame": is_steam_frame(),
        "steam_running": is_steam_running(),
        "desktop_mode": is_desktop_mode(),
        "lepton": lepton_status(),
        "proton": proton_status(),
        "battery": battery_state(),
        "storage": storage_info(),
        "host_fixes": ensure_host_podman_fixes(),
    }
