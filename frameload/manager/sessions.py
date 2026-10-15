"""What happened to a game's last session: how it ended, why, and a report the player can copy.

launch.sh (layout 7) records the end of every session with the launcher's exit status (.session_end)
and asks Lepton to keep Android's logs after every session (LEPTON_DUMP_LOGCAT=1; Lepton itself only
keeps them when a game ends within 30 s). When a session ends, FrameLoad copies that evidence here,
because the next start erases launch.log and Lepton's log dump, and names the outcome in plain words.
Whoever stops a game leaves a marker first (the player's Stop, the Freeze Guard, a move), so a stop is
not mistaken for a crash: Lepton exits 0 after a quit, a crash and a killed container alike.

The dashboard shows one dialog for an abnormal end (a crash, a hung graphics processor, running out of
memory, a Freeze Guard stop, a game that could not start or closed right away, a headset that
restarted mid-game), also later when the player comes back, until it is dismissed.

The crash patterns and the process filter follow FramePort's triage (github.com/spoopyghosty0/frameport,
GPL-3.0: catalog/triage.yaml, validate/triage.py, agent cmd_session_log). Logcat times are only compared
with each other, never with the host's clock: the container's time zone is not known.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import DATA_DIR, HOME, STEAM_DIR

SESSION_DIR = os.path.join(DATA_DIR, "sessions")
# Outcomes that open the dialog by themselves; the rest are only recorded.
POPUP_OUTCOMES = ("crashed", "gpu_hang", "out_of_memory", "guard_memory", "guard_frozen", "start_failed",
                  "closed_early", "interrupted")
KEEP_SECONDS = 7 * 86400      # older sessions are not judged any more
ALERT_SECONDS = 3 * 86400     # an alert nobody dismissed is offered this long
GUARD_MARK_HOLD = 15          # s a guard's stop marker is not replaced by the stop call it makes itself
LOG_HEAD_LINES = 200
LOG_TAIL_BYTES = 2 << 20
LOG_COPY_MAX = 4 << 20
LOG_READ_MAX = 64 << 20       # a longer launch.log is read from its end
DUMP_TAIL_BYTES = 1 << 20
COPY_MAX_CHARS = 60000        # what Copy Log puts on the clipboard (fits a GitHub issue)
EVIDENCE_LINES = 40
BACKTRACE_LINES = 120
SHOWN_LINES = 400

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOGCAT_RE = re.compile(r"^\s*(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d+)\s+(\d+)\s+(\d+)\s+[VDIWEFAS]\s+(.*?)\s*: ?(.*)$")
# Lines of a long log that are kept from its middle (FramePort's SESSION_KEEP).
KEEP_RE = re.compile(r"FrameBridge|focus|pacing|Fatal signal|FATAL|CRASH|#\d\d pc |Abort message|DEVICE.LOST|"
                     r"AndroidRuntime|vrclient|Start proc|lepton|exited due to signal|lowmemorykiller", re.I)
FATAL_SIGNAL_RE = re.compile(r"Fatal signal (\d+) \((SIG\w+)\)")
FATAL_THREAD_RE = re.compile(r"in tid \d+ \(([^)]*)\)")
FATAL_PROCESS_RE = re.compile(r"pid (\d+) \(([^)]*)\)")
TOMBSTONE_START = "*** *** *** *** *** ***"
TOMBSTONE_PID_RE = re.compile(r"pid: (\d+), tid: \d+, name: (.*?)\s+>>> (\S+) <<<")
TOMBSTONE_SIGNAL_RE = re.compile(r"^\s*signal (\d+) \((SIG\w+)\)")
ABORT_RE = re.compile(r"Abort message: '(.*)'")
FRAME_RE = re.compile(r"#(\d\d) pc [0-9a-fA-F]+\s+(\S+)")
UNITY_CRASH_RE = re.compile(r"CRASH\s*:.*#\d+ pc|^CRASH$")
ZYGOTE_RE = re.compile(r"Process (\d+) exited due to signal (\d+)")
CRASH_SIGNALS = {4: "SIGILL", 5: "SIGTRAP", 6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE", 11: "SIGSEGV", 31: "SIGSYS"}
DEVICE_LOST_RE = re.compile(r"zink.*DEVICE[_ ]LOST|VK_ERROR_DEVICE_LOST", re.I)
KERNEL_GPU_RE = re.compile(r"hangcheck|gpu fault|adreno|kgsl|msm_drm.*(hang|recover)", re.I)
HANG_WORDS_RE = re.compile(r"hang|fault|recover|lockup", re.I)  # a GPU line about a hang, not any driver line
KERNEL_OOM_RE = re.compile(r"Memory cgroup out of memory|Out of memory|oom-kill|Killed process", re.I)
KERNEL_PANIC_RE = re.compile(r"panic|watchdog", re.I)
QUIT_RE = re.compile(r"System\.exit called|xrRequestExitSession|RequestExit|Application\.Quit|focus: session ending")
MUTEX_ABORT_RE = re.compile(r"pthread_mutex_lock called on a destroyed mutex")
SIGTERM_RE = re.compile(r"Signal SIG(?:TERM|INT) received")
FRAME_SEEN_RE = re.compile(r"FrameBridge: (?:pacing:|new layer:)")
DUMP_DIR_RE = re.compile(r"Dumping logcat to (\S+)")
LEPTON_VERSION_RE = re.compile(r"Lepton (\S+) \(rootfs (\S+)\) starting up")
# launchlog findings that mean the game never really started.
START_FAILURES = ("The APK has no launcher activity", "Lepton could not read the APK", "podman ran out of kernel keyrings",
                  "Android refused to install the APK", "The game's files were not found", "Lepton was not found",
                  "The game asks for OpenXR 1.1", "The game needs Meta's runtime", "The container stopped early")
# Where a crash happened, by the library of the backtrace's first frame that says something.
LIBRARY_PLACES = (
    (("libgallium_dri", "freedreno", "zink", "mesa"), "the headset's graphics driver"),
    (("libopenxr_loader", "libframe_settings", "vrclient"), "the VR runtime connection (OpenXR/FrameBridge)"),
    (("libil2cpp", "libunity"), "the game's Unity code"),
    (("libue4", "libunreal"), "the game's Unreal code"),
    (("libovrplugin", "libvrapi", "libovrplatform"), "Meta's Quest libraries (the game may need porting)"),
)
GENERIC_LIBRARIES = ("libc.so", "libm.so", "libdl.so", "linker", "linker64", "libart.so", "libbase.so", "liblog.so",
                     "libc++.so", "libc++_shared.so", "libutils.so")
GENERIC_HOSTS = ("localhost", "steamdeck", "steamos", "steamframe")

_lock = threading.RLock()
_marker_lock = threading.Lock()  # stop markers: never held while evidence is copied


# --------------------------------------------------------------------------- storage
def _record_path(pkg: str) -> str:
    return os.path.join(SESSION_DIR, f"{pkg}.json")


def _marker_path(pkg: str) -> str:
    return os.path.join(SESSION_DIR, f"{pkg}.stop.json")


def _evidence_dir(pkg: str) -> str:
    return os.path.join(SESSION_DIR, pkg)


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _records_since() -> float:
    """When FrameLoad started keeping session records (made on first use). Sessions that ended before
    are recorded as seen: an update must not greet the player with old crashes."""
    stamp = os.path.join(SESSION_DIR, ".created")
    try:
        with open(stamp, "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        pass
    os.makedirs(SESSION_DIR, exist_ok=True)
    now = time.time()
    try:
        with open(stamp, "x", encoding="utf-8") as f:
            f.write(f"{now}\n")
    except FileExistsError:  # made meanwhile by another thread
        return _records_since()
    except OSError:
        pass
    return now


def _read_text(path: str, limit: int = 0) -> str:
    """A text file, or its last `limit` bytes, without colour codes and carriage returns."""
    try:
        with open(path, "rb") as f:
            if limit:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - limit))
            data = f.read()
    except OSError:
        return ""
    return ANSI_RE.sub("", data.decode("utf-8", "replace")).replace("\r", "")


def _int_file(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(float(f.read().strip() or 0)) or None
    except (OSError, ValueError):
        return None


def load(pkg: str) -> Optional[Dict[str, Any]]:
    record = _read_json(_record_path(pkg))
    if not isinstance(record, dict):
        return None
    record["muted"] = pkg in _muted()
    return record


def _muted() -> set:
    data = _read_json(os.path.join(SESSION_DIR, "muted.json"))
    return set(data) if isinstance(data, list) else set()


def summary(pkg: str) -> Optional[Dict[str, Any]]:
    """What the library needs: whether a game's last session ended abnormally."""
    record = _read_json(_record_path(pkg))
    if not isinstance(record, dict):
        return None
    return {"outcome": record.get("outcome"), "end": record.get("end"), "popup": bool(record.get("popup")),
            "abnormal": record.get("outcome") in POPUP_OUTCOMES, "headline": record.get("headline", "")}


