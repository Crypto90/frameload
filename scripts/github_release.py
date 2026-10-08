#!/usr/bin/env python3
"""GitHub Release Publisher for FrameLoad.
Interacts with GitHub's REST API using pure Python standard library.
Creates/updates releases and uploads standalone distribution packages.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
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
        req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "FrameLoad-GitHub-Release-Agent/1.0")

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
        print(f"[GitHub API] HTTP Error {e.code} for {method} {url}: {body}", file=sys.stderr)
        raise RuntimeError(f"API {method} {url} returned {e.code}: {body}") from e


def upload_asset(repo: str, release_id: int, file_path: str, token: str) -> None:
    filename = os.path.basename(file_path)
    url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={urllib.parse.quote(filename)}"
    print(f"  ⬆️ Uploading asset {filename} ({os.path.getsize(file_path)} bytes)...")

    mime, _ = mimetypes.guess_type(file_path)
    mime = mime or "application/octet-stream"

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    make_request(url, method="POST", token=token, data=file_bytes, content_type=mime)
    print(f"  ✔ Successfully attached {filename}")


def publish_release(
    repo: str,
    tag: str,
    name: str,
    body: str,
    token: str,
    dist_dir: str
) -> None:
    print(f"🚀 Publishing release '{tag}' to https://github.com/{repo}...")

    # 1. Check if release already exists
    existing_url = f"https://api.github.com/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}"
    release = make_request(existing_url, token=token)

    if not release:
        # Create release
        create_url = f"https://api.github.com/repos/{repo}/releases"
        payload = json.dumps({
            "tag_name": tag,
            "target_commitish": "main",
            "name": name,
            "body": body,
            "draft": False,
            "prerelease": False
        }).encode("utf-8")
        release = make_request(create_url, method="POST", token=token, data=payload, content_type="application/json")
        print(f"✔ Created new GitHub release: {release.get('html_url')}")
    else:
        print(f"✔ Found existing GitHub release: {release.get('html_url')}")

    release_id = release["id"]

    # 2. Upload assets in dist_dir
    if os.path.isdir(dist_dir):
        existing_assets = {a["name"]: a["id"] for a in release.get("assets", [])}
        for fname in sorted(os.listdir(dist_dir)):
            if fname.endswith((".tar.gz", ".sh", "SHA256SUMS")):
                # Delete existing asset if it exists to allow re-upload
                if fname in existing_assets:
                    del_url = f"https://api.github.com/repos/{repo}/releases/assets/{existing_assets[fname]}"
                    print(f"  🗑️ Replacing existing asset {fname}...")
                    make_request(del_url, method="DELETE", token=token)

                fpath = os.path.join(dist_dir, fname)
                upload_asset(repo, release_id, fpath, token)

    print(f"\n🎉 GitHub Release {tag} published successfully!")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "Crypto90/frameload")

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(root_dir, "dist")

    tag = sys.argv[1] if len(sys.argv) > 1 else "v1.0.0"
    name = f"FrameLoad {tag}"

    notes_file = os.path.join(dist_dir, "RELEASE_NOTES.md")
    if os.path.isfile(notes_file):
        with open(notes_file, "r", encoding="utf-8") as f:
            body = f.read()
    else:
        try:
            from scripts.build_release import create_release_notes
            created_path = create_release_notes(tag.lstrip("v"))
            with open(created_path, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception:
            body = f"""# FrameLoad {tag}

## ⚡ 1-Click On-Device Installation (Single Command)

Open Konsole on your Steam Frame in Desktop Mode and run:

```bash
curl -fsSL https://raw.githubusercontent.com/{repo}/main/install.sh | bash
```

## 📦 What's Included
- Complete On-Device VR Catalog & Sideloading Engine
- Valve Lepton Android Container Runtime Integration
- Automatic Steam Grid Artwork generation (Vertical Posters, Banners, Heroes, Icons)
- Windows PCVR & Flat EXEs via Proton ARM64 / WineOpenXR
- Linux Native ARM64 & AppImages support
- Mod & Custom Content Injector (Beat Saber custom songs with auto permissions)
- Flat Android Window Display Presets
- Storage Manager with MicroSD card support
- One-Click Deep Linking (`frameload://` protocol)
- Safe Game Saves Backup and Restore
"""

    if not token:
        print("ERROR: GITHUB_TOKEN is required to publish releases.", file=sys.stderr)
        sys.exit(1)

    publish_release(
        repo=repo,
        tag=tag,
        name=name,
        body=body,
        token=token,
        dist_dir=dist_dir
    )


if __name__ == "__main__":
    main()
