"""Live view: what the headset shows, with its sound, played in a browser on a paired device (the /live page).

The picture is SteamVR's headset view (the v4l2loopback webcam "SteamVR", see screenshot.py), the sound the monitor of
the Frame's default output (what the headset plays). One ffmpeg turns both into fragmented MP4 (H.264 + AAC) for every
viewer at once: through the Frame's hardware encoder when FramePort's fp_venc helper is there (FrameLoad's own
FramePort install has it; about 3 % of a core), else x264 (about a core at 720p, at nice 10 so the game comes first).
The settings and their reasons are FramePort's (install/livestream.py, measured on the Frame).

FrameLoad keeps the init segment and the fragments since the last keyframe, so a viewer who joins later starts at a
keyframe. The stream stops a few seconds after its last viewer leaves.
"""
from __future__ import annotations

import os
import queue
import shutil
import signal
import struct
import subprocess
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..config import DATA_DIR

SAMPLE_NON_SYNC = 0x10000  # ISO/IEC 14496-12 sample_is_non_sync_sample
QUALITY = {"480p": (480, "1500k", 2_500_000), "720p": (720, "3M", 5_000_000), "1080p": (1080, "6M", 8_000_000)}
DEFAULT_QUALITY = "720p"
FPS = 30  # software path; the hardware path takes an even share of the panel rate
VIEWER_QUEUE = 240  # fragments (about 24 s) a slow viewer may lag before it is dropped
IDLE_STOP = 8.0  # seconds without viewers before the encoder stops
INFO_PREFIX = "live: "
VENC = os.path.join(DATA_DIR, "bin", "fp_venc")


# --------------------------------------------------------------------------------------------- MP4 boxes
def boxes(data: bytes, start: int = 0, end: Optional[int] = None) -> Iterator[Tuple[str, int, int]]:
    """(type, payload start, end) of each complete box in data[start:end]."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size, header = struct.unpack_from(">Q", data, pos + 8)[0], 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind.decode("latin-1"), pos + header, pos + size
        pos += size


def _child(data: bytes, start: int, end: int, kind: str) -> Optional[Tuple[int, int]]:
    return next(((s, e) for k, s, e in boxes(data, start, end) if k == kind), None)


def video_track(init: bytes) -> Optional[int]:
    """The video track's ID in an init segment (its handler is 'vide')."""
    moov = _child(init, 0, len(init), "moov")
    for kind, s, e in boxes(init, *moov) if moov else ():
        if kind != "trak":
            continue
        tkhd, mdia = _child(init, s, e, "tkhd"), _child(init, s, e, "mdia")
        hdlr = mdia and _child(init, *mdia, "hdlr")
        if tkhd and hdlr and init[hdlr[0] + 8:hdlr[0] + 12] == b"vide":
            return struct.unpack_from(">I", init, tkhd[0] + (20 if init[tkhd[0]] == 1 else 12))[0]
    return None


def codecs(init: bytes) -> Optional[str]:
    """The MSE codecs value: avc1.PPCCLL from avcC, plus mp4a.40.2 with sound (ffmpeg's aac is AAC-LC)."""
    i = init.find(b"avcC")
    if i < 0 or i + 8 > len(init):
        return None
    out = f"avc1.{init[i + 5]:02x}{init[i + 6]:02x}{init[i + 7]:02x}"
    return out + (", mp4a.40.2" if b"mp4a" in init else "")


