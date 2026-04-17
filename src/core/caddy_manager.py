"""
caddy_manager.py
Manages the Caddy reverse proxy for PGOps.

Architecture (post-mkcert migration):
  - Caddy uses `tls <cert> <key>` pointing to mkcert-issued certificate
  - mkcert CA is trusted system-wide → zero browser warnings on LAN
  - Every service gets its own subdomain under pgops.test:
      pgops.test              → landing page  (port 8080)
      minio.pgops.test        → MinIO API     (port 9000)
      console.pgops.test      → MinIO Console (port 9001)
      pgadmin.pgops.test      → pgAdmin       (port 5050)
      <app>.pgops.test        → Laravel apps  (port 8081+)
  - HTTP is redirected to HTTPS automatically
  - Caddy admin API on 127.0.0.1:2019 for zero-downtime reloads
"""

import os
import sys
import subprocess
import platform
import socket
import time
import shutil
import threading
from pathlib import Path
from typing import Optional


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


# ── Path helpers ──────────────────────────────────────────────────────────────

def get_caddy_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "caddy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_caddy_data_dir() -> Path:
    d = get_caddy_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_caddy_config_dir() -> Path:
    d = get_caddy_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_caddy_bin() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return get_caddy_dir() / f"caddy{ext}"


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


# ── Availability checks ───────────────────────────────────────────────────────

def is_caddy_available() -> bool:
    return get_caddy_bin().exists()


def is_caddy_process_running() -> bool:
    try:
        import psutil
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = (proc.info.get("name") or "").lower()
                exe  = (proc.info.get("exe")  or "").lower()
                if "caddy" in name or "caddy" in exe:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        pass
    return False


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def is_caddy_admin_running(admin_port: int = 2019) -> bool:
    return is_port_open(admin_port)


# ── Binary setup ──────────────────────────────────────────────────────────────

def setup_caddy_binary(progress_callback=None) -> tuple[bool, str]:
    """Extract from assets/ or download from GitHub releases."""
    dest = get_caddy_bin()
    if dest.exists():
        if progress_callback:
            progress_callback(100)
        return True, "Caddy already available."

    asset_name = "caddy.exe" if platform.system() == "Windows" else "caddy"
    bundled    = get_assets_dir() / asset_name

    if bundled.exists():
        shutil.copy2(bundled, dest)
        if platform.system() != "Windows":
            dest.chmod(0o755)
        if progress_callback:
            progress_callback(100)
        return True, "Caddy extracted from bundle."

    # Download latest from GitHub
    sys_name = platform.system()
    machine  = platform.machine().lower()

    if sys_name == "Windows":
        fname = "caddy_windows_amd64.zip"
    elif sys_name == "Darwin":
        arch  = "arm64" if ("arm" in machine or "aarch" in machine) else "amd64"
        fname = f"caddy_darwin_{arch}.tar.gz"
    else:
        fname = "caddy_linux_amd64.tar.gz"

    url = f"https://github.com/caddyserver/caddy/releases/latest/download/{fname}"

    try:
        import requests
        import zipfile
        import tarfile
        import tempfile

        if progress_callback:
            progress_callback(5)

        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        total      = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with tempfile.NamedTemporaryFile(delete=False, suffix=fname) as tf:
            tmp_path = tf.name
            for chunk in resp.iter_content(chunk_size=65536):
                tf.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(5 + int(downloaded / total * 80))

        extract_dir = get_caddy_dir() / "_extract"
        extract_dir.mkdir(exist_ok=True)

        if fname.endswith(".zip"):
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(extract_dir)
        else:
            with tarfile.open(tmp_path, "r:gz") as tf:
                tf.extractall(extract_dir)

        caddy_exe = "caddy.exe" if sys_name == "Windows" else "caddy"
        found = next(extract_dir.rglob(caddy_exe), None)

        if found and found.exists():
            shutil.copy2(found, dest)
            if sys_name != "Windows":
                dest.chmod(0o755)
            shutil.rmtree(extract_dir, ignore_errors=True)
            Path(tmp_path).unlink(missing_ok=True)
            if progress_callback:
                progress_callback(100)
            return True, "Caddy downloaded and installed."

        shutil.rmtree(extract_dir, ignore_errors=True)
        Path(tmp_path).unlink(missing_ok=True)
        return False, "Caddy binary not found in downloaded archive."

    except Exception as exc:
        return False, (
            f"Could not download Caddy: {exc}\n\n"
            f"Download manually from https://caddyserver.com/download and place as:\n{dest}"
        )


# ── Caddyfile generation ──────────────────────────────────────────────────────

