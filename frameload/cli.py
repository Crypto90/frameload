"""Command line interface for FrameLoad."""
from __future__ import annotations

import argparse
import json
import sys

from .catalog.vrp_mirror import VrpMirror
from .installer.apk_patcher import ApkPatcher
from .installer.lepton_quest import LeptonInstaller
from .manager.installed import InstalledManager
from .manager.launcher import GameLauncher
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
    subparsers.add_parser("list", help="List all installed games on the Steam Frame")

    # Sync
    subparsers.add_parser("sync", help="Synchronize the VR games catalog from mirror")

    # Search
    search_parser = subparsers.add_parser("search", help="Search the game catalog")
    search_parser.add_argument("query", help="Search query (name or package)")

    # Install local APK
    install_parser = subparsers.add_parser("install", help="Install an APK directly onto the Steam Frame")
    install_parser.add_argument("apk", help="Path to APK file")
    install_parser.add_argument("--title", default="", help="Custom game title")
    install_parser.add_argument("--obb", default=None, help="Path to OBB file or folder")
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
    elif args.command == "list":
        games = InstalledManager.list_installed()
        print(f"Installed games ({len(games)}):")
        for g in games:
            print(f" - {g['title']} [{g['package']}] (VR: {g['is_vr']}, AppID: {g['appid']})")
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
        title = args.title
        analysis = ApkPatcher.inspect(args.apk)
        if not title:
            title = analysis.package_name
        print(f"Installing {title} ({analysis.package_name})...")
        res = LeptonInstaller.install_quest_game(
            package_name=analysis.package_name,
            title=title,
            apk_path=args.apk,
            obb_path=args.obb,
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
