# AGENTS.md — FrameLoad Knowledge Base & Guidelines

> **Project:** FrameLoad  
> **Repository:** [https://github.com/Crypto90/frameload.git](https://github.com/Crypto90/frameload.git)  
> **Primary Target:** Valve Steam Frame (Galileo / Roy) running SteamOS (Linux ARM64 / aarch64)  
> **Runtime Environment:** Valve Lepton (Android Container Runtime), Proton ARM64 (FEX-Emu), Monado/SteamVR Native OpenXR

---

## 🎯 1. Project Mission & Core Principles

FrameLoad is an **all-in-one, 100% on-device VR sideloading engine, mirror catalog browser, and game manager** engineered specifically for the Valve Steam Frame standalone VR headset.

- **Zero-PC Requirement:** Operates entirely inside the headset. No companion PC, Android phone, sidecar daemon, or USB tethering is required.
- **Pure Native Python & Web Stack:** The backend runs on pure Python 3 standard library with minimal external dependencies. The web UI uses Vanilla HTML5, CSS3 (dark neon glassmorphism), and Vanilla JavaScript with gamepad/controller navigation.
- **Port:** Default web dashboard runs on port `5050` (`http://127.0.0.1:5050` or `http://<frame-ip>:5050`).

---

## 🔢 2. Versioning & Release Rules (CRITICAL)

Agents working on this repository **MUST** strictly follow this release versioning rule:

1. **Step Increment Rule:**
   - **ONLY** increment versions by `0.0.1`.
   - Progression: `1.0.0` → `1.0.1` → `1.0.2` → ... → `1.0.9` → **`1.1.0`**.
   - **NEVER** jump directly by `0.1.0` (e.g., from `1.0.0` directly to `1.1.0`). Jump to `0.1.0` only after `0.0.9`.
2. **Version Synchronization:**
   - When bumping a version, update **all** of the following:
     - `frameload/__init__.py` (`__version__ = "X.Y.Z"`)
     - `setup.py` (`version="X.Y.Z"`)
     - `CHANGELOG.md` (document authentic release notes under `## [vX.Y.Z]`)
     - `scripts/build_release.py` (imports `__version__` dynamically from `frameload`)
     - `README.md` (installation instructions and links)
3. **Building Releases:**
   - Execute `python3 scripts/build_release.py` to create:
     - `dist/frameload-vX.Y.Z-standalone.tar.gz` (standalone tarball)
     - `dist/frameload-installer.sh` (self-extracting shell installer)
     - `dist/SHA256SUMS` (checksums)
     - `dist/RELEASE_NOTES.md` (release changelog)
4. **Publishing Releases:**
   - **GitHub Actions:** Pushing a git tag `v*` (e.g., `git push origin v1.0.2`) automatically triggers `.github/workflows/release.yml`, builds distribution archives, and publishes the release on GitHub. Pushes to `main` run the tests only; they do not publish.
   - **Direct Script:** `GITHUB_TOKEN="$TOKEN" python3 scripts/github_release.py <tag>` can be used to publish releases and upload assets directly via the GitHub REST API.
5. **Latest Version Grep in Installation Commands:**
   - Never hardcode a static release version in general install instructions. Always dynamically query the latest release from the GitHub API or use GitHub's native redirect:
     ```bash
     TAG=$(curl -s https://api.github.com/repos/Crypto90/frameload/releases/latest | grep '"tag_name":' | cut -d'"' -f4)
     curl -fsSLO "https://github.com/Crypto90/frameload/releases/download/${TAG}/frameload-installer.sh"
     bash frameload-installer.sh
     ```
     Or via the direct GitHub redirect:
     ```bash
     curl -fsSLO https://github.com/Crypto90/frameload/releases/latest/download/frameload-installer.sh
     bash frameload-installer.sh
     ```

---

## 🏗️ 3. Architecture & Codebase Map

### Core Architecture

```
FrameLoad/
├── frameload/
│   ├── catalog/              # Mirror parser, 2D app sources, download queue, multi-threaded downloader
│   │   ├── app_sources.py    # 2D app sources (F-Droid, IzzyOnDroid, Guardian Project, added repos): sync, merge, origins
│   │   ├── repo_index.py     # Signed F-Droid repository index: JAR signature check (pure Python) and parser
│   │   ├── fdroid.py         # Names kept for older code: FDroidCatalog is the F-Droid source
│   │   ├── downloader.py     # Resumable chunks, speed metrics, ETA, completion hooks
│   │   ├── models.py         # CatalogGame and DownloadTask models
│   │   └── vrp_mirror.py     # VRP JSON mirror fetcher & local caching
│   ├── installer/            # Sideloading, patching, and container runners
│   │   ├── axml.py           # Binary AndroidManifest.xml + resources.arsc reader (pure Python)
│   │   ├── apk_analysis.py   # APK inspection + Steam Frame compatibility verdict
│   │   ├── apk_patcher.py    # Compatibility alias for apk_analysis (nothing is patched)
│   │   ├── hand_tracking.py  # Hand input modes -> FrameBridge controller_fix, status report
│   │   ├── porting.py        # Drives FramePort's CLI on the headset to port Quest games (background jobs)
│   │   ├── artwork.py        # Steam Grid artwork scrapers and local generator
│   │   ├── lepton_quest.py   # Lepton install layout, launch.sh generator, OBB pairing
│   │   ├── linux_native.py   # Linux native ARM64 & AppImage launcher via Monado / SteamVR
│   │   ├── package_loader.py # Universal loader (APK, XAPK, APKS, ZIP, Windows EXE, loose folders)
│   │   └── windows_proton.py # Windows PCVR/flat EXEs via Proton ARM64, FEX-Emu, WineOpenXR
│   ├── manager/              # High-level management systems
│   │   ├── backup.py         # Save games backup and restore (~/.local/share/frameload/backups)
│   │   ├── installed.py      # Installed titles catalog, play history (play_stats)
│   │   ├── guard.py          # Freeze guard: memory limit, memory-pressure watchdog, stopping frozen pictures
│   │   ├── sessions.py       # How a game's last session ended ("What happened"), kept evidence, the report
│   │   ├── github_reports.py # Send to GitHub: the report as an issue (user's own token), one issue per signature
│   │   ├── tuning.py         # Per-game settings schema -> launch env + FrameBridge conf keys
│   │   ├── migrate.py        # One-time upgrade of installs made by older versions (layout_version)
│   │   ├── files.py          # File browser roots and uploads from paired devices
│   │   ├── launchlog.py      # Reads launch.log (+ dashboard.log, .last_launch) and names known failures
│   │   ├── launcher.py       # Game launcher (VR vs. Flat)
│   │   ├── mods.py           # Beat Saber custom songs & mod manager, auto-folder & permissions
│   │   ├── settings.py       # System settings, refresh rate (72/80/90/120Hz), resolution scale
│   │   ├── storage.py        # Steam-style storage manager, multi-drive mover, segmented bar visualizer
│   │   ├── uninstaller.py    # Complete clean uninstaller option
│   │   └── updates.py        # On-device self-updater (git pull or release tarball + deferred restart)
│   ├── system/               # OS and Steam integrations
│   │   ├── protocol.py       # Deep linking handler (frameload://)
│   │   ├── shortcuts.py      # Steam shortcuts.vdf reader/writer, multi-path detection, grid artwork
│   │   ├── steam_vdf.py      # Pure Python binary VDF encoder and decoder
│   │   ├── access.py         # Pairing codes and sessions for devices other than the headset
│   │   ├── doctor.py         # Self-test of every assumption about the headset (`frameload doctor`)
│   │   ├── fsutil.py         # Delete/move/inspect Lepton data (podman unshare, filesystem support)
│   │   ├── steam_session.py  # Which shortcuts the running Steam has loaded; safe Steam restart
│   │   ├── steam_ui.py       # Hides Steam's menu over a freshly started game, Show <game> (CEF devtools on 127.0.0.1:8080)
│   │   ├── perf.py           # CPU, memory, PSI, temperatures, GPU clock; a game's GPU time (DRM fdinfo)
│   │   ├── power.py          # Keep-awake via systemd-inhibit while FrameLoad is busy
│   │   └── steamos.py        # Hardware telemetry (battery, storage, Lepton container, Proton status)
│   ├── web/                  # Web Dashboard UI & REST API
│   │   ├── static/           # CSS (style.css), JS (app.js, gamepad.js), and Steam artwork assets
│   │   │   ├── css/skins/    # One stylesheet per look (a-f), loaded only while that look is active
│   │   │   ├── js/skins/     # One view per look (a-f): how it draws the library, registered with registerSkin()
│   │   │   └── fonts/        # Bundled Latin fonts of the looks (fonts.css, OFL.txt)
│   │   └── templates/        # HTML (index.html)
│   ├── cli.py                # Command-line interface and deep-link dispatcher
│   ├── config.py             # Global paths (HOME, STEAM_DIR, ANCHOR_DIR, FRAMELOAD_DIR)
│   └── server.py             # ThreadingHTTPServer and REST API endpoints
├── scripts/
│   ├── build_release.py      # Builds tarballs, self-extracting installer, SHA256SUMS, and release notes
│   ├── capture_screenshots.py# Headless Chrome script for automated 1080p README screenshots
│   └── github_release.py     # Pure Python GitHub REST API release publisher and asset uploader
├── tests/                    # Unit tests (414 cases); axml_builder.py builds test APKs, fake_frameport.py stands in for FramePort,
│                             # fixtures/fdroid_repo/ holds signed test indexes (make_fixtures.py rebuilds them)
├── install.sh                # 1-Click on-device installer script
├── run.sh                    # Smart runner for Steam and command-line execution
└── uninstall.sh              # 1-Click clean uninstaller
```

---

## 🧭 4a. Lepton & FrameBridge Ground Truth (read before touching installer or settings code)

Verified against Valve's Lepton source (`compat_tool/liblepton/*.sh`) and FramePort's `docs/FRAME_RUNTIME.md`. Do not add a setting unless one of these mechanisms carries it.

1. **Lepton ships with the Steam Frame.** Locate it (`lepton_status()`); never make installing it part of a normal flow.
2. **What `lepton start` reads:** `SteamAppId`, `STEAM_COMPAT_INSTALL_PATH` (folder with exactly one `*.apk` plus `obb/`), `STEAM_COMPAT_DATA_PATH`, `STEAM_COMPAT_SHADER_PATH`, `STEAM_COMPAT_LIBRARY_PATHS`, `LEPTON_ENV_<NAME>` (passed into the app as `<NAME>`), `FDM_DEBUG`, `FOVE_LEVEL`, `VK_INSTANCE_LAYERS`, `LEPTON_DUMP_LOGCAT` (undocumented: keep Android's logs in `<steamvr logs>/lepton-logcats/steamlaunch-<appid>/` after every session, not only one under 30 s; the dump is deleted at the next start and needs the container alive, so a killed game has none), and the marker file `lepton-show-flatscreen`.
3. **No per-game Android properties.** Lepton writes its own `lepton.prop` (`ro.product.model=Lepton`). Device spoofing, `local.prop`, `debug.oculus.*`, MSAA/AF and CPU/GPU levels cannot be set from a launcher. The only exception in use is the navigation-bar property injected through `LEPTON_GFXRECON_*`.
4. **Launching:** Lepton starts the first real `<activity>` with `MAIN` + `LAUNCHER`. `<activity-alias>` and the Quest store's `INFO` category are ignored ("APP_ACTIVITY is empty"). Lepton is 64-bit only and installs a single APK (no splits).
5. **FrameBridge** is FramePort's OpenXR adapter inside a ported APK (`libframe_settings.so`, `libopenxr_loader_original.so`). It reads `settings.conf` (via `LEPTON_ENV_FRAMEBRIDGE_CONFIG`) and `Android/data/<pkg>/files/framebridge.conf`. FrameLoad ships no native code; an APK without the adapter ignores those files.
6. **Hand tracking:** the Frame has no camera hand tracking. SteamVR's Android runtime exposes `XR_EXT_hand_tracking` synthesized from the controllers' finger sensors. FrameBridge `controller_fix=1` hides it and reports Touch controllers; `0` passes it through.
7. **Dashboard input** is the controller laser (pointer events) and the Gamepad API. A flat web page receives no hand joints.
8. **Porting is FramePort's job.** Converting a Meta-runtime game needs OVRPort (Java), FramePort's native adapter and apksigner. `installer/porting.py` calls FramePort's CLI (`tools install`, `scan <folder>`, `build <pkg> --outdir`, result line `<pkg>: OK -> <apk>`) with `FRAMEPORT_HOME` inside FrameLoad's folder. Do not reimplement the conversion here; `tests/fake_frameport.py` stands in for the CLI in tests. The tools are fetched automatically (`porting.background_maintenance()` 30 s after server start, `ensure_ready()` on demand), never bundled: bundling would add ~130 MB of binaries tied to the headset's Python version to every release and freeze FramePort's per-game fixes. On ARM64 UnityPy cannot be built (no compiler); `_install_without_optional` handles that.
10. **Steam reads shortcuts.vdf only at start** and writes its own copy back on exit. Never assume a freshly written shortcut is launchable through `steam://rungameid`; ask `steam_session.is_pending()` and start the launcher directly (with `FRAMELOAD_DETACHED=1`) when it is.
11. **Lepton data is owned by subordinate user ids.** Plain `shutil.rmtree`/`copytree`/`tarfile` can silently miss files; use `system/fsutil.py` (`podman unshare`). App-private saves live in `lepton-data/internal/<pkg>`, shared files in `lepton-data/external`.
12. **Only loopback is trusted.** Any other client must hold a paired session (`system/access.py`). New API routes inherit this from `do_GET`/`do_POST`; do not add routes that bypass `authorized()`.
13. **Some apps cannot be ported** because they check their own signing certificate (`SELF_SIGNATURE_CHECK_LIBS` in `apk_analysis.py`). Mark them blocked; never add code that defeats such a check.
14. **Always offer Stop.** Games FrameLoad launches directly are invisible to Steam's exit; `GameLauncher.stop()` kills the `lepton-steamlaunch-<appid>` container.
15. **Steam opens its Resume / Exit menu over a game's first frame, and FrameLoad's own window lives in the same dashboard layer**, so a VR game can run behind it and only be heard. `launch.sh` of a VR game starts `python3 -m frameload.system.steam_ui`, which waits for FrameBridge's first-frame lines (`new layer:` / `pacing:`) in `launch.log`; while there are none it also asks the container every 2 s (`podman exec lepton-steamlaunch-$SteamAppId logcat -d -v brief -s FrameBridge:I`, 5 s timeout, only for APKs that carry FrameBridge), because Lepton's copy of the log can die. Then it calls `SteamClient.OpenVR.VROverlay.HideDashboard()` in Steam's `SharedJSContext` (the approach is FramePort's). It must never close a dashboard the player opened (`toggle_dashboard_action` in `vrwebhelper_systemui.txt`); the position in that log is taken at the first frame, so presses during Lepton's boot do not count. Ten hides within 15 s is `keeps-reopening`. `dashboard.log` ends with exactly one `result: hidden N | no-frames | player | keeps-reopening | error <msg>` line, which `launchlog.session_findings()` explains (with `<base>/.last_launch`, written by `GameLauncher.launch`). With config `ui.close_on_vr_start` (off by default) it sends SIGTERM, at the first frame or on `keeps-reopening`, to the pid in `~/.local/share/frameload/window.pid`, which `run.sh` writes after taking `window.lock` and removes on exit; only a process whose cmdline is `run.sh` is signalled. The manual control is `POST /api/installed/show-game` (`GameLauncher.show` -> `steam_ui.show_game()`: `IsDashboardVisible()`, HideDashboard, then `IsDashboardVisible()` after 1 s and again 2 s later; `reason` unreachable / refused / still-open / no-answer / reopened), shown as Show next to Stop for a running VR game, never for a 2D app (HideDashboard would hide its window). Every press is appended to `<base>/show.log` (with `.last_launch`'s `via`), which the report carries. When Show fails, or is pressed again within 2 minutes of a success, the dashboard offers to close FrameLoad's window (`POST /api/window/close`, only when `steam_ui.window_pid()` finds run.sh). `steam_js` raises on `exceptionDetails`, so a changed Steam interface is not mistaken for "no answer"; `frameload doctor` checks the port. Any change to `LAUNCH_SCRIPT_TEMPLATE` needs `layout_version` raised in both `lepton_quest.py` and `migrate.py` (currently 12), or existing games keep the old launcher. Launchers of games FramePort installed (`installed_by` is not `frameload`) are left as they are.
16. **Dashboard UI rules.** It is used with a laser pointer in a headset: interactive targets are at least 40 px tall; no `confirm()` / `alert()` (use `confirmDialog()` in `app.js`); every scrollable view must work with the scroll arrows (`ScrollAssist` in `gamepad.js`) because not every controller reaches the page as a gamepad; long jobs report steps and a percentage (`JOB_STEPS` / `JOB_MARKERS` in `porting.py`), not raw console output. Long lists must stay cheap: the catalog renders one `.catalog-page` grid per loaded page with `content-visibility: auto`, and focus candidates are filtered with `checkVisibility({contentVisibilityAuto: true})`; reading `offsetParent` on every card lays out skipped content (12 s at 2,000 cards). Lists that poll (Downloads) update cards in place instead of rebuilding them.
17. **Drives are classified by bus, never by device name.** The Frame's UFS storage is `/dev/sd*` with many system partitions. `storage.classify_disk()` reads sysfs: `/usb` in the disk's device path = USB, `mmcblk*` with `device/type` SD = microSD card, `removable` = 1 = USB; everything else is internal and is not offered. Only the home drive, microSD and USB drives appear.
18. **One app window, owned by run.sh.** `run.sh` decides which browser is available first, then runs exactly one window as its child and waits; it never tries the next browser because a window exited non-zero (a closed Firefox does). Firefox runs with `--no-remote` and a profile inside its Flatpak folder (`~/.var/app/org.mozilla.firefox/frameload-profile`); `flatpak run --die-with-parent`; a lock file keeps a second window from opening.
19. **Steam artwork pipeline.** At install the APK's launcher icon is extracted (`artwork.extract_apk_icon`), downloaded pictures are kept, and missing slots get a plain placeholder; `artwork.json` records each slot's source. The dashboard (`composeArtwork` in app.js) draws placeholders on a canvas and POSTs them to `/api/installed/artwork/<pkg>`; the server writes them and calls `shortcuts.refresh_grid_artwork()`, which uses the appid stored in each user's shortcut. Never compute grid file names from the title. The icon slot is the APK's launcher icon whenever `artwork.apk_icon_kind()` is "full" (a cover is copied into it otherwise; an adaptive icon's foreground layer alone is drawn over the app's colours; old cover copies and WebP icons are redrawn, see `icon_redraw()`), and shortcuts point at `artwork.steam_icon()`, never at a hard-coded `icon.png`. `shortcuts.register_frameload()` (install.sh, its updates, and `steam_session.resync_shortcuts()` for Restart Steam Now / `frameload sync-shortcuts`) writes FrameLoad's own shortcut only for Steam users whose list lacks a working one, and never renames it or replaces its pictures. Moving a game moves its shortcut (`shortcuts.move_shortcut`), keeping its appid.
20. **Play history** is written by launch.sh (`.last_played` at start, a `start end` line in `.playtime` at exit; keep that line at exactly two fields, `play_stats()` skips others). `installed.play_stats()` reads it; games from before layout 6 fall back to their launch.log's time. Since layout 7 the EXIT trap also writes `.session_end` (`start end exit-status`; `local rc=$?` must stay the trap's first statement, the next command overwrites `$?`), and `fail()` writes `.launch_error` when Lepton or the game's files are missing. Lepton exits 0 after a quit, a crash and a killed container alike: only 130/143 (a signal) and early errors are told apart by the status.
21. **Freeze guard.** Running games are found through `/proc/locks` (the flock launch.sh holds on `.launch.lock`); reading it takes no lock, so it can never make a launch think its game is already starting. Do not probe that lock with flock. Three independent switches (`guard.enabled` = memory watchdog, `memory_limit`, `stop_frozen`), all on by default: memory is limited with `podman update --memory` (RAM minus 2.5 GB) a few seconds into a session; the watchdog stops games on PSI `full avg10` >= 20 % for 3 samples or < 3 % RAM available with swap full; a VR game whose picture froze for `frozen_seconds` (15/30/60/120, default 30, `snap_frozen_seconds()`) is stopped, or only reported with `stop_frozen` off. Frames are FrameBridge's `pacing:` lines (every 5 s, `%.1f fps`) and `focus: lost / back after / session ending` lines; launch.log is read at most 1 MiB per tick, from its end when more is waiting. Ages use `time.monotonic()`, and a gap of more than 10 s between ticks (suspend) restarts every game's wait. Only at the limit does the guard look further: the headset in standby (vrserver.txt `[CCVTrackedHmdDriver] in State...`), a background game (up to `FOCUS_WAIT_MAX` 120 s: a frozen game never logs "back"), the Steam menu open (`steam_ui.dashboard_visible()`, read-only) all wait, and standby or the menu restart the full wait once they end. A game whose own GPU time (`perf.app_pids/render_fds/gpu_time_ns`, DRM fdinfo `drm-engine-gpu`) is >= 5 % over the limit keeps running (one "info" event); unreadable GPU time is no veto. VR games without FrameBridge are judged by GPU time alone (drawing after 3 ticks >= 5 %, frozen after < 1 % for the limit) and only stopped when the headset is known awake and the Steam menu known closed. 2D apps are never judged. `stop()`'s result decides the message. Settings version 2 (`SETTINGS_VERSION`) drops the `stop_frozen`/`frozen_seconds` saved by v1.3.5-1.3.7 once. Every tick also hands ended sessions to `sessions.finalize` (in a thread, whatever the switches say) and every 30 s runs `sessions.sweep`.
22. **Looks (skins).** The dashboard has six looks: a Big Picture (default), b Spatial, c Showcase, d Neon, e Command Center, f Daylight (light/dark via `data-mode`). The saved look lives in config `ui.skin` / `ui.daylight`; `server.serve_index()` writes it into `<html data-skin data-mode>` and the skin stylesheet link, `?skin=x` previews one without saving. style.css is the neon base and defines every colour, font and radius as a token (`--bg`, `--surface`, `--text`, `--accent`, `--accent-rgb`, `--fg-rgb` …); never write a literal colour into style.css, index.html or app.js markup, use a token (canvas code is the exception: canvas cannot read CSS variables). A look owns `static/css/skins/<id>.css` and `static/js/skins/<id>.js`; the view API (`registerSkin(id, {library, empty, noMatch, status, mount, unmount})` and the `ctx` it gets) is in app.js under "Looks". Shared markup changes must be checked in all six looks (and both Daylight modes); the dev tools under `scripts/` do not cover this yet, so screenshot each look.
23. **Uninstalling.** Every way to remove FrameLoad ends in `Uninstaller.uninstall_frameload_app` (uninstall.sh calls it from a temp copy of the package, by function, so it also works with older installs). The dashboard runs it inside `frameload.service`, and stopping that service kills the process: it passes `stop_service_last=True` (disable first, stop last). FrameLoad's own Steam shortcut is found with `shortcuts.is_frameload_itself()`, never by a substring: games live in `quest-frame` folders that may sit on a drive named FrameLoad. The signing keys of ported games are copied to `~/Documents/FrameLoad-signing-keys` before any data is deleted, and kept in place when that copy fails. These rules hold for the uninstaller of v1.3.7 and later; with an older install, uninstall.sh only fixes the shortcut matching.
24. **Shell scripts are LF.** `.gitattributes` forces `*.sh` to LF (this repo is also edited on Windows with autocrlf); the release tarball packs the working tree, so a CRLF `run.sh` would break on the headset.
25. **What happened (sessions.py).** A session's record (`DATA_DIR/sessions/<pkg>.json`) is made when the guard sees a game's lock go away, by `sweep`, and at server start by `catch_up` (which also records `interrupted`: started, never ended, system booted since; the very first look records everything as seen). It copies the evidence the next start erases (launch.log cut to 4 MB, Lepton's logcat dump, kernel GPU/OOM lines) and classifies in this order: interrupted, a stop marker (`mark_stop(pkg, "player"|"guard"|"frameload")`, written by `GameLauncher.stop/stop_all`, the guard and moves; a player marker never replaces a guard marker under 15 s old), exit 130/143 or "Signal SIGTERM received" (Steam's Exit), could-not-start, out of memory, GPU hang, crash (process-filtered by "Start proc <pid>:<pkg>" and FrameBridge pids, a crash within 10 s after a quit request is a normal end), closed within 60 s without a picture, quit. Popup outcomes come back through `/api/system` `session_alerts` until `/api/sessions/seen`; the dashboard opens `#session-modal` only when no other dialog is open and no game runs. Copy Log uses `navigator.clipboard` in a secure context, else a selection of a hidden `div.copy-buffer` and `execCommand("copy")` inside the click: never a text field (the Steam keyboard opens on focus). `report_text` redacts home, host, LAN addresses, MAC and SteamID64 and stays under 60,000 characters; `/api/sessions/save` writes the full one to `~/Downloads` and is headset-only. The record also keeps `dashboard.log`, `.last_launch` and SteamVR's `xrclient*<pkg>*.txt` of the session (the report's "Starting the game" section, with show.log presses of that session).
27. **Send to GitHub (github_reports.py).** FrameLoad ships no token and never may: the user pastes their own fine-grained token (Issues: read and write) under System; it lives in `DATA_DIR/github_token` (0600), never in config.json (GET `/api/config` returns the config), is never returned by an API (only its last 4 characters) and only goes to `https://api.github.com`. Paired devices may set it (pasting on a PC is the point). The issue body is `report_text` (already redacted; the player's note is redacted too) in a fence longer than any backtick run, cut to 65,000 characters. One issue per `signature()` (package, version code, outcome, signal, library, else the first error finding; never a cause text, which names seconds): the local map `github_reports.json`, else open issues carrying `frameload-signature: <sig>`, get a comment; a closed one gets a new issue naming it; one session (`pkg:end`) is sent once. A label GitHub refuses (422) is dropped, not the report. Tests replace `_urlopen` with a fake GitHub; never call the real API from tests.
26. **2D app sources.** Every source is an F-Droid repository. Only `index-v1.jar` is read (`repo_index.read_index_v1`; a v2 reader would sit beside it), and only after `verify_index_jar` has checked its JAR signature against the source's key: pinned in `app_sources.BUILTIN_SOURCES`, or stored in config `app_sources.custom` when a repository is added (the user's fingerprint, or the one the check saw). Never parse an unverified index, and keep the declared-size caps, the `repo.timestamp` rollback check and, for added repositories, https only and public addresses only (`check_public_host` when added and `_public_create_connection` on every connection, redirects and APK downloads included: 127.0.0.1:8080 is Steam's CEF debugger; the server fetches no pictures from them). Sync is manual and one source at a time (`_SYNC_LOCK`; F-Droid's index takes about 250 MB while it is parsed); there is no background sync, and one added later must skip while the freeze guard sees a running game. `deployment.json` `origin` says where an app came from (`app_origin()`; `{"source": "file"}` for files and `{"source": "link"}` for install links; older 2D installs without one count as F-Droid). Updates come only from the origin source and only when the listed `signer` matches or is unknown; switching sources needs the same key (`switch_refusal`). `install_quest_game(expected_package=…)` refuses an APK whose package differs from the catalog's before anything is copied, and the downloader refuses a second task for a package that has one running. F-Droid entry ids stay md5(package); other sources use md5(`<source>/<package>`). Adding, removing and hiding sources is allowed only at the headset (`handle_app_sources`, like pairing codes).
28. **Mirror releases keep the OBB folder beside the APK.** An archive extracts to `DATA_DIR/<release>/<release>/<package>.apk` plus `<package>/` (main/patch/overflow `.obb`, `Audio_<lang>.obb`, or plain data such as `files/`): that whole folder is `Android/obb/<package>`. `find_release_obb()` finds it (also `Android/obb/<package>`, `obb/` and loose `main.<v>.<package>.obb`); never only look for `Android/obb` or `obb` under the root, which lost every catalog game's data up to v1.4.0. Layout 8 (`migrate.restore_release_obb`) moves a left-behind folder of the installed version in when `lepton-app/obb/` is empty. After a successful install the extracted release is deleted (`delete_cache_after_install`). The Freeze Guard's memory limit falls back to writing the container's cgroup v2 `memory.max` when `podman update` refuses (podman 5.0: "healthcheck-timeout must be at least 1 second").
29. **Foveation and GPU hangs; Steam shortcut ids.** Valve's gaze foveation layer (`VK_LAYER_VALVE_fdm_injection`) makes the Adreno GPU fault in some games (Red Matter 2, Epic Roller Coasters: `gpu fault ring 2` / `hangcheck recover`, then SIGSEGV in `vulkan.freedreno.so`); with tuning `foveation: off` (`VK_INSTANCE_LAYERS=""`) they run. `sessions._foveation_off_after_hang` sets `off` after a `gpu_hang` session of a VR game FrameLoad installed (record `auto_fix`). `GameLauncher.launch` names the shortcut's own appid from the active user's `shortcuts.vdf` (`shortcuts.steam_shortcut_appid`; 0 = gone, None = cannot tell) in `steam://rungameid`, never deployment.json's alone; a gone shortcut is started directly and registered again. launch.sh exports its own `SteamAppId`, so container names follow deployment.json either way. Lepton's Android lacks some system services (NsdManager, clipboard): apps that require them stop at start and cannot be fixed from FrameLoad.
30. **Release install.txt and stop logs.** `installer/release_script.py` carries out a Rookie-style install.txt after a download (and layout 9 for a release left in DATA_DIR): `_bin.7z`/`_bin.zip` is unpacked when the script pushes files, `adb push`/`adb shell mkdir` under `/sdcard` map to `<base>/lepton-data/external` (`/sdcard/Android/obb/<pkg>` to `lepton-app/obb`), paths may not leave the release or the storage, APK installs are skipped, and only `appops set --uid <own pkg> OP mode` / `pm grant <own pkg> android.permission.X` reach `container_setup.txt`, which launch.sh runs in the container once `pm path` answers (output in `container_setup.log`, kept with the session). Lepton's Android has no `appops` service, so `MANAGE_EXTERNAL_STORAGE` cannot be set. A left-behind release counts for a game only when it holds `<package>.apk`, a `<package>` folder or names the package in `release.manifest` (`migrate.release_belongs_to`): version codes collide (many games are version 1). `GameLauncher.stop`/`stop_all` copy the container's logcat to `<base>/.stop_logcat.log` before killing it; Lepton's own dump fails once the container is gone. Presets in `tuning.PRESETS` set only their own keys and never `foveation`.
31. **Compatibility list (website/ and compat_reports.py).** The site at https://frameload.crypto90.de is `website/` (PHP 8.1+, SQLite, no framework, no third-party requests: it is hosted in Germany, so no Google Fonts or CDNs). `public/` is the document root; `app/`, `data/` and `config.php` stay outside it. `app/status.php` `rate_report` and `compat_reports.rating` must stay the same rule. Looks draw a game's verdict from `ctx.community(game)` (`{status, label, note}` or null for unlisted/untested), each in its own style, after the flags that matter more (cannot run, needs porting, update). FrameLoad's `compat.show` (default on) fetches the whole list (`/api/v1/compat.php`, never `?packages=`, so the site never learns what is installed) at most every 6 h into `DATA_DIR/compat_list.json` and `annotate()`s `/api/installed` with `community`; `compat.share` (default off, the player's opt-in) POSTs one report per finished, non-quiet, non-interrupted session from `sessions._store`. Never send names, paths, logs or Steam ids; the install id is a random uuid4 in config. A report carries `icon` (base64 of `artwork.steam_icon()`, only when `artwork.json` says `composed` or `downloaded`, never `generated`, at most 256 KB) while the cached list has no `icon` for the game. The site (`app/icons.php`) keeps the first icon of a listed game in `data/icons/`, re-encoded with GD to 128 × 128 PNG, served by `public/icon.php`, and refuses an engine's default launcher icon (`DEFAULT_ICONS`, 8 × 8 average hashes within 8 bits: Unity's white cube, which TriptoVR, QuestCraft and SKYBOX carry); `POST /api/v1/icon.php` takes one on its own. Tests replace `_urlopen`; never call the real site from tests. The team's tests are `CURATED` in `website/app/seed.php`.
9. **Camera hand tracking does not exist on the Frame yet.** It needs a tracker inside SteamVR; nothing in this repo can provide it. Do not add UI or files that claim otherwise.

