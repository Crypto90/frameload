"""Talking to Steam's own interface on the headset, and closing SteamVR's dashboard when a game starts.

When a Lepton game submits its first VR frame, Steam opens its "Resume game" menu on top of it and
the player has to dismiss it before the game is in front. SteamOS starts Steam with its CEF
debugging port open on 127.0.0.1:8080; Steam's shared JavaScript context there offers
`SteamClient.OpenVR.VROverlay.IsDashboardVisible()` and `HideDashboard()`.

The approach (first-frame markers in launch.log, never closing a dashboard the player opened
themselves) is FramePort's, which its author verified on the headset
(github.com/spoopyghosty0/frameport, GPL-3.0, agent `_dashboard_worker`).

Run by a game's launch.sh:  python3 -m frameload.system.steam_ui <launch.log> <launcher pid>
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from typing import Any, Callable, Optional, Tuple

DEVTOOLS = ("127.0.0.1", 8080)
# FrameBridge logs these when the game hands over its first image.
FIRST_FRAME_MARKERS = (b"FrameBridge: new layer:", b"FrameBridge: pacing:")
# SteamVR's interface logs a dashboard opened with the controller's button with this word.
USER_DASHBOARD_MARKER = b"toggle_dashboard_action"


def _steam_ui_log() -> str:
    for base in ("~/.steam/steam", "~/.local/share/Steam"):
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
                     evaluate: Callable[[str], Any] = steam_js, say: Callable[[str], None] = print) -> int:
    """Waits for the game's first VR frame, then hides Steam's menu each time it appears for `window`
    seconds. Stops for good when the player opens the dashboard with the controller, and when the
    launcher ends. Returns how often the dashboard was hidden."""
    ui_log = ui_log or _steam_ui_log()
    _, ui_pos = _user_opened_dashboard(ui_log, None)

    deadline, pos, tail = time.time() + wait_start, 0, b""
    started = False
    while time.time() < deadline and _alive(parent_pid):
        try:
            with open(launch_log, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos += len(chunk)
            text = tail + chunk
            if any(marker in text for marker in FIRST_FRAME_MARKERS):
                started = True
                break
            tail = text[-64:]  # a marker split across two reads
        except OSError:
            pass
        time.sleep(poll)
    if not started:
        say("no VR frames logged; dashboard left as it is")
        return 0

    say(f"{time.strftime('%H:%M:%S')} first VR frame")
    hidden, end = 0, time.time() + window
    while time.time() < end and hidden < max_hides and _alive(parent_pid):
        opened, ui_pos = _user_opened_dashboard(ui_log, ui_pos)
        if opened:  # the player wants the dashboard: never close it on them
            say(f"{time.strftime('%H:%M:%S')} dashboard opened with the controller: leaving it to the player")
            break
        try:
            if evaluate("SteamClient.OpenVR.VROverlay.IsDashboardVisible()"):
                evaluate("SteamClient.OpenVR.VROverlay.HideDashboard()")
                hidden += 1
                say(f"{time.strftime('%H:%M:%S')} dashboard hidden")
        except Exception as exc:  # no devtools port, Steam restarting: leave it
            say(f"steam ui: {exc}")
            break
        time.sleep(poll)
    return hidden


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        dashboard_worker(sys.argv[1], sys.argv[2])
