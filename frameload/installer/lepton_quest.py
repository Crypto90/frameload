"""Lepton container installer and launcher generator for Steam Frame."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import time
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR, HOME
from ..system.shortcuts import register_game_in_steam, shortcut_appid
from ..system.steamos import lepton_status
from .apk_patcher import ApkPatcher
from .artwork import ArtworkManager

LAUNCH_SCRIPT_TEMPLATE = r"""#!/usr/bin/env bash
# FrameLoad Steam Frame launcher for {title} ({pkg})
set -euo pipefail

app_dir={base_q}
[[ -d "$app_dir/lepton-app" ]] || {{ echo "Game files missing at $app_dir" >&2; exit 1; }}

# Lepton permissions auto-repair loop
fix_perms() {{
    find "$app_dir/lepton-data/external" -type d ! -perm -u+rwx -exec chmod u+rwx {{}} + 2>/dev/null || true
}}

mkdir -p "$app_dir/lepton-data/external/Android/data/{pkg}/files" \
         "$app_dir/lepton-data/external/Android/data/{pkg}/cache" 2>/dev/null || true
fix_perms
( while sleep 2 && kill -0 $$ 2>/dev/null; do fix_perms; done ) & permfix=$!

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

setsid {lepton_q} start >"$app_dir/launch.log" 2>&1 &
child=$!
wait "$child"
"""


class LeptonInstaller:
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
    ) -> Dict[str, Any]:
        """Installs a Quest VR or 2D Android APK into Lepton on the Steam Frame internal SSD or MicroSD."""
        if target_anchor:
            anchor = os.path.join(target_anchor, package_name)
        elif device_id and device_id != "internal":
            from ..manager.storage import StorageManager
            target_base = StorageManager.resolve_anchor(device_id)
            anchor = os.path.join(target_base, package_name)
        else:
            from ..config import Config
            cfg = Config.get()
            default_dev = cfg.get("storage", {}).get("default_device_id", "internal")
            if default_dev and default_dev != "internal":
                from ..manager.storage import StorageManager
                target_base = StorageManager.resolve_anchor(default_dev)
                anchor = os.path.join(target_base, package_name)
                device_id = default_dev
            else:
                anchor = os.path.join(ANCHOR_DIR, package_name)
                device_id = "internal"

        base = anchor  # Storage anchor for this device
        app_dir = os.path.join(base, "lepton-app")
        data_dir = os.path.join(base, "lepton-data")
        shaders_dir = os.path.join(base, "lepton-shaders")
        art_dir = os.path.join(anchor, "artwork")

        for d in (anchor, app_dir, data_dir, shaders_dir, art_dir):
            os.makedirs(d, exist_ok=True)

        # Inspect APK
        analysis = ApkPatcher.inspect(apk_path)
        is_vr = analysis.is_vr if force_flat is None else (not force_flat)

        # Copy & Patch APK for Steam Frame OpenXR runtime
        dest_apk = os.path.join(app_dir, "game.apk")
        if is_vr:
            ApkPatcher.inject_frame_shims(apk_path, dest_apk)
        else:
            if os.path.abspath(apk_path) != os.path.abspath(dest_apk):
                shutil.copy2(apk_path, dest_apk)

        # Handle OBB files
        obb_target = os.path.join(app_dir, "obb")
        os.makedirs(obb_target, exist_ok=True)
        if obb_path and os.path.exists(obb_path):
            if os.path.isdir(obb_path):
                # Copy entire obb directory
                for item in os.listdir(obb_path):
                    s = os.path.join(obb_path, item)
                    d = os.path.join(obb_target, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)
            elif os.path.isfile(obb_path):
                pkg_obb_dir = os.path.join(obb_target, package_name)
                os.makedirs(pkg_obb_dir, exist_ok=True)
                shutil.copy2(obb_path, os.path.join(pkg_obb_dir, os.path.basename(obb_path)))

        # Setup Android files directory
        external_dir = os.path.join(data_dir, "external")
        files_dir = os.path.join(external_dir, "Android/data", package_name, "files")
        cache_dir = os.path.join(external_dir, "Android/data", package_name, "cache")
        os.makedirs(files_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        # Flat-screen marker
        marker = os.path.join(app_dir, "lepton-show-flatscreen")
        if not is_vr:
            open(marker, "a").close()
        elif os.path.exists(marker):
            os.remove(marker)

        # Settings
        settings = analysis.recommended_settings.copy()
        if custom_settings:
            settings.update(custom_settings)

        settings_conf_path = os.path.join(base, "settings.conf")
        ApkPatcher.generate_settings_conf(settings, settings_conf_path)
        ApkPatcher.generate_settings_conf(settings, os.path.join(files_dir, "framebridge.conf"))

        # Artwork
        ArtworkManager.ensure_artwork(package_name, title, art_dir)

        # Lepton binary
        lep = lepton_status()
        lepton_bin = lep["path"] or "/usr/bin/lepton"

        # Launch script
        launch_script = os.path.join(anchor, "launch.sh")
        appid = shortcut_appid(f'"{launch_script}"', title)

        script_content = LAUNCH_SCRIPT_TEMPLATE.format(
            title=title.replace("\n", " "),
            pkg=package_name,
            base_q=shlex.quote(base),
            appid=appid,
            lepton_q=shlex.quote(lepton_bin),
            extra_env=""
        )

        with open(launch_script, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(launch_script, 0o755)

        # Deployment metadata
        dep = {
            "package": package_name,
            "title": title,
            "appid": appid,
            "base": base,
            "anchor": anchor,
            "device_id": device_id or "internal",
            "kind": "quest" if is_vr else "flat",
            "is_vr": is_vr,
            "engine": analysis.engine,
            "apk_size": os.path.getsize(dest_apk),
            "settings": settings,
            "installed_by": "frameload",
            "time": time.time(),
        }
        with open(os.path.join(anchor, "deployment.json"), "w", encoding="utf-8") as f:
            json.dump(dep, f, indent=2)

        # Register in Steam
        steam_res = register_game_in_steam(
            title=title,
            launch_script_path=launch_script,
            anchor_dir=anchor,
            icon_path=os.path.join(art_dir, "icon.png"),
            artwork_dir=art_dir,
            is_vr=is_vr
        )

        return {
            "success": True,
            "package": package_name,
            "title": title,
            "appid": appid,
            "is_vr": is_vr,
            "anchor": anchor,
            "device_id": device_id or "internal",
            "steam": steam_res
        }
