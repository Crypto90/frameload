"""SteamVR's per-game refresh rate, set before Lepton starts a game.

The Frame's OpenXR runtime only offers the panel's current rate: a game's xrRequestDisplayRefreshRateFB for any
other rate is refused (XR_ERROR_DISPLAY_REFRESH_RATE_UNSUPPORTED_FB, -1000101000), and so is FrameBridge's
refresh_rate setting, which goes the same way. SteamVR picks the mode from its per-application setting
`steam.app.<appid>` / `preferredRefreshRate` when the game's session starts, so launch.sh sets that first
(FramePort's PLAYBOOK: Jurassic World Aftermath then ran at 90.2 fps).

The setting goes through OpenVR's IVRSettings in SteamVR's own libopenvr_api.so, as a utility application: that
never starts SteamVR, and SteamVR keeps what it is told (editing steamvr.vrsettings while it runs is lost).

launch.sh runs `python3 -m frameload.system.steamvr_settings <app_dir> <appid>`; the rate comes from
<app_dir>/.refresh_rate, which tuning.py writes (0 = the game's own choice: a key FrameLoad set is removed, a
key it never set is left alone).
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

OPENVR_LIBS = ("/opt/steamvr/bin/linuxarm64/libopenvr_api.so", "/opt/steamvr/bin/linux64/libopenvr_api.so")
VR_APP_UTILITY = 4
SETTINGS_INTERFACE = b"FnTable:IVRSettings_003"
# openvr_capi.h VR_IVRSettings_FnTable slots
GET_ERROR_NAME, SET_FLOAT, GET_FLOAT, REMOVE_KEY = 0, 3, 7, 10
TABLE_SIZE = 11
KEY = b"preferredRefreshRate"
RATE_FILE = ".refresh_rate"
MARKER = ".refresh_rate_set"  # FrameLoad set the key: only then does "game's choice" remove it
# The rates the Frame's panel offers (DRM modes and Steam Link's list in vrserver.txt).
PANEL_RATES = (72, 80, 90, 96, 108, 120, 144)


def snap_rate(rate: float) -> int:
    """The panel rate nearest to what a game asked for (a game asking 89.9 Hz means 90)."""
    return min(PANEL_RATES, key=lambda r: abs(r - rate)) if rate > 0 else 0


class SteamVRSettings:
    """IVRSettings of the running SteamVR; open() returns None when SteamVR is not running."""

    def __init__(self, vr, ct, table):
        self.vr, self.ct, self.table = vr, ct, table

    @classmethod
    def open(cls) -> Optional["SteamVRSettings"]:
        import ctypes

        lib = next((p for p in OPENVR_LIBS if os.path.isfile(p)), None)
        if lib is None:
            return None
        vr = ctypes.CDLL(lib)
        vr.VR_InitInternal2.restype = ctypes.c_uint32
        vr.VR_InitInternal2.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_char_p]
        vr.VR_GetGenericInterface.restype = ctypes.c_void_p
        vr.VR_GetGenericInterface.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        vr.VR_ShutdownInternal.restype = None
        err = ctypes.c_int(0)
        vr.VR_InitInternal2(ctypes.byref(err), VR_APP_UTILITY, None)
        if err.value:
            return None
        ptr = vr.VR_GetGenericInterface(SETTINGS_INTERFACE, ctypes.byref(err))
        if not ptr:
            vr.VR_ShutdownInternal()
            return None
        return cls(vr, ctypes, (ctypes.c_void_p * TABLE_SIZE).from_address(ptr))

    def _check(self, err) -> None:
        if err.value:
            name = self.ct.CFUNCTYPE(self.ct.c_char_p, self.ct.c_int)(self.table[GET_ERROR_NAME])(err.value)
            raise OSError((name or b"SteamVR settings error").decode())

    def set_refresh_rate(self, appid: int, rate: float) -> None:
        ct = self.ct
        err = ct.c_int(0)
        section = f"steam.app.{int(appid)}".encode()
        if rate > 0:
            ct.CFUNCTYPE(None, ct.c_char_p, ct.c_char_p, ct.c_float, ct.POINTER(ct.c_int))(
                self.table[SET_FLOAT])(section, KEY, float(rate), ct.byref(err))
        else:
            ct.CFUNCTYPE(None, ct.c_char_p, ct.c_char_p, ct.POINTER(ct.c_int))(
                self.table[REMOVE_KEY])(section, KEY, ct.byref(err))
        self._check(err)

    def refresh_rate(self, appid: int) -> float:
        ct = self.ct
        err = ct.c_int(0)
        value = ct.CFUNCTYPE(ct.c_float, ct.c_char_p, ct.c_char_p, ct.POINTER(ct.c_int))(
            self.table[GET_FLOAT])(f"steam.app.{int(appid)}".encode(), KEY, ct.byref(err))
        return float(value) if not err.value else 0.0

    def close(self) -> None:
        self.vr.VR_ShutdownInternal()


def read_rate(app_dir: str) -> Optional[float]:
    """The rate tuning.py chose for this game; None when it chose nothing (no file)."""
    try:
        with open(os.path.join(app_dir, RATE_FILE), encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return None


def write_rate(app_dir: str, rate: float) -> None:
    path = os.path.join(app_dir, RATE_FILE)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(f"{int(rate)}\n")
        os.replace(path + ".tmp", path)
    except OSError as e:
        print(f"[FrameLoad] Could not save the refresh rate in {app_dir}: {e}")


def apply(app_dir: str, appid: int, opener=SteamVRSettings.open) -> str:
    """Sets (or clears) SteamVR's preferred rate for this game. Returns one line for refresh-rate.log."""
    rate = read_rate(app_dir)
    marker = os.path.join(app_dir, MARKER)
    if rate is None or not appid:
        return "nothing to set"
    if rate <= 0 and not os.path.exists(marker):
        return "game's choice; SteamVR's own setting left alone"
    if rate > 0 and not 60 <= rate <= 144:
        return f"invalid rate {rate}"
    vr = opener()
    if vr is None:
        return "SteamVR is not running; the panel stays at its current rate"
    try:
        vr.set_refresh_rate(appid, rate)
        if rate > 0:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(f"{int(rate)}\n")
            return f"steam.app.{appid} preferredRefreshRate = {int(rate)} Hz"
        os.remove(marker)
        return f"steam.app.{appid} preferredRefreshRate removed (game's choice)"
    except OSError as e:
        return f"error: {e}"
    finally:
        vr.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python3 -m frameload.system.steamvr_settings <app_dir> <appid>")
    print(time.strftime("%H:%M:%S"), apply(sys.argv[1], int(sys.argv[2] or 0)))
