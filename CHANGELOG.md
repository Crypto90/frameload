# Changelog

All notable changes to **FrameLoad** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) using 0.0.1 increments.

---

## [v1.4.2] - 2026-10-28

### Fixed
- **Games that hang the graphics processor get foveated rendering turned off.** Valve's foveation layer makes the Steam Frame's graphics processor hang in some games: Red Matter 2 hung after about 40 seconds and Epic Roller Coasters crashed in the graphics driver after 30, and both ran at a steady 72 fps for minutes once Foveated rendering was Off. When a VR game's session ends with the graphics processor hung, FrameLoad now sets that game to Foveated rendering: Off and says so in the What happened window. Games already set to Off, and games FramePort installed, are left alone.
- **Games whose Steam shortcut was lost or kept an older id did not start from Play.** FrameLoad asked Steam to start the id in its own records, which Steam ignored when its shortcut had an older id (the game was renamed), or when Steam had written its older list back on exit and dropped the shortcut (TriptoVR never started). Play now uses the id of the shortcut Steam actually has; a game whose shortcut is gone is started directly and its shortcut is written again (it is back in the library after Restart Steam).
- **"The game asks for OpenXR 1.1" was reported for games that do not.** Unity asks for OpenXR 1.1 first and continues with 1.0; the loader's line about that was taken as the failure, so Epic Roller Coasters and Rick and Morty were reported as needing OpenXR 1.1 when their data was missing.
- **New explanations in the What happened window:** "The game's data files are missing" (Unity's "RuntimeData is null" and missing OBB data), and "The app needs an Android service that Lepton does not have" (Vision Player Pro asks for NsdManager, which Lepton's Android lacks, and stops at start).
- The GPU use of a game read up to 1,900 % for a moment when FrameLoad found another of its graphics devices; that reading could keep a frozen game from being stopped for one check.

---

## [v1.4.1] - 2026-10-28

### Fixed
- **Games from the catalog were installed without their data.** Mirror releases keep a game's OBB folder beside its APK (`<release>/<package>/`), but the installer only looked for `Android/obb` and `obb`, so only the APK was installed. Games that need their data then quit at start or ran without it: Red Matter, Red Matter 2, Marvel's Iron Man VR, SWORDS of GARGANTUA, Space Pirate Trainer DX, Vampire Survivors VR, Walkabout Mini Golf, Epic Roller Coasters ("RuntimeData is null"), Rick and Morty Virtual Rick-ality and others.
  - New downloads install the whole folder, including OBB files with other names (`Audio_<lang>.obb`, `overflow1.<package>.obb`) and folders without OBB files (`files/`).
  - Games already installed get their data on the first start after the update: the left-behind folder of the installed version is moved in from FrameLoad's download folder. Nothing has to be downloaded again.
- **Extracted downloads were never deleted** and kept a second copy of every catalog game in `~/.local/share/frameload/data`. They are now removed once the game is installed (when "delete cache after install" is on, the default).
- **The Freeze Guard's memory limit never applied** on SteamOS's podman ("healthcheck-timeout must be at least 1 second"). FrameLoad now writes the limit into the game container's own cgroup when `podman update` refuses.
- A failed install after a mirror download no longer shows "Installed & Ready to Play" under the error.

---

## [v1.4.0] - 2026-10-15

### Changed
- **Free space, CPU and memory in every look.** Big Picture (the default) and Showcase showed none of them, and no look showed memory.
  - Big Picture: in the bottom bar, between the activity and the button hints. On windows narrower than 1400 px only the A and B hints stay, so nothing overlaps.
  - Showcase: in the top bar. The tabs get a row of their own below 1440 px, so they are no longer cut off.
  - Spatial: RAM joins its status dock.
  - Neon: shows RAM beside CPU. On windows narrower than 1720 px free space, CPU and RAM show as short figures and Stop drops the game's name (it stays in the tooltip, as on Show), so battery, Show, Stop, Porting and an update still share one row.
  - Command Center and Daylight: each gets a RAM figure next to CPU.
  - Pressing free space opens Storage; pressing CPU or RAM opens Performance.

