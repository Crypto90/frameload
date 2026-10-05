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

    nohup /usr/bin/python3 "$SCRIPT_DIR/frameload/cli.py" serve --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    for _ in {1..12}; do
        if is_server_alive; then return 0; fi
        sleep 0.5
    done
}

# 1. Direct CLI commands pass-through
if [[ "${1:-}" == "serve" || "${1:-}" == "info" || "${1:-}" == "install" || "${1:-}" == "sync" || "${1:-}" == "list" || "${1:-}" == "storage" || "${1:-}" == "move" || "${1:-}" == "uninstall" || "${1:-}" == "uninstall-app" || "${1:-}" == "inject-mod" ]]; then
    exec /usr/bin/python3 -m frameload.cli "$@"
fi

if [[ "${1:-}" == "--daemon" ]]; then
    start_daemon_if_needed
    if is_server_alive; then
        printf "✔ FrameLoad server running at %s\n" "$URL"
        exit 0
    else
        printf "✖ Failed to start FrameLoad server. Check %s\n" "$LOG_FILE" >&2
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

# 2. Steam & Interactive Launch: Ensure server is running, then open dashboard window
start_daemon_if_needed

# Launch UI window (SteamOS Gaming Mode & Desktop Mode compatible)
# In Gaming Mode, gamescope requires a graphic window to be attached to the shortcut PID
launch_browser_window() {
    # Method A: Google Chrome / Chromium in app mode (kiosk / app window without address bar)
    for BROWSER in google-chrome-stable google-chrome chromium-browser chromium; do
        if which "$BROWSER" >/dev/null 2>&1; then
            exec "$BROWSER" \
                --app="$URL" \
                --window-size=1280,800 \
                --no-first-run \
                --no-default-browser-check \
                --disable-features=TranslateUI \
                --enable-features=OverlayScrollbar
        fi
    done

    # Method B: Flatpak Chromium or Chrome
    if which flatpak >/dev/null 2>&1; then
        if flatpak info org.chromium.Chromium >/dev/null 2>&1; then
            exec flatpak run org.chromium.Chromium --app="$URL" --window-size=1280,800
        elif flatpak info com.google.Chrome >/dev/null 2>&1; then
            exec flatpak run com.google.Chrome --app="$URL" --window-size=1280,800
        elif flatpak info org.mozilla.firefox >/dev/null 2>&1; then
            exec flatpak run org.mozilla.firefox --new-window "$URL"
        fi
    fi

    # Method C: Native Firefox
    if which firefox >/dev/null 2>&1; then
        exec firefox --new-window "$URL"
    fi

    # Method D: Standard xdg-open / python webbrowser
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

launch_browser_window