def is_keyframe(moof: bytes, track: Optional[int]) -> bool:
    """Whether a movie fragment's video run starts with a sync sample (trun first-sample or sample flags, else tfhd's
    default flags). Unknown: False, so a joining viewer waits for the next one."""
    top = _child(moof, 0, len(moof), "moof")
    for kind, s, e in boxes(moof, *top) if top else ():
        if kind != "traf":
            continue
        default = None
        tfhd = _child(moof, s, e, "tfhd")
        if tfhd:
            p = tfhd[0]
            flags = int.from_bytes(moof[p + 1:p + 4], "big")
            if track is not None and struct.unpack_from(">I", moof, p + 4)[0] != track:
                continue
            p += 8
            for bit, size in ((0x1, 8), (0x2, 4), (0x8, 4), (0x10, 4)):
                p += size if flags & bit else 0
            if flags & 0x20 and p + 4 <= tfhd[1]:
                default = struct.unpack_from(">I", moof, p)[0]
        trun = _child(moof, s, e, "trun")
        if not trun:
            continue
        p = trun[0]
        flags = int.from_bytes(moof[p + 1:p + 4], "big")
        count = struct.unpack_from(">I", moof, p + 4)[0]
        p += 8 + (4 if flags & 0x1 else 0)
        if flags & 0x4:
            return not struct.unpack_from(">I", moof, p)[0] & SAMPLE_NON_SYNC
        if count and flags & 0x400:
            p += (4 if flags & 0x100 else 0) + (4 if flags & 0x200 else 0)
            return not struct.unpack_from(">I", moof, p)[0] & SAMPLE_NON_SYNC
        return default is not None and not default & SAMPLE_NON_SYNC
    return False


class Splitter:
    """Cuts ffmpeg's byte stream into the init segment (ftyp + moov) and fragments (moof + mdat)."""

    def __init__(self) -> None:
        self.buf = b""
        self.head = b""
        self.moof = b""
        self.init_done = False

    def feed(self, data: bytes) -> List[Tuple[str, bytes]]:
        self.buf += data
        out: List[Tuple[str, bytes]] = []
        while len(self.buf) >= 8:
            size, kind = struct.unpack_from(">I4s", self.buf, 0)
            if size == 1:
                if len(self.buf) < 16:
                    break
                size = struct.unpack_from(">Q", self.buf, 8)[0]
            if size < 8 or len(self.buf) < size:
                break
            box, self.buf = self.buf[:size], self.buf[size:]
            if not self.init_done:
                self.head += box
                if kind == b"moov":
                    self.init_done = True
                    out.append(("init", self.head))
            elif kind == b"moof":
                self.moof = box
            elif kind == b"mdat" and self.moof:
                out.append(("fragment", self.moof + box))
                self.moof = b""
        return out


# --------------------------------------------------------------------------------------------- the encoder
def venc() -> Optional[str]:
    """FramePort's fp_venc (the Frame's hardware H.264 encoder), copied out of FrameLoad's FramePort install so it can
    be executed. None without one."""
    from ..installer.framebridge_patch import artifacts_dir
    from ..installer.porting import VENV_DIR

    art = artifacts_dir(VENV_DIR)
    src = os.path.join(art, "linux-arm64-bin", "fp_venc") if art else ""
    if not os.path.isfile(src):
        return VENC if os.access(VENC, os.X_OK) else None
    try:
        if not os.path.isfile(VENC) or os.path.getsize(VENC) != os.path.getsize(src) \
                or os.path.getmtime(VENC) < os.path.getmtime(src):
            os.makedirs(os.path.dirname(VENC), exist_ok=True)
            shutil.copyfile(src, VENC + ".tmp")
            os.chmod(VENC + ".tmp", 0o755)
            os.replace(VENC + ".tmp", VENC)
    except OSError:
        return None
    return VENC


