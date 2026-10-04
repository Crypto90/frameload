# FrameLoad 🚀

![FrameLoad Banner](docs/images/banner.jpg)

**All-in-One On-Device VR Sideloading, Catalog Downloader & Library Manager for the Steam Frame**

[![Steam Frame](https://img.shields.io/badge/Steam%20Frame-Supported-1b2838?logo=steam&logoColor=white)](https://forgejo.shieldserver.de/Crypto90/FrameLoad)
[![Releases](https://img.shields.io/badge/Release-v1.0.0-00f2fe?logo=forgejo&logoColor=white)](https://forgejo.shieldserver.de/Crypto90/FrameLoad/releases)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-Docker%20Runner-22c55e?logo=docker&logoColor=white)](https://forgejo.shieldserver.de/Crypto90/FrameLoad/actions)
[![Platform](https://img.shields.io/badge/Platform-SteamOS%20%7C%20Linux%20ARM64-blue)](#)
[![License](https://img.shields.io/badge/License-GPL--3.0-green.svg)](#)

---

## 🌟 Overview

**FrameLoad** brings the best of both worlds directly to your **Steam Frame VR device**:
- The **on-device browsing, downloading, and catalog engine** of **Rookie Sideloader** and **QRookie**
- The **Steam Frame Lepton container compatibility layer, OpenXR translation, and Steam shortcuts integration** of **FramePort** and **FrameDrop**

Unlike PC-dependent companion tools, **FrameLoad runs directly ON-DEVICE on the Steam Frame** (which runs standalone SteamOS / Linux ARM64). You can browse thousands of VR titles, download them, automatically apply Lepton container patches, and register them into your Steam library with high-resolution vertical grid posters—**all from inside your headset without ever needing a companion PC!**

---

## ⚡ Key Features

- **🎮 100% On-Device & Standalone:**
  - Runs natively on SteamOS (ARM64 / aarch64).
  - Open it directly in SteamVR, Gaming Mode, Desktop Mode, or access it over local Wi-Fi from your phone/tablet/laptop.
- **🌐 Direct Mirror & Catalog Integration:**
  - Integrated with VRP public mirrors (`meta.7z`, `VRP-GameList.txt`) with instant search, genre filtering, and sorting.
  - Multi-part archive download with auto-resumption (`Range: bytes`), download speed metrics (EMA), and ETA calculations.
- **📦 Automated Lepton Container Setup:**
  - Installs games to `~/Applications/quest-frame/<package>/`.
  - Configures Valve's Lepton Android container runtime (`lepton-app/`, `lepton-data/`, `lepton-shaders/`).
  - Auto-repairs Android external permissions (`/sdcard/Android/data/<package>/files/`).
  - Automatically isolates containers and cleans up rootless podman keyring quota leaks (`keyring = false`).
- **🔧 Compatibility & Translation Engine:**
  - VR APKs: Automatically detected and patched with FrameBridge OpenXR shims (`libopenxr_loader_generic.so`, `libframe_xrshim.so`, `libovrplatformcompat.so`).
  - 2D Flat Android Apps: Automatically detected and tagged with `lepton-show-flatscreen` to render as floating virtual windows in SteamVR.
  - PCVR Games: Compatibility with Proton ARM64, Revive, and WineOpenXR.
- **🎨 Complete Steam Library Integration:**
  - Pure Python binary `shortcuts.vdf` parser & serializer with automatic backup protection.
  - Automatically fetches and formats complete Steam Grid Artwork:
    - Vertical Poster (`600x900`)
    - Horizontal Banner (`460x215`)
    - Hero Background (`1920x620`)
    - Logo (`logo.png`) and Icon (`icon.png`)
  - Seamless 1-click launch via `steam://rungameid/<gameid>`.
- **🕹️ Dual Input Engine (VR Controller + Gamepad Navigation):**
  - Built-in HTML5 Gamepad API navigator (`gamepad.js`):
    - D-Pad / Left Stick: Navigate cards and controls with glowing focus rings.
    - LB / RB: Quick tab switching.
    - `A`: Select / Install / Play.
    - `B`: Back / Close modals.
    - `X`: Action button.
    - `Y`: Instant search focus.
- **💾 Save Data & Game Manager:**
  - 1-click game save export/import (`tar.gz`).
  - Per-game runtime settings editor (72Hz, 90Hz, 120Hz refresh rates, resolution scaling, MSAA, controller model rendering).
  - Clean uninstaller: Stops running containers, purges game data, and cleans Steam library shortcuts.
- **💾 Full MicroSD Card & Multi-Drive Storage:**
  - **Native MicroSD Detection:** Automatically discovers formatted MicroSD cards mounted by SteamOS (`/run/media/deck/*`, `mmcblk`), external USB drives, and custom storage paths.
  - **Selectable Install Location:** Install catalog downloads or sideloaded apps directly to Internal SSD or MicroSD Card.
  - **1-Click Game Migration:** Move installed games between Internal Storage and MicroSD Card seamlessly—automatically moves container directories, updates launch scripts, and refreshes Steam shortcuts.
  - **Multi-Drive Library Scanning:** Browse all installed games across all connected drives with clear MicroSD badges.
- **📦 Universal Package & Multi-Format Sideloading:**
  - **Split APK & Bundle Support:** Directly install `.xapk`, `.apks`, and `.zip` archives containing base APK, split configuration APKs, and OBB data trees.
  - **Loose Directory Sideloading:** Point to or drag an extracted game folder from a USB drive or MicroSD card; FrameLoad automatically pairs APKs with matching `com.pkg/` OBB folders.
  - **Pre-Install Package Inspection:** Inspect package name, title, engine (Unity, Unreal, Godot), VR requirements, and OBB status before installing.
- **📊 Steam-Style Storage Manager:**
  - Designed after Steam's storage settings with horizontal drive switcher cards (Internal SSD, MicroSD card).
  - Multi-colored segmented bar visualizer: Blue (Games), Teal (Saves & Data), Amber (Shaders & Cache), Purple (System), and Grey (Free Space).
  - Instant disk space breakdown per game (App APKs, saves, shader caches, artwork).
  - Multi-selection checkboxes with floating batch action bar and space reclaimed calculation.
  - Safe batch uninstallation with automatic save game archiving.
  - 1-click download cache cleanup and Lepton shader cache reset.
- **⚡ 1-Click Updates Management (OTA & Games):**
  - **FrameLoad App Self-Updater:** Automatically checks Forgejo releases for new versions, with a 1-click update button that pulls updates, refreshes container configurations, and reloads the service.
  - **Installed VR Game Updates:** Compares installed titles against the VRP catalog mirror, highlighting games with newer releases.
  - **1-Click Game Upgrades:** Upgrade individual games or batch update all titles with one click while safely preserving all save data (`lepton-data/`).

---

## 📸 App Screenshots

| 🌐 Browse Mirror Catalog | 🎮 Installed Library |
|:---:|:---:|
| ![Browse Catalog](docs/images/screenshot_catalog.png) | ![Installed Library](docs/images/screenshot_library.png) |
| *Browse, filter, and queue VR titles with one click* | *Manage installed games, launch in VR, and configure settings* |

| 🛠️ System & VR Diagnostics | ⚙️ Game Details & Sideloading |
|:---:|:---:|
| ![System & Diagnostics](docs/images/screenshot_system.png) | ![Game Details Modal](docs/images/screenshot_modal.png) |
| *Live telemetry: Lepton status, Proton ARM64, and storage* | *Quick install modal and per-game FrameBridge tweaks* |

---

## 🚀 Quick Start (On Your Steam Frame)

### ⚡ 1-Click Install (Single Command)

Open **Konsole** in SteamOS Desktop Mode (or connect via SSH) and run:

```bash
curl -fsSL https://forgejo.shieldserver.de/Crypto90/FrameLoad/raw/branch/main/install.sh | bash
```

> [!TIP]
> Click the **Copy** button on the top right of the code block above to copy the command directly to your clipboard!

---

### 📦 Alternative: Self-Extracting Offline Installer

If you prefer downloading a single pre-built installer package without needing `git`:

```bash
curl -fsSLO https://forgejo.shieldserver.de/Crypto90/FrameLoad/releases/download/v1.0.0/frameload-installer.sh
bash frameload-installer.sh
```

---

### 🔧 Alternative: Manual Git Clone

```bash
cd ~/
git clone https://forgejo.shieldserver.de/Crypto90/FrameLoad.git
cd FrameLoad
./install.sh
```

---

### What the Installer Does Automatically:
1. Configures `~/.config/containers/containers.conf` to stop rootless podman leaking kernel keyrings (`keyring = false`).
2. Installs standalone static 7-Zip (`7za`) archive extraction tools.
3. Creates the desktop launcher `~/.local/share/applications/frameload.desktop`.
4. Enables the background user service `frameload.service` on port `5050`.
5. Adds **FrameLoad** directly to your SteamVR & Steam library as a Non-Steam Game shortcut with complete vertical poster grid artwork.

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

---

## 🛠️ Command-Line Interface (CLI)

FrameLoad also includes a powerful CLI:

```bash
# Start Web Server & REST API
frameload serve --host 0.0.0.0 --port 5050

# Display Steam Frame system, Lepton, Proton, and battery telemetry
frameload info

# List installed games
frameload list

# Synchronize VR catalog metadata from mirror
frameload sync

# Search catalog
frameload search "Beat Saber"

# Install a local APK directly
frameload install /path/to/game.apk --title "My Game"

# Launch an installed game
frameload launch com.beatgames.beatsaber

# Cleanly uninstall a game and remove its Steam shortcut
frameload uninstall com.beatgames.beatsaber --keep-saves
```

---

## 📁 Storage Layout

| Directory | Purpose |
|---|---|
| `~/Applications/quest-frame/<pkg>/` | Game container anchor, `launch.sh`, `deployment.json`, and artwork |
| `~/Applications/quest-frame/<pkg>/lepton-app/` | `game.apk` and `obb/` files |
| `~/Applications/quest-frame/<pkg>/lepton-data/` | Container storage (`/sdcard/Android/data/<pkg>/files/` and save files) |
| `~/.local/share/frameload/data/` | Mirror catalog metadata (`VRP-GameList.txt`, thumbnails) |
| `~/.local/share/frameload/cache/` | In-progress downloads |
| `~/.local/share/frameload/backups/` | Exported save game archives |
| `~/.local/share/Steam/userdata/<id>/config/` | Steam `shortcuts.vdf` and `grid/` artwork |

---

## 🎮 VR Controller & Gamepad Bindings

| Button | Action |
|---|---|
| **D-Pad / Left Stick** | Navigate between cards, buttons, and inputs |
| **A / Cross** | Select / Open Game Details / Confirm |
| **B / Circle** | Back / Close Modal |
| **X / Square** | Quick Download / Launch Game |
| **Y / Triangle** | Jump to Search Bar |
| **LB / RB (L1 / R1)** | Previous / Next Tab |

---

## 📜 License

GPL-3.0 License. Built for the Steam Frame and open VR gaming community.
