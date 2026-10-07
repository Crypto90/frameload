"""Artwork fetcher and Steam Grid generator for FrameLoad."""
from __future__ import annotations

import os
import shutil
import urllib.parse
import urllib.request
from typing import Dict, Optional

from ..config import DATA_DIR


class ArtworkManager:
    @staticmethod
    def ensure_artwork(package_name: str, title: str, output_dir: str) -> Dict[str, str]:
        """Ensures grid artwork exists in output_dir (poster, banner, hero, logo, icon)."""
        os.makedirs(output_dir, exist_ok=True)
        art_files: Dict[str, str] = {}

        # 1. Check local VRP thumbnail (exact + case-insensitive)
        vrp_thumb = os.path.join(DATA_DIR, ".meta/thumbnails", f"{package_name}.jpg")
        base_img = None
        if os.path.isfile(vrp_thumb):
            base_img = vrp_thumb
        else:
            meta_thumb_dir = os.path.join(DATA_DIR, ".meta/thumbnails")
            if os.path.isdir(meta_thumb_dir):
                target_lower = f"{package_name.lower()}.jpg"
                try:
                    for entry in os.listdir(meta_thumb_dir):
                        if entry.lower() == target_lower:
                            base_img = os.path.join(meta_thumb_dir, entry)
                            break
                except OSError:
                    pass

        # 2. Try fetching from public game art mirrors if not found locally
        if not base_img:
            base_img = ArtworkManager._fetch_cover_art(package_name, title, output_dir)

        # 3. Create the required Steam grid art variants
        target_names = ["poster.png", "banner.png", "hero.png", "logo.png", "icon.png"]

        if base_img and os.path.isfile(base_img):
            for name in target_names:
                target_path = os.path.join(output_dir, name)
                if not os.path.isfile(target_path):
                    try:
                        shutil.copy2(base_img, target_path)
                    except OSError:
                        pass
                art_files[name] = target_path
        else:
            # Generate a clean placeholder artwork with SVG if no image could be downloaded
            ArtworkManager._generate_fallback_art(title, output_dir)

        return art_files

    @staticmethod
    def _fetch_cover_art(package_name: str, title: str, output_dir: str) -> Optional[str]:
        """Tries to download cover artwork from community repositories or SteamGrid."""
        safe_pkg = urllib.parse.quote(package_name)
        candidates = [
            f"https://raw.githubusercontent.com/Android-XR-Bridge/OVRPort/main/assets/covers/{safe_pkg}.jpg",
            f"https://raw.githubusercontent.com/spoopyghosty0/frameport/main/catalog/artwork/{safe_pkg}/poster.png",
            f"https://vrpirates.wiki/thumbnails/{safe_pkg}.jpg",
        ]

        target_file = os.path.join(output_dir, "cover.jpg")
        for url in candidates:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        with open(target_file, "wb") as f:
                            f.write(resp.read())
                        return target_file
            except Exception:
                continue
        return None

    @staticmethod
    def _generate_fallback_art(title: str, output_dir: str) -> None:
        """Generates fallback SVG/PNG placeholder files."""
        # Clean SVG graphic
        safe_title = (title[:24] + "...") if len(title) > 24 else title
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" viewBox="0 0 600 900">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f1424" />
      <stop offset="50%" stop-color="#171e38" />
      <stop offset="100%" stop-color="#0b0f1a" />
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#00f2fe" />
      <stop offset="100%" stop-color="#4facfe" />
    </linearGradient>
  </defs>
  <rect width="600" height="900" fill="url(#bg)" rx="16"/>
  <rect x="20" y="20" width="560" height="860" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2" rx="12"/>
  <circle cx="300" cy="380" r="80" fill="rgba(0, 242, 254, 0.08)" stroke="url(#accent)" stroke-width="4"/>
  <path d="M260,380 L340,380 M300,340 L300,420" stroke="url(#accent)" stroke-width="6" stroke-linecap="round"/>
  <text x="300" y="540" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="34" font-weight="bold" fill="#ffffff" text-anchor="middle">{safe_title}</text>
  <text x="300" y="585" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" fill="#00f2fe" text-anchor="middle" letter-spacing="3">STEAM FRAME VR</text>
  <rect x="220" y="820" width="160" height="32" rx="16" fill="rgba(255,255,255,0.05)"/>
  <text x="300" y="842" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" fill="rgba(255,255,255,0.6)" text-anchor="middle">FrameLoad</text>
</svg>"""

        svg_path = os.path.join(output_dir, "poster.svg")
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            # Copy to poster.png / banner.png / icon.png
            for name in ("poster.png", "banner.png", "hero.png", "logo.png", "icon.png"):
                dest = os.path.join(output_dir, name)
                if not os.path.isfile(dest):
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write(svg_content)
        except OSError as e:
            print(f"[FrameLoad] Could not write fallback artwork: {e}")
