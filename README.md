# FrameLoad 🚀

![FrameLoad Banner](docs/images/banner.jpg)

**All-in-One On-Device VR Sideloading, Catalog Downloader & Library Manager for the Steam Frame**

[![Steam Frame](https://img.shields.io/badge/Steam%20Frame-Supported-1b2838?logo=steam&logoColor=white)](https://forgejo.shieldserver.de/Crypto90/FrameLoad)
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

---

## 🚀 Quick Start (On Your Steam Frame)

### 1-Click Install

Open **Konsole** in SteamOS Desktop Mode (or connect via SSH) and run:

```bash
cd ~/
git clone https://forgejo.shieldserver.de/Crypto90/FrameLoad.git
cd FrameLoad
./install.sh
```

The installer will:
1. Configure `~/.config/containers/containers.conf` to prevent podman keyring exhaustion.
2. Create the desktop launcher `~/.local/share/applications/frameload.desktop`.
3. Enable the user background service `frameload.service` on port `5050`.
4. Add `FrameLoad` to your Steam library as a Non-Steam Game shortcut with artwork.

### Launching FrameLoad

- **From SteamVR / Gaming Mode:** Select **FrameLoad** directly in your Steam Library.
- **From Desktop Mode:** Open the Application Menu → **Game** → **FrameLoad**.
- **From Any Web Browser:** Navigate to:
  ```
  http://localhost:5050
  ```
  or from another device on the same Wi-Fi:
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
