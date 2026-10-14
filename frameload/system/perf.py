"""CPU, memory, temperature and GPU readings for the dashboard, read from /proc and /sys.

Everything here is a handful of small file reads, cheap enough to sample every couple of
seconds. On the Steam Frame (SteamOS 0.4.x, kernel 6.18) the GPU clock is the devfreq device
3d00000.gpu and the thermal zones are typed cpu*, gpuss*, ddr*, max1720x (battery); FramePort's
monitor reads the same sources. Missing files (another machine, a container) give None.
"""
from __future__ import annotations

import glob
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

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
