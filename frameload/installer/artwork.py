"""Steam library artwork for installed apps.

Steam shows PNG or JPEG files in five slots (portrait capsule, landscape banner, wide hero, logo,
square icon). Python's standard library cannot decode or resize images, so at install each slot gets
a real picture (a downloaded cover or icon) or a plain placeholder in the app's colour, and the app's
own launcher icon is taken from its APK. The dashboard, which has image decoders and a canvas, then
draws the placeholders properly from the icon, the cover and the title (see composeArtwork in app.js).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import struct
import time
import urllib.parse
import urllib.request
import zipfile
import zlib
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATA_DIR

THUMB_DIR = os.path.join(DATA_DIR, ".meta/thumbnails")
MISS_TTL = 7 * 24 * 3600
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# name -> (width, height); logo is left out: a full cover used as a logo hides the hero image
SLOTS = {"poster": (600, 900), "banner": (920, 430), "hero": (1920, 620), "icon": (256, 256)}
# Slots the dashboard can draw (it has the image decoders and a canvas that Python's standard
# library lacks): poster, banner, hero and logo from the app's icon or cover and its title.
COMPOSED_SLOTS = ("poster", "banner", "hero", "logo", "icon")
STATE_FILE = "artwork.json"  # slot -> "downloaded" | "generated" | "composed"
ICON_NAMES = re.compile(r"^res/(?:mipmap|drawable)[^/]*/(?:ic_launcher|app_icon|icon|ic_launcher_foreground)[^/]*\.(?:png|webp)$")
MAX_ICON_BYTES = 8 * 1024 * 1024
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


def read_state(output_dir: str) -> Dict[str, str]:
    try:
        with open(os.path.join(output_dir, STATE_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(output_dir: str, changes: Dict[str, str]) -> None:
    state = read_state(output_dir)
    state.update(changes)
    try:
        with open(os.path.join(output_dir, STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
    except OSError:
        pass


def slot_file(output_dir: str, slot: str) -> Optional[str]:
    for ext in (".png", ".jpg", ".webp"):
        path = os.path.join(output_dir, slot + ext)
        if os.path.isfile(path):
            return path
    return None


def steam_icon(output_dir: str) -> str:
    """The icon file a Steam shortcut points at: icon.png or icon.jpg, '' when there is none Steam can
    show. The dashboard always draws the icon as icon.png, so an icon it is about to draw is named by
    that path already (the file it replaces is deleted then)."""
    if icon_redraw(output_dir):
        return os.path.join(output_dir, "icon.png")
    for ext in (".png", ".jpg"):
        path = os.path.join(output_dir, "icon" + ext)
        if os.path.isfile(path):
            return path
    return ""


def _same_content(a: Optional[str], b: Optional[str]) -> bool:
    try:
        if not a or not b or os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def apk_icon_kind(output_dir: str) -> str:
    """'full' for a complete launcher icon taken from the APK, 'foreground' for only the foreground layer
    of an adaptive icon (a glyph without its background), '' when there is no APK icon. Icons taken out
    by versions up to v1.3.6 are looked at once more in the game's APK."""
    if not slot_file(output_dir, "apk_icon"):
        return ""
    kind = read_state(output_dir).get("apk_icon", "")
    if not kind:
        apk = os.path.join(os.path.dirname(output_dir), "lepton-app", "game.apk")
        if os.path.isfile(apk) and extract_apk_icon(apk, output_dir):
            kind = read_state(output_dir).get("apk_icon", "")
        if not kind:
            kind = "unknown"
            write_state(output_dir, {"apk_icon": kind})  # not opened again on every page load
    return kind if kind in ("full", "foreground") else ""


def icon_redraw(output_dir: str) -> str:
    """Why the icon slot is drawn again although it holds a picture: 'webp' (Steam cannot show it),
    'apk' (a copy of the cover, which versions up to v1.3.6 put there although the APK has a complete
    icon of its own), '' when it is kept."""
    icon = slot_file(output_dir, "icon")
    if not icon:
        return ""
    if icon.endswith(".webp"):
        return "webp"
    if (read_state(output_dir).get("icon") == "downloaded" and apk_icon_kind(output_dir) == "full"
            and _same_content(icon, slot_file(output_dir, "poster"))):
        return "apk"
    return ""


def slot_sources(output_dir: str, package_name: str, title: str = "") -> Dict[str, str]:
    """Where each slot's picture came from. Installs from before artwork.json existed are told
    apart by comparing a slot with the plain gradient FrameLoad would have generated for it."""
    state = read_state(output_dir)
    sizes = {slot: [size] for slot, size in SLOTS.items()}
    sizes["banner"].append((460, 215))  # the banner size before v1.3.5
    keys = {k for k in (package_name or title, title) if k}
    changed: Dict[str, str] = {}
    for slot, options in sizes.items():
        path = slot_file(output_dir, slot)
        if slot in state or not path:
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        # Only a PNG of exactly a placeholder's size can be one; anything else is a real picture.
        dims = struct.unpack(">II", data[16:24]) if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 24 else None
        generated = dims in options and any(data == gradient_png(w, h, *app_colours(key))
                                            for (w, h) in options if (w, h) == dims for key in keys)
        if not image_extension(data):
            generated = True  # e.g. an SVG saved as .png by old versions: Steam cannot show it either
        state[slot] = "generated" if generated else "downloaded"
        changed[slot] = state[slot]
    if changed:
        write_state(output_dir, changed)  # decided once; the comparison is not repeated
    return state


