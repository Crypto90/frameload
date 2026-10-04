"""VRP public mirror and catalog manager for FrameLoad."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from ..config import Config, DATA_DIR
from .extractor import extract_archive
from .models import CatalogGame

CATALOG_CACHE_FILE = os.path.join(DATA_DIR, "catalog_cache.json")
GAMELIST_FILE = os.path.join(DATA_DIR, "VRP-GameList.txt")


class VrpMirror:
    def __init__(self) -> None:
        self.config = Config.get()
        self.base_url: str = ""
        self.password: str = ""
        self.games: List[CatalogGame] = []
        self.games_by_id: Dict[str, CatalogGame] = {}
        self.games_by_pkg: Dict[str, CatalogGame] = {}
        self.load_cache()

    def update_mirror_config(self) -> bool:
        """Fetches vrp-public.json to get active baseUri and password."""
        urls = self.config["mirrors"].get("vrp_config_urls", [
            "https://vrpirates.wiki/downloads/vrp-public.json"
        ])

        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad/1.0"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        base_uri = data.get("baseUri", "").rstrip("/")
                        b64_pw = data.get("password", "")
                        if base_uri and b64_pw:
                            self.base_url = base_uri
                            self.password = base64.b64decode(b64_pw).decode("utf-8", errors="replace")
                            return True
            except Exception as e:
                print(f"[FrameLoad] Failed to fetch mirror config from {url}: {e}")

        # Fallback to defaults if mirror unreachable
        if not self.base_url:
            self.base_url = "https://public.vrpirates.wiki"
        return False

    def sync_catalog(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Downloads meta.7z, extracts VRP-GameList.txt, and updates local catalog."""
        if status_callback:
            status_callback("Connecting to mirror...")

        if not self.base_url or not self.password:
            self.update_mirror_config()

        if not self.base_url:
            if status_callback:
                status_callback("Could not resolve mirror URL.")
            return False

        meta_url = f"{self.base_url}/meta.7z"
        meta_archive = os.path.join(DATA_DIR, "meta.7z")

        if status_callback:
            status_callback(f"Downloading catalog metadata from {meta_url}...")

        try:
            req = urllib.request.Request(meta_url, headers={"User-Agent": "FrameLoad/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(meta_archive, "wb") as out_f:
                shutil_copy(resp, out_f)
        except Exception as e:
            if status_callback:
                status_callback(f"Download meta.7z failed: {e}. Checking local cache...")
            if os.path.isfile(GAMELIST_FILE):
                return self.parse_gamelist_file()
            return False

        if status_callback:
            status_callback("Decompressing catalog metadata...")

        success = extract_archive(meta_archive, DATA_DIR, password=self.password)
        try:
            os.remove(meta_archive)
        except OSError:
            pass

        if not success:
            if status_callback:
                status_callback("Failed to extract meta.7z.")
            return False

        if status_callback:
            status_callback("Parsing game catalog...")

        parsed = self.parse_gamelist_file()
        if parsed and status_callback:
            status_callback(f"Catalog updated successfully! {len(self.games)} titles available.")
        return parsed

    def parse_gamelist_file(self) -> bool:
        if not os.path.isfile(GAMELIST_FILE):
            return False

        new_games = []
        try:
            with open(GAMELIST_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            # Skip header if present
            if lines and ";" in lines[0] and "Name" in lines[0]:
                lines = lines[1:]

            for line in lines:
                parts = line.strip().split(";")
                if len(parts) >= 6:
                    name = parts[0].strip()
                    release_name = parts[1].strip()
                    pkg_name = parts[2].strip()
                    version_code = parts[3].strip()
                    last_updated = parts[4].strip()
                    try:
                        size_bytes = int(parts[5].strip())
                    except ValueError:
                        size_bytes = 0

                    thumb_path = os.path.join(DATA_DIR, ".meta/thumbnails", f"{pkg_name}.jpg")
                    thumb_url = f"/api/thumbnail/{pkg_name}" if os.path.isfile(thumb_path) else ""

                    game = CatalogGame(
                        name=name,
                        release_name=release_name,
                        package_name=pkg_name,
                        version_code=version_code,
                        last_updated=last_updated,
                        size_bytes=size_bytes,
                        thumbnail_url=thumb_url,
                        kind="quest"
                    )
                    new_games.append(game)

            if new_games:
                self.games = new_games
                self.games_by_id = {g.id: g for g in new_games}
                self.games_by_pkg = {g.package_name: g for g in new_games}
                self.save_cache()
                return True
        except Exception as e:
            print(f"[FrameLoad] Error parsing {GAMELIST_FILE}: {e}")

        return False

    def save_cache(self) -> None:
        try:
            data = [g.to_dict() for g in self.games]
            with open(CATALOG_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError as e:
            print(f"[FrameLoad] Error saving catalog cache: {e}")

    def load_cache(self) -> None:
        if os.path.isfile(CATALOG_CACHE_FILE):
            try:
                with open(CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.games = []
                for item in raw:
                    g = CatalogGame(
                        name=item["name"],
                        release_name=item["release_name"],
                        package_name=item["package_name"],
                        version_code=item.get("version_code", ""),
                        last_updated=item.get("last_updated", ""),
                        size_bytes=item.get("size_bytes", 0),
                        id=item.get("id", ""),
                        thumbnail_url=item.get("thumbnail_url", ""),
                        kind=item.get("kind", "quest")
                    )
                    self.games.append(g)
                self.games_by_id = {g.id: g for g in self.games}
                self.games_by_pkg = {g.package_name: g for g in self.games}
            except Exception as e:
                print(f"[FrameLoad] Error loading catalog cache: {e}")
        elif os.path.isfile(GAMELIST_FILE):
            self.parse_gamelist_file()

    def search(
        self,
        query: str = "",
        sort_by: str = "date",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = 50
    ) -> Dict[str, Any]:
        """Search, filter, and paginate the game catalog."""
        results = self.games

        if query:
            q = query.lower().strip()
            results = [
                g for g in results
                if q in g.name.lower() or q in g.package_name.lower() or q in g.release_name.lower()
            ]

        # Sorting
        if sort_by == "name":
            results.sort(key=lambda g: g.name.lower(), reverse=(sort_order == "desc"))
        elif sort_by == "size":
            results.sort(key=lambda g: g.size_bytes, reverse=(sort_order == "desc"))
        elif sort_by == "date":
            results.sort(key=lambda g: g.last_updated, reverse=(sort_order == "desc"))

        total_count = len(results)
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = results[start_idx:end_idx]

        return {
            "items": [g.to_dict() for g in page_items],
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page
        }

    def get_game(self, game_id: str) -> Optional[CatalogGame]:
        return self.games_by_id.get(game_id)


def shutil_copy(src, dst, chunk_size=1024 * 64):
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        dst.write(chunk)
