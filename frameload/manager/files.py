"""Finding installable files on the headset, and receiving them from a phone or PC."""
from __future__ import annotations

import os
import re
import shutil
import time
from typing import Any, BinaryIO, Dict, List, Optional

from ..config import FRAMELOAD_DIR, HOME

UPLOAD_DIR = os.path.join(FRAMELOAD_DIR, "uploads")
INSTALLABLE = (".apk", ".xapk", ".apks", ".zip", ".obb", ".exe", ".appimage")
SESSION_RE = re.compile(r"[a-f0-9]{8,32}")
MAX_ENTRIES = 500
FREE_SPACE_MARGIN = 512 * 1024 * 1024
STALE_UPLOAD_SECONDS = 24 * 3600


def roots() -> List[Dict[str, str]]:
    """Where the file browser may look: the home folder, removable drives and received uploads."""
    found = [{"name": "Home", "path": HOME}]
    downloads = os.path.join(HOME, "Downloads")
    if os.path.isdir(downloads):
        found.append({"name": "Downloads", "path": downloads})
    if os.path.isdir("/run/media"):
        found.append({"name": "Drives and microSD", "path": "/run/media"})
    if os.path.isdir(UPLOAD_DIR) and os.listdir(UPLOAD_DIR):
        found.append({"name": "Received from other devices", "path": UPLOAD_DIR})
    return found


def _inside_root(path: str) -> bool:
    real = os.path.realpath(path)
    for root in (HOME, "/run/media", UPLOAD_DIR):
        root_real = os.path.realpath(root)
        if real == root_real or real.startswith(root_real.rstrip(os.sep) + os.sep):
            return True
    return False


def browse(path: str = "") -> Dict[str, Any]:
    """Folders and installable files in path; the list of roots when path is empty."""
    if not path:
        return {"path": "", "parent": None, "entries": [
            {"name": r["name"], "path": r["path"], "is_dir": True, "size": 0} for r in roots()]}
    if not _inside_root(path) or not os.path.isdir(path):
        raise PermissionError("That folder is not available to the file browser.")

    entries: List[Dict[str, Any]] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        entries.append({"name": entry.name, "path": entry.path, "is_dir": True, "size": 0})
                    elif entry.name.lower().endswith(INSTALLABLE):
                        entries.append({"name": entry.name, "path": entry.path, "is_dir": False,
                                        "size": entry.stat().st_size})
                except OSError:
                    continue
    except OSError as e:
        raise PermissionError(f"Cannot read that folder: {e}") from e
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    parent = os.path.dirname(path.rstrip(os.sep))
    return {
        "path": path,
        "parent": parent if parent and _inside_root(parent) else "",
        "entries": entries[:MAX_ENTRIES],
        "truncated": len(entries) > MAX_ENTRIES,
    }


def safe_upload_name(name: str) -> str:
    """The file name an upload is stored under, or '' if it is not an installable file."""
    name = os.path.basename(str(name).replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._ ()\[\]+\-]", "_", name)
    if not name or name.startswith(".") or not name.lower().endswith(INSTALLABLE):
        return ""
    return name[:200]


def receive_upload(session: str, name: str, length: int, stream: BinaryIO) -> Dict[str, Any]:
    """Stores one uploaded file in the session's folder, reading the body straight to disk."""
    if not SESSION_RE.fullmatch(session or ""):
        raise ValueError("Invalid upload session")
    safe = safe_upload_name(name)
    if not safe:
        raise ValueError("Only .apk, .obb, .xapk, .apks, .zip, .exe and .AppImage files can be uploaded")
    if length <= 0:
        raise ValueError("Empty upload")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if length + FREE_SPACE_MARGIN > shutil.disk_usage(UPLOAD_DIR).free:
        raise OSError("Not enough free space on the headset for this file")

    folder = os.path.join(UPLOAD_DIR, session)
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, safe)
    partial = target + ".part"
    remaining = length
    try:
        with open(partial, "wb") as out:
            while remaining > 0:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining:
            raise ConnectionError("The upload was interrupted")
        os.replace(partial, target)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return {"success": True, "path": target, "folder": folder, "name": safe, "size": length}


def upload_session_of(path: str) -> Optional[str]:
    """The upload folder a path lives in, if it is an upload."""
    real = os.path.realpath(path)
    base = os.path.realpath(UPLOAD_DIR)
    if not real.startswith(base + os.sep):
        return None
    session = os.path.relpath(real, base).split(os.sep)[0]
    return os.path.join(base, session) if SESSION_RE.fullmatch(session) else None


def discard_upload(path: str) -> None:
    folder = upload_session_of(path)
    if folder:
        shutil.rmtree(folder, ignore_errors=True)


def clean_stale_uploads() -> int:
    """Removes uploads that were never installed."""
    removed = 0
    if not os.path.isdir(UPLOAD_DIR):
        return 0
    for name in os.listdir(UPLOAD_DIR):
        folder = os.path.join(UPLOAD_DIR, name)
        try:
            if time.time() - os.path.getmtime(folder) > STALE_UPLOAD_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