def extract_apk_icon(apk_path: str, output_dir: str) -> Optional[str]:
    """Saves the app's own launcher icon from its APK as apk_icon.png/.webp (the sharpest raster
    version; for an adaptive icon its foreground layer). None when the APK has no usable icon."""
    from .axml import parse_axml, read_manifest, resource_files, ResRef
    try:
        with zipfile.ZipFile(apk_path) as zf:
            names = set(zf.namelist())
            arsc = zf.read("resources.arsc") if "resources.arsc" in names else b""
            manifest = read_manifest(zf.read("AndroidManifest.xml"))
            paths: List[str] = []
            if manifest.icon_ref and arsc:
                paths = [p for _, p in resource_files(arsc, manifest.icon_ref)]
            elif manifest.icon_path:
                paths = [manifest.icon_path]

            def raster(candidates: List[str]) -> Optional[str]:
                for p in candidates:
                    if p in names and p.lower().endswith((".png", ".webp", ".jpg")):
                        return p
                return None

            best = raster(paths)
            kind = "full"
            if not best and arsc:
                for xml in (p for p in paths if p.endswith(".xml") and p in names):
                    try:
                        root = parse_axml(zf.read(xml))
                    except ValueError:
                        continue
                    layer = root.find("foreground")
                    drawable = layer.attrs.get("drawable") if layer is not None else None
                    if isinstance(drawable, ResRef):
                        best = raster([p for _, p in resource_files(arsc, int(drawable))])
                    if best:
                        kind = "foreground"  # an adaptive icon's foreground: no background of its own
                        break
            if not best:  # no resource table, or an icon that is only a vector drawing
                matches = [n for n in names if ICON_NAMES.match(n)]
                best = max(matches, key=lambda n: zf.getinfo(n).file_size, default=None)
                if best and "foreground" in best.rsplit("/", 1)[-1]:
                    kind = "foreground"
            if not best or zf.getinfo(best).file_size > MAX_ICON_BYTES:
                return None
            data = zf.read(best)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    ext = image_extension(data)
    if ext not in (".png", ".webp", ".jpg"):
        return None
    os.makedirs(output_dir, exist_ok=True)
    for old in glob.glob(os.path.join(output_dir, "apk_icon.*")):
        try:
            os.remove(old)
        except OSError:
            pass
    path = os.path.join(output_dir, "apk_icon" + ext)
    with open(path, "wb") as f:
        f.write(data)
    write_state(output_dir, {"apk_icon": kind})
    return path


def artwork_info(output_dir: str, package_name: str, title: str = "") -> Dict[str, Any]:
    """What the dashboard needs to draw better artwork: which slots still hold placeholders and
    which pictures it can draw them from."""
    sources = slot_sources(output_dir, package_name, title)
    has = lambda name: bool(slot_file(output_dir, name))  # noqa: E731
    redraw = icon_redraw(output_dir)  # the dashboard draws these as icon.png
    pending = [slot for slot in COMPOSED_SLOTS
               if sources.get(slot) == "generated" or (slot == "logo" and "logo" not in sources)
               or (slot != "logo" and not slot_file(output_dir, slot)) or (slot == "icon" and bool(redraw))]
    top, bottom = app_colours(package_name or title)
    return {
        "pending": pending if os.path.isdir(output_dir) else [],
        "cover": sources.get("poster") == "downloaded",
        "icon": has("apk_icon") or sources.get("icon") == "downloaded",
        # A downloaded WebP icon is converted, not swapped for the APK's; a foreground layer gets a backdrop.
        "icon_from": "icon" if redraw == "webp" else "apk_icon",
        "icon_layer": apk_icon_kind(output_dir) == "foreground",
        "colors": ["#%02x%02x%02x" % top, "#%02x%02x%02x" % bottom],
    }


def save_composed(output_dir: str, slot: str, data: bytes) -> str:
    """Stores one picture drawn by the dashboard. Only PNG and JPEG, and only known slots."""
    if slot not in COMPOSED_SLOTS:
        raise ValueError(f"unknown artwork slot {slot!r}")
    ext = image_extension(data)
    if ext not in (".png", ".jpg"):
        raise ValueError("artwork must be a PNG or JPEG image")
    if slot in ("icon", "logo") and ext != ".png":
        raise ValueError("icons and logos need a PNG (transparency)")
    os.makedirs(output_dir, exist_ok=True)
    for old in glob.glob(os.path.join(output_dir, slot + ".*")):
        try:
            os.remove(old)
        except OSError:
            pass
    path = os.path.join(output_dir, slot + ext)
    with open(path, "wb") as f:
        f.write(data)
    write_state(output_dir, {slot: "composed"})
    return path


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

        state: Dict[str, str] = {}
        if "icon" not in art and icon_url.startswith("https://"):
            icon = _download(icon_url)
            if icon:
                art["icon"] = write("icon", icon)
                state["icon"] = "downloaded"

        if "poster" not in art:
            cover_path = ArtworkManager._local_thumbnail(package_name) or ArtworkManager._fetch_cover_art(
                package_name, title, output_dir)
            if cover_path and os.path.isfile(cover_path):
                with open(cover_path, "rb") as f:
                    cover = f.read()
                if image_extension(cover):
                    art["poster"] = write("poster", cover)
                    state["poster"] = "downloaded"
                    # Without a complete icon of its own (none, or only an adaptive icon's foreground
                    # layer) the cover is the best icon there is. With the APK's launcher icon, the
                    # slot stays a placeholder and the dashboard draws that icon.
                    if "icon" not in art and apk_icon_kind(output_dir) != "full":
                        art["icon"] = write("icon", cover)
                        state["icon"] = "downloaded"

        top, bottom = app_colours(package_name or title)
        for slot, (width, height) in SLOTS.items():
            if slot not in art:
                art[slot] = write(slot, gradient_png(width, height, top, bottom))
                state[slot] = "generated"  # a placeholder until the dashboard draws a real one
        if state:
            write_state(output_dir, state)
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
