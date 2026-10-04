"""Windows executable (PCVR & Flat) and Proton compatibility runner installer for Steam Frame."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import time
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR, HOME
from ..system.shortcuts import register_game_in_steam, shortcut_appid
from .artwork import ArtworkManager

WINDOWS_LAUNCH_TEMPLATE = r"""#!/usr/bin/env bash
# FrameLoad Windows Proton Launcher for {title}
set -euo pipefail

app_dir={anchor_q}
exe_path="$app_dir/app/{rel_exe}"
[[ -f "$exe_path" ]] || {{ echo "Executable missing: $exe_path" >&2; exit 1; }}

export SteamAppId={appid}
export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.local/share/Steam"
export STEAM_COMPAT_DATA_PATH="$app_dir/pfx"
export WINEPREFIX="$app_dir/pfx/pfx"
mkdir -p "$app_dir/pfx"

# PCVR OpenXR / SteamVR configuration
if [[ "{is_vr}" == "True" ]]; then
    export XR_RUNTIME_JSON="${{XR_RUNTIME_JSON:-/usr/share/openxr/1/openxr_steamvr.json}}"
    export PRESSURE_VESSEL_FILESYSTEMS_RO="/usr/share/openxr"
    export WINE_VR_DISABLE_SURFACE=0
fi

# Detect best available Proton runner
PROTON_BIN=""
for cand in \
    "$HOME/.local/share/Steam/compatibilitytools.d"/GE-Proton*/proton \
    "$HOME/.local/share/Steam/steamapps/common/Proton - Experimental/proton" \
    "$HOME/.local/share/Steam/steamapps/common/Proton 9.0/proton" \
    "$HOME/.local/share/Steam/steamapps/common/Proton 8.0/proton" \
    "/usr/share/steam/compatibilitytools.d"/GE-Proton*/proton \
    "/usr/bin/proton"; do
    if [[ -x "$cand" ]]; then
        PROTON_BIN="$cand"
        break
    fi
done

cd "$(dirname "$exe_path")"
if [[ -n "$PROTON_BIN" ]]; then
    exec "$PROTON_BIN" run "$exe_path" "$@"
elif which wine >/dev/null 2>&1; then
    exec wine "$exe_path" "$@"
else
    echo "Error: Neither Proton nor Wine found on Steam Frame." >&2
    exit 1
