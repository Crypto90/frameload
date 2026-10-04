"""Command line interface for FrameLoad."""
from __future__ import annotations

import argparse
import json
import sys

from .catalog.vrp_mirror import VrpMirror
from .installer.package_loader import PackageLoader
from .manager.installed import InstalledManager
from .manager.launcher import GameLauncher
from .manager.storage import StorageManager
from .manager.uninstaller import Uninstaller
from .server import run_server
from .system.steamos import get_system_summary


def main() -> None:
    parser = argparse.ArgumentParser(
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
    install_parser = subparsers.add_parser("install", help="Install an APK, XAPK, APKS, ZIP, or folder directly onto the Steam Frame")
    install_parser.add_argument("source", help="Path to APK, .xapk bundle, or game directory")
    install_parser.add_argument("--title", default="", help="Custom game title")
    install_parser.add_argument("--obb", default=None, help="Path to OBB file or folder")
    install_parser.add_argument("--device", default=None, help="Target storage device (e.g. internal or ext_microsd)")
    install_parser.add_argument("--flat", action="store_true", help="Force flat 2D window mode")

    # Launch
    launch_parser = subparsers.add_parser("launch", help="Launch an installed game")
    launch_parser.add_argument("package", help="Package name of the game")

    # Uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a game and remove Steam shortcut")
    uninstall_parser.add_argument("package", help="Package name of the game")
    uninstall_parser.add_argument("--keep-saves", action="store_true", help="Keep save files in backup")

    args = parser.parse_args()

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
        print(f"Moving {args.package} to {args.target_device}...")
        res = StorageManager.move_game(args.package, args.target_device)
        print(json.dumps(res, indent=2))
    elif args.command == "list":
        games = InstalledManager.list_installed()
        print(f"Installed games ({len(games)}):")
        for g in games:
            loc = g.get("device_name", "Internal Storage")
            print(f" - {g['title']} [{g['package']}] (Location: {loc}, VR: {g['is_vr']}, AppID: {g['appid']})")
    elif args.command == "sync":
        mirror = VrpMirror()
        print("Synchronizing mirror catalog...")
        success = mirror.sync_catalog(status_callback=print)
        print("Done." if success else "Failed to sync catalog.")
    elif args.command == "search":
        mirror = VrpMirror()
        res = mirror.search(query=args.query)
        items = res.get("items", [])
        print(f"Found {res.get('total_count', 0)} results:")
        for item in items[:25]:
            print(f" - {item['name']} ({item['size_formatted']}) [{item['package_name']}]")
    elif args.command == "install":
        print(f"Installing from source: {args.source}...")
        res = PackageLoader.install_source(
            source_path=args.source,
            title=args.title,
            obb_path=args.obb,
            device_id=args.device,
            force_flat=args.flat
        )
        print("Installation complete:", json.dumps(res, indent=2))
    elif args.command == "launch":
        print(f"Launching {args.package}...")
        res = GameLauncher.launch(args.package)
        print(json.dumps(res, indent=2))
    elif args.command == "uninstall":
        print(f"Uninstalling {args.package}...")
        res = Uninstaller.uninstall(args.package, keep_saves=args.keep_saves)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
