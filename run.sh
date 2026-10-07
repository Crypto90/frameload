#!/usr/bin/env bash
# ==============================================================================
# FrameLoad Runner & Steam Integration Launcher
# Compatible with SteamOS Gaming Mode, SteamVR & Linux Desktop
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

PORT="${FRAMELOAD_PORT:-5050}"
URL="http://127.0.0.1:${PORT}"
DATA_DIR="$HOME/.local/share/frameload"
PID_FILE="$DATA_DIR/frameload.pid"
LOG_FILE="$DATA_DIR/server.log"

mkdir -p "$DATA_DIR"

is_server_alive() {
    python3 -c "
import urllib.request, sys
try:
    with urllib.request.urlopen('$URL/api/config', timeout=1) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1
}

start_daemon_if_needed() {
    if is_server_alive; then
        return 0
    fi

    # Set systemd environment if in a subshell without XDG_RUNTIME_DIR
    if [[ -z "${XDG_RUNTIME_DIR:-}" && -d "/run/user/$(id -u)" ]]; then
        export XDG_RUNTIME_DIR="/run/user/$(id -u)"
    fi
    if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "${XDG_RUNTIME_DIR:-}/bus" ]]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    fi

    # Try starting via systemd user service first
    if systemctl --user is-enabled frameload.service >/dev/null 2>&1; then
        systemctl --user start frameload.service 2>/dev/null || true
        for _ in {1..6}; do
            if is_server_alive; then return 0; fi
            sleep 0.5
        done
    fi

    # Fallback: start direct background process
    if [[ -f "$PID_FILE" ]]; then
        OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 0.5
        fi
    fi

    nohup /usr/bin/python3 -m frameload.cli serve --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    for _ in {1..12}; do
        if is_server_alive; then return 0; fi
        sleep 0.5
    done
}

# 1. Direct CLI commands pass-through
if [[ "${1:-}" == "serve" || "${1:-}" == "info" || "${1:-}" == "install" || "${1:-}" == "sync" || "${1:-}" == "list" || "${1:-}" == "storage" || "${1:-}" == "move" || "${1:-}" == "uninstall" || "${1:-}" == "uninstall-app" || "${1:-}" == "inject-mod" || "${1:-}" == "window" || "${1:-}" == "tune" ]]; then
    exec /usr/bin/python3 -m frameload.cli "$@"
fi

if [[ "${1:-}" == "--daemon" ]]; then
    start_daemon_if_needed
    if is_server_alive; then
        printf "\033[1;32m✔ FrameLoad server running at %s\033[0m\n" "$URL"
        exit 0
    else
        printf "\033[1;31m✖ Failed to start FrameLoad server. Check %s\033[0m\n" "$LOG_FILE" >&2
        if [[ -f "$LOG_FILE" ]]; then
            printf "\033[1;31m--- Recent Server Log ---\033[0m\n" >&2
            tail -n 15 "$LOG_FILE" | while IFS= read -r line; do
                printf "\033[0;31m  %s\033[0m\n" "$line" >&2
            done
            printf "\033[1;31m-------------------------\033[0m\n" >&2
        fi
        exit 1
    fi
fi

if [[ "${1:-}" == "--kill" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$PID" ]]; then
            kill "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
        fi
    fi
    systemctl --user stop frameload.service 2>/dev/null || true
    printf "FrameLoad server stopped.\n"
    exit 0
fi

# 2. Steam & Interactive Launch: Ensure server is running, then open standalone app window
start_daemon_if_needed

# Launch UI window (SteamOS Gaming Mode & Standalone VR compatible)
# In Gaming Mode, gamescope requires a graphic window to be attached to the shortcut PID
launch_app_window() {
    # Method 1: Native Standalone Python Window (PyQt6 / WebKit2GTK / pywebview)
    # Launches as a 100% native desktop application with ZERO external browser chrome
    if /usr/bin/python3 -m frameload.web.window --url "$URL" 2>/dev/null; then
        exit 0
    elif python3 -m frameload.web.window --url "$URL" 2>/dev/null; then
        exit 0
    fi

    # Method 2: Native or Flatpak Chromium / Chrome in standalone App Mode
    for BROWSER in google-chrome-stable google-chrome chromium-browser chromium; do
        if which "$BROWSER" >/dev/null 2>&1; then
            exec "$BROWSER" \
                --app="$URL" \
                --class="FrameLoad" \
                --window-size=1280,800 \
                --no-first-run \
                --no-default-browser-check \
                --disable-features=TranslateUI \
                --enable-features=OverlayScrollbar
        fi
    done

    if which flatpak >/dev/null 2>&1; then
        if flatpak info org.chromium.Chromium >/dev/null 2>&1; then
            exec flatpak run org.chromium.Chromium --app="$URL" --class="FrameLoad" --window-size=1280,800
        elif flatpak info com.google.Chrome >/dev/null 2>&1; then
            exec flatpak run com.google.Chrome --app="$URL" --class="FrameLoad" --window-size=1280,800
        fi
    fi

    # Method 3: Isolated Kiosk-Mode Window for Firefox (SteamOS Default)
    # Standard --new-window opens Firefox with tabs, address bar, and search menus.
    # --kiosk creates a true borderless app display without ANY browser chrome!
    FF_PROFILE="$DATA_DIR/browser_profile"
    mkdir -p "$FF_PROFILE"
    if [[ ! -f "$FF_PROFILE/user.js" ]]; then
        cat > "$FF_PROFILE/user.js" << 'EOF'
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionPolicyAcceptedVersion", 2);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
EOF
    fi

    if which flatpak >/dev/null 2>&1 && flatpak info org.mozilla.firefox >/dev/null 2>&1; then
        exec flatpak run org.mozilla.firefox --profile "$FF_PROFILE" --kiosk "$URL"
    elif which firefox >/dev/null 2>&1; then
        exec firefox --profile "$FF_PROFILE" --kiosk "$URL"
    fi

    # Method 4: Standard xdg-open / python webbrowser fallback
    if which xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 || true
    else
        python3 -m webbrowser "$URL" >/dev/null 2>&1 || true
    fi

    # Keep script alive while server is up so Steam tracks game session
    while is_server_alive; do
        sleep 2
    done
}

launch_app_window
