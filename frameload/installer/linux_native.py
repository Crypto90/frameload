"""Native Linux ARM64 binary, AppImage, and shell launcher installer for Steam Frame."""
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

LINUX_LAUNCH_TEMPLATE = r"""#!/usr/bin/env bash
# FrameLoad Linux Native Launcher for {title}
set -euo pipefail

app_dir={anchor_q}
bin_path="$app_dir/bin/{rel_bin}"
[[ -f "$bin_path" ]] || {{ echo "Executable missing: $bin_path" >&2; exit 1; }}

export SteamAppId={appid}
export XDG_DATA_HOME="$app_dir/data"
export XDG_CONFIG_HOME="$app_dir/config"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME"

# OpenXR SteamVR configuration if VR game
if [[ "{is_vr}" == "True" ]]; then
    export XR_RUNTIME_JSON="${{XR_RUNTIME_JSON:-/usr/share/openxr/1/openxr_steamvr.json}}"
fi

cd "$(dirname "$bin_path")"
chmod +x "$bin_path"
exec "$bin_path" "$@"
"""


class LinuxNativeInstaller:
    @staticmethod
    def inspect_linux_source(source_path: str) -> Dict[str, Any]:
        """Inspects an AppImage, Linux executable, or shell script."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")

        is_dir = os.path.isdir(source_path)
        is_vr = False
        total_size = 0
        primary_bin = source_path
        kind = "elf"

        if is_dir:
            bins = []
            for root, _, files in os.walk(source_path):
                for f in files:
                    full = os.path.join(root, f)
                    total_size += os.path.getsize(full)
                    if os.access(full, os.X_OK) and not f.endswith((".so", ".a", ".txt", ".json")):
                        bins.append(full)
            if not bins:
                # Find any non-extension file
                for root, _, files in os.walk(source_path):
                    for f in files:
                        if "." not in f:
                            bins.append(os.path.join(root, f))
            if not bins:
                raise FileNotFoundError(f"No Linux executables found in {source_path}")
            primary_bin = bins[0]
            folder_name = os.path.basename(source_path.rstrip("/"))
            title = folder_name.replace("_", " ").replace("-", " ")
        else:
            total_size = os.path.getsize(source_path)
            lower = source_path.lower()
            if lower.endswith(".appimage"):
                kind = "appimage"
                title = os.path.basename(source_path).replace(".AppImage", "").replace(".appimage", "")
            elif lower.endswith(".sh"):
                kind = "script"
                title = os.path.basename(source_path).replace(".sh", "")
            else:
                title = os.path.basename(source_path)

            # Inspect binary for OpenXR
            try:
                with open(source_path, "rb") as f:
                    chunk = f.read(1024 * 1024 * 2)
                    if b"openxr" in chunk.lower() or b"steamvr" in chunk.lower():
                        is_vr = True
            except OSError:
                pass

        title = title.replace("_", " ").replace("-", " ")
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "", title.lower().replace(" ", "_"))
        pkg = f"linux.{clean_name}"

        return {
            "source_type": "linux_native",
            "format": kind,
            "path": source_path,
            "package_name": pkg,
            "title": title,
            "is_vr": is_vr,
            "primary_bin": primary_bin,
            "size_bytes": total_size,
            "runtime": "linux_native"
        }

    @staticmethod
    def install_linux_app(
        source_path: str,
        title: str = "",
        force_vr: Optional[bool] = None,
        device_id: Optional[str] = None,
        target_anchor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Installs a Native Linux application or AppImage on the Steam Frame."""
        info = LinuxNativeInstaller.inspect_linux_source(source_path)
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

        bin_dir = os.path.join(anchor, "bin")
        data_dir = os.path.join(anchor, "data")
        config_dir = os.path.join(anchor, "config")
        art_dir = os.path.join(anchor, "artwork")
        for d in (bin_dir, data_dir, config_dir, art_dir):
            os.makedirs(d, exist_ok=True)

        primary_bin = info["primary_bin"]
        if os.path.isdir(source_path):
            rel_bin = os.path.relpath(primary_bin, source_path)
            for item in os.listdir(source_path):
                s = os.path.join(source_path, item)
                d = os.path.join(bin_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
        else:
            rel_bin = os.path.basename(primary_bin)
            dest = os.path.join(bin_dir, rel_bin)
            shutil.copy2(primary_bin, dest)
            os.chmod(dest, 0o755)

        # Setup Artwork
        ArtworkManager.ensure_artwork(pkg, final_title, art_dir)

        # Generate launch script
        launch_script = os.path.join(anchor, "launch.sh")
        appid = shortcut_appid(f'"{launch_script}"', final_title)

        script_content = LINUX_LAUNCH_TEMPLATE.format(
            title=final_title.replace("\n", " "),
            anchor_q=shlex.quote(anchor),
            rel_bin=rel_bin,
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
            "runtime": "linux_native",
            "kind": "linux_native",
            "anchor": anchor,
            "appid": appid,
            "device_id": device_id or "internal",
            "primary_bin": rel_bin
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
            "install_type": "linux_native",
            "runtime": "linux_native",
            "is_vr": is_vr,
            "anchor": anchor,
            "appid": appid,
            "steam": steam_res
        }
