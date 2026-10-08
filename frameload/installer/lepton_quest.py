"""Installs Android apps (Quest VR and 2D) for Valve's Lepton container on the Steam Frame.

The on-disk layout and launcher follow FramePort's (GPL-3.0) conventions, so both tools can manage
the same library: an anchor folder per game with launch.sh + deployment.json, and the game's files
(lepton-app/, lepton-data/, lepton-shaders/, settings.conf) in deployment.json["base"].
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import time
from typing import Any, Dict, Optional

from ..config import ANCHOR_DIR
from ..system.shortcuts import register_game_in_steam, shortcut_appid
from ..system.steamos import lepton_status
from .apk_analysis import inspect_apk
from .artwork import ArtworkManager

FLATSCREEN_MARKER = "lepton-show-flatscreen"

LAUNCH_SCRIPT_TEMPLATE = r"""#!/usr/bin/env bash
# FrameLoad Steam Frame launcher for {title} ({pkg})
set -euo pipefail

app_dir={base_q}
[[ -d "$app_dir/lepton-app" ]] || {{ echo "Game files missing at $app_dir (storage not mounted?)" >&2; exit 1; }}

# One launcher per game: a second Lepton started while the first still boots stops its container.
exec 9>"$app_dir/.launch.lock"
flock -n 9 || {{ echo "already starting or running: second launch ignored" >&2; exit 0; }}

# Lepton ships with the Steam Frame; its folder depends on the Steam library it lives in.
lepton={lepton_q}
if [[ ! -x "$lepton" ]]; then
    for candidate in "$HOME/.steam/steam/steamapps/common/Lepton/lepton" \
                     "$HOME/.local/share/Steam/steamapps/common/Lepton/lepton" /usr/bin/lepton; do
        if [[ -x "$candidate" ]]; then lepton="$candidate"; break; fi
    done
fi
[[ -x "$lepton" ]] || {{ echo "Lepton runtime not found on this system." >&2; exit 1; }}

# Some games create folders the app inside Lepton cannot write to (it writes through the folder's
# group), which breaks saving. Repair them before and during every launch.
fix_perms() {{
    find "$app_dir/lepton-data/external" -type d \( ! -perm -u+rwx -o ! -perm -g+rwx \) \
        -exec chmod u+rwx,g+rwx {{}} + 2>/dev/null || true
}}

# Android cannot create an app's external files/cache folders inside Lepton, so create them here.
mkdir -p "$app_dir/lepton-data/external/Android/data/{pkg}/files" \
         "$app_dir/lepton-data/external/Android/data/{pkg}/cache" 2>/dev/null || true
fix_perms
# Also ends the game when whoever started this launcher (Steam's reaper) is gone.
parent=$PPID
# Started by FrameLoad itself rather than Steam: its server restarts on updates, so don't follow it.
[[ -n "${{FRAMELOAD_DETACHED:-}}" ]] && parent=1
( while sleep 2 && kill -0 $$ 2>/dev/null; do
      fix_perms
      if [[ $parent -gt 1 ]] && ! kill -0 "$parent" 2>/dev/null; then kill -TERM $$; fi
  done ) 9>&- & permfix=$!

export SteamAppId={appid}
export STEAM_COMPAT_INSTALL_PATH="$app_dir/lepton-app"
export STEAM_COMPAT_DATA_PATH="$app_dir/lepton-data"
export STEAM_COMPAT_SHADER_PATH="$app_dir/lepton-shaders"
export STEAM_COMPAT_LIBRARY_PATHS="$app_dir"
export LEPTON_ENV_FRAMEBRIDGE_CONFIG="$app_dir/settings.conf"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export IS_PARENT=true
{extra_env}
child=''
stop() {{
    trap - EXIT INT TERM
    kill $permfix 2>/dev/null || true
    [[ -n "$child" ]] && kill -TERM -- "-$child" 2>/dev/null || true
    podman kill "lepton-steamlaunch-$SteamAppId" >/dev/null 2>&1 || true
}}
trap stop EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

