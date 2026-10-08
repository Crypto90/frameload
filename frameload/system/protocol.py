"""One-click links (frameload://) for SteamOS and Steam Frame.

    frameload://install?url=https://example.org/app.apk&title=My%20App
    frameload://sideload?path=/home/steamos/Downloads/app.apk&title=My%20App
    frameload://launch?package=org.example.app

A link can come from any web page, so nothing is downloaded or installed until the person wearing
the headset confirms it in the dashboard.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import urllib.parse
import uuid
from typing import Any, Dict, List

MAX_PENDING = 10
PENDING_TTL = 15 * 60


class PendingLinks:
    """Install requests waiting for confirmation. Lives in the server process."""
    _lock = threading.Lock()
    _items: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def add(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        with cls._lock:
            now = time.time()
            for key in [k for k, v in cls._items.items() if now - v["created"] > PENDING_TTL]:
                del cls._items[key]
            item = dict(item, id=uuid.uuid4().hex[:12], created=now)
            cls._items[item["id"]] = item
            for key in sorted(cls._items, key=lambda k: cls._items[k]["created"])[:-MAX_PENDING]:
                del cls._items[key]
            return item

    @classmethod
    def all(cls) -> List[Dict[str, Any]]:
        with cls._lock:
            now = time.time()
            return [v for v in cls._items.values() if now - v["created"] <= PENDING_TTL]

    @classmethod
    def take(cls, link_id: str) -> Dict[str, Any]:
        with cls._lock:
            item = cls._items.pop(link_id, None)
        if not item or time.time() - item["created"] > PENDING_TTL:
            raise KeyError("That install request is no longer waiting.")
        return item


class ProtocolHandler:
    @staticmethod
    def handle_url(url: str) -> Dict[str, Any]:
        """Parses a frameload:// link. Installs are queued for confirmation, never run directly."""
        if not url.startswith("frameload://"):
            return {"success": False, "error": f"Invalid protocol in URL: {url}"}

        parsed = urllib.parse.urlparse(url)
        action = parsed.netloc or parsed.path.lstrip("/")
        params = urllib.parse.parse_qs(parsed.query)

        def first(*names: str) -> str:
            for name in names:
                if params.get(name):
                    return params[name][0]
            return ""

        if action in ("install", "download"):
            dl_url = first("url")
            target = urllib.parse.urlparse(dl_url)
            if target.scheme != "https" or not target.netloc:
                return {"success": False, "error": "Install links must point to an https:// address."}
            if not target.path.lower().endswith(".apk"):
                return {"success": False, "error": "Install links must point to an .apk file."}
            # The query parser decoded the address; encode its path again so spaces survive.
            dl_url = urllib.parse.urlunparse(target._replace(path=urllib.parse.quote(target.path, safe="/%:@+~")))
            filename = os.path.basename(urllib.parse.unquote(target.path))
            item = PendingLinks.add({
                "kind": "download", "url": dl_url, "host": target.netloc,
                "title": (first("title") or os.path.splitext(filename)[0])[:120],
            })
            return {"success": True, "action": "install", "needs_confirmation": True, "pending_id": item["id"]}

        if action == "sideload":
            source = first("source", "path")
            if not source or not os.path.exists(source):
                return {"success": False, "error": f"Source path not found: {source}"}
            item = PendingLinks.add({
                "kind": "sideload", "path": source, "host": "this headset",
                "title": (first("title") or os.path.basename(source.rstrip("/")))[:120],
                "device": first("device"),
            })
            return {"success": True, "action": "sideload", "needs_confirmation": True, "pending_id": item["id"]}

        if action == "launch":
            pkg = first("package", "pkg")
            if not pkg:
                return {"success": False, "error": "Missing 'package' parameter in frameload://launch"}
            from ..manager.launcher import GameLauncher
            return {"success": True, "action": "launch", "package": pkg, "result": GameLauncher.launch(pkg)}

        if action == "sync":
            from ..catalog.vrp_mirror import VrpMirror
            return {"success": VrpMirror().sync_catalog(), "action": "sync"}

        return {"success": False, "error": f"Unknown action: {action}"}

    @staticmethod
    def confirm(link_id: str) -> Dict[str, Any]:
        """Carries out an install request the user approved."""
        item = PendingLinks.take(link_id)
        if item["kind"] == "sideload":
            from ..installer.package_loader import PackageLoader
            result = PackageLoader.install_source(source_path=item["path"], title=item["title"],
                                                  device_id=item.get("device") or None)
            return {"success": True, "action": "sideload", "result": result}

        from ..catalog.downloader import Downloader
        from ..catalog.models import CatalogGame
        game = CatalogGame(
            name=item["title"], release_name=item["url"], package_name="link.download",
            version_code="1", last_updated="", size_bytes=0, download_url=item["url"], source="link",
        )
        task = Downloader.get().add_to_queue(game)
        return {"success": True, "action": "install", "task_id": task.id, "title": game.name}

    @staticmethod
    def register_protocol() -> bool:
        """Registers frameload:// URL handler with xdg-mime on SteamOS."""
        try:
            subprocess.run(["xdg-mime", "default", "frameload.desktop", "x-scheme-handler/frameload"], capture_output=True)
            return True
        except OSError:
            return False
