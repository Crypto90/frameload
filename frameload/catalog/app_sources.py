"""Where 2D apps come from: F-Droid, IzzyOnDroid, Guardian Project and repositories the player adds.

Every source is an F-Droid-format repository. Its index is downloaded only when the player presses Sync
(never in the background), one source at a time, and is used only when it is signed by the source's key:
pinned here for the built-in sources, stored when a repository is added (from the fingerprint the player
gave, or the one seen when the repository was checked). An index older than the one already downloaded is
refused, and when a repository does not answer, the mirrors its last signed index named are tried.

Installed apps remember where they came from (deployment.json "origin"); an app is updated only from that
source and only when the new APK is signed by the same key. Apps installed by FrameLoad versions without
origins are treated as F-Droid installs, which is what they were.
"""
from __future__ import annotations

import gc
import glob
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..config import ANCHOR_DIR, DATA_DIR, Config
from .models import CatalogGame
from .repo_index import (
    FDROID_REPO,
    INDEX_V1_JAR,
    MAX_INDEX_JSON_BYTES,
    is_fingerprint,
    normalize_fingerprint,
    parse_index,
    read_index_v1,
    repo_mirrors,
)

SOURCES_DIR = os.path.join(DATA_DIR, "app_sources")
CACHE_VERSION = 3  # 3: signer, repository timestamp, mirrors and fingerprint
CACHE_FIELDS = 3   # 3: screenshots and video
MAX_INDEX_BYTES = 96 * 1024 * 1024        # F-Droid's index-v1.jar is about 16 MB
MAX_CUSTOM_JAR_BYTES = 32 * 1024 * 1024    # repositories the player added
MAX_CUSTOM_JSON_BYTES = 96 * 1024 * 1024
MAX_CUSTOM_SOURCES = 20
USER_AGENT = "FrameLoad"
INDEX_FORMAT = "v1"


@dataclass(frozen=True)
class AppSource:
    id: str
    name: str
    url: str
    fingerprint: str  # SHA-256 of the key that signs the index
    builtin: bool = True
    blurb: str = ""
    size_hint: str = ""  # how much one sync downloads
    added: str = ""


BUILTIN_SOURCES: Tuple[AppSource, ...] = (
    AppSource("fdroid", "F-Droid", FDROID_REPO,
              "43238d512c1e5eb2d6569f4a3afbf5523418b82e0a3ed1552770abb9a9c9ccab",
              blurb="Free and open-source apps, built by F-Droid", size_hint="16 MB"),
    AppSource("izzyondroid", "IzzyOnDroid", "https://apt.izzysoft.de/fdroid/repo",
              "3bf0d6abfeae2f401707b6d966be743bf0eee49c2561b9ba39073711f628937a",
              blurb="Free and open-source apps as released by their developers", size_hint="4 MB"),
    AppSource("guardian", "Guardian Project", "https://guardianproject.info/fdroid/repo",
              "b7c2eefd8dac7806af67dfcd92eb18126bc08312a7f2d6f3862e46013c7a6135",
              blurb="Privacy apps such as Orbot and Tor Browser", size_hint="0.2 MB"),
)
BUILTIN = {s.id: s for s in BUILTIN_SOURCES}
# How an install that came from no catalog is named ("Installed from a file").
ORIGIN_NAMES = {"file": "a file", "link": "a link"}

_GAME_FIELDS = {f.name for f in fields(CatalogGame)}

# One index is downloaded and parsed at a time: F-Droid's takes about 250 MB while it is read.
_SYNC_LOCK = threading.Lock()
_syncing = {"id": ""}


class RepoUnavailable(Exception):
    """The repository could not be reached, or answered with an error."""


class UnsafeAddressError(ValueError):
    """The address points at this headset or the local network."""


# ----------------------------------------------------------------------------- addresses

def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


LOCAL_ADDRESS_MESSAGE = ("That address belongs to this headset or the local network. Only repositories on the "
                         "internet can be added.")


def check_public_host(url: str) -> None:
    """Refuses a repository whose host is, or resolves to, a loopback, private, link-local or reserved
    address (127.0.0.1:8080 is Steam's own debugging port). Checked when a repository is added and
    again on every connection, because DNS answers can change."""
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise ValueError(f"The address {host} could not be found.") from None
    if not infos or not all(_is_public(info[4][0]) for info in infos):
        raise UnsafeAddressError(LOCAL_ADDRESS_MESSAGE)