def generate_caddyfile(
    apps: list,
    http_port:    int = 80,
    https_port:   int = 443,
    landing_port: int = 8080,
    admin_port:   int = 2019,
    minio_api_port:     int = 9000,
    minio_console_port: int = 9001,
    pgadmin_port:       int = 5050,
    pgadmin_enabled:    bool = False,
    cert_file: str = "",
    key_file:  str = "",
) -> str:
    """
    Generate a Caddyfile that:
      1. Redirects all HTTP → HTTPS
      2. Uses the mkcert cert+key for every HTTPS site
      3. Routes every known service subdomain
      4. Routes every deployed app subdomain

    If cert_file/key_file are not provided, falls back to `tls internal`
    (Caddy's built-in CA — requires manual trust on each device).
    """
    # Determine TLS directive
    if cert_file and key_file:
        tls_line = f"    tls {cert_file} {key_file}"
        tls_mode = "mkcert"
    else:
        tls_line = "    tls internal"
        tls_mode = "internal"

    caddy_data = str(get_caddy_data_dir()).replace("\\", "/")
    cert_f     = cert_file.replace("\\", "/") if cert_file else ""
    key_f      = key_file.replace("\\", "/")  if key_file  else ""
    tls_dir    = f"    tls {cert_f} {key_f}" if (cert_f and key_f) else "    tls internal"

    lines = [
        "{",
        f"    admin 127.0.0.1:{admin_port}",
        f"    http_port {http_port}",
        f"    https_port {https_port}",
        f"    storage file_system {{",
        f"        root {caddy_data}",
        f"    }}",
        # Disable Caddy's internal CA when using mkcert — keeps things clean
        *(
            ["    pki {", '        ca local { name "PGOps Local CA" }', "    }"]
            if not (cert_f and key_f)
            else []
        ),
        "}",
        "",
    ]

    # ── HTTP → HTTPS global redirect ────────────────────────────────────────
    lines += [
        f"http://pgops.test {{",
        f"    redir https://pgops.test{{uri}} permanent",
        "}",
        "",
        f"http://*.pgops.test {{",
        f"    redir https://{{host}}{{uri}} permanent",
        "}",
        "",
    ]

    # ── pgops.test root (landing page) ──────────────────────────────────────
    lines += [
        f"pgops.test:{https_port} {{",
        tls_dir,
        f"    reverse_proxy 127.0.0.1:{landing_port}",
        "}",
        "",
    ]

    # ── minio.pgops.test → MinIO API ────────────────────────────────────────
    lines += [
        f"minio.pgops.test:{https_port} {{",
        tls_dir,
        f"    reverse_proxy 127.0.0.1:{minio_api_port}",
        "}",
        "",
    ]

    # ── console.pgops.test → MinIO Console ──────────────────────────────────
    lines += [
        f"console.pgops.test:{https_port} {{",
        tls_dir,
        f"    reverse_proxy 127.0.0.1:{minio_console_port}",
        "}",
        "",
    ]

    # ── pgadmin.pgops.test → pgAdmin (when running) ─────────────────────────
    if pgadmin_enabled:
        lines += [
            f"pgadmin.pgops.test:{https_port} {{",
            tls_dir,
            f"    reverse_proxy 127.0.0.1:{pgadmin_port}",
            "}",
            "",
        ]

    # ── App subdomains ───────────────────────────────────────────────────────
    for app in apps:
        domain = app.get("domain", "")
        port   = app.get("internal_port", 8081)
        if not domain:
            continue
        # Include all apps in routing — stopped apps show a 502 (by design:
        # user can see the domain is registered and knows to start the app)
        lines += [
            f"{domain}:{https_port} {{",
            tls_dir,
            f"    reverse_proxy 127.0.0.1:{port}",
            "}",
            "",
        ]

    caddyfile_path = get_caddy_dir() / "Caddyfile"
    caddyfile_path.write_text("\n".join(lines), encoding="utf-8")
    return str(caddyfile_path)


def _build_caddy_env() -> dict:
    """Build environment for Caddy process."""
    env = {**os.environ}
    caddy_data = str(get_caddy_data_dir())
    env["XDG_DATA_HOME"]  = caddy_data
    env["CADDY_DATA_DIR"] = caddy_data
    if platform.system() != "Windows":
        env["HOME"] = caddy_data
    if platform.system() == "Windows":
        env["APPDATA"]      = caddy_data
        env["LOCALAPPDATA"] = caddy_data
    return env


# ── CaddyManager ─────────────────────────────────────────────────────────────

