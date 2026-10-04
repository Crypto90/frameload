#!/usr/bin/env python3
"""Forgejo Release Publisher for FrameLoad.
Interacts with Forgejo's REST API using pure Python standard library.
Creates/updates releases and uploads build artifacts.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional


def make_request(
    url: str,
    method: str = "GET",
    token: str = "",
    data: Optional[bytes] = None,
    content_type: Optional[str] = None
) -> Dict[str, Any] | List[Any] | None:
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"token {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "FrameLoad-Forgejo-Release-Agent/1.0")

    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 404:
            return None
        print(f"[Forgejo API] HTTP Error {e.code} for {method} {url}: {body}", file=sys.stderr)
        raise RuntimeError(f"API {method} {url} returned {e.code}: {body}") from e


def upload_asset(server_url: str, repo: str, release_id: int, file_path: str, token: str) -> None:
    filename = os.path.basename(file_path)
    url = f"{server_url}/api/v1/repos/{repo}/releases/{release_id}/assets?name={urllib.parse.quote(filename)}"
    print(f"  ⬆️ Uploading asset {filename} ({os.path.getsize(file_path)} bytes)...")

    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    content_type = f"multipart/form-data; boundary={boundary}"

    mime, _ = mimetypes.guess_type(file_path)
    mime = mime or "application/octet-stream"

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="attachment"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    make_request(url, method="POST", token=token, data=bytes(body), content_type=content_type)
    print(f"  ✔ Successfully attached {filename}")


def publish_release(
    server_url: str,
    repo: str,
    tag: str,
    name: str,
    body: str,
    token: str,
    dist_dir: str
) -> None:
    server_url = server_url.rstrip("/")
    print(f"🚀 Publishing release '{tag}' to {server_url}/{repo}...")

    # 1. Check if release already exists
    existing_url = f"{server_url}/api/v1/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}"
    release = make_request(existing_url, token=token)

    if not release:
        # Create release
        create_url = f"{server_url}/api/v1/repos/{repo}/releases"
        payload = json.dumps({
            "tag_name": tag,
            "target_commitish": "main",
            "name": name,
            "body": body,
            "draft": False,
            "prerelease": False
        }).encode("utf-8")
        release = make_request(create_url, method="POST", token=token, data=payload, content_type="application/json")
        print(f"✔ Created new release {tag} (ID: {release['id']})")
    else:
        print(f"ℹ Release {tag} already exists (ID: {release['id']})")

    release_id = release["id"]

    # 2. Check existing assets and clean up any conflicts
    assets_url = f"{server_url}/api/v1/repos/{repo}/releases/{release_id}/assets"
    existing_assets = make_request(assets_url, token=token) or []
    asset_map = {a["name"]: a["id"] for a in existing_assets if "name" in a and "id" in a}

    # 3. Upload all artifacts in dist_dir
    if os.path.isdir(dist_dir):
        for fname in sorted(os.listdir(dist_dir)):
            fpath = os.path.join(dist_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if fname in asset_map:
                print(f"  Removing outdated asset {fname}...")
                del_url = f"{server_url}/api/v1/repos/{repo}/releases/{release_id}/assets/{asset_map[fname]}"
                try:
                    make_request(del_url, method="DELETE", token=token)
                except Exception as e:
                    print(f"  Warning deleting old asset: {e}")
            upload_asset(server_url, repo, release_id, fpath, token)

    print(f"\n🎉 Forgejo Release {tag} published successfully!")
    print(f"🔗 View Release: {server_url}/{repo}/releases/tag/{tag}")


def main() -> None:
    # Read environment variables commonly provided in Forgejo/Gitea Actions
    token = os.environ.get("FORGEJO_TOKEN") or os.environ.get("GITEA_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    server_url = os.environ.get("GITHUB_SERVER_URL") or os.environ.get("GITEA_SERVER_URL") or "https://forgejo.shieldserver.de"
    repo = os.environ.get("GITHUB_REPOSITORY") or "Crypto90/FrameLoad"
    ref = os.environ.get("GITHUB_REF", "")

    # Determine tag or version
    tag = ""
    if ref.startswith("refs/tags/"):
        tag = ref.replace("refs/tags/", "")
    elif len(sys.argv) > 1:
        tag = sys.argv[1]
    else:
        tag = "v1.0.0"

    release_name = f"FrameLoad {tag} — Standalone On-Device VR Sideload & Manager"
    release_body = f"""## 🚀 FrameLoad {tag} (Steam Frame VR & SteamOS)

### ⚡ 1-Click Quick Install (Run directly in Konsole on Steam Frame):
```bash
curl -fsSL https://forgejo.shieldserver.de/Crypto90/FrameLoad/raw/branch/main/install.sh | bash
```

### 📦 Standalone Offline Installer:
Download `frameload-installer.sh` from the assets below and execute:
```bash
bash frameload-installer.sh
```

### 🌟 Release Highlights:
- **Steam Frame Standalone:** 100% on-device execution on SteamOS (Linux ARM64 / aarch64).
- **VRP Mirror Downloader:** Direct multi-threaded resumable download engine with live speed metrics and ETA.
- **Lepton Compatibility Engine:** Automated Valve Lepton container setup, permission auto-repair, and FrameBridge OpenXR translation layer.
- **Steam-Style Storage Manager:** Drive switcher pills, multi-colored segmented bar visualizer, per-game disk breakdown, and safe batch uninstaller.
- **Steam Library & VR Navigation:** Full binary `shortcuts.vdf` integration with grid posters, gamepad/VR controller D-pad navigation, and one-click launch.
"""

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(root_dir, "dist")

    if not token:
        print("ERROR: FORGEJO_TOKEN / GITHUB_TOKEN is required to publish releases.", file=sys.stderr)
        sys.exit(1)

    publish_release(server_url, repo, tag, release_name, release_body, token, dist_dir)


if __name__ == "__main__":
    main()