def script(device: str, quality: str, helper: Optional[str]) -> str:
    """The bash script that streams fragmented MP4 to stdout: fp_venc + ffmpeg (sound, packing) or ffmpeg + x264."""
    height, rate, hw_rate = QUALITY.get(quality, QUALITY[DEFAULT_QUALITY])
    scale = f",scale=-2:'min({height},ih)':flags=fast_bilinear"
    venc_args = f'--source "{device}" --bitrate {hw_rate} --peak {int(hw_rate * 1.5)} --height {height}'
    return f"""set -u
export XDG_RUNTIME_DIR=${{XDG_RUNTIME_DIR:-/run/user/$(id -u)}}
audio=(-an)
sink=$(pactl get-default-sink 2>/dev/null)
if [ -n "$sink" ]; then
  audio=(-thread_queue_size 1024 -f pulse -fragment_size 3840 -i "$sink.monitor"
         -map 0:v -map 1:a -af aresample=async=1 -c:a aac -b:a 128k -ac 2 -ar 48000)
  echo "{INFO_PREFIX}sound=$sink" >&2
fi
venc={helper or ''}
info=
[ -n "$venc" ] && [ -x "$venc" ] && info=$("$venc" --probe {venc_args} 2>/dev/null)
hwfps=$(printf %s "$info" | sed -n 's/.*"fps":\\([0-9][0-9]*\\).*/\\1/p')
if [ -n "$hwfps" ]; then
  echo "{INFO_PREFIX}encoder=hardware fps=$hwfps" >&2
  # FramePort's measurements: stamp the raw H.264 on arrival, number it on fp_venc's fps grid, and start the video
  # input 0.25 s back so ffmpeg does not stall it waiting for pulse's late sound.
  exec 3< <(sleep infinity)
  "$venc" {venc_args} --fps "$hwfps" <&3 | nice -n 10 ffmpeg -nostdin -hide_banner -loglevel error \\
    -probesize 32 -analyzeduration 0 -use_wallclock_as_timestamps 1 -itsoffset -0.25 \\
    -f h264 -i pipe:0 "${{audio[@]}}" \\
    -c:v copy -bsf:v "setts=ts=N*(1/$hwfps)/TB:duration=(1/$hwfps)/TB" -shortest \\
    -f mp4 -movflags empty_moov+default_base_moof+frag_keyframe -frag_duration 100000 -
  exit $?
fi
echo "{INFO_PREFIX}encoder=software fps={FPS}" >&2
exec nice -n 10 ffmpeg -nostdin -hide_banner -loglevel error \\
  -thread_queue_size 64 -ts mono2abs -f v4l2 -input_format rgb24 -i "{device}" "${{audio[@]}}" \\
  -vf "fps={FPS}{scale},format=yuv420p" -c:v libx264 -preset ultrafast -tune zerolatency -threads 3 \\
  -g {FPS} -b:v {rate} -maxrate {rate} -bufsize {rate} \\
  -f mp4 -movflags empty_moov+default_base_moof -frag_duration 100000 -
"""


