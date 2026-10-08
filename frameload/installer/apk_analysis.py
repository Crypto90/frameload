"""APK inspection for the Steam Frame: what the app is, and whether Lepton can run it as it stands.

FrameLoad does not convert Quest games itself. A game built against Meta's runtime needs porting
(OVRPort + FramePort's FrameBridge adapter, done on a PC) before it starts on the Frame; the verdict
below tells the user which case an APK is, before they install it.
"""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .axml import AxmlError, ManifestInfo, read_manifest, resolve_string_resource

# Libraries FramePort's FrameBridge adapter adds to an APK it has ported.
FRAMEBRIDGE_LIBS = ("libframe_settings.so", "libopenxr_loader_original.so")
# Lepton's newest Android image (image-14). Apps that need more cannot install.
LEPTON_MAX_SDK = 34
ARM64 = "arm64-v8a"

# Apps that verify their own signing certificate. Porting re-signs the APK, so they stop at their
# loading screen. Getting past that would mean defeating the app's tamper check, which neither
# FramePort nor FrameLoad does. Keyed by a library only that app ships (FramePort's PLAYBOOK).
SELF_SIGNATURE_CHECK_LIBS = {
    "libskybox.so": "SKYBOX VR Player",
}

READY, LIKELY, NEEDS_PORT, BLOCKED = "ready", "likely", "needs_port", "blocked"
COMPAT_LABELS = {
    READY: "Ready for Steam Frame",
    LIKELY: "Should run",
    NEEDS_PORT: "Needs porting first",
    BLOCKED: "Cannot run on Steam Frame",
}


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
    label: str = ""
    abis: List[str] = field(default_factory=list)
    framebridge: bool = False
    xr_runtime: str = "none"  # framebridge, openxr, meta, vrapi, none
    launch_activity: str = ""
    hand_tracking: str = "none"  # none, optional, required
    min_sdk: int = 0
    manifest_parsed: bool = False
    compat: Dict[str, Any] = field(default_factory=dict)
    recommended_settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("libs", None)
        return d


