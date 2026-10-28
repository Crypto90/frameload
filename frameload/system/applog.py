"""FrameLoad's own log, for System > FrameLoad Log: what the server printed, why it last stopped or restarted.

The service (frameload.service, install.sh) logs to the user journal; systemd adds its own lines about the unit
("Main process exited, code=killed", "Failed with result 'oom-kill'"). A FrameLoad started without the service
(run.sh --daemon, install.sh's fallback) writes DATA_DIR/server.log instead. The kernel's OOM-killer lines say
whether the system took memory back from it. Everything passes sessions.redact like a session report.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List

from ..config import DATA_DIR

SERVER_LOG = os.path.join(DATA_DIR, "server.log")
MAX_LINES = 600
MAX_BYTES = 256 * 1024
# systemd's own lines about the unit: starts, stops and why.
LIFECYCLE_RE = re.compile(r"Started |Stopped |Stopping |Main process exited|Failed with result|oom|Killed|"
                          r"Scheduled restart|Consumed .* CPU time|frameload\.service: ")
OOM_RE = re.compile(r"Out of memory|oom-kill|Killed process|oom_reaper", re.I)


def _env() -> Dict[str, str]:
    env = dict(os.environ)
    run = f"/run/user/{os.getuid()}"
    env.setdefault("XDG_RUNTIME_DIR", run)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={run}/bus")
    return env


def _run(cmd: List[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=_env())
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def journal(lines: int = MAX_LINES) -> List[str]:
    text = _run(["journalctl", "--user", "-u", "frameload.service", "-n", str(lines), "--no-pager",
                 "-o", "short-iso"])
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("-- ")]


def server_log(lines: int = MAX_LINES) -> List[str]:
    try:
        with open(SERVER_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - MAX_BYTES))
            return f.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:
        return []


def kernel_oom() -> List[str]:
    """The kernel's OOM-killer lines since boot (readable without privileges on SteamOS, else none)."""
    return [ln for ln in _run(["journalctl", "-k", "-b", "--no-pager", "-o", "short-iso", "-n", "4000"]).splitlines()
            if OOM_RE.search(ln)][-20:]


def unit_state() -> Dict[str, str]:
    """systemd's view of the service: how its last run ended, how often it was restarted, since when it runs."""
    text = _run(["systemctl", "--user", "show", "frameload.service", "-p",
                 "Result,NRestarts,ExecMainStartTimestamp,ExecMainStatus,ActiveState"])
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def read() -> Dict[str, Any]:
    from ..manager.sessions import redact

    log = journal()
    source = "journal"
    if not log:
        log, source = server_log(), "server.log"
    lifecycle = [ln for ln in log if LIFECYCLE_RE.search(ln) and ("systemd[" in ln or source != "journal")][-30:]
    return {
        "source": source if log else "",
        "unit": unit_state(),
        "lifecycle": [redact(ln) for ln in lifecycle],
        "oom": [redact(ln) for ln in kernel_oom()],
        "lines": [redact(ln) for ln in log],
    }
