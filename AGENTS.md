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
│   ├── catalog/              # Mirror parser, download queue, multi-threaded downloader
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
│   │   ├── installed.py      # Installed titles catalog
│   │   ├── tuning.py         # Per-game settings schema -> launch env + FrameBridge conf keys
│   │   ├── migrate.py        # One-time upgrade of installs made by older versions (layout_version)
│   │   ├── files.py          # File browser roots and uploads from paired devices
│   │   ├── launchlog.py      # Reads launch.log and names known failures
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
│   │   └── steamos.py        # Hardware telemetry (battery, storage, Lepton container, Proton status)
│   ├── web/                  # Web Dashboard UI & REST API
│   │   ├── static/           # CSS (style.css), JS (app.js, gamepad.js), and Steam artwork assets
│   │   └── templates/        # HTML (index.html)
│   ├── cli.py                # Command-line interface and deep-link dispatcher
│   ├── config.py             # Global paths (HOME, STEAM_DIR, ANCHOR_DIR, FRAMELOAD_DIR)
│   └── server.py             # ThreadingHTTPServer and REST API endpoints
├── scripts/
│   ├── build_release.py      # Builds tarballs, self-extracting installer, SHA256SUMS, and release notes
│   ├── capture_screenshots.py# Headless Chrome script for automated 1080p README screenshots
│   └── github_release.py     # Pure Python GitHub REST API release publisher and asset uploader
├── tests/                    # Unit tests (140+ cases); axml_builder.py builds test APKs, fake_frameport.py stands in for FramePort
├── install.sh                # 1-Click on-device installer script
├── run.sh                    # Smart runner for Steam and command-line execution
└── uninstall.sh              # 1-Click clean uninstaller
```

---

## 🧭 4a. Lepton & FrameBridge Ground Truth (read before touching installer or settings code)

Verified against Valve's Lepton source (`compat_tool/liblepton/*.sh`) and FramePort's `docs/FRAME_RUNTIME.md`. Do not add a setting unless one of these mechanisms carries it.

1. **Lepton ships with the Steam Frame.** Locate it (`lepton_status()`); never make installing it part of a normal flow.
2. **What `lepton start` reads:** `SteamAppId`, `STEAM_COMPAT_INSTALL_PATH` (folder with exactly one `*.apk` plus `obb/`), `STEAM_COMPAT_DATA_PATH`, `STEAM_COMPAT_SHADER_PATH`, `STEAM_COMPAT_LIBRARY_PATHS`, `LEPTON_ENV_<NAME>` (passed into the app as `<NAME>`), `FDM_DEBUG`, `FOVE_LEVEL`, `VK_INSTANCE_LAYERS`, and the marker file `lepton-show-flatscreen`.
3. **No per-game Android properties.** Lepton writes its own `lepton.prop` (`ro.product.model=Lepton`). Device spoofing, `local.prop`, `debug.oculus.*`, MSAA/AF and CPU/GPU levels cannot be set from a launcher. The only exception in use is the navigation-bar property injected through `LEPTON_GFXRECON_*`.
4. **Launching:** Lepton starts the first real `<activity>` with `MAIN` + `LAUNCHER`. `<activity-alias>` and the Quest store's `INFO` category are ignored ("APP_ACTIVITY is empty"). Lepton is 64-bit only and installs a single APK (no splits).
5. **FrameBridge** is FramePort's OpenXR adapter inside a ported APK (`libframe_settings.so`, `libopenxr_loader_original.so`). It reads `settings.conf` (via `LEPTON_ENV_FRAMEBRIDGE_CONFIG`) and `Android/data/<pkg>/files/framebridge.conf`. FrameLoad ships no native code; an APK without the adapter ignores those files.
6. **Hand tracking:** the Frame has no camera hand tracking. SteamVR's Android runtime exposes `XR_EXT_hand_tracking` synthesized from the controllers' finger sensors. FrameBridge `controller_fix=1` hides it and reports Touch controllers; `0` passes it through.
7. **Dashboard input** is the controller laser (pointer events) and the Gamepad API. A flat web page receives no hand joints.
8. **Porting is FramePort's job.** Converting a Meta-runtime game needs OVRPort (Java), FramePort's native adapter and apksigner. `installer/porting.py` calls FramePort's CLI (`tools install`, `scan <folder>`, `build <pkg> --outdir`, result line `<pkg>: OK -> <apk>`) with `FRAMEPORT_HOME` inside FrameLoad's folder. Do not reimplement the conversion here; `tests/fake_frameport.py` stands in for the CLI in tests.
10. **Steam reads shortcuts.vdf only at start** and writes its own copy back on exit. Never assume a freshly written shortcut is launchable through `steam://rungameid`; ask `steam_session.is_pending()` and start the launcher directly (with `FRAMELOAD_DETACHED=1`) when it is.
11. **Lepton data is owned by subordinate user ids.** Plain `shutil.rmtree`/`copytree`/`tarfile` can silently miss files; use `system/fsutil.py` (`podman unshare`). App-private saves live in `lepton-data/internal/<pkg>`, shared files in `lepton-data/external`.
12. **Only loopback is trusted.** Any other client must hold a paired session (`system/access.py`). New API routes inherit this from `do_GET`/`do_POST`; do not add routes that bypass `authorized()`.
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
   - Header animated chip (`⚡ Update: vX.Y.Z`).
   - Top dismissable banner on main dashboard.
   - System & Diagnostics tab badge.
3. **Execution Flow:**
   - **Git install:** Runs `git pull --ff-only origin main` (falls back to `git stash` if local files are modified).
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
- Included as an interactive support chip in the top header, in the System & Diagnostics tab, and in the README header.
