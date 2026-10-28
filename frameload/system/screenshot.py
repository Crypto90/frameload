"""A picture of what the headset shows, for checking a game without wearing the Frame.

SteamVR's v4l2cam (user unit steamvr-v4l2cam.service, part of the gaming session) copies the compositor's headset
view to a v4l2loopback webcam named "SteamVR", /dev/video99 (1920x1080 RGB24; FramePort's FRAME_RUNTIME.md "Video of
the headset view"). Nothing reads it by default. One frame of it is the screenshot: with the Frame's ffmpeg as a
JPEG, else read here (VIDIOC_G_FMT, one read()) and written as a PNG with the standard library. The picture is black
while the headset sleeps.

Screenshots go to SCREENSHOT_DIR (newest KEEP kept) and are served by /api/system/screenshot.
"""
from __future__ import annotations

import fcntl
import glob
import os
import select
import shutil
import struct
import subprocess
import time
import zlib
from typing import Any, Dict, Optional, Tuple

from ..config import DATA_DIR

DEVICE = "/dev/video99"
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
KEEP = 20
READ_TIMEOUT = 4.0
# linux/videodev2.h (64-bit): struct v4l2_format is 208 bytes, its union at offset 8.
VIDIOC_G_FMT = 0xC0D05604
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
RGB24 = struct.unpack("<I", b"RGB3")[0]
BGR24 = struct.unpack("<I", b"BGR3")[0]


class ScreenshotError(OSError):
    pass


def device() -> Optional[str]:
    """The headset-view webcam: /dev/video99, else any v4l2 device named SteamVR."""
    if os.path.exists(DEVICE):
        return DEVICE
    for name_file in sorted(glob.glob("/sys/class/video4linux/video*/name")):
        try:
            with open(name_file, encoding="utf-8") as f:
                if f.read().strip() == "SteamVR":
                    return "/dev/" + os.path.basename(os.path.dirname(name_file))
        except OSError:
            continue
    return None


def _format(fd: int) -> Tuple[int, int, int, int]:
    """(width, height, bytes per line, pixel format) of the device's capture format."""
    buf = bytearray(208)
    struct.pack_into("<I", buf, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
    fcntl.ioctl(fd, VIDIOC_G_FMT, buf)
    width, height, pixfmt, _field, bpl, _size = struct.unpack_from("<6I", buf, 8)
    return width, height, bpl or width * 3, pixfmt


def png(width: int, height: int, rgb_rows) -> bytes:
    """A PNG of 8-bit RGB rows (each width * 3 bytes), standard library only."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + row for row in rgb_rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _read_frame(path: str, scale: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        width, height, bpl, pixfmt = _format(fd)
        if pixfmt not in (RGB24, BGR24):
            raise ScreenshotError(f"the headset view has an unexpected pixel format {pixfmt:#x}")
        size = bpl * height
        data = b""
        deadline = time.monotonic() + READ_TIMEOUT
        while len(data) < size:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise ScreenshotError("no picture from the headset view (is steamvr-v4l2cam.service running?)")
            try:
                chunk = os.read(fd, size - len(data))
            except BlockingIOError:
                continue
            if not chunk:
                raise ScreenshotError("the headset view ended")
            data += chunk
    finally:
        os.close(fd)
    rows = []
    step = max(1, scale)
    for y in range(0, height, step):
        row = data[y * bpl:y * bpl + width * 3]
        if step > 1:
            row = b"".join(row[x * 3:x * 3 + 3] for x in range(0, width, step))
        if pixfmt == BGR24:
            swapped = bytearray(row)
            swapped[0::3], swapped[2::3] = row[2::3], row[0::3]
            row = bytes(swapped)
        rows.append(row)
    return png((width + step - 1) // step, len(rows), rows)


def _ffmpeg(path: str, out: str, width: int) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "v4l2", "-i", path,
                                 "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", out],
                                capture_output=True, timeout=12)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0


def take(width: int = 1920) -> Dict[str, Any]:
    """Takes a screenshot of the headset view. Returns {path, name, size, time, method}."""
    path = device()
    if not path:
        raise ScreenshotError("The headset view (SteamVR's v4l2cam, /dev/video99) is not available on this system.")
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    width = max(320, min(1920, int(width)))
    out = os.path.join(SCREENSHOT_DIR, f"headset-{stamp}.jpg")
    method = "ffmpeg"
    if not _ffmpeg(path, out, width):
        out = os.path.join(SCREENSHOT_DIR, f"headset-{stamp}.png")
        method = "v4l2"
        data = _read_frame(path, 1920 // width)
        with open(out + ".tmp", "wb") as f:
            f.write(data)
        os.replace(out + ".tmp", out)
    for old in sorted(glob.glob(os.path.join(SCREENSHOT_DIR, "headset-*")))[:-KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    return {"path": out, "name": os.path.basename(out), "size": os.path.getsize(out), "time": time.time(),
            "method": method}


def latest() -> Optional[str]:
    shots = sorted(glob.glob(os.path.join(SCREENSHOT_DIR, "headset-*.*")))
    return shots[-1] if shots else None
