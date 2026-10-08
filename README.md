# FrameLoad 🚀

![FrameLoad Banner](docs/images/banner.jpg)

**All-in-One On-Device VR Sideloading, Catalog Downloader & Library Manager for the Steam Frame**

[![Steam Frame](https://img.shields.io/badge/Steam%20Frame-Supported-1b2838?logo=steam&logoColor=white)](https://github.com/Crypto90/frameload)
[![GitHub Release](https://img.shields.io/github/v/release/Crypto90/frameload?color=00f2fe&logo=github&logoColor=white)](https://github.com/Crypto90/frameload/releases)
[![CI/CD](https://img.shields.io/github/actions/workflow/status/Crypto90/frameload/release.yml?logo=githubactions&logoColor=white)](https://github.com/Crypto90/frameload/actions)
[![Platform](https://img.shields.io/badge/Platform-SteamOS%20%7C%20Linux%20ARM64-blue)](#)
[![License](https://img.shields.io/badge/License-GPL--3.0-green.svg)](LICENSE)
[![ko-fi](https://img.shields.io/badge/Support-Ko--Fi-ff5e5b?logo=kofi&logoColor=white)](https://ko-fi.com/K3K314GUP?ref=frameload_readme)

---

## 🌟 Overview

**FrameLoad** brings the best of both worlds directly to your **Steam Frame VR device**:
- The **on-device browsing, downloading, and catalog engine** of **Rookie Sideloader** and **QRookie**
- The **Steam Frame Lepton container compatibility layer, OpenXR translation, and Steam shortcuts integration** of **FramePort** and **FrameDrop**

Unlike PC-dependent companion tools, **FrameLoad runs directly ON-DEVICE on the Steam Frame** (which runs standalone SteamOS / Linux ARM64). You can browse thousands of VR titles, download them, automatically apply Lepton container patches, and register them into your Steam library with high-resolution vertical grid posters—**all from inside your headset without ever needing a companion PC!**

---

## ⚡ Key Features

- **🎮 100% On-Device & Standalone:**
  - Runs natively on SteamOS (ARM64 / aarch64) with **zero companion PC required**.
  - **Zero-Browser Standalone Window:** Launches as a dedicated native desktop application window (`PyQt6`, `WebKit2GTK`, `pywebview`, or chromeless `--kiosk` profile) with **zero tabs, zero address bars, and zero external browser UI**.
  - Open it directly in SteamVR Gaming Mode or Desktop Mode, or from a phone, tablet or PC on the same Wi-Fi after approving that device once with a pairing code.
- **📲 Upload From a Phone or PC, or Pick Files in the Headset:**
  - On another device, open the dashboard, choose an APK (and its OBB files) and it is sent straight to the headset and installed.
  - In the headset, a file browser covers the home folder, Downloads and any microSD card or USB drive, so nobody has to type a path with a VR keyboard.
- **🕹️ Dual Input Engine (VR Laser Pointer + Gamepad Navigation):**
  - Built-in HTML5 Gamepad & VR Pointer API navigator (`gamepad.js`):
    - **Momentum Drag-to-Scroll:** Grab and flick lists, catalog grids, and modal dialogs with realistic inertial physics friction.
    - **Laser-Aim Targeted Scrolling:** Point your controller laser at any specific area (card notes, categories carousel, log drawer) and tilt the Right Stick to scroll that exact container smoothly.
    - **Laser-Aim Contextual Navigation:** Pointing at any element anchors D-Pad / Left Stick directional movement directly to that card.
    - **True 2D Spatial Vector Navigation:** Seamless joystick movement between cards, chips, search, and action buttons.
    - **Modal Focus Trapping & VR HUD:** Cleanly traps focus inside open dialogs (B/Grip button exits) with an on-screen VR controller guide bar.
- **🥽 Per-Game Settings That Reach the Headset:**
  - **Foveated rendering:** follow gaze (Valve's default), fixed, or off, through the Vulkan-layer variables Lepton passes to the game.
  - **Typing in VR apps** and a **hidden Android navigation bar** for 2D apps.
  - **For games ported with FramePort** (they contain the FrameBridge adapter): resolution scale (0.5x-2.0x), refresh rate (72-144 Hz), vibration strength, space warp and play-space options.
  - Settings Lepton cannot apply (device spoofing, MSAA, CPU/GPU levels) are not offered. See the [settings guide](#-per-game-settings-guide).
- **🖐️ Hand Tracking, As the Frame Provides It:**
  - The Steam Frame has no camera hand tracking. Its OpenXR runtime builds the 26-joint hand skeleton (`XR_EXT_hand_tracking`) from the controllers' finger sensors.
  - FrameLoad reads each APK's manifest, recognises games that support or require hands, and for FramePort-ported games switches between **Controllers** and **Hands** (FrameBridge's `controller_fix`). Games that require hands get them automatically.
- **🔎 Compatibility Check Before You Install:**
  - Reads the real binary manifest and native libraries of an APK and tells you whether it is ready (FramePort port, native OpenXR, 2D app), needs porting first (Meta OVRPlugin / VrApi, no launcher activity), or cannot run (32-bit only, split APK).
- **🌐 Direct Mirror & Catalog Integration:**
  - **Progressive Fuzzy Catalog Browser:** Infinite smooth scrolling eliminating cumbersome Next/Prev buttons, optimized for huge catalogs (2,900+ titles) with zero DOM reflow stutters.
  - **Pause & Resume Downloads:** Native HTTP Range and archive resumption with live Pause / Resume buttons in both the queue and bottom drawer.
  - **Live Extraction Progression:** Real-time percentage decompression feedback (`-bsp1` stream) for multi-gigabyte 7z and zip archives.
  - **1-Click Launch from Downloads:** Instant "Play Now" action for finished installs plus "Clear Completed" task management.
  - Multi-part archive download with auto-resumption (`Range: bytes`), download speed metrics (EMA), and ETA calculations.
- **📦 Automated Lepton Container Setup:**
  - Installs games to `~/Applications/quest-frame/<package>/`.
  - Configures Valve's Lepton Android container runtime (`lepton-app/`, `lepton-data/`, `lepton-shaders/`).
  - Auto-repairs Android external permissions (`/sdcard/Android/data/<package>/files/`).
  - Automatically isolates containers and cleans up rootless podman keyring quota leaks (`keyring = false`).
- **🔧 What Runs:**
  - Quest games already ported for the Frame with [FramePort](https://github.com/spoopyghosty0/frameport) (OVRPort + FrameBridge), native OpenXR 1.0 Android apps, and 2D Android apps.
  - **On-headset porting (experimental):** a game built for Meta's runtime is flagged "Needs porting first" and is ported automatically when you sideload it (or with its **Port for Steam Frame** button). FrameLoad runs [FramePort](https://github.com/spoopyghosty0/frameport)'s command line on the headset (OVRPort conversion, FrameBridge adapter, signing) and swaps in the result, keeping saves and OBB files. Set it up once under **System & Diagnostics > Quest Game Porting**.
  - 2D Android apps get Lepton's `lepton-show-flatscreen` marker and open as a flat window in the headset.
  - PCVR Games: Compatibility with Proton ARM64, Revive, and WineOpenXR.
- **🎨 Steam Library Integration:**
  - Pure Python binary `shortcuts.vdf` parser & serializer with automatic backups.
  - Artwork for every slot Steam shows (portrait `600x900`, banner `460x215`, hero `1920x620`, icon): a real cover or the app's icon where one exists, a generated image in the app's colour otherwise.
  - **Honest about Steam's limits:** Steam only loads new shortcuts when it starts. FrameLoad tells you which games are waiting, starts them itself in the meantime, and offers a safe one-press Steam restart (stop Steam, write the shortcuts, start it again).
- **💾 Saves, Logs & Game Management:**
  - Save backup and restore covering both places a Lepton app keeps data (its private storage and shared storage), including files owned by the container.
  - **Launch log with a diagnosis:** each game's last start, with the usual failures explained in plain words (no launcher activity, podman keyring quota, rejected APK, OpenXR 1.1, missing card).
  - Per-game settings editor (hand input, resolution scale, refresh rate, foveated rendering).
  - Clean uninstaller: stops the container, removes the game's files and its Steam shortcut.
- **🎵 Mod & Custom Content Injector:**
  - **Beat Saber Custom Songs:** Drop any custom song `.zip` directly from the Web UI or CLI; FrameLoad extracts it into `CustomSongs/`, repairs container permissions (`0777`), and makes it immediately available in game.
  - **Mod Packs & Textures:** Inject mods directly into `lepton-data/external/Android/data/<package>/files/` with auto-repair permissions, inspection, and deletion.
- **🛍️ 2D App Store (F-Droid):**
  - Browse, search and filter by category the free and open-source Android apps from F-Droid that Lepton can run (64-bit ARM, Android API 34 or lower).
  - Offers F-Droid's suggested release, verifies every download against the catalog's SHA-256 before installing, and marks installed apps and available updates.
  - Apps open as a flat window in the headset with Android's navigation bar hidden.
- **🪟 Windows & 🐧 Linux Apps (experimental):**
  - Sideload a Windows `.exe` or a Linux `.AppImage` / ELF binary; FrameLoad writes a launcher and a Steam shortcut.
  - These launchers are not yet verified on a Steam Frame. PC VR titles in particular need FramePort's OpenXR layer; use FramePort for those.
- **🔗 Install Links (`frameload://`):**
  - `frameload://install?url=https://…/app.apk&title=<title>`, `frameload://sideload?path=<file>&title=<title>`, `frameload://launch?package=<package>`.
  - A link never installs by itself: FrameLoad shows what it is and where it comes from, and waits for you to confirm in the dashboard.
- **💾 Full MicroSD Card & Multi-Drive Storage:**
  - **Native MicroSD Detection:** Automatically discovers MicroSD cards mounted by SteamOS, external USB drives, and custom storage paths. Cards formatted as FAT, exFAT or NTFS are shown but refused for games: Lepton data needs a Linux filesystem.
  - **Selectable Install Location:** Install catalog downloads or sideloaded apps directly to Internal SSD or MicroSD Card.
  - **1-Click Game Migration:** Move installed games between Internal Storage and MicroSD Card. The copy is checked before the original is removed, nothing at the destination is overwritten, and the launcher, settings and Steam shortcut follow the game.
  - **Multi-Drive Library Scanning:** Browse all installed games across all connected drives with clear MicroSD badges.
- **📦 Universal Package & Multi-Format Sideloading:**
  - **Bundles:** Install `.xapk`, `.apks` and `.zip` archives that hold one complete APK and its OBB data. Lepton installs a single APK, so an app delivered only as split APKs is reported as not installable.
  - **Loose Directory Sideloading:** Point to or drag an extracted game folder from a USB drive or MicroSD card; FrameLoad automatically pairs APKs with matching `com.pkg/` OBB folders.
  - **Pre-Install Package Inspection:** Inspect package name, title, engine (Unity, Unreal, Godot), VR requirements, and OBB status before installing.
- **📊 Steam-Style Storage Manager:**
  - Designed after Steam's storage settings with horizontal drive switcher cards (Internal SSD, MicroSD card).
  - Multi-colored segmented bar visualizer: Blue (Games), Teal (Saves & Data), Amber (Shaders & Cache), Purple (System), and Grey (Free Space).
  - Instant disk space breakdown per game (App APKs, saves, shader caches, artwork).
  - Multi-selection checkboxes with floating batch action bar and space reclaimed calculation.
  - Safe batch uninstallation with automatic save game archiving.
  - 1-click download cache cleanup and Lepton shader cache reset.
- **⚡ In-Headset Updates:**
  - Checks GitHub Releases a few times a day and shows a badge and banner when a new version is out.
  - **Verified updates:** the update package is checked against the release's `SHA256SUMS` before anything is replaced; a mismatch changes nothing.
  - One press updates FrameLoad and restarts its service.
  - **F-Droid apps:** an "Update N Apps" button appears in the app store when installed apps have newer versions.
  - **Catalog games:** installed titles are compared against the mirror catalog and can be upgraded while keeping save data.

---

## 📸 App Screenshots

| 🌐 Browse Mirror Catalog | 🎮 Installed Library |
|:---:|:---:|
| [![Browse Catalog](docs/images/screenshot_catalog.png)](docs/images/screenshot_catalog.png) | [![Installed Library](docs/images/screenshot_library.png)](docs/images/screenshot_library.png) |
| *Browse, search, and queue VR titles with live Ko-fi chip, battery, storage & Lepton telemetry* | *Manage installed games, launch in VR, and configure FrameBridge per-title settings* |

| 📊 Steam-Style Storage Manager | 📥 Sideload |
|:---:|:---:|
| [![Steam Storage Manager](docs/images/screenshot_storage.png)](docs/images/screenshot_storage.png) | [![Sideloading Hub](docs/images/screenshot_sideload.png)](docs/images/screenshot_sideload.png) |
| *Segmented storage visualizer, multi-drive mover (Internal SSD & MicroSD), and cache cleanup* | *Sideload Quest APKs, Windows Proton EXEs, Linux apps, and toggle flat theater presets* |

| 🛠️ System & Diagnostics with Ko-fi | 🎵 Game Details & Custom Songs / Mods |
|:---:|:---:|
| [![System & Diagnostics](docs/images/screenshot_system.png)](docs/images/screenshot_system.png) | [![Game Details & Mods](docs/images/screenshot_modal.png)](docs/images/screenshot_modal.png) |
| *Live telemetry (Lepton VR, FEX-Emu Proton ARM64), OTA updates, and Support on Ko-fi card* | *Per-game settings, drive migration, and Beat Saber custom songs & mod injector* |

---

## 🎨 Steam Grid Artwork & Visual Assets

FrameLoad includes high-resolution, pixel-perfect artwork tailored for **SteamOS Gaming Mode**, **SteamVR**, and the **Steam Library** in all official Steam formats:

### 🎮 Steam Grid Formats & Posters

| 📱 Steam Frame Device Poster (`600x900`) | 🌌 Portal Edition Poster (`600x900`) | 🏷️ Steam Grid Banner (`920x430`) |
|:---:|:---:|:---:|
| ![Device Poster](docs/images/steam/capsule_device.png) | ![Portal Poster](docs/images/steam/poster.png) | ![Steam Banner](docs/images/steam/banner.png) |
| *Steam Frame Headset Capsule* | *Vibrant SteamVR Portal Edition* | *Steam Library Grid Banner (460x215)* |

| 🥽 Steam Frame Headset Icon (`512x512`) | ⚡ FrameLoad Hologram Icon (`512x512`) | 🏷️ Transparent Title Logo |
|:---:|:---:|:---:|
| ![Headset Icon](docs/images/steam/icon_device.png) | ![Hologram Icon](docs/images/steam/icon.png) | ![Title Logo](docs/images/steam/logo.png) |
| *Headset Device App Icon* | *Cyan VR Vortex Glyph* | *Transparent Overlay Logo* |

### 🖼️ Steam Hero Backgrounds (`1920x620`)

**Steam Frame Hardware Edition Hero:**
![Steam Frame Device Hero](docs/images/steam/hero_device.png)

**SteamVR Cosmic Portal Edition Hero:**
![Portal Edition Hero](docs/images/steam/hero.png)

### 🌟 Concept Banner Artworks

| 🌊 Stream Edition | 🛠️ Hardware Edition | 🚪 Gateway Edition |
|:---:|:---:|:---:|
| ![Stream Edition](docs/images/banner_option1_stream.jpg) | ![Hardware Edition](docs/images/banner_option2_hardware.jpg) | ![Gateway Edition](docs/images/banner_option3_gateway.jpg) |
| *Data Stream & Wireless Sideloading* | *Industrial Steam Frame Device* | *Dimensional VR Portal Gateway* |

---

## 🚀 Quick Start (On Your Steam Frame)

### ⚡ 1-Click Install (Single Command)

Open **Konsole** in SteamOS Desktop Mode (or connect via SSH) and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/install.sh | bash
```

> [!TIP]
> Click the **Copy** button on the top right of the code block above to copy the command directly to your clipboard!

---

### 📦 Alternative: Self-Extracting Offline Installer

If you prefer downloading a single pre-built installer package without needing `git`:

```bash
# Grep latest release tag and download the standalone installer:
TAG=$(curl -s https://api.github.com/repos/Crypto90/frameload/releases/latest | grep '"tag_name":' | cut -d'"' -f4)
curl -fsSLO "https://github.com/Crypto90/frameload/releases/download/${TAG:-v1.3.2}/frameload-installer.sh"
bash frameload-installer.sh
```

*(Or via GitHub's direct latest redirect: `curl -fsSLO https://github.com/Crypto90/frameload/releases/latest/download/frameload-installer.sh`)*

---

### 🔧 Alternative: Manual Git Clone

```bash
cd ~/
git clone https://github.com/Crypto90/frameload.git
cd frameload
./install.sh
```

---

### What the Installer Does Automatically:
1. Configures `~/.config/containers/containers.conf` to stop rootless podman leaking kernel keyrings (`keyring = false`).
2. Installs standalone static 7-Zip (`7za`) archive extraction tools.
3. Creates the desktop launcher `~/.local/share/applications/frameload.desktop` and the `frameload` command in `~/.local/bin`.
4. Enables the background user service `frameload.service` on port `5050`.
5. Adds **FrameLoad** to your Steam library as a Non-Steam Game shortcut with artwork.

Lepton itself ships with the Steam Frame; FrameLoad only locates it.

---

### 🎮 Launching FrameLoad

- **In VR / Gaming Mode:** Open your Steam Library and select **FrameLoad**.
- **In Desktop Mode:** Open Application Launcher → **Games** → **FrameLoad**.
- **From Any Web Browser:** Navigate to:
  ```
  http://localhost:5050
  ```
  or from your phone / tablet / PC on the same Wi-Fi:
  ```
  http://<steam-frame-ip>:5050
  ```
  The first time, that device shows a pairing page. In the headset open **System & Diagnostics → Phone & PC Access → Show Pairing Code** and type the six digits on the device. Paired devices are listed there and can be removed.

---

## 🗑️ Clean Uninstallation

If you ever wish to completely remove FrameLoad and all its traces from your device:

### ⚡ 1-Click Clean Uninstall (Single Command)

```bash
curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/uninstall.sh | bash
```

Or from your terminal if already installed:

```bash
bash ~/Applications/FrameLoad/uninstall.sh
```

### Options & Flags:

| Option | Description |
| :--- | :--- |
| **`./uninstall.sh`** | Interactive mode (asks whether to keep games and save backups). |
| **`-y` / `--yes`** | Skips prompts; cleanly removes daemon, desktop launcher, Steam shortcuts, and caches while preserving installed games and saves. |
| **`--purge-games`** | Also deletes all sideloaded VR games in `~/Applications/quest-frame/` and on MicroSD cards. |
| **`--purge-all`** | Total clean wipe: removes app, caches, games, saves, and backups. |
| **`--keep-backups`** | Preserves game save backups in `~/.local/share/frameload/backups/` *(default: yes)*. |

### What the Uninstaller Cleans Up Automatically:
1. Stops and deletes the background systemd service (`frameload.service`).
2. Removes the Desktop launcher (`~/.local/share/applications/frameload.desktop`).
3. Removes FrameLoad and all 5 Grid artwork files from Steam (`shortcuts.vdf` and `userdata/*/config/grid/`).
4. Kills any lingering Lepton container shims.
5. Deletes caches, metadata, and temporary files (`~/.local/share/frameload/`).
6. Optionally deletes installed VR games and preserves or removes save game backups according to your choice.

---

## 🛠️ Command-Line Interface (CLI)

FrameLoad includes a full-featured CLI for on-device management and scripting:

```bash
# Start Web Server & REST API
frameload serve --host 0.0.0.0 --port 5050

# Launch as a dedicated standalone desktop application window (Zero-Browser Chrome)
frameload window

# Display Steam Frame system, Lepton, Proton, and battery telemetry
frameload info

# List installed games
frameload list

# List presets and every setting
frameload tune --list

# Apply a preset (default, sharp, smooth, battery)
frameload tune com.beatgames.beatsaber --preset sharp

# Set individual values
frameload tune com.beatgames.beatsaber --scale 1.3 --refresh 90 --hands controllers --set foveation=fixed

# Batch-apply an optimization preset across ALL installed games
frameload tune --batch default

# Synchronize VR catalog metadata from mirror
frameload sync

# Search catalog
frameload search "Beat Saber"

# Install a local package (Quest APK, Windows Proton EXE, Linux AppImage)
frameload install /path/to/game.xapk --title "My Game"

# Install as 2D Flat Android window with customized preset
frameload install /path/to/app.apk --flat --window-preset tablet

# Inject Beat Saber custom song or mod package
frameload inject-mod com.beatgames.beatsaber /path/to/song.zip --name "SongName"

# Handle a frameload:// deep link URL directly
frameload handle-url "frameload://launch?pkg=com.beatgames.beatsaber"

# Launch an installed game
frameload launch com.beatgames.beatsaber

# Cleanly uninstall a game and remove its Steam shortcut
frameload uninstall com.beatgames.beatsaber --keep-saves

# Completely uninstall FrameLoad itself and remove all system traces
frameload uninstall-app --keep-backups
```

---

## 🥽 Per-Game Settings Guide

Open a game in **Installed Library** and press **Settings**. Every control maps to something the headset reads.

### For every Android app (Lepton)

| Setting | What it does | How |
| :--- | :--- | :--- |
| Foveated rendering | *Follow gaze* (default), *Fixed* (cures one-eye jitter in some games) or *Off* | `FDM_DEBUG=disable_offsets` / `VK_INSTANCE_LAYERS=""` for `lepton start` |
| Allow typing (VR) | Shows the app's Android window behind its VR view so Steam's keyboard reaches it | `lepton-show-flatscreen` marker |
| Hide navigation bar (2D) | Removes Android's back / home / recents bar | `qemu.hw.mainkeys=1` boot property |

### For games ported with FramePort (FrameBridge adapter)

| Setting | Values | FrameBridge key |
| :--- | :--- | :--- |
| Hand input | Automatic, Controllers, Hands | `controller_fix` |
| Resolution scale | 0.5x - 2.0x | `scale` |
| Refresh rate | Game's choice, 72, 80, 90, 96, 108, 120, 144 Hz | `refresh_rate` |
| Vibration strength | 0 - 1 | `haptic_scale` |
| Turn off space warp | on / off | `hide_space_warp` |
| Keep the play space still | on / off | `stable_local` |

FrameLoad writes only the values you change into `settings.conf` and `framebridge.conf`, and leaves every other line of those files alone. For an APK without the adapter these controls are shown greyed out, because nothing would read them.

**Presets:** *Game defaults*, *Sharper* (1.3x), *120 Hz*, *Battery saver* (0.85x at 72 Hz).

### What is deliberately not here

Lepton writes its own Android system properties (`ro.product.model=Lepton`) and offers no per-game override, so a launcher cannot spoof a Quest model, force MSAA or anisotropic filtering, or set CPU/GPU levels. Earlier FrameLoad versions showed such controls; they changed nothing and were removed in v1.3.2.

### Porting a Quest game on the headset

1. **System & Diagnostics > Quest Game Porting > Set Up Porting.** FrameLoad installs FramePort's command-line wheel into `~/.local/share/frameload/frameport-venv` and lets it download its Java runtime, OVRPort and apksigner. FramePort's own data stays in `~/.local/share/frameload/frameport-home`.
2. From then on a sideloaded Quest game that needs it is ported automatically right after it is installed; the dialog shows FramePort's output, and a big game takes several minutes. Games sideloaded before the setup are ported when the setup finishes. **Port for Steam Frame** on a game in your library does the same by hand (to retry, or after updating FramePort), and the switch on the porting card turns the automatic step off.
3. The original APK is kept as `unported.apk` next to the game, so it can be ported again with a newer FramePort.

Command line: `frameload port --setup`, `frameload port <package>`, `frameload port --status`. An existing FramePort install can be used instead by setting `porting.frameport_cli` in `config.json`.

Setup, analysis and the build step were run against the real FramePort command line on Linux (x86-64 and ARM64 containers). It has not yet been run on a Steam Frame, and whether a given game then starts is decided by FramePort's patches for it; game-specific fixes belong in FramePort's catalog.

### Self-test

You never have to run this: the dashboard runs it by itself each time it opens and shows a notice only if something is wrong. To see the full list, `frameload doctor` (or **System & Diagnostics > Run Self-Test**) checks Lepton, podman and its keyring fix, the tools the launcher needs, your Steam library, every installed game and the porting setup, and lists the cameras the system exposes. Include its output when you report a problem.

### Hand tracking

The Frame does not track bare hands with its cameras. Its runtime exposes `XR_EXT_hand_tracking` with a skeleton driven by the controllers' capacitive finger sensors, so hand-tracking games are played holding the controllers. *Hand input: Hands* passes that skeleton to a FramePort-ported game; *Controllers* reports Touch controllers instead; *Automatic* chooses Hands only for games whose manifest requires hand tracking.

Playing with bare hands and no controllers is not possible today: it needs a tracker that reads the headset's cameras and feeds SteamVR, which neither Valve nor FrameLoad ships. Community projects are working on one. Because FrameLoad passes the runtime's own hand skeleton through, a game set to *Hands* should pick up such a tracker without changes here once one exists.

### Opening the dashboard from another device

Requests from the headset itself are trusted. Every other device must be paired once with a six-digit code shown in the headset (**System & Diagnostics → Phone & PC Access**); the code is valid for five minutes and works once. Only someone at the headset can create codes or remove devices.

The dashboard answers under an IP address, `localhost` and the headset's own name. To use another host name, run `frameload allow-host <name>` on the Frame (`--remove` undoes it).

### When a new game is missing from Steam

Steam reads its shortcut list only when it starts. After an install, FrameLoad shows which games are waiting. You can start them right away with **Launch** in FrameLoad's library, or press **Restart Steam Now**, which closes FrameLoad's window and any running game, rewrites the shortcuts while Steam is stopped, and starts Steam again.

### When a game does not start

Open the game in the library and press **Launch Log**. FrameLoad reads the log of the last start and names the cause when it recognises one; the raw log is shown below for everything else.

---

## 📁 Storage Layout

| Directory | Purpose |
|---|---|
| `~/Applications/quest-frame/<pkg>/` | Game container anchor, `launch.sh`, `deployment.json`, and artwork |
| `~/Applications/quest-frame/<pkg>/lepton-app/` | `game.apk` and `obb/` files |
| `~/Applications/quest-frame/<pkg>/lepton-data/` | Container storage: `internal/<pkg>` (the app's private data, most saves) and `external/` (shared storage, `Android/data/<pkg>/files/`) |
| `~/.local/share/frameload/data/` | Mirror catalog metadata (`VRP-GameList.txt`, thumbnails) |
| `~/.local/share/frameload/cache/` | In-progress downloads |
| `~/.local/share/frameload/backups/` | Exported save game archives |
| `~/.local/share/frameload/uploads/` | Files received from a phone or PC, removed after install |
| `~/Documents/FrameLoad-signing-keys/` | Signing keys of ported games, saved when FrameLoad is uninstalled |
| `~/.local/share/Steam/userdata/<id>/config/` | Steam `shortcuts.vdf` and `grid/` artwork |

---

## 🎮 VR Controller & Laser Pointer Bindings

| Control / Gesture | Action |
|---|---|
| **Laser Pointer Drag & Flick** | **Momentum Drag-to-Scroll:** Grab any page, catalog grid, or modal and flick with natural inertial physics friction |
| **Laser Aim + Right Stick** | **Targeted Scrolling:** Point your laser at any specific card, release note, chips bar, or log drawer and tilt Right Stick to scroll it smoothly |
| **Laser Aim + Left Stick / D-Pad** | **Contextual Navigation:** Pointing at any element anchors joystick movement directly to that card |
| **Index Trigger / A Button** | Select / Open Game Details / Sideload / Confirm |
| **Grip Button / B Button** | Back / Close Modal dialogs (Modal Focus Trap) |
| **X Button** | Quick Action (Download / Launch) |
| **Y Button** | Instant Search Focus |
| **LB / RB (Bumpers)** | Previous / Next Tab switching |

---

## ☕ Support the Project

If you love using **FrameLoad** on your Steam Frame and want to support ongoing development, new features, and maintenance, you can support me on Ko-fi:

<p align="left">
  <a href="https://ko-fi.com/K3K314GUP?ref=frameload_readme" target="_blank" rel="noopener noreferrer">
    <img src="https://storage.ko-fi.com/cdn/kofi2.png?v=3" alt="Buy Me a Coffee at ko-fi.com" height="42">
  </a>
</p>

[![Support on Ko-fi](https://img.shields.io/badge/Support-Ko--Fi-ff5e5b?style=for-the-badge&logo=kofi&logoColor=white)](https://ko-fi.com/K3K314GUP?ref=frameload_readme)

---

## 📜 License

GPL-3.0, see [LICENSE](LICENSE). On-headset porting runs [FramePort](https://github.com/spoopyghosty0/frameport) (GPL-3.0), which FrameLoad downloads on request; the game folder layout follows FramePort's so both tools can manage the same library. Not affiliated with Valve or Meta.
