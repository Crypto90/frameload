"""F-Droid, the default source of 2D apps. The code lives in app_sources.py (every source) and
repo_index.py (reading a repository's signed index); these names stay for the code and tests that
used them before there was more than one source."""
from __future__ import annotations

import os

from ..config import DATA_DIR
from .app_sources import CACHE_FIELDS, CACHE_VERSION, MAX_INDEX_BYTES, FDroidCatalog, RepoCatalog  # noqa: F401
from .repo_index import (  # noqa: F401
    FDROID_REPO,
    LEPTON_ABI,
    LEPTON_MAX_SDK,
    LOCALES,
    MAX_SCREENSHOTS,
    SCREENSHOT_KINDS,
    parse_index,
    pick_release,
)

FDROID_INDEX_JAR = f"{FDROID_REPO}/index-v1.jar"
# F-Droid's catalog cache; the other sources keep theirs in data/app_sources/.
FDROID_CACHE_JSON = os.path.join(DATA_DIR, "fdroid_cache.json")

__all__ = [
    "CACHE_FIELDS", "CACHE_VERSION", "FDROID_CACHE_JSON", "FDROID_INDEX_JAR", "FDROID_REPO", "FDroidCatalog",
    "LEPTON_ABI", "LEPTON_MAX_SDK", "LOCALES", "MAX_INDEX_BYTES", "MAX_SCREENSHOTS", "RepoCatalog",
    "SCREENSHOT_KINDS", "parse_index", "pick_release",
]
