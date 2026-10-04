#!/usr/bin/env bash
# FrameLoad: 1-Click On-Device Installer for Steam Frame
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m ✔  %s\033[0m\n' "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"

# 0. Self-bootstrapping: If run via curl pipe or outside repo, download FrameLoad first
if [[ ! -f "$SCRIPT_DIR/frameload/cli.py" ]]; then
    APP_TARGET="${FRAMELOAD_INSTALL_DIR:-$HOME/Applications/FrameLoad}"
    say "Bootstrapping FrameLoad into $APP_TARGET..."
    mkdir -p "$APP_TARGET"

    if which git >/dev/null 2>&1; then
        if [[ -d "$APP_TARGET/.git" ]]; then
            git -C "$APP_TARGET" pull --ff-only 2>/dev/null || true
        else
            git clone --depth 1 "https://forgejo.shieldserver.de/Crypto90/FrameLoad.git" "$APP_TARGET" 2>/dev/null || true
        fi
    fi

    if [[ ! -f "$APP_TARGET/frameload/cli.py" ]]; then
        say "Downloading standalone FrameLoad release archive from Forgejo..."
        curl -fsSL "https://forgejo.shieldserver.de/Crypto90/FrameLoad/releases/download/v1.0.0/frameload-v1.0.0-standalone.tar.gz" | tar -xzf - -C "$APP_TARGET"
    fi

    chmod +x "$APP_TARGET/install.sh" "$APP_TARGET/run.sh"
    cd "$APP_TARGET"
    exec bash "$APP_TARGET/install.sh" "$@"
fi

FRAMELOAD_DIR="$HOME/.local/share/frameload"
APPLICATIONS_DIR="$HOME/.local/share/applications"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

say "Installing FrameLoad on $(hostname)..."

# 1. Ensure required directories
mkdir -p "$FRAMELOAD_DIR/bin" "$FRAMELOAD_DIR/cache" "$FRAMELOAD_DIR/data" "$FRAMELOAD_DIR/backups"
mkdir -p "$HOME/Applications/quest-frame"
mkdir -p "$APPLICATIONS_DIR" "$SYSTEMD_USER_DIR"

# 2. Configure podman for Lepton (prevent keyring quota leak)
say "Configuring rootless podman leak fix for Lepton..."
mkdir -p "$HOME/.config/containers"
CONTAINERS_CONF="$HOME/.config/containers/containers.conf"
if [[ ! -f "$CONTAINERS_CONF" ]] || ! grep -qs '^ *keyring *=' "$CONTAINERS_CONF"; then
    printf '[containers]\n# FrameLoad: stop rootless podman leaking a kernel keyring per container start\nkeyring = false\n' >> "$CONTAINERS_CONF"
    ok "Configured keyring = false in $CONTAINERS_CONF"
else
    ok "Podman keyring configuration already optimal"
fi

# 2.5 Ensure standalone static 7-Zip binary exists
if [[ ! -x "$FRAMELOAD_DIR/bin/7za" ]] && ! which 7za 7z >/dev/null 2>&1; then
    say "Setting up standalone 7-Zip archive utility..."
    ARCH="$(uname -m)"
    if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
        curl -sL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-arm64.tar.xz | tar -xJf - -C "$FRAMELOAD_DIR/bin" 7zzs 2>/dev/null || true
    else
        curl -sL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-x64.tar.xz | tar -xJf - -C "$FRAMELOAD_DIR/bin" 7zzs 2>/dev/null || true
    fi
    if [[ -f "$FRAMELOAD_DIR/bin/7zzs" ]]; then
        mv "$FRAMELOAD_DIR/bin/7zzs" "$FRAMELOAD_DIR/bin/7za"
        chmod +x "$FRAMELOAD_DIR/bin/7za"
        ok "Installed standalone 7za in $FRAMELOAD_DIR/bin/7za"
    fi
fi

# 3. Create Desktop Entry for SteamOS Desktop Mode
say "Creating Desktop launcher..."
cat > "$APPLICATIONS_DIR/frameload.desktop" <<EOF
[Desktop Entry]
Name=FrameLoad
Comment=On-Device VR Sideloading, Catalog Downloader & Game Manager
Exec=python3 $SCRIPT_DIR/frameload/cli.py serve
Icon=$SCRIPT_DIR/frameload/web/static/assets/icon.png
Terminal=false
Type=Application
Categories=Game;VR;Utility;
Keywords=SteamFrame;VR;Sideload;Lepton;
EOF
chmod +x "$APPLICATIONS_DIR/frameload.desktop"
ok "Created $APPLICATIONS_DIR/frameload.desktop"

# 4. Create systemd user service (for background operation)
say "Setting up background systemd user service..."
cat > "$SYSTEMD_USER_DIR/frameload.service" <<EOF
[Unit]
Description=FrameLoad On-Device VR Sideloading Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/frameload/cli.py serve --host 0.0.0.0 --port 5050
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Reload and enable service
systemctl --user daemon-reload || true
systemctl --user enable --now frameload.service || true
ok "FrameLoad service enabled on port 5050"

# 5. Add FrameLoad to Steam as a Non-Steam Game shortcut with full Steam Grid artwork
say "Adding FrameLoad shortcut to Steam library with full Grid artwork..."
python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from frameload.system.shortcuts import register_game_in_steam
import os

res = register_game_in_steam(
    title='FrameLoad',
    launch_script_path='$SCRIPT_DIR/run.sh',
    anchor_dir='$SCRIPT_DIR',
    icon_path='$SCRIPT_DIR/frameload/web/static/assets/icon.png',
    artwork_dir='$SCRIPT_DIR/frameload/web/static/assets',
    is_vr=False,
    launch_options=''
)
print('Steam registration result:', res)
" || true

say "================================================================="
ok "FrameLoad successfully installed!"
printf "  🌐 Dashboard URL:    \033[1;33mhttp://localhost:5050\033[0m\n"
printf "  📱 Over Local Wi-Fi: \033[1;33mhttp://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<frame-ip>'):5050\033[0m\n"
printf "  🎮 In Headset:       Launch 'FrameLoad' directly from your Steam library!\n"
say "================================================================="
