"""F-Droid catalog: the store for 2D Android apps, shown as flat windows by Lepton."""
from __future__ import annotations

import io
import json
import os
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import fields
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .models import CatalogGame
from ..config import ANCHOR_DIR, DATA_DIR

FDROID_REPO = "https://f-droid.org/repo"
FDROID_INDEX_JAR = f"{FDROID_REPO}/index-v1.jar"
FDROID_CACHE_JSON = os.path.join(DATA_DIR, "fdroid_cache.json")
CACHE_VERSION = 2
MAX_INDEX_BYTES = 96 * 1024 * 1024
# Lepton runs 64-bit ARM apps only, on Android images up to API 34.
LEPTON_ABI = "arm64-v8a"
LEPTON_MAX_SDK = 34
LOCALES = ("en-US", "en-GB", "en")

_GAME_FIELDS = {f.name for f in fields(CatalogGame)}


def _is_compatible(pkg: Dict[str, Any]) -> bool:
    native = pkg.get("nativecode") or []
    if native and LEPTON_ABI not in native:
        return False
    try:
        return int(pkg.get("minSdkVersion", 1)) <= LEPTON_MAX_SDK
    except (TypeError, ValueError):
        return True


def pick_release(app: Dict[str, Any], releases: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The release to offer: F-Droid's suggested version if Lepton can run it, else the newest
    compatible one at or below it (releases above the suggested version are betas)."""
    usable = [r for r in releases if r.get("apkName") and _is_compatible(r)]
    if not usable:
        return None
    usable.sort(key=lambda r: int(r.get("versionCode", 0)), reverse=True)
    try:
        suggested = int(app.get("suggestedVersionCode") or 0)
    except (TypeError, ValueError):
        suggested = 0
    if suggested:
        for r in usable:
            if int(r.get("versionCode", 0)) <= suggested:
                return r
    return usable[0]


def _localized(app: Dict[str, Any], key: str) -> str:
    loc = app.get("localized") or {}
    for name in LOCALES:
        value = (loc.get(name) or {}).get(key)
        if value:
            return str(value)
    return str(app.get(key) or "")


def _icon_url(app: Dict[str, Any], pkg: str) -> str:
    loc = app.get("localized") or {}
    for name in LOCALES:
        icon = (loc.get(name) or {}).get("icon")
        if icon:
            return f"{FDROID_REPO}/{pkg}/{name}/{icon}"
    return f"{FDROID_REPO}/icons-640/{app['icon']}" if app.get("icon") else ""


def parse_index(index: Dict[str, Any]) -> List[CatalogGame]:
    """Turns an F-Droid index-v1 document into catalog entries Lepton can install."""
    packages = index.get("packages") or {}
    games: List[CatalogGame] = []
    for app in index.get("apps") or []:
        pkg = app.get("packageName") or ""
        release = pick_release(app, packages.get(pkg) or []) if pkg else None
        if not release:
            continue
        updated_ms = app.get("lastUpdated") or release.get("added") or 0
        updated = datetime.fromtimestamp(updated_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d") if updated_ms else ""
        sha256 = release.get("hash", "") if release.get("hashType", "sha256") == "sha256" else ""
        games.append(CatalogGame(
            name=_localized(app, "name") or pkg,
            release_name=pkg,
            package_name=pkg,
            version_code=str(release.get("versionCode", "1")),
            version_name=str(release.get("versionName", "")),
            last_updated=updated,
            size_bytes=int(release.get("size") or 0),
            thumbnail_url=_icon_url(app, pkg),
            kind="flat",
            download_url=f"{FDROID_REPO}/{release['apkName']}",
            sha256=sha256,
            summary=_localized(app, "summary"),
            description=_localized(app, "description"),
            categories=[str(c) for c in (app.get("categories") or [])],
            license=str(app.get("license") or ""),
            anti_features=[str(a) for a in (app.get("antiFeatures") or [])],
            source="fdroid",
        ))
    return games


class FDroidCatalog:
    _instance: Optional["FDroidCatalog"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self.games: List[CatalogGame] = []
        self.games_by_id: Dict[str, CatalogGame] = {}
        self.games_by_pkg: Dict[str, CatalogGame] = {}
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self.last_sync = ""
        self.etag = ""
        self.load_cache()

    @classmethod
    def get(cls) -> "FDroidCatalog":
        """One catalog per process: the cache holds thousands of apps and is not re-read per request."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _set_games(self, games: List[CatalogGame]) -> None:
        with self._lock:
            self.games = games
            self.games_by_id = {g.id: g for g in games}
            self.games_by_pkg = {g.package_name: g for g in games}

    def load_cache(self) -> None:
        if not os.path.isfile(FDROID_CACHE_JSON):
            return
        try:
            with open(FDROID_CACHE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != CACHE_VERSION:
                return  # older caches hold wrong icon URLs and no checksums: sync again
            self.last_sync = data.get("last_sync", "")
            self.etag = data.get("etag", "")
            self._set_games([
                CatalogGame(**{k: v for k, v in item.items() if k in _GAME_FIELDS})
                for item in data.get("games", [])
            ])
        except Exception as e:
            print(f"[FrameLoad] Error loading F-Droid cache: {e}")

    def save_cache(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            data = {
                "version": CACHE_VERSION,
                "last_sync": self.last_sync,
                "etag": self.etag,
                "games": [g.to_dict() for g in self.games],
            }
            tmp = FDROID_CACHE_JSON + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, FDROID_CACHE_JSON)
        except Exception as e:
            print(f"[FrameLoad] Error saving F-Droid cache: {e}")

    def sync(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        def say(msg: str) -> None:
            if status_callback:
                status_callback(msg)

        if not self._sync_lock.acquire(blocking=False):
            say("F-Droid sync already running.")
            return bool(self.games)
        try:
            say("Downloading F-Droid catalog index...")
            headers = {"User-Agent": "FrameLoad"}
            if self.etag and self.games:
                headers["If-None-Match"] = self.etag
            try:
                req = urllib.request.Request(FDROID_INDEX_JAR, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read(MAX_INDEX_BYTES + 1)
                    etag = resp.headers.get("ETag", "")
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    self.last_sync = datetime.now().isoformat()
                    self.save_cache()
                    say(f"F-Droid catalog is up to date ({len(self.games)} apps).")
                    return True
                raise
            if len(data) > MAX_INDEX_BYTES:
                raise ValueError("F-Droid index is larger than expected")

            say("Parsing F-Droid catalog...")
            with zipfile.ZipFile(io.BytesIO(data)) as z, z.open("index-v1.json") as f:
                games = parse_index(json.load(f))
            if not games:
                raise ValueError("F-Droid index contained no installable apps")

            self._set_games(games)
            self.last_sync = datetime.now().isoformat()
            self.etag = etag
            self.save_cache()
            say(f"F-Droid sync complete: {len(games)} apps available.")
            return True
        except Exception as e:
            say(f"F-Droid sync failed: {e}")
            print(f"[FrameLoad] F-Droid sync error: {e}")
            return False
        finally:
            self._sync_lock.release()

    def get_game(self, game_id: str) -> Optional[CatalogGame]:
        return self.games_by_id.get(game_id) or self.games_by_pkg.get(game_id)

    def categories(self) -> List[Dict[str, Any]]:
        counts: Dict[str, int] = {}
        for g in self.games:
            for c in g.categories:
                counts[c] = counts.get(c, 0) + 1
        return [{"name": c, "count": n} for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    @staticmethod
    def _installed_version_codes(packages: List[str]) -> Dict[str, str]:
        """version_code of each of these packages that is installed, on any drive."""
        found: Dict[str, str] = {}
        try:
            from ..manager.installed import InstalledManager
            anchors = [a["path"] for a in InstalledManager.get_all_anchor_dirs()]
        except Exception:
            anchors = [ANCHOR_DIR]
        for pkg in packages:
            for anchor in anchors:
                dep_path = os.path.join(anchor, pkg, "deployment.json")
                if not os.path.isfile(dep_path):
                    continue
                try:
                    with open(dep_path, "r", encoding="utf-8") as f:
                        found[pkg] = str(json.load(f).get("version_code", ""))
                except (OSError, ValueError):
                    found[pkg] = ""
                break
        return found

    def available_updates(self) -> List[Dict[str, Any]]:
        """Installed apps for which the catalog offers a newer version."""
        try:
            from ..manager.installed import InstalledManager
            installed = InstalledManager.list_installed()
        except Exception:
            return []
        updates = []
        for app in installed:
            entry = self.games_by_pkg.get(app.get("package", ""))
            if not entry or app.get("kind") != "flat":
                continue
            try:
                newer = int(entry.version_code) > int(app.get("version_code") or 0)
            except ValueError:
                newer = False
            if newer:
                updates.append({
                    "id": entry.id, "package": entry.package_name, "title": app.get("title") or entry.name,
                    "installed_version": app.get("version_name", ""), "new_version": entry.version_name,
                    "size_formatted": entry.size_formatted,
                })
        return updates

    def search(
        self,
        query: str = "",
        sort_by: str = "date",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = 36,
        category: str = "",
    ) -> Dict[str, Any]:
        """Search, filter, and paginate the F-Droid catalog."""
        results = list(self.games)

        if category:
            results = [g for g in results if category in g.categories]
        tokens = [t for t in query.lower().split() if t]
        if tokens:
            results = [
                g for g in results
                if all(t in g.name.lower() or t in g.package_name.lower() or t in g.summary.lower() for t in tokens)
            ]

        reverse = sort_order == "desc"
        if sort_by == "name":
            results.sort(key=lambda g: g.name.lower(), reverse=reverse)
        elif sort_by == "size":
            results.sort(key=lambda g: g.size_bytes, reverse=reverse)
        else:  # F-Droid publishes no download counts or ratings: newest first
            results.sort(key=lambda g: g.last_updated, reverse=True)

        total_count = len(results)
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        page_items = results[(page - 1) * per_page:page * per_page]

        installed = self._installed_version_codes([g.package_name for g in page_items])
        items = []
        for g in page_items:
            d = g.to_dict()
            d.pop("description", None)  # long; served by /api/catalog/game/<id>
            if g.package_name in installed:
                d["is_installed"] = True
                d["installed_version"] = installed[g.package_name]
                try:
                    d["update_available"] = int(g.version_code) > int(installed[g.package_name] or 0)
                except ValueError:
                    d["update_available"] = False
            items.append(d)

        return {
            "items": items,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "last_sync": self.last_sync,
        }
