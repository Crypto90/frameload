"""One-click deep linking (frameload:// protocol handler) for SteamOS and Steam Frame."""
from __future__ import annotations

import os
import subprocess
import urllib.parse
from typing import Any, Dict

from ..config import HOME


class ProtocolHandler:
    @staticmethod
    def handle_url(url: str) -> Dict[str, Any]:
        """Parses and executes a frameload:// deep link URL."""
        if not url.startswith("frameload://"):
            return {"success": False, "error": f"Invalid protocol in URL: {url}"}

        # Parse scheme and action
        parsed = urllib.parse.urlparse(url)
        action = parsed.netloc or parsed.path.lstrip("/")
        params = urllib.parse.parse_qs(parsed.query)

        # 1. frameload://install?url=...&title=...&pkg=...
        if action in ("install", "download"):
            dl_url = params.get("url", [""])[0]
            title = params.get("title", [""])[0]
            pkg = params.get("pkg", [""])[0] or params.get("package", [""])[0]
            if not dl_url:
                return {"success": False, "error": "Missing 'url' parameter in frameload://install"}

            from ..catalog.downloader import Downloader
            from ..catalog.vrp_mirror import CatalogGame
            downloader = Downloader.get()

            game = CatalogGame(
                name=title or pkg or "Sideloaded Game",
                release_name=title or pkg or "Sideloaded Game",
                package_name=pkg or "custom.download",
                version_code="1.0",
                last_updated="",
                size_bytes=0,
            )
            task = downloader.add_to_queue(game)
            return {
                "success": True,
                "action": "install",
                "task_id": task.id,
                "title": game.name,
                "package": game.package_name
            }

        # 2. frameload://sideload?source=...&title=...
        elif action == "sideload":
            source = params.get("source", [""])[0] or params.get("path", [""])[0]
            title = params.get("title", [""])[0]
            device = params.get("device", [None])[0]
            if not source or not os.path.exists(source):
                return {"success": False, "error": f"Source path not found: {source}"}

            from ..installer.package_loader import PackageLoader
            res = PackageLoader.install_source(source_path=source, title=title, device_id=device)
            return {"success": True, "action": "sideload", "result": res}

        # 3. frameload://launch?package=...
        elif action == "launch":
            pkg = params.get("package", [""])[0] or params.get("pkg", [""])[0]
            if not pkg:
                return {"success": False, "error": "Missing 'package' parameter in frameload://launch"}

            from ..manager.launcher import GameLauncher
            res = GameLauncher.launch(pkg)
            return {"success": True, "action": "launch", "package": pkg, "result": res}

        # 4. frameload://sync
        elif action == "sync":
            from ..catalog.vrp_mirror import VrpMirror
            mirror = VrpMirror()
            ok = mirror.sync_catalog()
            return {"success": ok, "action": "sync"}

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    @staticmethod
    def register_protocol() -> bool:
        """Registers frameload:// URL handler with xdg-mime on SteamOS."""
        desktop_file = "frameload.desktop"
        try:
            subprocess.run(["xdg-mime", "default", desktop_file, "x-scheme-handler/frameload"], capture_output=True)
            return True
        except OSError:
            return False
