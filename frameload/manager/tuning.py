"""Steam Frame VR Performance, Resolution, Foveation & Quest Hardware Spoofing Manager."""
from __future__ import annotations

import json
import os
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from ..config import ANCHOR_DIR, Config
from ..installer.apk_patcher import ApkPatcher
from .installed import InstalledManager

SPOOF_PROFILES: Dict[str, Dict[str, Any]] = {
    "quest3": {
        "id": "quest3",
        "name": "Meta Quest 3 (Recommended)",
        "model": "Quest 3",
        "device": "eureka",
        "manufacturer": "Meta",
        "product": "eureka",
        "headset_type": 10,
        "fingerprint": "oculus/eureka/eureka:12/SQ3A.220605.009.A1/506698000:user/release-keys",
        "description": "Unlocks 4K textures, dynamic realtime shadows, increased LOD distances, and modern shaders.",
    },
    "quest_pro": {
        "id": "quest_pro",
        "name": "Meta Quest Pro",
        "model": "Quest Pro",
        "device": "seacliff",
        "manufacturer": "Meta",
        "product": "seacliff",
        "headset_type": 9,
        "fingerprint": "oculus/seacliff/seacliff:12/SQ3A.220605.009.A1/506698000:user/release-keys",
        "description": "Enables eye-tracking & face-tracking API surface in supported titles.",
    },
    "quest3s": {
        "id": "quest3s",
        "name": "Meta Quest 3S",
        "model": "Quest 3S",
        "device": "panther",
        "manufacturer": "Meta",
        "product": "panther",
        "headset_type": 11,
        "fingerprint": "oculus/panther/panther:12/SQ3A.220605.009.A1/506698000:user/release-keys",
        "description": "Modern shader profile with balanced memory & fillrate footprint.",
    },
    "quest2": {
        "id": "quest2",
        "name": "Meta Quest 2 (Legacy)",
        "model": "Quest 2",
        "device": "hollywood",
        "manufacturer": "Oculus",
        "product": "hollywood",
        "headset_type": 8,
        "fingerprint": "oculus/hollywood/hollywood:10/QQ3A.200805.001/300000000:user/release-keys",
        "description": "Standard Quest 2 profile for maximum battery savings or legacy compatibility.",
    },
    "steam_frame": {
        "id": "steam_frame",
        "name": "Valve Steam Frame (Native)",
        "model": "Steam Frame",
        "device": "galileo",
        "manufacturer": "Valve",
        "product": "galileo",
        "headset_type": 100,
        "fingerprint": "valve/galileo/galileo:13/TF1A.220905.001/100000000:user/release-keys",
        "description": "Passes native Valve Steam Frame hardware identifier to OpenXR.",
    },
}