---

## 🥽 4. SteamOS & Steam Frame Gotchas & Specifics

1. **Systemd User Scope Bus (`failed to connect to user scope bus`):**
   - On Linux / SteamOS, running `systemctl --user` without a graphical session or inside a subshell/pipe often lacks `XDG_RUNTIME_DIR`.
   - **Fix:** Always ensure `XDG_RUNTIME_DIR="/run/user/$(id -u)"` and `DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"` are exported before interacting with `systemctl --user`.
   - **Autostart Fallback:** In `install.sh`, if `systemctl --user` fails to connect, configure `~/.config/autostart/frameload.desktop` and start the daemon directly using `run.sh --daemon`.
2. **Never Run as Root / Sudo:**
   - Running `sudo bash install.sh` misplaces files into `/root`, breaks Steam user paths, and fails to connect to systemd user scope.
   - `install.sh` automatically detects `SUDO_USER` and drops privileges back to the actual user.
3. **Steam Directory Multi-Path Discovery:**
   - SteamOS and Linux distros store Steam data in different locations:
     - `~/.steam/steam/userdata` (standard SteamOS)
     - `~/.local/share/Steam/userdata` (standard Ubuntu/Debian)
     - `~/.steam/root/userdata`
     - `~/.var/app/com.valvesoftware.Steam/...` (Flatpak Steam)
   - Use `get_steam_dir()` in `frameload/config.py` and `get_steam_users()` in `frameload/system/shortcuts.py` which dynamically check all candidates.
