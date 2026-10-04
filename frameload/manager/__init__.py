"""Game management, uninstallation, storage, and updates modules."""
from .installed import InstalledManager
from .launcher import GameLauncher
from .settings import SettingsManager
from .uninstaller import Uninstaller
from .backup import SaveBackupManager
from .storage import StorageManager, format_size, get_dir_size
from .updates import UpdateManager

__all__ = [
    "InstalledManager",
    "GameLauncher",
    "SettingsManager",
    "Uninstaller",
    "SaveBackupManager",
    "StorageManager",
    "UpdateManager",
    "format_size",
    "get_dir_size",
]