### Fixed
- Neon and Daylight drew the keyboard button of the search field twice.

---

## [v1.3.9] - 2026-10-15

### Added
- **Send to GitHub.** One press in the What happened window or the Launch Log turns the game's report into a GitHub issue, so crashes found while testing games can be worked through later.
  - If the same problem of the same game version already has an open issue, the report is added to it as a comment. The same session is never sent twice.
  - If that issue was closed and the problem comes back, a new issue names the old one.
  - It needs your own GitHub token (fine-grained, Issues: read and write), pasted under **System → Crash Reports to GitHub**; FrameLoad comes with none. The token stays on the headset (readable by your user only), is sent only to GitHub and is never shown again. The buttons appear only once a token is set.
- **Reports say more about how a game started:** whether FrameLoad started it through Steam or directly, what became of Steam's menu at the start, each press of Show, and SteamVR's log of the game's OpenXR client. These are now kept with each session, because the next start overwrites them.
- `frameload doctor` (System → Self-Test) checks that Steam's interface answers on 127.0.0.1:8080, which Show and the automatic closing of Steam's menu need.

### Changed
- **Show** checks Steam's menu before and after closing it, and again three seconds later, because Steam can open it again right away.
  - When the menu cannot be closed, or comes back, FrameLoad offers to close its own window instead: the game keeps running alone in front, and FrameLoad opens again from the Steam library.
  - Pressing Show again within two minutes, when the game still cannot be seen, offers the same.
  - When Steam's interface does not answer at all, FrameLoad says so instead of the general message.
  - Every press is written to `show.log` in the game's folder.

---

## [v1.3.8] - 2026-10-15

### Added
- **"What happened" window.** When a game crashes, hangs the graphics processor, runs out of memory, cannot start, closes right after starting, or is stopped by the Freeze Guard, FrameLoad says why in plain words, for example "It crashed (SIGSEGV) in thread RenderThread, inside the headset's graphics driver". It also opens later, when you come back to FrameLoad, until you close it.
  - **Copy Log** puts a report on the clipboard: the game, its version and compatibility, the cause, the crash backtrace and the end of its log, with your home folder, network addresses and account ids removed. **Save Log** saves it to Downloads.
  - A normal quit, Steam's Exit and your own Stop open nothing. "Don't Show for This Game" and a switch on the Freeze Guard card turn the window off.
  - The game launcher now records how each session ended, and asks Lepton to keep Android's crash logs after every session (before, only after sessions under 30 seconds). Games installed earlier get the new launcher automatically.
  - The Launch Log can be copied and saved as well, and a game's page has **What Happened** after an abnormal end.
  - If the headset restarted while a game ran, FrameLoad says so the next time it opens.
- **Show <game>.** When a VR game started from FrameLoad can only be heard, FrameLoad's window (which lives in Steam's menu layer) is in front of it. A **Show** button next to Stop, and in each look's running-game area, closes Steam's menu so the game is in front.
- **Close FrameLoad's window when a VR game starts** (System → Starting Games, off by default), for when Steam keeps its menu in front.
- **More sources for 2D apps:** Browse → 2D Apps now offers F-Droid, IzzyOnDroid (about 900 apps that are not in F-Droid) and Guardian Project, all sources together, and repositories you add yourself (from the headset only, with a warning). Every app list's signature is checked against the source's key; updates come only from the source an app was installed from and only with the same signing key.
- **Phone & PC Access shows the headset's address** on your network, so it no longer has to be looked up.