class CaddyManager:

    ADMIN_PORT = 2019

    def __init__(self, config: dict, log_fn=None):
        self.config = config
        self._log   = log_fn or print
        self._proc: Optional[subprocess.Popen] = None
        self._lock  = threading.Lock()

    def log(self, msg: str):
        self._log(msg)

    # ── Port properties ───────────────────────────────────────────────────────

    @property
    def http_port(self) -> int:
        return self.config.get("caddy_http_port", 80)

    @property
    def https_port(self) -> int:
        return self.config.get("caddy_https_port", 443)

    @property
    def landing_port(self) -> int:
        return self.config.get("landing_port", 8080)

    @property
    def minio_api_port(self) -> int:
        return self.config.get("minio_api_port", 9000)

    @property
    def minio_console_port(self) -> int:
        return self.config.get("minio_console_port", 9001)

    @property
    def pgadmin_port(self) -> int:
        return self.config.get("pgadmin_port", 5050)

    # ── mkcert integration ────────────────────────────────────────────────────

    def _get_tls_files(self) -> tuple[str, str]:
        """
        Return (cert_file, key_file) if mkcert cert exists, else ("", "").
        """
        try:
            from core.mkcert_manager import get_cert_path, get_key_path, is_cert_generated
            if is_cert_generated():
                return str(get_cert_path()), str(get_key_path())
        except Exception:
            pass
        return "", ""

    def ensure_tls_cert(self) -> tuple[bool, str]:
        """
        Make sure an mkcert cert exists. Generate one if not.
        Called automatically before starting Caddy.
        """
        try:
            from core.mkcert_manager import is_cert_generated, generate_cert, is_available
            if is_cert_generated():
                return True, "TLS certificate ready."
            if not is_available():
                return False, "mkcert not available — Caddy will use internal CA instead."
            ok, msg = generate_cert(log_fn=self._log)
            return ok, msg
        except Exception as exc:
            return False, f"TLS cert check failed: {exc}"

    # ── Availability / running ────────────────────────────────────────────────

    def is_available(self) -> bool:
        return is_caddy_available()

    def is_running(self) -> bool:
        if is_caddy_admin_running(self.ADMIN_PORT):
            return True
        if is_caddy_process_running():
            return True
        return is_port_open(self.https_port) or is_port_open(self.http_port)

    # ── Start / Stop / Reload ─────────────────────────────────────────────────

    def start(self, apps: list, pgadmin_running: bool = False) -> tuple[bool, str]:
        if not is_caddy_available():
            return False, "Caddy binary not found. Click Setup Caddy first."

        if self.is_running():
            self._log("[Caddy] Already running.")
            return True, "Caddy already running."

        # Ensure mkcert cert is available
        cert_ok, cert_msg = self.ensure_tls_cert()
        if cert_ok:
            self._log(f"[Caddy] {cert_msg}")
        else:
            self._log(f"[Caddy] Warning: {cert_msg} — falling back to internal CA.")

        cert_file, key_file = self._get_tls_files()

        caddyfile = generate_caddyfile(
            apps,
            http_port=self.http_port,
            https_port=self.https_port,
            landing_port=self.landing_port,
            admin_port=self.ADMIN_PORT,
            minio_api_port=self.minio_api_port,
            minio_console_port=self.minio_console_port,
            pgadmin_port=self.pgadmin_port,
            pgadmin_enabled=pgadmin_running,
            cert_file=cert_file,
            key_file=key_file,
        )
        self._log(f"[Caddy] Caddyfile → {caddyfile}")

        env = _build_caddy_env()
        cmd = [str(get_caddy_bin()), "run", "--config", caddyfile]

        try:
            kwargs = _popen_kwargs()
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
            kwargs["env"]    = env
            with self._lock:
                self._proc = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start Caddy: {exc}"

        # Wait up to 20 s for admin API
        for _ in range(40):
            time.sleep(0.5)
            if is_caddy_admin_running(self.ADMIN_PORT):
                tls_mode = "mkcert" if cert_file else "internal CA"
                self._log(
                    f"[Caddy] Running — "
                    f"HTTP:{self.http_port} HTTPS:{self.https_port} TLS:{tls_mode}\n"
                    f"[Caddy] pgops.test | minio.pgops.test | console.pgops.test"
                    + (" | pgadmin.pgops.test" if pgadmin_running else "")
                    + (f" | + {len([a for a in apps if a.get('domain')])} app(s)" if apps else "")
                )
                return True, (
                    f"Caddy started ({tls_mode}). "
                    f"Domains: pgops.test, *.pgops.test"
                )

        return False, "Caddy did not start in time (admin API not responding)."

    def reload(self, apps: list = None, pgadmin_running: bool = False) -> tuple[bool, str]:
        """Regenerate Caddyfile and hot-reload via admin API."""
        if not self.is_running():
            return False, "Caddy not running."

        # Regenerate with latest app list
        if apps is not None:
            cert_file, key_file = self._get_tls_files()
            generate_caddyfile(
                apps,
                http_port=self.http_port,
                https_port=self.https_port,
                landing_port=self.landing_port,
                admin_port=self.ADMIN_PORT,
                minio_api_port=self.minio_api_port,
                minio_console_port=self.minio_console_port,
                pgadmin_port=self.pgadmin_port,
                pgadmin_enabled=pgadmin_running,
                cert_file=cert_file,
                key_file=key_file,
            )

        caddyfile = str(get_caddy_dir() / "Caddyfile")
        if not Path(caddyfile).exists():
            return False, "Caddyfile not found."

        # Try admin API hot-reload
        try:
            import urllib.request

            env = _build_caddy_env()
            r = subprocess.run(
                [str(get_caddy_bin()), "adapt", "--config", caddyfile],
                capture_output=True, text=True, env=env, **_popen_kwargs(),
            )
            if r.returncode != 0:
                return False, f"caddy adapt failed: {r.stderr}"

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.ADMIN_PORT}/load",
                data=r.stdout.strip().encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    self._log("[Caddy] Config reloaded via admin API.")
                    return True, "Caddy reloaded."
                return False, f"Admin API returned {resp.status}"
        except Exception as exc:
            self._log(f"[Caddy] Admin API reload failed, trying CLI: {exc}")

        # CLI fallback
        env = _build_caddy_env()
        r = subprocess.run(
            [str(get_caddy_bin()), "reload", "--config", caddyfile],
            capture_output=True, text=True, env=env, **_popen_kwargs(),
        )
        if r.returncode == 0:
            return True, "Caddy reloaded via CLI."
        return False, (r.stdout + r.stderr).strip()

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            proc = self._proc
            self._proc = None

        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if is_caddy_process_running():
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "caddy.exe"],
                    capture_output=True, **_popen_kwargs(),
                )
            else:
                subprocess.run(["pkill", "-f", "caddy run"], capture_output=True)

        self._log("[Caddy] Stopped.")
        return True, "Caddy stopped."

    def update_apps(self, apps: list, pgadmin_running: bool = False) -> tuple[bool, str]:
        """Called when an app is deployed/deleted/started/stopped."""
        if self.is_running():
            return self.reload(apps=apps, pgadmin_running=pgadmin_running)
        # Just update the Caddyfile so it's ready for next start
        cert_file, key_file = self._get_tls_files()
        generate_caddyfile(
            apps,
            http_port=self.http_port,
            https_port=self.https_port,
            landing_port=self.landing_port,
            admin_port=self.ADMIN_PORT,
            minio_api_port=self.minio_api_port,
            minio_console_port=self.minio_console_port,
            pgadmin_port=self.pgadmin_port,
            pgadmin_enabled=pgadmin_running,
            cert_file=cert_file,
            key_file=key_file,
        )
        return True, "Caddyfile updated (Caddy not running)."

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status_detail(self) -> dict:
        try:
            from core.mkcert_manager import get_status as mkcert_status
            mk = mkcert_status()
        except Exception:
            mk = {}

        return {
            "running":        self.is_running(),
            "available":      is_caddy_available(),
            "http_port":      self.http_port,
            "https_port":     self.https_port,
            # mkcert info
            "mkcert_available":    mk.get("available", False),
            "mkcert_ca_installed": mk.get("ca_installed", False),
            "mkcert_cert_exists":  mk.get("cert_exists", False),
            "ca_path":             mk.get("ca_path", ""),
            "cert_info":           mk.get("cert_info", {}),
            # Backward-compat keys (used by tab_ssl)
            "ca_available": mk.get("ca_installed", False),
        }

    def console_url(self) -> str:
        return f"https://pgops.test" if self.https_port == 443 else f"https://pgops.test:{self.https_port}"

    # ── Legacy compat (used by tab_ssl for export) ────────────────────────────

    def get_ca_cert_path(self):
        try:
            from core.mkcert_manager import get_ca_cert_path
            return get_ca_cert_path()
        except Exception:
            return None

    def install_ca(self) -> tuple[bool, str]:
        try:
            from core.mkcert_manager import install_ca
            return install_ca(log_fn=self._log)
        except Exception as exc:
            return False, str(exc)

    def export_ca(self, dest: str) -> tuple[bool, str]:
        try:
            from core.mkcert_manager import export_ca_cert
            return export_ca_cert(dest)
        except Exception as exc:
            return False, str(exc)
