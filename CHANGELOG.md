# Changelog

All notable changes to **FrameLoad** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) using 0.0.1 increments.

---

## [v1.3.2] - 2026-10-08

### Added
- **Real APK inspection:** A binary `AndroidManifest.xml` / `resources.arsc` reader replaces the byte-pattern guess, so package name, version, app label, launcher activity, VR and hand-tracking declarations are read correctly.
- **Steam Frame compatibility verdict:** Every APK is classed as ready, should run, needs porting first, or cannot run, with the reasons shown in the Sideload preview, the library and the settings dialog.
- **Hand input setting:** Automatic / Controllers / Hands per game, mapped to FrameBridge's `controller_fix`. Games that require hand tracking get hands automatically.
- **F-Droid store:** Categories, summaries and descriptions, version names, installed and update markers, and SHA-256 verification of every download before install.
- **Gamepad control of dropdowns and sliders** in dialogs.
- **On-headset porting of Quest games (experimental):** "Port for Steam Frame" runs FramePort's command line on the headset (OVRPort conversion, FrameBridge adapter, signing) and replaces the game's APK, keeping saves, OBB files and settings. Once set up, a sideloaded game that needs porting is ported automatically after install (switchable); games installed earlier are ported when setup finishes. One-time setup under System & Diagnostics; `frameload port` on the command line.
- **Self-test:** `frameload doctor` and a System & Diagnostics card check Lepton, podman, launcher tools, the Steam library, installed games and the porting setup.
- **Automatic migration of older installs:** on start, games installed by earlier versions get the current launcher, their OBB files moved to where Lepton reads them, and unused files removed. Running games and games installed by FramePort are left alone.
- **`frameload allow-host <name>`** to open the dashboard under an extra host name, with an on-page notice when an address is refused.
- **LICENSE** file (GPL-3.0), matching what the README has always stated.
- **Upload from a phone or PC, and a file browser:** send an APK (with its OBB files) from another device straight to the headset, or pick files in the headset from Home, Downloads and removable drives.
- **Device pairing:** another device on the network is let in once with a six-digit code shown on the headset; paired devices are listed and can be removed.
- **Steam library state:** FrameLoad shows which new games Steam has not loaded yet, starts those itself, and offers a safe Steam restart that rewrites the shortcuts while Steam is stopped.
- **Launch log with diagnosis** for every Android app.
- **F-Droid updates:** "Update N Apps" for installed apps with a newer version in the catalog.
- **Install links ask first:** `frameload://install` and `frameload://sideload` now wait for confirmation in the dashboard.