### Changed
- **Freeze Guard stops a frozen game by default, after 30 seconds** (choices 15 s, 30 s, 1 min, 2 min; before: off, 90 s). Settings saved by v1.3.5-1.3.7 move to the new default once; turning it off afterwards sticks. It does not stop a game while the headset is asleep, the Steam menu is open or the game is still busy drawing (for example on a loading screen), and it now also watches VR games without FrameBridge through their graphics work (stopping those only when it knows the headset is awake and the menu closed).
- The three Freeze Guard switches work independently and say what they do, and the card shows each running game's frames, graphics load and memory limit.
- Steam's menu is closed more reliably when a ported game shows its first picture: FrameLoad also asks the game's container when Lepton stops copying the game's log, and pressing the Steam button while a game loads no longer stops it.
- The Launch Log names more causes: Lepton no longer copying the game's log, a hung graphics processor, Steam's Exit, how the game was started, and why Steam's menu was left open.
- **Updating FrameLoad waits while a game runs**: the update restarts FrameLoad's service, which could end a game FrameLoad started itself.
- When Lepton stops copying a game's log, the Freeze Guard reads its frames from the game's container, and never stops a game on missing log lines alone.

### Fixed
- **A game with a busy log looked frozen**: the Freeze Guard read old lines when more than 1 MB had piled up.
- FrameBridge's frame lines ("72.0 fps") were never recognised in the Launch Log.

---

## [v1.3.7] - 2026-10-15

### Fixed
- **Uninstalling from a terminal damaged the Steam library.** `uninstall.sh` removed every non-Steam shortcut up to FrameLoad's own, all FrameLoad games included, never removed FrameLoad's artwork, and deleted the signing keys of ported games without saving them. Piped from curl it cancelled itself at the first question. It now asks its questions on the terminal (also through a pipe) and leaves the work to FrameLoad's own uninstaller, which removes only FrameLoad's shortcut, saves the keys first and keeps them in place if that fails. Games on a drive whose name contains "FrameLoad" keep their shortcuts, also when an older FrameLoad is uninstalled this way.
- **Uninstalling in the headset (System > Clean Uninstallation) did nothing.** It stopped FrameLoad's service first, which ended the uninstall itself. The service is now disabled first and stopped last.
- **A game could be uninstalled although its save backup failed**, after the dialog had said its save data is kept. The game now stays when the backup fails or is incomplete, and its page offers "Uninstall anyway" with the reason. A game that never saved anything still uninstalls normally; Windows and Linux apps, whose data backups do not cover, are only removed after that question. The Storage tab's batch uninstall reports removed and kept games separately, keeps the kept ones selected, and counts the space of games on a microSD card or USB drive.
- **A failed self-update on a git install was reported as done**: it stashed local changes, pulled again without checking the result, and restarted on the old version. It now stops, names the local files that block the update, and leaves everything as it was.
- `frameload uninstall-app` crashed (it now has `--yes` and `--purge-backups`, and keeps save backups by default), and `frameload window` exited with an argument error.
- **Port & Play did nothing with automatic porting switched off**; it now ports the game you pressed it on (fetching the tools first if needed), and only that game: games queued while the switch was on wait until it is on again. A failed port showed as finished in the porting dialog, and one that failed right after the tool download left the dialog waiting without a word.
- **Install links went around the dashboard's checks:** `frameload://launch` started apps that cannot run and games that still need porting; it now refuses the first and ports the second first, as far as the automatic porting switches allow. A confirmed `frameload://sideload` is ported like any other install and keeps the headset awake while it copies.
- **Saving a game's Settings froze every value**, so later changes under System > Default Game Settings never reached it. A game now keeps only the values that differ from the defaults; settings saved by older versions still apply.
- **Games ported or updated while Steam was running were treated as new to Steam**: FrameLoad started them itself (so Steam's Exit could not end them) and listed them as waiting for a Steam restart. Only games Steam really does not know yet count now, and FrameLoad itself is never listed.
- **Only one of a game's OBB files was installed** when a main and a patch OBB lay next to the APK; both are installed now, and an OBB of another app in the same folder is left out.
- **The Steam icon of a game with a downloaded cover was the cover**, not the app's own icon, and the shortcut could point at an icon file that did not exist. The icon now comes from the APK when it has a complete one (an adaptive icon's foreground layer alone is drawn over the app's colours); games installed earlier are redrawn by the dashboard, and WebP icons Steam cannot show are converted.
- **FrameLoad could vanish from the Steam library for good**: Steam writes back the list it read at its start, and only the installer ever wrote FrameLoad's shortcut. Restart Steam Now and `frameload sync-shortcuts` now add it back when it is missing. Neither they nor an update rename a FrameLoad tile you renamed or replace pictures you picked for it any more.
- Launch options you set for a game in Steam (such as `FRAMELOAD_KEEP_DASHBOARD=1 %command%`) are kept when FrameLoad rewrites its shortcut.
- **Installs from the Install File tab or a phone did not keep the headset awake**; they do now, like downloads and ports.
- **Reset Lepton Shader Caches only reached games on internal storage**; it now covers every drive.
- **Move Drive always moved a game to the first other drive**, even one that cannot hold games. It now asks which drive, shows each drive's free space against the game's size, and explains drives that cannot take it.
- **Moving a game left a dead tile in Steam**: a second shortcut was added for the new place and the old one stayed, with the id FrameLoad kept using. The shortcut now moves with the game and keeps its id, pictures and launch options.
- Storage cards called USB drives "SSD"; they show Internal, microSD or USB now.
- Windows and Linux apps were shown as "Lepton (Android VR)" on their page, and the System card promised Windows VR games through WineOpenXR, which FrameLoad never set up. Both now say what really happens: experimental, started with Proton or Wine.
- `install.sh` could add a second `[containers]` table to podman's `containers.conf`, which stops every container from starting; it now adds the keyring line to the existing table.
- `install.sh` installed pywebview where no app-mode browser was found; on Linux it opens no window and kept Firefox from being used. It is no longer installed or counted as a native window.

### Changed
- **README rewritten** for what FrameLoad does today, checked against the code: features, install, opening, updating, uninstalling, a guide, controller bindings, every command, files and settings.
- Messages no longer point to buttons and tabs that do not exist ("Port for Steam Frame", "Sideload", "System & Diagnostics", porting "on a PC"); the Storage menu's keyring item has the same name as the System button, and Big Picture's hint bar says what X does.
- The Storage batch bar's backup checkbox, which nothing read, is gone; the uninstall confirmation asks about the backup.
- The uninstaller also removes the autostart entry and the browser profile of FrameLoad's window, and stops a FrameLoad server that runs without systemd. The in-headset uninstall says what it removes (only FrameLoad's own Steam shortcut) and writes what it kept to the service's log; its end page is readable in every look.
- Release archives include `uninstall.sh`; `frameload --help` prints the command list.

