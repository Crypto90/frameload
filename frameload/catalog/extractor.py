"""Archive decompression utilities for 7z, zip, and tar files on Steam Frame."""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from typing import Callable, Optional

from ..config import FRAMELOAD_DIR

STATIC_7ZA_DIR = os.path.join(FRAMELOAD_DIR, "bin")


def find_7z_binary() -> Optional[str]:
    """Finds available 7z / 7za binary in PATH or FrameLoad bin."""
    candidates = [
        os.path.join(STATIC_7ZA_DIR, "7za"),
        os.path.join(STATIC_7ZA_DIR, "7z"),
        shutil.which("7za"),
        shutil.which("7z"),
        shutil.which("p7zip"),
        "/usr/bin/7za",
        "/usr/bin/7z",
        "/usr/local/bin/7za",
        "/usr/local/bin/7z",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def extract_archive(
    archive_path: str,
    output_dir: str,
    password: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None
) -> bool:
    """Extracts an archive (7z, zip, tar.gz) to output_dir, supporting passwords."""
    os.makedirs(output_dir, exist_ok=True)
    ext = os.path.splitext(archive_path)[1].lower()

    if progress_callback:
        progress_callback(f"Extracting {os.path.basename(archive_path)}...")

    # Check for zipfile
    if ext == ".zip":
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if password:
                    zf.setpassword(password.encode("utf-8"))
                zf.extractall(output_dir)
            return True
        except Exception as e:
            if progress_callback:
                progress_callback(f"Zip extraction error: {e}")
            return False

    # Check for tar
    if ext in (".tar", ".gz", ".tgz", ".bz2", ".xz") or archive_path.endswith(".tar.gz"):
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                tf.extractall(output_dir)
            return True
        except Exception as e:
            if progress_callback:
                progress_callback(f"Tar extraction error: {e}")
            return False

    # 7z or multi-part 7z (e.g. .7z.001)
    bin_7z = find_7z_binary()
    if not bin_7z:
        err = "7za / 7z binary not found. Please install p7zip via package manager or place 7za in ~/.local/share/frameload/bin"
        if progress_callback:
            progress_callback(err)
        print(f"[FrameLoad] {err}")
        return False

    cmd = [
        bin_7z,
        "x",
        archive_path,
        f"-o{output_dir}",
        "-aoa",  # overwrite all existing files
        "-y"     # assume yes on all queries
    ]
    if password:
        cmd.append(f"-p{password}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if proc.returncode != 0:
            if progress_callback:
                progress_callback(f"7z error: {proc.stderr or proc.stdout}")
            return False
        return True
    except Exception as e:
        if progress_callback:
            progress_callback(f"Decompression process error: {e}")
        return False