setsid "$lepton" start >"$app_dir/launch.log" 2>&1 &
child=$!
wait "$child"
"""


def find_obb_dir(path: Optional[str], package_name: str) -> Optional[str]:
    """The folder whose contents belong in Android/obb/<package>/, for the layouts dumps come in."""
    if not path or not os.path.isdir(path):
        return None
    for candidate in (
        os.path.join(path, package_name),
        os.path.join(path, "obb", package_name),
        os.path.join(path, "Android", "obb", package_name),
        path,
        os.path.join(path, "obb"),
    ):
        try:
            if os.path.isdir(candidate) and any(n.lower().endswith(".obb") for n in os.listdir(candidate)):
                return candidate
        except OSError:
            continue
    return None


class LeptonInstaller:
    @staticmethod
    def set_flatscreen(app_dir: str, on: bool) -> None:
        """Lepton shows an app's 2D window only when its app folder holds this marker; otherwise the
        app runs headless and only OpenXR output reaches the headset."""
        marker = os.path.join(app_dir, FLATSCREEN_MARKER)
        if on:
            os.makedirs(app_dir, exist_ok=True)
            open(marker, "a").close()
        elif os.path.exists(marker):
            os.remove(marker)

    @staticmethod
    def write_launcher(anchor: str, base: str, package_name: str, title: str, appid: Any,
                       env: Optional[Dict[str, str]] = None) -> str:
        """Writes <anchor>/launch.sh, the script the game's Steam shortcut runs."""
        extra = "".join(
            f"export {k}={shlex.quote(str(v))}\n" for k, v in (env or {}).items()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)
        )
        text = LAUNCH_SCRIPT_TEMPLATE.format(
            title=re.sub(r"\s+", " ", title),
            pkg=package_name,
            base_q=shlex.quote(base),
            appid=int(appid or 0),
            lepton_q=shlex.quote(lepton_status()["path"] or "/usr/bin/lepton"),
            extra_env=extra,
        )
        path = os.path.join(anchor, "launch.sh")
        tmp = path + ".tmp"
        # A new file, so a launcher that is running keeps reading the old one.
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, 0o755)
        os.replace(tmp, path)
        return path

    @staticmethod
    def _resolve_anchor(package_name: str, target_anchor: Optional[str], device_id: Optional[str]) -> tuple:
        if target_anchor:
            return os.path.join(target_anchor, package_name), device_id or "internal"
        if not device_id:
            from ..config import Config
            device_id = Config.get().get("storage", {}).get("default_device_id", "internal")
        if device_id and device_id != "internal":
            from ..manager.storage import StorageManager
            return os.path.join(StorageManager.resolve_anchor(device_id), package_name), device_id
        return os.path.join(ANCHOR_DIR, package_name), "internal"

    @staticmethod
    def install_quest_game(
        package_name: str,
        title: str,
        apk_path: str,
        obb_path: Optional[str] = None,
        custom_settings: Optional[Dict[str, Any]] = None,
        force_flat: Optional[bool] = None,
        target_anchor: Optional[str] = None,
        device_id: Optional[str] = None,
        icon_url: str = "",
    ) -> Dict[str, Any]:
        """Installs a Quest VR or 2D Android APK for Lepton and adds it to the Steam library.

        force_flat=True shows the app as a 2D window; anything else trusts the APK's own manifest.
        """
        analysis = inspect_apk(apk_path)
        if analysis.manifest_parsed:
            package_name = analysis.package_name  # Lepton keys data and OBB folders on the real package
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*", package_name or "") or ".." in package_name:
            raise ValueError(f"Invalid package name: {package_name!r}")
        is_vr = False if force_flat else analysis.is_vr
        title = (title or analysis.label or package_name).strip()

        anchor, device_id = LeptonInstaller._resolve_anchor(package_name, target_anchor, device_id)
        base = anchor
        app_dir = os.path.join(base, "lepton-app")
        data_dir = os.path.join(base, "lepton-data")
        art_dir = os.path.join(anchor, "artwork")
        for d in (anchor, app_dir, data_dir, os.path.join(base, "lepton-shaders"), art_dir):
            os.makedirs(d, exist_ok=True)

        # Lepton starts the single APK in the app folder; a second one makes its lookup ambiguous.
        dest_apk = os.path.join(app_dir, "game.apk")
        if os.path.abspath(apk_path) != os.path.abspath(dest_apk):
            tmp_apk = dest_apk + ".incoming"
            shutil.copy2(apk_path, tmp_apk)
            os.replace(tmp_apk, dest_apk)
        for name in os.listdir(app_dir):
            if name.lower().endswith(".apk") and name != "game.apk":
                os.remove(os.path.join(app_dir, name))

        # OBB files sit directly in lepton-app/obb/; Lepton links that folder to Android/obb/<package>.
        obb_target = os.path.join(app_dir, "obb")
        os.makedirs(obb_target, exist_ok=True)
        obb_count = 0
        if obb_path and os.path.isfile(obb_path):
            shutil.copy2(obb_path, os.path.join(obb_target, os.path.basename(obb_path)))
            obb_count = 1
        else:
            obb_dir = find_obb_dir(obb_path, package_name)
            if obb_dir:
                for item in os.listdir(obb_dir):
                    src = os.path.join(obb_dir, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, os.path.join(obb_target, item), dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, os.path.join(obb_target, item))
                    obb_count += 1

        for sub in ("files", "cache"):
            os.makedirs(os.path.join(data_dir, "external/Android/data", package_name, sub), exist_ok=True)

        ArtworkManager.ensure_artwork(package_name, title, art_dir, icon_url=icon_url)

        launch_script = os.path.join(anchor, "launch.sh")
        appid = shortcut_appid(f'"{launch_script}"', title)

        from ..manager.tuning import TuningManager, normalize_settings
        previous: Dict[str, Any] = {}
        dep_path = os.path.join(anchor, "deployment.json")
        if os.path.isfile(dep_path):  # an update keeps the game's settings
            try:
                with open(dep_path, "r", encoding="utf-8") as f:
                    previous = json.load(f)
            except (OSError, ValueError):
                previous = {}
        settings = normalize_settings(previous.get("settings", {}), keep_defaults=True)
        settings.update(normalize_settings(custom_settings or {}, keep_defaults=True))

        dep = {
            "package": package_name,
            "title": title,
            "appid": appid,
            "base": base,
            "anchor": anchor,
            "device_id": device_id,
            "kind": "quest" if is_vr else "flat",
            "is_vr": is_vr,
            "engine": analysis.engine,
            "version_name": analysis.version_name,
            "version_code": analysis.version_code,
            "apk_size": os.path.getsize(dest_apk),
            "xr_runtime": analysis.xr_runtime,
            "framebridge": analysis.framebridge,
            "hand_tracking": analysis.hand_tracking,
            "compat": analysis.compat,
            "settings": settings,
            "framebridge_keys": previous.get("framebridge_keys", []),
            "installed_by": "frameload",
            "layout_version": 3,
            "time": time.time(),
        }
        with open(dep_path, "w", encoding="utf-8") as f:
            json.dump(dep, f, indent=2)

        # Launcher, 2D-window marker and FrameBridge settings
        TuningManager.apply_tuning_to_game(package_name, dep=dep)

        steam_res = register_game_in_steam(
            title=title,
            launch_script_path=launch_script,
            anchor_dir=anchor,
            icon_path=os.path.join(art_dir, "icon.png"),
            artwork_dir=art_dir,
            is_vr=is_vr,
        )

        return {
            "success": True,
            "package": package_name,
            "title": title,
            "appid": appid,
            "is_vr": is_vr,
            "kind": dep["kind"],
            "anchor": anchor,
            "device_id": device_id,
            "obb_files": obb_count,
            "compat": analysis.compat,
            "hand_tracking": analysis.hand_tracking,
            "framebridge": analysis.framebridge,
            "steam": steam_res,
        }
