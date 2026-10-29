"""CPU, memory, temperature and GPU readings for the dashboard, read from /proc and /sys.

Everything here is a handful of small file reads, cheap enough to sample every couple of
seconds. On the Steam Frame (SteamOS 0.4.x, kernel 6.18) the GPU clock is the devfreq device
3d00000.gpu and the thermal zones are typed cpu*, gpuss*, ddr*, max1720x (battery); FramePort's
monitor reads the same sources. Missing files (another machine, a container) give None.

A game's own GPU time comes from the DRM fdinfo of its processes (`drm-engine-gpu: <ns> ns`), which
FramePort documents as readable by the headset's user for Lepton games (docs/FRAME_RUNTIME.md).
"""
from __future__ import annotations

import glob
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

PROC = "/proc"
SYS = "/sys"
# zone type prefix -> group shown on the dashboard; the hottest zone of a group is reported
TEMP_GROUPS = (("cpu", ("cpu",)), ("gpu", ("gpu",)), ("memory", ("ddr",)), ("battery", ("max1720x", "battery")))

_lock = threading.Lock()
_cpu_prev: Optional[Tuple[int, int, float]] = None  # (total jiffies, idle jiffies, time)
_zones: Optional[Tuple[float, list]] = None  # (time listed, [(group, temp path)])


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _cpu_times(proc: str = PROC) -> Optional[Tuple[int, int]]:
    line = _read(os.path.join(proc, "stat")).split("\n", 1)[0].split()
    if len(line) < 5 or line[0] != "cpu":
        return None
    values = [int(v) for v in line[1:9] if v.isdigit()]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    return total, idle


def cpu_percent(proc: str = PROC) -> Optional[float]:
    """Busy share of all cores since the previous call (the first call measures 0.2 s)."""
    global _cpu_prev
    now_times = _cpu_times(proc)
    if now_times is None:
        return None
    with _lock:
        prev = _cpu_prev
        if prev is None or time.time() - prev[2] > 30:
            time.sleep(0.2)
            prev = (*now_times, time.time())
            now_times = _cpu_times(proc) or now_times
        _cpu_prev = (*now_times, time.time())
    total = now_times[0] - prev[0]
    idle = now_times[1] - prev[1]
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (total - idle) / total)), 1)


def memory(proc: str = PROC) -> Optional[Dict[str, int]]:
    info: Dict[str, int] = {}
    for line in _read(os.path.join(proc, "meminfo")).splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            info[name] = int(parts[0]) * 1024
    if "MemTotal" not in info:
        return None
    total = info["MemTotal"]
    available = info.get("MemAvailable", info.get("MemFree", 0))
    swap_total = info.get("SwapTotal", 0)
    swap_used = swap_total - info.get("SwapFree", swap_total)
    return {"total": total, "available": available, "used": total - available,
            "swap_total": swap_total, "swap_used": max(0, swap_used)}


def memory_pressure(proc: str = PROC) -> Optional[Dict[str, float]]:
    """Share of the last 10 s in which tasks waited for memory ('some') or all did ('full')."""
    out: Dict[str, float] = {}
    for line in _read(os.path.join(proc, "pressure", "memory")).splitlines():
        parts = line.split()
        if parts and parts[0] in ("some", "full"):
            for field in parts[1:]:
                if field.startswith("avg10="):
                    try:
                        out[parts[0]] = float(field[6:])
                    except ValueError:
                        pass
    return out or None


def _thermal_zones(sys_root: str = SYS) -> list:
    global _zones
    with _lock:
        if _zones is not None and time.time() - _zones[0] < 300 and sys_root == SYS:
            return _zones[1]
    zones = []
    for zone in sorted(glob.glob(os.path.join(sys_root, "class", "thermal", "thermal_zone*"))):
        kind = _read(os.path.join(zone, "type")).strip().lower()
        for group, prefixes in TEMP_GROUPS:
            if kind.startswith(prefixes):
                zones.append((group, os.path.join(zone, "temp")))
                break
    if sys_root == SYS:
        with _lock:
            _zones = (time.time(), zones)
    return zones


def temperatures(sys_root: str = SYS) -> Dict[str, float]:
    hottest: Dict[str, float] = {}
    for group, path in _thermal_zones(sys_root):
        raw = _read(path).strip()
        try:
            value = int(raw) / 1000.0
        except ValueError:
            continue
        if -40 < value < 150 and value > hottest.get(group, -999):
            hottest[group] = round(value, 1)
    return hottest


