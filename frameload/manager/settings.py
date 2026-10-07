"""Game runtime settings manager for Steam Frame."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from ..config import ANCHOR_DIR
from ..installer.apk_patcher import ApkPatcher
from .installed import InstalledManager


from .tuning import TuningManager


class SettingsManager:
    @staticmethod
    def update_settings(package_name: str, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Updates framebridge, hardware spoofing, and runtime settings for an installed game."""
        return TuningManager.save_game_tuning(package_name, new_settings)
