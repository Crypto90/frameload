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


def _report_extract_progress(callback: Optional[Callable], pct: float, msg: str) -> None:
    if not callback:
        return
    try:
        import inspect
        sig = inspect.signature(callback)
        if len(sig.parameters) >= 2:
            callback(pct, msg)
        else:
            callback(msg)
    except Exception:
        try:
            callback(msg)
        except Exception:
            pass


def extract_archive(
    archive_path: str,
    output_dir: str,
    password: Optional[str] = None,
    progress_callback: Optional[Callable] = None
) -> bool:
    """Extracts an archive (7z, zip, tar.gz) to output_dir with live percentage progress."""
    os.makedirs(output_dir, exist_ok=True)
    ext = os.path.splitext(archive_path)[1].lower()
    base_name = os.path.basename(archive_path)

    _report_extract_progress(progress_callback, 0.05, f"Preparing to extract {base_name}...")

    # Check for zipfile
    if ext == ".zip":
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if password:
                    zf.setpassword(password.encode("utf-8"))
                members = zf.infolist()
                total = len(members) or 1
                for i, member in enumerate(members):
                    zf.extract(member, output_dir)
                    if i % 10 == 0 or i == total - 1:
                        pct = round((i + 1) / total, 2)
                        _report_extract_progress(progress_callback, pct, f"Extracting {os.path.basename(member.filename)} ({int(pct*100)}%)")
            _report_extract_progress(progress_callback, 1.0, f"Extracted {base_name} (100%)")
            return True
        except Exception as e:
            _report_extract_progress(progress_callback, 0.0, f"Zip extraction error: {e}")
            return False

    # Check for tar
    if ext in (".tar", ".gz", ".tgz", ".bz2", ".xz") or archive_path.endswith(".tar.gz"):
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                members = tf.getmembers()
                total = len(members) or 1
                for i, member in enumerate(members):
                    tf.extract(member, output_dir)
                    if i % 10 == 0 or i == total - 1:
                        pct = round((i + 1) / total, 2)
                        _report_extract_progress(progress_callback, pct, f"Extracting {os.path.basename(member.name)} ({int(pct*100)}%)")
            _report_extract_progress(progress_callback, 1.0, f"Extracted {base_name} (100%)")
            return True
        except Exception as e:
            _report_extract_progress(progress_callback, 0.0, f"Tar extraction error: {e}")
            return False

    # 7z or multi-part 7z (e.g. .7z.001)
    bin_7z = find_7z_binary()
    if not bin_7z:
        err = "7za / 7z binary not found. Please install p7zip via package manager or place 7za in ~/.local/share/frameload/bin"
        _report_extract_progress(progress_callback, 0.0, err)
        print(f"[FrameLoad] {err}")
        return False

    cmd = [
        bin_7z,
        "x",
        archive_path,
        f"-o{output_dir}",
        "-aoa",  # overwrite all existing files
        "-y",    # assume yes on all queries
        "-bsp1"  # live progress stream to stdout
    ]
    if password:
        cmd.append(f"-p{password}")

    try:
        import re
        pct_regex = re.compile(r"(\d{1,3})%")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1
        )
        last_pct = 0.05

        if proc.stdout:
            while True:
                chunk = proc.stdout.read(48)
                if not chunk and proc.poll() is not None:
                    break
                matches = pct_regex.findall(chunk)
                if matches:
                    val = min(100, max(0, int(matches[-1]))) / 100.0
                    if abs(val - last_pct) >= 0.02 or val >= 0.99:
                        last_pct = val
                        _report_extract_progress(progress_callback, val, f"Extracting archive... {int(val*100)}%")

        proc.wait()
        if proc.returncode != 0:
            err_output = proc.stderr.read() if proc.stderr else "Decompression error"
            _report_extract_progress(progress_callback, 0.0, f"7z error: {err_output[:200]}")
            return False

        _report_extract_progress(progress_callback, 1.0, f"Extracted {base_name} (100%)")
        return True
    except Exception as e:
        _report_extract_progress(progress_callback, 0.0, f"Decompression process error: {e}")
        return False
