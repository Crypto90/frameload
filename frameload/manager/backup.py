"""Save game backup and restore manager.

A Lepton app keeps data in two places under <game>/lepton-data: `internal/<package>` (the app's
private storage, where most games save) and `external` (shared storage: Android/data, mods, songs).
Both are archived. Downloaded game data in external/Android/obb is left out: it is not a save.
"""
from __future__ import annotations

import glob
import json
import os
import re
import tarfile
import time
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR, BACKUP_DIR
from ..system import fsutil
from .installed import InstalledManager

SAVE_FOLDERS = ("internal", "external")
EXCLUDE = "external/Android/obb"
BACKUP_NAME = re.compile(r"[A-Za-z0-9_.\-]+_save_\d{8}_\d{6}\.tar\.gz")


AUTO_KEEP = 3  # backups FrameLoad took by itself before a change, per game
AUTO_INDEX = os.path.join(BACKUP_DIR, "automatic.json")


def _read_auto() -> Dict[str, List[str]]:
    try:
        with open(AUTO_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_auto(data: Dict[str, List[str]]) -> None:
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(AUTO_INDEX + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(AUTO_INDEX + ".tmp", AUTO_INDEX)
    except OSError:
        pass


class NoSaveData(FileNotFoundError):
    """The game has not written any data yet, so there is nothing to back up."""


class SaveBackupManager:
    @staticmethod
    def _data_dir(package_name: str) -> str:
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} not found")
        return os.path.join(dep.get("base", os.path.join(ANCHOR_DIR, package_name)), "lepton-data")

    @staticmethod
    def backup_saves(package_name: str, anchor: str = "") -> Dict[str, Any]:
        """Creates a tar.gz backup of the game's private and shared data."""
        data_dir = os.path.join(anchor, "lepton-data") if anchor else SaveBackupManager._data_dir(package_name)
        folders = [f for f in SAVE_FOLDERS if os.path.isdir(os.path.join(data_dir, f))]
        if not folders:
            raise NoSaveData(f"No save data found in {data_dir}")

        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_filename = f"{package_name}_save_{time.strftime('%Y%m%d_%H%M%S')}.tar.gz"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        complete = True
        if fsutil.podman():
            # Inside the container namespace every file is readable, whoever owns it.
            code, out = fsutil.unshare(["tar", "-czf", backup_path, f"--exclude={EXCLUDE}", "-C", data_dir] + folders)
            if code and not os.path.isfile(backup_path):
                raise OSError(f"Backup failed: {out[-300:]}")
            complete = code == 0
        else:
            def keep(info: tarfile.TarInfo):
                return None if info.name == EXCLUDE or info.name.startswith(EXCLUDE + "/") else info

            with tarfile.open(backup_path, "w:gz") as tar:
                for folder in folders:
                    try:
                        tar.add(os.path.join(data_dir, folder), arcname=folder, filter=keep)
                    except OSError:
                        complete = False

        return {
            "success": True,
            "package": package_name,
            "filename": backup_filename,
            "path": backup_path,
            "size_bytes": os.path.getsize(backup_path),
            "includes": folders,
            "complete": complete,
        }

    @staticmethod
    def backup_before_change(package_name: str, anchor: str = "") -> Optional[Dict[str, Any]]:
        """A backup taken by itself before an update, port or reinstall replaces the game's APK. Only the
        newest AUTO_KEEP of these stay per game (backups made by hand are never removed); a failure is
        logged and never stops the install. None when the game has no data yet."""
        try:
            result = SaveBackupManager.backup_saves(package_name, anchor)
        except NoSaveData:
            return None
        except Exception as e:
            print(f"[FrameLoad] Could not back up the saves of {package_name} before changing it: {e}")
            return None
        auto = _read_auto()
        names = [n for n in auto.get(package_name, []) if os.path.isfile(os.path.join(BACKUP_DIR, n))]
        names.append(result["filename"])
        for old in names[:-AUTO_KEEP]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
            except OSError:
                pass
        auto[package_name] = names[-AUTO_KEEP:]
        _write_auto(auto)
        print(f"[FrameLoad] Saves of {package_name} backed up before the change: {result['filename']}")
        return result

    @staticmethod
    def list_backups(package_name: str = "") -> List[Dict[str, Any]]:
        """Lists available backup archives, newest first."""
        pattern = f"{glob.escape(package_name)}_save_*.tar.gz" if package_name else "*.tar.gz"
        results = []
        for f in sorted(glob.glob(os.path.join(BACKUP_DIR, pattern)), reverse=True):
            name = os.path.basename(f)
            results.append({
                "filename": name,
                "package": name.split("_save_")[0] if "_save_" in name else name,
                "size_bytes": os.path.getsize(f),
                "modified": os.path.getmtime(f),
            })
        return results

    @staticmethod
    def _check_archive(backup_path: str) -> None:
        """Refuses archives with entries that would land outside the game's data folder."""
        with tarfile.open(backup_path, "r:gz") as tar:
            for member in tar:
                name = member.name.replace("\\", "/")
                top = name.split("/", 1)[0]
                if name.startswith("/") or ".." in name.split("/") or top not in SAVE_FOLDERS:
                    raise ValueError(f"Backup contains an unexpected entry: {member.name}")
                if member.islnk() or member.issym():
                    target = member.linkname.replace("\\", "/")
                    if target.startswith("/") or ".." in target.split("/"):
                        raise ValueError(f"Backup contains a link that points outside: {member.name}")

    @staticmethod
    def restore_backup(package_name: str, backup_filename: str) -> bool:
        """Restores save data from a backup archive."""
        if not BACKUP_NAME.fullmatch(backup_filename or "") or not backup_filename.startswith(f"{package_name}_save_"):
            raise ValueError("That is not a backup of this game")
        data_dir = SaveBackupManager._data_dir(package_name)
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        if not os.path.isfile(backup_path):
            raise FileNotFoundError(f"Backup file {backup_filename} not found")
        SaveBackupManager._check_archive(backup_path)

        os.makedirs(data_dir, exist_ok=True)
        if fsutil.podman():
            # Restores owners and permissions as the app left them.
            code, out = fsutil.unshare(["tar", "-xzf", backup_path, "-C", data_dir])
            if code:
                raise OSError(f"Restore failed: {out[-300:]}")
        else:
            with tarfile.open(backup_path, "r:gz") as tar:
                try:
                    tar.extractall(data_dir, filter="data")
                except TypeError:  # Python without extraction filters; entries were checked above
                    tar.extractall(data_dir)
        return True
