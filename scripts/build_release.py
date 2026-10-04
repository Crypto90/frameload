#!/usr/bin/env python3
"""FrameLoad Release Artifacts Builder.
Creates standalone distribution tarballs, self-extracting shell installer (.sh),
and cryptographic checksums (SHA256SUMS).
"""
from __future__ import annotations

import hashlib
import os
import shutil
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

        # Include root runner and installer scripts
        for item in ["install.sh", "run.sh", "setup.py", "README.md"]:
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


def create_release_notes() -> str:
    """Generates RELEASE_NOTES.md describing release contents and features."""
    notes_path = os.path.join(DIST_DIR, "RELEASE_NOTES.md")
    content = f"""# 🚀 FrameLoad v{VERSION}

An all-in-one, on-device VR sideloading engine, mirror catalog browser, and game manager engineered specifically for the **Valve Steam Frame (Galileo / Roy)** running SteamOS and the Lepton Android runtime container.

## ⚡ 1-Click On-Device Installation

Open Konsole on your Steam Frame in Desktop Mode and run:
```bash
curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/install.sh | bash
```

## ✨ Highlights & Features in v{VERSION}
- **📊 Steam-Style Storage Manager:** Multi-drive overview (Internal NVMe SSD & MicroSD Card) with multi-colored segmented storage visualizer and 1-click drive migrator.
- **📥 Universal Sideloading Hub & 2D Window Presets:** Sideload Quest APKs/XAPKs, Windows PCVR & Flat EXEs (via Proton ARM64 / FEX-Emu), and Linux native ARM64 apps with theater window presets (Tablet, Ultrawide, IMAX).
- **🎵 Beat Saber Mods & Custom Songs:** Full custom content management with auto-folder creation, permission unlocking, song listing, and 1-click mod injector.
- **🔄 On-Device Self-Updating Daemon:** In-headset update alerts with top header chip, prominent banner, and 1-click zero-downtime service reload.
- **🎨 Complete Steam Grid Visual Assets:** High-resolution vertical posters (600x900), banners (920x430), heroes (1920x620), and 512x512 icons for SteamOS and SteamVR.
- **☕ Ko-fi Integration:** Direct developer support links in header and diagnostics.
- **🧹 Full Clean Uninstaller:** Complete trace removal option in Settings & Diagnostics.

## 📦 Distribution Packages
- **`frameload-v{VERSION}-standalone.tar.gz`**: Standalone distribution archive including all web UI assets and dependencies.
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
