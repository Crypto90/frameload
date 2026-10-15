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
case "${1:-}" in
    serve|info|list|storage|move|sync|search|install|inject-mod|handle-url|launch|uninstall|uninstall-app|window|tune|doctor|allow-host|port|sync-shortcuts|stop)
        exec /usr/bin/python3 -m frameload.cli "$@" ;;
    -h|--help)
        exec /usr/bin/python3 -m frameload.cli --help ;;
esac

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

if [[ "${1:-}" == frameload://* ]]; then
    /usr/bin/python3 -m frameload.cli handle-url "$1" || true
fi

# Launch UI window (SteamOS Gaming Mode & Standalone VR compatible)
# Exactly one window is opened and this script lives exactly as long as it: Steam follows this
# process, so closing FrameLoad in Steam closes the window, and closing the window ends the app.
# A window that ran and was closed can exit non-zero, so a failed exit is never a reason to try the
# next browser (that retry used to reopen Firefox behind the closed window).
WINDOW_LOCK="$DATA_DIR/window.lock"
BROWSER_PID=""

close_window() {
    trap - TERM INT HUP
    if [[ -n "$BROWSER_PID" ]]; then
        kill -TERM "$BROWSER_PID" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$BROWSER_PID" 2>/dev/null || break
            sleep 0.3
        done
        kill -KILL "$BROWSER_PID" 2>/dev/null || true
    fi
    exit 0
}

run_window() {
    "$@" &
    BROWSER_PID=$!
    trap close_window TERM INT HUP
    wait "$BROWSER_PID" || true
    BROWSER_PID=""
    exit 0
}

# Fullscreen without browser controls in Gaming Mode and in the headset; a normal window on a desktop.
use_kiosk() {
    case "${FRAMELOAD_WINDOW:-}" in
        kiosk) return 0 ;;
        normal) return 1 ;;
    esac
    case "${XDG_CURRENT_DESKTOP:-}" in
        *KDE*|*GNOME*|*XFCE*) return 1 ;;
    esac
    return 0
}

# A profile of FrameLoad's own: the window never attaches to another Firefox (which would keep the
# dashboard open after FrameLoad closes) and never shows first-run pages or session restore.
firefox_profile() {
    mkdir -p "$1"
    cat > "$1/user.js" <<'PREFS'
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.max_resumed_crashes", 0);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.warnOnQuit", false);
user_pref("browser.translations.automaticallyPopup", false);
user_pref("signon.rememberSignons", false);
user_pref("app.update.auto", false);
PREFS
}

flatpak_has() {
    which flatpak >/dev/null 2>&1 && flatpak info "$1" >/dev/null 2>&1
}

launch_app_window() {
    # One FrameLoad window at a time: a frameload:// link opened while it is up is handled by the
    # running dashboard instead of a second window.
    exec 8>"$WINDOW_LOCK"
    if ! flock -n 8; then
        echo "FrameLoad's window is already open."
        exit 0
    fi

    local flatpak_args=()
    if which flatpak >/dev/null 2>&1 && flatpak run --help 2>/dev/null | grep -q -- "--die-with-parent"; then
        flatpak_args=(--die-with-parent)  # ends the sandboxed browser together with this script
    fi

    # Method 1: a native window (Qt WebEngine, WebKit2GTK or pywebview), when one is installed
    if /usr/bin/python3 -m frameload.web.window --check >/dev/null 2>&1; then
        run_window /usr/bin/python3 -m frameload.web.window --url "$URL"
    fi

    # Method 2: Chromium / Chrome app window with a profile of its own
    for BROWSER in google-chrome-stable google-chrome chromium-browser chromium; do
        if which "$BROWSER" >/dev/null 2>&1; then
            run_window "$BROWSER" --app="$URL" --class="FrameLoad" --window-size=1280,800 \
                --user-data-dir="$DATA_DIR/chromium-profile" --no-first-run --no-default-browser-check \
                --disable-features=TranslateUI --enable-features=OverlayScrollbar
        fi
    done
    for APP in org.chromium.Chromium com.google.Chrome; do
        if flatpak_has "$APP"; then
            run_window flatpak run "${flatpak_args[@]}" "$APP" --app="$URL" --class="FrameLoad" \
                --window-size=1280,800 --user-data-dir="$HOME/.var/app/$APP/frameload-profile" \
                --no-first-run --no-default-browser-check
        fi
    done

    # Method 3: Firefox (SteamOS ships it as the org.mozilla.firefox Flatpak). The sandbox can only
    # read profiles inside its own ~/.var/app folder.
    local mode=()
    if use_kiosk; then mode=(--kiosk); fi
    if flatpak_has org.mozilla.firefox; then
        local profile="$HOME/.var/app/org.mozilla.firefox/frameload-profile"
        firefox_profile "$profile"
        run_window flatpak run "${flatpak_args[@]}" org.mozilla.firefox --no-remote --profile "$profile" "${mode[@]}" "$URL"
    fi
    if which firefox >/dev/null 2>&1; then
        firefox_profile "$DATA_DIR/firefox-profile"
        run_window firefox --no-remote --profile "$DATA_DIR/firefox-profile" "${mode[@]}" "$URL"
    fi

    # Method 4: whatever opens web pages on this system. That browser is not ours to close, so stay
    # alive while the server runs to keep Steam's session.
    if which xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 || true
    else
        python3 -m webbrowser "$URL" >/dev/null 2>&1 || true
    fi
    while is_server_alive; do
        sleep 2
    done
}

launch_app_window