4. **Steam Shortcut Locking:**
   - Steam keeps `shortcuts.vdf` in memory while running. If shortcuts are written while Steam is open, Steam might overwrite them on exit. Always prompt the user to restart Steam or switch to Gaming Mode to see newly added shortcuts.
5. **Steam Window Tracking (`run.sh`):**
   - SteamOS Gaming Mode (gamescope) requires a graphical window to attach to a game's PID.
   - `run.sh` ensures the background server is alive, then launches a dedicated application window using Chrome/Chromium (`--app=http://127.0.0.1:5050`) or Firefox, and keeps running to preserve session tracking.
6. **Lepton Podman Keyring Leak:**
   - Rootless podman on SteamOS leaks a kernel keyring per container start unless configured.
   - `install.sh` automatically appends `keyring = false` in `~/.config/containers/containers.conf`.
7. **Standalone 7-Zip (`7za`):**
   - Standalone static `7za` binary is auto-installed to `~/.local/share/frameload/bin/7za` for high-performance extraction of APKS, XAPK, and ZIP archives.
8. **Beat Saber Custom Songs Path:**
   - Custom songs must be stored in:  
     `~/Applications/quest-frame/com.beatgames.beatsaber/lepton-data/external/Android/data/com.beatgames.beatsaber/files/CustomSongs/`
   - Permissions must be unlocked (`chmod -R 777`) so the Lepton Android sandbox user can read the songs.

