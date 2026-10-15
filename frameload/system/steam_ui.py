"""Talking to Steam's own interface on the headset, and closing SteamVR's dashboard when a game starts.

When a Lepton game submits its first VR frame, Steam opens its "Resume game" menu on top of it and
the player has to dismiss it before the game is in front. SteamOS starts Steam with its CEF
debugging port open on 127.0.0.1:8080; Steam's shared JavaScript context there offers
`SteamClient.OpenVR.VROverlay.IsDashboardVisible()` and `HideDashboard()` (Steam's own Resume is a
HideDashboard).

The approach (first-frame markers in launch.log, never closing a dashboard the player opened
themselves) is FramePort's, which its author verified on the headset
(github.com/spoopyghosty0/frameport, GPL-3.0, agent `_dashboard_worker`).

Run by a game's launch.sh:  python3 -m frameload.system.steam_ui <launch.log> <launcher pid>
It writes what it did to dashboard.log and ends it with one line `result: hidden N`, `no-frames`,
`player`, `keeps-reopening` or `error <message>` (read by manager/launchlog.py).
"""
from __future__ import annotations

import base64
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile
from typing import Any, Callable, Dict, Optional, Tuple

from ..config import CONFIG_FILE, FRAMELOAD_DIR

DEVTOOLS = ("127.0.0.1", 8080)
# FrameBridge logs "new layer:" when the game hands over its first image and "pacing:" every few
# seconds after. launch.log has logcat's threadtime format ("I FrameBridge: new layer: ..."),
# `logcat -v brief` writes "I/FrameBridge( 1234): new layer: ...".
FIRST_FRAME_RE = re.compile(rb"FrameBridge(?:\(\s*\d+\))?\s*:\s*(?:new layer:|pacing:)")
# The libraries that make an APK carry FrameBridge (apk_analysis.FRAMEBRIDGE_LIBS).
FRAMEBRIDGE_LIBS = ("libframe_settings.so", "libopenxr_loader_original.so")
# SteamVR's interface logs a dashboard opened with the controller's button with this word.
USER_DASHBOARD_MARKER = b"toggle_dashboard_action"
# run.sh writes the pid of FrameLoad's window here while it holds window.lock.
WINDOW_PID = os.path.join(FRAMELOAD_DIR, "window.pid")
CONTAINER_PREFIX = "lepton-steamlaunch-"
MENU_LEFT_OPEN = "Steam's menu could not be closed from here. Press the Steam button on your controller."


def _say(line: str) -> None:
    print(line, flush=True)  # dashboard.log is read while the game runs


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _steam_ui_log() -> str:
    from ..config import STEAM_DIR
    for base in (STEAM_DIR, "~/.steam/steam", "~/.local/share/Steam"):
        path = os.path.expanduser(os.path.join(base, "logs/vrwebhelper_systemui.txt"))
        if os.path.exists(path):
            return path
    return os.path.expanduser("~/.local/share/Steam/logs/vrwebhelper_systemui.txt")


def _read_exact(sock: socket.socket, count: int) -> bytes:
    buf = b""
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise ConnectionError("Steam's devtools closed the connection")
        buf += chunk
    return buf


