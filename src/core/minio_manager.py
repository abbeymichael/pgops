"""
minio_manager.py
Manages the MinIO object storage server.
Mirrors the structure of pg_manager.py for consistency.

URL strategy (post-Caddy/mkcert migration):
  - All external-facing URLs use the mkcert-secured Caddy subdomains:
      API endpoint  → https://minio.pgops.local:<https_port>
      Web console   → https://console.pgops.local:<https_port>
  - MinIO itself still listens on plain HTTP internally (127.0.0.1:9000).
    Caddy terminates TLS and reverse-proxies to it.
  - Laravel .env must use the HTTPS Caddy URL as AWS_ENDPOINT so that
    apps on the LAN can reach storage without certificate warnings.
  - The raw internal URL (http://127.0.0.1:9000) is only used for mc
    alias registration and internal health checks.
"""

import os
import sys
import subprocess
import platform
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
    ALIAS        = "pgops"
    API_PORT     = 9000
    CONSOLE_PORT = 9001

    def __init__(self, config: dict, log_fn=None):
        self.config = config
        self._log   = log_fn or print
        self._proc  = None

    def log(self, msg: str):
        self._log(msg)

    # ── Config properties ─────────────────────────────────────────────────────

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

    @property
    def https_port(self) -> int:
        """Caddy HTTPS port — used to build the public-facing URLs."""
        return self.config.get("caddy_https_port", 8443)

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
            progress_callback=lambda p: progress_callback(p // 2) if progress_callback else None,
        )
        if not ok1:
            return False, msg1

        ok2, msg2 = self._setup_binary(
            "mc",
            MC_BUNDLED.get(system, ""),
            MINIO_CLIENT_DOWNLOAD.get(system, ""),
            progress_callback=lambda p: progress_callback(50 + p // 2) if progress_callback else None,
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

        assets  = get_assets_dir()
        bundled = assets / bundled_name if bundled_name else None
        if bundled and bundled.exists():
            self.log(f"Extracting bundled {name}...")
            shutil.copy2(bundled, dest)
            if platform.system() != "Windows":
                dest.chmod(0o755)
            if progress_callback:
                progress_callback(100)
            return True, f"{name} extracted from bundle."

        if not url:
            return False, f"No download URL for {name} on {platform.system()}."
        self.log(f"Downloading {name}...")
        try:
            resp = requests.get(url, stream=True, timeout=120)
            resp.raise_for_status()
            total      = int(resp.headers.get("content-length", 0))
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
        """Check if MinIO is listening on its internal API port."""
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
            "--address",         f"127.0.0.1:{self.api_port}",
            "--console-address", f"127.0.0.1:{self.console_port}",
        ]

        try:
            kwargs = _popen_kwargs()
            kwargs["env"]    = env
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
            self._proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            return False, f"Failed to start MinIO: {e}"

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

        if is_mc_available():
            subprocess.run(
                [str(mc_bin()), "admin", "service", "stop", self.ALIAS],
                capture_output=True, **_popen_kwargs(),
            )
            time.sleep(2)

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

        if self.is_running():
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "minio.exe"],
                    capture_output=True, **_popen_kwargs(),
                )
            else:
                subprocess.run(["pkill", "-f", "minio server"], capture_output=True)

        self.log("MinIO stopped.")
        return True, "MinIO stopped."

    # ── mc alias ─────────────────────────────────────────────────────────────

    def _configure_mc_alias(self):
        """
        Register the pgops alias in mc using the internal plaintext URL.
        mc talks directly to MinIO on localhost — it does NOT go through Caddy.
        """
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

    # ── URL helpers ───────────────────────────────────────────────────────────
    #
    # Rule: anything shown to the user or written into .env files uses the
    # HTTPS Caddy subdomain. The raw internal URL is only used by mc and for
    # health checks inside this process.

    def _caddy_base(self, subdomain: str) -> str:
        """Return https://<subdomain>:<https_port> (omit port if 443)."""
        port = self.https_port
        if port == 443:
            return f"https://{subdomain}"
        return f"https://{subdomain}:{port}"

    def api_url(self) -> str:
        """
        Public HTTPS URL for the MinIO S3 API — use this in .env files.
        Goes through Caddy → mkcert TLS.
        """
        return self._caddy_base("minio.pgops.local")

    def console_url(self) -> str:
        """
        Public HTTPS URL for the MinIO web console — use this to open the browser.
        Goes through Caddy → mkcert TLS.
        """
        return self._caddy_base("console.pgops.local")

    def internal_api_url(self) -> str:
        """Raw internal URL used only by mc and health checks."""
        return f"http://127.0.0.1:{self.api_port}"

    # Keep old name for any callers that used endpoint_url()
    def endpoint_url(self, use_local: bool = False) -> str:
        """
        Backwards-compatible wrapper.
        Always returns the public HTTPS Caddy URL now.
        `use_local` is ignored — internal callers should use internal_api_url().
        """
        return self.api_url()

    # ── Bucket policy helpers ─────────────────────────────────────────────────

    def set_bucket_public(self, bucket: str) -> tuple[bool, str]:
        """
        Make a bucket publicly readable (anonymous GET/download allowed).
        Sets the 'download' canned policy via mc.
        """
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()
        r = subprocess.run(
            [str(mc_bin()), "anonymous", "set", "download",
             f"{self.ALIAS}/{bucket}"],
            capture_output=True, text=True, **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, f"Bucket '{bucket}' is now public (read-only)."
        return False, r.stderr.strip() or r.stdout.strip()

    def set_bucket_private(self, bucket: str) -> tuple[bool, str]:
        """
        Make a bucket private (no anonymous access).
        Sets the 'none' canned policy via mc.
        """
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()
        r = subprocess.run(
            [str(mc_bin()), "anonymous", "set", "none",
             f"{self.ALIAS}/{bucket}"],
            capture_output=True, text=True, **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, f"Bucket '{bucket}' is now private."
        return False, r.stderr.strip() or r.stdout.strip()

    def get_bucket_policy(self, bucket: str) -> str:
        """
        Return 'public' or 'private'.
        Uses `mc anonymous get` — returns 'none' for private buckets,
        'download' for publicly readable ones.
        """
        if not is_mc_available():
            return "unknown"
        self.ensure_mc_alias()
        r = subprocess.run(
            [str(mc_bin()), "anonymous", "get", f"{self.ALIAS}/{bucket}"],
            capture_output=True, text=True, **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).lower()
        if "download" in out or "public" in out:
            return "public"
        return "private"

    # ── Folder (prefix) helpers ───────────────────────────────────────────────
    #
    # S3/MinIO has no real folders — a "folder" is a key prefix ending in '/'.
    # We create one by uploading a zero-byte placeholder object: prefix/.keep

    def create_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        """
        Create a folder (prefix) inside a bucket by uploading a .keep placeholder.
        `folder` should NOT have a leading slash.  Trailing slash is added here.
        """
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()

        folder = folder.strip("/")
        if not folder:
            return False, "Folder name cannot be empty."

        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".keep") as tf:
            tf.write(b"")
            tmp = tf.name

        target = f"{self.ALIAS}/{bucket}/{folder}/.keep"
        try:
            r = subprocess.run(
                [str(mc_bin()), "cp", tmp, target],
                capture_output=True, text=True, **_popen_kwargs(),
            )
            _os.unlink(tmp)
            if r.returncode == 0:
                return True, f"Folder '{folder}' created in '{bucket}'."
            return False, r.stderr.strip() or r.stdout.strip()
        except Exception as exc:
            try:
                _os.unlink(tmp)
            except Exception:
                pass
            return False, str(exc)

    def list_folders(self, bucket: str, prefix: str = "") -> list[str]:
        """
        List the immediate sub-folders (common prefixes) inside a bucket/prefix.
        Returns a list of folder names (without trailing slash).
        """
        if not is_mc_available():
            return []
        self.ensure_mc_alias()

        path = f"{self.ALIAS}/{bucket}"
        if prefix:
            path += f"/{prefix.strip('/')}/"

        r = subprocess.run(
            [str(mc_bin()), "ls", "--recursive=false", path],
            capture_output=True, text=True, **_popen_kwargs(),
        )
        folders = []
        for line in r.stdout.splitlines():
            # mc ls output: `[date] [time]     0 folder/`
            parts = line.strip().split()
            if parts and parts[-1].endswith("/"):
                name = parts[-1].rstrip("/")
                if name and name != ".":
                    folders.append(name)
        return folders

    def delete_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        """
        Recursively delete a folder (prefix) and all objects under it.
        """
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()

        folder = folder.strip("/")
        if not folder:
            return False, "Folder name cannot be empty."

        r = subprocess.run(
            [str(mc_bin()), "rm", "--recursive", "--force",
             f"{self.ALIAS}/{bucket}/{folder}/"],
            capture_output=True, text=True, **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, f"Folder '{folder}' deleted from '{bucket}'."
        return False, r.stderr.strip() or r.stdout.strip()

    # ── Connection info (legacy) ──────────────────────────────────────────────

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