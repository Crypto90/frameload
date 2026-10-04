"""Installed games scanner and manager."""
from __future__ import annotations

import glob
import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR


class InstalledManager:
    @staticmethod
    def get_all_anchor_dirs() -> List[Dict[str, Any]]:
        """Returns all anchor directories across internal SSD and mounted MicroSD/external drives."""
        from .storage import StorageManager
        anchors = [{
            "device_id": "internal",
            "device_name": "Internal Storage",
            "path": ANCHOR_DIR,
            "is_external": False,
            "mount_path": os.path.expanduser("~"),
        }]
        seen_paths = {os.path.realpath(ANCHOR_DIR)}
        try:
            for dev in StorageManager.get_devices():
                if dev.get("is_external"):
                    ext_anchor = os.path.join(dev["path"], "quest-frame")
                    rp = os.path.realpath(ext_anchor) if os.path.exists(ext_anchor) else ext_anchor
                    if rp not in seen_paths:
                        anchors.append({
                            "device_id": dev["id"],
                            "device_name": dev["name"],
                            "path": ext_anchor,
                            "is_external": True,
                            "mount_path": dev["path"],
                        })
                        seen_paths.add(rp)
        except Exception:
            pass
        return anchors

    @staticmethod
    def list_installed() -> List[Dict[str, Any]]:
        """Scans internal SSD and mounted MicroSD cards for installed games."""
        games = []
        running_containers = InstalledManager._get_running_lepton_containers()
        anchors = InstalledManager.get_all_anchor_dirs()

        for anchor_info in anchors:
            anchor_dir = anchor_info["path"]
            if not os.path.isdir(anchor_dir):
                continue
            pattern = os.path.join(anchor_dir, "*/deployment.json")

            for dep_path in sorted(glob.glob(pattern)):
                try:
                    with open(dep_path, "r", encoding="utf-8") as f:
                        dep = json.load(f)
                except (OSError, ValueError):
                    continue

                pkg = dep.get("package", os.path.basename(os.path.dirname(dep_path)))
                game_anchor = os.path.dirname(dep_path)
                base = dep.get("base", game_anchor)
                appid = dep.get("appid", 0)

                # Check files status
                apk_path = os.path.join(base, "lepton-app/game.apk")
                apk_present = os.path.isfile(apk_path)
                apk_size = os.path.getsize(apk_path) if apk_present else 0

                # Artwork
                art_dir = os.path.join(game_anchor, "artwork")
                thumb_path = os.path.join(art_dir, "poster.png")
                if not os.path.isfile(thumb_path):
                    thumb_path = os.path.join(art_dir, "icon.png")

                # Running status
                is_running = f"lepton-steamlaunch-{appid}" in running_containers

                games.append({
                    "package": pkg,
                    "title": dep.get("title", pkg),
                    "appid": appid,
                    "gameid": (int(appid) << 32) | 0x02000000 if appid else 0,
                    "base": base,
                    "anchor": game_anchor,
                    "device_id": dep.get("device_id", anchor_info["device_id"]),
                    "device_name": anchor_info["device_name"],
                    "is_external": anchor_info["is_external"],
                    "kind": dep.get("kind", "quest"),
                    "is_vr": dep.get("is_vr", True),
                    "engine": dep.get("engine", "Unknown"),
                    "apk_present": apk_present,
                    "apk_size": apk_size,
                    "installed_time": dep.get("time", 0),
                    "settings": dep.get("settings", {}),
                    "is_running": is_running,
                    "thumbnail_url": f"/api/installed/artwork/{pkg}" if os.path.isdir(art_dir) else "",
                })
        return games

    @staticmethod
    def get_game(package_name: str) -> Optional[Dict[str, Any]]:
        anchors = InstalledManager.get_all_anchor_dirs()
        for anchor_info in anchors:
            dep_path = os.path.join(anchor_info["path"], package_name, "deployment.json")
            if os.path.isfile(dep_path):
                try:
                    with open(dep_path, "r", encoding="utf-8") as f:
                        dep = json.load(f)
                    dep.setdefault("anchor", os.path.dirname(dep_path))
                    dep.setdefault("base", os.path.dirname(dep_path))
                    dep.setdefault("device_id", anchor_info["device_id"])
                    dep.setdefault("device_name", anchor_info["device_name"])
                    dep.setdefault("is_external", anchor_info["is_external"])
                    return dep
                except (OSError, ValueError):
                    pass
        return None

    @staticmethod
    def _get_running_lepton_containers() -> List[str]:
        try:
            res = subprocess.run(["podman", "ps", "--format", "{{.Names}}"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()
        except OSError:
            pass
        return []
