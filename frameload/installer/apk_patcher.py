"""APK inspection and compatibility patching for Steam Frame Lepton container."""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ApkAnalysis:
    package_name: str
    version_name: str
    version_code: str
    is_vr: bool
    engine: str
    abi: str
    libs: List[str]
    has_openxr: bool
    has_ovrplugin: bool
    has_vrapi: bool
    recommended_settings: Dict[str, Any]


class ApkPatcher:
    @staticmethod
    def inspect(apk_path: str) -> ApkAnalysis:
        """Inspects an APK file to determine package metadata, engine, and VR requirements."""
        if not os.path.isfile(apk_path):
            raise FileNotFoundError(f"APK not found at {apk_path}")

        libs: List[str] = []
        is_vr = False
        engine = "Unknown"
        abi = "arm64-v8a"
        pkg_name = ""
        version_code = "1"
        version_name = "1.0"

        with zipfile.ZipFile(apk_path, "r") as zf:
            namelist = zf.namelist()

            # Find ABI and native libraries
            for name in namelist:
                if name.startswith("lib/"):
                    parts = name.split("/")
                    if len(parts) >= 3 and parts[2].endswith(".so"):
                        libs.append(parts[2])
                        if parts[1] in ("arm64-v8a", "armeabi-v7a"):
                            abi = parts[1]

            # Detect engine
            lib_set = set(libs)
            if "libil2cpp.so" in lib_set or "libunity.so" in lib_set:
                engine = "Unity"
            elif "libUE4.so" in lib_set or "libUnreal.so" in lib_set or any("Unreal" in x for x in namelist):
                engine = "Unreal"
            elif "libgodot_android.so" in lib_set:
                engine = "Godot"
            elif libs:
                engine = "Native C++"

            # Detect VR
            has_openxr = any("openxr" in x.lower() for x in lib_set)
            has_ovrplugin = "libOVRPlugin.so" in lib_set
            has_vrapi = "libvrapi.so" in lib_set

            if has_openxr or has_ovrplugin or has_vrapi:
                is_vr = True

            # Inspect AndroidManifest.xml strings
            if "AndroidManifest.xml" in namelist:
                raw_manifest = zf.read("AndroidManifest.xml")
                # Manifest binary XML string scan
                text_bytes = raw_manifest.decode("latin1", errors="replace")
                if "com.oculus.intent.category.VR" in text_bytes or "vr_only" in text_bytes:
                    is_vr = True

                # Extract package name via regex search on printable chunks
                pkg_match = re.search(r"package[\x00-\x1f]+([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)", text_bytes)
                if pkg_match:
                    pkg_name = pkg_match.group(1)

        # Fallback package name from filename if not found in manifest
        if not pkg_name:
            base = os.path.basename(apk_path).replace(".apk", "")
            # If named like com.something.app
            if "." in base:
                pkg_name = base
            else:
                pkg_name = f"com.steamframe.{base.lower().replace('-', '_')}"

        recommended = {
            "refresh_rate": 90,
            "resolution_scale": 1.0,
            "controller_models": 1 if is_vr else 0,
            "passthrough": 1 if is_vr else 0,
            "msaa": 2 if is_vr else 0,
        }

        return ApkAnalysis(
            package_name=pkg_name,
            version_name=version_name,
            version_code=version_code,
            is_vr=is_vr,
            engine=engine,
            abi=abi,
            libs=list(set(libs)),
            has_openxr=has_openxr,
            has_ovrplugin=has_ovrplugin,
            has_vrapi=has_vrapi,
            recommended_settings=recommended,
        )

    @staticmethod
    def generate_settings_conf(settings: Dict[str, Any], output_path: str) -> None:
        """Writes FrameBridge settings.conf for the game."""
        lines = []
        for k, v in settings.items():
            lines.append(f"{k}={v}")
        content = "\n".join(lines) + "\n"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
