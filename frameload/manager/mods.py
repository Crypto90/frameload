"""Mod and custom content injector for sideloaded VR games (Beat Saber songs, textures, mod packs)."""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR
from .installed import InstalledManager


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def _safe_name(name: str) -> str:
    """A single path component: mod names come from the API and become folder names."""
    name = os.path.basename(str(name).replace("\\", "/").rstrip("/"))
    if name in ("", ".", ".."):
        raise ValueError("Invalid mod name")
    return name


def _inside(base: str, relative: str) -> str:
    """base/relative, refusing anything that leaves base."""
    base = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base, relative))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("Target folder is outside the game's data folder")
    return target


class ModManager:
    @staticmethod
    def get_game_data_dir(package_name: str) -> str:
        """Resolves the external Android data directory for an installed game."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} is not installed.")
        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, package_name))
        return os.path.join(anchor, "lepton-data/external/Android/data", package_name, "files")

    @staticmethod
    def inject_mod(
        package_name: str,
        source_path: str,
        mod_name: str = "",
        target_subpath: str = ""
    ) -> Dict[str, Any]:
        """Injects a mod, custom song, or texture pack into an installed game container."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path}")

        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, package_name))
        base_files_dir = ModManager.get_game_data_dir(package_name)
        os.makedirs(base_files_dir, exist_ok=True)

        is_zip = zipfile.is_zipfile(source_path) if os.path.isfile(source_path) else False
        is_beat_saber = "beatsaber" in package_name.lower()

        # Determine mod name
        if not mod_name:
            base_n = os.path.basename(source_path.rstrip("/"))
            mod_name = os.path.splitext(base_n)[0] if os.path.isfile(source_path) else base_n

        # Check if archive contains direct Android/data or CustomSongs structure
        is_custom_song = False
        if is_zip:
            try:
                with zipfile.ZipFile(source_path, "r") as zf:
                    namelist = [n.lower() for n in zf.namelist()]
                    if any("info.dat" in n for n in namelist) or any(n.endswith((".egg", ".ogg")) for n in namelist):
                        is_custom_song = True
            except Exception:
                pass

        mod_name = _safe_name(mod_name)

        # Determine destination directory
        if target_subpath:
            dest_dir = _inside(base_files_dir, target_subpath)
        elif is_beat_saber or is_custom_song:
            dest_dir = os.path.join(base_files_dir, "CustomSongs", mod_name)
        else:
            dest_dir = os.path.join(base_files_dir, "mods", mod_name)

        os.makedirs(dest_dir, exist_ok=True)
        files_copied = 0

        if is_zip:
            with zipfile.ZipFile(source_path, "r") as zf:
                # Check if archive has an outer wrapping folder
                zf.extractall(dest_dir)
                files_copied = len(zf.namelist())
        elif os.path.isdir(source_path):
            for root, _, files in os.walk(source_path):
                for f in files:
                    s = os.path.join(root, f)
                    rel = os.path.relpath(s, source_path)
                    d = os.path.join(dest_dir, rel)
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy2(s, d)
                    files_copied += 1
        else:
            shutil.copy2(source_path, os.path.join(dest_dir, os.path.basename(source_path)))
            files_copied = 1

        # Fix permissions so Lepton container user can read & write
        try:
            for root, dirs, files in os.walk(dest_dir):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o777)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o666)
        except OSError:
            pass

        return {
            "success": True,
            "package": package_name,
            "mod_name": mod_name,
            "is_custom_song": is_custom_song,
            "files_injected": files_copied,
            "destination": dest_dir
        }

    @staticmethod
    def list_mods(package_name: str) -> List[Dict[str, Any]]:
        """Lists installed mods, custom songs, and content for a given package."""
        try:
            base_dir = ModManager.get_game_data_dir(package_name)
        except FileNotFoundError:
            return []

        mods: List[Dict[str, Any]] = []

        # 1. Check CustomSongs/
        songs_dir = os.path.join(base_dir, "CustomSongs")
        if os.path.isdir(songs_dir):
            for item in sorted(os.listdir(songs_dir)):
                p = os.path.join(songs_dir, item)
                if os.path.isdir(p):
                    sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)
                    mods.append({
                        "id": f"song:{item}",
                        "name": item,
                        "type": "custom_song",
                        "size_bytes": sz,
                        "size_formatted": _format_size(sz),
                        "path": p
                    })

        # 2. Check mods/
        general_mods_dir = os.path.join(base_dir, "mods")
        if os.path.isdir(general_mods_dir):
            for item in sorted(os.listdir(general_mods_dir)):
                p = os.path.join(general_mods_dir, item)
                sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs) if os.path.isdir(p) else os.path.getsize(p)
                mods.append({
                    "id": f"mod:{item}",
                    "name": item,
                    "type": "mod_pack",
                    "size_bytes": sz,
                    "size_formatted": _format_size(sz),
                    "path": p
                })

        return mods

    @staticmethod
    def delete_mod(package_name: str, mod_id: str) -> bool:
        """Deletes a custom song or mod package."""
        base_dir = ModManager.get_game_data_dir(package_name)
        if ":" in mod_id:
            m_type, m_name = mod_id.split(":", 1)
        else:
            m_type, m_name = "mod", mod_id

        m_name = _safe_name(m_name)
        if m_type in ("song", "custom_song"):
            target = os.path.join(base_dir, "CustomSongs", m_name)
        else:
            target = os.path.join(base_dir, "mods", m_name)

        if os.path.exists(target):
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                os.remove(target)
            return True
        return False
