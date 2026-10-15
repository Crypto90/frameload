"""Dashboard wording and small UI behaviour: names that exist, drive badges, the Move dialog, hints."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "frameload")
WEB = os.path.join(PACKAGE, "web")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def declaration(source, name):
    """One top-level function or const of app.js; each ends with a brace in the first column."""
    match = re.search(rf"^(?:async )?function {name}\(.*?^\}}$|^const {name} = .*?^\}};$", source, re.M | re.S)
    if not match:
        raise AssertionError(f"{name} not found in app.js")
    return match.group(0)


class TestNamesThatExist(unittest.TestCase):
    # Buttons, tabs and runtimes the dashboard used to have or never had.
    STALE = (
        "Port for Steam Frame",      # the buttons are Port & Play / Port Again
        "Set Up Porting",            # it is Set Up Now under System > Quest Game Porting
        "System & Diagnostics",      # the tab is System
        "System &amp; Diagnostics",
        "Sideload tab", "under Sideload",  # the tab is Install File
        "Catalog tab",               # the tab is Browse
        "on a PC",                   # porting runs on the headset
        "WineOpenXR", "FEX-Emu", "Monado",  # nothing in FrameLoad sets these up
        "Repair Container Keyring",  # the item only applies the podman keyring fix
    )

    def test_no_stale_names_in_the_sources(self):
        found = []
        for folder, _, files in os.walk(PACKAGE):
            for name in files:
                if not name.endswith((".py", ".js", ".html")):
                    continue
                text = read(folder, name)
                found += [f"{os.path.relpath(os.path.join(folder, name), ROOT)}: {s}" for s in self.STALE if s in text]
        self.assertEqual(found, [])

    def test_keyring_buttons_say_what_they_do(self):
        page = read(WEB, "templates", "index.html")
        labels = re.findall(r'onclick="fixKeyring\(\)">(.*?)</button>', page, re.S)
        labels = [re.sub(r"<svg.*?</svg>", "", label, flags=re.S).strip() for label in labels]
        self.assertEqual(labels, ["Apply Podman Keyring Leak Fix"] * 2)

    def test_big_picture_hint_for_x_matches_what_x_does(self):
        # X presses a card's own button (gamepad.js triggerAction) or acts like A; it opens no options menu.
        hints = re.search(r'<footer class="hint-bar".*?</footer>', read(WEB, "templates", "index.html"), re.S).group(0)
        label = re.search(r'<b class="key">X</b>([^<]+)</span>', hints).group(1)
        self.assertNotIn("Options", label)
        self.assertEqual(label, "Quick action")
        self.assertIn('querySelector(".card-btn")', read(WEB, "static", "js", "gamepad.js"))


class TestStorageTab(unittest.TestCase):
    def setUp(self):
        self.app = read(WEB, "static", "js", "app.js")

    def test_batch_bar_has_no_backup_switch_that_nothing_reads(self):
        # Batch uninstall asks in its own dialog (modal-confirm-keep-saves); the bar's switch was ignored.
        self.assertNotIn("batch-keep-saves", read(WEB, "templates", "index.html"))
        self.assertNotIn("batch-backup-toggle", read(WEB, "static", "css", "style.css"))
        self.assertIn('getElementById("modal-confirm-keep-saves")', self.app)

    def test_drive_cards_use_the_reported_drive_type(self):
        body = declaration(self.app, "renderStorageDrives")
        self.assertNotIn("is_sd_card", body)
        self.assertNotIn("SSD", body)
        self.assertIn("dev.device_type", body)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_drive_cards_render_by_device_type(self):
        devices = [
            {"id": "internal", "name": "Internal Storage (Home)", "device_type": "internal",
             "free_formatted": "1 GB", "total_formatted": "2 GB", "is_default": True},
            {"id": "ext_Nico's_SD", "name": "microSD Card (Nico's SD)", "device_type": "microsd",
             "free_formatted": "1 GB", "total_formatted": "2 GB"},
            {"id": "ext_stick", "name": "USB Drive (stick)", "device_type": "usb",
             "free_formatted": "1 GB", "total_formatted": "2 GB"},
        ]
        script = "\n".join(declaration(self.app, name) for name in
                           ("escapeHtml", "jsArg", "driveIcon", "DRIVE_TYPE_ICONS", "renderStorageDrives"))
        script += f"""
const els = {{ "storage-drives-list": {{ innerHTML: "" }} }};
var document = {{ getElementById: (id) => els[id] || null }};
renderStorageDrives({json.dumps(devices)}, null);
process.stdout.write(els["storage-drives-list"].innerHTML);
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cards.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            html = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8",
                                  check=True, timeout=60).stdout
        badges = re.findall(r'class="badge drive-type (\w+)">([^<]+)<', html)
        self.assertEqual(badges, [("internal", "Internal"), ("microsd", "microSD"), ("usb", "USB")])
        self.assertNotIn("SSD", html)
        # A drive name with an apostrophe still selects its drive.
        self.assertIn("selectStorageDrive(&quot;ext_Nico&#39;s_SD&quot;)", html)


class TestGamePage(unittest.TestCase):
    def setUp(self):
        self.app = read(WEB, "static", "js", "app.js")

    def test_move_drive_asks_which_drive(self):
        body = declaration(self.app, "moveCurrentModalGame")
        self.assertIn("/api/storage/move-targets", body)
        self.assertIn("pickDrive(", body)
        self.assertIn('okLabel: "Move"', body)
        self.assertIn("title: `Move ${name}`", body)
        self.assertNotIn("otherDevices[0]", body)
        self.assertNotIn("confirmDialog(", body)  # the drive dialog is the one question
        # The install dialog and the move dialog are the same markup.
        self.assertIn("pickDrive(", declaration(self.app, "chooseInstallDrive"))
        self.assertIn('id="install-drive-default-row"', read(WEB, "templates", "index.html"))

    def test_windows_and_linux_apps_are_recognised_by_their_kind(self):
        # Installed games carry `kind` from deployment.json; `install_type` only exists in the install result.
        body = declaration(self.app, "openGameModal")
        self.assertNotIn("install_type", body)
        for kind in ('"pcvr"', '"windows_flat"', '"linux_native"'):
            self.assertIn(kind, body)
        for installer in ("windows_proton.py", "linux_native.py"):
            text = read(PACKAGE, "installer", installer)
            self.assertTrue(re.search(r'"kind": "(pcvr|linux_native)"', text), installer)


if __name__ == "__main__":
    unittest.main()