---

## [v1.3.6] - 2026-10-14

### Added
- **Six looks for the whole dashboard**, chosen under System → Appearance and remembered on the headset:
  - **Big Picture** (the new default): looks like SteamOS, with tabs on top, Steam covers, a wide card for the game you are playing and the controller's buttons along the bottom.
  - **Spatial**: a floating glass window with the navigation beside it, the largest targets and a status bar underneath.
  - **Showcase**: the game you played last fills the screen with one big Play or Resume button; the library sits in one row below it.
  - **Neon**: the original FrameLoad look, refined.
  - **Command Center**: a sortable list of everything installed beside a detail panel, with recent games, activity and device status in a side bar.
  - **Daylight**: light and very legible, with a dark version.
  Each look arranges the library its own way; Browse, Install File, Downloads, Storage, System and every dialog follow its colours and type. The page opens directly in the saved look.
- **Fonts are bundled** with FrameLoad (about 400 KB, SIL Open Font License), so the looks work without a network.
- The storage menu (clean the download cache, reset shader caches, repair the keyring) can now be reached with the controller.

### Changed
- An installed game's page shows its wide artwork at the top, and downloads of an installed game show its own icon.
- Plain wording instead of emoji in buttons and messages (they clashed with the new looks).
- The storage sort control has one label, "Sort", and plain option names.