PRESETS: Dict[str, Dict[str, Any]] = {
    "steam_frame_turbo": {
        "id": "steam_frame_turbo",
        "name": "Steam Frame Turbo",
        "badge": "Recommended",
        "icon": "⚡",
        "description": "Quest 3 spoofing + 1.25x crisp render scale + eye-tracked foveation + 4x MSAA + 8x AF.",
        "settings": {
            "spoof_profile": "quest3",
            "resolution_scale": 1.25,
            "refresh_rate": 90,
            "foveated_rendering": "dynamic",
            "dynamic_foveation": True,
            "eye_tracking": True,
            "msaa": 4,
            "anisotropic_filtering": 8,
            "cpu_level": 4,
            "gpu_level": 4,
            "controller_models": "steam_frame_roy",
            "haptic_multiplier": 1.2,
            "passthrough": True,
            "hand_tracking": "synthetic",
        },
    },
    "max_visuals": {
        "id": "max_visuals",
        "name": "Maximum Visuals (PCVR Clarity)",
        "badge": "Ultra",
        "icon": "🌟",
        "description": "Quest 3 spoofing + 1.45x high-res eye buffers (~3100px) + 16x AF + eye-tracked DFR + boost clocks.",
        "settings": {
            "spoof_profile": "quest3",
            "resolution_scale": 1.45,
            "refresh_rate": 90,
            "foveated_rendering": "dynamic",
            "dynamic_foveation": True,
            "eye_tracking": True,
            "msaa": 4,
            "anisotropic_filtering": 16,
            "cpu_level": 4,
            "gpu_level": 5,
            "controller_models": "steam_frame_roy",
            "haptic_multiplier": 1.4,
            "passthrough": True,
        },
    },
    "high_fps_120": {
        "id": "high_fps_120",
        "name": "120Hz Ultra Smooth",
        "badge": "Competitive",
        "icon": "🏎️",
        "description": "120 Hz display refresh rate + 1.0x native resolution + dynamic VRS foveation for minimum motion latency.",
        "settings": {
            "spoof_profile": "quest3",
            "resolution_scale": 1.00,
            "refresh_rate": 120,
            "foveated_rendering": "dynamic",
            "dynamic_foveation": True,
            "eye_tracking": True,
            "msaa": 2,
            "anisotropic_filtering": 4,
            "cpu_level": 4,
            "gpu_level": 4,
            "controller_models": "steam_frame_roy",
            "haptic_multiplier": 1.0,
            "passthrough": True,
        },
    },
    "battery_saver": {
        "id": "battery_saver",
        "name": "Battery Saver",
        "badge": "Eco",
        "icon": "🔋",
        "description": "Quest 2 profile + 0.85x render scale + 72Hz + high fixed foveation for maximum playtime on battery.",
        "settings": {
            "spoof_profile": "quest2",
            "resolution_scale": 0.85,
            "refresh_rate": 72,
            "foveated_rendering": "high",
            "dynamic_foveation": False,
            "eye_tracking": False,
            "msaa": 2,
            "anisotropic_filtering": 1,
            "cpu_level": 2,
            "gpu_level": 2,
            "controller_models": "quest_touch",
            "haptic_multiplier": 0.8,
            "passthrough": False,
        },
    },
    "stock_default": {
        "id": "stock_default",
        "name": "Stock Quest 3 (1.0x)",
        "badge": "Stock",
        "icon": "🔄",
        "description": "Native Quest 3 settings at 1.0x scaling and 90Hz without additional supersampling.",
        "settings": {
            "spoof_profile": "quest3",
            "resolution_scale": 1.00,
            "refresh_rate": 90,
            "foveated_rendering": "off",
            "dynamic_foveation": False,
            "eye_tracking": False,
            "msaa": 2,
            "anisotropic_filtering": 1,
            "cpu_level": 3,
            "gpu_level": 3,
            "controller_models": "quest_touch",
            "haptic_multiplier": 1.0,
            "passthrough": True,
        },
    },
}

DEFAULT_TUNING: Dict[str, Any] = PRESETS["steam_frame_turbo"]["settings"].copy()