---

## 🔄 5. In-Headset Self-Update Mechanism

FrameLoad self-updates directly inside the headset without a PC:

1. **Detection:** Checks GitHub Releases API (`/repos/Crypto90/frameload/releases/latest`) and local git remote (`git fetch origin main`).
2. **Notification Touchpoints:**
   - Header chip (`Update vX.Y.Z`).
   - Top dismissable banner on main dashboard.
   - System tab, FrameLoad Updates card badge.
3. **Execution Flow:**
   - **Git install:** Runs `git pull --ff-only origin main`. Never stash: when it fails, return `success: False` with git's output (local changes that block it are named from `git status --porcelain`) and skip install.sh and the restart.
   - **Tarball install:** Downloads `frameload-vX.Y.Z-standalone.tar.gz` and extracts to application root.
   - Runs `install.sh --no-restart` to refresh shortcuts, systemd units, and container configs without killing the active HTTP process.
   - Returns HTTP 200 JSON to the frontend.
   - Triggers `sleep 2 && systemctl --user restart frameload.service` in the background for zero-downtime service reload.
   - Frontend automatically reloads after 3.5 seconds.

---

## 🎨 6. Steam Grid Artwork Specs

Official Steam artwork formats are generated and stored in `frameload/web/static/assets/` and `docs/images/steam/`:
- **Vertical Poster / Capsule:** `600x900` (`capsule_device.png`, `poster.png`)
- **Grid Banner:** `920x430` / `460x215` (`banner.png`)
- **Hero Background:** `1920x620` (`hero_device.png`, `hero.png`)
- **App Icon:** `512x512` (`icon_device.png`, `icon.png`)
- **Logo Overlay:** Transparent PNG (`logo.png`)

---

## 🧪 7. Testing Requirements

- **Test Suite Command:** `python3 -m unittest discover tests`
- **Rule:** Before committing changes or building releases, all unit tests must pass with 0 failures or errors.
- Never use packages outside Python standard library in core backend code (Pillow is permitted for image generation/testing).

---

## ☕ 8. Developer Support

- **Ko-fi Page:** [https://ko-fi.com/K3K314GUP](https://ko-fi.com/K3K314GUP)
- Included as an interactive support chip in the top header, in the System tab, and in the README header.