### Fixed
- The web server queues up to 64 waiting connections instead of 5, so a browser opening the page with a dozen parallel requests is not turned away.
- The drawn Steam artwork kept working: its canvas colours are now literal values (canvas cannot read the page's colour variables).

---

## [v1.3.5] - 2026-10-14

### Added
- **Choose where a game goes.** With more than one drive that can hold games, installing from Browse asks where to install, like Steam does: each drive with its free space, drives that cannot hold games greyed out with the reason, and "Always install here" to make it the default. Updates stay on the drive the game is on.
- **Recently Played.** The library starts with the last three games you played, with when and for how long, and can be sorted by recently played, name, install date or size. Each game's launcher records its sessions, so games started from Steam count too.
- **Freeze Guard.** When a game uses up the headset's memory everything stops responding, even the Steam button. FrameLoad now limits each game's memory (SteamVR keeps 2.5 GB), watches memory pressure while a game runs and ends the game before the headset locks up, with a notice saying which game it was. A game that stops drawing frames is reported after 90 seconds; stopping it automatically is a switch, off by default.
- **Keep Awake.** The headset is kept awake while FrameLoad downloads, installs or ports, and on request for an hour or until switched off.
- **CPU and memory in the header**, and a live Performance card (CPU, memory, swap, GPU clock, temperatures, memory pressure).
- **Store pages with screenshots and trailers** for F-Droid apps, from the apps' own metadata; a screenshot opens large.
- **Thumbnails in Downloads**, and a clear state for each download (Downloading, Unpacking, Installing, Installed, Failed) with time left.

### Changed
- **Steam artwork is drawn properly.** FrameLoad takes the app's own launcher icon from its APK (the sharpest version; for adaptive icons the foreground layer), and the dashboard draws poster, banner (now 920x430), hero, logo and icon from the icon, any downloaded cover and the title, replacing the plain colour placeholders. Games installed earlier are redrawn too.
- **Only real drives are listed:** internal storage, the microSD card and USB drives. The Frame's own system partitions no longer show up as storage.
- The Lepton chip in the header appears only when Lepton is missing.

### Fixed
- **Scrolling far down the catalog got slower and slower.** Every page load made FrameLoad check thousands of buttons in a way that laid out the whole page each time (12 s at 2,000 cards, now 4 ms), and the cards were one huge grid. The catalog now renders each loaded page as its own block that the browser skips while off screen, closed dialogs are no longer rendered, and the page background no longer repaints on every scrolled frame.
- **Opening a game's page reflowed the list behind it**: the scroll arrows' gutter disappeared while the dialog was open and the grid changed its column count.
- **FrameLoad's window could leave Firefox running, or open it a second time.** When the window closed, the launcher tried the next way of opening it. It now opens exactly one window with a Firefox profile of its own, closes it when Steam ends FrameLoad, ends when the window is closed, and does not open a second window while one is up.
- **Steam showed no artwork for a game whose shortcut was made under an older title:** grid files were named after the new title's id instead of the id the shortcut has.
- A refused request (for example an upload from a device that is not paired) reached the client as a reset connection instead of the error message.
- An outdated message after sideloading pointed to a "Set Up Porting" button that no longer exists.

---

## [v1.3.4] - 2026-10-08

### Added
- **Scroll arrows.** Whenever a page or dialog is longer than the window, three buttons appear at the right edge: back to top, up and down. A tap moves a step, holding keeps scrolling and speeds up. They need nothing but the laser pointer.
- **More ways to scroll:** the triggers page up and down, a stick click jumps to the top, the D-pad and a single stick scroll when nothing can be focused, Page Up / Page Down / Home / End work everywhere, and pressing the tab you are on returns to its top.
- **Porting shows progress.** The dialog has a progress bar, the elapsed time and the steps (reading, converting, signing, installing) instead of console output; FramePort's output is behind "Show Details" and opens by itself when something fails. A finished port offers "Play Now".
- **Porting in the background is visible:** a chip in the header shows a running job and its percentage and reopens the dialog. Jobs FrameLoad starts by itself (after an install, the first tool download) appear the same way.
- **Steam's menu no longer covers a game that just started.** When a ported game shows its first frame, the launcher closes Steam's Resume / Exit menu through Steam's own interface. A menu you open yourself is never closed; `FRAMELOAD_KEEP_DASHBOARD=1` turns it off. Existing games get the new launcher automatically.
- **Controller Test** (System tab): shows live which gamepads, sticks, buttons, scroll and pointer events reach FrameLoad.
- **Search works on the Library**, and offers to search Browse when nothing matches.

### Changed
- **Library is the first tab** and the one FrameLoad opens with. Tabs are named Library, Browse, Install File, Downloads, Storage and System; the Downloads tab shows how many are running.
- **The tab bar stays on screen** under the header while a page scrolls, and a tab always opens at its top. Reloading stays on the tab you were on.
- **Sized for a headset:** larger text, buttons and checkboxes at least 40 px tall, larger close buttons, a wider scrollbar.
- **Questions are asked inside the page** (uninstall, move, delete, reset shader caches, restart Steam) with large buttons, instead of the browser's own small dialog. Back answers "no".
- **Notifications** are larger, stay longer when they report a problem, do not stack the same message twice and close when pressed.
- **Empty lists say what to do next:** an empty library offers Browse and Install a File.
- **System tab** is ordered by how often a card is needed: Self-Test, Lepton, Porting, Hand Tracking, Phone & PC Access first.
- The header wraps onto a second line when a running game, a porting job and an update all add a chip, instead of squeezing the search box.
- Closing the porting dialog no longer stops FrameLoad from following the job, so a game queued with Port & Play still starts when its port is done.

### Fixed
- **Analog stick scrolling** only worked while the laser pointed at one particular kind of container; it now scrolls whatever is under the pointer, then the open dialog, then the page.
- **Broken cover in a game's page:** placeholders that older versions saved as `poster.png` but were really SVG are skipped, artwork is served as the type its content has, and the cover falls back correctly every time the page is opened.
- With one dialog on top of another, Back, focus and scrolling now belong to the top one.

---

## [v1.3.3] - 2026-10-08

### Changed
- **Porting needs no setup step.** On a Steam Frame, FrameLoad downloads the porting tools (FramePort, a Java runtime, OVRPort, apksigner; about 310 MB on disk) in the background shortly after it starts, and again on demand if a Quest game needs them first. A game sideloaded before the tools are ready is ported as soon as they are.
- **FramePort is kept current:** a weekly check installs a newer FramePort release, which is where per-game fixes arrive.
- **Failed downloads are retried** after six hours instead of at every start, and the porting card shows what went wrong.
- **New switch:** "Download and update the porting tools automatically" (on by default) for metered connections; "Set Up Now" fetches them on request.
- pip's download cache is no longer kept on the headset (44 MB saved).
- **Launch ports first.** Pressing Launch (now "Port & Play") on a game that needs porting ports it and then starts it. Games already in the library, and games that arrive through a download, are ported in the background as well, not only freshly sideloaded ones.
- **A failed port is remembered** and not repeated on every start or every press of Launch; "Port Again" retries, and a FramePort update retries by itself.
- **A game's buttons are at the top of its page**, above the details, so nothing has to be scrolled to in the headset.

### Added
- **Stop.** A running game gets a Stop button on its card and page, and a red "Stop <game>" chip stays in the header. A game FrameLoad starts itself (because Steam has not loaded its shortcut yet) has no exit in Steam, and a hung one could not be closed at all. `frameload stop [package]` does the same from a terminal.
- **Apps that check their own signature are recognised** (SKYBOX VR Player): they are marked "Cannot run" before any time is spent porting them, and are not started. A ported copy is signed with a different key, and such an app stays on its loading screen; getting past that would mean defeating its tamper check, which FrameLoad does not do.
- **Launch log:** names the case where a game started but never showed a VR frame.

### Fixed
- **A game that cannot run could still be launched** and then hang with SteamVR showing "Waiting".

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
