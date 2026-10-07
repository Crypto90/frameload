#!/usr/bin/env bash
# FrameLoad: 1-Click On-Device Installer for Steam Frame
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m ✔  %s\033[0m\n' "$*"; }
err() { printf '\033[1;31m ✖  %s\033[0m\n' "$*" >&2; }
warn(){ printf '\033[1;33m ℹ  %s\033[0m\n' "$*"; }

# Prevent running as root/sudo directly so paths and Steam ownership match user
if [[ "$(id -u)" -eq 0 && -n "${SUDO_USER:-}" ]]; then
    say "Detected sudo execution. Re-running as user '$SUDO_USER'..."
    exec su - "$SUDO_USER" -c "bash '$0' $*"
fi

# Ensure user runtime environment variables are exported for systemd user bus
if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
    USER_UID="$(id -u)"
    if [[ -d "/run/user/$USER_UID" ]]; then
        export XDG_RUNTIME_DIR="/run/user/$USER_UID"
    fi
fi
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -n "${XDG_RUNTIME_DIR:-}" ]]; then
    if [[ -S "$XDG_RUNTIME_DIR/bus" ]]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    fi
fi

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
            git clone --depth 1 "https://github.com/Crypto90/frameload.git" "$APP_TARGET" 2>/dev/null || true
        fi
    fi

    if [[ ! -f "$APP_TARGET/frameload/cli.py" ]]; then
        say "Fetching latest FrameLoad release archive from GitHub..."
        LATEST_TAG=$(curl -sSL https://api.github.com/repos/Crypto90/frameload/releases/latest 2>/dev/null | grep '"tag_name":' | head -n1 | cut -d'"' -f4 || echo "")
        if [[ -z "$LATEST_TAG" ]]; then
            LATEST_TAG=$(curl -sIL -o /dev/null -w '%{url_effective}' https://github.com/Crypto90/frameload/releases/latest 2>/dev/null | awk -F'/' '{print $NF}')
        fi
        [[ -z "$LATEST_TAG" ]] && LATEST_TAG="v1.2.2"
        say "Downloading release $LATEST_TAG..."
        curl -fsSL "https://github.com/Crypto90/frameload/releases/download/${LATEST_TAG}/frameload-${LATEST_TAG}-standalone.tar.gz" | tar -xzf - -C "$APP_TARGET" || \
        curl -fsSL "https://github.com/Crypto90/frameload/archive/refs/heads/main.tar.gz" | tar -xzf - --strip-components=1 -C "$APP_TARGET"
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

# 2.6 Check standalone application window runtime
say "Checking standalone window runtime..."
if python3 -c "import PyQt6.QtWebEngineWidgets" >/dev/null 2>&1 || \
   python3 -c "import gi; gi.require_version('WebKit2', '4.0')" >/dev/null 2>&1 || \
   python3 -c "import webview" >/dev/null 2>&1; then
    ok "Native standalone application window engine detected"
elif which chromium google-chrome >/dev/null 2>&1 || \
     (which flatpak >/dev/null 2>&1 && (flatpak info org.chromium.Chromium >/dev/null 2>&1 || flatpak info com.google.Chrome >/dev/null 2>&1)); then
    ok "Standalone App-Mode browser detected"
else
    if which pip3 >/dev/null 2>&1 || which pip >/dev/null 2>&1; then
        PIP_CMD=$(which pip3 2>/dev/null || which pip)
        say "Installing pywebview in user space for native window..."
        "$PIP_CMD" install --user --quiet pywebview 2>/dev/null || true
    fi
    ok "Configured standalone kiosk window profile for Steam Frame"
fi

# 3. Create Desktop Entry for SteamOS Desktop Mode
say "Creating Desktop launcher..."
cat > "$APPLICATIONS_DIR/frameload.desktop" <<EOF
[Desktop Entry]
Name=FrameLoad
Comment=On-Device VR Sideloading, Catalog Downloader & Game Manager
Exec=$SCRIPT_DIR/run.sh %u
Icon=$SCRIPT_DIR/frameload/web/static/assets/icon.png
Terminal=false
Type=Application
Categories=Game;VR;Utility;
Keywords=SteamFrame;VR;Sideload;Lepton;
MimeType=x-scheme-handler/frameload;
EOF
chmod +x "$APPLICATIONS_DIR/frameload.desktop"
if which xdg-mime >/dev/null 2>&1; then
    xdg-mime default frameload.desktop x-scheme-handler/frameload 2>/dev/null || true
fi
ok "Created and registered $APPLICATIONS_DIR/frameload.desktop"

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
ExecStart=/usr/bin/python3 -m frameload.cli serve --host 0.0.0.0 --port 5050
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Reload and enable service
SYSTEMD_OK=false
if systemctl --user daemon-reload >/dev/null 2>&1; then
    SYSTEMD_OK=true
fi

if [[ "$SYSTEMD_OK" == "true" ]]; then
    if [[ "${1:-}" != "--no-restart" && "${1:-}" != "--update" ]]; then
        systemctl --user enable --now frameload.service 2>/dev/null || true
        ok "FrameLoad service enabled via systemd user manager"
    else
        systemctl --user enable frameload.service 2>/dev/null || true
        ok "FrameLoad service updated (restart deferred)"
    fi
else
    say "Note: systemd user session bus not directly accessible in this terminal."
    say "Configuring XDG user autostart and background daemon fallback..."
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/frameload.desktop" <<EOF
[Desktop Entry]
Name=FrameLoad
Exec=$SCRIPT_DIR/run.sh --daemon
Type=Application
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    chmod +x "$HOME/.config/autostart/frameload.desktop"
    ok "Configured user autostart in ~/.config/autostart/frameload.desktop"
fi

# Ensure FrameLoad daemon is active right now
say "Starting FrameLoad daemon..."
bash "$SCRIPT_DIR/run.sh" --daemon || true

# 5. Add FrameLoad to Steam as a Non-Steam Game shortcut with full Steam Grid artwork
say "Adding FrameLoad shortcut to Steam library with full Grid artwork..."
python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from frameload.system.shortcuts import register_game_in_steam

res = register_game_in_steam(
    title='FrameLoad',
    launch_script_path='$SCRIPT_DIR/run.sh',
    anchor_dir='$SCRIPT_DIR',
    icon_path='$SCRIPT_DIR/frameload/web/static/assets/icon.png',
    artwork_dir='$SCRIPT_DIR/frameload/web/static/assets',
    is_vr=False,
    launch_options=''
)
if res.get('success'):
    print('✔ Successfully registered FrameLoad in Steam shortcuts.vdf!')
    for u in res.get('users', {}):
        print(f'  - Steam User ID: {u} (Artwork installed)')
else:
    print('ℹ Steam registration notice:', res.get('error'))
" || true

if pgrep -x steam >/dev/null 2>&1; then
    printf '\n\033[1;33mℹ Steam is currently running. Please restart Steam (or switch to Gaming Mode) to see FrameLoad in your library.\033[0m\n'
fi

# 6. Verify server connectivity
say "Verifying FrameLoad web server..."
SERVER_OK=false
for _ in {1..10}; do
    if curl -s --connect-timeout 1 http://127.0.0.1:5050/api/config >/dev/null 2>&1; then
        SERVER_OK=true
        break
    fi
    sleep 0.5
done

if [[ "$SERVER_OK" == "true" ]]; then
    ok "FrameLoad server is verified RUNNING and accessible!"
else
    say "Starting server fallback process directly..."
    export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"
    nohup /usr/bin/python3 -m frameload.cli serve --host 0.0.0.0 --port 5050 > "$HOME/.local/share/frameload/server.log" 2>&1 &
    sleep 1.5
    if curl -s --connect-timeout 1 http://127.0.0.1:5050/api/config >/dev/null 2>&1; then
        ok "FrameLoad server is verified RUNNING!"
    else
        err "FrameLoad server failed to start! Recent logs:"
        if [[ -f "$HOME/.local/share/frameload/server.log" ]]; then
            tail -n 15 "$HOME/.local/share/frameload/server.log" | while IFS= read -r line; do
                printf '\033[0;31m  %s\033[0m\n' "$line" >&2
            done
        fi
    fi
fi

say "================================================================="
ok "FrameLoad successfully installed!"
printf "  🌐 Dashboard URL:    \033[1;33mhttp://localhost:5050\033[0m\n"
printf "  📱 Over Local Wi-Fi: \033[1;33mhttp://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<frame-ip>'):5050\033[0m\n"
printf "  🎮 In Headset:       Launch 'FrameLoad' directly from your Steam library!\n"
say "================================================================="
