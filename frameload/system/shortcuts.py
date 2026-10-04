"""Steam non-Steam game shortcuts and grid artwork coordinator."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from ..config import ANCHOR_DIR, HOME, STEAM_DIR
from .steam_vdf import shortcut_appid, vdf_decode, vdf_encode

MAX_VDF_BACKUPS = 5


def get_steam_users() -> List[str]:
    userdata = os.path.join(STEAM_DIR, "userdata")
    if not os.path.isdir(userdata):
        return []
    return sorted(d for d in os.listdir(userdata) if d.isdigit() and d != "0")


def get_active_steam_user() -> Optional[str]:
    loginusers = os.path.join(STEAM_DIR, "config/loginusers.vdf")
    users = get_steam_users()
    if not users:
        return None
    if os.path.isfile(loginusers):
        try:
            with open(loginusers, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            for sid, body in re.findall(r'"(\d{17})"\s*\{([^}]*)\}', text):
                if re.search(r'"MostRecent"\s+"1"', body):
                    # SteamID64 base offset
                    account_id = str(int(sid) - 76561197960265728)
                    if account_id in users:
                        return account_id
        except OSError:
            pass
    return users[0] if users else None


def backup_vdf(vdf_path: str) -> None:
    if not os.path.isfile(vdf_path):
        return
    backup_file = f"{vdf_path}.backup-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(vdf_path, backup_file)
    backups = sorted(glob.glob(f"{vdf_path}.backup-*"))
    if len(backups) > MAX_VDF_BACKUPS:
        for b in backups[:-MAX_VDF_BACKUPS]:
            try:
                os.remove(b)
            except OSError:
                pass


def upsert_shortcut(
    vdf_path: str,
    exe: str,
    title: str,
    start_dir: str,
    icon: str = "",
    tag: str = "FrameLoad VR",
    tags: Optional[List[str]] = None,
    openvr: bool = True,
    launch_options: str = ""
) -> int:
    """Adds or updates a non-Steam shortcut in shortcuts.vdf."""
    data = b""
    if os.path.isfile(vdf_path):
        try:
            with open(vdf_path, "rb") as f:
                data = f.read()
        except OSError:
            pass

    root = vdf_decode(data) if data else {"shortcuts": {}}
    shortcuts = root.setdefault("shortcuts", {})

    target_entry = None
    target_key = None
    for k, v in shortcuts.items():
        if isinstance(v, dict) and v.get("Exe") == exe:
            target_entry = v
            target_key = k
            break

    ident = target_entry.get("appid") if target_entry else shortcut_appid(exe, title)

    if target_entry is None:
        int_keys = [int(k) for k in shortcuts.keys() if k.isdigit()]
        target_key = str(max(int_keys + [-1]) + 1)
        target_entry = {
            "appid": ident,
            "LastPlayTime": 0,
            "tags": {"0": tag}
        }
        shortcuts[target_key] = target_entry

    # Merge tags
    all_tags = [tag]
    if tags:
        all_tags.extend(tags)
    existing_tags = [v for v in (target_entry.get("tags") or {}).values() if isinstance(v, str)]
    merged_tags = list(dict.fromkeys(existing_tags + all_tags))
    target_entry["tags"] = {str(i): t for i, t in enumerate(merged_tags)}

    target_entry.update(
        appname=title,
        Exe=exe,
        StartDir=start_dir,
        icon=icon or target_entry.get("icon", ""),
        ShortcutPath="",
        LaunchOptions=launch_options,
        IsHidden=0,
        AllowDesktopConfig=1,
        AllowOverlay=1,
        OpenVR=1 if openvr else 0,
        Devkit=0,
        DevkitGameID="",
        DevkitOverrideAppID=0,
        FlatpakAppID=""
    )

    backup_vdf(vdf_path)
    os.makedirs(os.path.dirname(vdf_path), exist_ok=True)
    tmp_path = vdf_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(vdf_encode(root))
    os.replace(tmp_path, vdf_path)
    return ident


def remove_shortcut_by_exe(vdf_path: str, exe: str) -> bool:
    """Removes a shortcut matching exe."""
    if not os.path.isfile(vdf_path):
        return False
    try:
        with open(vdf_path, "rb") as f:
            data = f.read()
    except OSError:
        return False

    root = vdf_decode(data)
    shortcuts = root.get("shortcuts", {})
    keep = [v for v in shortcuts.values() if not (isinstance(v, dict) and v.get("Exe") == exe)]

    if len(keep) == len(shortcuts):
        return False

    root["shortcuts"] = {str(i): v for i, v in enumerate(keep)}
    backup_vdf(vdf_path)
    tmp = vdf_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(vdf_encode(root))
    os.replace(tmp, vdf_path)
    return True


def remove_shortcut_by_title_or_exe(vdf_path: str, title: str = "", exe_substring: str = "") -> List[int]:
    """Removes shortcuts matching title or containing exe_substring, returning removed appids."""
    if not os.path.isfile(vdf_path):
        return []
    try:
        with open(vdf_path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    root = vdf_decode(data)
    shortcuts = root.get("shortcuts", {})
    keep = []
    removed_appids: List[int] = []
    for v in shortcuts.values():
        if isinstance(v, dict):
            appname = str(v.get("appname", ""))
            exe = str(v.get("Exe", ""))
            match_title = bool(title and appname and appname.strip().lower() == title.strip().lower())
            match_exe = bool(exe_substring and exe and exe_substring.lower() in exe.lower())
            if match_title or match_exe:
                appid = v.get("appid")
                if appid is not None:
                    try:
                        removed_appids.append(int(appid))
                    except (ValueError, TypeError):
                        pass
                continue
        keep.append(v)

    if len(keep) == len(shortcuts):
        return []

    root["shortcuts"] = {str(i): v for i, v in enumerate(keep)}
    backup_vdf(vdf_path)
    tmp = vdf_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(vdf_encode(root))
    os.replace(tmp, vdf_path)
    return removed_appids


def install_grid_artwork(user_id: str, appid: int, artwork_dir: str) -> Dict[str, str]:
    """Copies poster, banner, hero, logo, icon to Steam's grid folder."""
    grid_dir = os.path.join(STEAM_DIR, "userdata", user_id, "config/grid")
    os.makedirs(grid_dir, exist_ok=True)
    installed: Dict[str, str] = {}

    artwork_map = {
        "p": ("poster", "cover", "portrait"),  # Vertical 600x900
        "": ("banner", "landscape", "header"), # Horizontal 460x215
        "_hero": ("hero", "background"),       # Wide 1920x620
        "_logo": ("logo", "clearlogo"),        # Transparent logo
        "_icon": ("icon", "thumb"),            # Square icon
    }

    for suffix, names in artwork_map.items():
        for name in names:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                src = os.path.join(artwork_dir, f"{name}{ext}")
                if os.path.isfile(src):
                    dest = os.path.join(grid_dir, f"{appid}{suffix}{ext}")
                    # Remove any existing extensions for this suffix
                    for old in glob.glob(os.path.join(grid_dir, f"{appid}{suffix}.*")):
                        try:
                            os.remove(old)
                        except OSError:
                            pass
                    shutil.copy2(src, dest)
                    installed[suffix or "banner"] = dest
                    break
            if suffix in installed or ("banner" in installed and suffix == ""):
                break

    return installed


