"""File operations on Lepton data.

Lepton's containers run under rootless podman, so files an app writes belong to subordinate user ids.
The owner of the home folder cannot always read, copy or delete them directly; inside
`podman unshare` (the same user namespace) every one of them is accessible.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

# Filesystems that cannot hold Lepton data or Wine prefixes: no Unix owners, permissions or symlinks.
UNSUPPORTED_FILESYSTEMS = ("vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "msdos")


def podman() -> Optional[str]:
    return shutil.which("podman")


def unshare(args: List[str], timeout: int = 3600) -> Tuple[int, str]:
    """Runs a command inside the user's podman namespace. Returns (exit code, output)."""
    exe = podman()
    if not exe:
        return 127, "podman is not available"
    try:
        proc = subprocess.run([exe, "unshare"] + args, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def remove_tree(path: str) -> bool:
    """Deletes a folder, including files owned by Lepton's containers. True when it is gone."""
    if not os.path.lexists(path):
        return True
    shutil.rmtree(path, ignore_errors=True)
    if os.path.lexists(path) and podman():
        unshare(["rm", "-rf", "--", path])
    return not os.path.lexists(path)


def tree_stats(path: str) -> Tuple[int, int]:
    """(number of files, total bytes) of what this user can see under path."""
    count = total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
                count += 1
            except OSError:
                continue
    return count, total


def move_tree(src: str, dst: str) -> None:
    """Moves a folder, across drives if needed. The source is deleted only after the copy checked out."""
    if os.path.lexists(dst):
        raise FileExistsError(f"{dst} already exists")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)  # same drive: instant, ownership untouched
        return
    except OSError:
        pass

    if podman():
        code, out = unshare(["cp", "-a", "--", src, dst])
        if code:
            remove_tree(dst)
            raise OSError(f"Copy failed: {out[-300:]}")
    else:
        shutil.copytree(src, dst, symlinks=True)
    if tree_stats(src) != tree_stats(dst):
        remove_tree(dst)
        raise OSError("The copy does not match the original; nothing was moved.")
    if not remove_tree(src):
        raise OSError(f"Copied to {dst}, but the original at {src} could not be removed.")


def mount_filesystems() -> Dict[str, str]:
    """Mount point -> filesystem type, from /proc/mounts."""
    mounts: Dict[str, str] = {}
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mounts[parts[1].replace("\\040", " ")] = parts[2]
    except OSError:
        pass
    return mounts


def filesystem_of(path: str, mounts: Optional[Dict[str, str]] = None) -> str:
    """Filesystem type of the mount that holds path ('' when unknown)."""
    mounts = mount_filesystems() if mounts is None else mounts
    path = os.path.realpath(path)
    best = ""
    for mount_point in mounts:
        if (path == mount_point or path.startswith(mount_point.rstrip("/") + "/")) and len(mount_point) > len(best):
            best = mount_point
    return mounts.get(best, "")


def supports_lepton(filesystem: str) -> bool:
    return filesystem.lower() not in UNSUPPORTED_FILESYSTEMS
