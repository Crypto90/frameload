"""Send to GitHub: the token kept on the headset only, the issue a report becomes, one issue per problem
(later sessions with the same signature become comments), and the routes the dashboard uses."""
from __future__ import annotations

import http.client
import io
import json
import os
import stat
import sys
import threading
import time
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_sessions import NATIVE_CRASH, PACING, PKG, START_PROC, TOMBSTONE, SessionCase  # noqa: E402

from frameload.config import Config  # noqa: E402
from frameload.manager import github_reports, sessions  # noqa: E402
from frameload.server import FrameLoadApiHandler  # noqa: E402

TOKEN = "github_pat_" + "A1b2C3d4" * 6


class Response(io.BytesIO):
    def __init__(self, status, payload):
        super().__init__(json.dumps(payload).encode() if payload is not None else b"")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGitHub:
    """api.github.com as far as FrameLoad uses it: one repository with issues and comments."""

    def __init__(self):
        self.issues = {}
        self.comments = []
        self.requests = []
        self.refuse_labels = False
        self.status = None  # answer every request with this status

    def __call__(self, req, timeout=None):
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        self.requests.append((method, url, body, dict(req.header_items())))
        assert url.startswith("https://api.github.com/"), url
        path = url[len("https://api.github.com"):]
        if self.status:
            raise urllib.error.HTTPError(url, self.status, "no", {}, io.BytesIO(b'{"message": "Bad credentials"}'))
        if method == "GET" and path == "/repos/Crypto90/frameload":
            return Response(200, {"full_name": "Crypto90/frameload", "has_issues": True})
        if method == "GET" and path.startswith("/repos/Crypto90/frameload/issues?"):
            return Response(200, [i for i in self.issues.values() if i["state"] == "open"])
        if method == "GET" and path.startswith("/repos/Crypto90/frameload/issues/"):
            return Response(200, self.issues[int(path.rsplit("/", 1)[1])])
        if method == "POST" and path == "/repos/Crypto90/frameload/issues":
            if self.refuse_labels and "labels" in body:
                raise urllib.error.HTTPError(url, 422, "no", {}, io.BytesIO(b'{"message": "Validation Failed"}'))
            number = len(self.issues) + 1
            self.issues[number] = {"number": number, "state": "open", "body": body["body"], "title": body["title"],
                                   "labels": body.get("labels", []),
                                   "html_url": f"https://github.com/Crypto90/frameload/issues/{number}"}
            return Response(201, self.issues[number])
        if method == "POST" and path.endswith("/comments"):
            number = int(path.split("/")[-2])
            self.comments.append((number, body["body"]))
            return Response(201, {"html_url": f"https://github.com/Crypto90/frameload/issues/{number}#c{len(self.comments)}"})
        raise AssertionError(f"unexpected {method} {path}")


class GitHubCase(SessionCase):
    def setUp(self):
        super().setUp()
        self.github = FakeGitHub()
        cfg = Config.get()
        saved = cfg.raw.get("reports")
        self.addCleanup(lambda: cfg.raw.__setitem__("reports", saved) if saved is not None else cfg.raw.pop("reports", None))
        cfg.raw.pop("reports", None)
        for p in (patch.object(github_reports, "TOKEN_FILE", os.path.join(self.tmp, "github_token")),
                  patch.object(github_reports, "STATE_FILE", os.path.join(self.tmp, "github_reports.json")),
                  patch.object(github_reports, "_urlopen", self.github),
                  patch.object(Config, "save")):
            p.start()
            self.addCleanup(p.stop)

    def crash(self, ago=10):
        _, end = self.session([START_PROC, PACING, NATIVE_CRASH], crash=TOMBSTONE, ago=ago)
        sessions.finalize(PKG)
        return end


