"""
frankenphp_manager.py
Manages FrankenPHP processes — one per deployed Laravel app.

Download formats (GitHub releases latest):
  Windows : frankenphp-windows-x86_64.zip   (ZIP containing frankenphp.exe + PHP DLLs)
  macOS   : frankenphp-mac-arm64            (single binary, no wrapper archive)
  macOS   : frankenphp-mac-x86_64          (Intel Macs)

Follows the same subprocess / binary-setup pattern as MinIOManager.
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
from pathlib import Path
from typing import Optional


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


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


# ── Download / asset info per platform ───────────────────────────────────────

def _get_download_info() -> tuple[str, str, bool]:
    """
    Returns (download_url, archive_filename, is_zip).
    Windows: ZIP containing frankenphp.exe + supporting DLLs.
    macOS:   Single binary file (no container archive).
    """
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

    # Linux
    fname = "frankenphp-linux-x86_64"
    return f"{base}/{fname}", fname, False


def _bundled_asset_name() -> str:
    """
    Name of the pre-placed file in assets/ before building.
      Windows : frankenphp_windows.zip   (the same ZIP from the release)
      macOS   : frankenphp_mac           (the single binary)
    """
    if platform.system() == "Windows":
        return "frankenphp.zip"
    return "frankenphp_mac"


# ── Extraction logic ─────────────────────────────────────────────────────────

def _install_from_zip(zip_path: Path, dest_dir: Path, progress_callback=None):
    """
    Extract the Windows ZIP release.
    The ZIP contains frankenphp.exe at its root plus PHP DLLs.
    All contents must stay together in dest_dir so the exe can find the DLLs.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total   = len(members)
        for i, member in enumerate(members):
            zf.extract(member, dest_dir)
            if progress_callback and total:
                # Map extraction progress to 60-95 % range
                progress_callback(60 + int(i / total * 35))

    # If everything landed inside a subfolder, hoist it up one level
    contents = list(dest_dir.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        inner = contents[0]
        for item in inner.iterdir():
            shutil.move(str(item), dest_dir)
        inner.rmdir()


def _install_from_binary(src: Path, dest_dir: Path, progress_callback=None):
    """Copy a single-file binary (macOS/Linux) into dest_dir and make it executable."""
    dest = dest_dir / "frankenphp"
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    if progress_callback:
        progress_callback(95)


# ── Setup binary (public API) ─────────────────────────────────────────────────

def setup_frankenphp_binary(progress_callback=None) -> tuple[bool, str]:
    """
    Ensure the FrankenPHP binary is installed in get_frankenphp_dir().
    Priority:
      1. Already installed → early return.
      2. Bundled asset in assets/ folder → extract.
      3. Download from GitHub releases → extract.

    Mirrors MinIOManager.setup_binaries() pattern exactly.
    """
    dest_dir = get_frankenphp_dir()
    bin_path = get_frankenphp_bin()

    if bin_path.exists():
        return True, "FrankenPHP already available."

    if progress_callback:
        progress_callback(5)

    # ── Try bundled asset ──────────────────────────────────────────────────────
    bundled_name = _bundled_asset_name()
    bundled      = get_assets_dir() / bundled_name
    if bundled.exists():
        try:
            if progress_callback:
                progress_callback(15)
            system = platform.system()
            if system == "Windows":
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

    # ── Download ───────────────────────────────────────────────────────────────
    url, fname, is_zip = _get_download_info()
    archive_dest       = dest_dir / fname

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
                    # Map download to 5-55 %
                    progress_callback(5 + int(downloaded / total * 50))
    except Exception as exc:
        return False, f"Failed to download FrankenPHP: {exc}"

    # ── Extract / install ──────────────────────────────────────────────────────
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
            f"Dir contents: {[p.name for p in dest_dir.iterdir()]}"
        )

    if progress_callback:
        progress_callback(100)
    return True, "FrankenPHP downloaded and installed."


# ── Per-app process ───────────────────────────────────────────────────────────

MAX_LOG_LINES = 500


class AppProcess:
    """
    A single FrankenPHP process serving one Laravel app.
    Collects stdout/stderr in a rolling log buffer.
    """

    def __init__(self, app: dict, frankenphp_bin: str):
        self.app             = app
        self.frankenphp_bin  = frankenphp_bin
        self.process: Optional[subprocess.Popen] = None
        self.log_lines: list[str]  = []
        self._log_lock       = threading.Lock()
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
            kwargs           = _popen_kwargs()
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.STDOUT
            kwargs["env"]    = env
            kwargs["cwd"]    = self.app["folder"]
            self.process     = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start '{self.app['id']}': {exc}"

        self._log_thread = threading.Thread(
            target=self._read_logs, daemon=True,
            name=f"PGOps-App-{self.app['id']}"
        )
        self._log_thread.start()

        # Brief pause to catch immediate crashes
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

    # ── Environment ───────────────────────────────────────────────────────────

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


# ── Process registry ──────────────────────────────────────────────────────────

class AppProcessManager:
    """Maintains a dict of AppProcess instances keyed by app id."""

    def __init__(self, log_fn=None):
        self._log      = log_fn or print
        self.processes: dict[str, AppProcess] = {}

    @property
    def _bin(self) -> str:
        return str(get_frankenphp_bin())

    def is_binary_available(self) -> bool:
        return is_frankenphp_available()

    # ── Per-app ───────────────────────────────────────────────────────────────

    def start_app(self, app: dict) -> tuple[bool, str]:
        if not is_frankenphp_available():
            return False, "FrankenPHP binary not found. Run Setup in the Server tab."
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
        results = []
        for app in apps:
            ok, msg = self.start_app(app)
            results.append((app["id"], ok, msg))
        return results

    def stop_all(self):
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
        return {
            app_id: ("running" if proc.is_running else "stopped")
            for app_id, proc in self.processes.items()
        }