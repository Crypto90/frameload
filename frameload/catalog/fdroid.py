"""F-Droid open source catalog integration."""
import os
import json
import io
import urllib.request
import zipfile
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime

from .models import CatalogGame
from ..config import DATA_DIR

FDROID_INDEX_JAR = "https://f-droid.org/repo/index-v1.jar"
FDROID_CACHE_JSON = os.path.join(DATA_DIR, "fdroid_cache.json")


class FDroidCatalog:
    def __init__(self):
        self.games: List[CatalogGame] = []
        self.games_by_id: Dict[str, CatalogGame] = {}
        self._lock = threading.Lock()
        self.last_sync = ""
        self.load_cache()

    def load_cache(self) -> None:
        if os.path.isfile(FDROID_CACHE_JSON):
            try:
                with open(FDROID_CACHE_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_sync = data.get("last_sync", "")
                    
                    self.games = []
                    for item in data.get("games", []):
                        g = CatalogGame(
                            name=item["name"],
                            release_name=item["release_name"],
                            package_name=item["package_name"],
                            version_code=str(item.get("version_code", "1")),
                            last_updated=item.get("last_updated", ""),
                            size_bytes=int(item.get("size_bytes", 0)),
                            id=item.get("id", ""),
                            thumbnail_url=item.get("thumbnail_url", ""),
                            kind=item.get("kind", "flat"),
                            download_url=item.get("download_url", "")
                        )
                        self.games.append(g)
                    
                    self.games_by_id = {g.id: g for g in self.games}
            except Exception as e:
                print(f"[FrameLoad] Error loading F-Droid cache: {e}")

    def save_cache(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            data = {
                "last_sync": self.last_sync,
                "games": [g.to_dict() for g in self.games]
            }
            with open(FDROID_CACHE_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[FrameLoad] Error saving F-Droid cache: {e}")

    def sync(self, status_callback: Optional[callable] = None) -> bool:
        if status_callback:
            status_callback("Downloading F-Droid catalog index...")
            
        try:
            req = urllib.request.Request(FDROID_INDEX_JAR, headers={"User-Agent": "FrameLoad/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            
            if status_callback:
                status_callback("Parsing F-Droid catalog...")
                
            new_games = []
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                with z.open("index-v1.json") as f:
                    index = json.load(f)
                    apps = index.get("apps", [])
                    packages = index.get("packages", {})
                    
                    for app in apps:
                        pkg = app.get("packageName", "")
                        if not pkg: continue
                        
                        pkgs = packages.get(pkg, [])
                        if not pkgs: continue
                        
                        latest = pkgs[0] # Usually first is latest
                        
                        name = app.get("localized", {}).get("en-US", {}).get("name")
                        if not name:
                            name = app.get("name", pkg)
                        
                        # Use suggested version code if available, else first pkg
                        vcode = str(app.get("suggestedVersionCode", latest.get("versionCode", "1")))
                        added_ms = latest.get("added", 0)
                        last_updated = datetime.fromtimestamp(added_ms / 1000.0).strftime("%Y-%m-%d") if added_ms else ""
                        
                        icon = app.get("icon", "")
                        icon_url = f"https://f-droid.org/repo/{icon}" if icon else ""
                        apk_name = latest.get("apkName", "")
                        download_url = f"https://f-droid.org/repo/{apk_name}" if apk_name else ""
                        
                        if not download_url: continue
                        
                        g = CatalogGame(
                            name=name,
                            release_name=pkg,
                            package_name=pkg,
                            version_code=vcode,
                            last_updated=last_updated,
                            size_bytes=latest.get("size", 0),
                            thumbnail_url=icon_url,
                            kind="flat",
                            download_url=download_url
                        )
                        new_games.append(g)
            
            with self._lock:
                self.games = new_games
                self.games_by_id = {g.id: g for g in new_games}
                self.last_sync = datetime.now().isoformat()
            
            self.save_cache()
            
            if status_callback:
                status_callback(f"F-Droid sync complete! {len(self.games)} apps available.")
            return True
        except Exception as e:
            if status_callback:
                status_callback(f"F-Droid sync failed: {e}")
            print(f"[FrameLoad] F-Droid sync error: {e}")
            return False

    def get_game(self, game_id: str) -> Optional[CatalogGame]:
        return self.games_by_id.get(game_id)

    def search(
        self,
        query: str = "",
        sort_by: str = "date",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = 36
    ) -> Dict[str, Any]:
        """Search, filter, and paginate the F-Droid catalog."""
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
