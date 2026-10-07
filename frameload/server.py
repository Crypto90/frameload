"""High-performance multi-threaded HTTP server and REST API for FrameLoad."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

# Ensure repository root is in sys.path and package context is established
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    __package__ = "frameload"

RED = "\033[1;31m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[1;36m"
RESET = "\033[0m"


def color_excepthook(exc_type, exc_value, exc_traceback):
    import traceback
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    sys.stderr.write(f"{RED}{tb}{RESET}\n")

sys.excepthook = color_excepthook


from .catalog.downloader import Downloader
from .catalog.vrp_mirror import VrpMirror
from .catalog.fdroid import FDroidCatalog
from .config import ANCHOR_DIR, Config, DATA_DIR
from .installer.lepton_quest import LeptonInstaller
from .installer.package_loader import PackageLoader
from .manager.backup import SaveBackupManager
from .manager.installed import InstalledManager
from .manager.launcher import GameLauncher
from .manager.mods import ModManager
from .manager.settings import SettingsManager
from .manager.storage import StorageManager
from .manager.tuning import TuningManager
from .manager.uninstaller import Uninstaller
from .manager.updates import UpdateManager
from .system.protocol import ProtocolHandler
from .system.steamos import (
    ensure_host_podman_fixes,
    get_system_summary,
    install_lepton_request,
)

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class FrameLoadApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.mirror = VrpMirror()
        self.fdroid = FDroidCatalog()
        self.downloader = Downloader.get()
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # Route API calls
        if path == "/api/system":
            self.send_json(get_system_summary())
        elif path == "/api/catalog":
            q = params.get("q", [""])[0]
            sort_by = params.get("sort_by", ["date"])[0]
            sort_order = params.get("sort_order", ["desc"])[0]
            try:
                page = max(1, int(params.get("page", ["1"])[0]))
            except (ValueError, TypeError):
                page = 1
            try:
                per_page = max(1, min(100, int(params.get("per_page", ["36"])[0])))
            except (ValueError, TypeError):
                per_page = 36
            kind = params.get("kind", ["vr"])[0]
            
            if kind == "flat":
                res = self.fdroid.search(
                    query=q, 
                    sort_by=sort_by, 
                    sort_order=sort_order, 
                    page=page, 
                    per_page=per_page
                )
            else:
                res = self.mirror.search(
                    query=q, 
                    sort_by=sort_by, 
                    sort_order=sort_order, 
                    page=page, 
                    per_page=per_page
                )
            self.send_json(res)
        elif path.startswith("/api/catalog/notes/"):
            identifier = path.replace("/api/catalog/notes/", "").strip()
            identifier = os.path.basename(identifier)
            notes = self.mirror.get_game_notes(identifier)
            self.send_json({"id": identifier, "notes": notes})
        elif path.startswith("/api/catalog/game/"):
            identifier = path.replace("/api/catalog/game/", "").strip()
            identifier = os.path.basename(identifier)
            game = self.mirror.get_game(identifier) or self.mirror.games_by_pkg.get(identifier)
            if game:
                g_dict = game.to_dict()
                g_dict["notes"] = self.mirror.get_game_notes(identifier)
                self.send_json({"success": True, "game": g_dict})
            else:
                self.send_json({"error": "Game not found"}, status=HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/thumbnail/"):
            raw_pkg = path.replace("/api/thumbnail/", "").strip()
            if "?" in raw_pkg:
                raw_pkg = raw_pkg.split("?")[0]
            pkg = os.path.basename(raw_pkg)

            # 1. Exact match in local cache
            thumb_path = os.path.join(DATA_DIR, ".meta/thumbnails", f"{pkg}.jpg")
            if os.path.isfile(thumb_path):
                self.serve_file(thumb_path, "image/jpeg")
                return

            # 2. Case-insensitive match in .meta/thumbnails
            meta_thumb_dir = os.path.join(DATA_DIR, ".meta/thumbnails")
            found_thumb = None
            if os.path.isdir(meta_thumb_dir):
                target_lower = f"{pkg.lower()}.jpg"
                try:
                    for entry in os.listdir(meta_thumb_dir):
                        if entry.lower() == target_lower:
                            found_thumb = os.path.join(meta_thumb_dir, entry)
                            break
                except OSError:
                    pass

            if found_thumb and os.path.isfile(found_thumb):
                self.serve_file(found_thumb, "image/jpeg")
                return

            # 3. Try online cover fetching & cache to disk
            from .installer.artwork import ArtworkManager
            fetched = ArtworkManager._fetch_cover_art(pkg, pkg, meta_thumb_dir)
            if fetched and os.path.isfile(fetched):
                self.serve_file(fetched, "image/jpeg")
                return

            # 4. Fallback vector SVG placeholder
            game = self.mirror.games_by_pkg.get(pkg)
            title = game.name if game else pkg
            safe_title = (title[:24] + "...") if len(title) > 24 else title
            svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" viewBox="0 0 600 900">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f1424" />
      <stop offset="50%" stop-color="#171e38" />
      <stop offset="100%" stop-color="#0b0f1a" />
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#00f2fe" />
      <stop offset="100%" stop-color="#4facfe" />
    </linearGradient>
  </defs>
  <rect width="600" height="900" fill="url(#bg)" rx="16"/>
  <rect x="20" y="20" width="560" height="860" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2" rx="12"/>
  <circle cx="300" cy="380" r="80" fill="rgba(0, 242, 254, 0.08)" stroke="url(#accent)" stroke-width="4"/>
  <path d="M260,380 L340,380 M300,340 L300,420" stroke="url(#accent)" stroke-width="6" stroke-linecap="round"/>
  <text x="300" y="540" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="34" font-weight="bold" fill="#ffffff" text-anchor="middle">{safe_title}</text>
  <text x="300" y="585" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" fill="#00f2fe" text-anchor="middle" letter-spacing="3">STEAM FRAME VR</text>
  <rect x="220" y="820" width="160" height="32" rx="16" fill="rgba(255,255,255,0.05)"/>
  <text x="300" y="842" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" fill="rgba(255,255,255,0.6)" text-anchor="middle">FrameLoad</text>
</svg>"""
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(svg_content.encode("utf-8"))
            except BrokenPipeError:
                pass
        elif path == "/api/downloads":
            self.send_json({"tasks": self.downloader.get_all_tasks()})
        elif path == "/api/installed":
            installed = InstalledManager.list_installed()
            self.send_json({"games": installed})
        elif path.startswith("/api/installed/artwork/"):
            raw_pkg = path.replace("/api/installed/artwork/", "").strip()
            if "?" in raw_pkg:
                raw_pkg = raw_pkg.split("?")[0]
            pkg = os.path.basename(raw_pkg)
            dep = InstalledManager.get_game(pkg)
            anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, pkg)) if dep else os.path.join(ANCHOR_DIR, pkg)
            art_dir = os.path.join(anchor, "artwork")
            for name in ("poster.png", "icon.png", "banner.png", "poster.svg"):
                f = os.path.join(art_dir, name)
                if os.path.isfile(f):
                    mime, _ = mimetypes.guess_type(f)
                    self.serve_file(f, mime or "image/png")
                    return
            # Fallback to thumbnail
            thumb_path = os.path.join(DATA_DIR, ".meta/thumbnails", f"{pkg}.jpg")
            if os.path.isfile(thumb_path):
                self.serve_file(thumb_path, "image/jpeg")
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/api/installed/backups":
            pkg = params.get("package", params.get("pkg", [""]))[0]
            self.send_json({"backups": SaveBackupManager.list_backups(pkg)})
        elif path == "/api/installed/mods":
            pkg = params.get("package", params.get("pkg", [""]))[0]
            if not pkg:
                self.send_json({"error": "Missing package parameter"}, status=HTTPStatus.BAD_REQUEST)
            else:
                self.send_json({"mods": ModManager.list_mods(pkg)})
        elif path == "/api/tuning/presets":
            self.send_json({
                "presets": TuningManager.get_presets(),
                "spoof_profiles": TuningManager.get_spoof_profiles()
            })
        elif path == "/api/tuning/global":
            self.send_json(TuningManager.get_global_tuning())
        elif path.startswith("/api/installed/tuning/"):
            pkg = path.replace("/api/installed/tuning/", "").strip()
            if "?" in pkg:
                pkg = pkg.split("?")[0]
            try:
                self.send_json(TuningManager.get_game_tuning(pkg))
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.NOT_FOUND)
        elif path == "/api/tuning/hand-tracking":
            from .installer.hand_tracking import HandTrackingManager
            self.send_json(HandTrackingManager.get_diagnostic_report())
        elif path == "/api/mirrors":
            config = Config.get()
            custom_mirrors = config["mirrors"].get("custom_mirrors", [])
            active_mirror = custom_mirrors[0] if custom_mirrors else {}
            self.send_json({
                "active_base_url": self.mirror.base_url,
                "active_catalog_url": config["mirrors"].get("catalog_url", ""),
                "catalog_game_count": len(self.mirror.games),
                "has_custom_mirror": bool(custom_mirrors),
                "custom_mirror": active_mirror,
                "vrp_config_urls": config["mirrors"].get("vrp_config_urls", []),
                "known_sources": [
                    {
                        "id": "vrsrc",
                        "name": "vrSrc (Community Mirror)",
                        "description": "Active community VR game mirror. Get your public config JSON from t.me/the_vrSrc",
                        "config_source": "https://t.me/the_vrSrc",
                        "website": "https://vrsrc.fyi/",
                        "type": "vrp_compatible",
                        "status": "active",
                        "note": "Paste your vrp-public.json from the Telegram channel. The config contains baseUri and password (base64)."
                    },
                    {
                        "id": "frameload_builtin",
                        "name": "FrameLoad Built-in Catalog",
                        "description": "Curated offline catalog bundled with FrameLoad, updated with each release.",
                        "config_source": "https://github.com/Crypto90/frameload",
                        "website": "https://github.com/Crypto90/frameload",
                        "type": "json_catalog",
                        "status": "active",
                        "note": "Always available offline. Sync pulls latest from GitHub."
                    },
                    {
                        "id": "custom",
                        "name": "Custom Self-Hosted Mirror",
                        "description": "Configure your own VRP-compatible mirror with a custom baseUri and password.",
                        "config_source": None,
                        "website": None,
                        "type": "custom",
                        "status": "manual",
                        "note": "Advanced: host your own rclone/WebDAV VRP-compatible game archive."
                    }
                ]
            })
        elif path == "/api/config":
            self.send_json(Config.get().raw)
        elif path == "/api/storage":
            device_id = params.get("device", [None])[0]
            self.send_json(StorageManager.get_storage_overview(device_id))
        elif path == "/api/updates":
            app_status = UpdateManager.check_app_update()
            game_status = UpdateManager.check_game_updates(self.mirror)
            self.send_json({
                "app": app_status,
                "games": game_status
            })
        elif path == "/api/diagnostics/mirror":
            base_url = "https://go.srcdl1.xyz"
            api_key = "a329d018062813601d60cc6936a4f75ffde4a1ef38349a9973eb9720f9e8a457"
            rclone = os.path.expanduser("~/.local/share/frameload/bin/rclone")
            logs = []
            
            # Test rclone
            cmd = [rclone, "size", ":http:/meta.7z", "--http-url", base_url, "--config", os.devnull, "--header", f"X-API-Key: {api_key}", "-vv"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            logs.append("--- rclone size ---")
            logs.append("Exit Code: " + str(res.returncode))
            for line in res.stderr.splitlines():
                if "ERROR" in line or "NOTICE" in line or "403" in line or "success" in line.lower():
                    logs.append(line)
            
            # Test curl
            logs.append("\\n--- curl test ---")
            curl_cmd = ["curl", "-I", f"{base_url}/meta.7z", "-H", f"X-API-Key: {api_key}", "-A", "rclone/v1.72.1", "-s", "-m", "10"]
            c_res = subprocess.run(curl_cmd, capture_output=True, text=True)
            logs.append("Exit Code: " + str(c_res.returncode))
            logs.append(c_res.stdout)
            logs.append(c_res.stderr)
            
            self.send_json({"success": True, "logs": "\\n".join(logs)})
        elif path == "/" or path == "/index.html":
            index_file = os.path.join(WEB_DIR, "templates", "index.html")
            self.serve_file(index_file, "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            rel = path.replace("/static/", "")
            clean_rel = os.path.normpath(rel).lstrip("/")
            static_dir = os.path.abspath(os.path.join(WEB_DIR, "static"))
            static_file = os.path.abspath(os.path.join(static_dir, clean_rel))
            if not static_file.startswith(static_dir) or not os.path.isfile(static_file):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime, _ = mimetypes.guess_type(static_file)
            self.serve_file(static_file, mime or "application/octet-stream")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_json_body()

        if path == "/api/catalog/sync":
            success = self.mirror.sync_catalog()
            
            # Sync fdroid async or sequentially (doing it sequentially is fine for now)
            self.fdroid.sync()
            
            self.send_json({"success": success, "total_games": len(self.mirror.games) + len(self.fdroid.games)})
        elif path == "/api/mirrors/apply":
            # Accept a vrp-public.json dict with baseUri + password
            config_json = body.get("config", body)  # supports {config:{...}} or direct
            if isinstance(config_json, str):
                try:
                    config_json = json.loads(config_json)
                except Exception:
                    config_json = {}
            result = self.mirror.apply_mirror_config(config_json)
            self.send_json(result)
        elif path == "/api/mirrors/test":
            result = self.mirror.test_mirror_connection()
            self.send_json(result)
        elif path == "/api/mirrors/clear":
            self.mirror.clear_mirror_config()
            self.send_json({"success": True, "message": "Mirror config cleared. Using built-in catalog."})
        elif path == "/api/mirrors/install-rclone":
            messages = []
            ok = self.mirror.install_rclone(lambda m: messages.append(m))
            self.send_json({"success": ok, "messages": messages})
        elif path == "/api/config/mirror":  # Legacy endpoint kept for compatibility
            base_url = body.get("base_url", "").strip()
            password = body.get("password", "").strip()
            result = self.mirror.apply_mirror_config({"baseUri": base_url, "password": password})
            self.send_json(result)
        elif path == "/api/catalog/import":
            content = body.get("content", "")
            format_type = body.get("format", "gamelist")
            if format_type == "json":
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        new_games = []
                        for item in data:
                            if isinstance(item, dict):
                                g = CatalogGame(
                                    name=item["name"],
                                    release_name=item["release_name"],
                                    package_name=item["package_name"],
                                    version_code=str(item.get("version_code", "1")),
                                    last_updated=item.get("last_updated", ""),
                                    size_bytes=int(item.get("size_bytes", 0)),
                                    id=item.get("id", ""),
                                    thumbnail_url=item.get("thumbnail_url", ""),
                                    kind=item.get("kind", "quest")
                                )
                                new_games.append(g)
                        if new_games:
                            self.mirror.games = new_games
                            self.mirror.games_by_id = {g.id: g for g in new_games}
                            self.mirror.games_by_pkg = {g.package_name: g for g in new_games}
                            self.mirror.save_cache()
                            self.send_json({"success": True, "total_games": len(self.mirror.games)})
                            return
                    elif isinstance(data, dict) and "baseUri" in data:
                        self.mirror.base_url = data["baseUri"].rstrip("/")
                        if "password" in data:
                            b64 = data["password"]
                            self.mirror.password = base64.b64decode(b64).decode("utf-8", errors="replace") if b64 else ""
                        self.send_json({"success": True, "base_url": self.mirror.base_url})
                        return
                    self.send_json({"error": "Unsupported JSON format"}, status=HTTPStatus.BAD_REQUEST)
                except Exception as e:
                    self.send_json({"error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)
            else:
                gamelist_path = os.path.join(DATA_DIR, "VRP-GameList.txt")
                with open(gamelist_path, "w", encoding="utf-8") as f:
                    f.write(content)
                success = self.mirror.parse_gamelist_file(gamelist_path)
                self.send_json({"success": success, "total_games": len(self.mirror.games)})
        elif path == "/api/downloads/queue":
            game_id = body.get("game_id", "")
            device_id = body.get("device_id")
            game = self.mirror.get_game(game_id) or self.fdroid.get_game(game_id)
            if not game:
                self.send_json({"error": "Game not found in catalog"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                task = self.downloader.add_to_queue(game, device_id=device_id)
                self.send_json({"success": True, "task": task.to_dict()})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"error": f"Failed to queue download: {str(e)}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/downloads/cancel":
            task_id = body.get("task_id", "")
            success = self.downloader.cancel_task(task_id)
            self.send_json({"success": success})
        elif path == "/api/installed/launch":
            pkg = body.get("package", "")
            try:
                res = GameLauncher.launch(pkg)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/stop":
            pkg = body.get("package", "")
            res = GameLauncher.stop(pkg)
            self.send_json(res)
        elif path == "/api/installed/settings" or path == "/api/installed/tuning":
            pkg = body.get("package", "")
            settings = body.get("settings", body)
            try:
                updated = TuningManager.save_game_tuning(pkg, settings)
                self.send_json({"success": True, "package": pkg, "settings": updated})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/tuning/preset":
            pkg = body.get("package", "")
            preset = body.get("preset", "steam_frame_turbo")
            try:
                updated = TuningManager.apply_preset(pkg, preset)
                self.send_json({"success": True, "package": pkg, "preset": preset, "settings": updated})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/tuning/global":
            settings = body.get("settings", body)
            try:
                updated = TuningManager.save_global_tuning(settings)
                self.send_json({"success": True, "settings": updated})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/tuning/batch-apply":
            preset = body.get("preset", "steam_frame_turbo")
            packages = body.get("packages")
            try:
                res = TuningManager.batch_apply(preset, packages)
                self.send_json({"success": True, "result": res})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/backup":
            pkg = body.get("package", "")
            try:
                res = SaveBackupManager.backup_saves(pkg)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/restore":
            pkg = body.get("package", "")
            filename = body.get("filename", "")
            try:
                success = SaveBackupManager.restore_backup(pkg, filename)
                self.send_json({"success": success})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/uninstall":
            pkg = body.get("package", "")
            keep_saves = body.get("keep_saves", False)
            try:
                res = Uninstaller.uninstall(pkg, keep_saves=keep_saves)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/storage/batch-uninstall":
            packages = body.get("packages", [])
            keep_saves = body.get("keep_saves", False)
            try:
                res = StorageManager.batch_uninstall(packages, keep_saves=keep_saves)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/storage/clean-cache":
            clear_downloads = body.get("clear_downloads", True)
            clear_shaders = body.get("clear_shaders", False)
            try:
                res = StorageManager.clean_cache(clear_downloads, clear_shaders)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/updates/app":
            res = UpdateManager.perform_app_update()
            self.send_json(res)
        elif path == "/api/updates/game":
            pkg = body.get("package", "")
            try:
                res = UpdateManager.update_game(pkg, self.mirror)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/updates/all-games":
            try:
                res = UpdateManager.update_all_games(self.mirror)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/storage/move":
            pkg = body.get("package", "")
            target_device = body.get("target_device_id", "internal")
            try:
                res = StorageManager.move_game(pkg, target_device)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/storage/batch-move":
            packages = body.get("packages", [])
            target_device = body.get("target_device_id", "internal")
            try:
                res = StorageManager.batch_move(packages, target_device)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/local/inspect":
            source_path = body.get("source_path") or body.get("apk_path", "")
            try:
                res = PackageLoader.inspect_source(source_path)
                self.send_json({"success": True, "inspection": res})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
        elif path == "/api/local/install":
            source_path = body.get("source_path") or body.get("apk_path", "")
            title = body.get("title", "")
            obb_path = body.get("obb_path")
            force_flat = body.get("force_flat", False)
            window_preset = body.get("window_preset")
            device_id = body.get("device_id")
            if not os.path.exists(source_path):
                self.send_json({"error": f"Path not found: {source_path}"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                res = PackageLoader.install_source(
                    source_path=source_path,
                    title=title,
                    obb_path=obb_path,
                    device_id=device_id,
                    force_flat=force_flat,
                    window_preset=window_preset
                )
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/mods/inject":
            pkg = body.get("package", "")
            source_path = body.get("source_path", "")
            mod_name = body.get("mod_name", "")
            target_subpath = body.get("target_subpath", "")
            if not pkg or not source_path:
                self.send_json({"error": "Missing package or source_path"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                res = ModManager.inject_mod(pkg, source_path, mod_name=mod_name, target_subpath=target_subpath)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/installed/mods/delete":
            pkg = body.get("package", "")
            mod_id = body.get("mod_id", "")
            if not pkg or not mod_id:
                self.send_json({"error": "Missing package or mod_id"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                ok = ModManager.delete_mod(pkg, mod_id)
                self.send_json({"success": ok})
            except Exception as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        elif path == "/api/system/protocol":
            url = body.get("url", "")
            res = ProtocolHandler.handle_url(url)
            self.send_json(res)
        elif path == "/api/system/install_lepton":
            success = install_lepton_request()
            self.send_json({"success": success})
        elif path == "/api/system/fix_keyring":
            fixes = ensure_host_podman_fixes()
            self.send_json({"success": True, "fixes": fixes})
        elif path == "/api/system/uninstall-app":
            confirm = body.get("confirm", "")
            if confirm != "UNINSTALL":
                self.send_json({"error": "Confirmation required. Send confirm='UNINSTALL'."}, status=HTTPStatus.BAD_REQUEST)
                return
            purge_games = bool(body.get("purge_games", False))
            keep_backups = bool(body.get("keep_backups", False))

            def _deferred_uninstall():
                time.sleep(1.0)
                Uninstaller.uninstall_frameload_app(purge_games=purge_games, keep_backups=keep_backups)
                os._exit(0)

            threading.Thread(target=_deferred_uninstall, daemon=True).start()
            self.send_json({
                "success": True,
                "message": "FrameLoad uninstallation initiated. The daemon is shutting down and all traces are being removed."
            })
        elif path == "/api/config":
            cfg = Config.get()
            for k, v in body.items():
                cfg[k] = v
            cfg.save()
            self.send_json({"success": True, "config": cfg.raw})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def read_json_body(self) -> Dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw)
        except Exception:
            pass
        return {}

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_file(self, file_path: str, content_type: str) -> None:
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def log_error(self, format: str, *args: Any) -> None:
        msg = format % args if args else format
        sys.stderr.write(f"{RED}✖ [HTTP Error] {msg}{RESET}\n")

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard request logs unless in debug mode
        pass


def run_server(host: str = "0.0.0.0", port: int = 5050) -> None:
    # Hook auto-installer into downloader
    downloader = Downloader.get()

    def on_download_complete(task):
        config = Config.get()
        if not config["download"].get("auto_install_on_download", True):
            task.status = "ready_to_install"
            return

        if not task.target_apk:
            task.status = "error"
            task.error_message = "No APK found in extracted game folder."
            sys.stderr.write(f"{RED}✖ [Auto-Install Error]: {task.error_message}{RESET}\n")
            return

        task.status = "installing"
        # Find obb folder if present
        obb_dir = os.path.join(task.extracted_path, "Android/obb")
        if not os.path.isdir(obb_dir):
            obb_dir = os.path.join(task.extracted_path, "obb")
            if not os.path.isdir(obb_dir):
                obb_dir = None

        target_device = getattr(task, "device_id", None) or config.get("storage", {}).get("default_device_id", "internal")
        try:
            LeptonInstaller.install_quest_game(
                package_name=task.game.package_name,
                title=task.game.name,
                apk_path=task.target_apk,
                obb_path=obb_dir,
                force_flat=(task.game.kind == "flat"),
                device_id=target_device
            )
            task.status = "completed"
            print(f"{GREEN}✔ [Auto-Install Success]: {task.game.name} installed successfully!{RESET}")
        except Exception as exc:
            task.status = "error"
            task.error_message = str(exc)
            sys.stderr.write(f"{RED}✖ [Auto-Install Failed]: {exc}{RESET}\n")

    downloader.set_complete_hook(on_download_complete)

    server = ThreadingHTTPServer((host, port), FrameLoadApiHandler)
    print(f"{CYAN}============================================================{RESET}")
    print(f"🚀 {GREEN}FrameLoad Server running at http://{host}:{port}{RESET}")
    print(f"📱 Access directly on Steam Frame or over Wi-Fi from any browser")
    print(f"{CYAN}============================================================{RESET}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Stopping FrameLoad server...{RESET}")
        server.server_close()


if __name__ == "__main__":
    run_server()
