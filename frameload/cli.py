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


def send_link_to_server(url: str) -> dict:
    """Hands a frameload:// link to the running dashboard server, which asks the user to confirm it."""
    import urllib.request
    from .config import Config

    port = Config.get()["server"].get("port", 5050)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/system/protocol", data=json.dumps({"url": url}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"success": False, "error": f"FrameLoad is not running ({exc}). Start it and open the link again."}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].startswith("frameload://"):
        print(json.dumps(send_link_to_server(sys.argv[1]), indent=2))
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

    subparsers.add_parser("doctor", help="Check that this Steam Frame has everything FrameLoad needs")
    subparsers.add_parser("sync-shortcuts", help="Write the Steam shortcut of every installed game again")

    host_parser = subparsers.add_parser("allow-host", help="Let the dashboard be opened under an extra host name")
    host_parser.add_argument("name", help="Host name, e.g. frame.home.arpa")
    host_parser.add_argument("--remove", action="store_true", help="Remove the name again")

    port_parser = subparsers.add_parser("port", help="Port an installed Quest game for the Steam Frame with FramePort")
    port_parser.add_argument("package", nargs="?", default="", help="Package name of the installed game")
    port_parser.add_argument("--setup", action="store_true", help="Install FramePort's command line and its tools")
    port_parser.add_argument("--status", action="store_true", help="Show whether porting is set up")

    # Per-game Lepton / FrameBridge settings
    tune_parser = subparsers.add_parser("tune", help="Per-game settings: hand input, resolution scale, refresh rate, foveation")
    tune_parser.add_argument("package", nargs="?", default="", help="Package name of the game")
    tune_parser.add_argument("--preset", help="Apply a named preset (default, sharp, smooth, battery)")
    tune_parser.add_argument("--set", action="append", metavar="KEY=VALUE", help="Set one setting (repeatable); see --list")
    tune_parser.add_argument("--scale", type=float, help="Resolution scale, 0.5-2.0 (FramePort-ported games)")
    tune_parser.add_argument("--refresh", type=int, choices=[0, 72, 80, 90, 96, 108, 120, 144], help="Refresh rate in Hz, 0 = game's choice")
    tune_parser.add_argument("--hands", choices=["auto", "controllers", "hands"], help="Hand input mode")
    tune_parser.add_argument("--batch", help="Apply a named preset to all installed Quest games")
    tune_parser.add_argument("--list", action="store_true", help="List presets and settings")

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
                force_flat=args.flat or None,
            )
            if res.get("success"):
                print_ok("Installation complete!")
            else:
                print_err(f"Installation failed: {res.get('error', 'Unknown error')}")
            print(json.dumps(res, indent=2))
            if res.get("success"):
                from .installer import porting
                if porting.needs_port(res) and porting.is_auto():
                    ready = porting.status()
                    if ready["installed"] and ready["tools_ready"]:
                        print_info("This game was built for Meta's runtime. Porting it for the Steam Frame...")
                        ported = porting.port_installed_game(res["package"], print)
                        print_ok(f"{ported['title']}: {ported['compat'].get('label', '')}")
                    else:
                        porting.auto_port(res)
                        print_info("This game needs porting before it starts. Run: frameload port --setup")
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
            res = send_link_to_server(args.url)
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
        elif args.command == "sync-shortcuts":
            from .system.steam_session import resync_shortcuts
            print_ok(f"Wrote {resync_shortcuts()} Steam shortcut(s).")
        elif args.command == "doctor":
            from .system.doctor import format_report, run_checks
            report = run_checks()
            print(format_report(report))
            sys.exit(1 if report["state"] == "fail" else 0)
        elif args.command == "allow-host":
            from .config import Config
            cfg = Config.get()
            server_cfg = dict(cfg["server"])
            hosts = [h for h in server_cfg.get("allowed_hosts", []) if h != args.name.lower()]
            if not args.remove:
                hosts.append(args.name.lower())
            server_cfg["allowed_hosts"] = hosts
            cfg["server"] = server_cfg
            print_ok("Allowed host names: " + (", ".join(hosts) or "(none besides this machine's own)"))
        elif args.command == "port":
            from .installer import porting
            if args.status or not (args.setup or args.package):
                print(json.dumps(porting.status(), indent=2))
                return
            if args.setup:
                porting.setup_and_port_pending(print)
                print_ok("FramePort is ready.")
            if args.package:
                res = porting.port_installed_game(args.package, print)
                print_ok(f"{res['title']}: {res['compat'].get('label', '')}")
        elif args.command == "window":
            from .web.window import main as window_main
            window_main()
        elif args.command == "tune":
            if args.list:
                print_ok("Presets:")
                for pid, p in TuningManager.get_presets().items():
                    print(f"  {pid}: {p['name']} - {p['description']}")
                print_ok("Settings (frameload tune <package> --set key=value):")
                for spec in TuningManager.get_schema():
                    note = " [FramePort-ported games only]" if spec["needs_framebridge"] else ""
                    print(f"  {spec['key']} (default {spec['default']}){note}: {spec['description']}")
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
            for pair in args.set or []:
                key, sep, value = pair.partition("=")
                if not sep:
                    print_err(f"Expected key=value, got: {pair}")
                    sys.exit(1)
                overrides[key.strip()] = value.strip()
            if args.scale is not None: overrides["scale"] = args.scale
            if args.refresh is not None: overrides["refresh_rate"] = args.refresh
            if args.hands: overrides["hand_input"] = args.hands

            if overrides:
                print_info(f"Applying custom tuning overrides to {args.package}...")
                res = TuningManager.save_game_tuning(args.package, overrides)
                print_ok("Settings saved and launch script updated!")
                print(json.dumps(res, indent=2))
            else:
                res = TuningManager.get_game_tuning(args.package)
                print_ok(f"Current settings for {args.package}:")
                print(json.dumps(res, indent=2))
    except Exception as exc:
        print_err(f"Operation failed with error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
