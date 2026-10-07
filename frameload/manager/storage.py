"""Steam-style Storage Manager for FrameLoad.
Provides drive telemetry, per-game disk breakdown, segmented usage visualizer,
cache cleanup, and batch uninstallation.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR, CACHE_DIR, HOME
from ..manager.installed import InstalledManager
from ..manager.uninstaller import Uninstaller


def format_size(size_bytes: int | float) -> str:
    """Formats bytes into human readable binary units matching Steam's UI."""
    size = float(size_bytes)
    if size < 1024:
        return f"{int(size)} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    elif size < 1024 * 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"
    else:
        return f"{size / (1024 * 1024 * 1024 * 1024):.2f} TB"


def get_dir_size(path: str) -> int:
    """Recursively computes directory size in bytes without loading everything into memory."""
    total = 0
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += get_dir_size(entry.path)
                except OSError:
                    continue
    except OSError:
        pass
    return total


class StorageManager:
    @staticmethod
    def get_devices() -> List[Dict[str, Any]]:
        """Detects internal storage and mounted external/MicroSD media."""
        devices = []
        seen_mounts = set()

        # 1. Primary Internal Storage (Home directory / SteamOS)
        try:
            home_usage = shutil.disk_usage(HOME)
            devices.append({
                "id": "internal",
                "name": "Internal Storage (Home)",
                "label": "SteamOS Internal SSD",
                "path": HOME,
                "is_default": True,
                "is_external": False,
                "is_sd_card": False,
                "device_type": "internal",
                "has_quest_anchor": os.path.isdir(ANCHOR_DIR),
                "total_bytes": home_usage.total,
                "free_bytes": home_usage.free,
                "used_bytes": home_usage.used,
                "free_formatted": format_size(home_usage.free),
                "total_formatted": format_size(home_usage.total),
                "used_formatted": format_size(home_usage.used),
                "percent_used": round((home_usage.used / home_usage.total) * 100, 1) if home_usage.total else 0,
            })
            seen_mounts.add(os.path.realpath(HOME))
        except OSError:
            pass

        candidate_mounts: List[Dict[str, Any]] = []

        # 2. Check /proc/mounts on Linux for mmcblk and sd devices
        if os.path.isfile("/proc/mounts"):
            try:
                with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 3:
                            dev_node, mount_point, fs_type = parts[0], parts[1], parts[2]
                            if fs_type in ("ext4", "btrfs", "vfat", "exfat", "f2fs", "ntfs", "fuseblk"):
                                if (dev_node.startswith("/dev/mmcblk") or
                                        dev_node.startswith("/dev/sd") or
                                        "/run/media/" in mount_point or
                                        "/media/" in mount_point):
                                    candidate_mounts.append({
                                        "path": mount_point,
                                        "dev_node": dev_node,
                                        "fs_type": fs_type,
                                        "is_sd": "/dev/mmcblk" in dev_node or "mmc" in mount_point.lower() or "sd" in mount_point.lower()
                                    })
            except OSError:
                pass

        # 3. Standard search roots
        search_roots = [
            "/run/media/deck",
            f"/run/media/{os.getenv('USER', 'deck')}",
            "/run/media",
            "/media",
            "/media/deck",
            "/mnt",
            "/Volumes",  # macOS dev compatibility
        ]

        for root in search_roots:
            if not os.path.isdir(root):
                continue
            try:
                for entry in os.scandir(root):
                    if entry.is_dir(follow_symlinks=False):
                        candidate_mounts.append({
                            "path": entry.path,
                            "dev_node": "",
                            "fs_type": "",
                            "is_sd": "sd" in entry.name.lower() or "mmc" in entry.name.lower()
                        })
            except OSError:
                continue

        # 4. Custom paths from config
        try:
            from ..config import Config
            cfg = Config.get()
            for custom_path in cfg.get("storage", {}).get("custom_paths", []):
                if os.path.isdir(custom_path):
                    candidate_mounts.append({
                        "path": custom_path,
                        "dev_node": "",
                        "fs_type": "",
                        "is_sd": False
                    })
        except Exception:
            pass

        # Deduplicate candidate mounts
        for c in candidate_mounts:
            p = c["path"]
            try:
                rp = os.path.realpath(p)
            except OSError:
                rp = p
            if rp in seen_mounts or p in seen_mounts or p.startswith("/Volumes/Macintosh"):
                continue
            try:
                usage = shutil.disk_usage(p)
                # Filter out virtual filesystems with tiny storage (< 100MB)
                if usage.total < 100 * 1024 * 1024:
                    continue

                name = os.path.basename(p.rstrip("/"))
                is_sd = c.get("is_sd", False) or "/run/media/" in p or "mmc" in name.lower() or "sd" in name.lower()
                dev_type = "microsd" if is_sd else "usb"
                label = f"MicroSD Card ({name})" if is_sd else f"External Drive ({name})"
                dev_id = f"ext_{name.replace(' ', '_').replace('-', '_')}"

                # Check if Steam library or quest-frame folder exists
                has_steam_lib = any(os.path.isdir(os.path.join(p, d)) for d in ("steamapps", "SteamLibrary"))
                has_quest = os.path.isdir(os.path.join(p, "quest-frame"))

                devices.append({
                    "id": dev_id,
                    "name": label,
                    "label": name,
                    "path": p,
                    "is_default": False,
                    "is_external": True,
                    "is_sd_card": is_sd,
                    "device_type": dev_type,
                    "filesystem": c.get("fs_type", "ext4"),
                    "is_steam_library": has_steam_lib,
                    "has_quest_anchor": has_quest,
                    "total_bytes": usage.total,
                    "free_bytes": usage.free,
                    "used_bytes": usage.used,
                    "free_formatted": format_size(usage.free),
                    "total_formatted": format_size(usage.total),
                    "used_formatted": format_size(usage.used),
                    "percent_used": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
                })
                seen_mounts.add(rp)
                seen_mounts.add(p)
            except OSError:
                continue

        return devices

    @staticmethod
    def resolve_anchor(device_id: Optional[str] = None) -> str:
        """Resolves the quest-frame anchor directory for a target device ID."""
        if not device_id or device_id == "internal":
            os.makedirs(ANCHOR_DIR, exist_ok=True)
            return ANCHOR_DIR

        devices = StorageManager.get_devices()
        dev = next((d for d in devices if d["id"] == device_id), None)
        if dev and dev.get("is_external"):
            anchor = os.path.join(dev["path"], "quest-frame")
            os.makedirs(anchor, exist_ok=True)
            return anchor

        # Check if device_id is a direct directory path
        if os.path.isdir(device_id):
            anchor = os.path.join(device_id, "quest-frame") if not device_id.endswith("quest-frame") else device_id
            os.makedirs(anchor, exist_ok=True)
            return anchor

        os.makedirs(ANCHOR_DIR, exist_ok=True)
        return ANCHOR_DIR

    @staticmethod
    def get_storage_overview(device_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculates segmented storage telemetry matching Steam's storage manager."""
        devices = StorageManager.get_devices()
        active_dev = next((d for d in devices if d["id"] == device_id), None)
        if not active_dev and devices:
            active_dev = devices[0]

        total_bytes = active_dev["total_bytes"] if active_dev else 1
        free_bytes = active_dev["free_bytes"] if active_dev else 0
        used_bytes = active_dev["used_bytes"] if active_dev else 0

        # Scan installed games
        games_data = []
        games_total_bytes = 0
        saves_total_bytes = 0
        shaders_total_bytes = 0
        artwork_total_bytes = 0

        # Determine target anchor path for this drive
        # If internal: standard ANCHOR_DIR; If external: check if quest-frame exists on that drive
        target_anchor = ANCHOR_DIR
        if active_dev and active_dev.get("is_external"):
            ext_anchor = os.path.join(active_dev["path"], "quest-frame")
            if os.path.isdir(ext_anchor):
                target_anchor = ext_anchor
            else:
                target_anchor = ""

        if target_anchor and os.path.isdir(target_anchor):
            pattern = os.path.join(target_anchor, "*/deployment.json")
            for dep_path in sorted(glob.glob(pattern)):
                try:
                    with open(dep_path, "r", encoding="utf-8") as f:
                        dep = json.load(f)
                except (OSError, ValueError):
                    continue

                pkg = dep.get("package", os.path.basename(os.path.dirname(dep_path)))
                anchor = os.path.dirname(dep_path)
                appid = dep.get("appid", 0)

                app_dir = os.path.join(anchor, "lepton-app")
                data_dir = os.path.join(anchor, "lepton-data")
                shaders_dir = os.path.join(anchor, "lepton-shaders")
                art_dir = os.path.join(anchor, "artwork")

                app_bytes = get_dir_size(app_dir)
                data_bytes = get_dir_size(data_dir)
                shaders_bytes = get_dir_size(shaders_dir)
                art_bytes = get_dir_size(art_dir)

                # Total size of the game installation directory
                game_total = get_dir_size(anchor)
                # If root files exist (scripts, manifests), account for them
                if game_total < (app_bytes + data_bytes + shaders_bytes + art_bytes):
                    game_total = app_bytes + data_bytes + shaders_bytes + art_bytes

                games_total_bytes += app_bytes
                saves_total_bytes += data_bytes
                shaders_total_bytes += shaders_bytes
                artwork_total_bytes += art_bytes

                # Format date
                install_time = dep.get("time", 0)
                time_str = "Installed recently"
                if install_time:
                    try:
                        time_str = time.strftime("%b %d, %Y", time.localtime(install_time))
                    except Exception:
                        pass

                games_data.append({
                    "package": pkg,
                    "title": dep.get("title", pkg),
                    "appid": appid,
                    "anchor": anchor,
                    "kind": dep.get("kind", "quest"),
                    "is_vr": dep.get("is_vr", True),
                    "engine": dep.get("engine", "Unity"),
                    "total_bytes": game_total,
                    "total_formatted": format_size(game_total),
                    "app_bytes": app_bytes,
                    "app_formatted": format_size(app_bytes),
                    "saves_bytes": data_bytes,
                    "saves_formatted": format_size(data_bytes),
                    "shaders_bytes": shaders_bytes,
                    "shaders_formatted": format_size(shaders_bytes),
                    "artwork_bytes": art_bytes,
                    "artwork_formatted": format_size(art_bytes),
                    "installed_time": install_time,
                    "installed_formatted": time_str,
                    "thumbnail_url": f"/api/installed/artwork/{pkg}" if os.path.isdir(art_dir) else f"/api/thumbnail/{pkg}",
                })

        # Sort games by total_bytes descending by default (matching Steam's default)
        games_data.sort(key=lambda g: g["total_bytes"], reverse=True)

        # Cache calculation
        cache_bytes = get_dir_size(CACHE_DIR) if (active_dev and not active_dev.get("is_external")) else 0
        cache_file_count = 0
        if os.path.isdir(CACHE_DIR):
            try:
                cache_file_count = len([f for f in os.listdir(CACHE_DIR) if os.path.isfile(os.path.join(CACHE_DIR, f))])
            except OSError:
                pass

        # Calculate "Other" space (Steam, system, OS, non-VR files)
        tracked_used = games_total_bytes + saves_total_bytes + shaders_total_bytes + artwork_total_bytes + cache_bytes
        other_bytes = max(0, used_bytes - tracked_used)

        def pct(val: int) -> float:
            return round((val / total_bytes) * 100, 2) if total_bytes > 0 else 0.0

        return {
            "devices": devices,
            "active_device": active_dev,
            "anchor_dir": target_anchor,
            "breakdown": {
                "total_bytes": total_bytes,
                "total_formatted": format_size(total_bytes),
                "free_bytes": free_bytes,
                "free_formatted": format_size(free_bytes),
                "free_percent": pct(free_bytes),
                "used_bytes": used_bytes,
                "used_formatted": format_size(used_bytes),
                "used_percent": pct(used_bytes),
                "games_bytes": games_total_bytes,
                "games_formatted": format_size(games_total_bytes),
                "games_percent": pct(games_total_bytes),
                "saves_bytes": saves_total_bytes,
                "saves_formatted": format_size(saves_total_bytes),
                "saves_percent": pct(saves_total_bytes),
                "shaders_bytes": shaders_total_bytes,
                "shaders_formatted": format_size(shaders_total_bytes),
                "shaders_percent": pct(shaders_total_bytes),
                "cache_bytes": cache_bytes,
                "cache_formatted": format_size(cache_bytes),
                "cache_percent": pct(cache_bytes),
                "other_bytes": other_bytes,
                "other_formatted": format_size(other_bytes),
                "other_percent": pct(other_bytes),
            },
            "games_count": len(games_data),
            "games": games_data,
            "cache": {
                "path": CACHE_DIR,
                "bytes": cache_bytes,
                "formatted": format_size(cache_bytes),
                "file_count": cache_file_count,
            }
        }

    @staticmethod
    def batch_uninstall(packages: List[str], keep_saves: bool = False) -> Dict[str, Any]:
        """Uninstalls multiple games sequentially and tracks total reclaimed storage."""
        reclaimed_total = 0
        results = []

        for pkg in packages:
            # Measure folder size before deletion
            target_dir = os.path.join(ANCHOR_DIR, pkg)
            pkg_size = get_dir_size(target_dir)

            try:
                res = Uninstaller.uninstall(pkg, keep_saves=keep_saves)
                reclaimed_total += pkg_size
                results.append({
                    "package": pkg,
                    "success": True,
                    "reclaimed_bytes": pkg_size,
                    "reclaimed_formatted": format_size(pkg_size),
                })
            except Exception as e:
                results.append({
                    "package": pkg,
                    "success": False,
                    "error": str(e),
                    "reclaimed_bytes": 0,
                    "reclaimed_formatted": "0 B",
                })

        return {
            "success": True,
            "uninstalled_count": sum(1 for r in results if r["success"]),
            "total_requested": len(packages),
            "reclaimed_bytes": reclaimed_total,
            "reclaimed_formatted": format_size(reclaimed_total),
            "results": results,
        }

    @staticmethod
    def clean_cache(clear_downloads: bool = True, clear_shaders: bool = False) -> Dict[str, Any]:
        """Clears temporary downloaded archives and optionally resets shader caches."""
        reclaimed_bytes = 0
        cleaned_files = 0

        # 1. Clean downloads / cache directory
        if clear_downloads and os.path.isdir(CACHE_DIR):
            try:
                for entry in os.scandir(CACHE_DIR):
                    try:
                        if entry.is_file(follow_symlinks=False):
                            sz = entry.stat().st_size
                            os.remove(entry.path)
                            reclaimed_bytes += sz
                            cleaned_files += 1
                        elif entry.is_dir(follow_symlinks=False):
                            sz = get_dir_size(entry.path)
                            shutil.rmtree(entry.path, ignore_errors=True)
                            reclaimed_bytes += sz
                            cleaned_files += 1
                    except OSError:
                        continue
            except OSError:
                pass

        # 2. Clean shader caches in installed games
        if clear_shaders and os.path.isdir(ANCHOR_DIR):
            for shader_dir in glob.glob(os.path.join(ANCHOR_DIR, "*/lepton-shaders")):
                if os.path.isdir(shader_dir):
                    sz = get_dir_size(shader_dir)
                    try:
                        shutil.rmtree(shader_dir, ignore_errors=True)
                        os.makedirs(shader_dir, exist_ok=True)
                        reclaimed_bytes += sz
                        cleaned_files += 1
                    except OSError:
                        pass

        return {
            "success": True,
            "reclaimed_bytes": reclaimed_bytes,
            "reclaimed_formatted": format_size(reclaimed_bytes),
            "cleaned_files": cleaned_files,
        }

    @staticmethod
    def move_game(package_name: str, target_device_id: str) -> Dict[str, Any]:
        """Moves an installed game between internal storage and MicroSD/external storage."""
        from .installed import InstalledManager
        from ..system.shortcuts import register_game_in_steam
        from ..installer.lepton_quest import LAUNCH_SCRIPT_TEMPLATE
        from ..system.steamos import lepton_status
        import shlex
        import subprocess

        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game '{package_name}' is not installed.")

        current_anchor = dep.get("anchor")
        if not current_anchor or not os.path.isdir(current_anchor):
            raise FileNotFoundError(f"Game directory not found at {current_anchor}")

        current_device_id = dep.get("device_id", "internal")
        if current_device_id == target_device_id:
            return {"success": True, "message": "Game is already on target device", "moved": False}

        target_base = StorageManager.resolve_anchor(target_device_id)
        new_anchor = os.path.join(target_base, package_name)

        if os.path.abspath(current_anchor) == os.path.abspath(new_anchor):
            return {"success": True, "message": "Source and destination paths are identical", "moved": False}

        # Check free disk space on target device
        game_size = get_dir_size(current_anchor)
        target_mount = target_base
        for d in StorageManager.get_devices():
            if d["id"] == target_device_id:
                target_mount = d["path"]
                break
        try:
            free_space = shutil.disk_usage(target_mount).free
            if free_space < game_size + (100 * 1024 * 1024):
                raise OSError(
                    f"Insufficient disk space on destination. Free: {format_size(free_space)}, Required: {format_size(game_size)}"
                )
        except OSError as e:
            if "Insufficient" in str(e):
                raise

        # 1. Kill running container if any
        appid = dep.get("appid")
        if appid:
            try:
                subprocess.run(["podman", "kill", f"lepton-steamlaunch-{appid}"], capture_output=True)
            except OSError:
                pass

        # 2. Move files to new anchor
        if os.path.exists(new_anchor):
            shutil.rmtree(new_anchor, ignore_errors=True)
        shutil.move(current_anchor, new_anchor)

        # 3. Update deployment.json
        dep_path = os.path.join(new_anchor, "deployment.json")
        dep["anchor"] = new_anchor
        dep["base"] = new_anchor
        dep["device_id"] = target_device_id
        with open(dep_path, "w", encoding="utf-8") as f:
            json.dump(dep, f, indent=2)

        # 4. Regenerate launch.sh with new paths
        title = dep.get("title", package_name)
        lep = lepton_status()
        lepton_bin = lep["path"] or "/usr/bin/lepton"
        launch_script = os.path.join(new_anchor, "launch.sh")
        script_content = LAUNCH_SCRIPT_TEMPLATE.format(
            title=title.replace("\n", " "),
            pkg=package_name,
            base_q=shlex.quote(new_anchor),
            appid=appid,
            lepton_q=shlex.quote(lepton_bin),
            extra_env=""
        )
        with open(launch_script, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(launch_script, 0o755)

        # 5. Update Steam shortcut with new launch script path
        art_dir = os.path.join(new_anchor, "artwork")
        register_game_in_steam(
            title=title,
            launch_script_path=launch_script,
            anchor_dir=new_anchor,
            icon_path=os.path.join(art_dir, "icon.png"),
            artwork_dir=art_dir,
            is_vr=dep.get("is_vr", True)
        )

        return {
            "success": True,
            "package": package_name,
            "title": title,
            "from_device": current_device_id,
            "to_device": target_device_id,
            "new_anchor": new_anchor,
            "bytes_moved": game_size,
            "moved": True
        }

    @staticmethod
    def batch_move(packages: List[str], target_device_id: str) -> Dict[str, Any]:
        """Moves multiple games to target storage device sequentially."""
        results = []
        errors = []
        total_moved = 0
        for pkg in packages:
            try:
                res = StorageManager.move_game(pkg, target_device_id)
                results.append(res)
                if res.get("moved"):
                    total_moved += res.get("bytes_moved", 0)
            except Exception as e:
                errors.append({"package": pkg, "error": str(e)})

        return {
            "success": len(errors) == 0,
            "results": results,
            "errors": errors,
            "total_bytes_moved": total_moved,
            "total_formatted": format_size(total_moved),
            "moved_count": len([r for r in results if r.get("moved")]),
            "requested_count": len(packages)
        }
