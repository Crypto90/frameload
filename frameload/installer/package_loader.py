"""Universal package and archive loader supporting APK, XAPK, APKS, ZIP bundles, and loose directories."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional

from ..config import CACHE_DIR
from .apk_patcher import ApkPatcher
from .lepton_quest import LeptonInstaller
from .linux_native import LinuxNativeInstaller
from .windows_proton import WindowsProtonInstaller


class PackageLoader:
    @staticmethod
    def inspect_source(source_path: str) -> Dict[str, Any]:
        """Inspects any input source: Android APK/XAPK/APKS, Windows EXE/Directory, Linux AppImage/ELF, or ZIP."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")

        if os.path.isdir(source_path):
            return PackageLoader._inspect_directory(source_path)

        ext = os.path.splitext(source_path)[1].lower()
        if ext in (".xapk", ".apks", ".zip"):
            return PackageLoader._inspect_archive(source_path, ext)
        elif ext == ".apk":
            return PackageLoader._inspect_single_apk(source_path)
        elif ext == ".exe":
            return WindowsProtonInstaller.inspect_windows_source(source_path)
        elif ext in (".appimage", ".sh"):
            return LinuxNativeInstaller.inspect_linux_source(source_path)
        else:
            # Check for ELF binary
            try:
                with open(source_path, "rb") as f:
                    magic = f.read(4)
                    if magic == b"\x7fELF":
                        return LinuxNativeInstaller.inspect_linux_source(source_path)
            except OSError:
                pass
            raise ValueError(f"Unsupported file format: {ext} (supported: .apk, .xapk, .apks, .zip, .exe, .AppImage, .sh, or folder)")

    @staticmethod
    def _inspect_directory(dir_path: str) -> Dict[str, Any]:
        """Scans a loose directory (e.g. from USB drive or MicroSD card) for Android, Windows, or Linux apps."""
        apks = []
        obbs = []
        obb_dirs = []
        exes = []
        linux_bins = []

        for root, dirs, files in os.walk(dir_path):
            for f in files:
                lower = f.lower()
                full = os.path.join(root, f)
                if lower.endswith(".apk"):
                    apks.append(full)
                elif lower.endswith(".obb"):
                    obbs.append(full)
                elif lower.endswith(".exe"):
                    exes.append(full)
                elif lower.endswith(".appimage") or (os.access(full, os.X_OK) and "." not in f):
                    linux_bins.append(full)
            for d in dirs:
                if d.startswith("com.") and ("." in d):
                    obb_dirs.append(os.path.join(root, d))

        if not apks:
            if exes:
                return WindowsProtonInstaller.inspect_windows_source(dir_path)
            elif linux_bins:
                return LinuxNativeInstaller.inspect_linux_source(dir_path)
            raise FileNotFoundError(f"No installable APK, EXE, or Linux executables found inside directory {dir_path}")

        # Find primary APK: preference for base.apk or largest apk
        primary_apk = None
        for a in apks:
            bname = os.path.basename(a).lower()
            if bname in ("base.apk", "game.apk"):
                primary_apk = a
                break
        if not primary_apk:
            # Pick largest APK
            primary_apk = max(apks, key=os.path.getsize)

        analysis = ApkPatcher.inspect(primary_apk)
        pkg = analysis.package_name

        # Detect matching OBB directory or file
        matched_obb: Optional[str] = None
        # 1. Check if a directory named after the package exists
        for od in obb_dirs:
            if os.path.basename(od) == pkg:
                matched_obb = od
                break
        # 2. Check if an Android/obb/<pkg> exists
        if not matched_obb:
            std_obb = os.path.join(dir_path, "Android", "obb", pkg)
            if os.path.isdir(std_obb):
                matched_obb = std_obb
            elif os.path.isdir(os.path.join(dir_path, "obb", pkg)):
                matched_obb = os.path.join(dir_path, "obb", pkg)

        # 3. Check loose obb files
        if not matched_obb and obbs:
            for o in obbs:
                if pkg in os.path.basename(o):
                    matched_obb = o
                    break
            if not matched_obb:
                matched_obb = obbs[0]

        folder_name = os.path.basename(dir_path.rstrip("/"))
        title = folder_name.replace("_", " ").replace("-", " ")
        if "." in title and title.startswith("com."):
            parts = title.split(".")
            title = parts[-1].capitalize()

        return {
            "source_type": "directory",
            "path": dir_path,
            "package_name": pkg,
            "title": title,
            "is_vr": analysis.is_vr,
            "engine": analysis.engine,
            "primary_apk": primary_apk,
            "all_apks": apks,
            "matched_obb": matched_obb,
            "has_obb": matched_obb is not None,
            "obb_count": len(obbs),
            "size_bytes": sum(os.path.getsize(a) for a in apks) + (sum(os.path.getsize(o) for o in obbs) if obbs else 0),
        }

    @staticmethod
    def _inspect_archive(archive_path: str, ext: str) -> Dict[str, Any]:
        """Inspects an XAPK, APKS, or ZIP archive without full extraction."""
        with zipfile.ZipFile(archive_path, "r") as zf:
            namelist = zf.namelist()
            manifest_info = {}
            if "manifest.json" in namelist:
                try:
                    raw = zf.read("manifest.json")
                    manifest_info = json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    pass

            pkg_name = manifest_info.get("package_name") or manifest_info.get("package")
            title = manifest_info.get("name") or manifest_info.get("title")

            apk_entries = [n for n in namelist if n.lower().endswith(".apk")]
            obb_entries = [n for n in namelist if n.lower().endswith(".obb")]

            if not apk_entries:
                exe_entries = [n for n in namelist if n.lower().endswith(".exe")]
                linux_entries = [n for n in namelist if n.lower().endswith(".appimage")]
                if exe_entries:
                    bname = os.path.basename(archive_path).replace(ext, "").replace("_", " ")
                    clean_id = re.sub(r"[^a-zA-Z0-9_]", "", bname.lower().replace(" ", "_"))
                    return {
                        "source_type": "archive_windows",
                        "path": archive_path,
                        "package_name": f"win.{clean_id}",
                        "title": bname,
                        "is_vr": any("openxr" in n.lower() or "openvr" in n.lower() for n in namelist),
                        "runtime": "proton",
                        "primary_exe": exe_entries[0],
                        "size_bytes": os.path.getsize(archive_path)
                    }
                elif linux_entries:
                    bname = os.path.basename(archive_path).replace(ext, "").replace("_", " ")
                    clean_id = re.sub(r"[^a-zA-Z0-9_]", "", bname.lower().replace(" ", "_"))
                    return {
                        "source_type": "archive_linux",
                        "path": archive_path,
                        "package_name": f"linux.{clean_id}",
                        "title": bname,
                        "is_vr": any("openxr" in n.lower() for n in namelist),
                        "runtime": "linux_native",
                        "primary_bin": linux_entries[0],
                        "size_bytes": os.path.getsize(archive_path)
                    }
                raise ValueError(f"Archive {archive_path} contains no installable .apk, .exe, or Linux executables")

            # Determine primary apk entry inside archive
            primary_entry = None
            for e in apk_entries:
                base = os.path.basename(e).lower()
                if base in ("base.apk", "game.apk") or (pkg_name and f"{pkg_name}.apk" in base):
                    primary_entry = e
                    break
            if not primary_entry:
                # Largest apk in zip
                primary_entry = max(apk_entries, key=lambda n: zf.getinfo(n).file_size)

            # Read sample bytes from primary apk to determine package & VR
            is_vr = False
            engine = "Unknown"
            if not pkg_name:
                base_name = os.path.basename(archive_path)
                pkg_match = re.search(r"([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+){2,})", base_name)
                if pkg_match:
                    pkg_name = pkg_match.group(1)
                else:
                    pkg_name = os.path.splitext(base_name)[0]

            if not title:
                title = os.path.splitext(os.path.basename(archive_path))[0].replace("_", " ").replace("-", " ")

            return {
                "source_type": "archive",
                "format": ext.lstrip("."),
                "path": archive_path,
                "package_name": pkg_name,
                "title": title,
                "is_vr": is_vr or True,  # Default VR for Quest packages
                "engine": engine,
                "primary_entry": primary_entry,
                "apk_entries": apk_entries,
                "obb_entries": obb_entries,
                "has_obb": len(obb_entries) > 0,
                "size_bytes": os.path.getsize(archive_path),
            }

    @staticmethod
    def _inspect_single_apk(apk_path: str) -> Dict[str, Any]:
        """Inspects a single APK and checks for adjacent OBB files or folders."""
        analysis = ApkPatcher.inspect(apk_path)
        pkg = analysis.package_name

        # Look for adjacent OBB
        dir_name = os.path.dirname(os.path.abspath(apk_path))
        base_no_ext = os.path.splitext(apk_path)[0]

        matched_obb: Optional[str] = None
        # Check <path>/<pkg>/
        candidate_dir = os.path.join(dir_name, pkg)
        if os.path.isdir(candidate_dir):
            matched_obb = candidate_dir
        # Check <path>/Android/obb/<pkg>/
        elif os.path.isdir(os.path.join(dir_name, "Android", "obb", pkg)):
            matched_obb = os.path.join(dir_name, "Android", "obb", pkg)
        # Check <base_no_ext>.obb
        elif os.path.isfile(f"{base_no_ext}.obb"):
            matched_obb = f"{base_no_ext}.obb"

        title = os.path.basename(apk_path).replace(".apk", "").replace("_", " ")

        return {
            "source_type": "apk",
            "path": apk_path,
            "package_name": pkg,
            "title": title,
            "is_vr": analysis.is_vr,
            "engine": analysis.engine,
            "primary_apk": apk_path,
            "matched_obb": matched_obb,
            "has_obb": matched_obb is not None,
            "size_bytes": os.path.getsize(apk_path),
        }

    @staticmethod
    def install_source(
        source_path: str,
        title: str = "",
        obb_path: Optional[str] = None,
        device_id: Optional[str] = None,
        force_flat: Optional[bool] = None,
        window_preset: Optional[str] = None,
        custom_settings: Optional[Dict[str, Any]] = None,
        target_anchor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Installs any supported source (APK, XAPK, APKS, ZIP, Windows EXE, or Linux AppImage) to SSD or MicroSD."""
        source_info = PackageLoader.inspect_source(source_path)
        pkg = source_info["package_name"]
        final_title = title or source_info.get("title", pkg)
        runtime = source_info.get("runtime", "lepton")

        # 1. Route Windows applications & PCVR to Proton runner
        if runtime == "proton" or source_info.get("source_type") in ("windows_exe", "windows_dir"):
            return WindowsProtonInstaller.install_windows_app(
                source_path=source_path,
                title=final_title,
                force_vr=not force_flat if force_flat is not None else None,
                device_id=device_id,
                target_anchor=target_anchor,
            )

        # 2. Route Native Linux applications & AppImages
        if runtime == "linux_native" or source_info.get("source_type") in ("linux_appimage", "linux_elf", "linux_script"):
            return LinuxNativeInstaller.install_linux_app(
                source_path=source_path,
                title=final_title,
                force_vr=not force_flat if force_flat is not None else None,
                device_id=device_id,
                target_anchor=target_anchor,
            )

        # 3. Route Windows ZIP Archives
        if source_info.get("source_type") == "archive_windows":
            staging_dir = tempfile.mkdtemp(prefix="frameload_win_", dir=CACHE_DIR if os.path.isdir(CACHE_DIR) else None)
            try:
                with zipfile.ZipFile(source_path, "r") as zf:
                    zf.extractall(staging_dir)
                res = WindowsProtonInstaller.install_windows_app(
                    source_path=staging_dir,
                    title=final_title,
                    force_vr=not force_flat if force_flat is not None else None,
                    device_id=device_id,
                    target_anchor=target_anchor,
                )
                res["extracted_from"] = source_path
                return res
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        # 4. Route Linux ZIP Archives
        if source_info.get("source_type") == "archive_linux":
            staging_dir = tempfile.mkdtemp(prefix="frameload_lin_", dir=CACHE_DIR if os.path.isdir(CACHE_DIR) else None)
            try:
                with zipfile.ZipFile(source_path, "r") as zf:
                    zf.extractall(staging_dir)
                res = LinuxNativeInstaller.install_linux_app(
                    source_path=staging_dir,
                    title=final_title,
                    force_vr=not force_flat if force_flat is not None else None,
                    device_id=device_id,
                    target_anchor=target_anchor,
                )
                res["extracted_from"] = source_path
                return res
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        # 5. Handle loose Android Directory
        if source_info["source_type"] == "directory":
            primary_apk = source_info["primary_apk"]
            chosen_obb = obb_path or source_info.get("matched_obb")
            return LeptonInstaller.install_quest_game(
                package_name=pkg,
                title=final_title,
                apk_path=primary_apk,
                obb_path=chosen_obb,
                custom_settings=custom_settings,
                force_flat=force_flat,
                window_preset=window_preset,
                device_id=device_id,
                target_anchor=target_anchor,
            )

        # 6. Handle Android Archive (.xapk, .apks, .zip)
        elif source_info["source_type"] == "archive":
            staging_dir = tempfile.mkdtemp(prefix="frameload_pkg_", dir=CACHE_DIR if os.path.isdir(CACHE_DIR) else None)
            try:
                with zipfile.ZipFile(source_path, "r") as zf:
                    zf.extractall(staging_dir)

                # Re-inspect extracted folder
                extracted_info = PackageLoader._inspect_directory(staging_dir)
                primary_apk = extracted_info["primary_apk"]
                chosen_obb = obb_path or extracted_info.get("matched_obb")
                actual_pkg = extracted_info.get("package_name") or pkg

                res = LeptonInstaller.install_quest_game(
                    package_name=actual_pkg,
                    title=final_title,
                    apk_path=primary_apk,
                    obb_path=chosen_obb,
                    custom_settings=custom_settings,
                    force_flat=force_flat,
                    window_preset=window_preset,
                    device_id=device_id,
                    target_anchor=target_anchor,
                )
                res["extracted_from"] = source_path
                return res
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        # 7. Handle single Android APK
        else:
            primary_apk = source_info["primary_apk"]
            chosen_obb = obb_path or source_info.get("matched_obb")
            return LeptonInstaller.install_quest_game(
                package_name=pkg,
                title=final_title,
                apk_path=primary_apk,
                obb_path=chosen_obb,
                custom_settings=custom_settings,
                force_flat=force_flat,
                window_preset=window_preset,
                device_id=device_id,
                target_anchor=target_anchor,
            )
