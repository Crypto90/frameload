"""Send to GitHub: a game's report becomes an issue in FrameLoad's repository (or one the player chose).

For testing many games: when one crashes, one press in What Happened (or the Launch Log) sends the
report, and the issues can be worked through later. GitHub needs a token for this, and FrameLoad
ships none: the player creates their own (fine-grained, access to that one repository, permission
Issues: read and write) and pastes it in System > Crash Reports. It is kept in DATA_DIR/github_token
(0600), never in config.json (GET /api/config hands that out), never returned by the API, and only
ever sent to api.github.com.

The report is the one Copy Log gives (sessions.report_text: home folder, host name, addresses and
Steam ids removed). A report whose signature (game, version, outcome, crash place) already has an
open issue becomes a comment on it instead of a second issue, and a session is sent only once.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATA_DIR

API = "https://api.github.com"
DEFAULT_REPO = "Crypto90/frameload"
TOKEN_FILE = os.path.join(DATA_DIR, "github_token")
STATE_FILE = os.path.join(DATA_DIR, "github_reports.json")
BODY_MAX = 65000             # GitHub refuses issue bodies and comments over 65,536 characters
NOTE_MAX = 1000
TITLE_MAX = 200
LABEL = "crash-report"
SEARCH_PAGES = 3             # open issues looked through for a signature (100 each)
TIMEOUT = 20
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
TOKEN_RE = re.compile(r"^(?:github_pat_[A-Za-z0-9_]{20,255}|gh[pousr]_[A-Za-z0-9]{20,255})$")
SIGNATURE_RE = re.compile(r"frameload-signature: ([0-9a-f]{12})")
OUTCOME_LABELS = {"crashed": "crash", "gpu_hang": "gpu-hang", "out_of_memory": "out-of-memory",
                  "guard_memory": "freeze-guard", "guard_frozen": "freeze-guard", "start_failed": "start-failed",
                  "no_picture": "no-picture", "interrupted": "interrupted"}
NO_TOKEN = "Add a GitHub token in System > Crash Reports first."

_lock = threading.Lock()
_urlopen = urllib.request.urlopen  # tests replace it


class GitHubError(Exception):
    pass


# --------------------------------------------------------------------------- settings
def _config() -> Dict[str, Any]:
    from ..config import Config
    return Config.get().raw.setdefault("reports", {})


def repo() -> str:
    value = str(_config().get("github_repo") or "").strip()
    return value if REPO_RE.match(value) else DEFAULT_REPO


def _token() -> str:
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return ""
    return value if TOKEN_RE.match(value) else ""


def settings() -> Dict[str, Any]:
    """What the dashboard may know: the repository and whether a token is set (its last 4 characters)."""
    token = _token()
    return {"repo": repo(), "default_repo": DEFAULT_REPO, "configured": bool(token),
            "hint": f"...{token[-4:]}" if token else ""}


def save_settings(body: Dict[str, Any]) -> Dict[str, Any]:
    """Sets the repository and/or the token ("token": "" or "clear": true removes it)."""
    from ..config import Config
    if "repo" in body:
        value = str(body.get("repo") or "").strip().strip("/")
        if value.startswith("https://github.com/"):
            value = value[len("https://github.com/"):].strip("/")
        if value.endswith(".git"):
            value = value[:-4]
        if value and not REPO_RE.match(value):
            raise ValueError("The repository must look like owner/name, for example Crypto90/frameload.")
        _config()["github_repo"] = value or DEFAULT_REPO
        Config.get().save()
    if body.get("clear"):
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass
    elif body.get("token"):
        token = str(body["token"]).strip()
        if not TOKEN_RE.match(token):
            raise ValueError("That is not a GitHub token (they start with github_pat_ or ghp_).")
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token + "\n")
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass
    return settings()


# --------------------------------------------------------------------------- GitHub's API
def _request(method: str, path: str, data: Optional[Dict[str, Any]] = None, token: str = "") -> Tuple[int, Any]:
    from .. import __version__
    token = token or _token()
    if not token:
        raise GitHubError(NO_TOKEN)
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(data).encode("utf-8") if data is not None else None)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", f"FrameLoad/{__version__}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, OSError) as e:
        raise GitHubError(f"GitHub cannot be reached: {getattr(e, 'reason', e)}") from None


def _explain(status: int, payload: Any, what: str) -> GitHubError:
    message = (payload or {}).get("message", "") if isinstance(payload, dict) else ""
    if status == 401:
        return GitHubError("GitHub refused the token (wrong, expired or revoked). Create a new one.")
    if status in (403, 404):
        return GitHubError(f"The token cannot {what} in {repo()}. Give it access to that repository "
                           "with the permission Issues: read and write." + (f" GitHub says: {message}" if message else ""))
    if status == 410:
        return GitHubError(f"Issues are turned off in {repo()}.")
    return GitHubError(f"GitHub answered {status}" + (f": {message}" if message else "."))


def check() -> Dict[str, Any]:
    """Test: whether the token can see the repository and whether it has issues. Creates nothing,
    so a token without Issues: write passes here and fails at the first report."""
    try:
        status, payload = _request("GET", f"/repos/{repo()}")
        if status != 200:
            raise _explain(status, payload, "see issues")
        if not payload.get("has_issues", True):
            raise GitHubError(f"Issues are turned off in {repo()}.")
    except GitHubError as e:
        return {"success": False, "error": str(e), **settings()}
    return {"success": True, "message": f"FrameLoad can reach {payload.get('full_name') or repo()}.", **settings()}


# --------------------------------------------------------------------------- the report
def _state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("signatures", {})
    data.setdefault("sent", {})
    return data


def _save_state(data: Dict[str, Any]) -> None:
    sent = data.get("sent") or {}
    if len(sent) > 500:  # the oldest go first
        data["sent"] = dict(sorted(sent.items(), key=lambda kv: kv[1].get("time", 0))[-500:])
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, STATE_FILE)


def _main_finding(record: Optional[Dict[str, Any]], findings: List[Dict[str, Any]]) -> str:
    for f in findings:
        if f.get("severity") in ("error", "warn"):
            return str(f.get("title", ""))
    return ""


def signature(pkg: str, dep: Dict[str, Any], record: Optional[Dict[str, Any]], findings: List[Dict[str, Any]]) -> str:
    """The same problem of the same game version gives the same signature. Only fixed strings go in
    (a cause can name seconds or memory sizes, finding titles do not)."""
    parts = [pkg, str(dep.get("version_code") or "")]
    if record:
        parts += [str(record.get("outcome", "")), str(record.get("signal", "")), str(record.get("library", ""))]
        if not record.get("library"):
            parts.append(_main_finding(record, findings))
    else:
        parts += ["live", _main_finding(None, findings)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def _fit(report: str, room: int) -> str:
    if len(report) <= room:
        return report
    head = min(8000, room // 4)
    return report[:head] + "\n\n[... cut to fit GitHub's size limit; Save Log has everything ...]\n\n" + report[-(room - head - 100):]


def _compose(pkg: str, dep: Dict[str, Any], record: Optional[Dict[str, Any]], findings: List[Dict[str, Any]],
             report: str, note: str, sig: str, again_of: Optional[int] = None, comment: bool = False) -> Tuple[str, str]:
    from .. import __version__
    from .sessions import redact
    title_name = dep.get("title") or pkg
    version = dep.get("version_name") or ""
    if record:
        what = record.get("headline") or record.get("outcome") or "Session report"
    else:
        what = f"{title_name}: {_main_finding(None, findings) or 'launch log'}"
    title = f"{what} - {pkg} {version}".strip()[:TITLE_MAX]

    lines = []
    if comment:
        lines += ["**Seen again.**", ""]
    lines += [f"**Game:** {title_name} (`{pkg}`) {version} (code {dep.get('version_code', '?')}), "
              f"{'VR' if dep.get('is_vr', True) else '2D'}"]
    if record:
        lines.append(f"**What happened:** {record.get('headline', '')}")
        if record.get("cause"):
            lines.append(f"**Cause:** {record['cause']}")
        if record.get("end"):
            lines.append(f"**Ended:** {time.strftime('%Y-%m-%d %H:%M', time.localtime(float(record['end'])))}"
                         f" after {int(record.get('duration') or 0)} s")
    else:
        lines.append("**What happened:** no finished session recorded; this is the current launch log.")
    lines.append(f"**FrameLoad:** {__version__}")
    if again_of:
        lines.append(f"**Earlier issue:** #{again_of} (closed)")
    note = redact(note.strip())[:NOTE_MAX]
    if note:
        lines += ["", "**Note from the player:**", "> " + note.replace("\n", "\n> ")]
    head = "\n".join(lines) + "\n\n"
    tail = f"\n\n<sub>Sent from FrameLoad. frameload-signature: {sig}</sub>\n"
    fence = _fence(report)
    room = BODY_MAX - len(head) - len(tail) - 2 * len(fence) - 80
    report = _fit(report, room)
    body = (head + f"<details><summary>Report ({max(1, round(len(report) / 1024))} KB)</summary>\n\n"
            f"{fence}text\n{report.rstrip()}\n{fence}\n\n</details>" + tail)
    return redact(title), body[:BODY_MAX]


def _find_open_issue(sig: str) -> Optional[Dict[str, Any]]:
    """An open issue (not a pull request) whose body carries the signature."""
    marker = f"frameload-signature: {sig}"
    for page in range(1, SEARCH_PAGES + 1):
        status, payload = _request("GET", f"/repos/{repo()}/issues?state=open&per_page=100&page={page}")
        if status != 200:
            raise _explain(status, payload, "read issues")
        if not isinstance(payload, list):
            return None
        for issue in payload:
            if not issue.get("pull_request") and marker in (issue.get("body") or ""):
                return issue
        if len(payload) < 100:
            return None
    return None


def send(pkg: str, source: str = "session", note: str = "") -> Dict[str, Any]:
    """Sends the game's report: a new issue, or a comment on the open issue with the same signature.
    The same recorded session is sent once; sending it again answers with the issue it went to."""
    from . import launchlog, sessions
    from .installed import InstalledManager

    if not _token():
        return {"success": False, "error": NO_TOKEN}
    dep = InstalledManager.get_game(pkg)
    if not dep:
        return {"success": False, "error": f"Game {pkg} is not installed."}
    record = sessions.load(pkg)
    if source == "live" and record and record.get("start") != sessions.current_start(dep):
        record = None  # the live log is a newer session than the record
    if source != "live" and not record:
        source = "live"
    key = f"{pkg}:{record.get('end')}" if record else ""

    with _lock:
        state = _state()
        if key and key in state["sent"]:
            done = state["sent"][key]
            return {"success": True, "already": True, "number": done.get("number"), "url": done.get("url"),
                    "comment": bool(done.get("comment")), "repo": repo()}
        report = sessions.report_text(pkg, source=source)
        findings = (record or {}).get("findings") or launchlog.diagnose(report.splitlines())
        sig = signature(pkg, dep, record, findings)
        try:
            issue, again_of = None, None
            known = state["signatures"].get(f"{repo()}#{sig}")
            if known:
                status, payload = _request("GET", f"/repos/{repo()}/issues/{known['number']}")
                if status == 200 and payload.get("state") == "open":
                    issue = payload
                elif status == 200:
                    again_of = known["number"]
            if issue is None and again_of is None:
                issue = _find_open_issue(sig)
            if issue is not None:
                _, body = _compose(pkg, dep, record, findings, report, note, sig, comment=True)
                status, payload = _request("POST", f"/repos/{repo()}/issues/{issue['number']}/comments", {"body": body})
                if status != 201:
                    raise _explain(status, payload, "comment on issues")
                number, url, comment = issue["number"], payload.get("html_url") or issue.get("html_url"), True
            else:
                title, body = _compose(pkg, dep, record, findings, report, note, sig, again_of=again_of)
                labels = [LABEL] + ([OUTCOME_LABELS[record["outcome"]]] if record and record.get("outcome") in OUTCOME_LABELS else [])
                status, payload = _request("POST", f"/repos/{repo()}/issues", {"title": title, "body": body, "labels": labels})
                if status == 422:  # a label GitHub would not take: the report matters more
                    status, payload = _request("POST", f"/repos/{repo()}/issues", {"title": title, "body": body})
                if status != 201:
                    raise _explain(status, payload, "create issues")
                number, url, comment = payload["number"], payload.get("html_url"), False
        except GitHubError as e:
            return {"success": False, "error": str(e), "repo": repo()}
        state["signatures"][f"{repo()}#{sig}"] = {"number": number, "url": payload.get("html_url") if not comment else issue.get("html_url"),
                                                  "time": int(time.time())}
        if key:
            state["sent"][key] = {"number": number, "url": url, "comment": comment, "time": int(time.time())}
        try:
            _save_state(state)
        except OSError:
            pass
    print(f"[FrameLoad] Report of {pkg} sent to {repo()} #{number}{' (comment)' if comment else ''}")
    return {"success": True, "number": number, "url": url, "comment": comment, "repo": repo(), "signature": sig}
