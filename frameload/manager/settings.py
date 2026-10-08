"""Game runtime settings manager for Steam Frame."""
from __future__ import annotations

from typing import Any, Dict

from .tuning import TuningManager


class SettingsManager:
    @staticmethod
    def update_settings(package_name: str, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Updates the Lepton and FrameBridge settings of an installed game."""
        return TuningManager.save_game_tuning(package_name, new_settings)
