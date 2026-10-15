# FrameLoad 🚀

![FrameLoad Banner](docs/images/banner.jpg)

**Install, port, play and manage Android VR games and apps on the Steam Frame, from inside the headset.**

[![Steam Frame](https://img.shields.io/badge/Steam%20Frame-Supported-1b2838?logo=steam&logoColor=white)](https://github.com/Crypto90/frameload)
[![GitHub Release](https://img.shields.io/github/v/release/Crypto90/frameload?color=00f2fe&logo=github&logoColor=white)](https://github.com/Crypto90/frameload/releases)
[![CI/CD](https://img.shields.io/github/actions/workflow/status/Crypto90/frameload/release.yml?logo=githubactions&logoColor=white)](https://github.com/Crypto90/frameload/actions)
[![Platform](https://img.shields.io/badge/Platform-SteamOS%20%7C%20Linux%20ARM64-blue)](#)
[![License](https://img.shields.io/badge/License-GPL--3.0-green.svg)](LICENSE)
[![ko-fi](https://img.shields.io/badge/Support-Ko--Fi-ff5e5b?logo=kofi&logoColor=white)](https://ko-fi.com/K3K314GUP?ref=frameload_readme)

---

FrameLoad runs on the Steam Frame itself (SteamOS on ARM64), so no PC is needed. It:
- installs Android apps into Valve's Lepton container, the Frame's own Android runtime;
- ports games built for Meta's Quest runtime with [FramePort](https://github.com/spoopyghosty0/frameport);
- adds everything to your Steam library with artwork;
- watches storage, memory and play time.

Its dashboard is built for the controller's laser pointer in the headset. You can also open it from a phone or PC on the same Wi-Fi.

**Contents:** [Looks](#-six-looks) · [Features](#-features) · [Install](#-install) · [Opening FrameLoad](#-opening-frameload) · [Updating](#-updating) · [Uninstalling](#-uninstalling) · [Guide](#-guide) · [Controls](#-controls) · [Command line](#-command-line) · [Files and folders](#-files-and-folders) · [Configuration](#-configuration) · [Support](#-support-the-project)

---

## 🎨 Six Looks

FrameLoad comes in six looks. Pick one under **System → Appearance**. It changes at once and is remembered on the headset. **Big Picture** is the default. Each look arranges the library its own way, and every other screen follows its colours and type.

| A · Big Picture (default) | B · Spatial |
|:---:|:---:|
| [![Big Picture](docs/images/looks/look-a.jpg)](docs/images/looks/look-a.jpg) | [![Spatial](docs/images/looks/look-b.jpg)](docs/images/looks/look-b.jpg) |
| *Looks like SteamOS: tabs on top, Steam covers, the controller's buttons along the bottom* | *A floating glass window with the navigation beside it; the largest targets* |

| C · Showcase | D · Neon |
|:---:|:---:|
| [![Showcase](docs/images/looks/look-c.jpg)](docs/images/looks/look-c.jpg) | [![Neon](docs/images/looks/look-d.jpg)](docs/images/looks/look-d.jpg) |
| *Your last game fills the screen with one big Play button; the library sits in one row* | *The original FrameLoad look, refined* |

| E · Command Center | F · Daylight |
|:---:|:---:|
| [![Command Center](docs/images/looks/look-e.jpg)](docs/images/looks/look-e.jpg) | [![Daylight](docs/images/looks/look-f.jpg)](docs/images/looks/look-f.jpg) |
| *A sortable list beside a detail panel, for big libraries and managing them* | *Calm and very legible, in a light and a [dark](docs/images/looks/look-f-dark.jpg) version* |

The fonts of the looks are bundled with FrameLoad (SIL Open Font License, see `frameload/web/static/fonts/OFL.txt`), so they work without a network. Game titles and covers in these pictures are examples.

---

## ⚡ Features

### 📚 Library
- All your games and apps in one place. The library starts with the games you played last (**Recent games** in Big Picture), with when you last played and for how long. Each game's launcher records its sessions, so games started from Steam count too.
- Sort by recently played, name, install date or size. Search filters as you type.
- A game's page has **Launch in VR** (**Open** for a 2D app), **Settings**, **Launch Log**, **Backup Saves** and **Uninstall**, and **What Happened** when its last session ended in a crash or a stop.
- A running game gets a **Stop** button, plus a Stop chip that stays on screen while it runs.
- A Quest game that still needs porting shows **Port & Play**: it is ported first and starts by itself when that is done.

### 📥 Installing apps
- **Install File:** install an APK, an XAPK, APKS or ZIP bundle, or an extracted game folder.
  - The built-in file browser covers Home, Downloads, the microSD card and USB drives, so you never type a path on a VR keyboard.
  - OBB files beside the APK are installed with it: loose `main.` / `patch.<version>.<package>.obb` files, or a folder named after the package.
- **Upload from a phone or PC:** open the dashboard on a paired device and choose the APK and its OBB files. They are sent to the headset and inspected, and **Install and Add to Steam Library** installs them.
- **Compatibility check before you install:** FrameLoad reads the APK's binary manifest and its native libraries and gives one of four verdicts:

  | Verdict | When |
  | :--- | :--- |
  | *Ready for Steam Frame* | Ported with FramePort, or a 2D app |
  | *Should run* | Native OpenXR |
  | *Needs porting first* | Built for Meta's runtime, or no launcher activity |
  | *Cannot run* | 32-bit only, needs a newer Android than Lepton's (Android 14), delivered as split APKs, or checks its own signature |
- **Browse** has two catalogs:
  - VR games from the catalog mirror set under System → Mirror Manager
  - 2D apps from F-Droid, IzzyOnDroid, Guardian Project and repositories you add

  Downloads can be paused, resume after an interruption and install by themselves when they finish. The Downloads tab shows each one with its picture, its state (Downloading, Unpacking, Installing, Installed, Failed) and the time left.
- **2D apps:**
  - **Sources:** F-Droid (the default), IzzyOnDroid (apps as their developers release them) and Guardian Project (Orbot, Tor Browser and other privacy apps). Choose one in Browse, or **All sources**, where an app listed by several sources appears once and its page shows the others.
  - **Your own repositories:** **Sources** → **Add a Repository** takes any F-Droid repository address (`https://…` or `fdroidrepos://…`, with or without `?fingerprint=`). FrameLoad downloads its app list, checks its signature and shows its signing key before you add it. Only public https addresses are accepted. Sources are added, removed or hidden on the headset itself; a paired phone or PC sees the list only.
  - **Signed app lists:** each source's list is used only when it is signed by that source's key (built into FrameLoad for the three sources above, recorded when you add a repository), and an older list never replaces a newer one. When a source does not answer, the mirrors its last list named are tried. Nothing is downloaded until you press **Sync Catalog**.
  - Lists only apps Lepton can run: 64-bit ARM apps that install on Android 14, Lepton's version. Google's own services (microG's packages) and Xposed modules are left out.
  - Offers each source's suggested version and checks every download against the list's SHA-256 before installing.
  - Each app's page shows its screenshots, and its trailer where it has one.
  - **Update N Apps** appears when installed apps have newer versions. An app is updated only from the source it was installed from, and only when the new version is signed by the same key; installing it from another source works only with the same key as well (otherwise uninstall it first, after backing up its saves). Apps installed from a file get no updates from a source.
  - Apps open as a flat window with Android's navigation bar hidden.
- **Install links:** `frameload://install?url=…` (an https link to an `.apk`), `frameload://sideload?path=…` and `frameload://launch?package=…`. A link never installs anything by itself: the dashboard shows where it comes from and waits for you to press **Install**, and a Quest game installed that way is ported like any other install. A launch link starts the game right away and refuses an app that cannot run on the Frame. A game built for Meta's runtime is ported first only while automatic porting is on (start it again when the port is done).

### 🔧 Quest games, ported on the headset
- Games built for Meta's Quest runtime are converted for the Frame on the headset with [FramePort](https://github.com/spoopyghosty0/frameport): OVRPort conversion, the FrameBridge adapter, and signing.
- FrameLoad does the setup and upkeep for you:
  - downloads FramePort and its tools by itself and keeps FramePort current;
  - ports a game right after it is installed;
  - keeps the original APK, so the game can be ported again.
- A progress bar shows the step the port is on. A port keeps running in the background, with its percentage in the dashboard. See [Porting a Quest game](#porting-a-quest-game).

### 🥽 Per-game settings
- **Every Android app, ported or not:** foveated rendering (follow gaze, fixed or off) and typing for VR apps, the navigation bar for 2D apps.
- **Games ported with FramePort:** hand input, resolution scale, refresh rate (72-144 Hz), vibration strength, space warp and play space, with the presets *Sharper*, *120 Hz* and *Battery saver*.
- Only settings the headset actually reads are offered. Defaults for all games are under System → Default Game Settings. Details are in the [settings guide](#per-game-settings).

### 🎮 Steam library
- **Artwork:** every install becomes a non-Steam game with a poster, banner, hero image, logo and icon.
  - The icon is the app's own launcher icon from its APK. A downloaded cover stands in for apps without a complete icon of their own.
  - A downloaded cover is used for the poster where there is one.
  - The dashboard draws whatever is still missing from the icon, the cover and the title.
- **New games:** Steam loads new shortcuts only when it starts. FrameLoad shows which games are waiting, starts them itself in the meantime, and offers **Restart Steam Now**.
- **Steam's menu:** Steam opens its Resume / Exit menu over a game that has just started. When a ported game shows its first frame, its launcher closes that menu. If you only hear a VR game, **Show** brings it in front of FrameLoad's window. See [Steam's menu over a game that just started](#steams-menu-over-a-game-that-just-started).

### 💾 Storage: internal, microSD and USB
- **Only real drives are listed:** the internal storage, a microSD card and USB drives. Drives are classified by the bus the kernel reports, so the Frame's own system partitions never appear.
- **FAT, exFAT and NTFS:** cards in these formats are shown but cannot hold games. Lepton needs a Linux filesystem such as ext4.
- **Choosing a drive:** with more than one drive that can hold games, installing from Browse asks where to put the game, like Steam does. It can remember your choice as the default.
- **Moving games:** **Move Drive** on a game's page asks which drive to move it to and shows each drive's free space against the game's size. The copy is checked before the original is removed.
- **The Storage tab** shows each drive's space split into games, saves, shaders and other, and lists every game's size. You can select several games to move or uninstall them, clean the download cache, or reset the shader caches of the installed games on every drive.

### 🧊 Freeze Guard, Keep Awake and Performance
- **Freeze Guard:** a game that uses up the headset's memory, or whose picture freezes, can leave the whole headset unresponsive, even the Steam button. FrameLoad prevents that with three switches, all on by default:
  - It limits each game's memory so SteamVR keeps 2.5 GB.
  - It watches memory pressure while a game runs, ends the game before the headset locks up, and tells you which game it was.
  - It stops a game whose picture has not changed for 30 seconds (15 s, 1 or 2 minutes can be chosen). It waits while the headset is asleep, the Steam menu is open or the game is still drawing.
- **What happened:** when a game crashes, hangs the graphics processor, runs out of memory, is stopped by the Freeze Guard, cannot start or closes right after starting, FrameLoad opens a window with the cause in plain words, the log lines that show it, and **Copy Log** / **Save Log** for the full report.
- **Keep Awake:** FrameLoad holds SteamOS's sleep inhibitor while it downloads from Browse, installs a game (a download, a file from the Install File tab or one sent from your phone or PC) or ports a game. You can also keep the headset awake for an hour, or until you switch it off. Whether Steam's own sleep timer on the Frame honours the inhibitor is not confirmed yet.
- **Performance:** System → Performance shows CPU, memory, swap, GPU clock and temperatures live. Neon, Spatial, Command Center and Daylight also show CPU use in their status area.

### 📱 Phone & PC access
- Open `http://<headset-ip>:5050` on another device on the same network. Pair it once with a six-digit code shown in the headset, and it can browse, install and upload like the headset can.

### 🧩 Saves, mods and logs
- **Save backups** hold the app's private storage, where most games save, and its shared storage. Uninstalling a game in the dashboard makes a backup first; if the backup fails, the game stays installed until you choose to uninstall it without one.
- **Mods and Beat Saber custom songs** go into the game's shared storage from its page or the command line.
- **Launch Log** explains the usual reasons a game does not start, in plain words. **Copy Log** and **Save Log** hand out the log as a report to share when you ask for help.
- **Self-test:** checks everything FrameLoad relies on. It runs by itself when the dashboard opens and only speaks up when something is wrong.

### ⚡ Updates
- **In-headset updates:** FrameLoad tells you when a new version is out and updates itself with one press in the headset. Release downloads are checked against the release's `SHA256SUMS`.

### 🪟 Windows and 🐧 Linux apps (experimental)
- A Windows `.exe` or a Linux AppImage / ELF binary gets a launcher and a Steam shortcut.
  - The `.exe` runs with a Proton from your Steam libraries, or Wine.
- These launchers have not been verified on a Steam Frame yet.
- Per-game settings, the Freeze Guard and Stop do not cover them.

| Porting on the headset | Choosing the drive |
|:---:|:---:|
| [![Porting](docs/images/features/porting.jpg)](docs/images/features/porting.jpg) | [![Install location](docs/images/features/install-drive.jpg)](docs/images/features/install-drive.jpg) |
| **Per-game settings** | **Downloads** |
| [![Settings](docs/images/features/settings.jpg)](docs/images/features/settings.jpg) | [![Downloads](docs/images/features/downloads.jpg)](docs/images/features/downloads.jpg) |

*Big Picture look with example games and drives.*

> [!NOTE]
> Only install games and apps you own or are otherwise allowed to use.

---

## 🚀 Install

On the Steam Frame, open a terminal (Konsole in Desktop Mode, or SSH) and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/install.sh | bash
```

This puts FrameLoad in `~/Applications/FrameLoad` and sets it up. It makes a git checkout when git is available, and otherwise downloads the latest release. Run it as your normal user, not with `sudo`.

**Or with the release installer.** It needs no git. Run it as a file, not through a pipe:

```bash
curl -fsSLO https://github.com/Crypto90/frameload/releases/latest/download/frameload-installer.sh
bash frameload-installer.sh
```

**Or from a git clone:**

```bash
git clone https://github.com/Crypto90/frameload.git ~/Applications/FrameLoad
bash ~/Applications/FrameLoad/install.sh
```

To install somewhere else, give the folder to `bash`: `curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/install.sh | FRAMELOAD_INSTALL_DIR=<folder> bash`, or `FRAMELOAD_INSTALL_DIR=<folder> bash frameload-installer.sh`. See [Uninstalling](#-uninstalling) for removing such an install.

### What the installer sets up

1. `keyring = false` in `~/.config/containers/containers.conf`. Without it, rootless podman runs out of kernel keyrings after about 200 game starts.
2. A static 7-Zip in `~/.local/share/frameload/bin/` when none is installed. It unpacks XAPK, APKS and ZIP bundles.
3. The desktop entry, which also opens `frameload://` links, and the `frameload` command in `~/.local/bin`.
4. The background service `frameload.service` (a systemd user service on port 5050). Where the user's systemd cannot be reached, an autostart entry starts it instead.
5. **FrameLoad** in your Steam library, with its artwork. If Steam was running, restart it (or switch to Gaming Mode) to see it.

Lepton comes with the Steam Frame; FrameLoad only looks for it. FrameLoad downloads the porting tools by itself later (see [Porting a Quest game](#porting-a-quest-game)).

---

## 🥽 Opening FrameLoad

- **In the headset or Gaming Mode:** select **FrameLoad** in your Steam library.
- **In Desktop Mode:** application launcher → Games → **FrameLoad**, or run `frameload` in a terminal.
- **In a browser on the headset:** `http://localhost:5050`.
- **From a phone, tablet or PC** on the same network: `http://<headset-ip>:5050` (System → Phone & PC Access shows the address). The first time, that device shows a pairing page. In the headset, open **System → Phone & PC Access → Show Pairing Code** and type the six digits on the device.

FrameLoad opens exactly one window, and closing that window closes it. The service keeps running in the background. The window is the first of these that is available:
1. a native window, if Qt WebEngine or WebKit2GTK is installed
2. Chrome or Chromium in app mode
3. Firefox with a profile of its own (full screen in Gaming Mode)
4. the default browser (closing it does not end FrameLoad in Steam; use Steam's Exit)

Starting FrameLoad again while its window is open does not open a second one.

---

## 🔄 Updating

FrameLoad checks GitHub at most every six hours; **Check for Updates** under System → FrameLoad Updates checks right away. When a new version is out, an **Update** chip appears in the header and a banner on top.

To install it, press **Review & Update** in the banner (or the **Update** chip) and then **Update and Restart**, or press **Update Now** under System → FrameLoad Updates. FrameLoad updates itself and restarts its service, and the page reloads.

- **A git install** updates with `git pull` from `main`, so it also gets fixes between releases. If files you changed in the FrameLoad folder are in the way, the update stops and names them; nothing is stashed or overwritten, and nothing restarts.
- **A release install** downloads the new release archive and checks it against the release's `SHA256SUMS`. If it does not match, nothing is changed.

---

## 🧹 Uninstalling

**In the headset:** go to System → **Clean Uninstallation** → **Uninstall FrameLoad...**.
1. Choose whether to delete the installed games too (off by default) and whether to keep the save backups (on by default).
2. Type `UNINSTALL` and confirm.

**From a terminal:**

```bash
curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/uninstall.sh | bash
```

It asks the same questions. To answer them on the command line instead, pass options like this: `curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/uninstall.sh | bash -s -- --yes`.

| Option | Effect |
| :--- | :--- |
| `-y`, `--yes` | Do not ask; keep games and save backups unless the options below say otherwise |
| `--purge-games` | Also delete every installed game (internal storage, microSD card, USB drives) |
| `--purge-backups` | Also delete the save backups |
| `--purge-all` | Same as `--yes --purge-games --purge-backups` |

`bash uninstall.sh` in the FrameLoad folder does the same. `frameload uninstall-app [--yes] [--purge-games] [--purge-backups]` asks only one y/N question (none with `--yes`): games and save backups are kept unless you pass the options.

If you installed into another folder, run `curl -fsSL https://raw.githubusercontent.com/Crypto90/frameload/main/uninstall.sh | FRAMELOAD_INSTALL_DIR=<folder> bash`, then delete that folder yourself.

**What is removed:**
- the service, the desktop entry and the `frameload` command
- FrameLoad's own Steam shortcut and its artwork
- `~/.local/share/frameload` (except the save backups, when kept)
- the browser profile of FrameLoad's window
- `~/Applications/FrameLoad`

Installed games and their Steam shortcuts stay unless you choose to delete the games. When you delete them and keep the save backups, a game whose saves cannot be backed up stays installed; `uninstall.sh` and `frameload uninstall-app` name it, and the in-headset uninstall writes it to the service's log (`journalctl --user -u frameload`). With a FrameLoad older than v1.3.7 installed, `uninstall.sh` uses that version's rules for the games, so update first if you delete games and keep backups. While Steam is running it keeps its own copy of the shortcut list and can write FrameLoad's entry back when it exits; if FrameLoad is still in your library after a Steam restart, remove it there (Manage → Remove non-Steam game).

The signing keys of ported games are always copied to `~/Documents/FrameLoad-signing-keys` first. An update of a ported game must be signed with the same key, and FrameLoad's next porting setup imports the keys again.

---

## 📖 Guide

### Per-game settings

Open a game in the **Library** and press **Settings**. Every control maps to something the headset reads. **System → Default Game Settings → Edit Defaults** sets the values every game starts from. When you save a game's Settings, the game keeps as its own only the values you set differently from those defaults; every other setting goes on following them, so a later change of the defaults still reaches it. Setting a value back to the default makes it follow the defaults again.

**For every Android app (Lepton)**

| Setting | What it does | How |
| :--- | :--- | :--- |
| Foveated rendering (VR) | *Follow gaze* (default), *Fixed* (cures one-eye jitter in some games) or *Off* | `FDM_DEBUG=disable_offsets` / `VK_INSTANCE_LAYERS=""` for `lepton start` |
| Allow typing (VR) | Shows the app's Android window behind its VR view, so Steam's keyboard reaches it | `lepton-show-flatscreen` marker |
| Hide Android navigation bar (2D, on by default) | Removes Android's back / home / recents bar | `qemu.hw.mainkeys=1` boot property |

**For games ported with FramePort (FrameBridge adapter)**

| Setting | Values | FrameBridge key |
| :--- | :--- | :--- |
| Hand input | Automatic, Controllers, Hands | `controller_fix` |
| Resolution scale | 0.5x - 2.0x | `scale` |
| Refresh rate | Game's choice, 72, 80, 90, 96, 108, 120, 144 Hz | `refresh_rate` |
| Vibration strength | 0 - 1 | `haptic_scale` |
| Turn off space warp | on / off | `hide_space_warp` |
| Keep the play space still | on / off | `stable_local` |

FrameLoad writes only the keys whose value differs from the adapter's default into `settings.conf` and `framebridge.conf`, and leaves every other line of those files alone. For an APK without the adapter these controls are greyed out, because nothing would read them.

**Presets:** *Game defaults*, *Sharper* (1.3x), *120 Hz*, *Battery saver* (0.85x at 72 Hz). A preset sets scale, refresh rate and foveation and keeps everything else. As with any saved value, the game keeps only the preset values that differ from the defaults: with the built-in defaults, *Sharper* stores just the scale, and the game still follows the default refresh rate.

**What is deliberately not here:** Lepton writes its own Android system properties (`ro.product.model=Lepton`) and offers no per-game override. So a launcher cannot spoof a Quest model, force MSAA or anisotropic filtering, or set CPU/GPU levels. Earlier FrameLoad versions showed such controls; they changed nothing and were removed in v1.3.2.

### Porting a Quest game

There is no setup step. Shortly after FrameLoad starts on a Steam Frame, it downloads the porting tools in the background, once (about 310 MB on disk in total):
- FramePort's command line, into `~/.local/share/frameload/frameport-venv`
- a Java runtime, OVRPort and apksigner, into `~/.local/share/frameload/frameport-home`

It checks weekly for a newer FramePort, because that is where per-game fixes arrive.

1. **Start a port.** Install a Quest game, or press **Port & Play** on one that is already in your library. If it was built for Meta's runtime, it is ported right after it is installed, or before it starts.
2. **Follow it, or don't.** The dialog shows a progress bar and the step the port is on, with FramePort's own output behind **Show Details**. A big game takes several minutes.
   - You can close the dialog with **Run in Background**: the port keeps going, and its progress stays on screen (a chip in the header, or the look's status area).
   - A game you pressed Port & Play on starts by itself when the port is done, as long as FrameLoad's window stays open.
   - If the tools are not there yet (in the first minutes after installing FrameLoad, or without a network), they are fetched first and the game is ported as soon as they are ready.
3. **If a port fails,** the game shows **Port Again**. FrameLoad does not retry it by itself until FramePort has been updated.
4. **The original APK is kept** as `unported.apk` next to the game. `frameload port <package>` ports it again by hand.

Two switches on the **Quest Game Porting** card in System turn off the automatic port and the automatic download of the tools (useful on a metered connection). With them off, nothing is ported or downloaded until you press **Port & Play** on a game or **Set Up Now** on the card; games installed before you switched it off wait until you ask for them too.

One of FramePort's dependencies cannot be installed on the Frame: it needs a C compiler, which SteamOS does not ship. So FramePort's "Unity: turn off MSAA" fix is unavailable there; everything else works. Whether a given game runs after porting is decided by FramePort's patches for it, so game-specific fixes belong in FramePort's catalog.

Command line: `frameload port --setup`, `frameload port <package>`, `frameload port --status`. To use an existing FramePort install instead, set `porting.frameport_cli` in `config.json`.

### Steam's menu over a game that just started

FrameLoad's window lives in SteamVR's dashboard, the same layer as Steam's menu. A VR game appears behind it, so until that layer is closed you stay in FrameLoad and only hear the game.

**Show &lt;game&gt;.** While a VR game runs, FrameLoad offers **Show** with the game's name:
- next to the **Stop** chip (Showcase and Daylight leave it out on the Library, where their "playing now" area has it);
- on the game's page;
- where each look shows the running game: **Show** replaces Resume in Big Picture, Showcase and Command Center, and sits beside Stop in Spatial, Neon and Daylight.

Show closes Steam's menu the way Steam's own Resume does, then checks a second later that it stayed closed. If it did not, FrameLoad says: "Steam's menu could not be closed from here. Press the Steam button on your controller." The toast after **Play** of a VR game points at it too. If the headset shows black after Show, the game itself is not drawing.

**Automatically.** When a ported game shows its first frame, its launcher closes Steam's menu by itself:
- It sees the first frame in the game's log. If Lepton stops copying that log into `launch.log` (it can, while the game keeps running), the launcher asks the game's container directly every 2 seconds.
- It stops as soon as you open the menu yourself with the controller's Steam button. Presses made while the game was still loading do not count.
- If the menu comes back ten times within 15 seconds, it gives up and the Launch Log says so.
- `dashboard.log` in the game's folder ends with one line on what happened (`result: hidden 1`, `no-frames`, `player`, `keeps-reopening` or `error ...`). The game's **Launch Log** explains it in plain words, and says when FrameLoad started the game directly because Steam had not loaded it yet.

A game that was not ported has no FrameBridge and does not report its first frame, so for it only Show helps.

**Close FrameLoad's window when a VR game shows its first picture** (System → Starting Games, off by default) closes FrameLoad's window at the game's first frame, or when Steam's menu keeps coming back. Then nothing of FrameLoad stays in front of the game. Open FrameLoad again from your Steam library: downloads, installs and ports keep running in the background, and Stop still works.

To switch the automatic closing of Steam's menu off for one game, put `FRAMELOAD_KEEP_DASHBOARD=1 %command%` in its launch options in Steam (game → Properties).

If Steam's "Exit game" does not end a game, use **Stop** in FrameLoad. That happens when FrameLoad started the game itself because Steam had not loaded its shortcut yet: the game was installed (or moved to another drive) while Steam was running. A game Steam already had in its library stays there when it is ported or updated, and starts through Steam.

### Hand tracking

The Frame does not track bare hands with its cameras. Its runtime exposes `XR_EXT_hand_tracking` with a skeleton driven by the controllers' finger sensors, so hand-tracking games are played holding the controllers. For a game ported with FramePort, the *Hand input* setting decides what the game sees:
- *Hands* passes that skeleton through.
- *Controllers* reports Touch controllers instead.
- *Automatic* chooses Hands only for games whose manifest requires hand tracking.

System → **Hand Tracking in Games** lists the games that use hands.

Playing with bare hands and no controllers is not possible today. It needs a tracker that reads the headset's cameras and feeds SteamVR, which neither Valve nor FrameLoad ships. Community projects are working on one. Because FrameLoad passes the runtime's own hand skeleton through, a game set to *Hands* should pick up such a tracker without changes here once one exists.

### When a new game is missing from Steam

Steam reads its shortcut list only when it starts. After an install, a banner shows which games are waiting.
- You can start them right away with **Play** in FrameLoad's library.
- Or press **Restart Steam Now**, which appears when FrameLoad can restart Steam safely. It closes FrameLoad's window and any running game, rewrites the shortcuts while Steam is stopped, and starts Steam again.

### Stopping a game

A running game has a **Stop** button on its card and page, and a red **Stop** chip in FrameLoad's header. Use it for any game FrameLoad started itself, because Steam only offers "exit" for games it started. From a terminal: `frameload stop` stops all running games, `frameload stop <package>` stops one.

### When a game freezes

If a game uses up the memory, or hangs with a picture that sticks to your head, the headset can stop responding entirely. The **Freeze Guard** (System tab) has three switches that work on their own, all on by default:
- **Stop a game before it runs the headset out of memory:** when the headset is about to run out, FrameLoad ends the game.
- **Limit each game's memory** so SteamVR keeps 2.5 GB.
- **Stop a game whose picture freezes** after 30 seconds (choose 15 seconds, 1 or 2 minutes). With 15 seconds a game that loads for a long time without drawing can be stopped.

How FrameLoad tells that a picture froze:
- A game ported with FramePort reports its frames about every 5 seconds. When the reports stop, FrameLoad still waits while the headset is asleep, while the Steam menu is open, and up to 2 minutes while the game is in the background. It also waits while the game keeps the graphics processor busy, for example on a loading screen.
- Other VR games are judged by their graphics work. FrameLoad only stops one when it can tell that the headset is in use and the Steam menu is closed; otherwise it tells you, and you decide whether to press **Stop**.
- 2D apps are never judged by their picture.
- With the switch off, FrameLoad still tells you when a picture has frozen.

Settings saved by v1.3.5 to v1.3.7 (off, 90 seconds) move to the new default (on, 30 seconds) once; switching it off again afterwards sticks.

The guard covers games started through FrameLoad's launcher, from FrameLoad or from Steam.

### When a game crashes or is stopped

FrameLoad opens a **What happened** window when a game:
- crashed, hung the graphics processor or ran out of memory
- was stopped by the Freeze Guard
- could not start, or closed within a minute without showing a VR picture
- was running when the headset restarted

It names the cause in plain words (for example "It crashed (SIGSEGV) in thread RenderThread, inside the headset's graphics driver (libgallium_dri.so)") and shows the log lines that say so. The window waits until no other dialog is open and no game is running. It also comes back later if FrameLoad was closed at the time, until you close it.

The window's buttons:
- **Copy Log** copies a report for a bug report or a forum post: what happened, the game and FrameLoad versions, SteamOS, Lepton, memory, the crash backtrace and the end of the log. Your home folder, host name, network and hardware addresses and Steam account ids are removed.
- **Save Log** saves the full report: on the headset to `~/Downloads`, on a phone or PC as a download.
- **Open Launch Log** shows the log of that session. FrameLoad keeps a copy, because the next start erases it.
- **Don't Show for This Game** stops the window from opening by itself for that game.

A game whose last session ended this way has a **What Happened** button on its page. Normal quits, Steam's Exit game and your own **Stop** are recorded without a window. Switch the window off under **System → Freeze Guard** ("Show what happened when a game crashes or is stopped").

### When a game does not start

Open the game and press **Launch Log**. FrameLoad reads the log of the last start and names the cause when it recognises one; the raw log is shown below it. **Copy Log** and **Save Log** hand out the same report as the What happened window. Recognised causes include:
- no launcher activity
- a rejected APK
- a game that asks for OpenXR 1.1 or for Meta's runtime
- a crash, or a hung graphics processor
- a missing microSD card, or Lepton not found
- podman running out of kernel keyrings

For everything around the game, run **System → Self-Test**, or `frameload doctor` in a terminal. It checks Lepton, podman and its keyring fix, the tools the launcher needs, your Steam library, every installed game and the porting setup. Include its output when you report a problem.

### Apps that cannot run

Some apps verify their own signing certificate when they start. Porting has to re-sign the APK, so such an app stops at its loading screen (SteamVR shows "Waiting"). FrameLoad marks the ones it knows (currently SKYBOX VR Player) as **Cannot run** and does not start them. Working around this would mean defeating the app's tamper check, which FrameLoad does not do. The same label marks apps that are 32-bit only, need a newer Android than Lepton's, or come only as split APKs.

### Opening the dashboard from another device

Requests from the headset itself are trusted. Every other device must be paired once:
- The six-digit code is shown in the headset under **System → Phone & PC Access**.
- A code is valid for five minutes, works once, and is withdrawn after five wrong tries.
- Only someone at the headset can create codes or remove paired devices.

The dashboard answers under an IP address, `localhost` and the headset's own name. To use another host name, run `frameload allow-host <name>` on the Frame; `--remove` undoes it.

### Mods and custom songs

In a game's page, under **Mods & Custom Songs**, type the path of a zip, folder or file and press **Inject**, or use `frameload inject-mod <package> <path>`. Everything goes into the game's shared storage, `lepton-data/external/Android/data/<package>/files/`:
- For Beat Saber, everything goes to `CustomSongs/<name>`.
- For other games, a zip with an `info.dat` or `.ogg`/`.egg` files goes to `CustomSongs/<name>`, anything else to `mods/<name>`.
- On the command line, `--subpath <folder>` picks another folder under `files/`.

The folders are made writable for the container. Whether a game loads them is up to the game or its mod loader.

### Save backups

**Backup Saves** on a game's page writes `~/.local/share/frameload/backups/<package>_save_<date>_<time>.tar.gz`. It holds the app's private storage (`internal/`) and its shared storage (`external/`, without OBB files).
- Uninstalling one game in the dashboard makes a backup first. The Storage tab's batch uninstall asks whether to make one. A game whose backup fails is not uninstalled: its page says why and asks before removing it without a backup, and the batch uninstall keeps it selected so you can untick the backup and try again. A game that has not saved anything yet is uninstalled without one. Windows and Linux apps keep their data in their own folder, which backups do not cover, so they are only uninstalled after that question.
- Restoring is not in the dashboard yet. To restore by hand, install the game again if it was uninstalled, make sure it is stopped, and run:

```bash
podman unshare tar -xzf ~/.local/share/frameload/backups/<file>.tar.gz -C <game folder>/lepton-data
```

The game folder is `~/Applications/quest-frame/<package>`, or `<drive>/quest-frame/<package>` for a game on a microSD card or USB drive.

---

## 🎮 Controls

| Control | Action |
| :--- | :--- |
| **Laser + trigger** | Click |
| **Laser drag** | Drag a list, page or dialog to scroll it; a flick keeps it moving |
| **Scroll arrows (right edge)** | Appear whenever a page or dialog is longer than the window: **back to top**, **up**, **down**. Tap for a step, hold to keep scrolling |
| **A** | Select (on a drop-down: the next option) |
| **B** | Back: closes the top dialog or leaves a text field |
| **X** | On a card with an action button (Browse in every look, the library in Neon and Daylight) it presses that button: Play, Download, Install, Update, Port & Play or Stop. Elsewhere it acts like A. On a text field it also opens Steam's keyboard while its auto-open switch is on |
| **Y** | Search |
| **LB / RB** | Previous / next tab |
| **LT / RT** | Page up / page down |
| **Stick click** | Back to the top |
| **D-pad / left stick** | Move the focus. The first press starts at whatever the laser points at. On a slider, left and right change its value |
| **Right stick** | Scroll whatever the laser points at, else the open dialog or the page |
| **The tab you are on** | Press it again to return to its top |
| **Keyboard** | Arrow keys move, Enter or Space selects, Esc goes back, Page Up / Page Down / Home / End scroll |

Big Picture shows the controller's buttons along the bottom. The other looks show a short button guide after you use the controller. The keyboard button next to the search box opens Steam's keyboard (Steam + X), and it can open by itself when a text field is selected (System → Steam Frame Virtual Keyboard).

If a stick or button does nothing, open **System → Controller Test**. It shows live what the controllers send to FrameLoad: gamepad axes and buttons, scroll events, and pointer presses. A browser only reports a gamepad after its first button press. Until then, the scroll arrows work with the laser alone.

---

## 💻 Command line

The installer puts a `frameload` command in `~/.local/bin`. If your shell does not find it, use the full path `~/.local/bin/frameload`.

```bash
frameload                      # open the dashboard window (starts the service if needed)
frameload --daemon             # start the background server only
frameload --kill               # stop the background server
frameload doctor               # self-test of Lepton, podman, Steam, games and porting
frameload info                 # device, Lepton, battery and storage as JSON

# Games
frameload list
frameload install <file-or-folder> [--title "Name"] [--obb <file-or-folder>] [--device <drive-id>] [--flat]
frameload launch <package>
frameload stop [<package>]                       # all running games without a package
frameload uninstall <package> [--keep-saves]     # --keep-saves: write a save backup first (stops if it fails)
frameload storage                                # drives and their ids, as JSON
frameload move <package> <internal|drive-id|folder>
frameload sync-shortcuts                         # rewrite every game's Steam shortcut, add FrameLoad's if missing (while Steam is stopped)

# Porting (FramePort)
frameload port --status
frameload port --setup
frameload port <package>

# Per-game settings
frameload tune --list                            # presets and every setting
frameload tune <package>                         # show a game's settings
frameload tune <package> --preset sharp          # default, sharp, smooth (120 Hz), battery
frameload tune <package> --scale 1.3 --refresh 90 --hands controllers --set foveation=fixed
frameload tune --batch battery                   # one preset for every installed Quest game

# Mods, links, access
frameload inject-mod <package> <zip-or-folder> [--name "Song"] [--subpath <folder>]
frameload handle-url "frameload://launch?package=<package>"
frameload allow-host <name> [--remove]

# Browse catalog
frameload sync
frameload search "<name>"

# Rarely needed
frameload serve [--host 0.0.0.0] [--port 5050]   # run the server in the foreground
frameload window [--url <url>] [--fullscreen]    # native window only (Qt WebEngine or WebKit2GTK)
frameload uninstall-app [--yes] [--purge-games] [--purge-backups]
```

`frameload --help` lists the commands (all of them except `--daemon` and `--kill`), and `frameload <command> --help` shows a command's options. Drive ids are `internal` or `ext_<name>`, as listed by `frameload storage`.

---

## 📁 Files and folders

**Program and system integration**

| Path | What is there |
| :--- | :--- |
| `~/Applications/FrameLoad/` | The program (a git checkout, or the release files) |
| `~/.config/systemd/user/frameload.service` | Background service on port 5050 |
| `~/.config/autostart/frameload.desktop` | Starts the service instead, where systemd's user bus is not available |
| `~/.local/share/applications/frameload.desktop` | Desktop entry and `frameload://` handler |
| `~/.local/bin/frameload` | The `frameload` command |
| `~/.config/containers/containers.conf` | `keyring = false` for rootless podman |
| `~/.steam/steam/userdata/<id>/config/` | Steam's `shortcuts.vdf` (FrameLoad keeps the last 5 versions as `shortcuts.vdf.backup-*`) and `grid/` artwork, named by each shortcut's id |
| `~/Documents/FrameLoad-signing-keys/` | Signing keys of ported games, saved when FrameLoad is uninstalled |
| `~/.var/app/<flatpak-id>/frameload-profile/` | Profile of FrameLoad's window in the Firefox, Chromium or Chrome Flatpak |

**FrameLoad's data: `~/.local/share/frameload/`**

| Path | What is there |
| :--- | :--- |
| `config.json` | Settings (see [Configuration](#-configuration)) |
| `paired_devices.json` | Paired phones and PCs (only hashes of their session tokens) |
| `backups/` | Save backups |
| `cache/` | Downloads in progress, porting work folders, update downloads |
| `data/` | Catalog data, cover thumbnails, and the unpacked copy of each game downloaded from Browse (kept after install; safe to delete once the game is installed) |
| `data/sessions/` | How each game's last session ended (`<package>.json`) and the logs kept from it (`<package>/`, at most about 7 MB per game; removed when the game is uninstalled) |
| `data/fdroid_cache.json`, `data/app_sources/` | The downloaded app lists of F-Droid and of the other 2D app sources (one file per source) |
| `uploads/` | Files received from a phone or PC; removed after install, and unused ones when FrameLoad starts and they are older than 24 hours |
| `frameport-venv/`, `frameport-home/` | FramePort and its tools (Java, OVRPort, apksigner, signing keys) |
| `bin/` | 7-Zip |
| `chromium-profile/`, `firefox-profile/` | Window profiles for a Chrome, Chromium or Firefox that is not a Flatpak |
| `window.lock`, `window.pid` | Held and written by `run.sh` while FrameLoad's window is open (one window at a time; a game's launcher closes it when System → Starting Games asks for that) |
| `server.log` | Server output when it runs without systemd (with systemd: `journalctl --user -u frameload`) |

**One game: `~/Applications/quest-frame/<package>/`** (on a microSD card or USB drive: `<drive>/quest-frame/<package>/`)

| Path | What is there |
| :--- | :--- |
| `launch.sh` | The launcher Steam starts |
| `deployment.json` | What FrameLoad knows about the game |
| `settings.conf` | FrameBridge settings |
| `artwork/` | Steam artwork, the APK's own icon and `artwork.json` |
| `launch.log`, `dashboard.log` | Output of the last start; `dashboard.log` ends with what became of Steam's menu over the game |
| `.last_launch` | How FrameLoad started the game last: through Steam, or directly because Steam had not loaded it |
| `.last_played`, `.playtime` | Play history |
| `.session_end`, `.launch_error` | How the last session ended (start, end, exit status), and why the launcher could not start Lepton |
| `unported.apk` | The original APK of a ported game |
| `lepton-app/` | `game.apk` and `obb/` |
| `lepton-data/` | The container's storage: `internal/<package>` (private data, most saves) and `external/` (shared storage, `Android/data/<package>/files/`) |
| `lepton-shaders/` | Shader cache |

---

## 🔧 Configuration

Almost everything is set in the dashboard. FrameLoad keeps its settings in `~/.local/share/frameload/config.json`. The running server writes this file back whenever a setting changes, so stop it before editing by hand (`frameload --kill`) and start it again afterwards (`frameload --daemon`).

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `ui.skin` / `ui.daylight` | `"a"` / `"light"` | The look (`a`-`f`) and Daylight's mode (System → Appearance) |
| `ui.close_on_vr_start` | `false` | Close FrameLoad's window when a VR game shows its first picture (System → Starting Games) |
| `app_sources.disabled` | `[]` | 2D app sources hidden from Browse (Browse → Sources → Show in Browse) |
| `app_sources.custom` | `[]` | Repositories you added: `id`, `name`, `url`, `fingerprint` (the SHA-256 of the key their app list must be signed with) and `added` |
| `app_sources.order` | `["fdroid", "izzyondroid", "guardian"]` | Order of the sources; an app listed by several sources is shown from the first one in **All sources** unless it is installed from another |
| `porting.auto` | `true` | Port Quest games automatically after installing them |
| `porting.auto_setup` | `true` | Download and update the porting tools automatically |
| `porting.frameport_cli` | `""` | Use this FramePort executable instead of FrameLoad's own copy (a path, or a list such as `["python3", "-m", "frameport"]`) |
| `guard.enabled`, `guard.memory_limit` | `true` | Freeze Guard's memory watchdog and its memory limit |
| `guard.stop_frozen`, `guard.frozen_seconds` | `true`, `30` | Stop a game whose picture froze, and after how long (15, 30, 60 or 120 s) |
| `guard.report_crashes` | `true` | Open "What happened" when a game crashes or is stopped |
| `power.keep_awake_busy` | `true` | Stay awake while downloading, installing or porting |
| `storage.default_device_id` | `"internal"` | Drive new games go to |
| `server.allowed_hosts` | `[]` | Extra host names (`frameload allow-host`) |
| `download.delete_cache_after_install` | `true` | Delete a download once it is installed |
| `game_defaults` | `{}` | Default per-game settings (System → Default Game Settings) |

**Environment variables**

| Variable | Effect |
| :--- | :--- |
| `FRAMELOAD_INSTALL_DIR` | Where the one-line installer and `frameload-installer.sh` put FrameLoad |
| `FRAMELOAD_PORT` | Port the `frameload` command uses to start and open the server (default 5050; the service itself always uses 5050) |
| `FRAMELOAD_WINDOW` | `kiosk` or `normal`, for a Firefox window |
| `FRAMELOAD_KEEP_DASHBOARD=1 %command%` | As a game's Steam launch options: leave Steam's menu open when the game starts |

---

## 🖼️ FrameLoad in your Steam library

FrameLoad adds itself to Steam with its own artwork:

| Poster (`600x900`) | Banner (`920x430`) | Icon (`512x512`) |
|:---:|:---:|:---:|
| ![Poster](docs/images/steam/poster.png) | ![Banner](docs/images/steam/banner.png) | ![Icon](docs/images/steam/icon.png) |

![Hero](docs/images/steam/hero.png)

If FrameLoad is missing from your Steam library, **Restart Steam Now** in the dashboard (shown while new games are waiting) adds its shortcut back together with the games'. So does `frameload sync-shortcuts` run while Steam is stopped, or running `bash ~/Applications/FrameLoad/install.sh` again. A FrameLoad tile you renamed or gave other pictures in Steam is left as it is.

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

GPL-3.0, see [LICENSE](LICENSE). On-headset porting runs [FramePort](https://github.com/spoopyghosty0/frameport) (GPL-3.0), which FrameLoad downloads by itself; the game folder layout follows FramePort's, so both tools can manage the same library. Not affiliated with Valve or Meta.
