"""FrameLoad's patched FrameBridge adapter in FrameLoad's own FramePort install (source: native/framebridge).

FramePort copies its prebuilt adapter, artifacts/<abi>/libopenxr_loader_generic.so, into every game it ports.
Before a port FrameLoad puts its patched build of that adapter there, but only while the file is byte for byte the
one the FramePort release ships (the build's ORIGINAL_SHA256SUMS). The patched build comes from FrameLoad's
release framebridge-<version>-p<n> (find_build) and is checked against that release's SHA256SUMS before it is used; the original is
kept beside it (<name>.frameload-original) and put back when there is no patch for the installed FramePort. Every
other case (another FramePort, a FramePort run from PATH, no network) ports exactly as before.

A ported game whose APK carries the patch logs it ("wait_balance:" is in the library), see has_patch().
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import time
import urllib.request
from typing import Any, Callable, Dict, Optional

from ..config import CACHE_DIR

ADAPTER = "libopenxr_loader_generic.so"
ORIGINAL_SUFFIX = ".frameload-original"
MARKER = b"wait_balance:"  # a log text only the patched adapter contains
REPO = "Crypto90/frameload"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
DOWNLOAD = f"https://github.com/{REPO}/releases/download/{{tag}}/{{name}}"
ABIS = ("arm64-v8a", "armeabi-v7a")
BUILDS_CACHE = os.path.join(CACHE_DIR, "framebridge", "builds.json")
CACHE_SECONDS = 6 * 3600
Log = Callable[[str], None]


def _urlopen(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)  # tests replace this


def _sums(text: str) -> Dict[str, str]:
    """{abi: sha256} from lines "<sha>  libopenxr_loader_generic-<abi>.so"."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"([0-9a-f]{64})\s+\*?libopenxr_loader_generic-([\w-]+)\.so$", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


def find_build(version: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The newest patched build for this FramePort version ({tag, patched, original}), from FrameLoad's releases
    framebridge-<version>-p<revision> (.github/workflows/framebridge.yml builds one for every FramePort release).
    None when there is none (yet). Answers are kept for CACHE_SECONDS, a missing build included."""
    now = time.time() if now is None else now
    try:
        with open(BUILDS_CACHE, encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        cached = {}
    hit = cached.get(version)
    if isinstance(hit, dict) and now - float(hit.get("time", 0)) < CACHE_SECONDS:
        return hit.get("build")
    build = None
    try:
        with _urlopen(RELEASES_API) as resp:
            releases = json.loads(resp.read(4 * 1024 * 1024).decode("utf-8"))
        pattern = re.compile(r"framebridge-" + re.escape(version) + r"-p(\d+)$")
        found = [(int(m.group(1)), r) for r in releases if isinstance(r, dict)
                 for m in [pattern.match(str(r.get("tag_name", "")))] if m]
        if found:
            release = max(found, key=lambda x: x[0])[1]
            tag = release["tag_name"]
            assets = {a.get("name"): a for a in release.get("assets", [])}
            if {"SHA256SUMS", "ORIGINAL_SHA256SUMS"} <= set(assets):
                with _urlopen(DOWNLOAD.format(tag=tag, name="SHA256SUMS")) as resp:
                    patched = _sums(resp.read(65536).decode("utf-8"))
                with _urlopen(DOWNLOAD.format(tag=tag, name="ORIGINAL_SHA256SUMS")) as resp:
                    original = _sums(resp.read(65536).decode("utf-8"))
                if patched and original:
                    build = {"tag": tag, "patched": patched, "original": original}
    except (OSError, ValueError, KeyError) as e:
        print(f"[FrameLoad] Could not look up the patched FrameBridge for FramePort {version}: {e}")
        return (hit or {}).get("build") if isinstance(hit, dict) else None
    cached[version] = {"time": now, "build": build}
    try:
        os.makedirs(os.path.dirname(BUILDS_CACHE), exist_ok=True)
        with open(BUILDS_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cached, f)
        os.replace(BUILDS_CACHE + ".tmp", BUILDS_CACHE)
    except OSError:
        pass
    return build


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifacts_dir(venv: str) -> Optional[str]:
    """FramePort's prebuilt artifacts inside FrameLoad's venv (the wheel keeps them in frameport/_data)."""
    found = sorted(glob.glob(os.path.join(venv, "lib", "python3*", "site-packages", "frameport", "_data", "artifacts")))
    return found[-1] if found else None


def _download(url: str, dest: str, sha: str) -> bool:
    tmp = dest + ".part"
    try:
        with _urlopen(url, 60) as resp, open(tmp, "wb") as f:
            f.write(resp.read(32 * 1024 * 1024))
        if _sha256(tmp) != sha:
            os.remove(tmp)
            return False
        os.replace(tmp, dest)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def ensure(version: str, venv: str, log: Log, cache: str = os.path.join(CACHE_DIR, "framebridge")) -> str:
    """Puts the patched adapter into FramePort's artifacts for this FramePort version, or the originals back.
    Returns one line for the port's log."""
    art = artifacts_dir(venv)
    if not art:
        return "FrameBridge patch: FramePort's artifacts were not found; porting with FramePort's own adapter"
    entry = find_build(version) if version else None
    lines = []
    for abi in ABIS:
        path = os.path.join(art, abi, ADAPTER)
        saved = path + ORIGINAL_SUFFIX
        if not os.path.isfile(path):
            continue
        current = _sha256(path)
        if not entry or not entry["patched"].get(abi):
            # No patched build to vouch for: FramePort's own adapter. A file that still carries the patch gets the
            # original back; one without it was replaced by FramePort itself (an update), so the copy is stale.
            if os.path.isfile(saved):
                with open(path, "rb") as f:
                    ours = MARKER in f.read()
                if ours:
                    os.replace(saved, path)
                else:
                    os.remove(saved)
            continue
        want, original = entry["patched"][abi], entry["original"][abi]
        if current == want:
            lines.append(f"{abi} patched")
            continue
        if current != original:
            lines.append(f"{abi} left alone (not FramePort {version}'s own adapter)")
            continue
        os.makedirs(cache, exist_ok=True)
        cached = os.path.join(cache, f"{entry['tag']}-{abi}.so")
        if not (os.path.isfile(cached) and _sha256(cached) == want) and \
                not _download(DOWNLOAD.format(tag=entry["tag"], name=f"libopenxr_loader_generic-{abi}.so"), cached, want):
            lines.append(f"{abi} unpatched (the patched build could not be downloaded)")
            continue
        with open(cached, "rb") as src, open(path + ".tmp", "wb") as dst:
            dst.write(src.read())
        if not os.path.isfile(saved):
            os.replace(path, saved)
        os.replace(path + ".tmp", path)
        lines.append(f"{abi} patched ({entry['tag']})")
    text = "FrameBridge patch: " + (", ".join(lines) if lines else f"none for FramePort {version or '?'}")
    log(text)
    return text


def has_patch(apk_path: str) -> bool:
    """Whether a ported APK carries FrameLoad's patched adapter."""
    import zipfile

    try:
        with zipfile.ZipFile(apk_path) as zf:
            name = f"lib/arm64-v8a/{ADAPTER}"
            return name in zf.namelist() and MARKER in zf.read(name)
    except (OSError, zipfile.BadZipFile, KeyError):
        return False