class TestToken(GitHubCase):
    def test_the_token_stays_in_its_own_file_and_never_comes_back(self):
        res = github_reports.save_settings({"token": f"  {TOKEN}\n", "repo": "https://github.com/Crypto90/frameload.git"})
        self.assertEqual(res, {"repo": "Crypto90/frameload", "default_repo": "Crypto90/frameload", "configured": True,
                               "hint": "...C3d4"})
        self.assertNotIn(TOKEN, json.dumps(Config.get().raw))  # GET /api/config hands the config out
        with open(github_reports.TOKEN_FILE, encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), TOKEN)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(github_reports.TOKEN_FILE).st_mode), 0o600)

        with self.assertRaises(ValueError):
            github_reports.save_settings({"token": "my password"})
        with self.assertRaises(ValueError):
            github_reports.save_settings({"repo": "not a repo/../x"})
        self.assertTrue(github_reports.settings()["configured"])  # a refused token leaves the old one

        self.assertFalse(github_reports.save_settings({"clear": True})["configured"])
        self.assertFalse(os.path.exists(github_reports.TOKEN_FILE))

    def test_test_asks_github_with_the_token(self):
        github_reports.save_settings({"token": TOKEN})
        res = github_reports.check()
        self.assertTrue(res["success"], res)
        method, url, _, headers = self.github.requests[0]
        self.assertEqual((method, url), ("GET", "https://api.github.com/repos/Crypto90/frameload"))
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, json.dumps(res))

        self.github.status = 401
        res = github_reports.check()
        self.assertFalse(res["success"])
        self.assertIn("refused the token", res["error"])


class TestSend(GitHubCase):
    def setUp(self):
        super().setUp()
        github_reports.save_settings({"token": TOKEN})

    def test_without_a_token_nothing_is_sent(self):
        github_reports.save_settings({"clear": True})
        self.crash()
        res = github_reports.send(PKG)
        self.assertEqual(res, {"success": False, "error": github_reports.NO_TOKEN})
        self.assertEqual(self.github.requests, [])

    def test_a_crash_becomes_an_issue_once(self):
        self.write("dashboard.log", "12:00:01 waiting for the first picture\nresult: hidden 1\n")
        self.write(".last_launch", json.dumps({"time": int(time.time()) - 320, "via": "direct", "pending": True}))
        end = self.crash()
        res = github_reports.send(PKG, note=f"Crashed when I opened the map, see {os.path.expanduser('~')}/x")
        self.assertEqual((res["success"], res["number"], res["comment"]), (True, 1, False))
        issue = self.github.issues[1]
        self.assertTrue(issue["title"].startswith("Test Game crashed"), issue["title"])
        self.assertIn(PKG, issue["title"])
        self.assertEqual(issue["labels"], ["crash-report", "crash"])
        body = issue["body"]
        self.assertLess(len(body), 65536)
        self.assertIn(f"frameload-signature: {res['signature']}", body)
        self.assertIn("**Cause:**", body)
        self.assertIn("SIGSEGV", body)
        self.assertIn("libgallium_dri.so", body)  # the backtrace
        self.assertIn("result: hidden 1", body)  # Steam's menu at the start, kept with the session
        self.assertIn("directly by FrameLoad", body)
        self.assertIn("Crashed when I opened the map", body)
        home = os.path.expanduser("~")
        if len(home) > 1:
            self.assertNotIn(home, body)

        again = github_reports.send(PKG)  # the same session: no second issue
        self.assertEqual((again["already"], again["number"]), (True, 1))
        self.assertEqual(len(self.github.issues), 1)
        self.assertEqual(self.github.comments, [])
        self.assertIn(f"{PKG}:{end}", github_reports._state()["sent"])

    def test_the_same_crash_again_is_a_comment_on_its_issue(self):
        self.crash(ago=30)
        first = github_reports.send(PKG)
        self.crash(ago=10)  # a later session, same game version, same crash place
        second = github_reports.send(PKG)
        self.assertEqual((second["number"], second["comment"]), (first["number"], True))
        self.assertEqual(len(self.github.issues), 1)
        self.assertTrue(self.github.comments[0][1].startswith("**Seen again.**"))

        # FrameLoad forgot its own record (reinstalled): the open issue is found by its signature.
        os.remove(github_reports.STATE_FILE)
        self.crash(ago=2)
        third = github_reports.send(PKG)
        self.assertEqual((third["number"], third["comment"]), (first["number"], True))

    def test_a_crash_after_its_issue_was_closed_opens_a_new_one(self):
        self.crash(ago=30)
        github_reports.send(PKG)
        self.github.issues[1]["state"] = "closed"  # fixed, or so it seemed
        self.crash(ago=10)
        res = github_reports.send(PKG)
        self.assertEqual((res["number"], res["comment"]), (2, False))
        self.assertIn("**Earlier issue:** #1 (closed)", self.github.issues[2]["body"])

    def test_a_label_github_refuses_does_not_stop_the_report(self):
        self.github.refuse_labels = True
        self.crash()
        res = github_reports.send(PKG)
        self.assertTrue(res["success"], res)
        self.assertEqual(self.github.issues[1]["labels"], [])

    def test_a_refused_token_sends_nothing_and_remembers_nothing(self):
        self.crash()
        self.github.status = 403
        res = github_reports.send(PKG)
        self.assertFalse(res["success"])
        self.assertIn("Issues: read and write", res["error"])
        self.assertEqual(github_reports._state()["sent"], {})

    def test_a_long_log_with_backticks_still_fits(self):
        lines = [START_PROC, PACING] + [f"line {i} ```` {'x' * 200}" for i in range(2000)] + [NATIVE_CRASH]
        self.session(lines, crash=TOMBSTONE)
        sessions.finalize(PKG)
        github_reports.send(PKG)
        body = self.github.issues[1]["body"]
        self.assertLessEqual(len(body), github_reports.BODY_MAX)
        self.assertIn("`````text\n", body)  # a fence longer than any run of backticks in the log
        self.assertTrue(body.rstrip().endswith("</sub>"))

    def test_without_a_recorded_session_the_current_log_is_sent(self):
        self.write("launch.log", "\n".join([START_PROC, PACING]) + "\n")
        self.write("show.log", f"{time.strftime('%Y-%m-%d %H:%M:%S')} Show: reopened; started via direct; menu open: True\n")
        res = github_reports.send(PKG, source="live")
        self.assertTrue(res["success"], res)
        body = self.github.issues[1]["body"]
        self.assertIn("no finished session recorded", body)
        self.assertIn("Show: reopened", body)  # the presses of Show belong in the report