class LiveStream:
    """One encoder for every viewer. subscribe() hands a viewer the init segment, the fragments since the last
    keyframe and a queue of what follows."""

    lock = threading.Lock()
    proc: Optional[subprocess.Popen] = None
    quality = ""
    init = b""
    track: Optional[int] = None
    gop: List[bytes] = []
    viewers: List["queue.Queue[Optional[bytes]]"] = []
    info: Dict[str, str] = {}
    error = ""
    started = 0.0
    sent = 0
    idle_since = 0.0

    @classmethod
    def status(cls) -> Dict[str, Any]:
        running = cls.proc is not None and cls.proc.poll() is None
        return {"running": running, "quality": cls.quality if running else "", "viewers": len(cls.viewers),
                "encoder": cls.info.get("encoder", ""), "sound": bool(cls.info.get("sound")),
                "codecs": codecs(cls.init) if cls.init else None, "error": cls.error,
                "seconds": round(time.time() - cls.started) if running else 0, "bytes": cls.sent,
                "qualities": list(QUALITY), "default_quality": DEFAULT_QUALITY}

    @classmethod
    def start(cls, quality: str) -> None:
        from .screenshot import device

        quality = quality if quality in QUALITY else DEFAULT_QUALITY
        with cls.lock:
            if cls.proc is not None and cls.proc.poll() is None:
                if cls.quality == quality:
                    return
                cls._stop_locked()  # a viewer asked for another quality: everyone gets it
            path = device()
            if not path:
                raise OSError("The headset view (SteamVR's v4l2cam, /dev/video99) is not available.")
            cls.quality, cls.init, cls.track, cls.gop, cls.info, cls.error = quality, b"", None, [], {}, ""
            cls.started, cls.sent, cls.idle_since = time.time(), 0, 0.0
            cls.proc = subprocess.Popen(["bash", "-c", script(path, quality, venc())], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True)
            threading.Thread(target=cls._read, args=(cls.proc,), daemon=True, name="live-read").start()
            threading.Thread(target=cls._errors, args=(cls.proc,), daemon=True, name="live-err").start()
            threading.Thread(target=cls._watch, args=(cls.proc,), daemon=True, name="live-watch").start()

    @classmethod
    def _read(cls, proc: subprocess.Popen) -> None:
        splitter = Splitter()
        while True:
            data = proc.stdout.read1(65536) if proc.stdout else b""  # type: ignore[union-attr]
            if not data:
                break
            for kind, payload in splitter.feed(data):
                with cls.lock:
                    if proc is not cls.proc:
                        return
                    if kind == "init":
                        cls.init, cls.track = payload, video_track(payload)
                        continue
                    if is_keyframe(payload, cls.track):
                        cls.gop = [payload]
                    elif cls.gop:
                        cls.gop.append(payload)
                    cls.sent += len(payload)
                    for q in list(cls.viewers):
                        try:
                            q.put_nowait(payload)
                        except queue.Full:  # too far behind: it reconnects at a keyframe
                            cls.viewers.remove(q)
                            q.put(None)
        with cls.lock:
            if proc is cls.proc:
                for q in cls.viewers:
                    q.put(None)

    @classmethod
    def _errors(cls, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stderr.readline, b"") if proc.stderr else ():  # type: ignore[union-attr]
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith(INFO_PREFIX):
                for part in line[len(INFO_PREFIX):].split():
                    key, _, value = part.partition("=")
                    cls.info[key] = value
            elif line.startswith("fp_venc: stats"):
                cls.info["stats"] = line[len("fp_venc: stats"):].strip()  # every 10 s: not a problem
            elif line:
                cls.error = line[-300:]
                print(f"[FrameLoad] Live view: {line[:300]}")

    @classmethod
    def _watch(cls, proc: subprocess.Popen) -> None:
        """Stops the encoder once nobody has watched for IDLE_STOP seconds."""
        while proc.poll() is None:
            time.sleep(1)
            with cls.lock:
                if proc is not cls.proc:
                    return
                if cls.viewers:
                    cls.idle_since = 0.0
                elif not cls.idle_since:
                    cls.idle_since = time.time()
                elif time.time() - cls.idle_since > IDLE_STOP:
                    cls._stop_locked()
                    return

    @classmethod
    def _stop_locked(cls) -> None:
        proc, cls.proc = cls.proc, None
        for q in cls.viewers:
            q.put(None)
        cls.viewers = []
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass

    @classmethod
    def stop(cls) -> None:
        with cls.lock:
            cls._stop_locked()

    @classmethod
    def subscribe(cls, quality: str, wait: float = 12.0) -> Tuple[bytes, List[bytes], "queue.Queue[Optional[bytes]]"]:
        """Starts the stream if needed and waits for its init segment. Returns (init, fragments since the last
        keyframe, queue of the following ones; None in it = the end)."""
        cls.start(quality)
        deadline = time.time() + wait
        while time.time() < deadline:
            with cls.lock:
                if cls.init and cls.gop:
                    q: "queue.Queue[Optional[bytes]]" = queue.Queue(VIEWER_QUEUE)
                    cls.viewers.append(q)
                    return cls.init, list(cls.gop), q
                if cls.proc is None or cls.proc.poll() is not None:
                    break
            time.sleep(0.1)
        raise OSError(cls.error or "The live view did not start (no picture from the headset view).")

    @classmethod
    def unsubscribe(cls, q: "queue.Queue[Optional[bytes]]") -> None:
        with cls.lock:
            if q in cls.viewers:
                cls.viewers.remove(q)
