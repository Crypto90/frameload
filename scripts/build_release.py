#!/usr/bin/env python3
"""FrameLoad Release Artifacts Builder.
Creates standalone distribution tarballs, self-extracting shell installer (.sh),
and cryptographic checksums (SHA256SUMS).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
from frameload import __version__ as VERSION
DIST_DIR = os.path.join(ROOT_DIR, "dist")


def sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_standalone_tarball() -> str:
    """Packages FrameLoad into a standalone tar.gz archive."""
    archive_name = f"frameload-v{VERSION}-standalone.tar.gz"
    archive_path = os.path.join(DIST_DIR, archive_name)

    print(f"📦 Packaging {archive_name}...")
    with tarfile.open(archive_path, "w:gz") as tar:
        # Include frameload package directory
        frameload_pkg = os.path.join(ROOT_DIR, "frameload")
        tar.add(frameload_pkg, arcname="frameload")

        # Include root runner, installer scripts, and documentation
        for item in ["install.sh", "run.sh", "setup.py", "README.md", "CHANGELOG.md"]:
            p = os.path.join(ROOT_DIR, item)
            if os.path.isfile(p):
                tar.add(p, arcname=item)

        # Include docs if available
        docs_dir = os.path.join(ROOT_DIR, "docs")
        if os.path.isdir(docs_dir):
            tar.add(docs_dir, arcname="docs")

    sz_mb = os.path.getsize(archive_path) / (1024 * 1024)
    print(f"✔ Created {archive_path} ({sz_mb:.2f} MB)")
    return archive_path


def create_self_extracting_installer(tarball_path: str) -> str:
    """Creates a self-extracting, standalone shell installer script."""
    installer_name = "frameload-installer.sh"
    installer_path = os.path.join(DIST_DIR, installer_name)

    print(f"🚀 Creating self-extracting installer {installer_name}...")

    header = r"""#!/usr/bin/env bash