def _package_from_filename(apk_path: str) -> str:
    base = os.path.splitext(os.path.basename(apk_path))[0]
    match = re.search(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", base)
    if match:
        return match.group(0)
    slug = re.sub(r"[^a-z0-9_]+", "_", base.lower()).strip("_") or "app"
    return f"local.{slug}"


def _detect_engine(lib_set: set, names: List[str]) -> str:
    if {"libil2cpp.so", "libunity.so"} & lib_set:
        return "Unity"
    if {"libUE4.so", "libUnreal.so"} & lib_set or any(n.startswith("assets/UE4Game/") for n in names):
        return "Unreal"
    if any(lib.startswith("libgodot") for lib in lib_set):
        return "Godot"
    return "Native" if lib_set else "Java/Kotlin"


def _build_compat(a: ApkAnalysis, manifest: ManifestInfo, platform_sdk: bool) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []

    def issue(severity: str, code: str, message: str) -> None:
        issues.append({"severity": severity, "code": code, "message": message})

    level = READY
    if a.libs and ARM64 not in a.abis:
        level = BLOCKED
        issue("error", "abi", f"Only built for {', '.join(a.abis) or 'another CPU'}. Lepton runs 64-bit ARM (arm64-v8a) apps only.")
    if a.min_sdk > LEPTON_MAX_SDK:
        level = BLOCKED
        issue("error", "min_sdk", f"Needs Android API {a.min_sdk}; Lepton provides up to API {LEPTON_MAX_SDK}.")
    if manifest.split_required:
        level = BLOCKED
        issue("error", "splits", "This is one part of a split APK. Lepton installs a single APK, so the app needs a merged (universal) build.")

    for lib, app_name in SELF_SIGNATURE_CHECK_LIBS.items():
        if lib in a.libs and a.xr_runtime != "openxr":
            level = BLOCKED
            issue("error", "signature_check",
                  f"{app_name} checks its own signing certificate when it starts. A ported copy is signed with a "
                  "different key, so it stays on its loading screen. It cannot run on the Steam Frame.")

    if level != BLOCKED and a.is_vr:
        if a.xr_runtime == "framebridge":
            level = READY
        elif a.xr_runtime == "vrapi":
            level = NEEDS_PORT
            issue("error", "vrapi", "Uses Meta's legacy VrApi, which the Frame has no runtime for. Port it with FramePort (VrApi bridge) on a PC first.")
        elif a.xr_runtime == "meta":
            level = NEEDS_PORT
            issue("error", "meta_runtime", "Built against Meta's Quest runtime (OVRPlugin). It needs porting with FramePort / OVRPort on a PC before it starts on the Frame.")
        else:
            level = LIKELY
            issue("info", "openxr", "Native OpenXR app. The Frame's runtime accepts OpenXR 1.0; apps that request 1.1 fail to start.")

    if level != BLOCKED and a.manifest_parsed and not a.launch_activity:
        if a.xr_runtime != "framebridge":
            level = NEEDS_PORT
        where = ("its launcher entry is an activity-alias, which Lepton ignores" if manifest.alias_launcher
                 else "Quest store builds use the INFO category instead" if manifest.info_activity
                 else "it declares none")
        issue("error", "no_launcher", f"Lepton only starts an activity with the LAUNCHER category and {where}. Launching stops with \"APP_ACTIVITY is empty\" until the manifest is patched (FramePort does this).")

    if a.hand_tracking == "required":
        issue("warn", "hand_tracking", "Requires hand tracking. The Frame has no camera hand tracking; its runtime drives the hand skeleton from the controllers' finger sensors, so you play it holding the controllers.")
    elif a.hand_tracking == "optional":
        issue("info", "hand_tracking", "Supports hand tracking. On the Frame the hand skeleton is driven by the controllers' finger sensors.")
    if platform_sdk:
        issue("warn", "platform_sdk", "Uses Meta's Platform SDK. Entitlement checks, friends and cloud saves have no service to talk to on the Frame.")
    if not a.manifest_parsed:
        issue("warn", "manifest", "AndroidManifest.xml could not be read; package name and launch checks are guesses.")

    return {"level": level, "label": COMPAT_LABELS[level], "issues": issues}


def inspect_apk(apk_path: str) -> ApkAnalysis:
    """Reads an APK's manifest and native libraries and judges whether Lepton can run it."""
    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"APK not found at {apk_path}")

    manifest = ManifestInfo()
    parsed = False
    label = ""
    with zipfile.ZipFile(apk_path, "r") as zf:
        names = zf.namelist()
        libs_by_abi: Dict[str, set] = {}
        for name in names:
            parts = name.split("/")
            if len(parts) == 3 and parts[0] == "lib" and parts[2].endswith(".so"):
                libs_by_abi.setdefault(parts[1], set()).add(parts[2])

        if "AndroidManifest.xml" in names:
            try:
                manifest = read_manifest(zf.read("AndroidManifest.xml"))
                parsed = bool(manifest.package)
            except (AxmlError, KeyError, zipfile.BadZipFile):
                pass
        label = manifest.label
        if not label and manifest.label_ref and "resources.arsc" in names:
            try:
                label = resolve_string_resource(zf.read("resources.arsc"), manifest.label_ref)
            except (KeyError, zipfile.BadZipFile, MemoryError):
                pass

    abis = sorted(libs_by_abi)
    abi = ARM64 if ARM64 in libs_by_abi else (abis[0] if abis else ARM64)
    lib_set = libs_by_abi.get(abi, set())
    has_openxr = any("openxr" in lib.lower() for lib in lib_set)
    has_ovrplugin = "libOVRPlugin.so" in lib_set
    has_vrapi = "libvrapi.so" in lib_set
    framebridge = any(lib in lib_set for lib in FRAMEBRIDGE_LIBS)
    platform_sdk = any(lib.lower().startswith(("libovrplatform", "libovrplatformloader")) for lib in lib_set)

    is_vr = manifest.is_vr or has_openxr or has_ovrplugin or has_vrapi
    if framebridge:
        xr_runtime = "framebridge"
    elif has_ovrplugin:
        xr_runtime = "meta"
    elif has_vrapi and not has_openxr:
        xr_runtime = "vrapi"
    elif is_vr:
        xr_runtime = "openxr"
    else:
        xr_runtime = "none"

    analysis = ApkAnalysis(
        package_name=manifest.package or _package_from_filename(apk_path),
        version_name=manifest.version_name or "1.0",
        version_code=manifest.version_code or "1",
        is_vr=is_vr,
        engine=_detect_engine(lib_set, names),
        abi=abi,
        libs=sorted(lib_set),
        has_openxr=has_openxr,
        has_ovrplugin=has_ovrplugin,
        has_vrapi=has_vrapi,
        label=label.strip(),
        abis=abis,
        framebridge=framebridge,
        xr_runtime=xr_runtime,
        launch_activity=manifest.launch_activity,
        hand_tracking=manifest.hand_tracking if is_vr else "none",
        min_sdk=manifest.min_sdk,
        manifest_parsed=parsed,
    )
    analysis.compat = _build_compat(analysis, manifest, platform_sdk)
    return analysis


def write_conf(settings: Dict[str, Any], output_path: str) -> None:
    """Writes a key=value file (FrameBridge's settings.conf / framebridge.conf format)."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in settings.items()))
