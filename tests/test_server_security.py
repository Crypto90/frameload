"""The dashboard API is unauthenticated: only its own pages may call it."""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from frameload.server import FrameLoadApiHandler, is_trusted_host, is_valid_package


class TestValidators(unittest.TestCase):
    def test_package_names(self):
        for good in ("com.beatgames.beatsaber", "org.example.app_2", "win.my-game"):
            self.assertTrue(is_valid_package(good), good)
        for bad in ("", "..", "../etc", "a/b", "a\\b", "com..evil", ".hidden", "a b", None, 5, "x" * 300):
            self.assertFalse(is_valid_package(bad), repr(bad))

    def test_trusted_hosts(self):
        for good in ("127.0.0.1:5050", "localhost:5050", "192.168.1.20:5050", "[::1]:5050", "10.0.0.5"):
            self.assertTrue(is_trusted_host(good), good)
        for bad in ("", "evil.example:5050", "rebind.attacker.net", "localhost.evil.com:5050"):
            self.assertFalse(is_trusted_host(bad), bad)


class TestRequestOrigin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            conn.putrequest(method, path, skip_host=True)
            sent = {"Host": f"127.0.0.1:{self.port}"}
            sent.update(headers or {})
            if payload is not None:
                sent.setdefault("Content-Type", "application/json")
                sent["Content-Length"] = str(len(payload))
            for key, value in sent.items():
                conn.putheader(key, value)
            conn.endheaders(payload)
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def test_same_origin_requests_work(self):
        status, headers, body = self.request("GET", "/api/tuning/presets")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("schema", data)
        self.assertNotIn("spoof_profiles", data)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        origin = f"http://127.0.0.1:{self.port}"
        status, _, _ = self.request("POST", "/api/installed/stop", {"Origin": origin}, {"package": "com.not.installed"})
        self.assertEqual(status, 200)

    def test_other_sites_cannot_call_the_api(self):
        evil = {"Origin": "https://evil.example"}
        self.assertEqual(self.request("GET", "/api/config", evil)[0], 403)
        self.assertEqual(self.request("POST", "/api/system/uninstall-app", evil,
                                      {"confirm": "UNINSTALL", "purge_games": True})[0], 403)
        self.assertEqual(self.request("POST", "/api/installed/stop", {"Origin": "null"}, {"package": "a.b"})[0], 403)
        self.assertEqual(self.request("POST", "/api/installed/stop", {"Sec-Fetch-Site": "cross-site"},
                                      {"package": "a.b"})[0], 403)

    def test_dns_rebinding_host_is_refused(self):
        rebind = {"Host": f"rebind.attacker.net:{self.port}"}
        self.assertEqual(self.request("GET", "/api/config", rebind)[0], 403)
        self.assertEqual(self.request("POST", "/api/installed/stop", rebind, {"package": "a.b"})[0], 403)

    def test_preflight_grants_nothing(self):
        status, headers, _ = self.request("OPTIONS", "/api/installed/uninstall", {"Origin": "https://evil.example"})
        self.assertEqual(status, 204)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_package_names_are_validated(self):
        self.assertEqual(self.request("POST", "/api/installed/uninstall", body={"package": "../../home"})[0], 400)
        self.assertEqual(self.request("POST", "/api/storage/batch-uninstall", body={"packages": ["ok.app", "../x"]})[0], 400)
        self.assertEqual(self.request("GET", "/api/installed/tuning/..%2F..%2Fetc")[0], 400)
        self.assertEqual(self.request("GET", "/api/installed/mods?package=../x")[0], 400)

    def test_extra_host_names_can_be_allowed(self):
        from frameload.config import Config
        name = {"Host": f"frame.home.arpa:{self.port}"}
        self.assertEqual(self.request("GET", "/api/tuning/presets", name)[0], 403)
        cfg = Config.get()
        server_cfg = dict(cfg["server"])
        previous = list(server_cfg.get("allowed_hosts", []))
        server_cfg["allowed_hosts"] = previous + ["frame.home.arpa"]
        cfg["server"] = server_cfg
        try:
            self.assertEqual(self.request("GET", "/api/tuning/presets", name)[0], 200)
        finally:
            server_cfg["allowed_hosts"] = previous
            cfg["server"] = server_cfg

    def test_diagnostics_and_porting_endpoints(self):
        status, _, body = self.request("GET", "/api/system/doctor")
        self.assertEqual(status, 200)
        self.assertIn("checks", json.loads(body))
        status, _, body = self.request("GET", "/api/porting/status")
        self.assertEqual(status, 200)
        self.assertIn("installed", json.loads(body))
        self.assertEqual(self.request("GET", "/api/porting/jobs/unknown")[0], 404)
        self.assertEqual(self.request("POST", "/api/porting/port", body={"package": "com.not.installed"})[0], 404)
        self.assertEqual(self.request("POST", "/api/porting/port", {"Origin": "https://evil.example"},
                                      {"package": "a.b"})[0], 403)

    def test_static_files_cannot_escape(self):
        self.assertEqual(self.request("GET", "/static/../server.py")[0], 404)
        self.assertEqual(self.request("GET", "/static/css/style.css")[0], 200)


if __name__ == "__main__":
    unittest.main()
