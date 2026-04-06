"""
minio_manager.py
Manages the MinIO object storage server.
Mirrors the structure of pg_manager.py for consistency.
"""

import os
import sys
import subprocess
import platform
import zipfile
import shutil
import socket
import time
import requests
from pathlib import Path


# ── Download URLs ─────────────────────────────────────────────────────────────
MINIO_DOWNLOAD = {
    "Windows": "https://dl.min.io/server/minio/release/windows-amd64/minio.exe",
    "Darwin":  "https://dl.min.io/server/minio/release/darwin-amd64/minio",
}

MINIO_CLIENT_DOWNLOAD = {
    "Windows": "https://dl.min.io/client/mc/release/windows-amd64/mc.exe",
    "Darwin":  "https://dl.min.io/client/mc/release/darwin-amd64/mc",
}

# Bundled asset names (place in assets/ before building)
MINIO_BUNDLED = {
    "Windows": "minio.exe",
    "Darwin":  "minio",
}
MC_BUNDLED = {
    "Windows": "mc.exe",
    "Darwin":  "mc",
}


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_minio_dir() -> Path:
    """Directory where minio and mc binaries live."""
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "minio-bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "minio-data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_assets_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


def _bin(name: str) -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    base = name.rstrip(".exe")
    return get_minio_dir() / f"{base}{ext}"


def minio_bin() -> Path:
    return _bin("minio")


def mc_bin() -> Path:
    return _bin("mc")


def is_binaries_available() -> bool:
    return minio_bin().exists()


def is_mc_available() -> bool:
    return mc_bin().exists()


class MinIOManager:
    # Default admin credentials — same as PostgreSQL admin for simplicity
    ALIAS = "pgops"
    API_PORT   = 9000
    CONSOLE_PORT = 9001

    def __init__(self, config: dict, log_fn=None):
        self.config  = config
        self._log    = log_fn or print
        self._proc   = None

    def log(self, msg: str):
        self._log(msg)

    @property
    def admin_user(self) -> str:
        return self.config.get("username", "postgres")

    @property
    def admin_password(self) -> str:
        return self.config.get("password", "postgres")

    @property
    def api_port(self) -> int:
        return self.config.get("minio_api_port", self.API_PORT)

    @property
    def console_port(self) -> int:
        return self.config.get("minio_console_port", self.CONSOLE_PORT)

    # ── Binary setup ──────────────────────────────────────────────────────────

    def is_binaries_available(self) -> bool:
        return minio_bin().exists()

    def is_mc_available(self) -> bool:
        return mc_bin().exists()

    def setup_binaries(self, progress_callback=None) -> tuple[bool, str]:
        """
        Extract from assets/ if available, otherwise download.
        Downloads both minio and mc (MinIO client).
        """
        system = platform.system()
        ok1, msg1 = self._setup_binary(
            "minio",
            MINIO_BUNDLED.get(system, ""),
            MINIO_DOWNLOAD.get(system, ""),
            progress_callback=lambda p: progress_callback(p // 2) if progress_callback else None
        )
        if not ok1:
            return False, msg1

        ok2, msg2 = self._setup_binary(
            "mc",
            MC_BUNDLED.get(system, ""),
            MINIO_CLIENT_DOWNLOAD.get(system, ""),
            progress_callback=lambda p: progress_callback(50 + p // 2) if progress_callback else None
        )
        if not ok2:
            return False, msg2

        if progress_callback:
            progress_callback(100)
        return True, "MinIO binaries ready."

    def _setup_binary(self, name: str, bundled_name: str,
                      url: str, progress_callback=None) -> tuple[bool, str]:
        dest = _bin(name)
        if dest.exists():
            self.log(f"{name} already available.")
            return True, f"{name} ready."

        # Try bundled assets first
        assets = get_assets_dir()
        bundled = assets / bundled_name if bundled_name else None
        if bundled and bundled.exists():
            self.log(f"Extracting bundled {name}...")
            shutil.copy2(bundled, dest)
            if platform.system() != "Windows":
                dest.chmod(0o755)
            if progress_callback:
                progress_callback(100)
            return True, f"{name} extracted from bundle."

        # Download
        if not url:
            return False, f"No download URL for {name} on {platform.system()}."
        self.log(f"Downloading {name}...")
        try:
            resp = requests.get(url, stream=True, timeout=120)
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
            return True, f"{name} downloaded."
        except Exception as e:
            return False, f"Failed to download {name}: {e}"

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def is_running(self) -> bool:
        """Check if MinIO is listening on its API port."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", self.api_port))
            s.close()
            return result == 0
        except Exception:
            return False

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            self.log("MinIO already running.")
            return True, "MinIO already running."

        if not is_binaries_available():
            return False, "MinIO binary not found. Run setup first."

        data_dir = get_data_dir()
        env = {
            **os.environ,
            "MINIO_ROOT_USER":     self.admin_user,
            "MINIO_ROOT_PASSWORD": self.admin_password,
        }

        cmd = [
            str(minio_bin()),
            "server",
            str(data_dir),
            "--address",  f"0.0.0.0:{self.api_port}",
            "--console-address", f"0.0.0.0:{self.console_port}",
        ]

        try:
            kwargs = _popen_kwargs()
            kwargs["env"] = env
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
            self._proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            return False, f"Failed to start MinIO: {e}"

        # Wait up to 10s for it to become available
        for _ in range(20):
            time.sleep(0.5)
            if self.is_running():
                self.log(f"MinIO started on port {self.api_port}.")
                self._configure_mc_alias()
                return True, f"MinIO started on port {self.api_port}."

        return False, "MinIO did not start in time."

    def stop(self) -> tuple[bool, str]:
        if not self.is_running():
            return True, "MinIO not running."

        # Try graceful shutdown via mc first
        if is_mc_available():
            subprocess.run(
                [str(mc_bin()), "admin", "service", "stop", self.ALIAS],
                capture_output=True, **_popen_kwargs()
            )
            time.sleep(2)

        # Kill process if still running
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        # Platform kill as last resort
        if self.is_running():
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "minio.exe"],
                    capture_output=True, **_popen_kwargs()
                )
            else:
                subprocess.run(["pkill", "-f", "minio server"],
                               capture_output=True)

        self.log("MinIO stopped.")
        return True, "MinIO stopped."

    # ── mc alias ─────────────────────────────────────────────────────────────

    def _configure_mc_alias(self):
        """Register pgops alias in mc so bucket_manager can use it."""
        if not is_mc_available():
            return
        subprocess.run([
            str(mc_bin()), "alias", "set", self.ALIAS,
            f"http://127.0.0.1:{self.api_port}",
            self.admin_user,
            self.admin_password,
        ], capture_output=True, **_popen_kwargs())

    def ensure_mc_alias(self):
        """Call this before any mc operations."""
        self._configure_mc_alias()

    # ── Connection info ───────────────────────────────────────────────────────

    def get_lan_ip(self) -> str:
        try:
            from core.network_info import get_all_interfaces, get_best_ip
            ifaces = get_all_interfaces()
            return get_best_ip(ifaces, self.config.get("preferred_ip", ""))
        except Exception:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return "127.0.0.1"

    def endpoint_url(self, use_local: bool = False) -> str:
        host = "127.0.0.1" if use_local else self.get_lan_ip()
        return f"http://{host}:{self.api_port}"

    def console_url(self) -> str:
        # Always use IP — browsers enforce HTTPS on .local via HSTS which breaks plain HTTP
        ip = self.get_lan_ip()
        return f"http://{ip}:{self.console_port}"