def _dialog_on() -> bool:
    """The Freeze Guard card's "Show what happened" switch: sessions ended while it was off never pop up."""
    try:
        from .guard import FreezeGuard
        return bool(FreezeGuard.settings().get("report_crashes", True))
    except Exception:
        return True


def forget(pkg: str) -> None:
    """Removes everything kept about a game (it was uninstalled)."""
    with _lock:
        for path in (_record_path(pkg), _marker_path(pkg)):
            try:
                os.remove(path)
            except OSError:
                pass
        shutil.rmtree(_evidence_dir(pkg), ignore_errors=True)
        muted = _muted()
        if pkg in muted:
            _write_json(os.path.join(SESSION_DIR, "muted.json"), sorted(muted - {pkg}))


# --------------------------------------------------------------------------- stop markers
def mark_stop(pkg: str, by: str, kind: str = "", message: str = "", now: Optional[float] = None) -> bool:
    """Notes who is about to stop a game: "player", "guard" or "frameload". The guard stops games through
    the same call as the player's Stop, so a player marker does not replace a guard marker that is
    seconds old. Returns whether the marker was written."""
    now = time.time() if now is None else now
    if not by:
        return False
    with _marker_lock:
        if by == "player":
            old = _read_json(_marker_path(pkg))
            if isinstance(old, dict) and old.get("by") == "guard" and 0 <= now - float(old.get("time", 0)) < GUARD_MARK_HOLD:
                return False
        try:
            _write_json(_marker_path(pkg), {"by": by, "kind": kind, "message": message, "time": now})
        except OSError:
            return False
    return True


def clear_stop(pkg: str) -> None:
    """Withdraws a stop marker, for a stop that did not happen."""
    try:
        os.remove(_marker_path(pkg))
    except OSError:
        pass


# --------------------------------------------------------------------------- when a session ran
def _plays_log(anchor: str) -> Optional[Tuple[int, Optional[int]]]:
    """The newest session in FramePort's <anchor>/plays.log ("start <unix>" / "end <unix>" lines)."""
    text = _read_text(os.path.join(anchor, "plays.log"), 8192)
    start = end = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        if parts[0] == "start":
            start, end = int(parts[1]), None
        elif parts[0] == "end" and start is not None and int(parts[1]) >= start:
            end = int(parts[1])
    return (start, end) if start else None


