"""VRP mirror, local caching, and catalog manager for FrameLoad."""
from __future__ import annotations

import base64
import json
import os
import shutil
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from ..config import Config, DATA_DIR
from .extractor import extract_archive
from .models import CatalogGame
from . import vrsrc as _vrsrc

CATALOG_CACHE_FILE = os.path.join(DATA_DIR, "catalog_cache.json")
GAMELIST_FILE = os.path.join(DATA_DIR, "VRP-GameList.txt")


class VrpMirror:
    def __init__(self) -> None:
        self.config = Config.get()
        self.base_url: str = "https://go.srcdl1.xyz"
        self.password: str = "gL59VfgPxoHR"
        self.games: List[CatalogGame] = []
        self.games_by_id: Dict[str, CatalogGame] = {}
        self.games_by_pkg: Dict[str, CatalogGame] = {}
        self.load_cache()

    def update_mirror_config(self) -> bool:
        """Fetches vrp-public.json or custom mirror config to get active baseUri and password."""
        urls = self.config["mirrors"].get("vrp_config_urls", [])

        # Check local vrp-public.json in DATA_DIR or FRAMELOAD_DIR first
        local_candidates = [
            os.path.join(DATA_DIR, "vrp-public.json"),
            os.path.join(os.path.dirname(DATA_DIR), "vrp-public.json"),
            os.path.join(os.path.dirname(__file__), "vrp-public.json"),
        ]
        for lpath in local_candidates:
            if os.path.isfile(lpath):
                try:
                    with open(lpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    base_uri = data.get("baseUri", "").rstrip("/")
                    b64_pw = data.get("password", "")
                    if base_uri:
                        self.base_url = base_uri
                        self.password = base64.b64decode(b64_pw).decode("utf-8", errors="replace") if b64_pw else ""
                        return True
                except Exception as e:
                    print(f"[FrameLoad] Error loading local mirror config from {lpath}: {e}")

        # Try remote config URLs
        for url in urls:
            if not url or not url.startswith("http"):
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if resp.status == 200:
                        content = resp.read().decode("utf-8").strip()
                        if content:
                            data = json.loads(content)
                            base_uri = data.get("baseUri", "").rstrip("/")
                            b64_pw = data.get("password", "")
                            if base_uri:
                                self.base_url = base_uri
                                self.password = base64.b64decode(b64_pw).decode("utf-8", errors="replace") if b64_pw else ""
                                return True
            except Exception as e:
                print(f"[FrameLoad] Mirror config check notice for {url}: {e}")

        return False

    def apply_mirror_config(self, config_data: dict) -> dict:
        """Apply a vrp-public.json config dict (baseUri + password).
        Accepts base64-encoded passwords (VRP/vrSrc format) or plain text."""
        base_uri = config_data.get("baseUri", "").strip().rstrip("/")
        raw_pw = config_data.get("password", "").strip()

        if not base_uri:
            return {"success": False, "error": "Missing baseUri in config"}

        # Detect if password is base64-encoded (vrSrc format)
        decoded_pw = raw_pw
        if raw_pw:
            try:
                candidate = base64.b64decode(raw_pw + "==").decode("utf-8")
                if candidate.isprintable() and 4 <= len(candidate) <= len(raw_pw):
                    decoded_pw = candidate
            except Exception:
                pass

        self.base_url = base_uri
        self.password = decoded_pw
        self.save_mirror_config(base_uri, raw_pw)

        self.config["mirrors"]["custom_mirrors"] = [{"base_uri": base_uri, "password": raw_pw}]
        self.config.save()

        return {"success": True, "base_url": self.base_url,
                "message": f"Mirror configured: {self.base_url}"}

    def save_mirror_config(self, base_uri: str, password_b64: str) -> None:
        """Persist vrp-public.json to DATA_DIR for future sessions."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            config_path = os.path.join(DATA_DIR, "vrp-public.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"baseUri": base_uri, "password": password_b64}, f, indent=2)
        except OSError as e:
            print(f"[FrameLoad] Could not save mirror config: {e}")

    def clear_mirror_config(self) -> None:
        """Remove saved mirror config and reset to built-in catalog."""
        self.base_url = ""
        self.password = ""
        self.config["mirrors"]["custom_mirrors"] = []
        self.config.save()
        
        # Remove vrp-public.json config
        config_path = os.path.join(DATA_DIR, "vrp-public.json")
        if os.path.isfile(config_path):
            try:
                os.remove(config_path)
            except OSError:
                pass
                
        # Clear catalog cache
        if os.path.isfile(CATALOG_CACHE_FILE):
            try:
                os.remove(CATALOG_CACHE_FILE)
            except OSError:
                pass
        
        # Clear VRP-GameList.txt
        if os.path.isfile(GAMELIST_FILE):
            try:
                os.remove(GAMELIST_FILE)
            except OSError:
                pass
        
        self.games = []
        self.games_by_id = {}
        self.games_by_pkg = {}

    def test_mirror_connection(self) -> dict:
        """Test connectivity to the configured mirror using rclone."""
        if not self.base_url:
            return {"success": False, "error": "No mirror configured"}
        return _vrsrc.test_connection(self.base_url, self.password)

    def install_rclone(self, status_cb: Optional[Callable[[str], None]] = None) -> bool:
        """Install rclone to the FrameLoad bin directory."""
        return _vrsrc.install_rclone(status_cb)

    def load_bundled_catalog(self, merge: bool = False) -> bool:
        """Removed: Bundled catalog is no longer supported."""
        return False

    def load_cache(self) -> None:
        """Loads catalog cache from disk, local VRP-GameList.txt, or bundled catalog."""
        # 1. Try saved catalog cache
        if os.path.isfile(CATALOG_CACHE_FILE):
            try:
                with open(CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if raw and isinstance(raw, list) and len(raw) > 0:
                    self.games = []
                    for item in raw:
                        g = CatalogGame(
                            name=item["name"],
                            release_name=item["release_name"],
                            package_name=item["package_name"],
                            version_code=str(item.get("version_code", "")),
                            last_updated=item.get("last_updated", ""),
                            size_bytes=int(item.get("size_bytes", 0)),
                            id=item.get("id", ""),
                            thumbnail_url=item.get("thumbnail_url", ""),
                            kind=item.get("kind", "quest"),
                            downloads=int(item.get("downloads", 0)),
                            rating=float(item.get("rating", 0.0)),
                            rating_count=int(item.get("rating_count", 0)),
                            notes=item.get("notes", ""),
                        )
                        self.games.append(g)
                    self.games_by_id = {g.id: g for g in self.games}
                    self.games_by_pkg = {g.package_name: g for g in self.games}
                    if len(self.games) >= 50:
                        return
            except Exception as e:
                print(f"[FrameLoad] Error loading catalog cache: {e}")

        # 2. Try VRP-GameList.txt / GameList.txt if present
        if self.parse_gamelist_file():
            if len(self.games) >= 50:
                return

    def sync_catalog(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Synchronizes catalog from online endpoints or GitHub raw updates with graceful fallback."""
        if status_callback:
            status_callback("Connecting to catalog service...")

        # 0. Try vrSrc mirror via rclone if configured (meta.7z with game list)
        if self.base_url:
            if not _vrsrc.rclone_available():
                if status_callback:
                    status_callback("Installing rclone for mirror access...")
                _vrsrc.install_rclone(status_callback)

            if _vrsrc.rclone_available():
                meta_archive = os.path.join(DATA_DIR, "meta.7z")
                if _vrsrc.fetch_meta_archive(self.base_url, self.password, meta_archive, status_callback):
                    try:
                        extract_archive(meta_archive, DATA_DIR, password=self.password)
                        if os.path.isfile(meta_archive):
                            os.remove(meta_archive)
                    except Exception as e:
                        print(f"[FrameLoad] meta.7z extract notice: {e}")

                    # Ensure both GameList.txt and VRP-GameList.txt are present
                    extracted_gamelist = os.path.join(DATA_DIR, "GameList.txt")
                    if os.path.isfile(extracted_gamelist):
                        try:
                            shutil.copy2(extracted_gamelist, GAMELIST_FILE)
                        except OSError:
                            pass

                    if self.parse_gamelist_file():
                        if status_callback:
                            status_callback(f"Catalog synced from vrSrc mirror! {len(self.games)} titles.")
                        return True

        # 1. Check online raw JSON catalog endpoints (GitHub updates or custom catalog URL)
        remote_json_urls: List[str] = []
        custom_catalog = self.config["mirrors"].get("catalog_url")
        if custom_catalog:
            remote_json_urls.append(custom_catalog)

        for json_url in remote_json_urls:
            try:
                if status_callback:
                    status_callback(f"Checking updates from {json_url}...")
                req = urllib.request.Request(json_url, headers={"User-Agent": "FrameLoad/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        raw = json.loads(resp.read().decode("utf-8"))
                        if isinstance(raw, list) and len(raw) > 0:
                            new_games = []
                            for item in raw:
                                g = CatalogGame(
                                    name=item["name"],
                                    release_name=item["release_name"],
                                    package_name=item["package_name"],
                                    version_code=str(item.get("version_code", "1")),
                                    last_updated=item.get("last_updated", ""),
                                    size_bytes=int(item.get("size_bytes", 0)),
                                    id=item.get("id", ""),
                                    thumbnail_url=item.get("thumbnail_url", ""),
                                    kind=item.get("kind", "quest"),
                                    downloads=int(item.get("downloads", 0)),
                                    rating=float(item.get("rating", 0.0)),
                                    rating_count=int(item.get("rating_count", 0)),
                                    notes=item.get("notes", ""),
                                )
                                new_games.append(g)
                            if new_games:
                                self.games = new_games
                                self.games_by_id = {g.id: g for g in new_games}
                                self.games_by_pkg = {g.package_name: g for g in new_games}
                                self.save_cache()
                                if status_callback:
                                    status_callback(f"Catalog updated from remote! {len(self.games)} titles available.")
                                return True
            except Exception as e:
                print(f"[FrameLoad] Catalog remote JSON fetch notice for {json_url}: {e}")

        # 2. Check local VRP-GameList.txt / GameList.txt
        if self.parse_gamelist_file():
            self.load_bundled_catalog(merge=True)
            if status_callback:
                status_callback(f"Catalog refreshed from local GameList ({len(self.games)} titles).")
            return True

        if len(self.games) > 0:
            if status_callback:
                status_callback(f"Active catalog refreshed ({len(self.games)} titles available).")
            return True

        return False

    def parse_gamelist_file(self, filepath: Optional[str] = None) -> bool:
        target_path = filepath
        if not target_path or not os.path.isfile(target_path):
            candidates = [
                os.path.join(DATA_DIR, "GameList.txt"),
                os.path.join(DATA_DIR, "VRP-GameList.txt"),
                GAMELIST_FILE,
                os.path.join(os.path.dirname(DATA_DIR), "GameList.txt"),
                os.path.join(os.path.dirname(DATA_DIR), "VRP-GameList.txt"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    target_path = c
                    break

        if not target_path or not os.path.isfile(target_path):
            return False

        new_games = []
        try:
            with open(target_path, "r", encoding="utf-8-sig", errors="replace") as f:
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
                        size_mb = float(parts[5].strip())
                        size_bytes = int(size_mb * 1024 * 1024)
                    except ValueError:
                        size_bytes = 0

                    downloads = 0
                    if len(parts) > 6 and parts[6].strip():
                        try:
                            downloads = int(float(parts[6].strip()))
                        except ValueError:
                            downloads = 0

                    rating = 0.0
                    if len(parts) > 7 and parts[7].strip():
                        try:
                            rating = float(parts[7].strip())
                        except ValueError:
                            rating = 0.0

                    rating_count = 0
                    if len(parts) > 8 and parts[8].strip():
                        try:
                            rating_count = int(parts[8].strip())
                        except ValueError:
                            rating_count = 0

                    thumb_url = f"/api/thumbnail/{pkg_name}"

                    game = CatalogGame(
                        name=name,
                        release_name=release_name,
                        package_name=pkg_name,
                        version_code=version_code,
                        last_updated=last_updated,
                        size_bytes=size_bytes,
                        thumbnail_url=thumb_url,
                        kind="quest",
                        downloads=downloads,
                        rating=rating,
                        rating_count=rating_count,
                    )
                    new_games.append(game)

            if new_games:
                self.games = new_games
                self.games_by_id = {g.id: g for g in new_games}
                self.games_by_pkg = {g.package_name: g for g in new_games}
                self.save_cache()
                return True
        except Exception as e:
            print(f"[FrameLoad] Error parsing {target_path}: {e}")

        return False

    def get_game_notes(self, identifier: str) -> str:
        """Returns release notes / instructions from .meta/notes if available."""
        if not identifier:
            return ""
        game = self.games_by_id.get(identifier) or self.games_by_pkg.get(identifier)
        rel_name = game.release_name if game else identifier
        safe_rel = os.path.basename(rel_name.strip())
        notes_candidates = [
            os.path.join(DATA_DIR, ".meta/notes", f"{safe_rel}.txt"),
            os.path.join(DATA_DIR, ".meta/notes", safe_rel),
        ]
        for nc in notes_candidates:
            if os.path.isfile(nc):
                try:
                    with open(nc, "r", encoding="utf-8", errors="replace") as f:
                        return f.read().strip()
                except OSError:
                    pass
        return ""

    def save_cache(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            data = [g.to_dict() for g in self.games]
            with open(CATALOG_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError as e:
            print(f"[FrameLoad] Error saving catalog cache: {e}")

    def search(
        self,
        query: str = "",
        sort_by: str = "date",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = 36
    ) -> Dict[str, Any]:
        """Search, filter, and paginate the game catalog."""
        results = list(self.games)

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
