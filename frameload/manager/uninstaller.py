"""Uninstallation coordinator for FrameLoad."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict

from ..config import ANCHOR_DIR, FRAMELOAD_DIR, HOME
from ..system import fsutil
from ..system.shortcuts import unregister_app_from_steam, unregister_game_from_steam
from .installed import InstalledManager


class Uninstaller:
    @staticmethod
    def uninstall(package_name: str, keep_saves: bool = False) -> Dict[str, Any]:
        """Completely uninstalls a game, container, and Steam shortcuts."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            # Check if directory exists even without deployment.json
            target = os.path.join(ANCHOR_DIR, package_name)
            if os.path.isdir(target):
                fsutil.remove_tree(target)
                return {"success": True, "package": package_name, "message": "Cleaned up orphaned directory"}
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        appid = dep.get("appid")
        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, package_name))
        launch_script = os.path.join(anchor, "launch.sh")

        # 1. Stop container if running
        if appid:
            try:
                subprocess.run(["podman", "kill", f"lepton-steamlaunch-{appid}"], capture_output=True)
            except OSError:
                pass

        # 2. Optionally backup saves if requested
        if keep_saves:
            from .backup import SaveBackupManager
            try:
                SaveBackupManager.backup_saves(package_name)
            except Exception as e:
                print(f"[FrameLoad] Could not auto-backup saves before uninstall: {e}")

        # 3. Remove game directory (Lepton's containers own some of the files)
        removed = fsutil.remove_tree(anchor) if os.path.isdir(anchor) else True

        # 4. Unregister from Steam
        steam_removed = unregister_game_from_steam(launch_script, appid)

        return {
            "success": removed,
            "error": "" if removed else f"Some files in {anchor} could not be deleted.",
            "package": package_name,
            "title": dep.get("title", package_name),
            "steam_shortcut_removed": steam_removed
        }

    @staticmethod
    def uninstall_frameload_app(
        purge_games: bool = False,
        keep_backups: bool = False,
        purge_all_data: bool = True,
        remove_install_dir: bool = True
    ) -> Dict[str, Any]:
        """Completely and cleanly uninstalls the FrameLoad application and removes all traces."""
        summary: Dict[str, Any] = {
            "success": True,
            "services_stopped": False,
            "service_file_removed": False,
            "desktop_launcher_removed": False,
            "steam_shortcut_removed": False,
            "games_removed_count": 0,
            "data_purged": False,
            "backups_kept": keep_backups,
            "details": []
        }

        # 1. Stop and disable systemd user service
        service_file = os.path.join(HOME, ".config/systemd/user/frameload.service")
        try:
            subprocess.run(["systemctl", "--user", "stop", "frameload.service"], capture_output=True, timeout=10)
            subprocess.run(["systemctl", "--user", "disable", "frameload.service"], capture_output=True, timeout=10)
            summary["services_stopped"] = True
        except Exception as e:
            summary["details"].append(f"systemctl stop/disable: {e}")

        if os.path.isfile(service_file):
            try:
                os.remove(service_file)
                subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=5)
                subprocess.run(["systemctl", "--user", "reset-failed"], capture_output=True, timeout=5)
                summary["service_file_removed"] = True
            except OSError as e:
                summary["details"].append(f"remove service file: {e}")

        # 2. Remove desktop launcher
        desktop_file = os.path.join(HOME, ".local/share/applications/frameload.desktop")
        if os.path.isfile(desktop_file):
            try:
                os.remove(desktop_file)
                summary["desktop_launcher_removed"] = True
                try:
                    subprocess.run(["update-desktop-database", os.path.join(HOME, ".local/share/applications")], capture_output=True)
                except OSError:
                    pass
            except OSError as e:
                summary["details"].append(f"remove desktop file: {e}")

        wrapper = os.path.join(HOME, ".local/bin/frameload")
        if os.path.isfile(wrapper):
            try:
                os.remove(wrapper)
            except OSError as e:
                summary["details"].append(f"remove command wrapper: {e}")

        # 3. Remove FrameLoad shortcut and grid artwork (poster, banner, hero, logo, icon) from Steam
        try:
            summary["steam_shortcut_removed"] = unregister_app_from_steam(title="FrameLoad", exe_substring="frameload")
        except Exception as e:
            summary["details"].append(f"steam unregister: {e}")

        # 4. Optionally purge all sideloaded VR games & containers
        if purge_games:
            # Stop any running Lepton game containers
            try:
                out = subprocess.run(["podman", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True)
                for line in out.stdout.splitlines():
                    name = line.strip()
                    if name.startswith("lepton-steamlaunch-"):
                        subprocess.run(["podman", "rm", "-f", name], capture_output=True)
            except OSError:
                pass

            # Uninstall all games registered in library
            try:
                installed = InstalledManager.list_installed()
                for g in installed:
                    pkg = g.get("package")
                    if pkg:
                        try:
                            Uninstaller.uninstall(pkg, keep_saves=keep_backups)
                            summary["games_removed_count"] += 1
                        except Exception:
                            pass
            except Exception as e:
                summary["details"].append(f"purge games: {e}")

            # Remove anchor directory ~/Applications/quest-frame
            if os.path.isdir(ANCHOR_DIR):
                fsutil.remove_tree(ANCHOR_DIR)

            # Check MicroSD mounts for quest-frame directory
            try:
                from .storage import StorageManager
                for dev in StorageManager.get_devices():
                    if dev.get("id") != "internal" and dev.get("path"):
                        sd_anchor = os.path.join(dev["path"], "quest-frame")
                        if os.path.isdir(sd_anchor):
                            fsutil.remove_tree(sd_anchor)
            except Exception as e:
                summary["details"].append(f"microsd cleanup: {e}")

        # Ported games must keep being signed with the same key, or updates cannot install over them.
        try:
            from ..installer import porting
            saved = porting.backup_signing_keys()
            if saved:
                summary["details"].append(f"signing keys of ported games saved to {saved}")
        except Exception as e:
            summary["details"].append(f"signing key backup: {e}")

        # 5. Clean up data, cache, and config in ~/.local/share/frameload
        if purge_all_data and os.path.isdir(FRAMELOAD_DIR):
            try:
                if keep_backups:
                    for item in os.listdir(FRAMELOAD_DIR):
                        if item == "backups":
                            continue
                        p = os.path.join(FRAMELOAD_DIR, item)
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                else:
                    shutil.rmtree(FRAMELOAD_DIR, ignore_errors=True)
                summary["data_purged"] = True
            except OSError as e:
                summary["details"].append(f"purge data: {e}")

        cfg_dir = os.path.join(HOME, ".config/frameload")
        if os.path.isdir(cfg_dir):
            shutil.rmtree(cfg_dir, ignore_errors=True)

        # 6. Remove standard application install directory (~/Applications/FrameLoad)
        if remove_install_dir:
            app_dir = os.path.join(HOME, "Applications/FrameLoad")
            if os.path.isdir(app_dir):
                try:
                    shutil.rmtree(app_dir, ignore_errors=True)
                    summary["install_dir_removed"] = True
                except OSError as e:
                    summary["details"].append(f"remove app_dir: {e}")

        return summary