fi
"""


class WindowsProtonInstaller:
    @staticmethod
    def inspect_windows_source(source_path: str) -> Dict[str, Any]:
        """Inspects a Windows .exe file or directory to determine VR support and primary executable."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")

        is_dir = os.path.isdir(source_path)
        exes: List[str] = []
        is_vr = False
        engine = "Generic"
        total_size = 0

        if is_dir:
            for root, _, files in os.walk(source_path):
                for f in files:
                    full = os.path.join(root, f)
                    total_size += os.path.getsize(full)
                    lower = f.lower()
                    if lower.endswith(".exe"):
                        exes.append(full)
                    elif lower in ("openxr_loader.dll", "openvr_api.dll", "vrclient.dll", "libopenxr_loader.dll"):
                        is_vr = True
                    elif "unity" in lower:
                        engine = "Unity"
                    elif "unreal" in lower or lower.endswith(".uproject"):
                        engine = "Unreal"

            if not exes:
                raise FileNotFoundError(f"No .exe executables found in directory: {source_path}")

            # Filter out uninstaller / crash reporter executables
            filtered = [
                e for e in exes
                if not any(x in os.path.basename(e).lower() for x in ("unins", "crash", "reporter", "update", "setup"))
            ]
            primary_exe = max(filtered or exes, key=os.path.getsize)
            folder_name = os.path.basename(source_path.rstrip("/"))
            title = folder_name.replace("_", " ").replace("-", " ")
        else:
            primary_exe = source_path
            total_size = os.path.getsize(source_path)
            title = os.path.basename(source_path).replace(".exe", "").replace("_", " ")

            # Inspect binary for VR DLL imports
            try:
                with open(source_path, "rb") as f:
                    chunk = f.read(1024 * 1024 * 4)  # First 4MB
                    if b"openxr" in chunk.lower() or b"openvr" in chunk.lower() or b"vrclient" in chunk.lower():
                        is_vr = True
            except OSError:
                pass

        # Clean sanitized package name
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "", title.lower().replace(" ", "_"))
        pkg = f"win.{clean_name}"

        return {
            "source_type": "windows_proton",
            "format": "dir" if is_dir else "exe",
            "path": source_path,
            "package_name": pkg,
            "title": title,
            "is_vr": is_vr,
            "engine": engine,
            "primary_exe": primary_exe,
            "size_bytes": total_size,
            "runtime": "proton"
        }

    @staticmethod
    def install_windows_app(
        source_path: str,
        title: str = "",
        force_vr: Optional[bool] = None,
        device_id: Optional[str] = None,
        target_anchor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Installs a Windows PCVR or Flat application on the Steam Frame via Proton."""
        info = WindowsProtonInstaller.inspect_windows_source(source_path)
        pkg = info["package_name"]
        final_title = title or info["title"]
        is_vr = force_vr if force_vr is not None else info["is_vr"]

        if target_anchor:
            anchor = os.path.join(target_anchor, pkg)
        elif device_id and device_id != "internal":
            from ..manager.storage import StorageManager
            target_base = StorageManager.resolve_anchor(device_id)
            anchor = os.path.join(target_base, pkg)
        else:
            from ..config import Config
            cfg = Config.get()
            default_dev = cfg.get("storage", {}).get("default_device_id", "internal")
            if default_dev and default_dev != "internal":
                from ..manager.storage import StorageManager
                target_base = StorageManager.resolve_anchor(default_dev)
                anchor = os.path.join(target_base, pkg)
                device_id = default_dev
            else:
                anchor = os.path.join(ANCHOR_DIR, pkg)
                device_id = "internal"

        app_dir = os.path.join(anchor, "app")
        pfx_dir = os.path.join(anchor, "pfx")
        art_dir = os.path.join(anchor, "artwork")
        os.makedirs(app_dir, exist_ok=True)
        os.makedirs(pfx_dir, exist_ok=True)
        os.makedirs(art_dir, exist_ok=True)

        # Copy or extract files into <anchor>/app
        primary_exe = info["primary_exe"]
        if os.path.isdir(source_path):
            rel_exe = os.path.relpath(primary_exe, source_path)
            # Copy contents of directory
            for item in os.listdir(source_path):
                s = os.path.join(source_path, item)
                d = os.path.join(app_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
        else:
            rel_exe = os.path.basename(primary_exe)
            shutil.copy2(primary_exe, os.path.join(app_dir, rel_exe))

        # Setup Artwork
        ArtworkManager.ensure_artwork(pkg, final_title, art_dir)

        # Generate launch script
        launch_script = os.path.join(anchor, "launch.sh")
        appid = shortcut_appid(f'"{launch_script}"', final_title)

        script_content = WINDOWS_LAUNCH_TEMPLATE.format(
            title=final_title.replace("\n", " "),
            anchor_q=shlex.quote(anchor),
            rel_exe=rel_exe,
            appid=appid,
            is_vr=str(is_vr)
        )

        with open(launch_script, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(launch_script, 0o755)

        # Save deployment metadata
        meta = {
            "package": pkg,
            "title": final_title,
            "version": "1.0",
            "installed_at": int(time.time()),
            "is_vr": is_vr,
            "engine": info.get("engine", "Generic"),
            "runtime": "proton",
            "kind": "pcvr" if is_vr else "windows_flat",
            "anchor": anchor,
            "appid": appid,
            "device_id": device_id or "internal",
            "primary_exe": rel_exe
        }
        with open(os.path.join(anchor, "deployment.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Register in Steam library
        icon_path = os.path.join(art_dir, "icon.png")
        steam_res = register_game_in_steam(
            title=final_title,
            launch_script_path=launch_script,
            anchor_dir=anchor,
            icon_path=icon_path if os.path.isfile(icon_path) else "",
            artwork_dir=art_dir,
            is_vr=is_vr
        )

        return {
            "success": True,
            "package": pkg,
            "title": final_title,
            "install_type": "windows_proton",
            "runtime": "proton",
            "is_vr": is_vr,
            "anchor": anchor,
            "appid": appid,
            "steam": steam_res
        }
