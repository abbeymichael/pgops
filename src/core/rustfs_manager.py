"""
rustfs_manager.py
Manages the RustFS object storage server.

RustFS is a single-binary, S3-compatible object storage server (Apache 2.0).
It uses the same port layout as MinIO but is configured exclusively via
RUSTFS_* environment variables — it does NOT accept positional path arguments
like MinIO/SeaweedFS do.

Environment variables used:
  RUSTFS_VOLUMES          — data directory (required)
  RUSTFS_ADDRESS          — S3 API bind address (default :9000)
  RUSTFS_CONSOLE_ADDRESS  — Console bind address (default :9001)
  RUSTFS_CONSOLE_ENABLE   — "true" to enable web UI
  RUSTFS_ACCESS_KEY       — root access key
  RUSTFS_SECRET_KEY       — root secret key
  RUSTFS_OBS_LOGGER_LEVEL — log level (info/warn/error)

Health check: GET http://127.0.0.1:<api_port>/health  → 200 OK

URL strategy (via Caddy + mkcert):
  S3 API   → https://s3.pgops.local[:<https_port>]
  Console  → https://console.pgops.local[:<https_port>]
  Internal → http://127.0.0.1:<api_port>  (health checks / mc alias only)

Binary distribution:
  Download base: https://dl.rustfs.com/artifacts/rustfs/
  Windows amd64: rustfs-release-x86_64-pc-windows-msvc.zip
  macOS   amd64: rustfs-release-x86_64-apple-darwin.zip
  macOS   arm64: rustfs-release-aarch64-apple-darwin.zip
  Linux   amd64: rustfs-release-x86_64-unknown-linux-musl.zip
"""

import os
import sys
import subprocess
import platform
import shutil
import socket
import time
import zipfile
import tempfile
from pathlib import Path

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# ── Download URLs ─────────────────────────────────────────────────────────────

_RUSTFS_BASE = "https://dl.rustfs.com/artifacts/rustfs"

RUSTFS_DOWNLOAD = {
    "Windows":     f"{_RUSTFS_BASE}/rustfs-release-x86_64-pc-windows-msvc.zip",
    "Darwin":      f"{_RUSTFS_BASE}/rustfs-release-x86_64-apple-darwin.zip",
    "Darwin_arm64": f"{_RUSTFS_BASE}/rustfs-release-aarch64-apple-darwin.zip",
    "Linux":       f"{_RUSTFS_BASE}/rustfs-release-x86_64-unknown-linux-musl.zip",
}

# Bundled asset names (place in assets/ before building)
RUSTFS_BUNDLED = {
    "Windows": "rustfs.exe",
    "Darwin":  "rustfs",
    "Linux":   "rustfs",
}


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


# ── Path helpers ──────────────────────────────────────────────────────────────

def get_rustfs_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "rustfs-bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "rustfs-data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


def _bin_path() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return get_rustfs_dir() / f"rustfs{ext}"


def rustfs_bin() -> Path:
    return _bin_path()


def is_binaries_available() -> bool:
    return rustfs_bin().exists()


def _get_download_url() -> str:
    system = platform.system()
    if system == "Darwin":
        import platform as _pl
        if _pl.machine().lower() in ("arm64", "aarch64"):
            return RUSTFS_DOWNLOAD.get("Darwin_arm64", RUSTFS_DOWNLOAD["Darwin"])
    return RUSTFS_DOWNLOAD.get(system, "")


# ── RustFSManager ─────────────────────────────────────────────────────────────

