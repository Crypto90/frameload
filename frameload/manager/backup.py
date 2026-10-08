"""Save game backup and restore manager."""
from __future__ import annotations

import glob
import os
import tarfile
import time
from typing import Any, Dict, List

from ..config import ANCHOR_DIR, BACKUP_DIR
from .installed import InstalledManager


class SaveBackupManager:
    @staticmethod
    def backup_saves(package_name: str) -> Dict[str, Any]:
        """Creates a tar.gz backup of the game's saves and container data."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} not found")

        base = dep.get("base", os.path.join(ANCHOR_DIR, package_name))
        external_data = os.path.join(base, "lepton-data/external")

        if not os.path.isdir(external_data):
            raise FileNotFoundError(f"No save/data directory found at {external_data}")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{package_name}_save_{timestamp}.tar.gz"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(external_data, arcname="external")

        return {
            "success": True,
            "package": package_name,
            "filename": backup_filename,
            "path": backup_path,
            "size_bytes": os.path.getsize(backup_path),
        }

    @staticmethod
    def list_backups(package_name: str = "") -> List[Dict[str, Any]]:
        """Lists available backup archives."""
        pattern = f"{package_name}*.tar.gz" if package_name else "*.tar.gz"
        files = sorted(glob.glob(os.path.join(BACKUP_DIR, pattern)), reverse=True)
        results = []
        for f in files:
            name = os.path.basename(f)
            pkg = name.split("_save_")[0] if "_save_" in name else name
            results.append({
                "filename": name,
                "package": pkg,
                "size_bytes": os.path.getsize(f),
                "modified": os.path.getmtime(f),
            })
        return results

    @staticmethod
    def restore_backup(package_name: str, backup_filename: str) -> bool:
        """Restores save data from a backup archive."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} not found")

        base = dep.get("base", os.path.join(ANCHOR_DIR, package_name))
        dest_dir = os.path.join(base, "lepton-data")
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        if not os.path.isfile(backup_path):
            raise FileNotFoundError(f"Backup file {backup_filename} not found")

        with tarfile.open(backup_path, "r:gz") as tar:
            try:
                tar.extractall(dest_dir, filter="data")
            except TypeError:
                tar.extractall(dest_dir)

        # Restore permissions so Lepton Android container user can read & write saves
        try:
            for root, dirs, files in os.walk(dest_dir):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o777)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o666)
        except OSError:
            pass

        return True
