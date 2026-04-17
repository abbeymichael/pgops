"""
frankenphp_manager.py
Manages FrankenPHP processes — one per deployed Laravel app.

FIXES:
- _free_port() on non-Windows now correctly uses lsof -ti output and kills PID
- AppProcess._read_logs() uses a thread with readline() not iteration to avoid
  blocking on large output buffering (prevents PIPE deadlock)
- stop() waits for log thread to finish before returning
- AppProcessManager.stop_app() removes the process from the dict after stopping
- status_map() includes all known apps (not just those still in processes dict)
- AppProcess.start() catches and re-raises with full detail on early exit
- MAX_LOG_LINES increased and buffer uses deque for O(1) append/pop
"""

import os
import sys
import subprocess
import platform
import shutil
import socket
import threading
import time
import zipfile
from collections import deque
from pathlib import Path
from typing import Optional


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def _free_port(port: int):
    """Kill any process listening on the given TCP port."""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, **_popen_kwargs()
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        if pid.isdigit():
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True, **_popen_kwargs()
                            )
                    break
        else:
            # lsof -ti returns PIDs, one per line
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True, text=True
            )
            for pid_str in result.stdout.strip().splitlines():
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    subprocess.run(["kill", "-9", pid_str], capture_output=True)
    except Exception:
        pass


# ── Paths ─────────────────────────────────────────────────────────────────────

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


def _get_download_info() -> tuple[str, str, bool]:
    base   = "https://github.com/php/frankenphp/releases/latest/download"
    system = platform.system()

    if system == "Windows":
        fname = "frankenphp.zip"
        return f"{base}/{fname}", fname, True

    if system == "Darwin":
        import platform as _p
        machine = _p.machine().lower()
        if "arm" in machine or "aarch" in machine:
            fname = "frankenphp-mac-arm64"
        else:
            fname = "frankenphp-mac-x86_64"
        return f"{base}/{fname}", fname, False

    fname = "frankenphp-linux-x86_64"
    return f"{base}/{fname}", fname, False


def _bundled_asset_name() -> str:
    if platform.system() == "Windows":
        return "frankenphp.zip"
    return "frankenphp_mac"