class TuningManager:
    @staticmethod
    def get_presets() -> Dict[str, Dict[str, Any]]:
        return PRESETS

    @staticmethod
    def get_spoof_profiles() -> Dict[str, Dict[str, Any]]:
        return SPOOF_PROFILES

    @staticmethod
    def get_global_tuning() -> Dict[str, Any]:
        """Reads global optimization defaults from config or returns DEFAULT_TUNING."""
        cfg = Config.get()
        stored = cfg.raw.get("game_defaults", {}) if hasattr(cfg, "raw") else {}
        merged = DEFAULT_TUNING.copy()
        if isinstance(stored, dict):
            merged.update(stored)
        return merged

    @staticmethod
    def save_global_tuning(settings: Dict[str, Any]) -> Dict[str, Any]:
        """Updates global default optimization settings in config.json."""
        cfg = Config.get()
        stored = cfg.raw.get("game_defaults", {}) if hasattr(cfg, "raw") else {}
        current = stored.copy() if isinstance(stored, dict) else {}
        current.update(settings)
        cfg["game_defaults"] = current
        return TuningManager.get_global_tuning()

    @staticmethod
    def get_game_tuning(package_name: str) -> Dict[str, Any]:
        """Returns the complete merged tuning profile for a specific installed game."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        global_tuning = TuningManager.get_global_tuning()
        game_settings = dep.get("settings", {})

        merged = global_tuning.copy()
        merged.update(game_settings)

        # Normalize types
        try:
            merged["resolution_scale"] = float(merged.get("resolution_scale", 1.25))
        except (ValueError, TypeError):
            merged["resolution_scale"] = 1.25

        try:
            merged["refresh_rate"] = int(merged.get("refresh_rate", 90))
        except (ValueError, TypeError):
            merged["refresh_rate"] = 90

        try:
            merged["msaa"] = int(merged.get("msaa", 4))
        except (ValueError, TypeError):
            merged["msaa"] = 4

        try:
            merged["anisotropic_filtering"] = int(merged.get("anisotropic_filtering", 8))
        except (ValueError, TypeError):
            merged["anisotropic_filtering"] = 8

        # Ensure spoof profile info is populated
        prof_id = merged.get("spoof_profile", "quest3")
        prof = SPOOF_PROFILES.get(prof_id, SPOOF_PROFILES["quest3"])
        merged["spoof_info"] = prof
        merged["engine"] = dep.get("engine", "Unknown")
        merged["is_vr"] = dep.get("is_vr", True)
        merged["title"] = dep.get("title", package_name)

        return merged

    @staticmethod
    def save_game_tuning(package_name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Saves tuning settings for an installed game and applies them immediately to all config files and launch script."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} is not installed.")

        current = dep.get("settings", {})
        current.update(settings)
        dep["settings"] = current

        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, package_name))
        dep_path = os.path.join(anchor, "deployment.json")
        with open(dep_path, "w", encoding="utf-8") as f:
            json.dump(dep, f, indent=2)

        # Apply changes to configs & launch.sh
        TuningManager.apply_tuning_to_game(package_name, current)

        return TuningManager.get_game_tuning(package_name)

    @staticmethod
    def apply_tuning_to_game(package_name: str, settings: Dict[str, Any]) -> bool:
        """Writes framebridge.conf, settings.conf, local.prop, and updates launch.sh with Steam Frame optimizations."""
        dep = InstalledManager.get_game(package_name)
        if not dep:
            return False

        base = dep.get("base", os.path.join(ANCHOR_DIR, package_name))
        anchor = dep.get("anchor", base)
        is_vr = dep.get("is_vr", True)

        # 1. Resolve Spoof Profile
        prof_id = settings.get("spoof_profile", "quest3")
        prof = SPOOF_PROFILES.get(prof_id, SPOOF_PROFILES["quest3"])

        # 2. Extract values with fallbacks
        scale = float(settings.get("resolution_scale", 1.25))
        refresh = int(settings.get("refresh_rate", 90))
        fov_mode = str(settings.get("foveated_rendering", "dynamic")).lower()
        dyn_fov = 1 if (fov_mode == "dynamic" or settings.get("dynamic_foveation")) else 0
        eye_track = 1 if (fov_mode == "dynamic" or settings.get("eye_tracking")) else 0
        msaa = int(settings.get("msaa", 4))
        af = int(settings.get("anisotropic_filtering", 8))
        cpu = int(settings.get("cpu_level", 4))
        gpu = int(settings.get("gpu_level", 4))
        ctrl_model = str(settings.get("controller_models", "steam_frame_roy"))
        haptic = float(settings.get("haptic_multiplier", 1.2))
        passthrough = 1 if settings.get("passthrough", True) else 0
        hand_track = str(settings.get("hand_tracking", "synthetic")).lower()

        # Calculate FFR level for debug.oculus.foveation.level
        ffr_levels = {"off": 0, "low": 1, "medium": 2, "high": 3, "dynamic": 3}
        ffr_num = ffr_levels.get(fov_mode, 3)

        # 3. Build FrameBridge / settings.conf dictionary
        bridge_conf = {
            "spoof_profile": prof_id,
            "spoof_model": prof["model"],
            "spoof_device": prof["device"],
            "spoof_manufacturer": prof["manufacturer"],
            "spoof_product": prof["product"],
            "spoof_headset_type": prof["headset_type"],
            "resolution_scale": f"{scale:.2f}",
            "refresh_rate": refresh,
            "foveated_rendering": fov_mode,
            "dynamic_foveation": dyn_fov,
            "eye_tracking": eye_track,
            "ffr_level": ffr_num,
            "msaa": msaa,
            "anisotropic_filtering": af,
            "cpu_level": cpu,
            "gpu_level": gpu,
            "controller_models": ctrl_model,
            "haptic_multiplier": f"{haptic:.2f}",
            "passthrough": passthrough,
            "hand_tracking": hand_track,
            "hand_tracking_enabled": 1 if hand_track != "disabled" else 0,
        }

        # Write settings.conf in base dir
        settings_conf_path = os.path.join(base, "settings.conf")
        ApkPatcher.generate_settings_conf(bridge_conf, settings_conf_path)

        # Write framebridge.conf in game data dir
        game_files_dir = os.path.join(base, "lepton-data/external/Android/data", package_name, "files")
        os.makedirs(game_files_dir, exist_ok=True)
        ApkPatcher.generate_settings_conf(bridge_conf, os.path.join(game_files_dir, "framebridge.conf"))

        # 4. Generate Android local.prop (Android Bionic System Property overrides)
        prop_lines = [
            "# Steam Frame Lepton Property Overrides",
            f"ro.product.model={prof['model']}",
            f"ro.product.device={prof['device']}",
            f"ro.product.manufacturer={prof['manufacturer']}",
            f"ro.build.product={prof['product']}",
            f"ro.build.fingerprint={prof['fingerprint']}",
            f"debug.oculus.cpuLevel={cpu}",
            f"debug.oculus.gpuLevel={gpu}",
            f"debug.oculus.refreshRate={refresh}",
            f"debug.oculus.foveation.level={ffr_num}",
            f"debug.oculus.foveation.dynamic={dyn_fov}",
            f"debug.oculus.textureWidthRatio={scale:.2f}",
            f"debug.oculus.textureHeightRatio={scale:.2f}",
            f"debug.oculus.anisotropic={af}",
            f"debug.oculus.handTracking={'1' if hand_track != 'disabled' else '0'}",
            f"debug.oculus.handTracking.mode={hand_track}",
        ]
        prop_content = "\n".join(prop_lines) + "\n"

        lepton_data = os.path.join(base, "lepton-data")
        os.makedirs(lepton_data, exist_ok=True)
        try:
            with open(os.path.join(lepton_data, "local.prop"), "w", encoding="utf-8") as f:
                f.write(prop_content)
            with open(os.path.join(game_files_dir, "local.prop"), "w", encoding="utf-8") as f:
                f.write(prop_content)
        except OSError:
            pass

        # 5. Hand Tracking Configuration & Skeleton Files
        try:
            from ..installer.hand_tracking import HandTrackingManager
            HandTrackingManager.generate_hand_tracking_files(base, package_name, mode=hand_track)
        except Exception as e:
            print(f"[FrameLoad] Hand tracking file gen error: {e}")

        # 6. Engine-Specific Optimizations
        engine = dep.get("engine", "Unknown")
        if engine == "Unreal":
            TuningManager._apply_unreal_engine_tweaks(game_files_dir, scale, msaa)

        # 7. Build Environment Variables string
        android_prop_override = ";".join([
            f"ro.product.model={prof['model']}",
            f"ro.product.device={prof['device']}",
            f"ro.product.manufacturer={prof['manufacturer']}",
            f"ro.build.product={prof['product']}",
            f"debug.oculus.cpuLevel={cpu}",
            f"debug.oculus.gpuLevel={gpu}",
            f"debug.oculus.refreshRate={refresh}",
            f"debug.oculus.foveation.level={ffr_num}",
            f"debug.oculus.foveation.dynamic={dyn_fov}",
            f"debug.oculus.textureWidthRatio={scale:.2f}",
            f"debug.oculus.textureHeightRatio={scale:.2f}",
            f"debug.oculus.anisotropic={af}",
            f"debug.oculus.handTracking={'1' if hand_track != 'disabled' else '0'}",
        ])

        env_block = f"""# === BEGIN STEAM FRAME TUNING ===
