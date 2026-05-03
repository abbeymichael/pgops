"""
rustfs_manager.py
Manages the RustFS object storage server (S3-compatible drop-in for MinIO).
Mirrors the structure of pg_manager.py for consistency.

URL strategy (post-Caddy/mkcert migration):
  - All external-facing URLs use the mkcert-secured Caddy subdomains:
      API endpoint  → https://storage.pgops.local:<https_port>
      Web console   → https://storage-console.pgops.local:<https_port>
  - RustFS itself still listens on plain HTTP internally (127.0.0.1:9000).
    Caddy terminates TLS and reverse-proxies to it.
  - Laravel .env must use the HTTPS Caddy URL as AWS_ENDPOINT so that
    apps on the LAN can reach storage without certificate warnings.
  - The raw internal URL (http://127.0.0.1:9000) is only used for mc
    alias registration and internal health checks.

Lifecycle orchestration:
  - RustFSManager tracks its own subprocess and performs health polling.
  - start()  → spawn process → wait-for-port loop → register mc alias.
  - stop()   → graceful mc admin service stop → terminate → force-kill fallback.
  - restart() → stop() then start() with full health gate.
  - The manager never returns "started" until the health endpoint responds 200,
    so callers can depend on the service being genuinely ready.
  - watchdog_tick() is called periodically by MainWindow._poll(); it auto-restarts
    a crashed process if _should_run is True.
"""

import os
import sys
import subprocess
import platform
import shutil
import socket
import time
import threading
import requests
from pathlib import Path

# ── Download URLs ─────────────────────────────────────────────────────────────
# RustFS releases mirror the MinIO binary layout.
RUSTFS_DOWNLOAD = {
    "Windows": "https://dl.rustfs.com/server/rustfs/release/windows-amd64/rustfs.exe",
    "Darwin": "https://dl.rustfs.com/server/rustfs/release/darwin-amd64/rustfs",
}

# mc (MinIO Client) — fully compatible with RustFS S3 API
MC_DOWNLOAD = {
    "Windows": "https://dl.min.io/client/mc/release/windows-amd64/mc.exe",
    "Darwin": "https://dl.min.io/client/mc/release/darwin-amd64/mc",
}

# Bundled asset names (place in assets/ before building)
RUSTFS_BUNDLED = {
    "Windows": "rustfs.exe",
    "Darwin": "rustfs",
}
MC_BUNDLED = {
    "Windows": "mc.exe",
    "Darwin": "mc",
}


# How long to wait for the health endpoint before giving up
_HEALTH_TIMEOUT_S = 20
# Interval between health polls during startup
_HEALTH_POLL_INTERVAL = 0.5


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp

        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


# ── Path helpers ───────────────────────────────────────────────────────────────


def get_rustfs_dir() -> Path:
    """Directory where rustfs and mc binaries live."""
    from core.pg_manager import get_app_data_dir

    d = get_app_data_dir() / "rustfs-bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_dir() -> Path:
    """Persistent object storage data directory."""
    from core.pg_manager import get_app_data_dir

    d = get_app_data_dir() / "rustfs-data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


def _bin(name: str) -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    base = name.rstrip(".exe")
    return get_rustfs_dir() / f"{base}{ext}"


def rustfs_bin() -> Path:
    return _bin("rustfs")


def mc_bin() -> Path:
    return _bin("mc")


def is_binaries_available() -> bool:
    return rustfs_bin().exists()


def is_mc_available() -> bool:
    return mc_bin().exists()


# ── RustFSManager ─────────────────────────────────────────────────────────────


