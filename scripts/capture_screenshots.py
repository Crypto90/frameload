import subprocess
import os
import sys
from PIL import Image

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUTPUT_DIR = os.path.abspath("docs/images")
BASE_URL = "http://127.0.0.1:5055"

TARGETS = [
    ("screenshot_catalog.png", f"{BASE_URL}/#catalog"),
    ("screenshot_library.png", f"{BASE_URL}/#library"),
    ("screenshot_storage.png", f"{BASE_URL}/#storage"),
    ("screenshot_sideload.png", f"{BASE_URL}/#sideload"),
    ("screenshot_system.png", f"{BASE_URL}/#system"),
    ("screenshot_modal.png", f"{BASE_URL}/#modal"),
]

def capture_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for filename, url in TARGETS:
        out_path = os.path.join(OUTPUT_DIR, filename)
        print(f"Capturing {filename} from {url}...", flush=True)
        cmd = [
            CHROME_BIN,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1920,1080",
            "--virtual-time-budget=3500",
            f"--screenshot={out_path}",
            url
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
        except subprocess.TimeoutExpired:
            print(f"  Timeout reached for {filename}, proceeding to check image...", flush=True)

        if os.path.exists(out_path):
            size = os.path.getsize(out_path)
            try:
                with Image.open(out_path) as img:
                    w, h = img.size
                print(f"  ✓ Saved {filename}: {w}x{h}, {size:,} bytes", flush=True)
            except Exception as e:
                print(f"  ✓ Saved {filename}: {size:,} bytes (PIL error: {e})", flush=True)
        else:
            print(f"  ✗ Failed to create {filename}", flush=True)

if __name__ == "__main__":
    capture_all()
