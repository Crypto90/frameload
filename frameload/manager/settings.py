"""Game runtime settings manager for Steam Frame."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from ..config import ANCHOR_DIR
from ..installer.apk_patcher import ApkPatcher
from .installed import InstalledManager


class SettingsManager:
    @staticmethod
    def update_settings(package_name: str, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Updates framebridge and runtime settings for an installed game."""
        dep_path = os.path.join(ANCHOR_DIR, package_name, "deployment.json")
        if not os.path.isfile(dep_path):
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        with open(dep_path, "r", encoding="utf-8") as f:
            dep = json.load(f)

        current_settings = dep.get("settings", {})
        current_settings.update(new_settings)
        dep["settings"] = current_settings

        base = dep.get("base", os.path.join(ANCHOR_DIR, package_name))
        settings_conf = os.path.join(base, "settings.conf")
        framebridge_conf = os.path.join(base, "lepton-data/external/Android/data", package_name, "files/framebridge.conf")

        ApkPatcher.generate_settings_conf(current_settings, settings_conf)
        if os.path.isdir(os.path.dirname(framebridge_conf)):
            ApkPatcher.generate_settings_conf(current_settings, framebridge_conf)

        # Update deployment.json
        with open(dep_path, "w", encoding="utf-8") as f:
            json.dump(dep, f, indent=2)

        return current_settings