def read_end(dep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The newest finished session: {start, end, rc, source}. rc is only known from .session_end."""
    base = dep.get("base") or dep.get("anchor") or ""
    anchor = dep.get("anchor") or base
    found: List[Dict[str, Any]] = []
    try:
        with open(os.path.join(base, ".session_end"), "r", encoding="utf-8") as f:
            parts = f.read().split()
        if len(parts) == 3 and all(p.lstrip("-").isdigit() for p in parts):
            found.append({"start": int(parts[0]), "end": int(parts[1]), "rc": int(parts[2]), "source": ".session_end"})
    except OSError:
        pass
    last = None
    for line in _read_text(os.path.join(base, ".playtime"), 8192).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and int(parts[1]) >= int(parts[0]):
            last = (int(parts[0]), int(parts[1]))
    if last:
        found.append({"start": last[0], "end": last[1], "rc": None, "source": ".playtime"})
    play = _plays_log(anchor)
    if play and play[1]:
        found.append({"start": play[0], "end": play[1], "rc": None, "source": "plays.log"})
    if not found:
        return None
    # The newest end; for the same session .session_end (listed first) wins, as it knows the exit status.
    return max(found, key=lambda s: (s["end"], s["rc"] is not None))


def current_start(dep: Dict[str, Any]) -> Optional[int]:
    """When the game was started last, by FrameLoad's launcher (.last_played) or FramePort's (plays.log)."""
    base = dep.get("base") or dep.get("anchor") or ""
    starts = [_int_file(os.path.join(base, ".last_played"))]
    play = _plays_log(dep.get("anchor") or base)
    starts.append(play[0] if play else None)
    starts = [s for s in starts if s]
    return max(starts) if starts else None


# --------------------------------------------------------------------------- evidence
def kernel_lines(since: float, until: Optional[float] = None, previous_boot: bool = False) -> List[str]:
    """Kernel lines about GPU hangs and out-of-memory kills from a session (or, with previous_boot, from
    before the last restart, with panics). Empty when the journal cannot be read."""
    cmd = ["journalctl", "-k", "-q", "--no-pager", "-o", "short-unix"]
    if previous_boot:
        cmd += ["-b", "-1", "-p", "warning"]
    else:
        cmd += ["--since", f"@{int(since)}"] + (["--until", f"@{int(until)}"] if until else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, errors="replace").stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    keep = [ln for ln in out.splitlines() if KERNEL_GPU_RE.search(ln) or KERNEL_OOM_RE.search(ln)
            or (previous_boot and KERNEL_PANIC_RE.search(ln))]
    return keep[-200:]


def gpu_hang_lines(lines: Iterable[str]) -> List[str]:
    """Kernel lines that say the graphics processor hung or faulted (FramePort's kernel GPU pattern)."""
    return [ln for ln in lines if KERNEL_GPU_RE.search(ln) and HANG_WORDS_RE.search(ln)]


def _copy_launch_log(src: str, dst: str) -> bool:
    """launch.log cut to at most 4 MB: its first lines, its last 2 MB whole, and from the middle only the
    lines about frames, focus and crashes (FramePort's slice_session_log)."""
    try:
        size = os.path.getsize(src)
    except OSError:
        return False
    if size <= LOG_COPY_MAX:
        text = _read_text(src)
    else:
        try:
            with open(src, "rb") as f:
                head = [f.readline() for _ in range(LOG_HEAD_LINES)]
                middle_from = max(f.tell(), size - LOG_READ_MAX)
                tail_from = size - LOG_TAIL_BYTES
                f.seek(middle_from)
                if middle_from > sum(len(h) for h in head):
                    f.readline()  # started inside a line
                budget, kept = LOG_COPY_MAX - LOG_TAIL_BYTES - 64 * 1024, []
                while f.tell() < tail_from:
                    line = f.readline()
                    if not line:
                        break
                    if KEEP_RE.search(line.decode("utf-8", "replace")):
                        budget -= len(line)
                        if budget < 0:
                            break
                        kept.append(line)
                f.seek(tail_from)
                f.readline()
                tail = f.read()
        except OSError:
            return False
        note = (f"[FrameLoad: this log had {size} bytes; from its middle only {len(kept)} lines about frames, "
                f"focus and crashes are kept]\n").encode()
        raw = b"".join(head) + note + b"".join(kept) + tail
        text = ANSI_RE.sub("", raw.decode("utf-8", "replace")).replace("\r", "")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def _dump_dirs(log_text: str, appid: Any) -> List[str]:
    """Where Lepton wrote this session's logcat dump: the folder it named, or the usual places."""
    found = DUMP_DIR_RE.findall(log_text)
    dirs = [found[-1]] if found else []
    for logs in (os.path.join(STEAM_DIR, "logs"), os.path.join(HOME, ".local/share/Steam/logs"),
                 os.path.join(HOME, ".steam/steam/logs")):
        path = os.path.join(logs, "lepton-logcats", f"steamlaunch-{appid}")
        if path not in dirs:
            dirs.append(path)
    return dirs


def _logcat(line: str) -> Optional[Tuple[float, str, str, str]]:
    """(time in s, pid, tag, message) of a logcat threadtime line; None for Lepton's own lines."""
    m = LOGCAT_RE.match(line)
    if not m:
        return None
    month, day, hour, minute, second, frac, pid, _tid, tag, message = m.groups()
    try:
        stamp = datetime.datetime(2000, int(month), int(day), int(hour), int(minute), int(second)).timestamp()
    except ValueError:
        stamp = 0.0
    return stamp + float("0." + frac), pid, tag, message


def game_pids(pkg: str, *sources: Sequence[str]) -> set:
    """Container pids of the game: from ActivityManager's "Start proc <pid>:<pkg>/" and FrameBridge's lines."""
    start = re.compile(r"Start proc (\d+):" + re.escape(pkg) + r"(?::[^/\s]*)?/")
    pids = set()
    for lines in sources:
        for line in lines:
            m = start.search(line)
            if m:
                pids.add(m.group(1))
            elif "FrameBridge" in line:
                fields = _logcat(line)
                if fields:
                    pids.add(fields[1])
    return pids


def game_lines(lines: Sequence[str], pids: set) -> List[str]:
    """The game's own logcat lines plus Lepton's. Without known pids the mirror was already filtered
    to the game (Lepton passes --pid), so every line counts."""
    if not pids:
        return list(lines)
    out = []
    for line in lines:
        fields = _logcat(line)
        if fields is None or fields[1] in pids:
            out.append(line)
    return out


def _is_app(name: str, pkg: str) -> bool:
    return name == pkg or name.startswith(pkg + ":") or name in (pkg[-15:], pkg[:15])


def _library(frames: Sequence[str]) -> str:
    """The library a backtrace points at: the first frame in a known place, else the first that is not libc."""
    libs = []
    for line in frames:
        m = FRAME_RE.search(line)
        if m:
            libs.append(os.path.basename(m.group(2)))
    for lib in libs:
        if any(key in lib.lower() for keys, _ in LIBRARY_PLACES for key in keys):
            return lib
    for lib in libs:
        if lib not in GENERIC_LIBRARIES:
            return lib
    return libs[0] if libs else ""


def _place(library: str) -> str:
    low = library.lower()
    for keys, place in LIBRARY_PLACES:
        if any(key in low for key in keys):
            return place
    return ""


def _tombstones(lines: Sequence[str], pkg: str) -> List[Dict[str, Any]]:
    """crash_dump's reports (the DEBUG lines of logcat's crash buffer) about this app."""
    blocks: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        fields = _logcat(line)
        message = fields[3] if fields else line
        if TOMBSTONE_START in message:
            current = {"process": "", "thread": "", "signal": "", "abort": "", "frames": [], "lines": [line],
                       "time": fields[0] if fields else None}
            blocks.append(current)
            continue
        if current is None:
            continue
        m = TOMBSTONE_PID_RE.search(message)
        if m:
            current["thread"], current["process"] = m.group(2), m.group(3)
            current["lines"].append(line)
            continue
        m = TOMBSTONE_SIGNAL_RE.search(message)
        if m and not current["signal"]:
            current["signal"] = m.group(2)
            current["lines"].append(line)
            continue
        m = ABORT_RE.search(message)
        if m:
            current["abort"] = m.group(1)
            current["lines"].append(line)
            continue
        if FRAME_RE.search(message):
            current["frames"].append(line)
    return [b for b in blocks if _is_app(b["process"], pkg)]


def _duration(seconds: float) -> str:
    total = int(max(0, seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def _find_crash(pkg: str, lines: Sequence[str], crash: Sequence[str], system: Sequence[str],
                pids: set, tombstone_file: bool) -> Optional[Dict[str, Any]]:
    """The first sign that the game crashed, or None."""
    found: List[Dict[str, Any]] = []
    combined = list(lines) + list(crash)
    for index, line in enumerate(combined):
        fields = _logcat(line)
        message = fields[3] if fields else line
        m = FATAL_SIGNAL_RE.search(message)
        if m:
            proc = FATAL_PROCESS_RE.search(message)
            if proc:  # libc names the crashing process: trust that over the line's pid
                mine = _is_app(proc.group(2), pkg) or proc.group(1) in pids
            else:
                mine = not pids or (fields is not None and fields[1] in pids)
            if mine:
                thread = FATAL_THREAD_RE.search(message)
                found.append({"kind": "native", "signal": m.group(2), "thread": thread.group(1) if thread else "",
                              "line": line, "time": fields[0] if fields else None, "index": index})
            continue
        if "FATAL EXCEPTION" in message:
            # AndroidRuntime's lines that follow: "Process: <pkg>, PID: n", the exception, "at ..." and "Caused by:".
            block = [line] + [b for b in combined[index + 1:index + 80]
                              if not _logcat(b) or _logcat(b)[2].strip() == "AndroidRuntime"][:60]
            if any(f"Process: {pkg}" in b for b in block[:3]):
                exception = next(((_logcat(b) or (0, "", "", b))[3].strip() for b in block[2:3]), "")
                causes = [i for i, b in enumerate(block) if "Caused by:" in b]
                found.append({"kind": "java", "exception": exception.split(":", 1)[0], "line": line,
                              "block": block[:causes[-1] + 1] if causes else block[:12],
                              "time": fields[0] if fields else None, "index": index})
            continue
        if UNITY_CRASH_RE.search(message) and (fields is None or fields[2].strip() == "CRASH") and \
                (not pids or (fields is not None and fields[1] in pids)):
            found.append({"kind": "unity", "line": line, "time": fields[0] if fields else None, "index": index})
    for line in system:
        fields = _logcat(line)
        message = fields[3] if fields else line
        m = ZYGOTE_RE.search(message)
        if m and m.group(1) in pids and int(m.group(2)) in CRASH_SIGNALS:
            found.append({"kind": "zygote", "signal": CRASH_SIGNALS[int(m.group(2))], "line": line,
                          "time": fields[0] if fields else None, "index": None})
    if not found and tombstone_file:
        found.append({"kind": "tombstone_file", "line": "", "time": None, "index": None})
    if not found:
        return None
    first = dict(found[0])
    tombs = _tombstones(crash, pkg) or _tombstones(lines, pkg)
    if tombs:
        tomb = tombs[0]
        first["signal"] = first.get("signal") or tomb["signal"]
        first["thread"] = first.get("thread") or tomb["thread"]
        first["abort"] = tomb["abort"]
        first["frames"] = tomb["frames"]
        first["tomb_lines"] = tomb["lines"]
    else:
        first["frames"] = [ln for ln in list(lines) if FRAME_RE.search(ln) and
                           (first["kind"] == "unity" or "DEBUG" in ln or "CRASH" in ln)][:16]
    return first


def _shutdown_crash(crash: Dict[str, Any], lines: Sequence[str]) -> bool:
    """A crash right after the game asked to quit, or vrclient's destroyed-mutex abort, is part of a
    normal exit (FramePort CLAUDE.md, known false alarms)."""
    if MUTEX_ABORT_RE.search(crash.get("abort", "") or "") or MUTEX_ABORT_RE.search(crash.get("line", "")):
        return True
    for index, line in enumerate(lines):
        if not QUIT_RE.search(line):
            continue
        fields = _logcat(line)
        if crash.get("time") is not None and fields:
            if 0 <= crash["time"] - fields[0] <= 10:
                return True
        elif crash.get("index") is not None and index <= crash["index"]:
            return True
    return False


def classify(pkg: str, title: str, lines: Sequence[str], crash: Sequence[str] = (), system: Sequence[str] = (),
             kernel: Sequence[str] = (), rc: Optional[int] = None, start: float = 0, end: float = 0,
             marker: Optional[Dict[str, Any]] = None, is_vr: bool = True, guard_state: Optional[Dict[str, Any]] = None,
             tombstone_file: bool = False, launch_error: str = "", interrupted: bool = False) -> Dict[str, Any]:
    """How a session ended: {outcome, popup, headline, cause, advice, evidence, findings}."""
    from . import launchlog

    t = title or pkg
    duration = max(0, end - start) if end and start else 0
    lines = [ANSI_RE.sub("", ln).replace("\r", "") for ln in lines]
    pids = game_pids(pkg, lines, system)
    own = game_lines(lines, pids)
    findings = launchlog.diagnose(own + ([launch_error] if launch_error else []))
    guard_state = guard_state or {}
    after = f", {_duration(duration)} after it started" if duration else ""
    out: Dict[str, Any] = {"findings": findings, "evidence": [], "cause": "", "advice": ""}

    def done(outcome: str, headline: str, cause: str = "", advice: str = "", evidence: Iterable[str] = ()) -> Dict[str, Any]:
        out.update(outcome=outcome, headline=headline, cause=cause, advice=advice,
                   evidence=[ln for ln in evidence if ln][:EVIDENCE_LINES], popup=outcome in POPUP_OUTCOMES)
        return out

    gpu_kernel = gpu_hang_lines(kernel)
    if interrupted:
        cause = "The headset restarted, or lost power, while the game was running."
        if gpu_kernel:
            cause += " Its log from before the restart shows that the graphics processor hung."
        return done("interrupted", f"{t} was running when the headset restarted", cause,
                    "If its picture froze before the restart, the game probably hung the graphics processor. "
                    "Copy the log and include it when you ask for help.", gpu_kernel or own[-12:])

    in_window = marker and (start - 2 <= float(marker.get("time", 0)) <= (end or time.time()) + 10)
    if in_window and marker.get("by") == "guard":
        message = marker.get("message") or ""
        cause = f"Freeze Guard stopped it{after}. {message}".strip()
        if marker.get("kind") == "frozen":
            if gpu_kernel:
                cause += " The headset's graphics processor hung while it ran."
            return done("guard_frozen", f"{t} froze and was stopped", cause,
                        "How long Freeze Guard waits is set under System > Freeze Guard.", gpu_kernel)
        return done("guard_memory", f"Freeze Guard stopped {t}", cause,
                    "Freeze Guard ended the game before the whole headset stopped responding. Restarting the "
                    "headset before playing again gives the game all memory.")
    if in_window and marker.get("by") == "player":
        return done("stopped_player", f"You stopped {t}", f"It was stopped with Stop{after}.")
    if in_window and marker.get("by") == "frameload":
        return done("stopped_frameload", f"FrameLoad stopped {t}", marker.get("message") or "FrameLoad stopped it.")
    if rc in (130, 143) or any(SIGTERM_RE.search(ln) for ln in own):
        return done("closed_by_steam", f"{t} was closed by Steam",
                    f"Its launcher was told to end it (Steam's Exit game, or the system){after}.")

    failed = [f for f in findings if f["title"] in START_FAILURES]
    if launch_error or failed or (rc is not None and rc != 0):
        cause = launch_error or (failed[0]["title"] if failed else f"Its launcher ended with error code {rc}.")
        advice = failed[0]["advice"] if failed else "The launch log says more about why."
        evidence = [ln for ln in own if any(re.search(p, ln) for p, _, title_, _a in launchlog.RULES
                                            if title_ in START_FAILURES)][-8:] or own[-12:]
        return done("start_failed", f"{t} could not start", cause, advice, evidence)

    comm = {pkg[-15:], pkg[:15]}
    oom = [ln for ln in kernel if KERNEL_OOM_RE.search(ln) and any(c in ln for c in comm)]
    lmk = re.compile(r"lowmemorykiller.*'" + re.escape(pkg) + "'")
    oom += [ln for ln in list(lines) + list(system) if lmk.search(ln)]
    if oom:
        return done("out_of_memory", f"{t} ran out of memory",
                    f"The system ended it because the headset ran out of memory{after}.",
                    "The game needed more memory than the headset could give it. Restart the headset before playing "
                    "it again, so it starts with all memory free.", oom)

    lost = [ln for ln in own if DEVICE_LOST_RE.search(ln)]
    if lost or gpu_kernel:
        return done("gpu_hang", f"{t} stopped: the graphics processor hung",
                    f"The headset's graphics processor stopped responding while the game drew{after}.",
                    "This usually happens at the same point in a game, and only a fix for that game helps. Copy the "
                    "log and include it when you ask for help.", (lost + gpu_kernel))

    crash = _find_crash(pkg, own, crash, system, pids, tombstone_file)
    if crash and _shutdown_crash(crash, own):
        out["quit_note"] = "it crashed while closing"
        return done("quit", f"{t} closed", f"It closed{after}; it crashed while closing, which games often do.")
    if crash:
        library = _library(crash.get("frames", []))
        place = _place(library)
        if crash["kind"] == "java":
            cause = f"It stopped with an error in its Java code ({crash.get('exception') or 'an exception'}){after}."
            evidence = crash.get("block", [crash["line"]])
        elif crash["kind"] == "tombstone_file":
            cause = f"It crashed{after}. The game caught the crash itself and left a crash report in its files."
            evidence = own[-12:]
        else:
            what = f"It crashed ({crash['signal']})" if crash.get("signal") else "It crashed"
            if crash.get("thread"):
                what += f" in thread {crash['thread']}"
            if place:
                what += f", inside {place} ({library})"
            elif library:
                what += f", in {library}"
            cause = what + after + "."
            if crash.get("abort"):
                cause += f" The game stopped itself after an internal error: {crash['abort'][:200]}"
            evidence = ([crash["line"]] if crash.get("line") else []) + \
                       [ln for ln in crash.get("tomb_lines", []) if ABORT_RE.search(ln)] + crash.get("frames", [])[:16]
        out.update(signal=crash.get("signal", ""), thread=crash.get("thread", ""), library=library)
        return done("crashed", f"{t} crashed", cause,
                    "If it crashes at the same point again, copy the log and include it when you ask for help.",
                    evidence)

    drew = any(FRAME_SEEN_RE.search(ln) for ln in own) or bool(guard_state.get("drew"))
    if duration and ((is_vr and duration < 60 and not drew) or (not is_vr and duration < 15)):
        return done("closed_early", f"{t} closed right after it started",
                    f"It ended {_duration(duration)} after it started" + (" and never showed a VR picture." if is_vr else "."),
                    "The launch log usually says why. Copy it and include it when you ask for help.", own[-12:])
    return done("quit", f"{t} closed", f"It closed normally{after}.")


# --------------------------------------------------------------------------- recording sessions
def _tombstone_file(dep: Dict[str, Any], pkg: str, since: float) -> bool:
    """Unity catches its own crashes and leaves tombstone_NN in the app's files (FramePort PLAYBOOK)."""
    folder = os.path.join(dep.get("base") or "", "lepton-data/external/Android/data", pkg, "files")
    try:
        return any(os.path.getmtime(p) >= since for p in glob.glob(os.path.join(folder, "tombstone_*")))
    except OSError:
        return False


def finalize(pkg: str, guard_state: Optional[Dict[str, Any]] = None, now: Optional[float] = None,
             quiet: bool = False) -> Optional[Dict[str, Any]]:
    """Records the game's newest finished session if it is not recorded yet. Returns the new record.
    quiet: recorded as already seen (as is every session that ended before FrameLoad kept records)."""
    from .installed import InstalledManager

    now = time.time() if now is None else now
    with _lock:
        dep = InstalledManager.get_game(pkg)
        if not dep:
            return None
        base = dep.get("base") or dep.get("anchor") or ""
        previous = _read_json(_record_path(pkg)) or {}
        session = read_end(dep)
        error_path = os.path.join(base, ".launch_error")
        launch_error = ""
        try:
            error_time = int(os.path.getmtime(error_path))
            if not session or error_time > session["end"]:
                launch_error = _read_text(error_path).strip()[:300] or "Its launcher stopped with an error."
                session = {"start": error_time, "end": error_time, "rc": 1, "source": ".launch_error"}
        except OSError:
            pass
        if not session or session["end"] <= float(previous.get("end") or 0) or now - session["end"] > KEEP_SECONDS:
            return None
        latest = current_start(dep)
        if not launch_error and latest and latest != session["start"]:
            return None  # started again since: the log is the new session's
        return _store(pkg, dep, session, guard_state, now, quiet, launch_error=launch_error)


def _store(pkg: str, dep: Dict[str, Any], session: Dict[str, Any], guard_state: Optional[Dict[str, Any]], now: float,
           quiet: bool, launch_error: str = "", interrupted: bool = False, kernel: Optional[List[str]] = None) -> Dict[str, Any]:
    base = dep.get("base") or dep.get("anchor") or ""
    start, end = session["start"], session["end"]
    quiet = quiet or end < _records_since()
    folder = _evidence_dir(pkg)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    sources = {"launch_log": False, "crash_log": False, "system_log": False, "main_log": False, "kernel": False}

    log = os.path.join(base, "launch.log")
    try:
        fresh = os.path.getmtime(log) >= start - 5  # else no log of this session is left
    except OSError:
        fresh = False
    if fresh and not launch_error:
        sources["launch_log"] = _copy_launch_log(log, os.path.join(folder, "launch.log"))
    lines = _read_text(os.path.join(folder, "launch.log")).splitlines() if sources["launch_log"] else []

    dumps: Dict[str, List[str]] = {}
    for directory in _dump_dirs("\n".join(lines[-4000:]), dep.get("appid")):
        for name, key, limit in (("logcat-crash.log", "crash_log", DUMP_TAIL_BYTES),
                                 ("logcat-system.log", "system_log", DUMP_TAIL_BYTES),
                                 ("logcat-main.log", "main_log", DUMP_TAIL_BYTES)):
            path = os.path.join(directory, name)
            if key in dumps:
                continue
            try:
                if not start - 5 <= os.path.getmtime(path) <= end + 120:
                    continue
            except OSError:
                continue
            text = _read_text(path, limit)
            with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            dumps[key] = text.splitlines()
            sources[key] = True

    if kernel is None:
        kernel = kernel_lines(start, end + 120)
    if kernel:
        with open(os.path.join(folder, "kernel.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(kernel) + "\n")
        sources["kernel"] = True

    marker = _read_json(_marker_path(pkg))
    marker = marker if isinstance(marker, dict) else None
    title = dep.get("title") or pkg
    result = classify(pkg, title, lines, crash=dumps.get("crash_log", []),
                      system=dumps.get("system_log", []) + dumps.get("main_log", []), kernel=kernel,
                      rc=session.get("rc"), start=start, end=end, marker=marker, is_vr=bool(dep.get("is_vr", True)),
                      guard_state=guard_state, tombstone_file=_tombstone_file(dep, pkg, start - 5),
                      launch_error=launch_error, interrupted=interrupted)
    if marker and float(marker.get("time", 0)) <= end + 10:
        clear_stop(pkg)  # used, or older than this session

    lepton = LEPTON_VERSION_RE.search("\n".join(lines[:400]))
    gs = guard_state or {}
    record = {
        "package": pkg, "title": title, "appid": dep.get("appid"), "start": start, "end": end,
        "duration": max(0, end - start), "rc": session.get("rc"), "end_source": session.get("source", ""),
        "outcome": result["outcome"], "popup": result["popup"] and not quiet and _dialog_on(), "headline": result["headline"],
        "cause": result["cause"], "advice": result["advice"], "findings": result["findings"],
        "evidence": result["evidence"], "quit_note": result.get("quit_note", ""),
        "signal": result.get("signal", ""), "thread": result.get("thread", ""), "library": result.get("library", ""),
        "frames": {"fps": gs.get("fps"), "last_frame_age": gs.get("last_frame_age"), "drew": gs.get("drew"),
                   "gpu": gs.get("gpu"), "limit": gs.get("limit", "")},
        "stop": marker if result["outcome"] in ("guard_memory", "guard_frozen", "stopped_player", "stopped_frameload") else None,
        "sources": sources, "lepton": f"{lepton.group(1)} (rootfs {lepton.group(2)})" if lepton else "",
        "kind": "vr" if dep.get("is_vr", True) else "2d", "seen": quiet, "time": now,
    }
    _write_json(_record_path(pkg), record)
    print(f"[FrameLoad] Session of {pkg}: {record['outcome']} ({record['headline']})")
    return record


def record_interrupted(pkg: str, boot: int, now: Optional[float] = None, quiet: bool = False) -> Optional[Dict[str, Any]]:
    """A session that was still running when the headset restarted: started, never ended, and the
    system booted after it started."""
    from .installed import InstalledManager

    now = time.time() if now is None else now
    with _lock:
        dep = InstalledManager.get_game(pkg)
        if not dep:
            return None
        started = current_start(dep)
        ended = read_end(dep)
        previous = _read_json(_record_path(pkg)) or {}
        if not started or now - started > KEEP_SECONDS or boot <= started:
            return None
        if (ended and ended["end"] >= started) or float(previous.get("start") or 0) >= started:
            return None
        session = {"start": started, "end": boot, "rc": None, "source": "boot"}
        return _store(pkg, dep, session, None, now, quiet, interrupted=True,
                      kernel=kernel_lines(0, previous_boot=True))


def sweep(games: Iterable[Dict[str, Any]], live: Iterable[str], now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Records ends the guard did not see (FrameLoad was restarted, or the guard was busy)."""
    live = set(live)
    made = []
    for game in games:
        if game["package"] in live:
            continue
        try:
            record = finalize(game["package"], now=now)
        except Exception as e:  # one broken game must not stop the others
            print(f"[FrameLoad] Could not record the session of {game['package']}: {e}")
            continue
        if record:
            made.append(record)
    return made


def catch_up(games: List[Dict[str, Any]], live: Iterable[str], boot: Optional[int] = None,
             now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Run once when FrameLoad starts: records sessions that ended while it was not running, and sessions
    the headset's restart cut off. The very first time, everything found is recorded as seen."""
    _records_since()
    live = set(live)
    made = []
    for game in games:
        pkg = game["package"]
        if pkg in live:
            continue
        try:
            record = finalize(pkg, now=now)
            if boot:
                record = record_interrupted(pkg, boot, now=now) or record
        except Exception as e:
            print(f"[FrameLoad] Could not record the session of {pkg}: {e}")
            continue
        if record:
            made.append(record)
    return made


def pending(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Sessions to tell the player about: abnormal, not dismissed, not muted, at most 3 days old."""
    now = time.time() if now is None else now
    muted = _muted()
    out = []
    for path in glob.glob(os.path.join(SESSION_DIR, "*.json")):
        if path.endswith(".stop.json") or os.path.basename(path) == "muted.json":
            continue
        record = _read_json(path)
        if not isinstance(record, dict) or not record.get("popup") or record.get("seen"):
            continue
        if record.get("package") in muted or now - float(record.get("end") or 0) > ALERT_SECONDS:
            continue
        out.append({"package": record["package"], "title": record.get("title", ""), "end": record.get("end"),
                    "outcome": record.get("outcome"), "headline": record.get("headline", "")})
    return sorted(out, key=lambda r: r["end"] or 0, reverse=True)


def acknowledge(pkg: str, end: Any = None, mute: Optional[bool] = None) -> bool:
    """The player closed the dialog of the session that ended at `end` (seen), and/or chose Don't Show for
    This Game (mute) or undid that. Without `end`, only a mute changes nothing else."""
    with _lock:
        record = _read_json(_record_path(pkg))
        changed = False
        seen = end is not None or mute is None
        try:
            same = end is None or float(record.get("end") or 0) == float(end)
        except (AttributeError, TypeError, ValueError):
            same = False
        if seen and isinstance(record, dict) and same:
            record["seen"] = True
            _write_json(_record_path(pkg), record)
            changed = True
        if mute is not None:
            muted = _muted()
            muted = muted | {pkg} if mute else muted - {pkg}
            _write_json(os.path.join(SESSION_DIR, "muted.json"), sorted(muted))
            changed = True
        return changed


# --------------------------------------------------------------------------- what the dashboard shows
def _tail_lines(path: str, count: int) -> List[str]:
    return _read_text(path, LOG_TAIL_BYTES).splitlines()[-count:]


def detail(pkg: str, source: str = "session") -> Dict[str, Any]:
    """The dialog's content: the record, the log it came from, and the report for Copy Log."""
    from . import launchlog

    record = load(pkg)
    if source == "session" and record and record.get("sources", {}).get("launch_log"):
        path = os.path.join(_evidence_dir(pkg), "launch.log")
        lines = _tail_lines(path, SHOWN_LINES + 1)
        out = {"package": pkg, "exists": True, "lines": lines[-SHOWN_LINES:], "truncated": len(lines) > SHOWN_LINES,
               "findings": record.get("findings") or [], "session": True}
    else:
        out = dict(launchlog.read_log(pkg), session=False)
    shown = out["lines"]
    out["record"] = record
    out["excerpt"] = (record or {}).get("evidence") or [ln for ln in shown if ln.strip()][-30:] if record else []
    out["copy_text"] = report_text(pkg, source=source)
    return out


def redact(text: str) -> str:
    """Removes what identifies the player: the home folder, the host name, LAN and public addresses,
    hardware addresses, Steam account ids. Based on patterns; game-specific ids can remain."""
    if HOME and len(HOME) > 1:
        text = text.replace(HOME, "~")
    host = socket.gethostname()
    if host and len(host) > 2 and host.lower() not in GENERIC_HOSTS:
        text = re.sub(r"\b" + re.escape(host) + r"\b", "<host>", text)

    def ip(m: "re.Match[str]") -> str:
        parts = [int(p) for p in m.groups()]
        if max(parts) > 255 or parts[0] < 10 or parts[0] == 127:
            return m.group(0)
        return "<ip>"
    text = re.sub(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d)", ip, text)
    text = re.sub(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b", "<mac>", text)
    text = re.sub(r"\b7656119\d{10}\b", "<steamid>", text)
    return re.sub(r"userdata/\d+", "userdata/<id>", text)


def _environment(dep: Dict[str, Any]) -> List[str]:
    import platform

    from .. import __version__
    from ..system import perf
    from ..system.steamos import get_os_release, is_steam_frame
    from .guard import FreezeGuard

    osr = get_os_release()
    lines = [f"FrameLoad {__version__} on {osr.get('NAME', platform.system())} {osr.get('VERSION_ID', '')} "
             f"(build {osr.get('BUILD_ID', '?')}), {platform.machine()}, Steam Frame: {'yes' if is_steam_frame() else 'no'}"]
    mem = perf.memory()
    if mem:
        gib = 1024 ** 3
        lines.append(f"Memory: {mem['total'] / gib:.1f} GB, {mem['available'] / gib:.1f} GB available; "
                     f"swap {mem['swap_used'] / gib:.1f} of {mem['swap_total'] / gib:.1f} GB used")
    try:
        g = FreezeGuard.settings()
        lines.append(f"Freeze Guard: memory watchdog {'on' if g['enabled'] else 'off'}, memory limit "
                     f"{'on' if g['memory_limit'] else 'off'}, stops frozen games {'after ' + str(g['frozen_seconds']) + ' s' if g['stop_frozen'] else 'off (reports them)'}")
    except Exception:
        pass
    conf = _read_text(os.path.join(dep.get("base") or "", "settings.conf"), 8192).strip()
    if conf:
        lines.append("Game settings (settings.conf): " + "; ".join(ln.strip() for ln in conf.splitlines() if ln.strip())[:600])
    return lines


def report_text(pkg: str, full: bool = False, source: str = "session") -> str:
    """The plain-text report Copy Log and Save Log hand out. source "session": the recorded last session
    with its kept evidence; "live": the current launch.log. The copied version stays under 60,000
    characters (the log's oldest lines go first); the saved one (full) has everything that was kept."""
    from . import launchlog
    from .installed import InstalledManager

    dep = InstalledManager.get_game(pkg) or {"package": pkg}
    record = load(pkg)
    if source == "live" and record and record.get("start") != current_start(dep):
        record = None  # the live log is a newer session than the record
    folder = _evidence_dir(pkg)
    use_copy = bool(record and record.get("sources", {}).get("launch_log"))
    log_path = os.path.join(folder, "launch.log") if use_copy else os.path.join(dep.get("base") or "", "launch.log")
    log_lines = _read_text(log_path, 0 if full else LOG_TAIL_BYTES).splitlines()

    title = dep.get("title") or pkg
    kind = "VR" if dep.get("is_vr", True) else "2D"
    compat = (dep.get("compat") or {}).get("label", "")
    head = ["FrameLoad session report", "========================",
            f"Game: {title} ({pkg}) {dep.get('version_name', '')} (code {dep.get('version_code', '?')}), {kind}, "
            f"{dep.get('engine') or 'engine unknown'}",
            f"Compatibility: {compat or 'unknown'}; FrameBridge: {'yes' if dep.get('framebridge') else 'no'}; "
            f"runtime: {dep.get('xr_runtime') or 'unknown'}; installed by {dep.get('installed_by') or 'unknown'}"]
    if record:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.get("end") or 0))
        head += [f"What happened: {record.get('headline', '')}",
                 f"Ended: {when}, after {_duration(record.get('duration') or 0)}",
                 f"Cause: {record.get('cause', '')}"]
        frames = record.get("frames") or {}
        if frames.get("fps") is not None or frames.get("last_frame_age") is not None:
            head.append(f"Frames: {frames.get('fps') or '?'} fps, last new picture "
                        f"{frames.get('last_frame_age') if frames.get('last_frame_age') is not None else '?'} s before the end")
        if frames.get("limit"):
            head.append(f"Memory limit: {frames['limit']}")
        head.append(f"Launcher exit code: {record.get('rc') if record.get('rc') is not None else 'not recorded'}")
        if record.get("stop"):
            stop = record["stop"]
            head.append(f"Stopped by: {stop.get('by')}{' (' + stop['kind'] + ')' if stop.get('kind') else ''}"
                        f"{': ' + stop['message'] if stop.get('message') else ''}")
        if record.get("lepton"):
            head.append(f"Lepton: {record['lepton']}")
    else:
        head.append("What happened: no finished session recorded; this is the current launch log.")
        lepton = LEPTON_VERSION_RE.search("\n".join(log_lines[:400]))
        if lepton:
            head.append(f"Lepton: {lepton.group(1)} (rootfs {lepton.group(2)})")
    head += [""] + _environment(dep)

    findings = (record or {}).get("findings") or launchlog.diagnose(log_lines)
    body = ["", "Findings:"] + [f"- [{f['severity']}] {f['title']}: {f['advice']}" for f in findings]
    backtrace: List[str] = []
    if record and record.get("sources", {}).get("crash_log"):
        crash = _read_text(os.path.join(folder, "logcat-crash.log")).splitlines()
        backtrace = crash if full else ([ln for ln in crash if TOMBSTONE_START in ln or FRAME_RE.search(ln) or
                                         ABORT_RE.search(ln) or FATAL_SIGNAL_RE.search(ln) or ">>> " in ln]
                                        or crash)[:BACKTRACE_LINES]
    elif record and record.get("evidence"):
        backtrace = record["evidence"][:BACKTRACE_LINES]
    if backtrace:
        body += ["", "Crash backtrace:" if record and record.get("outcome") == "crashed" else "Evidence:"] + backtrace
    if full and record:
        for name, label in (("kernel.txt", "Kernel log"), ("logcat-system.log", "Android system log"),
                            ("logcat-main.log", "Android main log")):
            text = _read_text(os.path.join(folder, name)).strip()
            if text:
                body += ["", f"{label}:", text]
    elif record and record.get("sources", {}).get("kernel"):
        body += ["", "Kernel log:"] + _read_text(os.path.join(folder, "kernel.txt")).splitlines()[-20:]

    text = redact("\n".join(head + body))
    label = "Launch log" + (" (kept copy of that session)" if use_copy else "")
    if full:
        return text + f"\n\n{label}:\n" + redact("\n".join(log_lines)) + "\n"
    budget = COPY_MAX_CHARS - len(text) - 200
    tail: List[str] = []
    for line in reversed(log_lines):
        line = redact(line)
        if budget - len(line) - 1 < 0:
            break
        budget -= len(line) + 1
        tail.append(line)
    tail.reverse()
    cut = len(log_lines) - len(tail)
    note = f" (last {len(tail)} lines; {cut} earlier lines are in Save Log)" if cut else ""
    result = text + f"\n\n{label}{note}:\n" + "\n".join(tail) + "\n"
    return result[-COPY_MAX_CHARS:] if len(result) > COPY_MAX_CHARS else result


def save_report(pkg: str, source: str = "session") -> str:
    """Writes the full report to ~/Downloads on the headset and returns its path."""
    folder = os.path.join(HOME, "Downloads")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, report_name(pkg))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report_text(pkg, full=True, source=source))
    return path


def report_name(pkg: str) -> str:
    return f"frameload-{pkg}-{time.strftime('%Y%m%d-%H%M%S')}.txt"
