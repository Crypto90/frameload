#!/usr/bin/env bash
# FrameLoad: uninstaller for the Steam Frame and SteamOS.
# The work is done by FrameLoad's own uninstaller (the one behind System > Clean Uninstallation), which
# removes only FrameLoad's own Steam shortcut and saves the signing keys of ported games first.
set -euo pipefail

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m ✔  %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m ⚠  %s\033[0m\n' "$*"; }

if [[ "$(id -u)" -eq 0 && -n "${SUDO_USER:-}" ]]; then
    warn "Run this as your normal user, not with sudo: FrameLoad lives in your own home folder."
    exit 1
fi

# systemctl --user needs the session's bus, which a pipe or an SSH shell may not have set.
if [[ -z "${XDG_RUNTIME_DIR:-}" && -d "/run/user/$(id -u)" ]]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "${XDG_RUNTIME_DIR:-}/bus" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" 2>/dev/null && pwd || echo "$PWD")"
FRAMELOAD_DIR="$HOME/.local/share/frameload"
DEFAULT_APP_DIR="$HOME/Applications/FrameLoad"

NON_INTERACTIVE=false
PURGE_GAMES=false
KEEP_BACKUPS=true

for arg in "$@"; do
    case "$arg" in
        -y|--yes) NON_INTERACTIVE=true ;;
        --purge-games) PURGE_GAMES=true ;;
        --keep-games) PURGE_GAMES=false ;;
        --keep-backups) KEEP_BACKUPS=true ;;
        --purge-backups) KEEP_BACKUPS=false ;;
        --purge-all)
            NON_INTERACTIVE=true
            PURGE_GAMES=true
            KEEP_BACKUPS=false
            ;;
        -h|--help)
            cat <<EOF
Usage: bash uninstall.sh [OPTIONS]

Removes FrameLoad from this Steam Frame: its background service, desktop entry, the frameload
command, its own Steam shortcut and artwork, and its data in ~/.local/share/frameload.
Installed games and their Steam shortcuts stay unless --purge-games is given. The signing keys
of ported games are saved to ~/Documents/FrameLoad-signing-keys.

Options:
  -y, --yes          Do not ask questions
  --purge-games      Also delete every installed game (internal storage, microSD card, USB drives)
  --keep-games       Keep installed games (default)
  --keep-backups     Keep save backups in ~/.local/share/frameload/backups (default)
  --purge-backups    Also delete the save backups
  --purge-all        Same as --yes --purge-games --purge-backups
  -h, --help         Show this help
EOF
            exit 0
            ;;
        *)
            warn "Unknown option: $arg (see --help)"
            exit 2
            ;;
    esac
done

# Questions are read from the terminal, so this also works as `curl ... | bash`.
ask() {
    local answer=""
    read -r -p "$1" answer </dev/tty || answer=""
    printf '%s' "$answer"
}

if [[ "$NON_INTERACTIVE" != true ]]; then
    if ! { true </dev/tty; } 2>/dev/null; then
        warn "No terminal to ask questions on. Run it again with --yes (and --purge-games / --purge-backups if wanted)."
        exit 1
    fi
    printf "\nThis removes FrameLoad and its system integration from this device.\n"
    case "$(ask "Uninstall FrameLoad? [y/N] ")" in
        y|Y|yes|YES) ;;
        *) warn "Nothing was changed."; exit 0 ;;
    esac
    case "$(ask "Also delete all installed games? [y/N] ")" in
        y|Y|yes|YES) PURGE_GAMES=true ;;
    esac
    case "$(ask "Keep your save backups? [Y/n] ")" in
        n|N|no|NO) KEEP_BACKUPS=false ;;
    esac
fi

# A server started without systemd (run.sh --daemon, the autostart entry) would keep writing into the
# folders that are about to be deleted.
pkill -f "frameload.cli serve" 2>/dev/null || true

# The FrameLoad that is installed: this script's own folder, or the standard install folder.
APP_DIR=""
for candidate in "$SCRIPT_DIR" "${FRAMELOAD_INSTALL_DIR:-$DEFAULT_APP_DIR}" "$DEFAULT_APP_DIR"; do
    if [[ -f "$candidate/frameload/cli.py" ]]; then
        APP_DIR="$candidate"
        break
    fi
done