class TestRoutes(GitHubCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameLoadApiHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            conn.request(method, path, body=payload, headers={"Content-Type": "application/json",
                                                              "Content-Length": str(len(payload or b""))})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read() or b"{}")
        finally:
            conn.close()

    def test_settings_send_and_no_token_in_any_answer(self):
        status, res = self.call("POST", "/api/reports/github/settings", {"token": TOKEN})
        self.assertEqual((status, res["configured"]), (200, True))
        status, res = self.call("GET", "/api/reports/github")
        self.assertEqual((status, res["hint"]), (200, "...C3d4"))
        self.assertNotIn(TOKEN, json.dumps(res))
        self.assertNotIn(TOKEN, json.dumps(self.call("GET", "/api/config")[1]))
        self.assertEqual(self.call("POST", "/api/reports/github/settings", {"token": "nope"})[0], 400)

        self.crash()
        status, res = self.call("POST", "/api/reports/github/send", {"package": PKG})
        self.assertEqual((status, res["success"], res["number"]), (200, True, 1))
        self.assertEqual(self.call("POST", "/api/reports/github/send", {"package": "../x"})[0], 400)

        with patch.object(FrameLoadApiHandler, "client_is_local", return_value=False):  # not paired
            self.assertEqual(self.call("POST", "/api/reports/github/send", {"package": PKG})[0], 401)
            self.assertEqual(self.call("GET", "/api/reports/github")[0], 401)


class TestDashboard(unittest.TestCase):
    def test_buttons_and_card(self):
        web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frameload", "web")
        with open(os.path.join(web, "templates", "index.html"), encoding="utf-8") as f:
            page = f.read()
        with open(os.path.join(web, "static", "js", "app.js"), encoding="utf-8") as f:
            js = f.read()
        for needle in ('id="session-github"', 'id="log-github"', 'id="github-token"', 'type="password"',
                       "Issues: Read and write", 'id="github-reports-card"'):
            self.assertIn(needle, page)
        for needle in ("/api/reports/github/send", "/api/reports/github/settings", "/api/reports/github/check"):
            self.assertIn(needle, js)


if __name__ == "__main__":
    unittest.main()
