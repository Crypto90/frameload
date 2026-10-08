"""Compatibility alias: APK inspection lives in apk_analysis. FrameLoad no longer claims to patch APKs."""
from __future__ import annotations

from typing import Any, Dict

from .apk_analysis import ApkAnalysis, inspect_apk, write_conf

__all__ = ["ApkAnalysis", "ApkPatcher"]


class ApkPatcher:
    @staticmethod
    def inspect(apk_path: str) -> ApkAnalysis:
        return inspect_apk(apk_path)

    @staticmethod
    def generate_settings_conf(settings: Dict[str, Any], output_path: str) -> None:
        write_conf(settings, output_path)
