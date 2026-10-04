#!/usr/bin/env bash
# FrameLoad: Complete Clean Uninstaller for Steam Frame & SteamOS
set -euo pipefail

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m ✔  %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m ⚠  %s\033[0m\n' "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
FRAMELOAD_DIR="$HOME/.local/share/frameload"
APPLICATIONS_DIR="$HOME/.local/share/applications"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
GAMES_DIR="$HOME/Applications/quest-frame"
APP_TARGET="$HOME/Applications/FrameLoad"

# CLI Options
NON_INTERACTIVE=false
PURGE_GAMES=false
KEEP_BACKUPS=true

for arg in "$@"; do
    case "$arg" in
        -y|--yes)
            NON_INTERACTIVE=true
            ;;
        --purge-games)
            PURGE_GAMES=true
            ;;
        --keep-games)
            PURGE_GAMES=false
            ;;
        --keep-backups)
            KEEP_BACKUPS=true
            ;;
        --purge-backups)
            KEEP_BACKUPS=false
            ;;
        --purge-all)
            NON_INTERACTIVE=true
            PURGE_GAMES=true
            KEEP_BACKUPS=false
            ;;
        -h|--help)
            cat <<EOF
Usage: ./uninstall.sh [OPTIONS]

Completely and cleanly uninstalls FrameLoad from the Steam Frame, removing
systemd services, desktop entries, Steam shortcuts, grid artwork, and caches.

Options:
  -y, --yes          Non-interactive mode (skips confirmation prompts)
  --purge-games      Also delete all sideloaded VR games in ~/Applications/quest-frame
  --keep-games       Preserve installed VR games and their Steam shortcuts (default)
  --keep-backups     Preserve game save backups in ~/.local/share/frameload/backups (default)
  --purge-backups    Permanently delete all save game backups
  --purge-all        Total clean wipe: remove app, caches, games, and backups
  -h, --help         Show this help message
EOF
            exit 0
            ;;
    esac
done

say "================================================================="
say "           FrameLoad Clean Uninstaller for Steam Frame"
say "================================================================="

# Interactive prompts if not -y
if [[ "$NON_INTERACTIVE" != true ]]; then
    printf "\nThis will completely remove FrameLoad and its system integrations from your device.\n"
    read -r -p "Are you sure you want to uninstall FrameLoad? [y/N] " confirm_uninstall
    if [[ "$confirm_uninstall" != "y" && "$confirm_uninstall" != "Y" && "$confirm_uninstall" != "yes" ]]; then
        warn "Uninstallation cancelled by user."
        exit 0
    fi

    read -r -p "Do you also want to delete all sideloaded VR games in ~/Applications/quest-frame? [y/N] " confirm_games
    if [[ "$confirm_games" == "y" || "$confirm_games" == "Y" || "$confirm_games" == "yes" ]]; then
        PURGE_GAMES=true
    fi

    read -r -p "Do you want to preserve your game save backups? [Y/n] " confirm_backups
    if [[ "$confirm_backups" == "n" || "$confirm_backups" == "N" || "$confirm_backups" == "no" ]]; then
        KEEP_BACKUPS=false
    fi
fi

say "Beginning clean uninstallation..."

# 1. Stop and remove background systemd user service
say "1/6 Stopping and disabling systemd background service..."
if which systemctl >/dev/null 2>&1; then
    systemctl --user stop frameload.service 2>/dev/null || true
    systemctl --user disable frameload.service 2>/dev/null || true
    if [[ -f "$SYSTEMD_USER_DIR/frameload.service" ]]; then
        rm -f "$SYSTEMD_USER_DIR/frameload.service"
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user reset-failed 2>/dev/null || true
        ok "Removed $SYSTEMD_USER_DIR/frameload.service"
    else
        ok "No systemd service file found"
    fi
fi

# Kill any lingering python serve processes
pkill -f "frameload/cli.py serve" 2>/dev/null || true
pkill -f "frameload.cli serve" 2>/dev/null || true

# 2. Remove desktop launcher
say "2/6 Removing desktop application launcher..."
if [[ -f "$APPLICATIONS_DIR/frameload.desktop" ]]; then
    rm -f "$APPLICATIONS_DIR/frameload.desktop"
    if which update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true
    fi
    ok "Removed $APPLICATIONS_DIR/frameload.desktop"
else
    ok "No desktop launcher found"
fi

# 3. Remove FrameLoad shortcut and grid artwork from Steam
say "3/6 Unregistering FrameLoad and artwork from Steam..."
python3 -c "
import glob, os, sys

steam_dirs = [
    os.path.expanduser('~/.local/share/Steam'),
    os.path.expanduser('~/.steam/steam'),
    os.path.expanduser('~/.steam/root'),
]

