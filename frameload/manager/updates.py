"""Updates management system for FrameLoad.
Provides 1-click self-updating for the FrameLoad application from GitHub releases,
and automated update checks for installed VR titles via the VRP mirror.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .. import __version__
from ..catalog.downloader import Downloader
from ..catalog.vrp_mirror import VrpMirror
from ..config import CACHE_DIR, HOME
from .installed import InstalledManager

GITHUB_API_BASE = "https://api.github.com"
REPO_OWNER = "Crypto90"
REPO_NAME = "frameload"
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# GitHub allows 60 anonymous API requests an hour per address; the dashboard asks far more often.
CHECK_INTERVAL = 6 * 3600
_check_cache: Dict[str, Any] = {"time": 0.0, "data": None}


def _fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"FrameLoad-Updater/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def expected_sha256(sums_text: str, filename: str) -> str:
    """The checksum SHA256SUMS lists for filename, '' if it is not listed."""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*").split("/")[-1] == filename:
            return parts[0].lower()
    return ""


def safe_extract(archive: str, dest: str) -> None:
    """Extracts a release tarball, refusing entries that would land outside dest."""
    dest_real = os.path.realpath(dest)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            target = os.path.realpath(os.path.join(dest_real, member.name))
            if target != dest_real and not target.startswith(dest_real + os.sep):
                raise ValueError(f"Update archive contains an unsafe path: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"Update archive contains an unexpected entry: {member.name}")
        try:
            tar.extractall(dest_real, filter="data")
        except TypeError:  # Python without extraction filters; entries were checked above
            tar.extractall(dest_real)


def parse_version(v_str: str) -> tuple[int, ...]:
    """Extracts numeric tuple from version string e.g. 'v1.0.1' -> (1, 0, 1)."""
    clean = v_str.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for x in clean.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class UpdateManager:
    @staticmethod
    def check_app_update(force: bool = False) -> Dict[str, Any]:
        """Checks GitHub releases and git remote for FrameLoad application updates.

        The answer is reused for six hours unless force is set (the user pressed Check)."""
        if not force and _check_cache["data"] and time.time() - _check_cache["time"] < CHECK_INTERVAL:
            return dict(_check_cache["data"])
        result = UpdateManager._check_app_update_now()
        _check_cache.update(time=time.time(), data=result)
        return dict(result)

    @staticmethod
    def _check_app_update_now() -> Dict[str, Any]:
        current_version = __version__
        cur_tuple = parse_version(current_version)

        is_git = os.path.isdir(os.path.join(ROOT_DIR, ".git"))
        has_update = False
        latest_tag = f"v{current_version}"
        release_name = f"FrameLoad {latest_tag}"
        release_notes = ""
        published_at = ""
        download_url = ""
        checksums_url = ""
        commits_behind = 0

        # 1. Query GitHub Releases API
        api_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
        try:
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": f"FrameLoad/{current_version}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    latest_tag = data.get("tag_name", latest_tag)
                    release_name = data.get("name", release_name)
                    release_notes = data.get("body", "")
                    published_at = data.get("published_at", "")

                    latest_tuple = parse_version(latest_tag)
                    if latest_tuple > cur_tuple:
                        has_update = True

                    for asset in data.get("assets", []):
                        if asset.get("name", "").endswith(".tar.gz") and not download_url:
                            download_url = asset.get("browser_download_url", "")
                        elif asset.get("name", "") == "SHA256SUMS":
                            checksums_url = asset.get("browser_download_url", "")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"[FrameLoad] Could not check GitHub releases: {e}")
        except Exception as e:
            pass

        # 2. If running from Git, check if remote main has newer commits
        if is_git:
            try:
                # Fetch remote heads silently
                subprocess.run(
                    ["git", "fetch", "--quiet", "origin", "main"],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    timeout=5
                )
                res = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD..origin/main"],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if res.returncode == 0:
                    commits_behind = int(res.stdout.strip() or 0)
                    if commits_behind > 0:
                        has_update = True
            except Exception:
                pass

        return {
            "has_update": has_update,
            "current_version": current_version,
            "latest_version": latest_tag.lstrip("vV"),
            "latest_tag": latest_tag,
            "release_name": release_name,
            "release_notes": release_notes,
            "published_at": published_at,
            "download_url": download_url,
            "checksums_url": checksums_url,
            "is_git": is_git,
            "commits_behind": commits_behind,
        }

    @staticmethod
    def check_game_updates(mirror: Optional[VrpMirror] = None) -> Dict[str, Any]:
        """Checks installed games against latest available versions in the mirror catalog."""
        if mirror is None:
            mirror = VrpMirror()

        installed = InstalledManager.list_installed()
        updates_available: List[Dict[str, Any]] = []

        for inst in installed:
            pkg = inst.get("package", "")
            catalog_game = mirror.games_by_pkg.get(pkg)

            # Fallback to name search if package key doesn't match directly
            if not catalog_game:
                title_lower = inst.get("title", "").lower().strip()
                for cg in mirror.games:
                    if cg.name.lower().strip() == title_lower:
                        catalog_game = cg
                        break

            if not catalog_game:
                continue

            installed_time = inst.get("installed_time", 0)
            catalog_updated = catalog_game.last_updated or ""

            # Check if catalog has newer version
            # If release_name or version_code differs or update date is newer
            has_game_update = False

            # If version code exists and differs
            inst_ver = inst.get("version_code") or inst.get("settings", {}).get("version_code", "")
            cat_ver = catalog_game.version_code

            if cat_ver and inst_ver and cat_ver != inst_ver:
                has_game_update = True

            # If installed before catalog update timestamp
            if not has_game_update and catalog_updated:
                try:
                    import time
                    cat_ts = time.mktime(time.strptime(catalog_updated, "%Y-%m-%d"))
                    if cat_ts > installed_time:
                        has_game_update = True
                except Exception:
                    pass

            if has_game_update:
                updates_available.append({
                    "package": pkg,
                    "title": inst.get("title", pkg),
                    "current_version": inst_ver or "Installed",
                    "new_version": cat_ver or catalog_updated,
                    "new_version_code": cat_ver,
                    "release_name": catalog_game.release_name,
                    "size_formatted": catalog_game.size_formatted,
                    "catalog_id": catalog_game.id,
                    "thumbnail_url": inst.get("thumbnail_url") or catalog_game.thumbnail_url or f"/api/thumbnail/{pkg}",
                })

        return {
            "updates_count": len(updates_available),
            "games": updates_available,
        }

    @staticmethod
    def perform_app_update() -> Dict[str, Any]:
        """Performs a 1-click update of FrameLoad and reconfigures shortcuts & systemd."""
        is_git = os.path.isdir(os.path.join(ROOT_DIR, ".git"))

        if is_git:
            # 1. Update via git pull
            try:
                res = subprocess.run(
                    ["git", "pull", "--ff-only", "origin", "main"],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if res.returncode != 0:
                    # Stash uncommitted changes if any and retry
                    subprocess.run(["git", "stash"], cwd=ROOT_DIR, capture_output=True, timeout=10)
                    res = subprocess.run(
                        ["git", "pull", "origin", "main"],
                        cwd=ROOT_DIR,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                update_log = res.stdout + res.stderr
            except Exception as e:
                return {"success": False, "error": f"Git update failed: {e}"}
        else:
            # 2. Standalone update via the release tarball, checked against the release's SHA256SUMS
            status = UpdateManager.check_app_update(force=True)
            tag = status.get("latest_tag", "")
            tarball_url = status.get("download_url")
            sums_url = status.get("checksums_url")
            if not tarball_url or not sums_url:
                return {"success": False, "error": "The latest release has no update package with checksums; nothing was changed."}

            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp_archive = os.path.join(CACHE_DIR, "frameload_update.tar.gz")
            try:
                filename = tarball_url.rsplit("/", 1)[-1]
                wanted = expected_sha256(_fetch(sums_url, 30).decode("utf-8", errors="replace"), filename)
                if not wanted:
                    return {"success": False, "error": f"SHA256SUMS does not list {filename}; nothing was changed."}
                req = urllib.request.Request(tarball_url, headers={"User-Agent": f"FrameLoad-Updater/{__version__}"})
                digest = hashlib.sha256()
                with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_archive, "wb") as f:
                    for block in iter(lambda: resp.read(1024 * 1024), b""):
                        digest.update(block)
                        f.write(block)
                if digest.hexdigest() != wanted:
                    return {"success": False, "error": "The downloaded update does not match its checksum; nothing was changed."}
                safe_extract(tmp_archive, ROOT_DIR)
                update_log = f"Installed {tag} (checksum verified)."
            except Exception as e:
                return {"success": False, "error": f"Update failed: {e}"}
            finally:
                if os.path.isfile(tmp_archive):
                    os.remove(tmp_archive)
        _check_cache.update(time=0.0, data=None)

        # 3. Execute install.sh with --no-restart to refresh shortcuts, systemd services, and container settings
        install_script = os.path.join(ROOT_DIR, "install.sh")
        if os.path.isfile(install_script):
            try:
                os.chmod(install_script, 0o755)
                subprocess.run(["bash", install_script, "--no-restart"], cwd=ROOT_DIR, capture_output=True, timeout=30)
            except Exception as e:
                print(f"[FrameLoad Updater] Warning running install.sh: {e}")

        # 4. Trigger systemd service restart in background after response is sent (2s delay)
        try:
            run_sh = os.path.join(ROOT_DIR, "run.sh")
            # With the systemd service: restart it. Started by run.sh instead: stop and start that way.
            restart_cmd = (
                "export XDG_RUNTIME_DIR=\"/run/user/$(id -u)\"; "
                "export DBUS_SESSION_BUS_ADDRESS=\"unix:path=$XDG_RUNTIME_DIR/bus\"; "
                "sleep 2; "
                "if systemctl --user is-active --quiet frameload.service; then "
                "systemctl --user restart frameload.service; "
                f"else bash '{run_sh}' --kill; bash '{run_sh}' --daemon; fi"
            )
            subprocess.Popen(
                ["bash", "-c", restart_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": "FrameLoad updated successfully! Reloading services...",
            "details": update_log
        }

    @staticmethod
    def update_game(package_name: str, mirror: Optional[VrpMirror] = None) -> Dict[str, Any]:
        """1-Click game update: queues the latest version from mirror, preserving user saves."""
        if mirror is None:
            mirror = VrpMirror()

        catalog_game = mirror.games_by_pkg.get(package_name)
        if not catalog_game:
            # Fallback search
            for cg in mirror.games:
                if cg.package_name == package_name:
                    catalog_game = cg
                    break

        if not catalog_game:
            raise FileNotFoundError(f"Update for package {package_name} not found in catalog.")

        downloader = Downloader.get()
        task = downloader.add_to_queue(catalog_game)

        return {
            "success": True,
            "message": f"Update for {catalog_game.name} queued for download.",
            "task": task.to_dict()
        }

    @staticmethod
    def update_all_games(mirror: Optional[VrpMirror] = None) -> Dict[str, Any]:
        """Queues updates for all installed games that have newer versions available."""
        if mirror is None:
            mirror = VrpMirror()

        updates = UpdateManager.check_game_updates(mirror).get("games", [])
        downloader = Downloader.get()
        queued = []

        for up in updates:
            cat_id = up.get("catalog_id")
            cat_game = mirror.get_game(cat_id)
            if cat_game:
                task = downloader.add_to_queue(cat_game)
                queued.append({
                    "package": up["package"],
                    "title": up["title"],
                    "task_id": task.id
                })

        return {
            "success": True,
            "queued_count": len(queued),
            "games": queued
        }
