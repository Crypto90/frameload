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


class PackageLoader:
    @staticmethod
    def inspect_source(source_path: str) -> Dict[str, Any]:
        """Inspects any input source: single APK, XAPK bundle, APKS bundle, ZIP archive, or loose folder."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")

        if os.path.isdir(source_path):
            return PackageLoader._inspect_directory(source_path)

        ext = os.path.splitext(source_path)[1].lower()
        if ext in (".xapk", ".apks", ".zip"):
            return PackageLoader._inspect_archive(source_path, ext)
        elif ext == ".apk":
            return PackageLoader._inspect_single_apk(source_path)
        else:
            raise ValueError(f"Unsupported file format: {ext} (supported: .apk, .xapk, .apks, .zip, or folder)")

    @staticmethod
    def _inspect_directory(dir_path: str) -> Dict[str, Any]:
        """Scans a loose directory (e.g. from USB drive or MicroSD card)."""
        apks = []
        obbs = []
        obb_dirs = []

        for root, dirs, files in os.walk(dir_path):
            for f in files:
                lower = f.lower()
                full = os.path.join(root, f)
                if lower.endswith(".apk"):
                    apks.append(full)
                elif lower.endswith(".obb"):
                    obbs.append(full)
            for d in dirs:
                if d.startswith("com.") and ("." in d):
                    obb_dirs.append(os.path.join(root, d))

        if not apks:
            raise FileNotFoundError(f"No .apk files found inside directory {dir_path}")

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
                raise ValueError(f"Archive {archive_path} contains no .apk files")

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
        custom_settings: Optional[Dict[str, Any]] = None,
        target_anchor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Installs any supported source (APK, XAPK, APKS, ZIP, or Directory) to Internal SSD or MicroSD."""
        source_info = PackageLoader.inspect_source(source_path)
        pkg = source_info["package_name"]
        final_title = title or source_info.get("title", pkg)

        # 1. Handle loose Directory
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
                device_id=device_id,
                target_anchor=target_anchor,
            )

        # 2. Handle Archive (.xapk, .apks, .zip)
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
                    device_id=device_id,
                    target_anchor=target_anchor,
                )
                res["extracted_from"] = source_path
                return res
            finally:
                # Clean up temporary staging files
                shutil.rmtree(staging_dir, ignore_errors=True)

        # 3. Handle single APK
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
                device_id=device_id,
                target_anchor=target_anchor,
            )
