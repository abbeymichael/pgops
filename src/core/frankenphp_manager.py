"""
frankenphp_manager.py
Manages FrankenPHP processes — one per deployed Laravel app.
Follows the same subprocess pattern as MinIOManager.
"""

import os
import sys
import subprocess
import platform
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Optional


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_frankenphp_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "frankenphp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_frankenphp_bin() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return get_frankenphp_dir() / f"frankenphp{ext}"


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


def is_frankenphp_available() -> bool:
    return get_frankenphp_bin().exists()


def setup_frankenphp_binary(progress_callback=None) -> tuple[bool, str]:
    """Extract from assets/ or download FrankenPHP binary."""
    dest = get_frankenphp_bin()
    if dest.exists():
        return True, "FrankenPHP already available."

    # Try bundled asset first
    asset_name = "frankenphp.exe" if platform.system() == "Windows" else "frankenphp"
    bundled = get_assets_dir() / asset_name
    if bundled.exists():
        shutil.copy2(bundled, dest)
        if platform.system() != "Windows":
            dest.chmod(0o755)
        if progress_callback:
            progress_callback(100)
        return True, "FrankenPHP extracted from bundle."

    # Download from GitHub releases
    system = platform.system()
    if system == "Windows":
        filename = "frankenphp-windows-x86_64.exe"
    elif system == "Darwin":
        filename = "frankenphp-mac-arm64"  # most modern Macs
    else:
        filename = "frankenphp-linux-x86_64"

    url = (
        f"https://github.com/dunglas/frankenphp/releases/latest/download/{filename}"
    )
    try:
        import requests
        resp = requests.get(url, stream=True, timeout=180)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(int(downloaded / total * 100))
        if platform.system() != "Windows":
            dest.chmod(0o755)
        return True, "FrankenPHP downloaded."
    except Exception as exc:
        return False, f"Failed to download FrankenPHP: {exc}"


# ── Per-App process ───────────────────────────────────────────────────────────

MAX_LOG_LINES = 500


class AppProcess:
    """
    A single FrankenPHP process serving one Laravel app.
    Collects stdout/stderr in a rolling buffer (MAX_LOG_LINES).
    """

    def __init__(self, app: dict, frankenphp_bin: str):
        self.app            = app
        self.frankenphp_bin = frankenphp_bin
        self.process: Optional[subprocess.Popen] = None
        self.log_lines: list[str]  = []
        self._log_lock     = threading.Lock()
        self._log_thread: Optional[threading.Thread] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        public_dir = os.path.join(self.app["folder"], "public")
        if not os.path.isdir(public_dir):
            return False, f"App public/ directory not found: {public_dir}"

        port = self.app["internal_port"]
        env  = self._build_env()

        cmd = [
            self.frankenphp_bin,
            "php-server",
            "--listen", f"127.0.0.1:{port}",
            "--root",   public_dir,
        ]

        try:
            kwargs = _popen_kwargs()
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.STDOUT
            kwargs["env"]    = env
            kwargs["cwd"]    = self.app["folder"]
            self.process     = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start {self.app['id']}: {exc}"

        self._log_thread = threading.Thread(
            target=self._read_logs, daemon=True,
            name=f"PGOps-App-{self.app['id']}"
        )
        self._log_thread.start()

        # Give it a moment to bind
        time.sleep(0.8)
        if self.process.poll() is not None:
            last = self.get_last_logs(20)
            return False, f"Process exited immediately.\n{''.join(last)}"

        return True, f"App '{self.app['id']}' started on port {port}."

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def restart(self) -> tuple[bool, str]:
        self.stop()
        return self.start()

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def port_listening(self) -> bool:
        port = self.app.get("internal_port", 0)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            return result == 0
        except Exception:
            return False

    # ── Logs ──────────────────────────────────────────────────────────────────

    def _read_logs(self):
        if not self.process or not self.process.stdout:
            return
        for raw in self.process.stdout:
            line = raw.decode("utf-8", errors="replace")
            with self._log_lock:
                self.log_lines.append(line)
                if len(self.log_lines) > MAX_LOG_LINES:
                    self.log_lines.pop(0)

    def get_last_logs(self, n: int = 100) -> list[str]:
        with self._log_lock:
            return list(self.log_lines[-n:])

    # ── Env ───────────────────────────────────────────────────────────────────

    def _build_env(self) -> dict:
        """Build environment for the FrankenPHP subprocess."""
        env = {**os.environ}
        # PHP ini overrides via environment
        memory   = os.environ.get("PGOPS_PHP_MEMORY",  "256M")
        upload   = os.environ.get("PGOPS_PHP_UPLOAD",  "50M")
        env.update({
            "PHP_INI_SCAN_DIR":         "",            # ignore system ini
            "PHP_MEMORY_LIMIT":         memory,
            "PHP_UPLOAD_MAX_FILESIZE":  upload,
            "PHP_POST_MAX_SIZE":        upload,
            "APP_ENV":                  "production",
        })
        return env


# ── Process registry ──────────────────────────────────────────────────────────

class AppProcessManager:
    """
    Maintains a dict of AppProcess instances keyed by app id.
    Thread-safe: operations are short and Python GIL-protected.
    """

    def __init__(self, log_fn=None):
        self._log      = log_fn or print
        self.processes: dict[str, AppProcess] = {}

    # ── Binary helpers ────────────────────────────────────────────────────────

    @property
    def _bin(self) -> str:
        return str(get_frankenphp_bin())

    # ── Per-app operations ────────────────────────────────────────────────────

    def start_app(self, app: dict) -> tuple[bool, str]:
        if not is_frankenphp_available():
            return False, "FrankenPHP binary not found. Run setup first."
        proc = AppProcess(app, self._bin)
        ok, msg = proc.start()
        if ok:
            self.processes[app["id"]] = proc
        self._log(f"[App:{app['id']}] {msg}")
        return ok, msg

    def stop_app(self, app_id: str) -> tuple[bool, str]:
        if app_id not in self.processes:
            return True, f"App '{app_id}' not in process list."
        self.processes[app_id].stop()
        del self.processes[app_id]
        self._log(f"[App:{app_id}] Stopped.")
        return True, f"App '{app_id}' stopped."

    def restart_app(self, app_id: str, app: dict) -> tuple[bool, str]:
        self.stop_app(app_id)
        return self.start_app(app)

    def start_all(self, apps: list) -> list[tuple[str, bool, str]]:
        """Start every app in the list. Returns list of (id, ok, msg)."""
        results = []
        for app in apps:
            ok, msg = self.start_app(app)
            results.append((app["id"], ok, msg))
        return results

    def stop_all(self):
        """Stop every running app process."""
        for app_id in list(self.processes.keys()):
            self.stop_app(app_id)

    # ── Status / logs ─────────────────────────────────────────────────────────

    def is_running(self, app_id: str) -> bool:
        proc = self.processes.get(app_id)
        return proc.is_running if proc else False

    def get_logs(self, app_id: str, n: int = 100) -> list[str]:
        proc = self.processes.get(app_id)
        return proc.get_last_logs(n) if proc else []

    def status_map(self) -> dict[str, str]:
        """Returns {app_id: 'running'|'stopped'} for all known apps."""
        return {
            app_id: ("running" if proc.is_running else "stopped")
            for app_id, proc in self.processes.items()
        }
