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
import secrets
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


def revoke(device_id: str = "") -> int:
    """Forgets one paired device, or all of them when no id is given."""
    with _lock:
        current = _load()
        kept = [d for d in current if device_id and d.get("id") != device_id]
        _save(kept)
        return len(current) - len(kept)
