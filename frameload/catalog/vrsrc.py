"""vrSrc mirror integration for FrameLoad.

Uses rclone (the same backend as VR CyberDeck v1.8.3) to fetch the VRP catalog
from go.srcdl1.xyz. The X-API-Key header is required by Cloudflare's bot
protection and is passed via the RCLONE_HEADER environment variable.

The API key was extracted from the VR CyberDeck v1.8.3 macOS ARM64 bundle
by reversing the XOR obfuscation (mask: 'vr-cyberdeck-build-obfuscation-mask-v1').
rclone v1.72.1 is used to match VRCD's exact Go TLS fingerprint.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import urllib.request
import zipfile
from typing import Callable, Optional

from ..config import DATA_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BIN_DIR = os.path.abspath(os.path.join(DATA_DIR, "..", "bin"))
RCLONE_BIN = os.path.join(BIN_DIR, "rclone")

# rclone version VRCD v1.8.3 ships with — same Go TLS stack, same JA3 fingerprint
RCLONE_VERSION = "1.72.1"

RCLONE_DOWNLOAD_URLS = {
    "linux_arm64":  f"https://github.com/rclone/rclone/releases/download/v{RCLONE_VERSION}/rclone-v{RCLONE_VERSION}-linux-arm64.zip",
    "linux_amd64":  f"https://github.com/rclone/rclone/releases/download/v{RCLONE_VERSION}/rclone-v{RCLONE_VERSION}-linux-amd64.zip",
    "darwin_arm64": f"https://github.com/rclone/rclone/releases/download/v{RCLONE_VERSION}/rclone-v{RCLONE_VERSION}-osx-arm64.zip",
    "darwin_amd64": f"https://github.com/rclone/rclone/releases/download/v{RCLONE_VERSION}/rclone-v{RCLONE_VERSION}-osx-amd64.zip",
    "windows_amd64": f"https://github.com/rclone/rclone/releases/download/v{RCLONE_VERSION}/rclone-v{RCLONE_VERSION}-windows-amd64.zip",
}

# API key extracted from VR CyberDeck v1.8.3 .asar bundle
# XOR of base64("F0EfWh1SVEpUU1FTHFFDWV0AG18BBUNKUFcVXQlZGAsHFw4ZFwATFB5bSlZcE11cVFhIAExeXlRLVgdeFEdWVg==")
# with mask "vr-cyberdeck-build-obfuscation-mask-v1"
VRSRC_API_KEY = "a329d018062813601d60cc6936a4f75ffde4a1ef38349a9973eb9720f9e8a457"

VRSRC_REMOTE_NAME = "vrsrc"
VRSRC_GAME_PATH = "Quest Games"


# ---------------------------------------------------------------------------
# rclone management
# ---------------------------------------------------------------------------

def _platform_key() -> str:
    import platform
    machine = platform.machine().lower()
    system = platform.system().lower()
    arch = "arm64" if ("arm" in machine or "aarch" in machine) else "amd64"
    return f"{system}_{arch}"


def rclone_available() -> bool:
    """Return True if rclone is installed and working."""
    rclone = _find_rclone()
    if not rclone:
        return False
    try:
        result = subprocess.run(
            [rclone, "version"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _find_rclone() -> Optional[str]:
    """Return path to rclone: local FrameLoad install first, then system PATH."""
    local = os.path.abspath(RCLONE_BIN)
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    system = shutil.which("rclone")
    return system or None


def install_rclone(status_cb: Optional[Callable[[str], None]] = None) -> bool:
    """Download and install rclone to BIN_DIR if not already present."""
    if rclone_available():
        rclone_path = _find_rclone()
        if status_cb:
            status_cb(f"rclone already available at {rclone_path}")
        return True

    key = _platform_key()
    url = RCLONE_DOWNLOAD_URLS.get(key)
    if not url:
        if status_cb:
            status_cb(f"No rclone download URL for platform: {key}")
        return False

    os.makedirs(BIN_DIR, exist_ok=True)

    if status_cb:
        status_cb(f"Downloading rclone v{RCLONE_VERSION} for {key}...")

    try:
        zip_path = os.path.join(BIN_DIR, "rclone_dl.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        if status_cb:
            status_cb("Extracting rclone...")

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                base = os.path.basename(member)
                if base in ("rclone", "rclone.exe") and member.endswith(base):
                    with zf.open(member) as src, open(RCLONE_BIN, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break

        if os.path.isfile(RCLONE_BIN):
            current_mode = os.stat(RCLONE_BIN).st_mode
            os.chmod(RCLONE_BIN, current_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        try:
            os.remove(zip_path)
        except OSError:
            pass

        if status_cb:
            status_cb("rclone installed successfully.")
        return rclone_available()

    except Exception as e:
        if status_cb:
            status_cb(f"Failed to install rclone: {e}")
        return False


# ---------------------------------------------------------------------------
# rclone config writing
# ---------------------------------------------------------------------------

def _get_config_dir() -> str:
    config_dir = os.path.join(DATA_DIR, ".rclone")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def _rclone_obscure(password: str) -> str:
    """Run rclone obscure to hash the password for the config file."""
    rclone = _find_rclone()
    if not rclone or not password:
        return ""
    try:
        result = subprocess.run(
            [rclone, "obscure", password],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def write_rclone_config(base_url: str, password: str) -> str:
    """Write rclone WebDAV config file and return its path."""
    config_path = os.path.join(_get_config_dir(), "vrsrc.conf")
    obscured = _rclone_obscure(password)
    pass_line = f"pass = {obscured}" if obscured else ""
    config_content = f"[{VRSRC_REMOTE_NAME}]\ntype = webdav\nurl = {base_url}\nvendor = other\nuser =\n{pass_line}\n"
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)
    return config_path


def _make_env() -> dict:
    """Build clean environment for rclone."""
    env = os.environ.copy()
    # Remove proxy vars that could alter TLS fingerprint routing
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        env.pop(var, None)
    return env


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_meta_archive(
    base_url: str,
    password: str,
    dest_path: str,
    status_cb: Optional[Callable[[str], None]] = None,
) -> bool:
    """Download meta.7z from the vrSrc mirror using rclone.

    rclone's Go TLS stack matches VR CyberDeck's TLS fingerprint, which is
    required to pass Cloudflare's bot protection on go.srcdl1.xyz.
    """
    rclone = _find_rclone()
    if not rclone:
        if status_cb:
            status_cb("Installing rclone for mirror access...")
        if not install_rclone(status_cb):
            return False
        rclone = _find_rclone()
        if not rclone:
            return False

    config_path = write_rclone_config(base_url, password)
    dest_dir = os.path.dirname(dest_path)
    os.makedirs(dest_dir, exist_ok=True)

    if status_cb:
        status_cb(f"Fetching game catalog from {base_url}...")

    cmd = [
        rclone, "copy",
        f"{VRSRC_REMOTE_NAME}:/{VRSRC_GAME_PATH}/meta.7z",
        dest_dir,
        "--config", config_path,
        "--tpslimit", "1.0",
        "--tpslimit-burst", "3",
        "--no-check-certificate",
        "--progress",
        "--stats", "2s",
    ]

    try:
        result = subprocess.run(
            cmd,
            env=_make_env(),
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0 and os.path.isfile(dest_path):
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            if status_cb:
                status_cb(f"meta.7z downloaded ({size_mb:.1f} MB)")
            return True
        else:
            err = (result.stderr or result.stdout or "").strip()
            if "403" in err or "Forbidden" in err:
                if status_cb:
                    status_cb("⚠️ Access denied (403) — update config from t.me/the_vrSrc")
            elif "401" in err or "Unauthorized" in err:
                if status_cb:
                    status_cb("⚠️ Wrong password — check vrp-public.json")
            elif "no such host" in err.lower() or "dial" in err.lower():
                if status_cb:
                    status_cb("⚠️ Cannot reach mirror — check network connection")
            else:
                if status_cb:
                    status_cb(f"⚠️ Mirror sync failed: {err[:200]}")
            return False

    except subprocess.TimeoutExpired:
        if status_cb:
            status_cb("⚠️ Download timed out after 5 minutes")
        return False
    except Exception as e:
        if status_cb:
            status_cb(f"⚠️ rclone error: {e}")
        return False


def test_connection(base_url: str, password: str) -> dict:
    """Test connectivity to the vrSrc mirror. Returns {success, message/error}."""
    if not base_url:
        return {"success": False, "error": "No mirror URL configured"}

    rclone = _find_rclone()
    if not rclone:
        return {"success": False, "error": "rclone not installed. Use 'Install rclone' in Mirror Manager."}

    config_path = write_rclone_config(base_url, password)

    cmd = [
        rclone, "lsd",
        f"{VRSRC_REMOTE_NAME}:/",
        "--config", config_path,
        "--no-check-certificate",
        "--contimeout", "10s",
        "--timeout", "15s",
    ]

    try:
        result = subprocess.run(
            cmd, env=_make_env(),
            capture_output=True, text=True, timeout=25
        )
        if result.returncode == 0:
            return {"success": True, "message": f"Connected to {base_url} ✓"}
        err = (result.stderr or "").strip()
        if "403" in err:
            return {"success": False, "error": "403 Forbidden — Cloudflare blocking. The API key may need updating. Check t.me/the_vrSrc for announcements."}
        if "401" in err:
            return {"success": False, "error": "401 Unauthorized — password incorrect"}
        return {"success": False, "error": f"Connection failed: {err[:300]}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Connection timed out (15s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}
