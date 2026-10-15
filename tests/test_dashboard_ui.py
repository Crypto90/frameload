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


class TestPortingDialog(unittest.TestCase):
    def test_a_failed_job_looks_failed(self):
        # Jobs that fail end with the status "error"; the stylesheet styles the icon and bar as "failed".
        render = declaration(read(PACKAGE, "web", "static", "js", "app.js"), "renderPortingJob")
        self.assertIn('job.status === "error" ? "failed"', render)
        self.assertNotIn("job-icon ${job.status}", render)

    def test_a_port_that_failed_inside_the_setup_ends_the_wait(self):
        poll = declaration(read(PACKAGE, "web", "static", "js", "app.js"), "pollPortingJob")
        self.assertIn("job.result.failed", poll)


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


def run_node(script):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "check.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        return subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8",
                              check=True, timeout=60).stdout


class TestFreezeGuardCard(unittest.TestCase):
    def setUp(self):
        self.page = read(WEB, "templates", "index.html")
        self.app = read(WEB, "static", "js", "app.js")

    def test_the_wait_offers_what_the_server_keeps(self):
        from frameload.manager.guard import DEFAULT_SETTINGS, FROZEN_CHOICES
        select = re.search(r'<select id="guard-frozen-seconds".*?</select>', self.page, re.S).group(0)
        self.assertEqual(tuple(int(v) for v in re.findall(r'<option value="(\d+)"', select)), FROZEN_CHOICES)
        self.assertNotIn("Off by default", self.page)
        self.assertIn("On by default", self.page)
        body = declaration(self.app, "saveGuardSettings")
        for key in DEFAULT_SETTINGS:
            self.assertIn(f"{key}:", body)
        self.assertIn('id="guard-report"', self.page)
        self.assertIn("Show what happened when a game crashes or is stopped", self.page)


class TestDeviceFigures(unittest.TestCase):
    """Every look shows free space, CPU and memory somewhere that is always on screen."""

    def test_each_look_shows_free_space_cpu_and_memory(self):
        app = read(WEB, "static", "js", "app.js")
        page = read(WEB, "templates", "index.html")
        # Shared places: Spatial's status dock and Big Picture's bottom bar.
        for needle in ('id="dock-mem"', 'id="hint-free"', 'id="hint-perf"'):
            self.assertIn(needle, page)
        self.assertIn("memory:", app)  # the icon
        # A uses the bottom bar, B the dock (both filled by app.js); C-F draw their own.
        self.assertIn(".hint-stat", read(WEB, "static", "css", "skins", "a.css"))
        self.assertIn(".status-dock", read(WEB, "static", "css", "skins", "b.css"))
        for skin, needles in {"c": ("freeGb", "dev.cpu", "ramUsedGb"), "d": ("freeGb", "cpu_percent", "ramShort"),
                              "e": ("freeGb", "d.cpu", "ramUsedGb"), "f": ("freeGb", "d.cpu", "ramUsedGb")}.items():
            js = read(WEB, "static", "js", "skins", f"{skin}.js")
            for needle in needles:
                self.assertIn(needle, js, f"look {skin}: {needle}")