def parse_repo_url(text: str) -> Tuple[str, str]:
    """A repository address as the player may paste it -> (https address of the repository, fingerprint
    from the address or ''). Accepts …/repo, …/repo?fingerprint=HEX, fdroidrepos:// links and addresses
    of the index files themselves."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Enter the repository's address.")
    lower = text.lower()
    if lower.startswith("fdroidrepos://"):
        text = "https://" + text[len("fdroidrepos://"):]
    elif lower.startswith("fdroidrepo://"):
        text = "http://" + text[len("fdroidrepo://"):]
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() != "https":
        raise ValueError("Only https repositories can be added.")
    if "@" in parts.netloc:
        raise ValueError("The address must not contain a user name or password.")
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = -1
    if not host or port == -1 or any(ch in host for ch in "/\\ "):
        raise ValueError("That is not a repository address.")
    query = urllib.parse.parse_qs(parts.query)
    fingerprint = normalize_fingerprint((query.get("fingerprint") or query.get("FINGERPRINT") or [""])[0])
    path = parts.path.rstrip("/")
    for tail in ("/index-v1.jar", "/index-v1.json", "/index-v2.json", "/entry.jar", "/entry.json", "/index.jar", "/index.xml"):
        if path.lower().endswith(tail):
            path = path[:-len(tail)]
            break
    if any(seg in (".", "..") for seg in path.split("/")):
        raise ValueError("That is not a repository address.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _is_public(host):
        raise UnsafeAddressError(LOCAL_ADDRESS_MESSAGE)
    netloc = f"[{host}]" if literal is not None and literal.version == 6 else host
    if port and port != 443:
        netloc += f":{port}"
    return f"https://{netloc}{path}", fingerprint


def custom_id(url: str) -> str:
    return "u" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]


# ----------------------------------------------------------------------------- HTTP

def _public_create_connection(address: Tuple[str, int], timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,
                              source_address: Any = None, *args: Any, **kwargs: Any) -> socket.socket:
    """socket.create_connection that connects only to public addresses (also after a redirect)."""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos or not all(_is_public(info[4][0]) for info in infos):
        raise UnsafeAddressError(LOCAL_ADDRESS_MESSAGE)
    error: Optional[OSError] = None
    for family, kind, proto, _, sockaddr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            error = e
            sock.close()
    raise error or OSError(f"Could not connect to {host}")


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _public_create_connection


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_PublicHTTPSConnection, req, context=getattr(self, "_context", None))


class _NoPlainHTTP(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        raise urllib.error.URLError("plain http is refused")


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.HTTPError(newurl, code, "a redirect away from https was refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener_for(public_only: bool) -> urllib.request.OpenerDirector:
    """https only; for repositories the player added also no proxy and public addresses only."""
    if public_only:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _PublicHTTPSHandler(),
                                           _NoPlainHTTP(), _HttpsOnlyRedirect())
    return urllib.request.build_opener(_HttpsOnlyRedirect())


def download_opener(source_id: str) -> Optional[urllib.request.OpenerDirector]:
    """The opener APK downloads from this source use (None: the downloader's default)."""
    if not source_id or source_id == "link":
        return None
    return opener_for(public_only=source_id not in BUILTIN)


def _http_get(url: str, headers: Dict[str, str], limit: int, public_only: bool) -> Tuple[int, Dict[str, str], bytes]:
    """(status, headers, body); a 304 is returned, other HTTP errors are raised."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener_for(public_only).open(req, timeout=60) as resp:
            return resp.status, dict(resp.headers.items()), resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, dict(e.headers.items()) if e.headers else {}, b""
        raise


def _retryable(error: BaseException) -> bool:
    """A network failure or a server error: worth trying a mirror."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500
    return isinstance(error, (urllib.error.URLError, OSError)) and not isinstance(error, UnsafeAddressError)


def _network_message(error: BaseException) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"the server answered {error.code}"
    reason = getattr(error, "reason", None) or error
    return str(reason) or type(error).__name__


# ----------------------------------------------------------------------------- installed apps

def origin_of(app: Dict[str, Any]) -> Dict[str, Any]:
    """Where an installed app came from. Apps installed before origins were recorded were F-Droid apps
    if they are 2D apps; anything else without an origin came from no app source."""
    origin = app.get("origin")
    if isinstance(origin, dict) and origin.get("source"):
        return origin
    return {"source": "fdroid"} if app.get("kind") == "flat" else {}


def signers_compatible(installed: str, offered: str) -> bool:
    """An APK can replace another only when both are signed by the same key; unknown keys are not held
    against an update."""
    return not installed or not offered or installed.lower() == offered.lower()


def installed_apps() -> Dict[str, Dict[str, Any]]:
    """package -> what its deployment.json says (version, kind, title, origin), on every drive."""
    try:
        from ..manager.installed import InstalledManager
        anchors = [a["path"] for a in InstalledManager.get_all_anchor_dirs()]
    except Exception:
        anchors = [ANCHOR_DIR]
    found: Dict[str, Dict[str, Any]] = {}
    for anchor in anchors:
        for dep_path in sorted(glob.glob(os.path.join(anchor, "*", "deployment.json"))):
            try:
                with open(dep_path, "r", encoding="utf-8") as f:
                    dep = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(dep, dict):
                continue
            pkg = str(dep.get("package") or os.path.basename(os.path.dirname(dep_path)))
            found.setdefault(pkg, {
                "package": pkg,
                "title": str(dep.get("title") or pkg),
                "kind": dep.get("kind", "quest"),
                "version_code": str(dep.get("version_code", "")),
                "version_name": str(dep.get("version_name", "")),
                "origin": dep.get("origin") if isinstance(dep.get("origin"), dict) else None,
            })
    return found


def app_origin(game: CatalogGame) -> Dict[str, Any]:
    """What an install from this catalog entry records in deployment.json."""
    source = AppSources.get().find(game.source)
    return {"source": game.source, "source_name": game.source_name or (source.name if source else game.source),
            "repo_url": source.url if source else "", "signer": game.signer, "version_code": game.version_code}


def origin_name(origin: Dict[str, Any]) -> str:
    sid = str(origin.get("source") or "")
    if sid in ORIGIN_NAMES:
        return ORIGIN_NAMES[sid]
    source = AppSources.get().find(sid)
    return source.name if source else str(origin.get("source_name") or sid)


def switch_refusal(game: CatalogGame, installed: Optional[Dict[str, Any]]) -> str:
    """Why this catalog entry may not replace the installed app ('' when it may).

    Android keeps an app's data only for an APK signed by the same key; a different key means
    uninstalling first."""
    if not installed or not game.source:
        return ""
    origin = origin_of(installed)
    if signers_compatible(str(origin.get("signer") or ""), game.signer):
        return ""
    if origin.get("source") == game.source:
        return (f"{game.source_name or game.source} now lists this app signed by a different key, so it cannot "
                "replace the installed one. Uninstall it first (back up its saves) to install it again.")
    return (f"Installed from {origin_name(origin)}. The {game.source_name or game.source} version is signed by a "
            "different key, so it cannot replace it. Uninstall it first (back up its saves) to switch.")


def _mark_installed(item: Dict[str, Any], game: CatalogGame, inst: Dict[str, Any]) -> None:
    origin = origin_of(inst)
    item["is_installed"] = True
    item["installed_version"] = inst.get("version_code", "")
    item["installed_source"] = str(origin.get("source") or "")
    item["installed_source_name"] = origin_name(origin) if origin.get("source") else ""
    try:
        newer = int(game.version_code) > int(inst.get("version_code") or 0)
    except ValueError:
        newer = False
    item["update_available"] = (newer and origin.get("source") == game.source
                                and signers_compatible(str(origin.get("signer") or ""), game.signer))
    item["blocked"] = switch_refusal(game, inst)  # why this entry cannot replace the installed app


def _also_in(entry: CatalogGame, shown: CatalogGame, inst: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    same = None if not (entry.signer and shown.signer) else entry.signer == shown.signer
    return {"id": entry.id, "source": entry.source, "source_name": entry.source_name, "name": entry.name,
            "package_name": entry.package_name, "kind": entry.kind, "size_bytes": entry.size_bytes,
            "version_name": entry.version_name, "version_code": entry.version_code,
            "same_signer": same, "blocked": switch_refusal(entry, inst)}


def _search(groups: List[Tuple[CatalogGame, List[CatalogGame]]], installed: Dict[str, Dict[str, Any]],
            query: str, sort_by: str, sort_order: str, page: int, per_page: int, category: str) -> Dict[str, Any]:
    """Filter, sort and page catalog entries; each group is (the entry shown, every source's entry)."""
    results = groups
    if category:
        results = [g for g in results if any(category in e.categories for e in g[1])]
    tokens = [t for t in query.lower().split() if t]
    if tokens:
        results = [g for g in results
                   if all(t in g[0].name.lower() or t in g[0].package_name.lower() or t in g[0].summary.lower()
                          for t in tokens)]
    reverse = sort_order == "desc"
    if sort_by == "name":
        results = sorted(results, key=lambda g: g[0].name.lower(), reverse=reverse)
    elif sort_by == "size":
        results = sorted(results, key=lambda g: g[0].size_bytes, reverse=reverse)
    else:  # repositories publish no download counts or ratings: newest first
        results = sorted(results, key=lambda g: g[0].last_updated, reverse=True)

    total_count = len(results)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    items = []
    for shown, entries in results[(page - 1) * per_page:page * per_page]:
        item = shown.to_dict()
        item.pop("description", None)  # long; served by /api/catalog/game/<id>
        item.pop("screenshots", None)  # likewise
        inst = installed.get(shown.package_name)
        if inst:
            _mark_installed(item, shown, inst)
        if len(entries) > 1:
            item["also_in"] = [_also_in(e, shown, inst) for e in entries if e is not shown]
        items.append(item)
    return {"items": items, "total_count": total_count, "page": page, "total_pages": total_pages, "per_page": per_page}


def _category_counts(groups: List[List[CatalogGame]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for entries in groups:
        for c in {c for e in entries for c in e.categories}:
            counts[c] = counts.get(c, 0) + 1
    return [{"name": c, "count": n} for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _update_entry(app: Dict[str, Any], entry: CatalogGame) -> Optional[Dict[str, Any]]:
    """The update an installed app gets from this entry of its own source, or None."""
    origin = origin_of(app)
    if origin.get("source") != entry.source or not signers_compatible(str(origin.get("signer") or ""), entry.signer):
        return None
    try:
        newer = int(entry.version_code) > int(app.get("version_code") or 0)
    except ValueError:
        newer = False
    if not newer:
        return None
    return {"id": entry.id, "package": entry.package_name, "title": app.get("title") or entry.name,
            "installed_version": app.get("version_name", ""), "new_version": entry.version_name,
            "size_formatted": entry.size_formatted, "source": entry.source, "source_name": entry.source_name}


def _list_installed() -> List[Dict[str, Any]]:
    try:
        from ..manager.installed import InstalledManager
        return InstalledManager.list_installed()
    except Exception:
        return []


# ----------------------------------------------------------------------------- one source

class RepoCatalog:
    """The apps of one source, kept in a cache file and read from disk on first use."""

    def __init__(self, source: AppSource) -> None:
        self.source = source
        self._games: List[CatalogGame] = []
        self._by_id: Dict[str, CatalogGame] = {}
        self._by_pkg: Dict[str, CatalogGame] = {}
        self._lock = threading.RLock()
        self._loaded = False
        self.last_sync = ""
        self.etag = ""
        self.repo_timestamp = 0
        self.mirrors: List[str] = []
        self.fingerprint = ""  # the key the cached index was signed by
        self.repo_name = ""
        self.index_format = INDEX_FORMAT
        if source.id == "fdroid":
            from . import fdroid  # the F-Droid cache keeps the name it had before app sources (tests replace it there)
            self.cache_file = fdroid.FDROID_CACHE_JSON
        else:
            self.cache_file = os.path.join(SOURCES_DIR, f"{source.id}.json")

    # The entries, loaded from the cache file the first time anything asks for them.
    @property
    def games(self) -> List[CatalogGame]:
        self._ensure_loaded()
        return self._games

    @property
    def games_by_id(self) -> Dict[str, CatalogGame]:
        self._ensure_loaded()
        return self._by_id

    @property
    def games_by_pkg(self) -> Dict[str, CatalogGame]:
        self._ensure_loaded()
        return self._by_pkg

    @property
    def loaded(self) -> bool:
        return self._loaded

    def has_cache(self) -> bool:
        return self._loaded or os.path.isfile(self.cache_file)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    self.load_cache()

    def _set_games(self, games: List[CatalogGame]) -> None:
        with self._lock:
            self._games = games
            self._by_id = {g.id: g for g in games}
            self._by_pkg = {g.package_name: g for g in games}
            self._loaded = True

    def expected_fingerprint(self) -> str:
        """The key the index must be signed by: pinned for the source, else the one seen first."""
        return normalize_fingerprint(self.source.fingerprint) or self.fingerprint

    def load_cache(self) -> None:
        with self._lock:
            self._loaded = True
            if not os.path.isfile(self.cache_file):
                return
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                version = data.get("version")
                if version not in (2, CACHE_VERSION):
                    return  # older caches hold wrong icon URLs and no checksums: sync again
                if str(data.get("url") or self.source.url).rstrip("/") != self.source.url.rstrip("/"):
                    return
                fingerprint = normalize_fingerprint(data.get("fingerprint", ""))
                pinned = normalize_fingerprint(self.source.fingerprint)
                if fingerprint and pinned and fingerprint != pinned:
                    return  # signed by another key than this source's: not used
                self.last_sync = str(data.get("last_sync", ""))
                # A cache from before screenshots, or from before indexes were verified, is downloaded again at
                # the next sync even when the repository says the index has not changed.
                current = version == CACHE_VERSION and data.get("fields", 0) >= CACHE_FIELDS
                self.etag = str(data.get("etag", "")) if current else ""
                self.repo_timestamp = int(data.get("repo_timestamp") or 0)
                self.mirrors = [m for m in data.get("mirrors") or [] if isinstance(m, str) and m.startswith("https://")]
                self.fingerprint = fingerprint
                self.repo_name = str(data.get("repo_name", ""))
                games = []
                for item in data.get("games", []):
                    game = CatalogGame(**{k: v for k, v in item.items() if k in _GAME_FIELDS})
                    game.source, game.source_name = self.source.id, self.source.name
                    games.append(game)
                self._set_games(games)
            except Exception as e:
                print(f"[FrameLoad] Error loading the {self.source.name} catalog cache: {e}")

    def save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            data = {
                "version": CACHE_VERSION,
                "fields": CACHE_FIELDS,
                "source": self.source.id,
                "url": self.source.url,
                "last_sync": self.last_sync,
                "etag": self.etag,
                "repo_timestamp": self.repo_timestamp,
                "mirrors": self.mirrors,
                "fingerprint": self.fingerprint,
                "repo_name": self.repo_name,
                "index_format": self.index_format,
                "games": [g.to_dict() for g in self.games],
            }
            tmp = self.cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.cache_file)
        except Exception as e:
            print(f"[FrameLoad] Error saving the {self.source.name} catalog cache: {e}")

    def delete_cache(self) -> None:
        with self._lock:
            for path in (self.cache_file, self.cache_file + ".tmp"):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._games, self._by_id, self._by_pkg = [], {}, {}

    # ------------------------------------------------------------------------- sync

    def sync(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        name = self.source.name

        def say(msg: str) -> None:
            if status_callback:
                status_callback(msg)

        if not _SYNC_LOCK.acquire(blocking=False):
            busy = _syncing["id"]
            other = AppSources.get().find(busy) if busy else None
            if busy == self.source.id:
                say(f"{name} sync already running.")
            else:
                say(f"{f'The {other.name} catalog' if other else 'Another catalog'} is still downloading. "
                    "Try again when it has finished.")
            return False
        _syncing["id"] = self.source.id
        try:
            self._ensure_loaded()
            return self._sync(say)
        except Exception as e:
            say(f"{name} sync failed: {e}")
            print(f"[FrameLoad] {name} sync error: {e}")
            return False
        finally:
            _syncing["id"] = ""
            _SYNC_LOCK.release()
            gc.collect()  # the parsed index was hundreds of MB

    def _fetch(self, say: Callable[[str], None], jar_limit: int) -> Tuple[int, Dict[str, str], bytes, str]:
        """index-v1.jar from the repository, or from one of its mirrors when it does not answer."""
        public_only = not self.source.builtin
        headers = {"User-Agent": USER_AGENT}
        if self.etag and self._games:
            headers["If-None-Match"] = self.etag
        try:
            status, resp_headers, data = _http_get(f"{self.source.url}/{INDEX_V1_JAR}", headers, jar_limit, public_only)
            return status, resp_headers, data, self.source.url
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RepoUnavailable(f"{self.source.name} publishes no index-v1.jar (404).") from None
            if not _retryable(e):
                raise RepoUnavailable(_network_message(e)) from None
            first: BaseException = e
        except UnsafeAddressError:
            raise
        except (urllib.error.URLError, OSError) as e:
            first = e
        for mirror in self.mirrors:
            say(f"{self.source.name} did not answer ({_network_message(first)}). Trying its mirror "
                f"{urllib.parse.urlsplit(mirror).hostname}...")
            try:
                status, resp_headers, data = _http_get(f"{mirror}/{INDEX_V1_JAR}", {"User-Agent": USER_AGENT},
                                                       jar_limit, public_only)
                return status, resp_headers, data, mirror
            except UnsafeAddressError:
                continue
            except (urllib.error.URLError, OSError):
                continue
        raise RepoUnavailable(f"{self.source.name} did not answer ({_network_message(first)}).")

    def _sync(self, say: Callable[[str], None]) -> bool:
        name = self.source.name
        jar_limit, json_limit = ((MAX_INDEX_BYTES, MAX_INDEX_JSON_BYTES) if self.source.builtin
                                 else (MAX_CUSTOM_JAR_BYTES, MAX_CUSTOM_JSON_BYTES))
        if not self.source.builtin:
            check_public_host(self.source.url)
        size = f" (about {self.source.size_hint})" if self.source.size_hint else ""
        say(f"Downloading the {name} catalog{size}...")
        status, headers, data, used = self._fetch(say, jar_limit)
        if status == 304:
            self.last_sync = datetime.now().isoformat()
            self.save_cache()
            say(f"The {name} catalog is up to date ({len(self._games)} apps).")
            return True
        if len(data) > jar_limit:
            raise ValueError(f"the {name} index is larger than expected")

        say(f"Checking the {name} catalog's signature...")
        found, index = read_index_v1(data, self.expected_fingerprint(), json_limit)
        del data
        repo = index.get("repo") or {}
        try:
            timestamp = int(repo.get("timestamp") or 0)
        except (TypeError, ValueError):
            timestamp = 0
        if self.repo_timestamp and timestamp < self.repo_timestamp:
            raise ValueError("the downloaded catalog is older than the one FrameLoad already has, so it was not used. "
                             "Try again later.")
        say(f"Reading the {name} catalog...")
        games = parse_index(index, base_url=self.source.url, source=self.source.id, source_name=name)
        mirrors = repo_mirrors(repo, self.source.url)
        repo_name = str(repo.get("name") or "")[:80]
        del index
        if not games and self.source.builtin:
            raise ValueError(f"the {name} catalog contained no apps that run on the Steam Frame")

        self._set_games(games)
        self.last_sync = datetime.now().isoformat()
        self.etag = str(headers.get("ETag") or headers.get("Etag") or "") if used == self.source.url else ""
        self.repo_timestamp = timestamp
        self.mirrors = mirrors
        self.fingerprint = found
        self.repo_name = repo_name
        self.save_cache()
        say(f"{name} catalog updated: {len(games)} apps available.")
        return True

    # ------------------------------------------------------------------------- reading

    def get_game(self, game_id: str) -> Optional[CatalogGame]:
        return self.games_by_id.get(game_id) or self.games_by_pkg.get(game_id)

    def categories(self) -> List[Dict[str, Any]]:
        return _category_counts([[g] for g in self.games])

    @staticmethod
    def _installed_version_codes(packages: List[str]) -> Dict[str, str]:
        """version_code of each of these packages that is installed, on any drive."""
        found = installed_apps()
        return {p: found[p]["version_code"] for p in packages if p in found}

    def available_updates(self) -> List[Dict[str, Any]]:
        """Installed apps from this source for which it offers a newer version signed by the same key."""
        updates = []
        for app in _list_installed():
            entry = self.games_by_pkg.get(app.get("package", ""))
            if entry and app.get("kind") == "flat":
                update = _update_entry(app, entry)
                if update:
                    updates.append(update)
        return updates

    def search(self, query: str = "", sort_by: str = "date", sort_order: str = "desc", page: int = 1,
               per_page: int = 36, category: str = "") -> Dict[str, Any]:
        """Search, filter, and paginate this source's apps."""
        res = _search([(g, [g]) for g in self.games], installed_apps(), query, sort_by, sort_order, page,
                      per_page, category)
        res["last_sync"] = self.last_sync
        return res

    def summary(self) -> Dict[str, Any]:
        self._ensure_loaded()
        return {"last_sync": self.last_sync, "app_count": len(self._games), "fingerprint": self.fingerprint,
                "mirrors": list(self.mirrors), "repo_name": self.repo_name, "index_format": self.index_format}


class FDroidCatalog(RepoCatalog):
    """F-Droid as the code before app sources knew it. FDroidCatalog.get() is the F-Droid source of
    AppSources; FDroidCatalog() is a separate catalog on the same cache file."""

    def __init__(self) -> None:
        super().__init__(BUILTIN["fdroid"])
        self.load_cache()

    @classmethod
    def get(cls) -> RepoCatalog:  # type: ignore[override]
        return AppSources.get().source("fdroid")  # type: ignore[return-value]


# ----------------------------------------------------------------------------- every source

def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


class AppSources:
    """The configured sources (config "app_sources") and their catalogs."""

    _instance: Optional["AppSources"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._catalogs: Dict[str, RepoCatalog] = {}
        self._lock = threading.RLock()

    @classmethod
    def get(cls) -> "AppSources":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------------- configuration

    @staticmethod
    def _settings() -> Dict[str, Any]:
        raw = Config.get().get("app_sources", {}) or {}
        custom = []
        for item in raw.get("custom") or []:
            if not isinstance(item, dict):
                continue
            url, sid = str(item.get("url") or ""), str(item.get("id") or "")
            if url.startswith("https://") and sid == custom_id(url) and is_fingerprint(normalize_fingerprint(item.get("fingerprint"))):
                custom.append(dict(item))
        return {
            "disabled": [str(s) for s in raw.get("disabled") or [] if isinstance(s, str)],
            "custom": custom,
            "order": [str(s) for s in raw.get("order") or [] if isinstance(s, str)],
        }

    @staticmethod
    def _save(settings: Dict[str, Any]) -> None:
        Config.get()["app_sources"] = settings

    def all(self) -> List[AppSource]:
        settings = self._settings()
        sources = list(BUILTIN_SOURCES)
        for item in settings["custom"]:
            host = urllib.parse.urlsplit(item["url"]).hostname or item["url"]
            sources.append(AppSource(
                item["id"], _clean_text(item.get("name"), 60) or host, item["url"],
                normalize_fingerprint(item["fingerprint"]), builtin=False,
                blurb=f"Apps from the repository at {host}", added=str(item.get("added") or "")))
        rank = {sid: i for i, sid in enumerate(settings["order"])}
        return [s for _, s in sorted(enumerate(sources), key=lambda p: (rank.get(p[1].id, len(rank)), p[0]))]

    def enabled(self) -> List[AppSource]:
        disabled = set(self._settings()["disabled"])
        return [s for s in self.all() if s.id not in disabled]

    def find(self, source_id: str) -> Optional[AppSource]:
        return next((s for s in self.all() if s.id == source_id), None)

    def source(self, source_id: str) -> Optional[RepoCatalog]:
        """The catalog of a configured source (created on first use)."""
        src = self.find(source_id)
        if not src:
            return None
        with self._lock:
            catalog = self._catalogs.get(source_id)
            if catalog is None:
                catalog = self._catalogs[source_id] = RepoCatalog(src)
            elif catalog.source != src:
                catalog.source = src
            return catalog

    def _catalogs_for_lookup(self, sources: Optional[Sequence[AppSource]] = None) -> List[RepoCatalog]:
        """Catalogs that may hold an entry: those already in memory first, then those with a cache file."""
        cats = [c for c in (self.source(s.id) for s in (sources if sources is not None else self.all())) if c]
        return [c for c in cats if c.loaded] + [c for c in cats if not c.loaded and c.has_cache()]

    # ------------------------------------------------------------------------- entries

    def get_game(self, identifier: str) -> Optional[CatalogGame]:
        """A catalog entry by its id, or (as before app sources) an F-Droid entry by its package."""
        for catalog in self._catalogs_for_lookup():
            game = catalog.games_by_id.get(identifier)
            if game:
                return game
        fdroid = self.source("fdroid")
        return fdroid.games_by_pkg.get(identifier) if fdroid and fdroid.has_cache() else None

    def loaded_entry(self, package: str) -> Optional[CatalogGame]:
        """An entry for this package among the catalogs already in memory (reads nothing from disk)."""
        for catalog in list(self._catalogs.values()):
            if catalog.loaded and package in catalog.games_by_pkg:
                return catalog.games_by_pkg[package]
        return None

    def entries_for(self, package: str, sources: Optional[Sequence[AppSource]] = None) -> List[CatalogGame]:
        """This package's entry in every source that lists it, in source order."""
        out = []
        for src in (sources if sources is not None else self.all()):
            catalog = self.source(src.id)
            if catalog and catalog.has_cache() and package in catalog.games_by_pkg:
                out.append(catalog.games_by_pkg[package])
        return out

    def describe(self, game: CatalogGame) -> Dict[str, Any]:
        """A catalog entry for the app's page: where it is installed from and the other sources that list it."""
        item = game.to_dict()
        source = self.find(game.source)
        item["repo_url"] = source.url if source else ""
        inst = installed_apps().get(game.package_name)
        if inst:
            _mark_installed(item, game, inst)
        item["also_in"] = [_also_in(e, game, inst) for e in self.entries_for(game.package_name, self.enabled())
                           if e.source != game.source]
        return item

    def _groups(self, sources: Sequence[AppSource], installed: Dict[str, Dict[str, Any]]) -> List[Tuple[CatalogGame, List[CatalogGame]]]:
        """One group per package across these sources. The entry shown is the one the app is installed
        from, otherwise the first source's in source order."""
        by_pkg: Dict[str, List[CatalogGame]] = {}
        for src in sources:
            catalog = self.source(src.id)
            for game in catalog.games if catalog else []:
                by_pkg.setdefault(game.package_name, []).append(game)
        groups = []
        for pkg, entries in by_pkg.items():
            shown = entries[0]
            inst = installed.get(pkg)
            if inst and len(entries) > 1:
                origin = origin_of(inst).get("source")
                shown = next((e for e in entries if e.source == origin), shown)
            groups.append((shown, entries))
        return groups

    def search(self, source: str = "fdroid", query: str = "", sort_by: str = "date", sort_order: str = "desc",
               page: int = 1, per_page: int = 36, category: str = "") -> Dict[str, Any]:
        """One source's apps, or with source 'all' every shown source's apps with duplicates merged."""
        if source != "all":
            catalog = self.source(source)
            if not catalog:
                raise KeyError(source)
            return catalog.search(query, sort_by, sort_order, page, per_page, category)
        sources = self.enabled()
        installed = installed_apps()
        res = _search(self._groups(sources, installed), installed, query, sort_by, sort_order, page, per_page, category)
        res["last_sync"] = max((c.last_sync for c in (self.source(s.id) for s in sources) if c and c.last_sync), default="")
        return res

    def categories(self, source: str = "fdroid") -> Dict[str, Any]:
        if source != "all":
            catalog = self.source(source)
            if not catalog:
                raise KeyError(source)
            return {"categories": catalog.categories(), "last_sync": catalog.last_sync}
        sources = self.enabled()
        groups = self._groups(sources, {})
        last = max((c.last_sync for c in (self.source(s.id) for s in sources) if c and c.last_sync), default="")
        return {"categories": _category_counts([entries for _, entries in groups]), "last_sync": last}

    def available_updates(self) -> List[Dict[str, Any]]:
        """Installed 2D apps with a newer version in the source they came from, signed by the same key."""
        updates = []
        for app in _list_installed():
            if app.get("kind") != "flat":
                continue
            catalog = self.source(str(origin_of(app).get("source") or ""))
            entry = catalog.games_by_pkg.get(app.get("package", "")) if catalog and catalog.has_cache() else None
            update = _update_entry(app, entry) if entry else None
            if update:
                updates.append(update)
        return updates

    # ------------------------------------------------------------------------- sync

    def sync(self, source: str, status_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """Downloads one source's index, or with 'all' every shown source's, one after another."""
        ids = [s.id for s in self.enabled()] if source == "all" else [source]
        messages: List[str] = []

        def say(msg: str) -> None:
            messages.append(msg)
            if status_callback:
                status_callback(msg)

        results = []
        for sid in ids:
            catalog = self.source(sid)
            if not catalog:
                raise KeyError(sid)
            before = len(messages)
            ok = catalog.sync(say)
            results.append((catalog, ok, messages[-1] if len(messages) > before else ""))
        total = sum(len(c.games) for c, ok, _ in results if c.has_cache())
        failed = [m for _, ok, m in results if not ok]
        if len(results) == 1:
            message = results[0][2]
        else:
            message = f"{total} apps from {sum(1 for _, ok, _ in results if ok)} of {len(results)} sources."
            if failed:
                message += " " + " ".join(failed)
        return {"success": any(ok for _, ok, _ in results) if source == "all" else results[0][1],
                "total_games": total, "message": message}

    @staticmethod
    def syncing() -> str:
        return _syncing["id"]

    # ------------------------------------------------------------------------- the Sources dialog

    def summaries(self) -> List[Dict[str, Any]]:
        disabled = set(self._settings()["disabled"])
        out = []
        for src in self.all():
            catalog = self.source(src.id)
            info = catalog.summary() if catalog else {}
            out.append({
                "id": src.id, "name": src.name, "url": src.url, "builtin": src.builtin, "enabled": src.id not in disabled,
                "blurb": src.blurb, "size_hint": src.size_hint, "added": src.added,
                "fingerprint": normalize_fingerprint(src.fingerprint) or info.get("fingerprint", ""),
                "last_sync": info.get("last_sync", ""), "app_count": info.get("app_count", 0),
                "mirrors": info.get("mirrors", []), "syncing": _syncing["id"] == src.id,
            })
        return out

    def probe(self, url: str, fingerprint: str = "") -> Dict[str, Any]:
        """Downloads and checks a repository's index without keeping anything."""
        url, from_url = parse_repo_url(url)
        want = normalize_fingerprint(fingerprint) or from_url
        if want and not is_fingerprint(want):
            raise ValueError("A signing key fingerprint is 64 hexadecimal characters (spaces and colons are fine).")
        known = next((s for s in self.all() if s.url.rstrip("/") == url), None)
        if known:
            raise ValueError(f"{known.name} is already in the list.")
        check_public_host(url)
        try:
            _, _, data = _http_get(f"{url}/{INDEX_V1_JAR}", {"User-Agent": USER_AGENT}, MAX_CUSTOM_JAR_BYTES, True)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError("No F-Droid repository was found at that address (it has no index-v1.jar).") from None
            raise RepoUnavailable(f"The repository could not be read: {_network_message(e)}.") from None
        except UnsafeAddressError:
            raise
        except (urllib.error.URLError, OSError) as e:
            raise RepoUnavailable(f"The repository did not answer: {_network_message(e)}.") from None
        if len(data) > MAX_CUSTOM_JAR_BYTES:
            raise ValueError("The repository's index is larger than FrameLoad accepts for an added repository.")
        found, index = read_index_v1(data, want, MAX_CUSTOM_JSON_BYTES)
        del data
        repo = index.get("repo") or {}
        host = urllib.parse.urlsplit(url).hostname or url
        name = _clean_text(repo.get("name"), 60) or host
        games = parse_index(index, base_url=url, source=custom_id(url), source_name=name)
        return {"name": name, "description": _clean_text(repo.get("description"), 300), "url": url,
                "fingerprint": found, "pinned": bool(want), "apps": len(index.get("apps") or []),
                "compatible": len(games), "index_format": INDEX_FORMAT}

    def add_custom(self, url: str, fingerprint: str, name: str = "") -> AppSource:
        url, from_url = parse_repo_url(url)
        fp = normalize_fingerprint(fingerprint) or from_url
        if not is_fingerprint(fp):
            raise ValueError("Check the repository first, so FrameLoad knows the key its index is signed with.")
        check_public_host(url)
        with self._lock:
            settings = self._settings()
            known = next((s for s in self.all() if s.url.rstrip("/") == url), None)
            if known:
                raise ValueError(f"{known.name} is already in the list.")
            if len(settings["custom"]) >= MAX_CUSTOM_SOURCES:
                raise ValueError(f"At most {MAX_CUSTOM_SOURCES} repositories can be added.")
            sid = custom_id(url)
            settings["custom"].append({"id": sid, "name": _clean_text(name, 60) or (urllib.parse.urlsplit(url).hostname or url),
                                       "url": url, "fingerprint": fp,
                                       "added": datetime.now().isoformat(timespec="seconds")})
            settings["disabled"] = [s for s in settings["disabled"] if s != sid]
            self._save(settings)
            stale = self._catalogs.pop(sid, None)
        if stale:
            stale.delete_cache()
        added = self.find(sid)
        if not added:
            raise ValueError("The repository could not be saved.")
        return added

    def remove_custom(self, source_id: str) -> List[Dict[str, str]]:
        """Removes a repository the player added and its cache; returns the installed apps that came from it
        (they stay installed, without updates)."""
        src = self.find(source_id)
        if not src:
            raise KeyError(source_id)
        if src.builtin:
            raise ValueError(f"{src.name} is built in and cannot be removed. Switch off Show in Browse instead.")
        with self._lock:
            settings = self._settings()
            settings["custom"] = [c for c in settings["custom"] if c["id"] != source_id]
            settings["disabled"] = [s for s in settings["disabled"] if s != source_id]
            settings["order"] = [s for s in settings["order"] if s != source_id]
            self._save(settings)
            catalog = self._catalogs.pop(source_id, None) or RepoCatalog(src)
        catalog.delete_cache()
        return [{"package": pkg, "title": app["title"]} for pkg, app in sorted(installed_apps().items())
                if origin_of(app).get("source") == source_id]

    def set_enabled(self, source_id: str, enabled: bool) -> None:
        if not self.find(source_id):
            raise KeyError(source_id)
        with self._lock:
            settings = self._settings()
            disabled = [s for s in settings["disabled"] if s != source_id]
            if not enabled:
                if not [s for s in self.all() if s.id not in disabled and s.id != source_id]:
                    raise ValueError("At least one source has to stay in Browse.")
                disabled.append(source_id)
            settings["disabled"] = disabled
            self._save(settings)
