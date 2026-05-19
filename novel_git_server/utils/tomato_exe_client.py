"""Client for Tomato-Novel-Downloader exe running in --server mode.

Manages the exe lifecycle: auto-start, configure, submit download jobs,
poll progress, and read the generated TXT output.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 18423
_DEFAULT_HOST = "127.0.0.1"
_POLL_INTERVAL = 3
_MAX_POLL_SECONDS = 600
_SHARED_CLIENT_LOCK = threading.Lock()
_SHARED_CLIENT: "TomatoExeClient | None" = None


class TomatoJobCancelled(RuntimeError):
    """Raised when a Tomato download job is cancelled by the caller."""


class TomatoExeClient:
    """HTTP client for a running Tomato-Novel-Downloader --server instance."""

    def __init__(
        self,
        exe_path: str,
        data_dir: str | None = None,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
    ) -> None:
        self.exe_path = exe_path
        self.data_dir = data_dir
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self._process: subprocess.Popen | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_running(self, timeout: float = 15) -> None:
        """Start the exe server if not already reachable."""
        if self._is_reachable():
            return
        self._start(timeout)

    def _is_reachable(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/status", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _start(self, timeout: float = 15) -> None:
        cmd = [self.exe_path, "--server"]
        if self.data_dir:
            cmd.extend(["--data-dir", self.data_dir])

        logger.info("Starting tomato exe server: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._is_reachable():
                logger.info("Tomato exe server ready at %s", self.base_url)
                return
            time.sleep(0.5)
        raise RuntimeError(f"Tomato exe server did not start within {timeout}s")

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, novel_format: str = "txt", bulk_files: bool = False) -> None:
        resp = requests.post(
            f"{self.base_url}/api/config",
            json={"novel_format": novel_format, "bulk_files": bulk_files},
            timeout=5,
        )
        resp.raise_for_status()

    def set_save_path(self, save_path: str) -> None:
        resp = requests.post(
            f"{self.base_url}/api/config",
            json={"save_path": save_path},
            timeout=5,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_book(
        self,
        book_id: str,
        poll_interval: float = _POLL_INTERVAL,
        max_wait: float = _MAX_POLL_SECONDS,
        on_progress: Any | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Submit a download job and wait for completion.

        Returns the final job dict with state, progress, etc.

        on_progress: optional callback(saved, total, state) called each poll tick.
        """
        if cancel_event and cancel_event.is_set():
            self.stop()
            raise TomatoJobCancelled(f"Download job for {book_id} cancelled")

        # Submit job
        try:
            resp = requests.post(
                f"{self.base_url}/api/jobs",
                json={"book_id": book_id},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            if cancel_event and cancel_event.is_set():
                self.stop()
                raise TomatoJobCancelled(f"Download job for {book_id} cancelled") from exc
            raise
        job = resp.json()
        job_id = job["id"]
        logger.info("Download job submitted: id=%d book_id=%s", job_id, book_id)

        # Poll until done
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                self.stop()
                raise TomatoJobCancelled(f"Download job {job_id} cancelled")
            time.sleep(poll_interval)
            if cancel_event and cancel_event.is_set():
                self.stop()
                raise TomatoJobCancelled(f"Download job {job_id} cancelled")
            try:
                jobs = self._get_jobs()
            except Exception as exc:
                if cancel_event and cancel_event.is_set():
                    self.stop()
                    raise TomatoJobCancelled(f"Download job {job_id} cancelled") from exc
                raise
            for j in jobs:
                if j["id"] == job_id:
                    state = j.get("state", "")
                    if state == "done":
                        logger.info("Download job %d complete: %s", job_id, j.get("title", ""))
                        return j
                    if state in ("failed", "error"):
                        raise RuntimeError(
                            f"Download job {job_id} failed: {j.get('message', 'unknown')}"
                        )
                    prog = j.get("progress") or {}
                    saved = prog.get("saved_chapters", 0)
                    total = prog.get("chapter_total", 0)
                    logger.debug(
                        "Job %d: %s saved=%d/%d",
                        job_id, state, saved, total,
                    )
                    if on_progress:
                        try:
                            on_progress(saved, total, state)
                        except Exception:
                            pass
                    break

        raise TimeoutError(f"Download job {job_id} did not complete within {max_wait}s")

    def _get_jobs(self) -> list[dict[str, Any]]:
        resp = requests.get(f"{self.base_url}/api/jobs", timeout=5)
        resp.raise_for_status()
        return resp.json().get("items", [])

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def find_output_txt(self, book_name: str) -> Path | None:
        """Find the generated TXT file in save_dir matching the book name."""
        status = self._get_status()
        save_dir = status.get("save_dir", "")
        if not save_dir or not os.path.isdir(save_dir):
            return None
        for f in os.listdir(save_dir):
            if f.endswith(".txt") and book_name in f:
                return Path(save_dir) / f
        return None

    def _get_status(self) -> dict[str, Any]:
        resp = requests.get(f"{self.base_url}/api/status", timeout=5)
        resp.raise_for_status()
        return resp.json()


def build_client_from_env() -> TomatoExeClient | None:
    """Build a client from environment config. Returns None if exe not configured."""
    exe_path = os.environ.get("TOMATO_DOWNLOADER_EXE", "").strip()
    if not exe_path or not os.path.isfile(exe_path):
        return None
    data_dir = os.environ.get("TOMATO_DOWNLOADER_DATA_DIR", "").strip() or None
    global _SHARED_CLIENT
    with _SHARED_CLIENT_LOCK:
        existing = _SHARED_CLIENT
        if existing and existing.exe_path == exe_path and existing.data_dir == data_dir:
            return existing
        _SHARED_CLIENT = TomatoExeClient(exe_path=exe_path, data_dir=data_dir)
        replacement = _SHARED_CLIENT
    if existing and existing is not replacement:
        existing.stop()
    return replacement


def stop_shared_client() -> None:
    global _SHARED_CLIENT
    with _SHARED_CLIENT_LOCK:
        client = _SHARED_CLIENT
        _SHARED_CLIENT = None
    if client is not None:
        client.stop()
