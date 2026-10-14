"""The dashboard's look (System > Appearance): saved on the headset, served from the first paint."""
from __future__ import annotations

import http.client
import json
import os
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from frameload.config import Config
from frameload.server import SKINS, FrameLoadApiHandler, appearance

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frameload", "web")


class TestAppearance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        cfg = Config.get()
        saved = dict(cfg.raw.get("ui", {}))
        self.addCleanup(lambda: cfg.raw.__setitem__("ui", saved))
        p = patch.object(Config, "save")
        p.start()
        self.addCleanup(p.stop)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))} if payload else {}
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read().decode("utf-8", "replace")
        finally:
            conn.close()

    def test_big_picture_is_the_default(self):
        Config.get().raw["ui"] = {}
        self.assertEqual(appearance(), ("a", "light"))
        Config.get().raw["ui"] = {"skin": "z", "daylight": "dim"}
        self.assertEqual(appearance(), ("a", "light"))  # anything unknown falls back

    def test_the_saved_look_is_in_the_page_before_it_paints(self):
        status, body = self.request("POST", "/api/ui/appearance", {"skin": "f", "daylight": "dark"})
        self.assertEqual(status, 200, body)
        self.assertEqual(Config.get().raw["ui"], {"skin": "f", "daylight": "dark"})
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('<html lang="en" data-skin="f" data-mode="dark">', page)
        self.assertIn('href="/static/css/skins/f.css"', page)
        self.assertNotIn('href="/static/css/skins/a.css"', page)

    def test_unknown_looks_are_refused(self):
        for body in ({"skin": "g"}, {"skin": "../x"}, {"skin": "b", "daylight": "sepia"}):
            self.assertEqual(self.request("POST", "/api/ui/appearance", body)[0], 400, body)

    def test_every_look_ships_its_stylesheet_and_view(self):
        page = open(os.path.join(WEB, "templates", "index.html"), encoding="utf-8").read()
        for skin in SKINS:
            self.assertTrue(os.path.isfile(os.path.join(WEB, "static", "css", "skins", f"{skin}.css")), skin)
            self.assertTrue(os.path.isfile(os.path.join(WEB, "static", "js", "skins", f"{skin}.js")), skin)
            self.assertIn(f'src="/static/js/skins/{skin}.js"', page)
        # every font a stylesheet names is bundled, so the headset needs no network for it
        fonts = open(os.path.join(WEB, "static", "fonts", "fonts.css"), encoding="utf-8").read()
        for name in re.findall(r'src: url\("([^"]+)"\)', fonts):
            self.assertTrue(os.path.isfile(os.path.join(WEB, "static", "fonts", name)), name)
        status, _ = self.request("GET", "/static/fonts/fonts.css")
        self.assertEqual(status, 200)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/static/fonts/" + re.findall(r'src: url\("([^"]+)"\)', fonts)[0])
            resp = conn.getresponse()
            resp.read()
            self.assertEqual(resp.getheader("Content-Type"), "font/woff2")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
