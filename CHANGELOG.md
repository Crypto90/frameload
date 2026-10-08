# Changelog

All notable changes to **FrameLoad** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) using 0.0.1 increments.

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

## [v1.1.1] - 2026-10-08

### Added
- **F-Droid 2D Android Flat App Catalog:** Integration for browsing and sideloading flat 2D Android applications alongside VR titles.

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
