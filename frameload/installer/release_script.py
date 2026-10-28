"""The install.txt of a mirror release: what a release needs beyond its APK and OBB folder.

Rookie-style releases (PortalVR: a Source engine port) carry an install.txt of adb commands, often with
their data packed in _bin.7z. Lepton has no adb, so the commands are carried out on the game's own
folders: /sdcard is <base>/lepton-data/external, /sdcard/Android/obb/<package> is lepton-app/obb.
Only `adb push` and `adb shell mkdir` change anything here; installing the APK is FrameLoad's own job.
Permission commands (appops set, pm grant) for the game's own package go to container_setup.txt, which
launch.sh runs in the game's container once Android has the app.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import shutil
from typing import Any, Dict, List, Optional

SCRIPT_NAME = "install.txt"
RECORD_NAME = "install_txt.json"  # <base>/install_txt.json: what was done, for the game's report
SETUP_NAME = "container_setup.txt"  # <base>/container_setup.txt: commands launch.sh runs in the container
SDCARD_PREFIXES = ("/sdcard/", "/storage/emulated/0/", "/mnt/sdcard/", "/storage/self/primary/")
BUNDLES = ("_bin.7z", "_bin.zip")


def find_script(release_dir: Optional[str]) -> Optional[str]:
    """install.txt in the release folder or the one folder an archive extracts to."""
    if not release_dir or not os.path.isdir(release_dir):
        return None
    candidates = [os.path.join(release_dir, SCRIPT_NAME)]
    try:
        candidates += [os.path.join(release_dir, d, SCRIPT_NAME) for d in sorted(os.listdir(release_dir))]
    except OSError:
        pass
    return next((c for c in candidates if os.path.isfile(c)), None)


def commands(text: str) -> List[List[str]]:
    """The adb commands of an install.txt, as argument lists (comments and blank lines dropped)."""
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        try:
            args = shlex.split(line)
        except ValueError:
            args = line.split()
        if args:
            out.append(args)
    return out


def needs_files(cmds: List[List[str]]) -> bool:
    return any(len(a) >= 4 and a[0] == "adb" and a[1] == "push" for a in cmds)


def device_path(path: str, base: str, package: str) -> Optional[str]:
    """Where an Android path of the shared storage is on the headset; None for anything else."""
    path = posixpath.normpath(path.replace("\\", "/"))
    for prefix in SDCARD_PREFIXES:
        root = prefix.rstrip("/")
        if path == root or path.startswith(prefix):
            rel = path[len(root):].lstrip("/")
            break
    else:
        return None
    obb = f"Android/obb/{package}"
    if rel == obb or rel.startswith(obb + "/"):
        # Lepton links lepton-app/obb to Android/obb/<package>.
        target = os.path.join(base, "lepton-app", "obb", rel[len(obb):].lstrip("/"))
        root_dir = os.path.join(base, "lepton-app", "obb")
    else:
        root_dir = os.path.join(base, "lepton-data", "external")
        target = os.path.join(root_dir, rel)
    target = os.path.normpath(target)
    if target != os.path.normpath(root_dir) and not target.startswith(os.path.normpath(root_dir) + os.sep):
        return None
    return target


def _open_up(path: str) -> None:
    """Lets the app inside Lepton (another user id) read and write what was placed."""
    try:
        if os.path.isfile(path):
            os.chmod(path, 0o666)
            return
        os.chmod(path, 0o777)
        for root, dirs, files in os.walk(path):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o777)
            for f in files:
                os.chmod(os.path.join(root, f), 0o666)
    except OSError:
        pass


def _place(src: str, dst: str) -> None:
    """adb push src dst: into dst when it is a folder (or ends with /), else as dst. Moves: the
    release copy is deleted after the install anyway."""
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src.rstrip(os.sep)))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src) and os.path.isdir(dst):
        shutil.copytree(src, dst, dirs_exist_ok=True)
        shutil.rmtree(src, ignore_errors=True)
    else:
        if os.path.isfile(dst):
            os.remove(dst)
        shutil.move(src, dst)
    _open_up(dst)


def unpack_bundle(folder: str, password: Optional[str] = None) -> Optional[str]:
    """Extracts the release's _bin archive into its folder; the archive's name, or None if there is none."""
    from ..catalog.extractor import extract_archive

    for name in BUNDLES:
        archive = os.path.join(folder, name)
        if os.path.isfile(archive):
            if not extract_archive(archive, folder, password=password):
                raise RuntimeError(f"Could not extract {name} of the release")
            os.remove(archive)
            return name
    return None


def container_commands(lines: List[str], package: str) -> List[List[str]]:
    """The permission lines of an install.txt that may run in the game's container: appops set and
    pm grant, for this package only, with plain names. Anything else from a release never runs there."""
    out = []
    for line in lines:
        args = line.split()
        if args[:2] == ["adb", "shell"]:
            args = args[2:]
        if (len(args) == 6 and args[:3] == ["appops", "set", "--uid"] and args[3] == package
                and re.fullmatch(r"[A-Z][A-Z0-9_]*", args[4]) and args[5] in ("allow", "ignore", "deny", "default")):
            out.append(args)
        elif (len(args) == 4 and args[:2] == ["pm", "grant"] and args[2] == package
              and re.fullmatch(r"android\.permission\.[A-Z][A-Z0-9_]*", args[3])):
            out.append(args)
    return out


def write_container_setup(base: str, package: str, permission_lines: List[str]) -> int:
    """Writes the container commands of a release for launch.sh; their number."""
    cmds = container_commands(permission_lines, package)
    path = os.path.join(base, SETUP_NAME)
    if not cmds:
        return 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(" ".join(c) + "\n" for c in cmds))
    return len(cmds)


def run(release_dir: str, package: str, base: str, password: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Carries out a release's install.txt for the installed game in base. None when it has none."""
    script = find_script(release_dir)
    if not script:
        return None
    folder = os.path.dirname(script)
    with open(script, "r", encoding="utf-8", errors="replace") as f:
        cmds = commands(f.read())
    record: Dict[str, Any] = {"package": package, "release": os.path.basename(os.path.normpath(release_dir)),
                              "script": os.path.relpath(script, release_dir), "done": [], "skipped": [],
                              "permissions": [], "failed": []}
    if needs_files(cmds):
        bundle = unpack_bundle(folder, password)
        if bundle:
            record["done"].append(f"extracted {bundle}")
    for args in cmds:
        line = " ".join(args)
        if args[0] != "adb" or len(args) < 2:
            record["skipped"].append(line)
            continue
        verb = args[1:]
        if verb[0] == "push" and len(verb) >= 3:
            src = os.path.normpath(os.path.join(folder, verb[-2]))
            dst = device_path(verb[-1], base, package)
            if not src.startswith(os.path.normpath(folder) + os.sep) or not os.path.exists(src) or not dst:
                record["failed"].append(line)
                continue
            if os.path.basename(src) == package and dst == device_path("/sdcard/Android/obb", base, package):
                # "adb push <package> /sdcard/Android/obb/": the folder Lepton links there is lepton-app/obb.
                obb = os.path.join(base, "lepton-app", "obb")
                os.makedirs(obb, exist_ok=True)
                for name in os.listdir(src):
                    _place(os.path.join(src, name), obb)
            else:
                if verb[-1].endswith("/"):
                    os.makedirs(dst, exist_ok=True)
                _place(src, dst)
            record["done"].append(line)
        elif verb[:2] == ["shell", "mkdir"]:
            targets = [device_path(p, base, package) for p in verb[2:] if not p.startswith("-")]
            if not targets or not all(targets):
                record["failed"].append(line)
                continue
            for target in targets:
                os.makedirs(target, exist_ok=True)
                _open_up(target)
            record["done"].append(line)
        elif verb[0] in ("install", "install-multiple", "uninstall") or verb[:3] == ["shell", "pm", "uninstall"]:
            record["skipped"].append(line)  # FrameLoad installs the APK itself
        elif verb[:3] in (["shell", "pm", "grant"], ["shell", "appops", "set"]):
            record["permissions"].append(line)
        else:
            record["skipped"].append(line)
    record["container"] = write_container_setup(base, package, record["permissions"])
    try:
        with open(os.path.join(base, RECORD_NAME), "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
    except OSError:
        pass
    return record