class TestSessionDialog(unittest.TestCase):
    def setUp(self):
        self.page = read(WEB, "templates", "index.html")
        self.app = read(WEB, "static", "js", "app.js")

    def modal(self, modal_id):
        start = self.page.index(f'<div id="{modal_id}"')
        return self.page[start:self.page.index("\n  </div>\n", start)]

    def test_dialog_markup(self):
        modal = self.modal("session-modal")
        self.assertIn('role="alertdialog" aria-labelledby="session-title"', modal)
        labels = [re.sub(r"\s+", " ", label).strip() for label in re.findall(r"<button[^>]*>([^<]+)</button>", modal)]
        self.assertEqual(labels, ["Copy Log", "Send to GitHub", "Save Log", "Open Launch Log", "Don't Show for This Game", "Close"])
        self.assertRegex(modal, r'<button[^>]*data-back[^>]*>Close</button>')  # B / Back closes it
        self.assertIn('class="job-log session-excerpt"', modal)
        # The launch log opens from it and must lie on top of it.
        self.assertLess(self.page.index('id="session-modal"'), self.page.index('id="log-modal"'))
        log = self.modal("log-modal")
        self.assertIn(">Copy Log<", log)
        self.assertIn(">Save Log<", log)
        self.assertIn('class="job-log log-modal-lines"', log)

    def test_logs_move_with_the_scroll_arrows(self):
        # ScrollAssist scrolls the dialog itself; a log with a scroll box of its own was out of its reach.
        css = read(WEB, "static", "css", "style.css")
        rule = re.search(r"\.session-excerpt, \.log-modal-lines \{([^}]*)\}", css).group(1)
        self.assertIn("max-height: none", rule)
        self.assertIn("overflow: visible", rule)
        added = css[css.index("/* What happened (session dialog)"):]
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d", added), "colours come from tokens")

    def test_copy_never_uses_a_text_field(self):
        # Focusing a text field opens the Steam keyboard (SteamOSK).
        body = declaration(self.app, "copyText") + declaration(self.app, "copyWithSelection")
        for part in ("isSecureContext", "writeText", 'execCommand("copy")', "createRange"):
            self.assertIn(part, body)
        self.assertNotIn("textarea", body.lower())
        self.assertNotIn(".focus(", body)

    def test_no_browser_dialogs(self):
        for name in ("openSessionDialog", "closeSessionDialog", "noteSessionAlerts", "copyReport", "saveReport",
                     "openLogModal", "noteGuardEvent", "loadGuard", "saveGuardSettings"):
            self.assertIsNone(re.search(r"\b(alert|confirm)\(", declaration(self.app, name)), name)

    def test_game_page_offers_what_happened_after_an_abnormal_end(self):
        body = declaration(self.app, "openGameModal")
        self.assertIn("game.last_session.abnormal", body)
        self.assertIn("openSessionDialog(${arg})\">What Happened</button>", body)
        self.assertIn("openSessionDialog(", read(WEB, "static", "js", "skins", "e.js"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_copy_in_an_insecure_context_selects_a_hidden_block(self):
        script = declaration(self.app, "copyText") + "\n" + declaration(self.app, "copyWithSelection") + """
const made = [], calls = [];
var window = { isSecureContext: false, getSelection: () => ({ removeAllRanges() { calls.push("clear"); }, addRange(r) { calls.push("select:" + r.node.textContent); } }) };
var navigator = {};
var document = {
  body: { appendChild(el) { calls.push("append:" + el.className); } },
  createElement(tag) { const el = { tag, className: "", textContent: "", remove() { calls.push("remove"); } }; made.push(tag); return el; },
  createRange() { return { selectNodeContents(node) { this.node = node; } }; },
  execCommand(cmd) { calls.push("exec:" + cmd); return true; },
};
const result = copyText("report text");
calls.push("sync");  // execCommand must run inside the click, before anything is awaited
result.then(ok => {
  window.isSecureContext = true;
  navigator.clipboard = { writeText: async (t) => { calls.push("clipboard:" + t); } };
  return copyText("secure").then(ok2 => process.stdout.write(JSON.stringify({ ok, ok2, made, calls })));
});
"""
        out = json.loads(run_node(script))
        self.assertTrue(out["ok"] and out["ok2"])
        self.assertEqual(out["made"], ["div"])
        self.assertEqual(out["calls"], ["append:copy-buffer", "clear", "select:report text", "exec:copy", "clear",
                                        "remove", "sync", "clipboard:secure"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_dialog_waits_for_a_free_moment(self):
        script = declaration(self.app, "noteSessionAlerts") + declaration(self.app, "sessionDialogMustWait") + """
var state = { installed: [], sessions: { handled: new Set() } };
let openModal = null;
var document = { querySelector: () => openModal };
const opened = [];
// Like the real one: an alert counts as handled once its dialog is open.
function openSessionDialog(pkg, options) { opened.push([pkg, options.auto]); state.sessions.handled.add(`${pkg}:${options.end}`); }
const alerts = [{ package: "a.game", end: 2 }, { package: "b.game", end: 1 }];
noteSessionAlerts(alerts);                                           // the library has not loaded yet
state.installedLoaded = true;
openModal = {};  noteSessionAlerts(alerts);                          // another dialog is open
opened.push("game");
openModal = null; state.installed = [{ is_running: true }]; noteSessionAlerts(alerts);  // a game runs
opened.push("starting");
state.installed = []; state.launchingUntil = Date.now() + 60000; noteSessionAlerts(alerts);  // Play was just pressed
opened.push("free");
state.launchingUntil = 0; noteSessionAlerts(alerts); noteSessionAlerts(alerts); noteSessionAlerts(alerts);
process.stdout.write(JSON.stringify(opened));
"""
        self.assertEqual(json.loads(run_node(script)), ["game", "starting", "free", ["a.game", True], ["b.game", True]])


if __name__ == "__main__":
    unittest.main()
