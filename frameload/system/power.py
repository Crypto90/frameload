"""Keeps the headset awake while FrameLoad downloads, installs or ports, or when the player asks.

An inhibitor taken with systemd-inhibit blocks automatic sleep (and idle) for as long as its child
process runs. The child is `cat` reading a pipe from this process, so the inhibitor also ends if
FrameLoad's server dies. Whether Steam's own sleep timer on the Frame respects logind inhibitors
has not been confirmed on the headset; status() says whether one is held, and taking the headset
off (displays off) is not affected either way.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional


class KeepAwake:
    _lock = threading.Lock()
    _proc: Optional[subprocess.Popen] = None
    _reason = ""
    manual_until = 0.0  # epoch seconds; float("inf") = until switched off

    @classmethod
    def available(cls) -> bool:
        return shutil.which("systemd-inhibit") is not None

    @classmethod
    def held(cls) -> bool:
        return cls._proc is not None and cls._proc.poll() is None

    @classmethod
    def _hold(cls, reason: str) -> None:
        if cls.held():
            cls._reason = reason
            return
        if not cls.available():
            return
        try:
            cls._proc = subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", "--who=FrameLoad", f"--why={reason}", "--mode=block", "cat"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cls._reason = reason
        except OSError:
            cls._proc = None

    @classmethod
    def _release(cls) -> None:
        proc, cls._proc, cls._reason = cls._proc, None, ""
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()  # cat ends at end of input, and the inhibitor with it
            proc.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass

    @classmethod
    def update(cls, busy_reason: str = "") -> None:
        """Holds the inhibitor while there is work (busy_reason) or the manual switch is on."""
        with cls._lock:
            manual = cls.manual_until > time.time()
            if not manual:
                cls.manual_until = 0.0
            reason = busy_reason or ("Kept awake from FrameLoad" if manual else "")
            if reason:
                cls._hold(reason)
            else:
                cls._release()

    @classmethod
    def set_manual(cls, hours: float) -> None:
        """hours > 0: stay awake that long; hours < 0: until switched off; 0: switch off."""
        cls.manual_until = float("inf") if hours < 0 else (time.time() + hours * 3600 if hours > 0 else 0.0)

    @classmethod
    def status(cls) -> Dict[str, Any]:
        manual = cls.manual_until > time.time()
        return {
            "available": cls.available(),
            "held": cls.held(),
            "reason": cls._reason if cls.held() else "",
            "manual": manual,
            "manual_until": None if cls.manual_until == float("inf") or not manual else int(cls.manual_until),
        }


def busy_reason(downloader: Any = None) -> str:
    """What FrameLoad is doing that sleep would interrupt, '' when nothing."""
    from ..installer import porting
    job = porting.PortingJobs.active_id()
    if job:
        current = porting.PortingJobs.get(job) or {}
        return "Porting a game" if current.get("kind") == "port" else "Downloading the porting tools"
    if downloader is not None:
        try:
            for task in downloader.get_all_tasks():
                if task.get("status") in ("downloading", "decompressing", "installing", "queued"):
                    name = (task.get("game") or {}).get("name") or "a game"
                    return f"Installing {name}" if task.get("status") == "installing" else f"Downloading {name}"
        except Exception:
            pass
    return ""
