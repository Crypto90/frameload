"""Download queue manager with resumption and speed tracking."""
from __future__ import annotations

import os
import queue
import shutil
import threading
import time
import urllib.request
from typing import Callable, Dict, List, Optional

from ..config import CACHE_DIR, Config, DATA_DIR
from .extractor import extract_archive
from .models import CatalogGame, DownloadTask

USER_AGENT = "FrameLoad/1.0 (Steam Frame; Linux arm64)"


class Downloader:
    _instance: Downloader | None = None

    def __init__(self) -> None:
        self.config = Config.get()
        self.tasks: Dict[str, DownloadTask] = {}
        self.active_task_id: Optional[str] = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_complete_hook: Optional[Callable[[DownloadTask], None]] = None
        self._start_worker()

    @classmethod
    def get(cls) -> Downloader:
        if cls._instance is None:
            cls._instance = Downloader()
        return cls._instance

    def set_complete_hook(self, hook: Callable[[DownloadTask], None]) -> None:
        self._on_complete_hook = hook

    def _start_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()

    def add_to_queue(self, game: CatalogGame) -> DownloadTask:
        with self._lock:
            if game.id in self.tasks and self.tasks[game.id].status in ("downloading", "queued"):
                return self.tasks[game.id]

            task = DownloadTask(
                id=game.id,
                game=game,
                status="queued",
                total_bytes=game.size_bytes
            )
            self.tasks[game.id] = task
            self._queue.put(game.id)
            return task

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task_id == self.active_task_id:
                task.status = "canceled"
                # Download thread checks status
            else:
                task.status = "canceled"
            return True

    def get_all_tasks(self) -> List[Dict]:
        with self._lock:
            return [t.to_dict() for t in self.tasks.values()]

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return self.tasks.get(task_id)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task_id = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            with self._lock:
                task = self.tasks.get(task_id)
                if not task or task.status == "canceled":
                    self._queue.task_done()
                    continue
                self.active_task_id = task_id
                task.status = "downloading"

            try:
                self._execute_download(task)
            except Exception as e:
                task.status = "error"
                task.error_message = str(e)
                print(f"[FrameLoad] Download error for {task.game.name}: {e}")
            finally:
                with self._lock:
                    self.active_task_id = None
                self._queue.task_done()

    def _execute_download(self, task: DownloadTask) -> None:
        from .vrp_mirror import VrpMirror

        mirror = VrpMirror()
        if not mirror.base_url:
            mirror.update_mirror_config()

        game_dir = os.path.join(CACHE_DIR, task.id)
        os.makedirs(game_dir, exist_ok=True)

        # In Rookie / VRP public mirrors, files are under baseUri/<id>/<id>.7z.001 etc.
        # Or baseUri/<id>.7z
        # Let's probe for the multi-part or single archive
        part_idx = 1
        downloaded_parts: List[str] = []
        base_uri = mirror.base_url.rstrip("/")

        # First probe for <id>.7z or <id>/<id>.7z.001
        first_url = f"{base_uri}/{task.id}/{task.id}.7z.{part_idx:03d}"
        is_multipart = True

        try:
            req = urllib.request.Request(first_url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as r:
                if r.status != 200:
                    is_multipart = False
        except Exception:
            is_multipart = False

        if not is_multipart:
            # Try single file format
            single_url = f"{base_uri}/{task.id}.7z"
            dest_file = os.path.join(game_dir, f"{task.id}.7z")
            if not self._download_file(single_url, dest_file, task):
                if task.status == "canceled":
                    return
                # Also try first_url in case HEAD was blocked
                if not self._download_file(first_url, os.path.join(game_dir, f"{task.id}.7z.001"), task):
                    raise RuntimeError(f"Could not download game archive from {base_uri}")
                downloaded_parts.append(os.path.join(game_dir, f"{task.id}.7z.001"))
            else:
                downloaded_parts.append(dest_file)
        else:
            # Download all parts
            while True:
                if task.status == "canceled":
                    return
                part_name = f"{task.id}.7z.{part_idx:03d}"
                part_url = f"{base_uri}/{task.id}/{part_name}"
                dest_file = os.path.join(game_dir, part_name)

                # Check if this part exists on remote
                try:
                    head_req = urllib.request.Request(part_url, method="HEAD", headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(head_req, timeout=6) as hr:
                        if hr.status != 200:
                            break
                except Exception:
                    # No more parts
                    break

                if not self._download_file(part_url, dest_file, task):
                    if task.status == "canceled":
                        return
                    raise RuntimeError(f"Failed to download archive part {part_name}")

                downloaded_parts.append(dest_file)
                part_idx += 1

        if not downloaded_parts:
            raise RuntimeError("No files were downloaded.")

        # Decompression stage
        task.status = "decompressing"
        task.progress = 1.0
        extract_dest = os.path.join(DATA_DIR, task.game.release_name)
        os.makedirs(extract_dest, exist_ok=True)

        primary_archive = downloaded_parts[0]
        success = extract_archive(
            archive_path=primary_archive,
            output_dir=extract_dest,
            password=mirror.password,
            progress_callback=lambda msg: setattr(task, "error_message", msg)
        )

        if not success:
            task.status = "error"
            task.error_message = "Decompression failed. The download may be corrupted."
            return

        task.extracted_path = extract_dest
        task.status = "ready_to_install"

        # Check for APK in extracted files
        for root, _, files in os.walk(extract_dest):
            for f in files:
                if f.endswith(".apk"):
                    task.target_apk = os.path.join(root, f)
                    break
            if task.target_apk:
                break

        # Delete cache archives if configured
        if self.config["download"].get("delete_cache_after_install", True):
            try:
                shutil.rmtree(game_dir, ignore_errors=True)
            except OSError:
                pass

        # Trigger auto-install hook if present
        if self._on_complete_hook:
            try:
                self._on_complete_hook(task)
            except Exception as e:
                task.status = "error"
                task.error_message = f"Install failed: {e}"
        else:
            task.status = "completed"

    def _download_file(self, url: str, dest_path: str, task: DownloadTask) -> bool:
        """Downloads a single file with resume support and speed calculation."""
        existing_size = os.path.getsize(dest_path) if os.path.isfile(dest_path) else 0
        headers = {"User-Agent": USER_AGENT}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
                content_len = resp.headers.get("Content-Length")
                file_total = int(content_len) if content_len else 0

                if status == 206:  # Partial Content
                    mode = "ab"
                else:
                    mode = "wb"
                    existing_size = 0

                start_time = time.time()
                last_time = start_time
                bytes_in_interval = 0
                chunk_size = self.config["download"].get("chunk_size_kb", 1024) * 1024

                with open(dest_path, mode) as out_f:
                    while True:
                        if task.status == "canceled":
                            return False

                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        chunk_len = len(chunk)
                        existing_size += chunk_len
                        bytes_in_interval += chunk_len
                        task.downloaded_bytes = existing_size

                        now = time.time()
                        dt = now - last_time
                        if dt >= 0.5:
                            speed = bytes_in_interval / dt
                            # Exponential Moving Average for smooth speed display
                            task.speed_bps = task.speed_bps * 0.7 + speed * 0.3 if task.speed_bps else speed
                            bytes_in_interval = 0
                            last_time = now

                            if task.total_bytes > 0:
                                task.progress = min(1.0, task.downloaded_bytes / task.total_bytes)
                                remaining_bytes = max(0, task.total_bytes - task.downloaded_bytes)
                                task.eta_seconds = int(remaining_bytes / max(task.speed_bps, 1.0))

            return True
        except Exception as e:
            print(f"[FrameLoad] Download chunk error for {url}: {e}")
            return False
