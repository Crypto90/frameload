"""Brings games installed by older FrameLoad versions to the current on-disk layout."""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR
from .installed import InstalledManager

LAYOUT_VERSION = 8  # 8: OBB folders that installs up to v1.4.0 left in the extracted release are moved in
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
    try:
        data_dir = data_dir or DATA_DIR
        releases = sorted(n for n in os.listdir(data_dir) if f" v{version_code}+" in n)
    except OSError:
        return 0
    for name in releases:
        release = os.path.join(data_dir, name)
        found = find_release_obb(release, None, package) if os.path.isdir(release) else None
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


def migrate_game(game: Dict[str, Any]) -> List[str]:
    """Migrates one install. Returns what was changed."""
    from .tuning import TuningManager

    package = game["package"]
    base = game.get("base") or game.get("anchor")
    changes: List[str] = []

    moved = flatten_obb(os.path.join(base, "lepton-app"), package)
    if moved:
        changes.append(f"moved {moved} OBB file(s) to where Lepton reads them")
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
    for game in games:
        if game.get("kind") not in LEPTON_KINDS or game.get("is_running"):
            continue
        dep = InstalledManager.get_game(game["package"]) or {}
        # Games installed by FramePort share the folder; their files are FramePort's to manage.
        if dep.get("installed_by") != "frameload" or dep.get("layout_version", 1) >= LAYOUT_VERSION:
            continue
        try:
            report[game["package"]] = migrate_game(game)
        except Exception as e:
            report[game["package"]] = [f"failed: {e}"]
            print(f"[FrameLoad] Could not migrate {game['package']}: {e}")
    return report