def gpu(sys_root: str = SYS) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for dev in sorted(glob.glob(os.path.join(sys_root, "class", "devfreq", "*"))):
        name = os.path.basename(dev).lower()
        if "gpu" in name or "kgsl" in name:
            try:
                out["mhz"] = int(_read(os.path.join(dev, "cur_freq")).strip()) // 1000000
                out["max_mhz"] = int(_read(os.path.join(dev, "max_freq")).strip()) // 1000000
            except ValueError:
                pass
            break
    busy = _read(os.path.join(sys_root, "class", "kgsl", "kgsl-3d0", "gpu_busy_percentage")).strip().rstrip("%")
    if busy.isdigit():
        out["busy"] = int(busy)
    return out


def app_pids(package: str, proc: str = PROC) -> List[int]:
    """Processes of an Android app running in a Lepton container, as the host sees them. The kernel keeps
    15 characters of a process name (Android's is the package), the full name is in cmdline; an app's
    extra processes are named <package>:<name>."""
    names = {package[-15:], package[:15]}
    pids = []
    try:
        entries = os.listdir(proc)
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        if _read(os.path.join(proc, entry, "comm")).strip() not in names:
            continue
        first = _read(os.path.join(proc, entry, "cmdline")).split("\0", 1)[0]
        if first == package or first.startswith(package + ":"):
            pids.append(int(entry))
    return sorted(pids)


def render_fds(pid: int, proc: str = PROC) -> List[str]:
    """File descriptors of a process that are a GPU device: their fdinfo carries per-engine busy time."""
    fdinfo = os.path.join(proc, str(pid), "fdinfo")
    try:
        fds = os.listdir(fdinfo)
    except OSError:
        return []
    return [fd for fd in sorted(fds) if "drm-engine-gpu:" in _read(os.path.join(fdinfo, fd))]


def gpu_time_ns(fds: Dict[int, List[str]], proc: str = PROC) -> Optional[int]:
    """GPU time used so far by these processes ({pid: [fd, ...]}), in ns; None when none could be read.
    A device opened once and duplicated shows one client id in several fds and is counted once."""
    total, seen, read_any = 0, set(), False
    for pid, numbers in fds.items():
        for fd in numbers:
            text = _read(os.path.join(proc, str(pid), "fdinfo", fd))
            busy, client = None, None
            for line in text.splitlines():
                name, _, value = line.partition(":")
                if name == "drm-engine-gpu":
                    try:
                        busy = int(value.split()[0])
                    except (IndexError, ValueError):
                        busy = None
                elif name == "drm-client-id":
                    client = value.strip()
            if busy is None:
                continue
            read_any = True
            key = client if client is not None else (pid, fd)
            if key in seen:
                continue
            seen.add(key)
            total += busy
    return total if read_any else None


UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}


def game_memory(fds: Dict[int, List[str]], proc: str = PROC) -> Dict[str, Optional[int]]:
    """Memory of a game's processes ({pid: [render fd, ...]}): "rss", what they hold in RAM (VmRSS), and "gpu",
    the GPU buffers their render devices hold (DRM fdinfo drm-resident-memory, else drm-total-memory; each client
    once). GPU buffers live in the same RAM on the Frame, but RSS does not show all of them, so a leak of either
    kind is told apart. None for what could not be read."""
    rss, read_rss = 0, False
    for pid in fds:
        for line in _read(os.path.join(proc, str(pid), "status")).splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    rss += int(parts[1]) * 1024
                    read_rss = True
    gpu, read_gpu, seen = 0, False, set()
    for pid, numbers in fds.items():
        for fd in numbers:
            values: Dict[str, int] = {}
            client = None
            for line in _read(os.path.join(proc, str(pid), "fdinfo", fd)).splitlines():
                name, _, value = line.partition(":")
                parts = value.split()
                if name == "drm-client-id":
                    client = value.strip()
                elif name in ("drm-resident-memory", "drm-total-memory") and parts and parts[0].isdigit():
                    values[name] = int(parts[0]) * UNITS.get(parts[1] if len(parts) > 1 else "B", 1)
            amount = values.get("drm-resident-memory", values.get("drm-total-memory"))
            key = client if client is not None else (pid, fd)
            if amount is None or key in seen:
                continue
            seen.add(key)
            gpu += amount
            read_gpu = True
    return {"rss": rss if read_rss else None, "gpu": gpu if read_gpu else None}


def boot_time(proc: str = PROC) -> Optional[int]:
    """When the system booted (unix time), from /proc/stat."""
    for line in _read(os.path.join(proc, "stat")).splitlines():
        if line.startswith("btime "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def snapshot() -> Dict[str, Any]:
    load = _read(os.path.join(PROC, "loadavg")).split()
    return {
        "time": time.time(),
        "cpu_percent": cpu_percent(),
        "cores": os.cpu_count() or 0,
        "load1": float(load[0]) if load else None,
        "memory": memory(),
        "pressure": memory_pressure(),
        "temps": temperatures(),
        "gpu": gpu(),
    }
