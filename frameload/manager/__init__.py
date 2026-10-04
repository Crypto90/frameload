"""Game management, uninstallation, and storage modules."""
from .installed import InstalledManager
from .launcher import GameLauncher
from .settings import SettingsManager
from .uninstaller import Uninstaller
from .backup import SaveBackupManager
from .storage import StorageManager, format_size, get_dir_size

__all__ = [
    "InstalledManager",
    "GameLauncher",
    "SettingsManager",
    "Uninstaller",
    "SaveBackupManager",
    "StorageManager",
    "format_size",
    "get_dir_size",
]