class RustFSManager:
    """
    Full lifecycle manager for the RustFS object storage server.

    Responsibilities
    ----------------
    • Binary setup   – extract from bundle or download from the internet.
    • Start / stop   – spawn / terminate the rustfs process.
    • Health gate    – block start() until the HTTP health endpoint is 200.
    • mc alias       – register the `pgops` alias after a successful start.
    • Watchdog       – watchdog_tick() is called by the 3-second poll timer;
                       it restarts a crashed process automatically when
                       _should_run is True (i.e. the user asked for it to run).
    • URL helpers    – return the public HTTPS Caddy URLs (storage.pgops.local)
                       for use in .env files and the UI.
    """

    ALIAS = "pgops"
    API_PORT = 9000
    CONSOLE_PORT = 9001

    def __init__(self, config: dict, log_fn=None):
        env = os.environ.copy()

        self.config = config
        self._log = log_fn or print
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        # Tracks *intent*: True means "the user wants this running".
        # The watchdog uses this to decide whether to auto-restart.
        self._should_run = False
        self._restart_count = 0
        self._MAX_AUTO_RESTARTS = 5  # give up after N *consecutive* crashes
        # Monotonic timestamp of the last moment RustFS was observed healthy.
        # Used by the watchdog to distinguish a fresh crash from a crash loop.
        self._last_healthy_time: float = 0.0
        # How long (seconds) RustFS must have been stable before the watchdog
        # treats a new crash as the start of a fresh restart sequence.
        self._STABLE_UPTIME_S: float = 90.0
        # Guards against two concurrent start() calls (e.g. watchdog firing
        # while the initial startup worker thread is still in start()).
        self._is_starting = False

    def log(self, msg: str):
        self._log(msg)

    # ── Config properties ──────────────────────────────────────────────────────

    @property
    def admin_user(self) -> str:
        return self.config.get("username", "postgres")

    @property
    def admin_password(self) -> str:
        return self.config.get("password", "postgres")

    @property
    def api_port(self) -> int:
        return self.config.get("rustfs_api_port", self.API_PORT)

    @property
    def console_port(self) -> int:
        return self.config.get("rustfs_console_port", self.CONSOLE_PORT)

    @property
    def https_port(self) -> int:
        """Caddy HTTPS port — used to build the public-facing URLs."""
        return self.config.get("caddy_https_port", 8443)

    # ── Binary setup ───────────────────────────────────────────────────────────

    def is_binaries_available(self) -> bool:
        return rustfs_bin().exists()

    def is_mc_available(self) -> bool:
        return mc_bin().exists()

    def setup_binaries(self, progress_callback=None) -> tuple[bool, str]:
        """
        Extract from assets/ if available, otherwise download.
        Sets up both rustfs server binary and mc (MinIO-compatible client).
        """
        system = platform.system()
        ok1, msg1 = self._setup_binary(
            "rustfs",
            RUSTFS_BUNDLED.get(system, ""),
            RUSTFS_DOWNLOAD.get(system, ""),
            progress_callback=lambda p: (
                progress_callback(p // 2) if progress_callback else None
            ),
        )
        if not ok1:
            return False, msg1

        ok2, msg2 = self._setup_binary(
            "mc",
            MC_BUNDLED.get(system, ""),
            MC_DOWNLOAD.get(system, ""),
            progress_callback=lambda p: (
                progress_callback(50 + p // 2) if progress_callback else None
            ),
        )
        if not ok2:
            return False, msg2

        if progress_callback:
            progress_callback(100)
        return True, "RustFS binaries ready."

    def _setup_binary(
        self, name: str, bundled_name: str, url: str, progress_callback=None
    ) -> tuple[bool, str]:
        dest = _bin(name)
        if dest.exists():
            self.log(f"{name} already available.")
            return True, f"{name} ready."

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

    # ── Port / health checks ───────────────────────────────────────────────────

    def is_port_open(self) -> bool:
        """Low-level TCP check — fast but doesn't confirm the service is ready."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", self.api_port))
            s.close()
            return result == 0
        except Exception:
            return False

    def is_healthy(self) -> bool:
        """
        Check liveness via a plain TCP connection to the API port.
        We do NOT use an HTTP GET because RustFS may interpret unknown URL paths
        as GetObject requests, which it rejects with AccessDenied — and enough
        of those rapid rejections crash the process.
        """
        return self.is_port_open()

    def is_running(self) -> bool:
        """
        Combined check:
          1. If we hold a live Popen handle → verify the process is still alive.
          2. Fall back to TCP port check (catches processes started outside PGOps).
        """
        with self._lock:
            proc = self._proc
        if proc is not None:
            if proc.poll() is None:
                return self.is_port_open()
            else:
                with self._lock:
                    self._proc = None
        return self.is_port_open()

    # ── Server lifecycle ───────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        """
        Start RustFS and block until the health endpoint returns 200.

        Lifecycle:
          1. Guard: already starting? (concurrent call protection)
          2. Guard: already running?
          3. Guard: binary exists?
          4. Spawn subprocess.
          5. Poll health endpoint for up to _HEALTH_TIMEOUT_S seconds.
          6. On success: set _should_run=True, reset restart counter, register mc alias.
          7. On timeout: terminate the process and return failure.
        """
        # Prevent two simultaneous start() calls (e.g. watchdog + initial boot).
        with self._lock:
            if self._is_starting:
                return False, "RustFS start already in progress — skipping."
            self._is_starting = True
        try:
            return self._start_inner()
        finally:
            with self._lock:
                self._is_starting = False

    def _start_inner(self) -> tuple[bool, str]:
        if self.is_running():
            self.log("[RustFS] Already running.")
            self._should_run = True
            return True, "RustFS already running."

        if not is_binaries_available():
            return False, "RustFS binary not found. Run setup first."

        data_dir = get_data_dir()
        env = {
            **os.environ,
            "RUSTFS_ACCESS_KEY": self.admin_user,
            "RUSTFS_SECRET_KEY": self.admin_password,
        }

        cmd = [
            str(rustfs_bin()),
            "server",
            str(data_dir),
            "--address",
            f"127.0.0.1:{self.api_port}",
            "--console-address",
            f"127.0.0.1:{self.console_port}",
        ]

        # Always reset the watchdog gave-up state on an explicit start() call so
        # the operator never has to know about the internal retry limit.
        self._restart_count = 0

        # Redirect RustFS output to a log file so crashes leave a paper trail.
        log_path = get_data_dir().parent / "rustfs.log"
        self.log(
            f"[RustFS] Spawning process on port {self.api_port}… (log → {log_path})"
        )
        try:
            log_fh = open(log_path, "a", buffering=1)  # line-buffered
            kwargs = _popen_kwargs()
            kwargs["env"] = env
            kwargs["stdout"] = log_fh
            kwargs["stderr"] = log_fh
            with self._lock:
                self._proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            return False, f"Failed to start RustFS: {e}"

        # ── Health gate ───────────────────────────────────────────────────────
        deadline = time.monotonic() + _HEALTH_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_HEALTH_POLL_INTERVAL)

            # Abort early if the process died immediately
            with self._lock:
                proc = self._proc
            if proc is not None and proc.poll() is not None:
                with self._lock:
                    self._proc = None
                return False, (
                    f"RustFS exited immediately (code {proc.returncode}). "
                    "Check credentials or port conflicts."
                )

            if self.is_healthy():
                self._should_run = True
                self._restart_count = 0
                self._last_healthy_time = time.monotonic()
                self.log(
                    f"[RustFS] Ready — API port {self.api_port}, console port {self.console_port}."
                )
                self._configure_mc_alias()
                return True, f"RustFS started on port {self.api_port}."

        # Timed out — kill the process we started
        self._force_stop_proc()
        return False, (
            f"RustFS did not become healthy within {_HEALTH_TIMEOUT_S}s. "
            "Check logs for port conflicts or configuration errors."
        )

    def stop(self) -> tuple[bool, str]:
        """
        Graceful stop via mc admin service stop, then terminate/kill fallback.
        Sets _should_run=False so the watchdog does NOT auto-restart.
        """
        self._should_run = False

        if not self.is_running():
            return True, "RustFS not running."

        # Attempt graceful shutdown through mc
        if is_mc_available():
            self.log("[RustFS] Requesting graceful shutdown via mc…")
            subprocess.run(
                [str(mc_bin()), "admin", "service", "stop", self.ALIAS],
                capture_output=True,
                timeout=10,
                **_popen_kwargs(),
            )
            # Give it a moment to shut down cleanly
            for _ in range(10):
                time.sleep(0.3)
                if not self.is_running():
                    self.log("[RustFS] Stopped gracefully.")
                    return True, "RustFS stopped."

        self._force_stop_proc()
        self.log("[RustFS] Stopped.")
        return True, "RustFS stopped."

    def restart(self) -> tuple[bool, str]:
        """Stop then start with full health gate."""
        self.log("[RustFS] Restarting…")
        self.stop()
        time.sleep(1)
        return self.start()

    def _force_stop_proc(self):
        """Terminate then kill the managed process; also hunt by process name."""
        with self._lock:
            proc = self._proc
            self._proc = None

        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # Belt-and-suspenders: kill any orphan by executable name
        if self.is_port_open():
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "rustfs.exe"],
                    capture_output=True,
                    **_popen_kwargs(),
                )
            else:
                subprocess.run(
                    ["pkill", "-f", "rustfs server"],
                    capture_output=True,
                )

    # ── Watchdog ───────────────────────────────────────────────────────────────

    def watchdog_tick(self, dispatch_fn=None):
        """
        Called by the main window's 3-second poll timer.

        If the user has asked for RustFS to run (_should_run=True) but the
        process is no longer healthy, schedule an automatic restart — up to
        _MAX_AUTO_RESTARTS *consecutive* times.

        dispatch_fn — if provided, the restart is handed off to it rather than
        called inline.  This keeps start()'s 20-second health-poll loop off the
        Qt main thread.  Signature: dispatch_fn(callable) where callable is
        self.start.  Pass None only in non-UI contexts (tests, CLI tools).

        "Consecutive" is time-gated: if RustFS was last seen healthy more than
        _STABLE_UPTIME_S seconds ago the crash counter resets, treating this as
        a fresh incident rather than a tight crash loop.
        """
        if not self._should_run:
            return

        if self.is_running():
            self._restart_count = 0
            self._last_healthy_time = time.monotonic()
            return

        # If start() is already running (e.g. initial boot worker still active),
        # don't queue another restart — just wait for it to finish.
        with self._lock:
            if self._is_starting:
                return

        # Time-based reset: if RustFS was stable long enough before this crash,
        # treat it as a new incident and reset the consecutive-restart counter.
        if self._last_healthy_time > 0:
            uptime_before_crash = time.monotonic() - self._last_healthy_time
            if uptime_before_crash >= self._STABLE_UPTIME_S:
                if self._restart_count > 0:
                    self.log(
                        f"[RustFS] Process ran for {uptime_before_crash:.0f}s before "
                        "crashing — resetting restart counter."
                    )
                self._restart_count = 0
                self._last_healthy_time = 0.0

        if self._restart_count >= self._MAX_AUTO_RESTARTS:
            if self._restart_count == self._MAX_AUTO_RESTARTS:
                self.log(
                    f"[RustFS] ⚠  Process has crashed {self._MAX_AUTO_RESTARTS} times in "
                    "a row. Automatic restart disabled. Check rustfs.log and restart manually."
                )
                self._restart_count += 1
            return

        self._restart_count += 1
        self.log(
            f"[RustFS] Process not healthy — auto-restart attempt "
            f"{self._restart_count}/{self._MAX_AUTO_RESTARTS}…"
        )

        if dispatch_fn is not None:
            # Hand off to caller's thread pool — never block the Qt event loop.
            dispatch_fn(self.start)
        else:
            ok, msg = self.start()
            if not ok:
                self.log(f"[RustFS] Auto-restart failed: {msg}")

    # ── mc alias ──────────────────────────────────────────────────────────────

    def _configure_mc_alias(self):

        import json

        # Determine mc config path per platform
        if platform.system() == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            config_path = base / "mc" / "config.json"
        else:
            config_path = Path.home() / ".config" / "mc" / "config.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config if present, otherwise start fresh
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                config = {}

        if "version" not in config:
            config["version"] = "10"
        if "aliases" not in config:
            config["aliases"] = {}

        config["aliases"][self.ALIAS] = {
            "url": f"http://127.0.0.1:{self.api_port}",
            "accessKey": self.admin_user,
            "secretKey": self.admin_password,
            "api": "s3v4",
            "path": "auto",
        }

        try:
            config_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
            self.log(f"[RustFS] mc alias '{self.ALIAS}' written to {config_path}")
        except Exception as exc:
            self.log(f"[RustFS] Warning: could not write mc config: {exc}")

    def ensure_mc_alias(self):
        """Call this before any mc operations."""
        self._configure_mc_alias()

    # ── URL helpers ────────────────────────────────────────────────────────────
    #
    # Rule: anything shown to the user or written into .env files uses the
    # HTTPS Caddy subdomain.  The raw internal URL is only used by mc and for
    # health checks inside this process.

    def _caddy_base(self, subdomain: str) -> str:
        """Return https://<subdomain>[:<https_port>] (omit port if 443)."""
        port = self.https_port
        if port == 443:
            return f"https://{subdomain}"
        return f"https://{subdomain}:{port}"

    def api_url(self) -> str:
        """
        Public HTTPS URL for the RustFS S3 API — use this in .env files.
        Routes through Caddy → mkcert TLS on storage.pgops.local.
        """
        return self._caddy_base("storage.pgops.local")

    def console_url(self) -> str:
        """
        Public HTTPS URL for the RustFS web console — open in browser.
        Routes through Caddy → mkcert TLS on storage-console.pgops.local.
        """
        return self._caddy_base("storage-console.pgops.local")

    def internal_api_url(self) -> str:
        """Raw internal URL — used only by mc and health checks."""
        return f"http://127.0.0.1:{self.api_port}"

    # Backwards-compatible alias
    def endpoint_url(self, use_local: bool = False) -> str:
        """Backwards-compatible wrapper — always returns the public HTTPS URL."""
        return self.api_url()

    # ── Bucket policy helpers ──────────────────────────────────────────────────

    def set_bucket_public(self, bucket: str) -> tuple[bool, str]:
        """Make a bucket publicly readable via mc anonymous set download."""
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()
        r = subprocess.run(
            [str(mc_bin()), "anonymous", "set", "download", f"{self.ALIAS}/{bucket}"],
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, f"Bucket '{bucket}' is now public (read-only)."
        return False, r.stderr.strip() or r.stdout.strip()

    def set_bucket_private(self, bucket: str) -> tuple[bool, str]:
        """Make a bucket private via mc anonymous set none."""
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()
        r = subprocess.run(
            [str(mc_bin()), "anonymous", "set", "none", f"{self.ALIAS}/{bucket}"],
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, f"Bucket '{bucket}' is now private."
        return False, r.stderr.strip() or r.stdout.strip()

    def get_bucket_policy(self, bucket: str) -> str:
        """Return 'public' or 'private' by querying mc anonymous get."""
        if not is_mc_available():
            return "unknown"
        self.ensure_mc_alias()
        r = subprocess.run(
            [str(mc_bin()), "anonymous", "get", f"{self.ALIAS}/{bucket}"],
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).lower()
        if "download" in out or "public" in out:
            return "public"
        return "private"

    # ── Folder (prefix) helpers ────────────────────────────────────────────────
    #
    # S3 has no real folders — a "folder" is a key prefix ending in '/'.
    # We create one by uploading a zero-byte placeholder: prefix/.keep

    def create_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
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
                capture_output=True,
                text=True,
                **_popen_kwargs(),
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
        if not is_mc_available():
            return []
        self.ensure_mc_alias()

        path = f"{self.ALIAS}/{bucket}"
        if prefix:
            path += f"/{prefix.strip('/')}/"

        r = subprocess.run(
            [str(mc_bin()), "ls", "--recursive=false", path],
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
        folders = []
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if parts and parts[-1].endswith("/"):
                name = parts[-1].rstrip("/")
                if name and name != ".":
                    folders.append(name)
        return folders

    def delete_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        if not is_mc_available():
            return False, "mc binary not available."
        self.ensure_mc_alias()

        folder = folder.strip("/")
        if not folder:
            return False, "Folder name cannot be empty."

        r = subprocess.run(
            [
                str(mc_bin()),
                "rm",
                "--recursive",
                "--force",
                f"{self.ALIAS}/{bucket}/{folder}/",
            ],
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, f"Folder '{folder}' deleted from '{bucket}'."
        return False, r.stderr.strip() or r.stdout.strip()

    # ── Connection info ────────────────────────────────────────────────────────

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