### Changed
- **Per-game settings rebuilt** on what Lepton and FrameBridge read: foveated rendering, typing window, navigation bar, resolution scale, refresh rate, vibration strength, space warp, play space. The dialog is generated from the server's schema.
- **Launcher (`launch.sh`)** now carries only variables Lepton honours, refuses a second concurrent launch, ends the game when Steam's launcher process is gone, and finds Lepton at start time.
- **OBB files** are placed directly in `lepton-app/obb/`, where Lepton links them from.
- **2D detection:** an unticked "2D window" box means "decide from the APK" instead of forcing VR.
- **Lepton** is treated as part of the Steam Frame; the dashboard no longer prompts to install it.
- **Save backups** now include the app's private storage (`lepton-data/internal`), where most games save, and are made and restored inside podman's user namespace so files owned by the container are included.
- **Self-update** verifies the package against the release's `SHA256SUMS`, refuses unsafe archive entries, checks GitHub every six hours instead of every minute, and restarts FrameLoad even when it does not run as a systemd service.
- **Releases** are published from version tags only, not from every push to `main`.
- **Steam artwork:** real PNG/JPEG files for every slot (the app's icon for F-Droid apps, a generated image otherwise) instead of one cover copied five times or an SVG Steam does not show.
- **Storage:** FAT/exFAT/NTFS drives are refused for games, a missing drive is an error instead of a silent install to internal storage, and a move verifies the copy and never overwrites the destination.
- **Windows and Linux launchers** use the Frame's OpenXR runtime file when present and set `SteamGameId`; both are marked experimental.

### Removed
- **Controls that had no effect:** Quest hardware spoofing, MSAA, anisotropic filtering, CPU/GPU levels, controller model choice, 2D window size presets, and the `local.prop`, `lepton-window.json`, `hand_tracking.json` and `framebridge_hands.conf` files. Lepton reads none of them. Stored values from older versions are discarded.
- **"Synthetic" and "optical" hand tracking modes and the dashboard's WebXR hand engine / input switcher.** They were never connected to an XR session, and the Frame has no camera hand tracking.
- **APK "shim injection":** no shim binaries were ever shipped, so APKs were copied unchanged. Use FramePort to port a Quest game.

### Fixed
- **Security:** any device on the same network could control FrameLoad without a login; other devices now need pairing.
- **Security:** the unauthenticated API answered any website (`Access-Control-Allow-Origin: *`); another site open in a browser could install, uninstall or reconfigure. Requests are now accepted only from the dashboard's own origin, with DNS-rebinding and path-traversal checks on hosts and package names.
- **Cross-site scripting:** catalog names and titles are escaped before they are inserted into the page.
- **Installed Library crash** after the update check returned, and an **endless request loop** for a missing fallback image in the Storage tab.
- **F-Droid:** wrong icon URLs, the newest release offered instead of the suggested one, 32-bit-only apps listed, the catalog re-read from disk on every HTTP request, and completed downloads left in the cache.
- **Settings dialog** stopped filling in after a JavaScript error (`msaVal`).
- **Config defaults** were shared and mutated between instances.
- **Uninstalling a game** could leave files owned by Lepton's container behind and still report success.
- **Uninstalling FrameLoad** deleted the signing keys of ported games; they are now saved to `~/Documents/FrameLoad-signing-keys` and restored by the next porting setup.
- **`frameload://install` links** ignored their address and never reached the running server.
- **Cover lookups** retried three slow addresses on every page load for apps without artwork.
- **Clearing the download cache** could delete a download or port in progress.
- **Moving a game to another drive** replaced Windows and Linux launchers with an Android one and dropped a game's settings.
- **Mod injection and deletion** accepted names and target folders that pointed outside the game's data folder.
- **`run.sh`** passed only some commands through to the command line; `install.sh` now also installs a `frameload` command in `~/.local/bin`.
- **Uninstalling FrameLoad with "delete games"** never cleaned games on a microSD card (it called a function that does not exist).
- **Self-test notice:** the dashboard runs the self-test by itself and shows a notice only when something is wrong.

---

## [v1.3.1] - 2026-10-08

### Added
- **Dynamic Release Notes Engine:** `scripts/build_release.py` and `scripts/github_release.py` now parse `CHANGELOG.md` dynamically per release tag, ensuring every release displays its authentic, version-specific features and fixes.
- **Git Commit History Fallback:** Automatic dynamic extraction from git logs if a release tag does not yet have an entry in `CHANGELOG.md`.
- **Repository-Wide `CHANGELOG.md`:** Comprehensive version history tracking from v1.0.0 through v1.3.1 following the Keep a Changelog standard.
- **Automated Changelog Testing:** Added unit tests in `tests/test_release_notes.py` validating changelog parsing and dynamic release notes generation.

### Fixed
- **Static Release Highlights Bug:** Resolved issue where GitHub release notes repeatedly outputted static boilerplate highlights from v1.0.1 across subsequent releases.

---

## [v1.3.0] - 2026-10-08

### Added
- **Steam Frame Virtual Keyboard Auto-Trigger:** Automatically triggers the SteamOS On-Screen Keyboard (`steam://open/keyboard` and `qdbus` virtualkeyboard) when focusing input/search fields inside VR and Desktop mode.
- **Header Virtual Keyboard Quick Button:** Added quick `⌨️` button in top navigation bar for 1-click manual keyboard activation.
- **`/api/system/keyboard` REST Endpoint:** Dedicated API endpoint to trigger or dismiss the SteamOS on-screen keyboard programmatically.
- **Multi-Word Search Tokenizer:** Token-based fuzzy search across VR and F-Droid catalogs, enabling multi-word queries (e.g. "beat saber", "half life") regardless of word order.
- **Resilient Download Auto-Retry with Backoff:** Network glitches, mirror rate limits, or transient connection drops are automatically retried up to 3 times with exponential backoff before failing.
- **Proton Discovery Expansion:** Added standard SteamOS Proton installation paths (`/usr/share/steam/compatibilitytools.d/`, `~/.steam/root/compatibilitytools.d/`, and Proton-GE custom runtimes).

### Fixed
- **Quest Save Backup Permissions:** Safe recursive permission handling when creating or restoring Quest game saves under rootless container environments.
- **Input Blur Handling:** Keyboard blur events cleanly disconnect to prevent infinite OSK trigger loops.

---

## [v1.2.9] - 2026-10-08

### Added
- **Progressive Fuzzy Catalog Infinite Loading:** Replaced pagination next/previous buttons with smooth, progressive infinite scrolling (36 items per batch) with fuzzy keyword filtering.
- **Live Extraction Progress Tracking:** Real-time percentage indicator and status stream during 7-Zip (`7za`) extraction and package deployment.
- **Interactive Download Pause & Resume:** Full support for pausing, resuming, and cancelling active downloads from both the download queue and bottom HUD bar.

### Fixed
- **Installed Library Fault Recovery:** Solved "Failed to load installed library" error caused by corrupt deployment JSON or missing manifest files with graceful fallback.
- **Update Check Resilience:** Auto-recovers update checker when catalog or library state is partially initialized.

---

## [v1.2.8] - 2026-10-08

### Added
- **VR Input Mode Switcher:** Dedicated VR input selector with 3 configurable modes:
  - `auto`: Automatically falls back to optical hand tracking whenever controllers are turned off or set down.
  - `controllers`: Locks input to Steam Frame Knuckles / physical controllers.
  - `hands`: Locks input to optical hand tracking.
- **VR HUD Input Badge:** Bottom HUD displays active controller status (`🎮 Controllers` vs `✋ Hands`).
- **WebXR Input Mode Listeners:** Automatically reacts to controller connect and disconnect events.

---

## [v1.2.7] - 2026-10-08

### Added
- **1:1 Square Game Card Artwork:** Render all game covers as authentic 1:1 squares with smooth image containment, matching modern VR catalog artwork standards.
- **Enhanced Cover Placeholders:** Clean typographic SVG fallback covers when cover artwork is loading or unavailable.

---

## [v1.2.6] - 2026-10-08

### Added
- **Advanced Catalog Sorting:** Sort games by "Most Downloads", "Least Downloads", "Highest Rating", and "Alphabetical (A-Z)".
- **Sort Selector in Catalog Bar:** Direct UI dropdown for instant re-ordering of thousands of titles.

---

## [v1.2.5] - 2026-10-08

### Fixed
- **Game Card Drag-to-Scroll:** Fixed mouse and VR laser drag scrolling being blocked when initiating a drag on top of game cards.
- **Analog Stick & Thumbstick Scrolling:** Enabled smooth analog stick/joystick scrolling (up/down and left/right) on VR gamepads and Knuckles controllers.
- **Mirror Source Resolution:** Resolved "NetworkError when attempting to fetch sources" by improving mirror failover and request spoofing.

---

## [v1.2.4] - 2026-10-08

### Fixed
- **Steam Frame Firefox Flatpak Sandbox Profile Error:** Fixed "Your Firefox profile cannot be loaded. It may be missing or inaccessible" by launching with dedicated profile paths and environment configurations.

---

## [v1.2.3] - 2026-10-08

### Added
- **26-Joint Meta Quest Skeletal Hand Tracking Bridge:** Full skeletal hand mapping for Valve Roy capacitive sensors and optical camera tracking.
- **WebXR Pinch Navigation:** Pinch-to-click gesture recognition and spatial raycasting.

---

## [v1.2.2] - 2026-10-08

### Added
- **Steam Frame VR Optimizer & Hardware Spoofing Engine:** Hardware ID spoofing (Quest 2/Quest 3/Quest Pro) for Lepton Android runtime compatibility.
- **Dynamic Foveated Rendering (DFR) & Supersampling Controls:** In-headset resolution scaling and refresh rate configuration (72/80/90/120Hz).

---

## [v1.2.1] - 2026-10-08

### Added
- **Chromeless Kiosk Window Runner:** Dedicated SteamOS Gaming Mode (gamescope) runner with session tracking and window PID attachment.

---

## [v1.2.0] - 2026-10-08

### Added
- **Laser-Aim Targeted Scrolling:** Precision VR laser pointer tracking with contextual spatial scrolling.

---

## [v1.1.9] - 2026-10-08

### Added
- **vrSrc Cloudflare Bypass:** Request header spoofing to prevent Cloudflare 403 blocks on mirror downloads.
- **VR Laser Momentum Drag:** Smooth velocity-based momentum scrolling for VR pointers.

---

## [v1.1.8] - 2026-10-08

### Added
- **Mirror Diagnostics Endpoint:** Integrated `/api/mirror/test` endpoint to diagnose connection latency, HTTP mirror headers, and reachability.

---

## [v1.1.7] - 2026-10-08

### Fixed
- **Cloudflare 403 Block Mitigation:** Normalized rclone User-Agent and headers to prevent automated Cloudflare anti-bot blocks on mirror sync.

---

## [v1.1.6] - 2026-10-08

### Fixed
- **Pure Python Downloader Headers:** Added custom browser User-Agent headers to the Python streaming downloader for HTTP mirror compatibility.

---

## [v1.1.5] - 2026-10-08

### Changed
- **Mirror Download Headers:** Configured spoofed User-Agent headers for background rclone jobs.

---

## [v1.1.4] - 2026-10-08

### Added
- **VR & 2D Catalog Selector:** Dedicated UI dropdown selector to switch between Quest VR games and 2D flat Android apps.

---

## [v1.1.3] - 2026-10-08

### Fixed
- **vrSrc Authentication:** Restored API key authentication headers for vrSrc public mirror endpoints.

---

## [v1.1.2] - 2026-10-08

### Changed
- **Catalog Synchronization:** Improved error handling and resilience during catalog index fetch.

---

## [v1.1.1] - 2026-10-08

### Added
- **F-Droid 2D Android Flat App Catalog:** Integration for browsing and sideloading flat 2D Android applications alongside VR titles.

---

## [v1.1.0] - 2026-10-08

### Fixed
- **Mirror UI & Cache Invalidation:** Resolved caching issues and Cloudflare 403 blocks in the Mirror Manager UI.

---

## [v1.0.9] - 2026-10-08

### Changed
- **Mirror Configuration Persistence:** Enhanced local mirror config caching and recovery.

---

## [v1.0.8] - 2026-10-08

### Added
- **Default Mirror Configuration:** Baked-in default mirror settings for instant zero-config catalog access.

---

## [v1.0.7] - 2026-10-08

### Added
- **Dynamic SVG Artwork Placeholders:** Responsive fallback SVG posters when game covers are loading or unavailable.
### Fixed
- **Rclone Auth Validation:** Fixed rclone credentials validation routine.

---

## [v1.0.6] - 2026-10-08

### Fixed
- **Mirror Manager Modal:** Resolved modal UI interaction bug and ensured spoofed mirror is selected by default.

---

## [v1.0.5] - 2026-10-08

### Added
- **Mirror Manager:** Comprehensive UI to manage, switch, and test custom community mirrors and vrSrc integration.

---

## [v1.0.4] - 2026-10-08

### Added
- **Offline VR Catalog Bundling:** Pre-packaged local VR catalog allowing game discovery without active internet connection.

---

## [v1.0.3] - 2026-10-08

### Fixed
- **CLI Import Path:** Fixed relative import error when running the CLI directly and formatted error messages in terminal red.

---

## [v1.0.2] - 2026-10-05

### Fixed
- **Systemd User Scope Bus Connection:** Resolved `failed to connect to user scope bus` error on SteamOS with automatic XDG runtime environment fallback.
- **Multi-Path Steam User Discovery:** Dynamic detection of Steam userdata across SteamOS, Flatpak, and Linux distributions.

---

## [v1.0.1] - 2026-10-05

### Added
- **Steam-Style Storage Manager:** Multi-drive visualizer for NVMe SSD and MicroSD card with 1-click drive migrator.
- **Universal Sideloading Hub:** Sideload Quest APKs/XAPKs, Windows PCVR via Proton ARM64 / FEX-Emu, and Linux native binaries.
- **Beat Saber Mod & Song Manager:** Custom song injector with automated permissions unlocking.
- **On-Device Self-Updating Daemon:** Header alert chip and zero-downtime service reload.

---

## [v1.0.0] - 2026-10-05

### Added
- Initial release of FrameLoad for Valve Steam Frame standalone VR headset.
