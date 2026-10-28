"""Brings games installed by older FrameLoad versions to the current on-disk layout."""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR
from .installed import InstalledManager

LAYOUT_VERSION = 11  # 11: launch.sh sets the permissions a release's install.txt asks for (container_setup.txt)
# 10: install.txt data placed in another game of the same version code is moved to its own
# 9: a left-behind release's install.txt is carried out; 8: its OBB folder is moved in
LEPTON_KINDS = ("quest", "flat")
# Files FrameLoad wrote up to v1.3.1 that nothing on the headset reads.
STALE_FILES = (
    "hand_tracking.json", "framebridge_hands.conf", "lepton-window.json",
    "lepton-app/lepton-window.json", "lepton-data/local.prop",
)
STALE_DATA_FILES = ("local.prop", "hand_tracking.json", "framebridge_hands.conf")


def flatten_obb(app_dir: str, package: str) -> int:
    """Moves lepton-app/obb/<package>/* up into lepton-app/obb/, where Lepton links OBB files from."""
    nested = os.path.join(app_dir, "obb", package)
    if not os.path.isdir(nested):
        return 0
    moved = 0
    for name in os.listdir(nested):
        target = os.path.join(app_dir, "obb", name)
        if os.path.exists(target):
            continue
        shutil.move(os.path.join(nested, name), target)
        moved += 1
    if not os.listdir(nested):
        os.rmdir(nested)
    return moved


def restore_release_obb(app_dir: str, package: str, version_code: str, data_dir: Optional[str] = None) -> int:
    """Moves a game's OBB folder in from its extracted mirror release when lepton-app/obb/ is empty.

    Up to v1.4.0 the install hook looked for Android/obb/ and obb/ only, while mirror releases keep the
    folder as <release>/<package>/ beside the APK: the game was installed without its data, which stayed
    behind in DATA_DIR/<release>/. Only a release of the installed version is used."""
    from ..installer.lepton_quest import find_release_obb

    obb_target = os.path.join(app_dir, "obb")
    if not version_code or (os.path.isdir(obb_target) and os.listdir(obb_target)):
        return 0
    for release in _releases_of(package, version_code, data_dir):
        found = find_release_obb(release, None, package)
        if not found:
            continue
        os.makedirs(obb_target, exist_ok=True)
        items = [found] if os.path.isfile(found) else [os.path.join(found, n) for n in os.listdir(found)]
        for src in items:
            shutil.move(src, os.path.join(obb_target, os.path.basename(src)))
        # What is left is the APK the game was installed from: a second copy of lepton-app/game.apk.
        shutil.rmtree(release, ignore_errors=True)
        return len(items)
    return 0


def release_belongs_to(release: str, package: str) -> bool:
    """Whether an extracted release is this package's: it holds <package>.apk or a <package> folder, or its
    release.manifest names the package. A version code alone says nothing (many games are version 1)."""
    for dirpath, dirnames, filenames in os.walk(release):
        if dirpath[len(release):].count(os.sep) >= 3:
            dirnames[:] = []
        if f"{package}.apk" in filenames or package in dirnames:
            return True
        if "release.manifest" in filenames:
            try:
                with open(os.path.join(dirpath, "release.manifest"), "r", encoding="utf-8", errors="replace") as f:
                    if f";{package};" in f.read():
                        return True
            except OSError:
                pass
    return False


def _releases_of(package: str, version_code: str, data_dir: Optional[str] = None) -> List[str]:
    """Extracted mirror releases of this game and version that an install left in DATA_DIR."""
    data_dir = data_dir or DATA_DIR
    try:
        names = sorted(n for n in os.listdir(data_dir) if version_code and f" v{version_code}+" in n)
    except OSError:
        return []
    paths = [os.path.join(data_dir, n) for n in names if os.path.isdir(os.path.join(data_dir, n))]
    return [p for p in paths if release_belongs_to(p, package)]