export LEPTON_SPOOF_MODEL={shlex.quote(prof['model'])}
export LEPTON_SPOOF_DEVICE={shlex.quote(prof['device'])}
export LEPTON_SPOOF_MANUFACTURER={shlex.quote(prof['manufacturer'])}
export LEPTON_VR_RESOLUTION_SCALE={shlex.quote(f"{scale:.2f}")}
export LEPTON_VR_REFRESH_RATE={shlex.quote(str(refresh))}
export LEPTON_FOVEATED_RENDERING={shlex.quote(fov_mode)}
export LEPTON_DYNAMIC_FOVEATION={dyn_fov}
export LEPTON_EYE_TRACKING={eye_track}
export LEPTON_MSAA={msaa}
export LEPTON_ANISOTROPIC={af}
export LEPTON_CPU_LEVEL={cpu}
export LEPTON_GPU_LEVEL={gpu}
export LEPTON_CONTROLLER_MODELS={shlex.quote(ctrl_model)}
export LEPTON_HAPTIC_SCALE={shlex.quote(f"{haptic:.2f}")}
export LEPTON_HAND_TRACKING={shlex.quote(hand_track)}
export ANDROID_PROPERTY_OVERRIDE={shlex.quote(android_prop_override)}
# === END STEAM FRAME TUNING ==="""

        # 7. Update launch.sh
        launch_script = os.path.join(anchor, "launch.sh")
        if os.path.isfile(launch_script):
            TuningManager._update_launch_script_env(launch_script, env_block)

        return True

    @staticmethod
    def _update_launch_script_env(launch_script_path: str, tuning_env_block: str) -> None:
        """Injects or replaces the Steam Frame Tuning block in launch.sh."""
        try:
            with open(launch_script_path, "r", encoding="utf-8") as f:
                content = f.read()

            pattern = r"# === BEGIN STEAM FRAME TUNING ===[\s\S]*?# === END STEAM FRAME TUNING ==="
            if re.search(pattern, content):
                new_content = re.sub(pattern, tuning_env_block, content)
            else:
                # Insert right before 'child='''
                target = "child=''"
                if target in content:
                    new_content = content.replace(target, f"{tuning_env_block}\n\n{target}")
                else:
                    new_content = content + f"\n\n{tuning_env_block}\n"

            with open(launch_script_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.chmod(launch_script_path, 0o755)
        except OSError as e:
            print(f"[FrameLoad] Error updating launch script {launch_script_path}: {e}")

    @staticmethod
    def _apply_unreal_engine_tweaks(game_files_dir: str, scale: float, msaa: int) -> None:
        """Writes Unreal Engine configuration overrides for VR clarity and performance."""
        try:
            ue_cfg_dir = os.path.join(game_files_dir, "UE4Game/Engine/Config")
            os.makedirs(ue_cfg_dir, exist_ok=True)
            ini_path = os.path.join(ue_cfg_dir, "ConsoleVariables.ini")

            screen_pct = int(scale * 100)
            lines = [
                "[Startup]",
                f"r.ScreenPercentage={screen_pct}",
                f"vr.EyeBufferResolutionScale={scale:.2f}",
                "r.MotionBlurQuality=0",
                "r.DepthOfFieldQuality=0",
                "r.SeparateTranslucency=0",
                f"r.MSAACount={msaa}",
            ]
            with open(ini_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass

    @staticmethod
    def apply_preset(package_name: str, preset_name: str) -> Dict[str, Any]:
        """Applies a named preset (e.g. steam_frame_turbo, max_visuals) to a specific game."""
        preset = PRESETS.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")
        return TuningManager.save_game_tuning(package_name, preset["settings"])

    @staticmethod
    def batch_apply(preset_name: str, package_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Applies a preset to all installed games or a given list of packages."""
        preset = PRESETS.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")

        installed = InstalledManager.list_installed()
        targets = package_names if package_names is not None else [g["package"] for g in installed]

        results = []
        for pkg in targets:
            try:
                res = TuningManager.apply_preset(pkg, preset_name)
                results.append({"package": pkg, "success": True})
            except Exception as e:
                results.append({"package": pkg, "success": False, "error": str(e)})

        return {
            "preset": preset_name,
            "applied_count": len([r for r in results if r["success"]]),
            "total": len(targets),
            "details": results,
        }
