"""Catalog and download queue models for FrameLoad."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 ** 3:
        return f"{size / (1024 ** 2):.1f} MB"
    else:
        return f"{size / (1024 ** 3):.2f} GB"


def format_speed(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    else:
        return f"{bps / (1024 ** 2):.1f} MB/s"


@dataclass
class CatalogGame:
    name: str
    release_name: str
    package_name: str
    version_code: str
    last_updated: str
    size_bytes: int
    id: str = ""
    thumbnail_url: str = ""
    kind: str = "quest"  # quest, pcvr, flat
    is_installed: bool = False
    installed_version: str = ""
    download_url: str = ""
    downloads: int = 0
    rating: float = 0.0
    rating_count: int = 0
    notes: str = ""
    version_name: str = ""
    summary: str = ""
    description: str = ""
    categories: List[str] = field(default_factory=list)
    license: str = ""
    anti_features: List[str] = field(default_factory=list)
    sha256: str = ""  # expected checksum of a direct download
    source: str = ""  # catalog the entry came from, e.g. "fdroid"
    update_available: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            h = hashlib.md5((self.release_name + "\n").encode("utf-8")).hexdigest()
            self.id = h

    @property
    def size_formatted(self) -> str:
        return format_bytes(self.size_bytes)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["size_formatted"] = self.size_formatted
        return d


@dataclass
class DownloadTask:
    id: str  # Game MD5 ID
    game: CatalogGame
    status: str = "queued"  # queued, downloading, decompressing, ready_to_install, installing, completed, error, paused
    progress: float = 0.0   # 0.0 to 1.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    eta_seconds: int = 0
    error_message: str = ""
    target_apk: str = ""
    extracted_path: str = ""
    device_id: str = "internal"

    status_detail: str = ""

    @property
    def speed_formatted(self) -> str:
        return format_speed(self.speed_bps)

    @property
    def progress_percent(self) -> int:
        return int(round(self.progress * 100))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "game": self.game.to_dict(),
            "status": self.status,
            "status_detail": self.status_detail,
            "progress": self.progress,
            "progress_percent": self.progress_percent,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "downloaded_formatted": format_bytes(self.downloaded_bytes),
            "total_formatted": format_bytes(self.total_bytes),
            "device_id": self.device_id,
            "speed_bps": self.speed_bps,
            "speed_formatted": self.speed_formatted,
            "eta_seconds": self.eta_seconds,
            "error_message": self.error_message,
        }
