"""Steam library artwork for installed apps.

Steam shows PNG or JPEG files in four shapes (portrait capsule, landscape banner, wide hero, square
icon). Without an image library FrameLoad cannot resize a cover, so each slot gets either a real
image in its own format (a downloaded cover or the app's icon) or a generated PNG in the app's colour.
"""
from __future__ import annotations

import hashlib
import os
import struct
import time
import urllib.parse
import urllib.request
import zlib
from typing import Dict, Optional, Tuple

from ..config import DATA_DIR

THUMB_DIR = os.path.join(DATA_DIR, ".meta/thumbnails")
MISS_TTL = 7 * 24 * 3600
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# name -> (width, height); logo is left out: a full cover used as a logo hides the hero image
SLOTS = {"poster": (600, 900), "banner": (460, 215), "hero": (1920, 620), "icon": (256, 256)}
_misses: Dict[str, float] = {}


def image_extension(data: bytes) -> str:
    """'.png', '.jpg' or '.webp' from the file's first bytes, '' for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def app_colours(key: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Two dark, saturated colours that stay the same for one app."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    hue = digest[0] / 255.0

    def rgb(h: float, lightness: float) -> Tuple[int, int, int]:
        def channel(offset: float) -> int:
            t = (h + offset) % 1.0
            value = 6 * t if t < 1 / 6 else 1 if t < 1 / 2 else (2 / 3 - t) * 6 if t < 2 / 3 else 0
            return int(255 * (lightness * 0.35 + value * lightness * 0.65))
        return channel(1 / 3), channel(0), channel(2 / 3)

    return rgb(hue, 0.55), rgb((hue + 0.08) % 1.0, 0.16)


def gradient_png(width: int, height: int, top: Tuple[int, int, int], bottom: Tuple[int, int, int]) -> bytes:
    """A vertical-gradient PNG, encoded with the standard library only."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    rows = bytearray()
    for y in range(height):
        t = y / max(height - 1, 1)
        pixel = bytes(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        rows += b"\x00" + pixel * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


def _download(url: str, timeout: float = 4.0) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_IMAGE_BYTES + 1)
        return data if len(data) <= MAX_IMAGE_BYTES and image_extension(data) else None
    except Exception:
        return None


class ArtworkManager:
    @staticmethod
    def _local_thumbnail(package_name: str) -> Optional[str]:
        if not os.path.isdir(THUMB_DIR):
            return None
        wanted = f"{package_name.lower()}.jpg"
        try:
            for entry in os.listdir(THUMB_DIR):
                if entry.lower() == wanted:
                    return os.path.join(THUMB_DIR, entry)
        except OSError:
            pass
        return None

    @staticmethod
    def ensure_artwork(package_name: str, title: str, output_dir: str, icon_url: str = "") -> Dict[str, str]:
        """Fills output_dir with poster, banner, hero and icon. Existing files are kept."""
        os.makedirs(output_dir, exist_ok=True)

        def existing(slot: str) -> Optional[str]:
            for ext in (".png", ".jpg", ".webp"):
                path = os.path.join(output_dir, slot + ext)
                if os.path.isfile(path):
                    return path
            return None

        def write(slot: str, data: bytes) -> str:
            path = os.path.join(output_dir, slot + (image_extension(data) or ".png"))
            with open(path, "wb") as f:
                f.write(data)
            return path

        art: Dict[str, str] = {slot: path for slot in SLOTS for path in [existing(slot)] if path}

        if "icon" not in art and icon_url.startswith("https://"):
            icon = _download(icon_url)
            if icon:
                art["icon"] = write("icon", icon)

        if "poster" not in art:
            cover_path = ArtworkManager._local_thumbnail(package_name) or ArtworkManager._fetch_cover_art(
                package_name, title, output_dir)
            if cover_path and os.path.isfile(cover_path):
                with open(cover_path, "rb") as f:
                    cover = f.read()
                if image_extension(cover):
                    art["poster"] = write("poster", cover)
                    art.setdefault("icon", write("icon", cover))

        top, bottom = app_colours(package_name or title)
        for slot, (width, height) in SLOTS.items():
            if slot not in art:
                art[slot] = write(slot, gradient_png(width, height, top, bottom))
        return {os.path.basename(path): path for path in art.values()}

    @staticmethod
    def _fetch_cover_art(package_name: str, title: str, output_dir: str) -> Optional[str]:
        """Tries to download a cover from community repositories. Misses are remembered for a week,
        so a package without artwork is not looked up again on every page load."""
        marker = os.path.join(THUMB_DIR, f"{package_name}.miss")
        now = time.time()
        if now - _misses.get(package_name, 0) < MISS_TTL:
            return None
        try:
            if now - os.path.getmtime(marker) < MISS_TTL:
                _misses[package_name] = now
                return None
        except OSError:
            pass

        safe_pkg = urllib.parse.quote(package_name)
        candidates = [
            f"https://raw.githubusercontent.com/Android-XR-Bridge/OVRPort/main/assets/covers/{safe_pkg}.jpg",
            f"https://raw.githubusercontent.com/spoopyghosty0/frameport/main/catalog/artwork/{safe_pkg}/poster.png",
            f"https://vrpirates.wiki/thumbnails/{safe_pkg}.jpg",
        ]
        for url in candidates:
            data = _download(url)
            if data:
                os.makedirs(output_dir, exist_ok=True)
                target_file = os.path.join(output_dir, "cover" + image_extension(data))
                with open(target_file, "wb") as f:
                    f.write(data)
                return target_file

        _misses[package_name] = now
        try:
            os.makedirs(THUMB_DIR, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(str(int(now)))
        except OSError:
            pass
        return None

    @staticmethod
    def _generate_fallback_art(title: str, output_dir: str) -> None:
        """Kept for callers of the old name: writes generated artwork for every slot."""
        ArtworkManager.ensure_artwork("", title, output_dir)
