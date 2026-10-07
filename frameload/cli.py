"""Command line interface for FrameLoad."""
from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure repository root is in sys.path and package context is established
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    __package__ = "frameload"

# ANSI Color formatting for terminal outputs
RED = "\033[1;31m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[1;36m"
RESET = "\033[0m"


def color_excepthook(exc_type, exc_value, exc_traceback):
    import traceback
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    sys.stderr.write(f"{RED}{tb}{RESET}\n")

sys.excepthook = color_excepthook


def print_err(msg: str) -> None:
    sys.stderr.write(f"{RED}✖ {msg}{RESET}\n")


def print_ok(msg: str) -> None:
    print(f"{GREEN}✔ {msg}{RESET}")


def print_info(msg: str) -> None:
    print(f"{CYAN}ℹ {msg}{RESET}")


class ColorArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print_err(f"Error: {message}")
        sys.exit(2)


from .catalog.vrp_mirror import VrpMirror
from .installer.package_loader import PackageLoader
from .manager.installed import InstalledManager
from .manager.launcher import GameLauncher
from .manager.mods import ModManager
from .manager.storage import StorageManager
from .manager.tuning import TuningManager
from .manager.uninstaller import Uninstaller
from .server import run_server
from .system.protocol import ProtocolHandler
from .system.steamos import get_system_summary


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].startswith("frameload://"):
        url = sys.argv[1]
        print(f"Handling deep link URL: {url}")
        res = ProtocolHandler.handle_url(url)
        print(json.dumps(res, indent=2))
        return

    parser = ColorArgumentParser(
        prog="frameload",
        description="FrameLoad: On-device VR Sideloading, Game Management, and Installer for Steam Frame"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Serve
    serve_parser = subparsers.add_parser("serve", help="Start the FrameLoad on-device web UI and REST API")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=5050, help="Port to listen on (default: 5050)")

    # System info
    subparsers.add_parser("info", help="Display Steam Frame system, Lepton, Proton, and battery status")

    # List installed
    subparsers.add_parser("list", help="List all installed games across internal SSD and MicroSD cards")

    # Storage overview
    subparsers.add_parser("storage", help="Display storage devices (SSD, MicroSD) and telemetry")

    # Move game
    move_parser = subparsers.add_parser("move", help="Move an installed game between internal SSD and MicroSD")
    move_parser.add_argument("package", help="Package name of the game")
    move_parser.add_argument("target_device", help="Target device ID (e.g. internal, ext_microsd) or mount path")

    # Sync
    subparsers.add_parser("sync", help="Synchronize the VR games catalog from mirror")

    # Search
    search_parser = subparsers.add_parser("search", help="Search the game catalog")
    search_parser.add_argument("query", help="Search query (name or package)")

    # Install local package/folder
    install_parser = subparsers.add_parser("install", help="Install an APK, XAPK, APKS, ZIP, Windows EXE, or Linux AppImage")
    install_parser.add_argument("source", help="Path to APK, bundle, Windows EXE, AppImage, or game directory")
    install_parser.add_argument("--title", default="", help="Custom game title")
    install_parser.add_argument("--obb", default=None, help="Path to OBB file or folder")
    install_parser.add_argument("--device", default=None, help="Target storage device (e.g. internal or ext_microsd)")
    install_parser.add_argument("--flat", action="store_true", help="Force flat 2D window mode")
    install_parser.add_argument("--window-preset", choices=["tablet", "phone", "desktop", "ultrawide"], default=None, help="Window preset for flat apps")

    # Inject Mod
    mod_parser = subparsers.add_parser("inject-mod", help="Inject custom songs, mods, or DLC packs into an installed game")
    mod_parser.add_argument("package", help="Package name of the game (e.g. com.beatgames.beatsaber)")
    mod_parser.add_argument("source", help="Path to mod zip file or folder")
    mod_parser.add_argument("--name", default="", help="Custom mod/song title")
    mod_parser.add_argument("--subpath", default="", help="Custom target subpath inside game files directory")

    # Handle URL
    url_parser = subparsers.add_parser("handle-url", help="Handle frameload:// deep link URL")
    url_parser.add_argument("url", help="frameload:// URL string")

    # Launch
    launch_parser = subparsers.add_parser("launch", help="Launch an installed game")
    launch_parser.add_argument("package", help="Package name of the game")

    # Uninstall game
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a game and remove Steam shortcut")
    uninstall_parser.add_argument("package", help="Package name of the game")
    uninstall_parser.add_argument("--keep-saves", action="store_true", help="Keep save files in backup")

    # Uninstall App
    uninst_app_parser = subparsers.add_parser("uninstall-app", help="Completely uninstall FrameLoad and remove all traces from system")
    uninst_app_parser.add_argument("--purge-games", action="store_true", help="Also delete all sideloaded VR games in ~/Applications/quest-frame")
    uninst_app_parser.add_argument("--keep-backups", action="store_true", help="Preserve game save backups in ~/.local/share/frameload/backups")
    # Standalone Window
    win_parser = subparsers.add_parser("window", help="Launch FrameLoad in a standalone native desktop window")
    win_parser.add_argument("--url", default="http://127.0.0.1:5050", help="Dashboard URL")
    win_parser.add_argument("--fullscreen", action="store_true", help="Launch in fullscreen mode")

    # Steam Frame Hardware Tuning & Quest Spoofing
    tune_parser = subparsers.add_parser("tune", help="Steam Frame VR hardware tuning, Quest 3 spoofing, and supersampling")
    tune_parser.add_argument("package", nargs="?", default="", help="Package name of the game")
    tune_parser.add_argument("--preset", help="Apply a named preset (steam_frame_turbo, max_visuals, high_fps_120, battery_saver, stock_default)")
    tune_parser.add_argument("--spoof", choices=["quest3", "quest_pro", "quest3s", "quest2", "steam_frame"], help="Hardware spoof profile")
    tune_parser.add_argument("--scale", type=float, help="Resolution supersampling scale multiplier (e.g. 1.25, 1.45)")
    tune_parser.add_argument("--refresh", type=int, choices=[72, 80, 90, 120, 144], help="Display refresh rate in Hz")
    tune_parser.add_argument("--fov", choices=["dynamic", "off", "low", "medium", "high"], help="Foveated rendering mode")
    tune_parser.add_argument("--msaa", type=int, choices=[0, 2, 4], help="MSAA sample count")
    tune_parser.add_argument("--af", type=int, choices=[1, 4, 8, 16], help="Anisotropic filtering level")
    tune_parser.add_argument("--batch", help="Batch apply a named preset across all installed games")
    tune_parser.add_argument("--list", action="store_true", help="List available tuning presets and spoof profiles")

    args = parser.parse_args()

    try:
        if args.command == "serve" or args.command is None:
            host = getattr(args, "host", "0.0.0.0")
            port = getattr(args, "port", 5050)
            run_server(host=host, port=port)
        elif args.command == "info":
            info = get_system_summary()
            print(json.dumps(info, indent=2))
        elif args.command == "storage":
            overview = StorageManager.get_storage_overview()
            print(json.dumps(overview, indent=2))
        elif args.command == "move":
            print_info(f"Moving {args.package} to {args.target_device}...")
            res = StorageManager.move_game(args.package, args.target_device)
            if res.get("success"):
                print_ok("Move completed successfully.")
            else:
                print_err(f"Move failed: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
        elif args.command == "list":
            games = InstalledManager.list_installed()
            print_ok(f"Installed games ({len(games)}):")
            for g in games:
                loc = g.get("device_name", "Internal Storage")
                print(f" - {g['title']} [{g['package']}] (Location: {loc}, VR: {g['is_vr']}, AppID: {g['appid']})")
        elif args.command == "sync":
            mirror = VrpMirror()
            print_info("Synchronizing mirror catalog...")
            success = mirror.sync_catalog(status_callback=print)
            if success:
                print_ok("Done.")
            else:
                print_err("Failed to sync catalog.")
        elif args.command == "search":
            mirror = VrpMirror()
            res = mirror.search(query=args.query)
            items = res.get("items", [])
            print_ok(f"Found {res.get('total_count', 0)} results:")
            for item in items[:25]:
                print(f" - {item['name']} ({item['size_formatted']}) [{item['package_name']}]")
        elif args.command == "install":
            print_info(f"Installing from source: {args.source}...")
            res = PackageLoader.install_source(
                source_path=args.source,
                title=args.title,
                obb_path=args.obb,
                device_id=args.device,
                force_flat=args.flat,
                window_preset=args.window_preset
            )
            if res.get("success"):
                print_ok("Installation complete!")
            else:
                print_err(f"Installation failed: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
        elif args.command == "inject-mod":
            print_info(f"Injecting mod/content into {args.package}...")
            res = ModManager.inject_mod(
                package_name=args.package,
                source_path=args.source,
                mod_name=args.name,
                target_subpath=args.subpath
            )
            if res.get("success"):
                print_ok("Mod injection complete!")
            else:
                print_err(f"Mod injection failed: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
        elif args.command == "handle-url":
            print_info(f"Processing deep link URL: {args.url}...")
            res = ProtocolHandler.handle_url(args.url)
            if res.get("success"):
                print_ok("Deep link handled successfully.")
            else:
                print_err(f"Deep link error: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
        elif args.command == "launch":
            print_info(f"Launching {args.package}...")
            res = GameLauncher.launch(args.package)
            if res.get("success"):
                print_ok(f"Game {args.package} launched successfully.")
            else:
                print_err(f"Failed to launch: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
        elif args.command == "uninstall":
            print_info(f"Uninstalling {args.package}...")
            res = Uninstaller.uninstall(args.package, keep_saves=args.keep_saves)
            if res.get("success"):
                print_ok(f"Successfully uninstalled {args.package}.")
            else:
                print_err(f"Failed to uninstall: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
        elif args.command == "uninstall-app":
            if not args.yes:
                confirm = input(f"{YELLOW}⚠️  Are you sure you want to completely uninstall FrameLoad and remove all traces? [y/N]: {RESET}").strip().lower()
                if confirm not in ("y", "yes"):
                    print_info("Aborted.")
                    sys.exit(0)
            print_info("Completely removing FrameLoad and system integrations...")
            res = Uninstaller.uninstall_frameload_app(purge_games=args.purge_games, keep_backups=args.keep_backups)
            print("Uninstallation summary:", json.dumps(res, indent=2))
            print_ok("FrameLoad successfully removed from the system.")
        elif args.command == "window":
            from .web.window import main as window_main
            window_main()
        elif args.command == "tune":
            if args.list:
                print_ok("Available Steam Frame VR Tuning Presets:")
                for pid, p in TuningManager.get_presets().items():
                    print(f"  {p['icon']} {p['name']} ({pid}) [{p['badge']}]: {p['description']}")
                print_ok("\nHardware Spoofing Profiles:")
                for sid, s in TuningManager.get_spoof_profiles().items():
                    print(f"  • {s['name']} ({sid}): {s['description']}")
                return

            if args.batch:
                print_info(f"Applying preset '{args.batch}' to all installed games...")
                res = TuningManager.batch_apply(args.batch)
                print_ok(f"Applied to {res['applied_count']} of {res['total']} games.")
                print(json.dumps(res, indent=2))
                return

            if not args.package:
                print_err("Package name is required. Usage: frameload tune <package> [--preset <preset>]")
                sys.exit(1)

            if args.preset:
                print_info(f"Applying preset '{args.preset}' to {args.package}...")
                res = TuningManager.apply_preset(args.package, args.preset)
                print_ok("Tuning successfully applied!")
                print(json.dumps(res, indent=2))
                return

            overrides = {}
            if args.spoof: overrides["spoof_profile"] = args.spoof
            if args.scale is not None: overrides["resolution_scale"] = args.scale
            if args.refresh is not None: overrides["refresh_rate"] = args.refresh
            if args.fov: overrides["foveated_rendering"] = args.fov
            if args.msaa is not None: overrides["msaa"] = args.msaa
            if args.af is not None: overrides["anisotropic_filtering"] = args.af

            if overrides:
                print_info(f"Applying custom tuning overrides to {args.package}...")
                res = TuningManager.save_game_tuning(args.package, overrides)
                print_ok("Settings saved and launch script updated!")
                print(json.dumps(res, indent=2))
            else:
                res = TuningManager.get_game_tuning(args.package)
                print_ok(f"Current Steam Frame tuning profile for {args.package}:")
                print(json.dumps(res, indent=2))
    except Exception as exc:
        print_err(f"Operation failed with error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