def move_misplaced_script_data(base: str, package: str, bases: Dict[str, str]) -> List[str]:
    """Layout 9 as first shipped matched releases by version code alone, so a game of the same version
    code (Rick and Morty, version 1) got another game's install.txt data (PortalVR's /sdcard/source).
    The game the script names gets it back."""
    import re
    import shlex
    from ..installer import release_script

    path = os.path.join(base, release_script.RECORD_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return []
    if record.get("package"):
        return []  # recorded by a version that matched releases by package
    named = {p for line in record.get("done", []) + record.get("skipped", []) + record.get("permissions", [])
             for p in re.findall(r"[A-Za-z][\w]*(?:\.[\w]+)+", line) if p in bases}
    if package in named or len(named) != 1:
        record["package"] = package
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        return []
    owner = named.pop()
    owner_base = bases[owner]
    moved = 0
    for line in record.get("done", []):
        args = shlex.split(line)
        if args[:2] != ["adb", "push"] or len(args) < 4:
            continue
        src, dst = args[-2], args[-1]
        here = release_script.device_path(dst, base, package)
        there = release_script.device_path(dst, owner_base, owner)
        if not here or not there:
            continue
        if dst.endswith("/"):
            here, there = os.path.join(here, os.path.basename(src)), os.path.join(there, os.path.basename(src))
        if not os.path.exists(here) or os.path.exists(there):
            continue
        os.makedirs(os.path.dirname(there), exist_ok=True)
        shutil.move(here, there)
        moved += 1
    for line in reversed(record.get("done", [])):  # the folders its mkdir lines made, if now empty
        args = shlex.split(line)
        if args[:3] == ["adb", "shell", "mkdir"]:
            for target in reversed(args[3:]):
                folder = release_script.device_path(target, base, package) if not target.startswith("-") else None
                if folder and os.path.isdir(folder) and not os.listdir(folder):
                    os.rmdir(folder)
    record["package"] = owner
    with open(os.path.join(owner_base, release_script.RECORD_NAME), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    os.remove(path)
    return [f"moved {moved} item(s) of {owner}'s install.txt to {owner}"]


def run_release_script(base: str, package: str, version_code: str, data_dir: Optional[str] = None) -> List[str]:
    """Carries out the install.txt of a left-behind release once (installs up to v1.4.2 ignored it)."""
    from ..installer import release_script
    from ..installer.lepton_quest import find_release_obb

    if os.path.isfile(os.path.join(base, release_script.RECORD_NAME)):
        return []
    for release in _releases_of(package, version_code, data_dir):
        if not release_script.find_script(release):
            continue
        record = release_script.run(release, package, base)
        if record is None:
            continue
        changes = [f"carried out the release's install.txt ({len(record['done'])} step(s))"]
        if record["failed"]:
            changes.append(f"{len(record['failed'])} install.txt step(s) failed: {'; '.join(record['failed'])}")
        elif not find_release_obb(release, None, package):
            shutil.rmtree(release, ignore_errors=True)  # nothing left in it that the game needs
        return changes
    return []


def container_setup_from_record(base: str, package: str) -> List[str]:
    """Layouts 9 and 10 recorded an install.txt's permission lines without setting them."""
    from ..installer import release_script

    if os.path.isfile(os.path.join(base, release_script.SETUP_NAME)):
        return []
    try:
        with open(os.path.join(base, release_script.RECORD_NAME), "r", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return []
    count = release_script.write_container_setup(base, package, record.get("permissions", []))
    return [f"sets {count} permission(s) of its install.txt at each start"] if count else []


def migrate_game(game: Dict[str, Any], bases: Optional[Dict[str, str]] = None) -> List[str]:
    """Migrates one install. Returns what was changed. bases: every installed game's folder."""
    from .tuning import TuningManager

    package = game["package"]
    base = game.get("base") or game.get("anchor")
    changes: List[str] = []

    changes += move_misplaced_script_data(base, package, bases or {package: base})

    moved = flatten_obb(os.path.join(base, "lepton-app"), package)
    if moved:
        changes.append(f"moved {moved} OBB file(s) to where Lepton reads them")
    changes += run_release_script(base, package, str(game.get("version_code") or ""))
    changes += container_setup_from_record(base, package)
    restored = restore_release_obb(os.path.join(base, "lepton-app"), package, str(game.get("version_code") or ""))
    if restored:
        changes.append(f"installed {restored} OBB item(s) the download had left behind")

    files_dir = os.path.join(base, "lepton-data/external/Android/data", package, "files")
    stale = [os.path.join(base, rel) for rel in STALE_FILES] + [os.path.join(files_dir, n) for n in STALE_DATA_FILES]
    removed = 0
    for path in stale:
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    if removed:
        changes.append(f"removed {removed} unused file(s)")

    dep = InstalledManager.get_game(package)
    if dep:
        # Judge the APK again: newer versions recognise more apps that cannot run.
        try:
            from ..installer.apk_analysis import inspect_apk
            analysis = inspect_apk(os.path.join(base, "lepton-app", "game.apk"))
            if analysis.compat.get("level") != (dep.get("compat") or {}).get("level"):
                changes.append(f"compatibility is now: {analysis.compat.get('label', '')}")
            dep.update(compat=analysis.compat, framebridge=analysis.framebridge,
                       hand_tracking=analysis.hand_tracking, xr_runtime=analysis.xr_runtime)
        except Exception:
            pass
        # The app's own icon, which the dashboard draws Steam artwork from.
        art_dir = os.path.join(dep["anchor"], "artwork")
        if os.path.isdir(art_dir) and not any(os.path.isfile(os.path.join(art_dir, "apk_icon" + e)) for e in (".png", ".webp", ".jpg")):
            from ..installer.artwork import extract_apk_icon
            if extract_apk_icon(os.path.join(base, "lepton-app", "game.apk"), art_dir):
                changes.append("found the app's icon for its Steam artwork")
        dep["layout_version"] = LAYOUT_VERSION
        with open(os.path.join(dep["anchor"], "deployment.json"), "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in dep.items() if k not in ("device_name", "is_external")}, f, indent=2)
        if TuningManager.apply_tuning_to_game(package):
            changes.append("rewrote the launcher")
    return changes


def migrate_installs() -> Dict[str, List[str]]:
    """Migrates every FrameLoad-installed Lepton app that is not running. Safe to call on every start."""
    report: Dict[str, List[str]] = {}
    try:
        games = InstalledManager.list_installed()
    except Exception as e:
        print(f"[FrameLoad] Migration skipped: {e}")
        return report
    running = {g["package"] for g in games if g.get("is_running")}
    bases = {g["package"]: g.get("base") or g.get("anchor") for g in games
             if g.get("kind") in LEPTON_KINDS and g["package"] not in running}
    for game in games:
        if game.get("kind") not in LEPTON_KINDS or game.get("is_running"):
            continue
        dep = InstalledManager.get_game(game["package"]) or {}
        # Games installed by FramePort share the folder; their files are FramePort's to manage.
        if dep.get("installed_by") != "frameload" or dep.get("layout_version", 1) >= LAYOUT_VERSION:
            continue
        try:
            report[game["package"]] = migrate_game(game, bases)
        except Exception as e:
            report[game["package"]] = [f"failed: {e}"]
            print(f"[FrameLoad] Could not migrate {game['package']}: {e}")
    return report