class RustFSManager:
    """
    Manages the RustFS single-binary S3-compatible object storage server.

    RustFS is configured entirely through environment variables (RUSTFS_*).
    It is launched as a subprocess; the process handles its own internal
    routing between S3 API and the web console.
    """

    API_PORT     = 9000   # S3 API  (same default as MinIO)
    CONSOLE_PORT = 9001   # Web console

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
        return int(self.config.get("rustfs_api_port", self.API_PORT))

    @property
    def console_port(self) -> int:
        return int(self.config.get("rustfs_console_port", self.CONSOLE_PORT))

    @property
    def https_port(self) -> int:
        return int(self.config.get("caddy_https_port", 8443))

    # Back-compat properties so old callers using s3_port/filer_port still work
    @property
    def s3_port(self) -> int:
        return self.api_port

    @property
    def filer_port(self) -> int:
        return self.console_port

    # ── Binary setup ──────────────────────────────────────────────────────────

    def is_binaries_available(self) -> bool:
        return rustfs_bin().exists()

    def setup_binaries(self, progress_callback=None) -> tuple[bool, str]:
        """
        Extract the rustfs binary from assets/ if available, otherwise
        download from the RustFS release CDN.
        Each release ZIP contains a single rustfs[.exe] binary.
        """
        dest = rustfs_bin()

        if dest.exists():
            self.log("RustFS binary already available.")
            if progress_callback:
                progress_callback(100)
            return True, "RustFS binary ready."

        # ── Try bundled asset first ────────────────────────────────────────
        system       = platform.system()
        bundled_name = RUSTFS_BUNDLED.get(system, "")
        if bundled_name:
            bundled = get_assets_dir() / bundled_name
            if bundled.exists():
                self.log("Extracting bundled RustFS binary…")
                shutil.copy2(bundled, dest)
                if system != "Windows":
                    dest.chmod(0o755)
                if progress_callback:
                    progress_callback(100)
                return True, "RustFS binary extracted from bundle."

        # ── Download from CDN ──────────────────────────────────────────────
        url = _get_download_url()
        if not url:
            return False, f"No download URL configured for RustFS on {system}."

        if not _HAS_REQUESTS:
            return False, (
                "The 'requests' package is required to download RustFS.\n"
                "Run: pip install requests"
            )

        self.log(f"Downloading RustFS from {url}…")
        try:
            if progress_callback:
                progress_callback(5)

            resp = _requests.get(url, stream=True, timeout=180)
            resp.raise_for_status()
            total      = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
                tmp_path = tf.name
                for chunk in resp.iter_content(chunk_size=65536):
                    tf.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(5 + int(downloaded / total * 80))

            # Extract the single binary from the ZIP
            extract_dir = get_rustfs_dir() / "_extract"
            extract_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(extract_dir)

            bin_name = "rustfs.exe" if system == "Windows" else "rustfs"
            found    = next(extract_dir.rglob(bin_name), None)

            if found and found.exists():
                shutil.copy2(found, dest)
                if system != "Windows":
                    dest.chmod(0o755)
                shutil.rmtree(extract_dir, ignore_errors=True)
                Path(tmp_path).unlink(missing_ok=True)
                if progress_callback:
                    progress_callback(100)
                return True, "RustFS binary downloaded and installed."

            shutil.rmtree(extract_dir, ignore_errors=True)
            Path(tmp_path).unlink(missing_ok=True)
            return False, "RustFS binary not found inside downloaded archive."

        except Exception as exc:
            return False, f"Failed to download RustFS: {exc}"

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def is_running(self) -> bool:
        """
        Primary check: hit the /health endpoint.
        Falls back to a bare TCP connect if the HTTP call fails (e.g. during
        very early startup before the HTTP stack is ready).
        """
        # Try the dedicated health endpoint first (most reliable)
        try:
            import urllib.request
            url = f"http://127.0.0.1:{self.api_port}/health"
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.status == 200
        except Exception:
            pass

        # Fallback: bare TCP connect
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
            self.log("RustFS already running.")
            return True, "RustFS already running."

        if not self.is_binaries_available():
            return False, "RustFS binary not found. Run setup first."

        data_dir = get_data_dir()
        log_dir  = data_dir.parent / "rustfs-logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # RustFS is configured entirely via environment variables.
        # Do NOT pass data paths as positional arguments — that is MinIO syntax.
        env = {
            **os.environ,
            # Required: where to store data
            "RUSTFS_VOLUMES":         str(data_dir),
            # Network
            "RUSTFS_ADDRESS":         f"127.0.0.1:{self.api_port}",
            "RUSTFS_CONSOLE_ADDRESS": f"127.0.0.1:{self.console_port}",
            "RUSTFS_CONSOLE_ENABLE":  "true",
            # Auth
            "RUSTFS_ACCESS_KEY":      self.admin_user,
            "RUSTFS_SECRET_KEY":      self.admin_password,
            # CORS — allow requests from any origin (LAN access)
            "RUSTFS_CORS_ALLOWED_ORIGINS":         "*",
            "RUSTFS_CONSOLE_CORS_ALLOWED_ORIGINS": "*",
            # Logging
            "RUSTFS_OBS_LOGGER_LEVEL":             "warn",
            "RUSTFS_OBS_LOG_DIRECTORY":            str(log_dir),
        }

        # The binary is invoked with no positional arguments; all config
        # comes from the environment variables set above.
        cmd = [str(rustfs_bin())]

        log_path = data_dir.parent / "rustfs.log"
        try:
            log_file        = open(log_path, "a", encoding="utf-8", errors="replace")
            kwargs          = _popen_kwargs()
            kwargs["env"]   = env
            kwargs["stdout"] = log_file
            kwargs["stderr"] = log_file
            self._proc = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start RustFS: {exc}"

        # Poll the /health endpoint until it responds or we time out (20 s)
        self.log(f"Waiting for RustFS health endpoint on port {self.api_port}…")
        for _ in range(40):
            time.sleep(0.5)
            if self.is_running():
                self.log(f"RustFS started — S3 API on port {self.api_port}.")
                return True, f"RustFS started on port {self.api_port}."

            # Check for immediate exit (bad config, port conflict, etc.)
            if self._proc.poll() is not None:
                break

        # Surface last log lines to help diagnose startup failures
        hint = ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                lines = lf.readlines()
                tail  = "".join(lines[-20:]).strip()
                if tail:
                    hint = f"\n\nLast log lines:\n{tail}"
        except Exception:
            pass

        rc = self._proc.poll()
        if rc is not None:
            return False, (
                f"RustFS exited immediately (code {rc}).\n"
                f"Common causes: port {self.api_port}/{self.console_port} already in use, "
                f"or insufficient disk space.{hint}"
            )
        return False, (
            f"RustFS did not become healthy within 20 s (log: {log_path}){hint}"
        )

    def stop(self) -> tuple[bool, str]:
        if not self.is_running():
            if self._proc:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
                except Exception:
                    pass
                self._proc = None
            return True, "RustFS not running."

        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=3)
                except Exception:
                    pass
            except Exception:
                pass
            self._proc = None

        # Fall back to system-wide kill if still listening
        if self.is_running():
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "rustfs.exe"],
                    capture_output=True, **_popen_kwargs(),
                )
            else:
                subprocess.run(["pkill", "-f", "rustfs"], capture_output=True)

        self.log("RustFS stopped.")
        return True, "RustFS stopped."

    # ── URL helpers ───────────────────────────────────────────────────────────

    def _caddy_base(self, subdomain: str) -> str:
        port = self.https_port
        if port == 443:
            return f"https://{subdomain}"
        return f"https://{subdomain}:{port}"

    def api_url(self) -> str:
        """Public HTTPS URL for the RustFS S3 API (via Caddy). Use in .env files."""
        return self._caddy_base("s3.pgops.local")

    def console_url(self) -> str:
        """Public HTTPS URL for the RustFS web console (via Caddy)."""
        return self._caddy_base("console.pgops.local")

    def internal_api_url(self) -> str:
        """Raw internal HTTP URL — only for health checks and mc alias setup."""
        return f"http://127.0.0.1:{self.api_port}"

    # Back-compat wrappers
    def endpoint_url(self, use_local: bool = False) -> str:
        return self.api_url()

    # ── Bucket policy helpers (standard S3 bucket-policy REST API) ────────────

    def _s3_request(
        self,
        method:  str,
        path:    str,
        params:  dict = None,
        data:    bytes = None,
        headers: dict = None,
    ):
        """Issue a raw authenticated request against the internal RustFS S3 endpoint."""
        if not _HAS_REQUESTS:
            raise RuntimeError("requests package required")
        url = f"http://127.0.0.1:{self.api_port}{path}"
        return _requests.request(
            method, url,
            params=params, data=data,
            headers=headers or {},
            auth=(self.admin_user, self.admin_password),
            timeout=10,
        )

    def set_bucket_public(self, bucket: str) -> tuple[bool, str]:
        """Make a bucket publicly readable (anonymous GET allowed)."""
        import json
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect":    "Allow",
                "Principal": "*",
                "Action":    ["s3:GetObject"],
                "Resource":  [f"arn:aws:s3:::{bucket}/*"],
            }],
        }
        try:
            r = self._s3_request(
                "PUT", f"/{bucket}",
                params={"policy": ""},
                data=json.dumps(policy).encode(),
                headers={"Content-Type": "application/json"},
            )
            if r.status_code in (200, 204):
                return True, f"Bucket '{bucket}' is now public (read-only)."
            return False, f"HTTP {r.status_code}: {r.text.strip()}"
        except Exception as exc:
            return False, str(exc)

    def set_bucket_private(self, bucket: str) -> tuple[bool, str]:
        """Remove the bucket policy (reverts to private / authenticated-only)."""
        try:
            r = self._s3_request("DELETE", f"/{bucket}", params={"policy": ""})
            if r.status_code in (200, 204):
                return True, f"Bucket '{bucket}' is now private."
            return False, f"HTTP {r.status_code}: {r.text.strip()}"
        except Exception as exc:
            return False, str(exc)

    def get_bucket_policy(self, bucket: str) -> str:
        """Return 'public' or 'private' by inspecting the S3 bucket policy."""
        try:
            r = self._s3_request("GET", f"/{bucket}", params={"policy": ""})
            if r.status_code == 200:
                import json as _json
                data = _json.loads(r.text)
                for stmt in data.get("Statement", []):
                    if stmt.get("Effect") == "Allow" and stmt.get("Principal") in (
                        "*", {"AWS": "*"}
                    ):
                        return "public"
            return "private"
        except Exception:
            return "private"

    # ── Folder (prefix) helpers ───────────────────────────────────────────────

    def create_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        """Create a virtual folder by uploading a zero-byte .keep placeholder."""
        folder = folder.strip("/")
        if not folder:
            return False, "Folder name cannot be empty."
        try:
            r = self._s3_request("PUT", f"/{bucket}/{folder}/.keep", data=b"")
            if r.status_code in (200, 201):
                return True, f"Folder '{folder}' created in '{bucket}'."
            return False, f"HTTP {r.status_code}: {r.text.strip()}"
        except Exception as exc:
            return False, str(exc)

    def list_folders(self, bucket: str, prefix: str = "") -> list[str]:
        """List immediate sub-folders (common prefixes) via ListObjectsV2."""
        params: dict = {"list-type": "2", "delimiter": "/", "max-keys": "1000"}
        if prefix:
            params["prefix"] = prefix.strip("/") + "/"
        try:
            r = self._s3_request("GET", f"/{bucket}", params=params)
            if r.status_code != 200:
                return []
            import xml.etree.ElementTree as ET
            ns      = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root    = ET.fromstring(r.text)
            folders = []
            for cp in root.findall("s3:CommonPrefixes", ns):
                p    = cp.findtext("s3:Prefix", namespaces=ns) or ""
                name = p.rstrip("/")
                if prefix:
                    name = name[len(prefix.strip("/")) + 1:]
                if name:
                    folders.append(name)
            return folders
        except Exception:
            return []

    def delete_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        """Recursively delete a folder and all objects under it via multi-delete."""
        folder = folder.strip("/") + "/"
        if folder == "/":
            return False, "Folder name cannot be empty."

        params: dict = {"list-type": "2", "prefix": folder, "max-keys": "1000"}
        try:
            r = self._s3_request("GET", f"/{bucket}", params=params)
            if r.status_code != 200:
                return False, f"Could not list objects: HTTP {r.status_code}"

            import xml.etree.ElementTree as ET, base64, hashlib
            ns   = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(r.text)
            keys = [
                c.findtext("s3:Key", namespaces=ns)
                for c in root.findall("s3:Contents", ns)
            ]

            if not keys:
                return True, f"Folder '{folder.rstrip('/')}' deleted (was already empty)."

            objects_xml = "".join(f"<Object><Key>{k}</Key></Object>" for k in keys if k)
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"<Delete>{objects_xml}</Delete>"
            ).encode("utf-8")
            md5 = base64.b64encode(hashlib.md5(body).digest()).decode()

            dr = self._s3_request(
                "POST", f"/{bucket}",
                params={"delete": ""},
                data=body,
                headers={
                    "Content-Type":   "application/xml",
                    "Content-MD5":    md5,
                    "Content-Length": str(len(body)),
                },
            )
            if dr.status_code in (200, 204):
                return True, f"Folder '{folder.rstrip('/')}' deleted from '{bucket}'."
            return False, f"Delete failed: HTTP {dr.status_code}: {dr.text.strip()}"
        except Exception as exc:
            return False, str(exc)

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