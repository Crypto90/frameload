"""On-device porting of Quest games, by driving FramePort's command line on the headset.

A game built for Meta's runtime needs three things FrameLoad has no code of its own for: OVRPort's
conversion to generic OpenXR (a Java tool), FramePort's native FrameBridge adapter, and re-signing.
FramePort (GPL-3.0, github.com/spoopyghosty0/frameport) publishes all of it behind a command line
that runs on Linux ARM64, so FrameLoad installs that into its own folder and calls:

    frameport tools install            # Java runtime, OVRPort, apksigner (FramePort downloads them)
    frameport scan <folder>            # analyse the APK, pick the patches
    frameport build <package> --outdir <dir>

FRAMEPORT_HOME keeps FramePort's data inside FrameLoad's folder and out of the user's own FramePort.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import CACHE_DIR, FRAMELOAD_DIR, Config
from .apk_analysis import inspect_apk

FRAMEPORT_REPO = "spoopyghosty0/frameport"
RELEASE_API = f"https://api.github.com/repos/{FRAMEPORT_REPO}/releases/latest"
VENV_DIR = os.path.join(FRAMELOAD_DIR, "frameport-venv")
FRAMEPORT_HOME = os.path.join(FRAMELOAD_DIR, "frameport-home")
STAGING_DIR = os.path.join(CACHE_DIR, "port-source")
OUTPUT_DIR = os.path.join(CACHE_DIR, "ported")
UNPORTED_APK = "unported.apk"
KEY_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "Documents", "FrameLoad-signing-keys")
# FramePort dependencies that have no ready-made ARM64 package and need a C compiler, which SteamOS
# does not ship. FramePort imports them only inside the patches that use them (UnityPy: "Unity: turn
# off MSAA"), so its command line works without them.
OPTIONAL_DEPENDENCIES = ("unitypy",)
LIMITED_MARKER = os.path.join(VENV_DIR, "frameload-limited.txt")
STATE_FILE = os.path.join(FRAMELOAD_DIR, "porting_state.json")
RETRY_SECONDS = 6 * 3600           # after a failed automatic setup (no network, for instance)
UPDATE_CHECK_SECONDS = 7 * 24 * 3600  # FramePort gains per-game fixes often

Log = Callable[[str], None]


class PortingError(RuntimeError):
    pass


def _venv_cli() -> str:
    return os.path.join(VENV_DIR, "Scripts" if os.name == "nt" else "bin", "frameport.exe" if os.name == "nt" else "frameport")


def find_cli() -> Optional[List[str]]:
    """The FramePort command to run: a configured one, FrameLoad's own install, or one on PATH."""
    configured = Config.get().get("porting", {}).get("frameport_cli")
    if configured:
        return [str(c) for c in configured] if isinstance(configured, list) else [str(configured)]
    if os.path.isfile(_venv_cli()):
        return [_venv_cli()]
    found = shutil.which("frameport")
    return [found] if found else None


