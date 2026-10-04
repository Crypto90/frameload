"""High-performance multi-threaded HTTP server and REST API for FrameLoad."""
from __future__ import annotations

import json
import mimetypes
import os
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .catalog.downloader import Downloader
from .catalog.vrp_mirror import VrpMirror
from .config import Config, DATA_DIR
from .installer.lepton_quest import LeptonInstaller
from .manager.backup import SaveBackupManager
from .manager.installed import InstalledManager
from .manager.launcher import GameLauncher
from .manager.settings import SettingsManager
from .manager.storage import StorageManager
from .manager.uninstaller import Uninstaller
from .system.steamos import (
    ensure_host_podman_fixes,
    get_system_summary,
    install_lepton_request,
)

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class FrameLoadApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.mirror = VrpMirror()
        self.downloader = Downloader.get()
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_HEAD(self) -> None:
        self.do_GET()

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
            page = int(params.get("page", [1])[0])
            per_page = int(params.get("per_page", [36])[0])
            res = self.mirror.search(query=q, sort_by=sort_by, sort_order=sort_order, page=page, per_page=per_page)
            self.send_json(res)
        elif path.startswith("/api/thumbnail/"):
            pkg = path.replace("/api/thumbnail/", "").strip()
            thumb_path = os.path.join(DATA_DIR, ".meta/thumbnails", f"{pkg}.jpg")
            if os.path.isfile(thumb_path):
                self.serve_file(thumb_path, "image/jpeg")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/api/downloads":
            self.send_json({"tasks": self.downloader.get_all_tasks()})
        elif path == "/api/installed":
            installed = InstalledManager.list_installed()
            self.send_json({"games": installed})
        elif path.startswith("/api/installed/artwork/"):
            pkg = path.replace("/api/installed/artwork/", "").strip()
            from .config import ANCHOR_DIR
            art_dir = os.path.join(ANCHOR_DIR, pkg, "artwork")
            for name in ("poster.png", "icon.png", "banner.png", "poster.svg"):
                f = os.path.join(art_dir, name)
                if os.path.isfile(f):
                    mime, _ = mimetypes.guess_type(f)
                    self.serve_file(f, mime or "image/png")
                    return
            self.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/api/installed/backups":
            pkg = params.get("package", [""])[0]
            self.send_json({"backups": SaveBackupManager.list_backups(pkg)})
        elif path == "/api/config":
            self.send_json(Config.get().raw)
        elif path == "/api/storage":
            device_id = params.get("device", [None])[0]
            self.send_json(StorageManager.get_storage_overview(device_id))
        elif path == "/" or path == "/index.html":
            index_file = os.path.join(WEB_DIR, "templates", "index.html")
            self.serve_file(index_file, "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            rel = path.replace("/static/", "")
            static_file = os.path.join(WEB_DIR, "static", rel)
            if os.path.isfile(static_file):
                mime, _ = mimetypes.guess_type(static_file)
                self.serve_file(static_file, mime or "application/octet-stream")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_json_body()

        if path == "/api/catalog/sync":
            success = self.mirror.sync_catalog()
            self.send_json({"success": success, "total_games": len(self.mirror.games)})
        elif path == "/api/downloads/queue":
            game_id = body.get("game_id", "")
            game = self.mirror.get_game(game_id)
            if not game:
                self.send_json({"error": "Game not found in catalog"}, status=HTTPStatus.NOT_FOUND)
                return
            task = self.downloader.add_to_queue(game)
            self.send_json({"success": True, "task": task.to_dict()})
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
        elif path == "/api/installed/settings":
            pkg = body.get("package", "")
            settings = body.get("settings", {})
            try:
                updated = SettingsManager.update_settings(pkg, settings)
                self.send_json({"success": True, "settings": updated})
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
        elif path == "/api/local/install":
            apk_path = body.get("apk_path", "")
            title = body.get("title", "")
            obb_path = body.get("obb_path")
            force_flat = body.get("force_flat", False)
            if not os.path.isfile(apk_path):
                self.send_json({"error": f"File not found: {apk_path}"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not title:
                title = os.path.basename(apk_path).replace(".apk", "")
            from .installer.apk_patcher import ApkPatcher
            analysis = ApkPatcher.inspect(apk_path)
            res = LeptonInstaller.install_quest_game(
                package_name=analysis.package_name,
                title=title,
                apk_path=apk_path,
                obb_path=obb_path,
                force_flat=force_flat
            )
            self.send_json(res)
        elif path == "/api/system/install_lepton":
            success = install_lepton_request()
            self.send_json({"success": success})
        elif path == "/api/system/fix_keyring":
            fixes = ensure_host_podman_fixes()
            self.send_json({"success": True, "fixes": fixes})
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
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

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
        except Exception:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

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
            return

        task.status = "installing"
        # Find obb folder if present
        obb_dir = os.path.join(task.extracted_path, "Android/obb")
        if not os.path.isdir(obb_dir):
            obb_dir = os.path.join(task.extracted_path, "obb")
            if not os.path.isdir(obb_dir):
                obb_dir = None

        LeptonInstaller.install_quest_game(
            package_name=task.game.package_name,
            title=task.game.name,
            apk_path=task.target_apk,
            obb_path=obb_dir,
            force_flat=(task.game.kind == "flat")
        )
        task.status = "completed"

    downloader.set_complete_hook(on_download_complete)

    server = ThreadingHTTPServer((host, port), FrameLoadApiHandler)
    print(f"============================================================")
    print(f"🚀 FrameLoad Server running at http://{host}:{port}")
    print(f"📱 Access directly on Steam Frame or over Wi-Fi from any browser")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping FrameLoad server...")
        server.server_close()