# ==============================================================================
# FrameLoad Self-Extracting On-Device Installer
# Standalone installation bundle for Steam Frame VR & SteamOS
# ==============================================================================
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m ✔  %s\033[0m\n' "$*"; }
err() { printf '\033[1;31m ✖  %s\033[0m\n' "$*" >&2; exit 1; }

TARGET_DIR="${FRAMELOAD_INSTALL_DIR:-$HOME/Applications/FrameLoad}"

say "FrameLoad Standalone Installer (Steam Frame / SteamOS)"
printf "Target Installation Directory: \033[1;33m%s\033[0m\n" "$TARGET_DIR"

mkdir -p "$TARGET_DIR"

say "Extracting bundled FrameLoad package files..."
PAYLOAD_LINE=$(awk '/^__FRAMELOAD_ARCHIVE_BELOW__/ {print NR + 1; exit 0; }' "$0")
if [[ -z "$PAYLOAD_LINE" ]]; then
    err "Corrupted installer: payload marker not found."
fi

tail -n +"$PAYLOAD_LINE" "$0" | tar -xzf - -C "$TARGET_DIR"
ok "Successfully extracted FrameLoad to $TARGET_DIR"

chmod +x "$TARGET_DIR/install.sh" "$TARGET_DIR/run.sh"

say "Configuring system services and Steam library shortcuts..."
(
    cd "$TARGET_DIR"
    bash "$TARGET_DIR/install.sh"
)

say "Installation completed successfully!"
printf "You can now launch \033[1;32mFrameLoad\033[0m directly from your Steam library in VR!\n"
exit 0

__FRAMELOAD_ARCHIVE_BELOW__
"""

    with open(installer_path, "wb") as out:
        out.write(header.encode("utf-8"))
        with open(tarball_path, "rb") as archive:
            shutil.copyfileobj(archive, out)

    os.chmod(installer_path, 0o755)
    sz_mb = os.path.getsize(installer_path) / (1024 * 1024)
    print(f"✔ Created self-extracting installer {installer_path} ({sz_mb:.2f} MB)")
    return installer_path


def generate_checksums(files: list[str]) -> str:
    """Generates SHA256SUMS file for release integrity verification."""
    checksums_path = os.path.join(DIST_DIR, "SHA256SUMS")
    print(f"🔒 Generating {checksums_path}...")
    lines = []
    for f in sorted(files):
        h = sha256_file(f)
        bname = os.path.basename(f)
        lines.append(f"{h}  {bname}")
        print(f"  {h}  {bname}")

    with open(checksums_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return checksums_path


def extract_changelog_section(version: str, changelog_path: str | None = None) -> str | None:
    """Extracts the section for a specific version from CHANGELOG.md.
    Supports headings like:
      ## [v1.3.0]
      ## [1.3.0]
      ## v1.3.0
      ## 1.3.0
    Returns markdown text of the section, or None if not found.
    """
    if changelog_path is None:
        changelog_path = os.path.join(ROOT_DIR, "CHANGELOG.md")

    if not os.path.isfile(changelog_path):
        return None

    clean_ver = version.lstrip("v")
    header_patterns = (
        f"## [v{clean_ver}]",
        f"## [{clean_ver}]",
        f"## v{clean_ver}",
        f"## {clean_ver}",
    )

    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None

    in_target = False
    section_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if any(stripped.startswith(pat) for pat in header_patterns):
                in_target = True
                continue
            elif in_target:
                # Reached next version section
                break
        elif in_target:
            section_lines.append(line)

    if not in_target or not section_lines:
        return None

    res = "".join(section_lines).strip()
    while res.endswith("---"):
        res = res[:-3].strip()
    return res


def extract_git_commits(version: str) -> str | None:
    """Dynamically extracts git commit messages since the previous tag as a fallback."""
    try:
        cmd = ["git", "describe", "--tags", "--abbrev=0", "HEAD^"]
        prev_tag = subprocess.check_output(cmd, cwd=ROOT_DIR, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        log_range = f"{prev_tag}..HEAD"
    except Exception:
        log_range = "-n 10"

    try:
        if ".." in log_range:
            cmd = ["git", "log", log_range, "--oneline"]
        else:
            cmd = ["git", "log", "-n", "10", "--oneline"]
        output = subprocess.check_output(cmd, cwd=ROOT_DIR, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        if output:
            commits = []
            for line in output.splitlines():
                parts = line.strip().split(" ", 1)
                if len(parts) == 2:
                    commits.append(f"- {parts[1]} (`{parts[0]}`)")
                else:
                    commits.append(f"- {line.strip()}")
            return "\n".join(commits)
    except Exception:
        pass
    return None


def create_release_notes(version: str = VERSION) -> str:
    """Generates RELEASE_NOTES.md describing release contents and authentic version changes."""
    notes_path = os.path.join(DIST_DIR, "RELEASE_NOTES.md")
    clean_ver = version.lstrip("v")
    display_ver = f"v{clean_ver}"

    # 1. Try to extract version details from CHANGELOG.md
    changelog_section = extract_changelog_section(clean_ver)

    # 2. If not found in CHANGELOG.md, dynamically pull git commit history
    if not changelog_section:
        git_commits = extract_git_commits(clean_ver)
        if git_commits:
            changelog_section = f"### Commits & Changes in {display_ver}\n{git_commits}"
        else:
            changelog_section = (
                f"- **Universal Sideloading Hub:** Sideload Quest APKs/XAPKs, PCVR EXEs, and Linux native ARM64 apps.\n"
                f"- **Storage & Updates:** Automated storage management, update alerts, and runtime maintenance."
            )

    content = f"""# 🚀 FrameLoad {display_ver}

An all-in-one, on-device VR sideloading engine, mirror catalog browser, and game manager engineered specifically for the **Valve Steam Frame (Galileo / Roy)** running SteamOS and the Lepton Android runtime container.

## ⚡ 1-Click On-Device Installation

Open Konsole on your Steam Frame in Desktop Mode and run:
```bash
curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/install.sh | bash
```

## ✨ Highlights & Changes in {display_ver}

{changelog_section}

## 📦 Distribution Packages
- **`frameload-{display_ver}-standalone.tar.gz`**: Standalone distribution archive including all web UI assets and dependencies.
- **`frameload-installer.sh`**: Self-extracting on-device installer script.
- **`SHA256SUMS`**: Cryptographic integrity checksums.
"""
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"📝 Created {notes_path}")
    return notes_path


def main() -> None:
    os.makedirs(DIST_DIR, exist_ok=True)
    create_release_notes()
    tarball = create_standalone_tarball()
    installer = create_self_extracting_installer(tarball)
    files = [tarball, installer]
    generate_checksums(files)
    print("\n✨ Release build completed successfully!")


if __name__ == "__main__":
    main()
