#!/usr/bin/env python3
"""Sync Release Notes for all GitHub Releases from CHANGELOG.md.
Updates the descriptions of all existing GitHub releases with their authentic,
version-specific changelog notes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
from scripts.build_release import extract_changelog_section


def get_github_token() -> str:
    """Retrieve GitHub token from environment or osxkeychain."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token

    try:
        proc = subprocess.Popen(
            ["git", "credential", "fill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out, _ = proc.communicate("protocol=https\nhost=github.com\n\n")
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("password=", 1)[1].strip()
    except Exception:
        pass

    return ""


def github_request(
    url: str,
    method: str = "GET",
    token: str = "",
    data: Optional[bytes] = None,
) -> Any:
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "FrameLoad-Release-Sync/1.0")
    if data:
        req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))


def generate_release_body(tag: str, repo: str = "Crypto90/frameload") -> str:
    clean_ver = tag.lstrip("v")
    display_ver = f"v{clean_ver}"
    changelog_section = extract_changelog_section(clean_ver)

    if not changelog_section:
        changelog_section = (
            f"- **Universal Sideloading Hub:** Sideload Quest APKs/XAPKs, PCVR EXEs, and Linux native ARM64 apps.\n"
            f"- **Storage & Updates:** Automated storage management, update alerts, and runtime maintenance."
        )

    return f"""# 🚀 FrameLoad {display_ver}

An all-in-one, on-device VR sideloading engine, mirror catalog browser, and game manager engineered specifically for the **Valve Steam Frame (Galileo / Roy)** running SteamOS and the Lepton Android runtime container.

## ⚡ 1-Click On-Device Installation

Open Konsole on your Steam Frame in Desktop Mode and run:
```bash
curl -fsSL https://raw.githubusercontent.com/{repo}/main/install.sh | bash
```

## ✨ Highlights & Changes in {display_ver}

{changelog_section}

## 📦 Distribution Packages
- **`frameload-{display_ver}-standalone.tar.gz`**: Standalone distribution archive including all web UI assets and dependencies.
- **`frameload-installer.sh`**: Self-extracting on-device installer script.
- **`SHA256SUMS`**: Cryptographic integrity checksums.
"""


def sync_all_releases(repo: str = "Crypto90/frameload", dry_run: bool = False) -> None:
    token = get_github_token()
    if not token and not dry_run:
        print("ERROR: GitHub token not found.", file=sys.stderr)
        sys.exit(1)

    print(f"📡 Fetching all releases from https://github.com/{repo}...")
    url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
    releases = github_request(url, method="GET", token=token)

    if not releases:
        print("No releases found.")
        return

    print(f"Found {len(releases)} releases on GitHub.\n")

    updated_count = 0
    skipped_count = 0

    for rel in releases:
        tag = rel.get("tag_name", "")
        rel_id = rel.get("id")
        current_body = (rel.get("body") or "").strip()
        new_body = generate_release_body(tag, repo=repo).strip()

        if current_body == new_body:
            print(f"⏭️  [{tag}] Already up to date.")
            skipped_count += 1
            continue

        print(f"🔄 [{tag}] Updating release text on GitHub (Release ID: {rel_id})...")
        if dry_run:
            print(f"   [DRY RUN] Would update {tag} with {len(new_body)} characters.")
            updated_count += 1
            continue

        patch_url = f"https://api.github.com/repos/{repo}/releases/{rel_id}"
        payload = json.dumps({
            "name": f"FrameLoad {tag}",
            "body": new_body,
        }).encode("utf-8")

        try:
            github_request(patch_url, method="PATCH", token=token, data=payload)
            print(f"   ✔ Successfully updated release notes for {tag}!")
            updated_count += 1
        except Exception as e:
            print(f"   ❌ Failed to update {tag}: {e}", file=sys.stderr)

    print(f"\n✨ Done! Updated: {updated_count}, Skipped: {skipped_count}")


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    sync_all_releases(dry_run=is_dry)
