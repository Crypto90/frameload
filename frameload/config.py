"""Configuration management for FrameLoad."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

HOME = os.path.expanduser("~")

def get_steam_dir() -> str:
    """Finds the active Steam directory with userdata folder on SteamOS/Linux."""
    candidates = [
        os.path.join(HOME, ".steam/steam"),
        os.path.join(HOME, ".local/share/Steam"),
        os.path.join(HOME, ".steam/root"),
        os.path.join(HOME, ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
        os.path.join(HOME, ".var/app/com.valvesoftware.Steam/.steam/steam"),
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "userdata")):
            return c
    for c in candidates:
        if os.path.isdir(c):
            return c
    return os.path.join(HOME, ".local/share/Steam")

STEAM_DIR = get_steam_dir()
ANCHOR_DIR = os.path.join(HOME, "Applications/quest-frame")
FRAMELOAD_DIR = os.path.join(HOME, ".local/share/frameload")
CACHE_DIR = os.path.join(FRAMELOAD_DIR, "cache")
DATA_DIR = os.path.join(FRAMELOAD_DIR, "data")
BACKUP_DIR = os.path.join(FRAMELOAD_DIR, "backups")
CONFIG_FILE = os.path.join(FRAMELOAD_DIR, "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "0.0.0.0",
        "port": 5050,
        "auto_open_browser": False,
    },
    "mirrors": {
        "catalog_url": "https://raw.githubusercontent.com/Crypto90/frameload/main/frameload/catalog/bundled_catalog.json",
        "vrp_config_urls": [
            "https://raw.githubusercontent.com/Crypto90/frameload/main/frameload/catalog/vrp-public.json"
        ],
        "custom_mirrors": [],
        "last_updated": 0,
    },
    "download": {
        "max_concurrent": 1,
        "chunk_size_kb": 1024,
        "auto_install_on_download": True,
        "delete_cache_after_install": True,
        "bandwidth_limit_mbps": 0,
    },
    "game_defaults": {
        "refresh_rate": 90,
        "resolution_scale": 1.0,
        "controller_models": True,
        "passthrough": True,
        "msaa": 2,
    },
    "steam": {
        "auto_restart_steam": True,
        "add_grid_artwork": True,
    },
    "storage": {
        "default_device_id": "internal",
        "custom_paths": [],
    }
}


class Config:
    _instance: Config | None = None

    def __init__(self) -> None:
        self._config: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self.ensure_dirs()
        self.load()

    @classmethod
    def get(cls) -> Config:
        if cls._instance is None:
            cls._instance = Config()
        return cls._instance

    def ensure_dirs(self) -> None:
        for path in (FRAMELOAD_DIR, CACHE_DIR, DATA_DIR, BACKUP_DIR, ANCHOR_DIR):
            os.makedirs(path, exist_ok=True)

    def load(self) -> None:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._deep_update(self._config, saved)
            except Exception as e:
                print(f"[FrameLoad] Error loading config: {e}")

    def save(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            print(f"[FrameLoad] Error saving config: {e}")

    def _deep_update(self, target: dict, source: dict) -> None:
        for k, v in source.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                self._deep_update(target[k], v)
            else:
                target[k] = v

    def __getitem__(self, key: str) -> Any:
        return self._config.get(key, {})

    def __setitem__(self, key: str, value: Any) -> None:
        self._config[key] = value
        self.save()

    @property
    def raw(self) -> Dict[str, Any]:
        return self._config
