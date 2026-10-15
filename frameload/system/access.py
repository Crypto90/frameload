"""Who may use the dashboard.

Requests from the headset itself (loopback) are trusted. Any other device on the network has to be
paired once: the headset's dashboard shows a six-digit code, the device enters it and receives a
session cookie. Without that, other machines on the same Wi-Fi could install or delete things.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from ..config import FRAMELOAD_DIR

PAIRED_FILE = os.path.join(FRAMELOAD_DIR, "paired_devices.json")
COOKIE_NAME = "frameload_session"
CODE_TTL = 300
MAX_ATTEMPTS = 5
MAX_DEVICES = 20

_lock = threading.Lock()
_code: Dict[str, Any] = {"value": "", "expires": 0.0, "attempts": 0}


def is_loopback(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load() -> List[Dict[str, Any]]:
    try:
        with open(PAIRED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(devices: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(PAIRED_FILE), exist_ok=True)
    tmp = PAIRED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, PAIRED_FILE)


def new_code() -> Dict[str, Any]:
    """A fresh pairing code, shown on the headset. Replaces any earlier one."""
    with _lock:
        _code.update(value=f"{secrets.randbelow(1000000):06d}", expires=time.time() + CODE_TTL, attempts=0)
        return {"code": _code["value"], "expires_in": CODE_TTL}


def redeem(code: str, label: str = "") -> Optional[str]:
    """Exchanges a correct, unexpired code for a session token. A code works once."""
    with _lock:
        if not _code["value"] or time.time() > _code["expires"]:
            return None
        _code["attempts"] += 1
        matches = hmac.compare_digest(str(code).strip(), _code["value"])
        if not matches:
            if _code["attempts"] >= MAX_ATTEMPTS:  # guessing: the code is withdrawn
                _code.update(value="", expires=0.0)
            return None
        _code.update(value="", expires=0.0)
        token = secrets.token_urlsafe(32)
        devices = _load()
        devices.append({"id": secrets.token_hex(6), "token_sha256": _digest(token),
                        "label": (label or "Device")[:60], "created": time.time()})
        _save(devices[-MAX_DEVICES:])
        return token


def is_valid(token: str) -> bool:
    if not token:
        return False
    wanted = _digest(token)
    return any(hmac.compare_digest(wanted, d.get("token_sha256", "")) for d in _load())


def devices() -> List[Dict[str, Any]]:
    return [{"id": d.get("id", ""), "label": d.get("label", ""), "created": d.get("created", 0)} for d in _load()]


# Interfaces of containers and virtual bridges: another device cannot reach the headset through them.
VIRTUAL_INTERFACES = ("lo", "docker", "br-", "veth", "virbr", "podman", "cni", "tun", "tap", "wg")


def lan_addresses() -> List[Dict[str, str]]:
    """The headset's IPv4 addresses another device on the same network can open, Wi-Fi first."""
    found: List[Dict[str, str]] = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        # "3: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global dynamic wlan0 ..."
        match = re.match(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/", line)
        if match and not match.group(1).startswith(VIRTUAL_INTERFACES):
            found.append({"interface": match.group(1), "ip": match.group(2)})
    if not found:
        # Without iproute2: the address the system would send from (a UDP connect sends nothing).
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))
                ip = s.getsockname()[0]
            if not ipaddress.ip_address(ip).is_loopback:
                found.append({"interface": "", "ip": ip})
        except (OSError, ValueError):
            pass
    found.sort(key=lambda a: 0 if a["interface"].startswith(("wl", "wifi")) else 1)
    return found


def revoke(device_id: str = "") -> int:
    """Forgets one paired device, or all of them when no id is given."""
    with _lock:
        current = _load()
        kept = [d for d in current if device_id and d.get("id") != device_id]
        _save(kept)
        return len(current) - len(kept)