if [[ -n "$APP_DIR" ]]; then
    say "Uninstalling FrameLoad ($APP_DIR)..."
    # Run from a copy of the program: the uninstaller deletes ~/Applications/FrameLoad while it runs.
    # The function is called directly because it has the same signature in every version since v1.3.0.
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    cp -r "$APP_DIR/frameload" "$work/frameload"
    (cd "$work" && PYTHONPATH="$work" FL_PURGE_GAMES="$PURGE_GAMES" FL_KEEP_BACKUPS="$KEEP_BACKUPS" python3 -c '
import glob, os
from frameload.manager import uninstaller
from frameload.manager.uninstaller import Uninstaller
from frameload.system import shortcuts
if not hasattr(shortcuts, "is_frameload_itself"):
    # Up to v1.3.6 any shortcut whose path contained "frameload" was taken for FrameLoad itself,
    # games on a drive named FrameLoad included. Match the title only.
    def unregister_app_from_steam(title="FrameLoad", **_):
        removed = False
        for user in shortcuts.get_steam_users():
            config = os.path.join(shortcuts.STEAM_DIR, "userdata", user, "config")
            for appid in shortcuts.remove_shortcut_by_title_or_exe(os.path.join(config, "shortcuts.vdf"), title=title):
                removed = True
                for art in glob.glob(os.path.join(config, "grid", f"{appid}*")):
                    os.remove(art)
        return removed
    uninstaller.unregister_app_from_steam = unregister_app_from_steam
res = Uninstaller.uninstall_frameload_app(purge_games=os.environ["FL_PURGE_GAMES"] == "true",
                                          keep_backups=os.environ["FL_KEEP_BACKUPS"] == "true")
for line in res.get("details", []):
    print("  " + line)
')
    # Older versions leave these two behind.
    rm -f "$HOME/.local/bin/frameload" "$HOME/.config/autostart/frameload.desktop"
    if [[ -d "$APP_DIR" && "$APP_DIR" != "$DEFAULT_APP_DIR" ]]; then
        warn "The program folder $APP_DIR was left in place; delete it yourself if you no longer need it."
    fi
else
    # Without FrameLoad's program there is no safe way to edit Steam's shortcut list, so it is left alone.
    warn "FrameLoad's program folder was not found. Removing its service, launcher and data only."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user stop frameload.service 2>/dev/null || true
        systemctl --user disable frameload.service 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/frameload.service"
        systemctl --user daemon-reload 2>/dev/null || true
    fi
    rm -f "$HOME/.local/share/applications/frameload.desktop" "$HOME/.local/bin/frameload" "$HOME/.config/autostart/frameload.desktop"
    keys="$FRAMELOAD_DIR/frameport-home/overport-workspace/signatures"
    if compgen -G "$keys/*.keystore" >/dev/null; then
        mkdir -p "$HOME/Documents/FrameLoad-signing-keys"
        cp -n "$keys"/*.keystore "$HOME/Documents/FrameLoad-signing-keys/"
        ok "Signing keys of ported games saved to ~/Documents/FrameLoad-signing-keys"
    fi
    if [[ -d "$FRAMELOAD_DIR" ]]; then
        if [[ "$KEEP_BACKUPS" == true ]]; then
            find "$FRAMELOAD_DIR" -mindepth 1 -maxdepth 1 ! -name backups -exec rm -rf {} + 2>/dev/null || true
        else
            rm -rf "$FRAMELOAD_DIR"
        fi
    fi
    if [[ "$PURGE_GAMES" == true ]]; then
        warn "Games were not deleted. Remove ~/Applications/quest-frame (and quest-frame on any card) yourself."
    fi
    warn "FrameLoad's Steam shortcut was left in Steam; remove it there (Manage > Remove non-Steam game)."
fi

pkill -f "frameload.cli serve" 2>/dev/null || true

say "FrameLoad was uninstalled."
if [[ "$KEEP_BACKUPS" == true && -d "$FRAMELOAD_DIR/backups" ]]; then
    printf "  Save backups were kept in \033[1;33m%s/backups\033[0m\n" "$FRAMELOAD_DIR"
fi
if [[ "$PURGE_GAMES" != true ]]; then
    printf "  Installed games stay in ~/Applications/quest-frame and in your Steam library.\n"
fi