def _env() -> Dict[str, str]:
    env = dict(os.environ)
    env["FRAMEPORT_HOME"] = FRAMEPORT_HOME
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _run(cmd: List[str], log: Log, timeout: int) -> Tuple[int, str]:
    """Runs a command, streaming its output to the log. Returns (exit code, output)."""
    log("$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_env(),
                                text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise PortingError(f"Could not start {cmd[0]}: {e}") from e
    lines: List[str] = []
    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            lines.append(line)
            log(line)
        code = proc.wait()
    finally:
        killer.cancel()
        if proc.stdout:
            proc.stdout.close()
    return code, "\n".join(lines)


def status() -> Dict[str, Any]:
    """Whether porting is set up on this machine."""
    cli = find_cli()
    info: Dict[str, Any] = {
        "installed": False,
        "command": cli,
        "version": "",
        "tools_ready": False,
        "tools": [],
        "managed": bool(cli and cli[0] == _venv_cli()),
        "limited": "",
    }
    if info["managed"] and os.path.isfile(LIMITED_MARKER):
        try:
            with open(LIMITED_MARKER, "r", encoding="utf-8") as f:
                info["limited"] = f.read().strip()
        except OSError:
            pass
    if not cli:
        return info
    try:
        ver = subprocess.run(cli + ["--version"], capture_output=True, text=True, timeout=60, env=_env())
        match = re.search(r"FramePort\s+(\S+)", ver.stdout)
        info["installed"] = ver.returncode == 0 and bool(match)
        info["version"] = match.group(1) if match else ""
        if info["installed"]:
            tools = subprocess.run(cli + ["tools", "status"], capture_output=True, text=True, timeout=120, env=_env())
            for line in tools.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    info["tools"].append({"name": parts[0], "installed": parts[1] == "installed"})
            needed = [t for t in info["tools"] if t["name"].lower() != "revive"]
            info["tools_ready"] = bool(needed) and all(t["installed"] for t in needed)
    except (OSError, subprocess.SubprocessError) as e:
        info["error"] = str(e)
    return info


def latest_wheel() -> Tuple[str, str]:
    """(version, download URL) of FramePort's command-line wheel in its newest release."""
    req = urllib.request.Request(RELEASE_API, headers={"User-Agent": "FrameLoad", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.load(resp)
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("frameport-") and name.endswith("-py3-none-any.whl"):
            return release.get("tag_name", ""), asset["browser_download_url"]
    raise PortingError("FramePort's latest release has no command-line wheel.")


def _keys_dir() -> str:
    return os.path.join(FRAMEPORT_HOME, "overport-workspace", "signatures")


def backup_signing_keys() -> str:
    """Copies the per-game signing keys out of FrameLoad's folder. Returns the folder, '' if none."""
    source = _keys_dir()
    keys = [n for n in os.listdir(source) if n.endswith(".keystore")] if os.path.isdir(source) else []
    if not keys:
        return ""
    os.makedirs(KEY_BACKUP_DIR, exist_ok=True)
    for name in keys:
        shutil.copy2(os.path.join(source, name), os.path.join(KEY_BACKUP_DIR, name))
    return KEY_BACKUP_DIR


def _install_without_optional(pip: List[str], venv_python: str, wheel: str, log: Log) -> Tuple[int, str]:
    """Second attempt: FramePort itself, then every dependency except the ones that need a compiler."""
    log("A dependency could not be built on this system (no C compiler). Installing FramePort without it...")
    code, out = _run(pip + ["--no-deps", wheel], log, 900)
    if code:
        return code, out
    listing = subprocess.run(
        [venv_python, "-c", "from importlib.metadata import requires; print('\\n'.join(requires('frameport') or []))"],
        capture_output=True, text=True, timeout=60, env=_env())
    wanted, skipped = [], []
    for line in listing.stdout.splitlines():
        requirement, _, marker = line.partition(";")
        if "extra" in marker:  # development extras
            continue
        name = re.match(r"[A-Za-z0-9_.\-]+", requirement.strip())
        if not name:
            continue
        if name.group(0).lower() in OPTIONAL_DEPENDENCIES:
            skipped.append(name.group(0))
        else:
            wanted.append(requirement.strip())
    if not wanted:
        return 1, "FramePort's dependency list could not be read: " + listing.stderr[-300:]
    code, out = _run(pip + wanted, log, 1800)
    if not code:
        note = (f"Installed without {', '.join(skipped) or 'an optional dependency'}: "
                "FramePort's \"Unity: turn off MSAA\" fix is not available on this system.")
        with open(LIMITED_MARKER, "w", encoding="utf-8") as f:
            f.write(note)
        log(note)
    return code, out


def _pip_install(wheel: str, log: Log) -> None:
    """Installs or upgrades FramePort's wheel in FrameLoad's own Python environment."""
    venv_python = os.path.join(os.path.dirname(_venv_cli()), "python.exe" if os.name == "nt" else "python")
    if not os.path.isfile(venv_python):
        code, out = _run([sys.executable or "python3", "-m", "venv", VENV_DIR], log, 300)
        if code:
            raise PortingError("Could not create a Python environment for FramePort: " + out[-400:])
    pip = [venv_python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--upgrade"]
    code, out = _run(pip + [wheel], log, 1800)
    if code:
        code, out = _install_without_optional(pip, venv_python, wheel, log)
    if code or not os.path.isfile(_venv_cli()):
        raise PortingError("pip could not install FramePort: " + out[-600:])


def setup(log: Log) -> Dict[str, Any]:
    """Installs FramePort's command line into FrameLoad's folder and lets it fetch its tools."""
    os.makedirs(FRAMEPORT_HOME, exist_ok=True)
    cli = find_cli()
    if not cli:
        version, wheel = latest_wheel()
        log(f"Installing FramePort {version} (command line) into {VENV_DIR}")
        try:
            _pip_install(wheel, log)
        except PortingError:
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            raise
        cli = [_venv_cli()]
    log("Downloading FramePort's tools (Java runtime, OVRPort, apksigner)...")
    code, out = _run(cli + ["tools", "install"], log, 3600)
    if code:
        raise PortingError("FramePort could not install its tools: " + out[-600:])
    if os.path.isdir(KEY_BACKUP_DIR):  # keys saved by an earlier uninstall
        _run(cli + ["tools", "import-keys", KEY_BACKUP_DIR], log, 120)
    return status()


def update(log: Log, wheel: str, version: str) -> Dict[str, Any]:
    """Moves FrameLoad's own FramePort to a newer release and refreshes its tools."""
    log(f"Updating FramePort to {version}")
    _pip_install(wheel, log)
    code, out = _run([_venv_cli(), "tools", "install", "--update"], log, 3600)
    if code:
        log("FramePort's tools could not be refreshed; the installed ones stay in use.")
    result = status()
    # A newer FramePort may port what the previous one could not.
    if clear_failed_ports() and is_auto():
        result["ported"] = port_pending(log)
    return result


def _stage(apk_path: str, package: str) -> str:
    """A folder holding only this game's APK, the layout `frameport scan` expects."""
    folder = os.path.join(STAGING_DIR, package)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    target = os.path.join(folder, f"{package}.apk")
    try:
        os.link(apk_path, target)
    except OSError:
        shutil.copy2(apk_path, target)
    return folder


def port_apk(apk_path: str, package: str, log: Log) -> str:
    """Converts one Quest APK for the Steam Frame and returns the path of the signed result."""
    cli = find_cli()
    if not cli:
        raise PortingError("FramePort is not set up yet.")
    if not os.path.isfile(apk_path):
        raise PortingError(f"APK not found: {apk_path}")

    folder = _stage(apk_path, package)
    outdir = os.path.join(OUTPUT_DIR, package)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir)
    try:
        code, out = _run(cli + ["scan", folder], log, 1800)
        if code:
            raise PortingError("FramePort could not analyse the game: " + out[-600:])
        code, out = _run(cli + ["build", package, "--outdir", outdir, "--verbose"], log, 7200)
        built = re.search(r"^" + re.escape(package) + r": (OK|CHECKS FAILED) -> (.+)$", out, re.M)
        if not built:
            # FramePort prints one line with the reason; the full output is in the job's log.
            reason = re.search(r"^" + re.escape(package) + r": FAILED (.+)$", out, re.M)
            raise PortingError("FramePort could not port this game: "
                               + (reason.group(1).strip() if reason else out[-400:]))
        result = built.group(2).strip()
        if not os.path.isfile(result):
            raise PortingError(f"FramePort reported {result}, but that file does not exist.")
        if built.group(1) != "OK":
            log("FramePort's own checks reported problems with this build; it may not start.")
        if not inspect_apk(result).framebridge:
            raise PortingError("The built APK does not contain the FrameBridge adapter.")
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def port_installed_game(package: str, log: Log) -> Dict[str, Any]:
    """Ports a game that is already installed and replaces its APK. Saves and OBB files stay."""
    from ..manager.installed import InstalledManager
    from .lepton_quest import LeptonInstaller

    dep = InstalledManager.get_game(package)
    if not dep or dep.get("kind", "quest") != "quest":
        raise PortingError(f"{package} is not an installed Quest game.")
    base = dep.get("base") or dep.get("anchor")
    anchor = dep.get("anchor") or base
    current = os.path.join(base, "lepton-app", "game.apk")
    original = os.path.join(base, UNPORTED_APK)
    source = original if os.path.isfile(original) else current

    ported = port_apk(source, package, log)

    # Keep the untouched APK: a later FramePort version may port the game better.
    if not os.path.isfile(original):
        try:
            os.link(current, original)
        except OSError:
            shutil.copy2(current, original)
    log("Installing the ported build...")
    result = LeptonInstaller.install_quest_game(
        package_name=package, title=dep.get("title", package), apk_path=ported,
        target_anchor=os.path.dirname(anchor), device_id=dep.get("device_id", "internal"))
    shutil.rmtree(os.path.dirname(ported), ignore_errors=True)
    log(f"Done: {result['compat'].get('label', '')}")
    return result


def is_auto() -> bool:
    """Whether Quest games that need it are ported right after they are installed."""
    return bool(Config.get().get("porting", {}).get("auto", True))


def needs_port(game: Dict[str, Any]) -> bool:
    return game.get("kind") == "quest" and (game.get("compat") or {}).get("level") == "needs_port"


def _set_flags(package: str, **flags: Any) -> None:
    """Records porting state (port_pending, port_failed, port_error) in a game's deployment.json."""
    from ..manager.installed import InstalledManager

    dep = InstalledManager.get_game(package)
    if not dep or all(dep.get(key) == value for key, value in flags.items()):
        return
    dep.update(flags)
    path = os.path.join(dep["anchor"], "deployment.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in dep.items() if k not in ("device_name", "is_external")}, f, indent=2)
    os.replace(path + ".tmp", path)


def _set_pending(package: str, pending: bool) -> None:
    _set_flags(package, port_pending=pending)


def pending_games() -> List[Dict[str, Any]]:
    """Installed Quest games that still need porting and have not already failed to port.

    With automatic porting on that is every such game, wherever it came from; with it off, only
    games that were explicitly queued."""
    from ..manager.installed import InstalledManager

    automatic = is_auto()
    found = []
    for game in InstalledManager.list_installed():
        dep = InstalledManager.get_game(game["package"]) or {}
        if needs_port(dep) and not dep.get("port_failed") and (automatic or dep.get("port_pending")):
            found.append({"package": game["package"], "title": dep.get("title", game["package"])})
    return found


def port_and_record(package: str, log: Log) -> Dict[str, Any]:
    """Ports one installed game. A failure is remembered on the game, so automatic porting does not
    repeat a port that takes minutes and fails the same way until FramePort changes or the user asks."""
    try:
        return port_installed_game(package, log)
    except Exception as e:
        _set_flags(package, port_failed=True, port_error=str(e)[:500], port_pending=False)
        raise


def clear_failed_ports() -> int:
    """Lets games that failed to port be tried again (after a FramePort update)."""
    from ..manager.installed import InstalledManager

    cleared = 0
    for game in InstalledManager.list_installed():
        dep = InstalledManager.get_game(game["package"]) or {}
        if dep.get("port_failed"):
            _set_flags(game["package"], port_failed=False, port_error="")
            cleared += 1
    return cleared


def auto_setup_enabled() -> bool:
    """Whether FrameLoad fetches and updates the porting tools by itself."""
    return bool(Config.get().get("porting", {}).get("auto_setup", True))


def _state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(**changes: Any) -> None:
    data = _state()
    data.update(changes)
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def ensure_ready() -> Optional[Dict[str, Any]]:
    """Starts the one-time setup in the background unless porting is ready or already being set up.
    Returns the setup job, or None when there is nothing to do."""
    running = PortingJobs.active()
    if running and running["kind"] == "setup":
        return running
    current = status()
    if current["installed"] and current["tools_ready"]:
        return None
    _save_state(last_attempt=time.time())
    return PortingJobs.start("setup", setup_and_port_pending, queue=True)


def background_maintenance() -> Optional[Dict[str, Any]]:
    """Run shortly after FrameLoad starts: sets porting up the first time and keeps FramePort current,
    so nobody has to press a button. Only on a Steam Frame, and only when allowed in the settings."""
    from ..system.steamos import is_steam_frame

    if not auto_setup_enabled() or not is_steam_frame():
        return None
    state = _state()
    now = time.time()
    current = status()
    if not (current["installed"] and current["tools_ready"]):
        if now - state.get("last_attempt", 0) < RETRY_SECONDS:
            return None
        return ensure_ready()
    if is_auto() and pending_games() and not PortingJobs.active():  # "blocked" games are not "needs_port"
        # Games already in the library (installed by an older version, or downloaded) are ported too.
        return PortingJobs.start("port", lambda log: {"ported": port_pending(log)}, queue=True)
    if not current["managed"] or now - state.get("last_update_check", 0) < UPDATE_CHECK_SECONDS:
        return None
    _save_state(last_update_check=now)
    try:
        version, wheel = latest_wheel()
    except Exception:
        return None
    if version.lstrip("vV") == current["version"]:
        return None
    return PortingJobs.start("update", lambda log: update(log, wheel, version), queue=True)


def auto_port(installed: Dict[str, Any]) -> Dict[str, Any]:
    """Called after an install and before a launch: ports the game when it needs it.

    If porting has not been set up yet, the game is marked as waiting and (unless switched off) the
    setup starts now; the game is ported as soon as it finishes."""
    if not needs_port(installed):
        return {"needed": False, "started": False}
    package = installed["package"]
    if not is_auto():
        return {"needed": True, "started": False, "reason": "disabled"}
    if installed.get("port_failed"):
        return {"needed": True, "started": False, "reason": "failed", "error": installed.get("port_error", "")}
    for job in PortingJobs._jobs.values():  # already being ported: show that job instead of queueing again
        if job["kind"] == "port" and job["package"] == package and job["status"] in ("running", "queued"):
            return {"needed": True, "started": True, "job": PortingJobs.public(job)}
    current = status()
    if not (current["installed"] and current["tools_ready"]):
        _set_pending(package, True)
        if not auto_setup_enabled():
            return {"needed": True, "started": False, "reason": "not_set_up"}
        job = ensure_ready()
        return {"needed": True, "started": bool(job), "job": job, "reason": "setting_up"}
    job = PortingJobs.start("port", lambda log: port_and_record(package, log), package=package, queue=True)
    return {"needed": True, "started": True, "job": job}


def port_pending(log: Log) -> List[str]:
    """Ports every game that is waiting to be ported. Returns the packages that worked."""
    done = []
    for game in pending_games():
        log(f"Porting {game['title']}...")
        try:
            port_and_record(game["package"], log)
            done.append(game["package"])
        except Exception as e:  # one failing game must not stop the others
            log(f"{game['title']}: {e}")
    return done


def setup_and_port_pending(log: Log) -> Dict[str, Any]:
    result = setup(log)
    if is_auto():
        result["ported"] = port_pending(log)
    return result


class PortingJobs:
    """Background jobs for setup and porting; one runs at a time (they are heavy on a headset)."""
    _lock = threading.Lock()
    _jobs: Dict[str, Dict[str, Any]] = {}
    _busy = threading.Lock()

    @classmethod
    def start(cls, kind: str, work: Callable[[Log], Any], package: str = "", queue: bool = False) -> Dict[str, Any]:
        """Starts a job. With queue=True it waits its turn behind a running one instead of being refused."""
        with cls._lock:
            busy = any(job["status"] in ("running", "queued") for job in cls._jobs.values())
            if busy and not queue:
                raise PortingError("Another porting job is still running.")
            job = {"id": uuid.uuid4().hex[:12], "kind": kind, "package": package,
                   "status": "queued" if busy else "running",
                   "log": [], "error": "", "result": None, "started": time.time(), "finished": 0.0}
            cls._jobs[job["id"]] = job
            for old in sorted(cls._jobs.values(), key=lambda j: j["started"])[:-10]:
                cls._jobs.pop(old["id"], None)

        def log(line: str) -> None:
            job["log"].append(line)
            del job["log"][:-2000]

        def run() -> None:
            with cls._busy:
                job["status"] = "running"
                try:
                    job["result"] = work(log)
                    job["status"] = "done"
                except Exception as e:  # reported to the user through the job
                    job["error"] = str(e)
                    job["status"] = "error"
                    log(f"Failed: {e}")
                finally:
                    job["finished"] = time.time()

        threading.Thread(target=run, daemon=True, name=f"porting-{kind}").start()
        return cls.public(job)

    @classmethod
    def last_error(cls, kind: str) -> str:
        """The error of the most recent job of this kind, '' if it worked or never ran."""
        jobs = sorted((j for j in cls._jobs.values() if j["kind"] == kind), key=lambda j: j["started"])
        return jobs[-1]["error"] if jobs and jobs[-1]["status"] == "error" else ""

    @classmethod
    def get(cls, job_id: str) -> Optional[Dict[str, Any]]:
        job = cls._jobs.get(job_id)
        return cls.public(job) if job else None

    @classmethod
    def active(cls) -> Optional[Dict[str, Any]]:
        for wanted in ("running", "queued"):
            for job in cls._jobs.values():
                if job["status"] == wanted:
                    return cls.public(job)
        return None

    @staticmethod
    def public(job: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: job[k] for k in ("id", "kind", "package", "status", "error", "started", "finished")}
        out["log"] = job["log"][-400:]
        result = job["result"]
        out["result"] = result if isinstance(result, dict) else None
        return out