def register_game_in_steam(
    title: str,
    launch_script_path: str,
    anchor_dir: str,
    icon_path: str = "",
    artwork_dir: str = "",
    is_vr: bool = True,
    launch_options: str = ""
) -> Dict[str, Any]:
    """Registers a game shortcut in all Steam users' libraries with full artwork."""
    users = get_steam_users()
    if not users:
        return {"success": False, "error": "No Steam users found on system"}

    exe = f'"{launch_script_path}"'
    appid = shortcut_appid(exe, title)
    results = {}

    for user in users:
        vdf_path = os.path.join(STEAM_DIR, "userdata", user, "config/shortcuts.vdf")
        upsert_shortcut(
            vdf_path=vdf_path,
            exe=exe,
            title=title,
            start_dir=anchor_dir,
            icon=icon_path,
            tag="FrameLoad VR" if is_vr else "FrameLoad 2D",
            openvr=is_vr,
            launch_options=launch_options
        )
        art = {}
        if artwork_dir and os.path.isdir(artwork_dir):
            art = install_grid_artwork(user, appid, artwork_dir)
        results[user] = {"appid": appid, "artwork": art}

    return {
        "success": True,
        "appid": appid,
        "gameid": (int(appid) << 32) | 0x02000000,
        "users": results
    }


def unregister_game_from_steam(launch_script_path: str, appid: Optional[int] = None) -> bool:
    """Removes a shortcut and its grid artwork from all Steam users."""
    users = get_steam_users()
    exe = f'"{launch_script_path}"'
    any_removed = False

    for user in users:
        vdf_path = os.path.join(STEAM_DIR, "userdata", user, "config/shortcuts.vdf")
        if remove_shortcut_by_exe(vdf_path, exe):
            any_removed = True
        if appid:
            grid_dir = os.path.join(STEAM_DIR, "userdata", user, "config/grid")
            for art in glob.glob(os.path.join(grid_dir, f"{appid}*")):
                try:
                    os.remove(art)
                except OSError:
                    pass
    return any_removed


def unregister_app_from_steam(title: str = "FrameLoad", exe_substring: str = "frameload") -> bool:
    """Removes FrameLoad shortcut and all its grid artwork (poster, banner, hero, logo, icon) from all Steam users."""
    users = get_steam_users()
    any_removed = False

    for user in users:
        vdf_path = os.path.join(STEAM_DIR, "userdata", user, "config/shortcuts.vdf")
        removed_ids = remove_shortcut_by_title_or_exe(vdf_path, title=title, exe_substring=exe_substring)
        if removed_ids:
            any_removed = True
            grid_dir = os.path.join(STEAM_DIR, "userdata", user, "config/grid")
            for appid in removed_ids:
                for art in glob.glob(os.path.join(grid_dir, f"{appid}*")):
                    try:
                        os.remove(art)
                    except OSError:
                        pass
    return any_removed
