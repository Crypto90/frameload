"""Per-game settings for Android apps running in Lepton on the Steam Frame.

Every setting here maps to something the headset reads:

* Lepton environment variables (liblepton/mounting.sh passes FDM_DEBUG through; VK_INSTANCE_LAYERS
  selects Valve's Vulkan layers) and the `lepton-show-flatscreen` marker file.
* FrameBridge keys in settings.conf / framebridge.conf. Only APKs ported with FramePort contain the
  adapter that reads them, so those settings are reported as inactive for every other app.

Lepton has no way to change Android system properties per game (it writes its own lepton.prop with
ro.product.model=Lepton), so there is no device spoofing, MSAA, CPU/GPU level or similar here.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ..config import ANCHOR_DIR, Config
from ..installer import hand_tracking
from ..system import steamvr_settings
from ..installer.apk_analysis import inspect_apk
from .installed import InstalledManager

LEPTON_KINDS = ("quest", "flat")
REFRESH_RATES = (0, 72, 80, 90, 96, 108, 120, 144)

# scope: which apps show the setting. needs_framebridge: only read by FramePort-ported APKs.
SETTINGS_SCHEMA: List[Dict[str, Any]] = [
    {
        "key": "hand_input", "type": "choice", "default": "auto", "scope": "vr", "needs_framebridge": True,
        "title": "Hand input",
        "description": "Whether the game sees Touch controllers or the hand skeleton the Frame builds from its "
                       "controllers' finger sensors. Automatic passes hands only to games that require them.",
        "choices": [
            {"value": "auto", "label": "Automatic"},
            {"value": "controllers", "label": "Controllers"},
            {"value": "hands", "label": "Hands"},
        ],
    },
    {
        "key": "scale", "type": "range", "default": 1.0, "min": 0.5, "max": 2.0, "step": 0.05,
        "scope": "vr", "needs_framebridge": True, "unit": "x",
        "title": "Resolution scale",
        "description": "Multiplies the eye-buffer width and height the game renders at. 1.5 is 2.25 times the pixels.",
    },
    {
        "key": "refresh_rate", "type": "choice", "default": 0, "scope": "vr", "needs_framebridge": False,
        "title": "Refresh rate",
        "description": "Display refresh rate while this game runs, set in SteamVR before it starts. Game's choice "
                       "is the rate the game asks for (many Quest 3 games want 90 Hz), from its second start on.",
        "choices": [{"value": r, "label": f"{r} Hz" if r else "Game's choice"} for r in REFRESH_RATES],
    },
    {
        "key": "haptic_scale", "type": "range", "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
        "scope": "vr", "needs_framebridge": True, "unit": "x",
        "title": "Vibration strength",
        "description": "Scales every controller vibration the game asks for.",
    },
    {
        "key": "hide_space_warp", "type": "bool", "default": False, "scope": "vr", "needs_framebridge": True,
        "title": "Turn off space warp",
        "description": "The game renders every frame itself. For games whose picture flickers or smears.",
    },
    {
        "key": "gl_error_clear", "type": "bool", "default": False, "scope": "vr", "needs_framebridge": True,
        "title": "Clear OpenGL errors",
        "description": "For OpenGL ES games whose memory keeps growing: errors the game leaves behind make SteamVR "
                       "take new memory every frame. FrameBridge clears them before each frame.",
    },
    {
        "key": "stable_local", "type": "bool", "default": False, "scope": "vr", "needs_framebridge": True,
        "title": "Keep the play space still",
        "description": "For games whose menus jump to where you look.",
    },
    {
        "key": "foveation", "type": "choice", "default": "gaze", "scope": "vr", "needs_framebridge": False,
        "title": "Foveated rendering",
        "description": "Valve's Vulkan layer lowers detail away from where you look. Fixed stops it following your "
                       "gaze (cures one-eye jitter in some games); Off loads none of Valve's Vulkan layers.",
        "choices": [
            {"value": "gaze", "label": "Follow gaze (default)"},
            {"value": "fixed", "label": "Fixed"},
            {"value": "off", "label": "Off"},
        ],
    },
    {
        "key": "gpu_driver", "type": "choice", "default": "default", "scope": "vr", "needs_framebridge": False,
        "title": "Graphics driver workaround",
        "description": "Changes how the headset's graphics driver (Mesa Turnip) draws, for games that freeze the "
                       "picture with a GPU hang. Direct to memory skips the tile memory; it costs some speed.",
        "choices": [
            {"value": "default", "label": "None (default)"},
            {"value": "sysmem", "label": "Direct to memory"},
            {"value": "nocb", "label": "No concurrent binning"},
            {"value": "nolrz", "label": "No depth pre-pass (LRZ)"},
            {"value": "noubwc", "label": "No compressed images"},
            {"value": "flushall", "label": "Flush after every pass (slow)"},
        ],
    },
    {
        "key": "text_input", "type": "bool", "default": False, "scope": "vr", "needs_framebridge": False,
        "title": "Allow typing",
        "description": "Shows the app's Android window behind its VR view so Steam's keyboard can type into it.",
    },
    {
        "key": "hide_navbar", "type": "bool", "default": True, "scope": "flat", "needs_framebridge": False,
        "title": "Hide Android navigation bar",
        "description": "Removes the back / home / recents bar that otherwise covers the app's own controls.",
    },
]
SCHEMA_BY_KEY = {s["key"]: s for s in SETTINGS_SCHEMA}
# gpu_driver choice -> Turnip's TU_DEBUG flags (src/freedreno/vulkan/tu_util.cc)
TU_DEBUG_FLAGS: Dict[str, str] = {
    "default": "", "sysmem": "sysmem", "nocb": "nocb", "nolrz": "nolrz", "noubwc": "noubwc", "flushall": "flushall",
}
DEFAULTS: Dict[str, Any] = {s["key"]: s["default"] for s in SETTINGS_SCHEMA}
FRAMEBRIDGE_KEYS = ("controller_fix", "scale", "refresh_rate", "haptic_scale", "hide_space_warp", "stable_local",
                    "gl_error_clear")

# Each preset sets only its own settings, so presets combine (Sharper and 120 Hz together); none touches
# foveation, which FrameLoad turns off by itself for games that hang the graphics processor.
PRESETS: Dict[str, Dict[str, Any]] = {
    "default": {
        "id": "default", "name": "Game defaults",
        "description": "The resolution and refresh rate the game picks itself.",
        "settings": {"scale": 1.0, "refresh_rate": 0},
    },
    "sharp": {
        "id": "sharp", "name": "Sharper",
        "description": "1.3x resolution scale: about 70% more pixels, clearer text and distance. Combines with 120 Hz.",
        "settings": {"scale": 1.3},
    },
    "smooth": {
        "id": "smooth", "name": "120 Hz",
        "description": "120 Hz display refresh. Combines with Sharper.",
        "settings": {"refresh_rate": 120},
    },
    "battery": {
        "id": "battery", "name": "Battery saver",
        "description": "0.85x resolution scale at 72 Hz.",
        "settings": {"scale": 0.85, "refresh_rate": 72},
    },
}

# Keys written by FrameLoad up to v1.3.1. None of them reached the game, so stored values are dropped
# rather than turned into settings that suddenly take effect.
LEGACY_KEYS = frozenset((
    "spoof_profile", "resolution_scale", "msaa", "anisotropic_filtering", "cpu_level", "gpu_level",
    "controller_models", "haptic_multiplier", "passthrough", "dynamic_foveation", "eye_tracking",
    "foveated_rendering", "hand_tracking",
))


def _coerce(key: str, value: Any) -> Any:
    """Returns a valid value for a setting, or raises ValueError."""
    spec = SCHEMA_BY_KEY[key]
    if spec["type"] == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if spec["type"] == "range":
        number = float(value)
        if number != number:  # NaN
            raise ValueError(f"{key}: not a number")
        return round(min(spec["max"], max(spec["min"], number)), 2)
    allowed = [c["value"] for c in spec["choices"]]
    if isinstance(spec["default"], int):
        value = int(float(value))
    if value not in allowed:
        raise ValueError(f"{key}: {value!r} is not one of {allowed}")
    return value


coerce_setting = _coerce


def normalize_settings(raw: Any, keep_defaults: bool = False) -> Dict[str, Any]:
    """Keeps the valid settings of a stored or submitted dict; default values only on request."""
    if not isinstance(raw, dict) or LEGACY_KEYS & raw.keys():
        return {}
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        if key not in SCHEMA_BY_KEY:
            continue
        try:
            value = _coerce(key, value)
        except (ValueError, TypeError):
            continue
        if keep_defaults or value != DEFAULTS[key]:
            out[key] = value
    return out


def _update_conf(path: str, values: Dict[str, Any], remove: List[str]) -> None:
    """Sets and removes keys in a key=value file, keeping lines FrameLoad does not manage."""
    lines: List[str] = []
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
    managed = set(values) | set(remove)
    kept = [ln for ln in lines if ln.split("=", 1)[0].strip() not in managed]
    kept += [f"{k}={v}" for k, v in values.items()]
    if not kept and not os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(ln + "\n" for ln in kept))


class TuningManager:
    @staticmethod
    def get_presets() -> Dict[str, Dict[str, Any]]:
        return PRESETS

    @staticmethod
    def get_schema() -> List[Dict[str, Any]]:
        return SETTINGS_SCHEMA

    @staticmethod
    def get_global_tuning() -> Dict[str, Any]:
        """Defaults applied to every game that has no setting of its own."""
        merged = DEFAULTS.copy()
        merged.update(normalize_settings(Config.get().raw.get("game_defaults", {})))
        return merged

    @staticmethod
    def save_global_tuning(settings: Dict[str, Any]) -> Dict[str, Any]:
        cfg = Config.get()
        current = normalize_settings(cfg.raw.get("game_defaults", {}))
        for key, value in (settings or {}).items():
            if key not in SCHEMA_BY_KEY:
                continue
            value = _coerce(key, value)
            if value == DEFAULTS[key]:
                current.pop(key, None)
            else:
                current[key] = value
        cfg["game_defaults"] = current
        for game in InstalledManager.list_installed():
            if game.get("kind") in LEPTON_KINDS:
                TuningManager.apply_tuning_to_game(game["package"])
        return TuningManager.get_global_tuning()

    @staticmethod
    def _dep(package_name: str) -> Dict[str, Any]:
        dep = InstalledManager.get_game(package_name)
        if not dep:
            raise FileNotFoundError(f"Game {package_name} is not installed.")
        return dep

    @staticmethod
    def _write_dep(dep: Dict[str, Any]) -> None:
        anchor = dep.get("anchor", os.path.join(ANCHOR_DIR, dep.get("package", "")))
        stored = {k: v for k, v in dep.items() if k not in ("device_name", "is_external")}
        tmp = os.path.join(anchor, "deployment.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stored, f, indent=2)
        os.replace(tmp, os.path.join(anchor, "deployment.json"))

    @staticmethod
    def _ensure_analysis(dep: Dict[str, Any]) -> bool:
        """Fills framebridge / hand_tracking for games installed before these were recorded."""
        if "framebridge" in dep and "hand_tracking" in dep:
            return False
        apk = os.path.join(dep.get("base", ""), "lepton-app", "game.apk")
        try:
            analysis = inspect_apk(apk)
            dep["framebridge"] = analysis.framebridge
            dep["hand_tracking"] = analysis.hand_tracking
            dep["xr_runtime"] = analysis.xr_runtime
            dep["compat"] = analysis.compat
        except Exception:
            dep.setdefault("framebridge", False)
            dep.setdefault("hand_tracking", "none")
        return True

    @staticmethod
    def recommended_settings(dep: Dict[str, Any]) -> Dict[str, Any]:
        """What the compatibility list recommends for this game ({} when nothing, or recommendations are off)."""
        from . import compat_reports

        try:
            return compat_reports.recommended(dep.get("package", ""), dep.get("version_code"))
        except Exception as e:
            print(f"[FrameLoad] Could not read recommended settings: {e}")
            return {}

    @staticmethod
    def inherited_settings(dep: Dict[str, Any]) -> Dict[str, Any]:
        """What a game gets without settings of its own: the defaults under System, then the list's recommendation."""
        from . import quality

        merged = TuningManager.get_global_tuning()
        merged.update(TuningManager.recommended_settings(dep))
        merged.update(quality.applied(dep))  # automatic quality: what the game managed last time
        return merged

    @staticmethod
    def effective_settings(dep: Dict[str, Any]) -> Dict[str, Any]:
        # A game's own value wins over the global default even when it equals the built-in default.
        merged = TuningManager.inherited_settings(dep)
        merged.update(normalize_settings(dep.get("settings", {}), keep_defaults=True))
        return merged

    @staticmethod
    def sync_recommended(package_name: str) -> bool:
        """Rewrites a game's launcher when the list's recommendation for it changed since it was last written.
        True when it did. Only games FrameLoad installed (FramePort's launchers are left as they are)."""
        dep = InstalledManager.get_game(package_name)
        if not dep or dep.get("kind", "quest") not in LEPTON_KINDS \
                or dep.get("installed_by", "frameload") != "frameload":
            return False
        current = TuningManager.recommended_settings(dep)
        if current == dep.get("recommended_applied", {}):
            return False
        dep["recommended_applied"] = current
        TuningManager._write_dep(dep)
        TuningManager.apply_tuning_to_game(package_name, dep=dep)
        print(f"[FrameLoad] Recommended settings for {package_name}: {current or 'none'}")
        return True

    @staticmethod
    def restore_recommended(package_name: str) -> Dict[str, Any]:
        """Drops the game's own settings: it gets the defaults under System plus the list's recommendation."""
        dep = TuningManager._dep(package_name)
        if dep.get("kind", "quest") not in LEPTON_KINDS:
            raise ValueError("Settings apply to Android apps running in Lepton only.")
        dep["settings"] = {}
        dep["recommended_applied"] = TuningManager.recommended_settings(dep)
        TuningManager._write_dep(dep)
        TuningManager.apply_tuning_to_game(package_name, dep=dep)
        return TuningManager.get_game_tuning(package_name)

    @staticmethod
    def get_game_tuning(package_name: str) -> Dict[str, Any]:
        """The settings in effect for a game, plus what the UI needs to explain them."""
        dep = TuningManager._dep(package_name)
        if dep.get("kind", "quest") in LEPTON_KINDS and TuningManager._ensure_analysis(dep):
            try:
                TuningManager._write_dep(dep)
            except OSError:
                pass
        result = TuningManager.effective_settings(dep)
        requirement = dep.get("hand_tracking", "none")
        own = normalize_settings(dep.get("settings", {}), keep_defaults=True)
        result.update({
            # The list's recommendation, and which of its values this game overrides with its own.
            "recommended": TuningManager.recommended_settings(dep),
            # Automatic quality (quality.py): its values sit under the game's own; note says why.
            "auto_quality": dep.get("auto_quality") if isinstance(dep.get("auto_quality"), dict) else None,
            "game_refresh_rate": int(dep.get("game_refresh_rate") or 0),
            "display_rate": TuningManager.display_rate(TuningManager.effective_settings(dep), dep),
            "own_keys": sorted(own),
            "package": package_name,
            "title": dep.get("title", package_name),
            "kind": dep.get("kind", "quest"),
            "is_vr": bool(dep.get("is_vr", True)),
            "engine": dep.get("engine", "Unknown"),
            "configurable": dep.get("kind", "quest") in LEPTON_KINDS,
            "framebridge": bool(dep.get("framebridge", False)),
            "hand_tracking_requirement": requirement,
            "hand_input_effective": hand_tracking.effective_mode(result["hand_input"], requirement),
            "compat": dep.get("compat", {}),
        })
        return result

    @staticmethod
    def save_game_tuning(package_name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Stores a game's settings and rewrites its launcher and FrameBridge files.

        The game keeps only the values that differ from what it would get anyway (the defaults under
        System, else the built-in ones). A submitted value equal to that is removed from the game's own
        settings, so a later change of the defaults still reaches it. Keys not submitted stay as they are."""
        dep = TuningManager._dep(package_name)
        if dep.get("kind", "quest") not in LEPTON_KINDS:
            raise ValueError("Settings apply to Android apps running in Lepton only.")
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")

        inherited = TuningManager.inherited_settings(dep)
        current = normalize_settings(dep.get("settings", {}), keep_defaults=True)
        for key, value in settings.items():
            if key not in SCHEMA_BY_KEY:
                continue
            value = _coerce(key, value)
            if value == inherited[key]:
                current.pop(key, None)
            else:
                current[key] = value
        dep["settings"] = current
        TuningManager._write_dep(dep)
        TuningManager.apply_tuning_to_game(package_name)
        return TuningManager.get_game_tuning(package_name)

    @staticmethod
    def framebridge_values(settings: Dict[str, Any], requirement: str) -> Dict[str, Any]:
        """FrameBridge settings.conf keys for the settings that differ from the adapter's defaults."""
        conf: Dict[str, Any] = {}
        fix = hand_tracking.controller_fix_for(settings["hand_input"], requirement)
        if fix is not None:
            conf["controller_fix"] = fix
        if settings["scale"] != 1.0:
            conf["scale"] = f"{settings['scale']:.2f}"
        if settings["refresh_rate"]:
            conf["refresh_rate"] = settings["refresh_rate"]
        if settings["haptic_scale"] != 1.0:
            conf["haptic_scale"] = f"{settings['haptic_scale']:.2f}"
        for key in ("hide_space_warp", "stable_local", "gl_error_clear"):
            if settings[key]:
                conf[key] = 1
        return conf

    @staticmethod
    def display_rate(settings: Dict[str, Any], dep: Dict[str, Any]) -> int:
        """The panel rate launch.sh asks SteamVR for: the player's Refresh rate, else ("Game's choice") the rate the
        game itself asked for in an earlier session (sessions.learn_refresh_rate), lowered to automatic quality's
        cap when it could not hold it, else 0 (SteamVR's own)."""
        from . import quality

        if settings.get("refresh_rate"):
            return int(settings["refresh_rate"])
        rate, cap = int(dep.get("game_refresh_rate") or 0), quality.rate_cap(dep)
        return min(rate, cap) if rate and cap else rate

    @staticmethod
    def launch_env(settings: Dict[str, Any], is_vr: bool) -> Dict[str, str]:
        """Environment for `lepton start` (values FramePort verified on the headset)."""
        env: Dict[str, str] = {}
        props: List[str] = []
        if is_vr:
            if settings["foveation"] == "fixed":
                env["FDM_DEBUG"] = "disable_offsets"
            elif settings["foveation"] == "off":
                env["VK_INSTANCE_LAYERS"] = ""
            flags = TU_DEBUG_FLAGS.get(settings.get("gpu_driver", "default"))
            if flags:
                # Mesa on Android reads TU_DEBUG from the property debug.mesa.tu.debug (util/os_misc.c);
                # "startup" makes Turnip log the flags it took, so the session shows the workaround was active.
                props.append(f"debug.mesa.tu.debug={flags},startup")
        elif settings["hide_navbar"]:
            props.append("qemu.hw.mainkeys=1")
        if props:
            # These properties are only read at boot and Lepton has no setting for extra properties; it copies
            # LEPTON_GFXRECON_* values into the boot properties unescaped, so each further line adds one.
            env["LEPTON_GFXRECON_FRAMELOAD"] = "0\n" + "\n".join(props)
        return env

    @staticmethod
    def apply_tuning_to_game(package_name: str, settings: Optional[Dict[str, Any]] = None,
                             dep: Optional[Dict[str, Any]] = None) -> bool:
        """Writes a Lepton app's launcher, flat-window marker and FrameBridge settings."""
        from ..installer.lepton_quest import LeptonInstaller

        dep = dep or InstalledManager.get_game(package_name)
        if not dep or dep.get("kind", "quest") not in LEPTON_KINDS:
            return False
        if settings is not None:
            dep["settings"] = normalize_settings(settings, keep_defaults=True)

        base = dep.get("base", os.path.join(ANCHOR_DIR, package_name))
        anchor = dep.get("anchor", base)
        is_vr = bool(dep.get("is_vr", True))
        analysed = TuningManager._ensure_analysis(dep)
        effective = TuningManager.effective_settings(dep)

        LeptonInstaller.set_flatscreen(os.path.join(base, "lepton-app"), (not is_vr) or effective["text_input"])
        if is_vr:
            steamvr_settings.write_rate(base, TuningManager.display_rate(effective, dep))
        LeptonInstaller.write_launcher(
            anchor=anchor, base=base, package_name=package_name, title=dep.get("title", package_name),
            appid=dep.get("appid", 0), env=TuningManager.launch_env(effective, is_vr),
            hide_dashboard=is_vr,
        )

        previous = [k for k in dep.get("framebridge_keys", []) if k in FRAMEBRIDGE_KEYS]
        conf = TuningManager.framebridge_values(effective, dep.get("hand_tracking", "none")) if is_vr else {}
        stale = [k for k in previous if k not in conf]
        files_dir = os.path.join(base, "lepton-data/external/Android/data", package_name, "files")
        try:
            if conf or stale:
                _update_conf(os.path.join(base, "settings.conf"), conf, stale)
                os.makedirs(files_dir, exist_ok=True)
                _update_conf(os.path.join(files_dir, "framebridge.conf"), conf, stale)
        except OSError as e:
            print(f"[FrameLoad] Could not write FrameBridge settings for {package_name}: {e}")

        if analysed or sorted(conf) != sorted(previous) or settings is not None:
            dep["framebridge_keys"] = sorted(conf)
            try:
                TuningManager._write_dep(dep)
            except OSError:
                pass
        return True

    @staticmethod
    def apply_preset(package_name: str, preset_name: str) -> Dict[str, Any]:
        """Sets a preset's own settings and keeps the others, so presets combine. Like any saved value, a
        preset value equal to the default is not stored: the game keeps following the defaults for it."""
        preset = PRESETS.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")
        return TuningManager.save_game_tuning(package_name, preset["settings"])

    @staticmethod
    def batch_apply(preset_name: str, package_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Applies a preset to the given games, or to every installed Quest game."""
        if preset_name not in PRESETS:
            raise ValueError(f"Unknown preset: {preset_name}")
        if package_names is None:
            package_names = [g["package"] for g in InstalledManager.list_installed() if g.get("kind") == "quest"]

        results = []
        for pkg in package_names:
            try:
                TuningManager.apply_preset(pkg, preset_name)
                results.append({"package": pkg, "success": True})
            except Exception as e:
                results.append({"package": pkg, "success": False, "error": str(e)})
        return {
            "preset": preset_name,
            "applied_count": sum(1 for r in results if r["success"]),
            "total": len(package_names),
            "details": results,
        }
