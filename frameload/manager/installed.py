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
    def list_installed() -> List[Dict[str, Any]]:
        """Scans ~/Applications/quest-frame for installed games."""
        games = []
        pattern = os.path.join(ANCHOR_DIR, "*/deployment.json")

        running_containers = InstalledManager._get_running_lepton_containers()

        for dep_path in sorted(glob.glob(pattern)):
            try:
                with open(dep_path, "r", encoding="utf-8") as f:
                    dep = json.load(f)
            except (OSError, ValueError):
                continue

            pkg = dep.get("package", os.path.basename(os.path.dirname(dep_path)))
            base = dep.get("base", os.path.dirname(dep_path))
            appid = dep.get("appid", 0)

            # Check files status
            apk_path = os.path.join(base, "lepton-app/game.apk")
            apk_present = os.path.isfile(apk_path)
            apk_size = os.path.getsize(apk_path) if apk_present else 0

            # Artwork
            art_dir = os.path.join(dep.get("anchor", base), "artwork")
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
                "anchor": dep.get("anchor", base),
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
        dep_path = os.path.join(ANCHOR_DIR, package_name, "deployment.json")
        if os.path.isfile(dep_path):
            try:
                with open(dep_path, "r", encoding="utf-8") as f:
                    return json.load(f)
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