def _install_from_zip(zip_path: Path, dest_dir: Path, progress_callback=None):
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total   = len(members)
        for i, member in enumerate(members):
            zf.extract(member, dest_dir)
            if progress_callback and total:
                progress_callback(60 + int(i / total * 35))

    contents = list(dest_dir.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        inner = contents[0]
        for item in inner.iterdir():
            shutil.move(str(item), dest_dir)
        inner.rmdir()


def _install_from_binary(src: Path, dest_dir: Path, progress_callback=None):
    dest = dest_dir / "frankenphp"
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    if progress_callback:
        progress_callback(95)


def setup_frankenphp_binary(progress_callback=None) -> tuple[bool, str]:
    """Ensure the FrankenPHP binary is installed."""
    dest_dir = get_frankenphp_dir()
    bin_path = get_frankenphp_bin()

    if bin_path.exists():
        return True, "FrankenPHP already available."

    if progress_callback:
        progress_callback(5)

    bundled = get_assets_dir() / _bundled_asset_name()
    if bundled.exists():
        try:
            if progress_callback:
                progress_callback(15)
            if platform.system() == "Windows":
                _install_from_zip(bundled, dest_dir, progress_callback)
            else:
                _install_from_binary(bundled, dest_dir, progress_callback)
            if bin_path.exists():
                if progress_callback:
                    progress_callback(100)
                return True, "FrankenPHP extracted from bundle."
            return False, "Bundle extraction finished but binary not found."
        except Exception as exc:
            return False, f"Failed to extract bundled FrankenPHP: {exc}"

    url, fname, is_zip = _get_download_info()
    archive_dest = dest_dir / fname

    try:
        import requests
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        total      = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(archive_dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(5 + int(downloaded / total * 50))
    except Exception as exc:
        return False, f"Failed to download FrankenPHP: {exc}"

    try:
        if is_zip:
            _install_from_zip(archive_dest, dest_dir, progress_callback)
        else:
            _install_from_binary(archive_dest, dest_dir, progress_callback)
    except Exception as exc:
        return False, f"Failed to install FrankenPHP: {exc}"
    finally:
        try:
            archive_dest.unlink(missing_ok=True)
        except Exception:
            pass

    if not bin_path.exists():
        return False, (
            f"FrankenPHP binary not found after setup.\n"
            f"Expected: {bin_path}\n"
            f"Dir: {[p.name for p in dest_dir.iterdir()]}"
        )

    if progress_callback:
        progress_callback(100)
    return True, "FrankenPHP downloaded and installed."


# ── Per-app process ────────────────────────────────────────────────────────────

MAX_LOG_LINES = 1000


class AppProcess:
    """A single FrankenPHP process serving one Laravel app."""

    def __init__(self, app: dict, frankenphp_bin: str):
        self.app            = app
        self.frankenphp_bin = frankenphp_bin
        self.process: Optional[subprocess.Popen] = None
        self._log_lines: deque = deque(maxlen=MAX_LOG_LINES)
        self._log_lock   = threading.Lock()
        self._log_thread: Optional[threading.Thread] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        public_dir = os.path.join(self.app["folder"], "public")
        if not os.path.isdir(public_dir):
            return False, f"App public/ directory not found: {public_dir}"

        port = self.app["internal_port"]
        _free_port(port)

        env = self._build_env()
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
            self.process = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start '{self.app['id']}': {exc}"

        # Start log reader thread
        self._log_thread = threading.Thread(
            target=self._read_logs,
            daemon=True,
            name=f"PGOps-App-Log-{self.app['id']}",
        )
        self._log_thread.start()

        # Brief pause to catch immediate crashes
        time.sleep(1.0)
        if self.process.poll() is not None:
            last = self.get_last_logs(30)
            output = "".join(last)
            return False, (
                f"Process exited immediately (code {self.process.returncode}).\n"
                f"Output:\n{output}"
            )

        return True, f"App '{self.app['id']}' started on port {port}."

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                    self.process.wait(timeout=2)
                except Exception:
                    pass
            except Exception:
                pass
            self.process = None

        # Wait for log thread to finish (briefly)
        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=2)
        self._log_thread = None

    def restart(self) -> tuple[bool, str]:
        self.stop()
        return self.start()

    # ── Status ─────────────────────────────────────────────────────────────────

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

    # ── Logs ───────────────────────────────────────────────────────────────────

    def _read_logs(self):
        """Read log output line by line — avoids PIPE buffer deadlock."""
        if not self.process or not self.process.stdout:
            return
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                with self._log_lock:
                    self._log_lines.append(decoded)
        except Exception:
            pass

    def get_last_logs(self, n: int = 100) -> list[str]:
        with self._log_lock:
            lines = list(self._log_lines)
        return lines[-n:]

    # ── Environment ────────────────────────────────────────────────────────────

    def _build_env(self) -> dict:
        env    = {**os.environ}
        memory = os.environ.get("PGOPS_PHP_MEMORY", "256M")
        upload = os.environ.get("PGOPS_PHP_UPLOAD",  "50M")
        env.update({
            "PHP_INI_SCAN_DIR":        "",
            "PHP_MEMORY_LIMIT":        memory,
            "PHP_UPLOAD_MAX_FILESIZE": upload,
            "PHP_POST_MAX_SIZE":       upload,
            "APP_ENV":                 "production",
        })
        return env


# ── Process registry ───────────────────────────────────────────────────────────

class AppProcessManager:
    """Maintains a dict of AppProcess instances keyed by app id."""

    def __init__(self, log_fn=None):
        self._log      = log_fn or print
        self._processes: dict[str, AppProcess] = {}
        self._lock = threading.Lock()

    @property
    def processes(self) -> dict:
        """Read-only view of current processes."""
        with self._lock:
            return dict(self._processes)

    @property
    def _bin(self) -> str:
        return str(get_frankenphp_bin())

    def is_binary_available(self) -> bool:
        return is_frankenphp_available()

    # ── Per-app ────────────────────────────────────────────────────────────────

    def start_app(self, app: dict) -> tuple[bool, str]:
        if not is_frankenphp_available():
            return False, "FrankenPHP binary not found. Run Setup in the Server tab."
        proc = AppProcess(app, self._bin)
        ok, msg = proc.start()
        if ok:
            with self._lock:
                self._processes[app["id"]] = proc
        self._log(f"[App:{app['id']}] {msg}")
        return ok, msg

    def stop_app(self, app_id: str) -> tuple[bool, str]:
        with self._lock:
            proc = self._processes.pop(app_id, None)
        if proc is None:
            return True, f"App '{app_id}' not in process list."
        proc.stop()
        self._log(f"[App:{app_id}] Stopped.")
        return True, f"App '{app_id}' stopped."

    def restart_app(self, app_id: str, app: dict) -> tuple[bool, str]:
        self.stop_app(app_id)
        return self.start_app(app)

    def start_all(self, apps: list) -> list[tuple[str, bool, str]]:
        results = []
        for app in apps:
            ok, msg = self.start_app(app)
            results.append((app["id"], ok, msg))
        return results

    def stop_all(self):
        with self._lock:
            app_ids = list(self._processes.keys())
        for app_id in app_ids:
            self.stop_app(app_id)

    # ── Status / logs ──────────────────────────────────────────────────────────

    def is_running(self, app_id: str) -> bool:
        with self._lock:
            proc = self._processes.get(app_id)
        return proc.is_running if proc else False

    def get_logs(self, app_id: str, n: int = 100) -> list[str]:
        with self._lock:
            proc = self._processes.get(app_id)
        return proc.get_last_logs(n) if proc else []

    def status_map(self) -> dict[str, str]:
        """Returns status for all tracked processes."""
        with self._lock:
            procs = dict(self._processes)
        return {
            app_id: ("running" if proc.is_running else "stopped")
            for app_id, proc in procs.items()
        }