for sdir in steam_dirs:
    userdata = os.path.join(sdir, 'userdata')
    if not os.path.isdir(userdata):
        continue
    users = [d for d in os.listdir(userdata) if d.isdigit() and d != '0']
    for user in users:
        vdf_path = os.path.join(userdata, user, 'config/shortcuts.vdf')
        if not os.path.isfile(vdf_path):
            continue
        try:
            with open(vdf_path, 'rb') as f:
                content = f.read()
            # Find and clean entries matching FrameLoad
            # Using FrameLoad's built-in decoder if accessible, or clean byte inspection
            import re
            cleaned = re.sub(b'\\x00[0-9]+\\x00\\x02appid\\x00[\\s\\S]*?FrameLoad[\\s\\S]*?\\x08\\x08', b'', content)
            if cleaned != content:
                with open(vdf_path, 'wb') as f:
                    f.write(cleaned)
                print(f'Cleaned FrameLoad shortcut from {vdf_path}')
        except Exception as e:
            pass

        # Clean grid artwork
        grid_dir = os.path.join(userdata, user, 'config/grid')
        if os.path.isdir(grid_dir):
            for pattern in ('*FrameLoad*', '*frameload*'):
                for f in glob.glob(os.path.join(grid_dir, pattern)):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
" 2>/dev/null || true
ok "Cleaned Steam shortcuts and grid artwork"

# 4. Handle Lepton containers & installed games
say "4/6 Checking running containers and game libraries..."
if which podman >/dev/null 2>&1; then
    containers=$(podman ps -a --format "{{.Names}}" 2>/dev/null | grep "^lepton-steamlaunch-" || true)
    if [[ -n "$containers" ]]; then
        echo "$containers" | xargs -r podman rm -f 2>/dev/null || true
        ok "Stopped and removed running Lepton VR game containers"
    fi
fi

if [[ "$PURGE_GAMES" == true ]]; then
    if [[ -d "$GAMES_DIR" ]]; then
        rm -rf "$GAMES_DIR"
        ok "Purged sideloaded games directory: $GAMES_DIR"
    fi

    # Check MicroSD mounts
    if [[ -f /proc/mounts ]]; then
        grep -E '/run/media/|/media/|/mnt/' /proc/mounts 2>/dev/null | while read -r line; do
            m_path=$(echo "$line" | awk '{print $2}')
            if [[ -d "$m_path/quest-frame" ]]; then
                rm -rf "$m_path/quest-frame"
                ok "Purged games on MicroSD at: $m_path/quest-frame"
            fi
        done || true
    fi
else
    ok "Preserved installed VR games in $GAMES_DIR"
fi

# 5. Clean up application data, caches, and configs
say "5/6 Cleaning data, cache, and configuration files..."
if [[ -d "$FRAMELOAD_DIR" ]]; then
    if [[ "$KEEP_BACKUPS" == true ]]; then
        # Preserve backups, delete cache, data, bin, config
        find "$FRAMELOAD_DIR" -mindepth 1 -maxdepth 1 ! -name 'backups' -exec rm -rf {} + 2>/dev/null || true
        ok "Cleaned cache and data, preserved save backups in $FRAMELOAD_DIR/backups"
    else
        rm -rf "$FRAMELOAD_DIR"
        ok "Purged entire FrameLoad data directory: $FRAMELOAD_DIR"
    fi
fi

if [[ -d "$HOME/.config/frameload" ]]; then
    rm -rf "$HOME/.config/frameload"
    ok "Removed $HOME/.config/frameload"
fi

# 6. Remove FrameLoad installation files (if installed in ~/Applications/FrameLoad)
say "6/6 Finalizing application removal..."
if [[ -d "$APP_TARGET" && "$APP_TARGET" != "$SCRIPT_DIR" ]]; then
    rm -rf "$APP_TARGET"
    ok "Removed application directory: $APP_TARGET"
elif [[ "$SCRIPT_DIR" == "$APP_TARGET" ]]; then
    # We are running inside the directory being deleted; schedule self-cleanup
    trap 'rm -rf "$APP_TARGET" 2>/dev/null || true' EXIT
    ok "Scheduled removal of $APP_TARGET upon exit"
fi

say "================================================================="
ok "FrameLoad has been completely and cleanly uninstalled!"
if [[ "$KEEP_BACKUPS" == true && -d "$FRAMELOAD_DIR/backups" ]]; then
    printf "  💾 Your save game backups were preserved at:\n     \033[1;33m%s/backups\033[0m\n" "$FRAMELOAD_DIR"
fi
printf "  ✨ No background services, shortcuts, or cache files remain.\n"
say "================================================================="