def steam_js(expression: str, timeout: float = 5.0, address: Tuple[str, int] = DEVTOOLS) -> Any:
    """Evaluates JavaScript in Steam's shared context and returns its value (a minimal WebSocket client)."""
    host, port = address
    with urllib.request.urlopen(f"http://{host}:{port}/json", timeout=timeout) as resp:
        targets = json.load(resp)
    url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("title") == "SharedJSContext")
    path = "/" + url.split("://", 1)[1].split("/", 1)[1]

    with socket.create_connection(address, timeout=timeout) as sock:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += _read_exact(sock, 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("Steam's devtools refused the connection")

        payload = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True}}).encode()
        mask = os.urandom(4)
        size = len(payload)
        header = bytes([0x80 | size]) if size < 126 else bytes([0x80 | 126]) + struct.pack(">H", size)
        sock.sendall(b"\x81" + header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

        while True:  # other messages may come first; ours carries id 1
            _, second = _read_exact(sock, 2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", _read_exact(sock, 2))[0]
            elif length == 127:
                length = struct.unpack(">Q", _read_exact(sock, 8))[0]
            message = json.loads(_read_exact(sock, length).decode("utf-8", "replace") or "{}")
            if message.get("id") == 1:
                return ((message.get("result") or {}).get("result") or {}).get("value")


def dashboard_visible(timeout: float = 3.0, evaluate: Optional[Callable[..., Any]] = None) -> Optional[bool]:
    """Whether SteamVR's dashboard (the Steam menu) is open over the game. Only asks, never changes it;
    None when Steam cannot be asked (no devtools port, Steam restarting)."""
    try:
        value = (evaluate or steam_js)("SteamClient.OpenVR.VROverlay.IsDashboardVisible()", timeout=timeout)
    except Exception:
        return None
    return value if isinstance(value, bool) else None


def show_game(evaluate: Callable[[str], Any] = steam_js, settle: float = 1.0) -> Dict[str, Any]:
    """What Show <game> in the dashboard does: closes SteamVR's dashboard (where FrameLoad's own
    window lives) so the running VR game is in front, then checks a moment later that it stayed
    closed. Steam may open it again, for example while FrameLoad is its only running app."""
    try:
        evaluate("SteamClient.OpenVR.VROverlay.HideDashboard()")
    except Exception as exc:  # no devtools port, Steam restarting
        return {"success": False, "visible": None, "error": MENU_LEFT_OPEN, "detail": str(exc)}
    time.sleep(settle)
    visible = dashboard_visible(evaluate=lambda expression, timeout=3.0: evaluate(expression))
    if visible is not False:  # still open, or Steam gave no clear answer
        return {"success": False, "visible": visible, "error": MENU_LEFT_OPEN}
    return {"success": True, "visible": False}


def container_logcat(appid: Any, timeout: float = 5.0) -> bytes:
    """FrameBridge's lines, read straight from the game's container. Lepton copies the game's log into
    launch.log, but that copy can die ("logcat: Unexpected EOF!", "Logcat read failure") or stay
    silent while the game keeps running (FramePort's notes on Lepton 3.0.5). The container is new for
    every start, so nothing from an earlier session can match."""
    try:
        out = subprocess.run(["podman", "exec", f"{CONTAINER_PREFIX}{appid}", "logcat", "-d", "-v", "brief",
                              "-s", "FrameBridge:I"], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):  # no container yet, podman busy
        return b""
    return out.stdout or b""


def carries_framebridge(install_path: str) -> bool:
    """False only for a game whose APK was read and has no FrameBridge: such a game never logs the
    first-frame lines, so asking its container for them every 2 s would only cost CPU while it loads."""
    try:
        apks = [n for n in os.listdir(install_path) if n.lower().endswith(".apk")]
        if len(apks) != 1:
            return True
        with zipfile.ZipFile(os.path.join(install_path, apks[0])) as zf:
            return any(name.rsplit("/", 1)[-1] in FRAMEBRIDGE_LIBS for name in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return True


def close_on_vr_start(config_file: str = CONFIG_FILE) -> bool:
    """The setting "Close FrameLoad's window when a VR game shows its first picture" (off by default)."""
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            ui = (json.load(f) or {}).get("ui") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return ui.get("close_on_vr_start") is True


def close_frameload_window(pid_file: str = WINDOW_PID, proc: str = "/proc") -> bool:
    """Ends FrameLoad's window: its run.sh closes the browser on SIGTERM, and Steam's FrameLoad entry
    ends with it. The server, downloads and Stop keep running; FrameLoad opens again from the Steam
    library. Only a process that is still run.sh is signalled (a pid can be reused)."""
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
            args = f.read().split(b"\0")
    except (OSError, ValueError):
        return False
    if pid <= 1 or not any(os.path.basename(arg) == b"run.sh" for arg in args):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def close_window_if_enabled() -> bool:
    return close_on_vr_start() and close_frameload_window()


def _user_opened_dashboard(ui_log: str, pos: Optional[int]) -> Tuple[bool, Optional[int]]:
    """(opened since pos, new position). A missing log answers no."""
    try:
        with open(ui_log, "rb") as f:
            f.seek(0, 2)
            end = f.tell()
            if pos is None or pos > end:  # first look, or the log was rotated
                return False, end
            f.seek(pos)
            return USER_DASHBOARD_MARKER in f.read(), end
    except OSError:
        return False, pos


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def dashboard_worker(launch_log: str, parent_pid: Any, wait_start: float = 240, window: float = 120,
                     poll: float = 0.5, max_hides: int = 10, ui_log: Optional[str] = None,
                     evaluate: Callable[[str], Any] = steam_js, say: Callable[[str], None] = _say,
                     logcat: Optional[Callable[[], bytes]] = None, logcat_every: float = 2.0,
                     bounce_seconds: float = 15.0, close_window: Optional[Callable[[], bool]] = None) -> int:
    """Waits for the game's first VR frame, then hides Steam's menu each time it appears for `window`
    seconds. Stops for good when the player opens the dashboard with the controller, and when the
    launcher ends. Returns how often the dashboard was hidden.

    logcat: reads FrameBridge's lines from the game's container, asked every `logcat_every` seconds
    while launch.log shows no first frame. close_window: called at the first frame, and again when
    Steam keeps reopening its menu (`max_hides` hides within `bounce_seconds`)."""
    ui_log = ui_log or _steam_ui_log()

    deadline, pos, tail = time.time() + wait_start, 0, b""
    next_logcat = time.time() + logcat_every
    source = ""
    while time.time() < deadline and _alive(parent_pid):
        try:
            with open(launch_log, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos += len(chunk)
            text = tail + chunk
            if FIRST_FRAME_RE.search(text):
                source = "launch.log"
                break
            tail = text[-128:]  # a marker split across two reads
        except OSError:
            pass
        if logcat and time.time() >= next_logcat:
            next_logcat = time.time() + logcat_every
            try:
                found = FIRST_FRAME_RE.search(logcat() or b"")
            except Exception:
                found = None
            if found:
                source = "container"
                break
        time.sleep(poll)
    if not source:
        say("no VR frames logged; dashboard left as it is")
        say("result: no-frames")
        return 0

    say(f"{_now()} first VR frame" + (" (in the game's container log; launch.log has none)" if source == "container" else ""))
    # Presses from before this moment (while Lepton started the game) were not about the game.
    _, ui_pos = _user_opened_dashboard(ui_log, None)
    closed = bool(close_window and close_window())
    if closed:
        say(f"{_now()} closed FrameLoad's window")

    hidden, end, stamps, result = 0, time.time() + window, [], ""
    while time.time() < end and hidden < max_hides and _alive(parent_pid):
        opened, ui_pos = _user_opened_dashboard(ui_log, ui_pos)
        if opened:  # the player wants the dashboard: never close it on them
            say(f"{_now()} dashboard opened with the controller: leaving it to the player")
            result = "player"
            break
        try:
            if evaluate("SteamClient.OpenVR.VROverlay.IsDashboardVisible()"):
                evaluate("SteamClient.OpenVR.VROverlay.HideDashboard()")
                hidden += 1
                stamps.append(time.time())
                say(f"{_now()} dashboard hidden")
        except Exception as exc:  # no devtools port, Steam restarting: leave it
            message = " ".join(str(exc).split()) or type(exc).__name__
            say(f"steam ui: {message}")
            result = f"error {message}"
            break
        time.sleep(poll)

    if not result and hidden >= max_hides and stamps[-1] - stamps[0] <= bounce_seconds:
        # Steam opens it again as fast as it is closed: hiding cannot win against that.
        result = "keeps-reopening"
        say(f"{_now()} the dashboard opened again {hidden} times within {stamps[-1] - stamps[0]:.0f} s")
        if close_window and not closed and close_window():
            say(f"{_now()} closed FrameLoad's window")
            time.sleep(poll * 4)
            try:
                if evaluate("SteamClient.OpenVR.VROverlay.IsDashboardVisible()"):
                    evaluate("SteamClient.OpenVR.VROverlay.HideDashboard()")
                    hidden += 1
                    say(f"{_now()} dashboard hidden")
            except Exception:
                pass
    say(f"result: {result or f'hidden {hidden}'}")
    return hidden


def main(argv: list) -> int:
    if len(argv) < 2:
        return 2
    appid = os.environ.get("SteamAppId", "")
    install = os.environ.get("STEAM_COMPAT_INSTALL_PATH", "")
    logcat = None
    if appid.isdigit() and int(appid) and (not install or carries_framebridge(install)):
        logcat = lambda: container_logcat(appid)  # noqa: E731
    dashboard_worker(argv[0], argv[1], logcat=logcat, close_window=close_window_if_enabled)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
