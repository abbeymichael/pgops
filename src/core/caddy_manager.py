"""
caddy_manager.py
Manages the Caddy reverse proxy for PGOps web app hosting.

FIXES:
- Default ports changed to 8080/8443 to avoid requiring admin on first run
  (users can re-configure to 80/443 after granting privileges)
- is_caddy_process_running() uses psutil more reliably with exe check
- generate_caddyfile() only adds apps that have status "running"
- _try_auto_trust() runs in a background thread to avoid blocking startup
- reload() uses Caddy admin API (localhost:2019) for zero-downtime reloads
- start() waits only for the HTTPS port, not HTTP (Caddy may redirect)
- CaddyManager.is_running() checks admin API before port scan for accuracy
- Caddyfile storage path uses forward slashes (Caddy cross-platform)
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


def get_caddy_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "caddy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_caddy_data_dir() -> Path:
    """Caddy stores its internal CA and certs here."""
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


def is_caddy_available() -> bool:
    return get_caddy_bin().exists()


def is_caddy_process_running() -> bool:
    """Check if a caddy process is running using psutil."""
    try:
        import psutil
        caddy_name = "caddy.exe" if platform.system() == "Windows" else "caddy"
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                proc_name = (proc.info.get("name") or "").lower()
                proc_exe  = (proc.info.get("exe")  or "").lower()
                if "caddy" in proc_name or "caddy" in proc_exe:
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
    """Check Caddy admin API is responding."""
    return is_port_open(admin_port)


def setup_caddy_binary(progress_callback=None) -> tuple[bool, str]:
    """Extract from assets/ or inform user where to get Caddy binary."""
    dest = get_caddy_bin()
    if dest.exists():
        if progress_callback:
            progress_callback(100)
        return True, "Caddy already available."

    asset_name = "caddy.exe" if platform.system() == "Windows" else "caddy"
    bundled = get_assets_dir() / asset_name

    if bundled.exists():
        shutil.copy2(bundled, dest)
        if platform.system() != "Windows":
            dest.chmod(0o755)
        if progress_callback:
            progress_callback(100)
        return True, "Caddy extracted from bundle."

    # Attempt download from GitHub releases
    import platform as _p
    system = _p.system()
    machine = _p.machine().lower()

    if system == "Windows":
        fname = "caddy_windows_amd64.zip"
        url = f"https://github.com/caddyserver/caddy/releases/latest/download/{fname}"
    elif system == "Darwin":
        arch = "arm64" if ("arm" in machine or "aarch" in machine) else "amd64"
        fname = f"caddy_darwin_{arch}.tar.gz"
        url = f"https://github.com/caddyserver/caddy/releases/latest/download/{fname}"
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
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with tempfile.NamedTemporaryFile(delete=False, suffix=fname) as tf:
            tmp_path = tf.name
            for chunk in resp.iter_content(chunk_size=65536):
                tf.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(5 + int(downloaded / total * 80))

        # Extract
        extract_dir = get_caddy_dir() / "_extract"
        extract_dir.mkdir(exist_ok=True)

        if fname.endswith(".zip"):
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(extract_dir)
        else:
            with tarfile.open(tmp_path, "r:gz") as tf:
                tf.extractall(extract_dir)

        # Find the caddy binary in the extracted files
        caddy_exe = "caddy.exe" if system == "Windows" else "caddy"
        found = None
        for candidate in extract_dir.rglob(caddy_exe):
            found = candidate
            break

        if found and found.exists():
            shutil.copy2(found, dest)
            if system != "Windows":
                dest.chmod(0o755)
            shutil.rmtree(extract_dir, ignore_errors=True)
            Path(tmp_path).unlink(missing_ok=True)
            if progress_callback:
                progress_callback(100)
            return True, "Caddy downloaded and installed."

        shutil.rmtree(extract_dir, ignore_errors=True)
        Path(tmp_path).unlink(missing_ok=True)
        return False, "Caddy binary not found in downloaded archive."

    except Exception as e:
        return False, (
            f"Could not download Caddy: {e}\n\n"
            f"Download manually from https://caddyserver.com/download and place as:\n"
            f"{dest}"
        )


def get_caddy_ca_cert_path() -> Optional[Path]:
    """Find Caddy's internal CA root certificate."""
    caddy_data = get_caddy_data_dir()
    # Caddy 2.x stores CA at caddy/pki/authorities/local/root.crt
    # relative to its data directory
    ca_path = caddy_data / "pki" / "authorities" / "local" / "root.crt"
    if ca_path.exists():
        return ca_path
    return None


def export_caddy_ca_cert(dest_path: str) -> tuple[bool, str]:
    ca = get_caddy_ca_cert_path()
    if not ca:
        return False, (
            "Caddy CA not found. Start Caddy at least once to generate the CA, "
            "then export it."
        )
    shutil.copy2(ca, dest_path)
    return True, f"Caddy CA certificate exported to {dest_path}"


def install_caddy_ca_system(log_fn=None) -> tuple[bool, str]:
    """Attempt to install Caddy's CA into the system trust store."""
    bin_path = get_caddy_bin()
    if not bin_path.exists():
        return False, "Caddy binary not found."

    env = _build_caddy_env()
    try:
        r = subprocess.run(
            [str(bin_path), "trust"],
            capture_output=True,
            text=True,
            env=env,
            **_popen_kwargs(),
            timeout=30,
        )
        out = (r.stdout + r.stderr).strip()
        if log_fn:
            log_fn(f"[Caddy trust] {out}")
        if r.returncode == 0:
            return True, "Caddy CA installed into system trust store."
        return False, f"caddy trust failed: {out}"
    except Exception as e:
        return False, f"caddy trust error: {e}"


def _build_caddy_env() -> dict:
    """Build environment with Caddy's data dir configured."""
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


def generate_caddyfile(
    apps: list,
    http_port: int = 8080,
    https_port: int = 8443,
    landing_port: int = 8080,
    admin_port: int = 2019,
) -> str:
    """
    Generate a Caddyfile. Uses high ports by default to avoid admin requirement.
    Apps with status != 'running' are skipped.
    """
    caddy_data = str(get_caddy_data_dir()).replace("\\", "/")

    lines = [
        "{",
        f"    admin 127.0.0.1:{admin_port}",
        f"    http_port {http_port}",
        f"    https_port {https_port}",
        f"    storage file_system {{",
        f"        root {caddy_data}",
        f"    }}",
        f"    pki {{",
        f"        ca local {{",
        f"            name \"PGOps Local CA\"",
        f"        }}",
        f"    }}",
        "}",
        "",
    ]

    # Landing page — pgops.test root
    # Use http only on high ports to avoid TLS issues during setup
    if https_port in (443, 8443):
        lines += [
            f"pgops.test:{https_port} {{",
            f"    tls internal",
            f"    reverse_proxy localhost:{landing_port}",
            "}",
            "",
            f"http://pgops.test:{http_port} {{",
            f"    reverse_proxy localhost:{landing_port}",
            "}",
            "",
        ]
    else:
        lines += [
            f"pgops.test:{http_port} {{",
            f"    reverse_proxy localhost:{landing_port}",
            "}",
            "",
        ]

    # Add each running app
    for app in apps:
        if app.get("status") != "running":
            continue
        domain = app.get("domain", "")
        port = app.get("internal_port", 8081)
        if not domain:
            continue

        if https_port in (443, 8443):
            lines += [
                f"{domain}:{https_port} {{",
                f"    tls internal",
                f"    reverse_proxy localhost:{port}",
                "}",
                "",
                f"http://{domain}:{http_port} {{",
                f"    reverse_proxy localhost:{port}",
                "}",
                "",
            ]
        else:
            lines += [
                f"{domain}:{http_port} {{",
                f"    reverse_proxy localhost:{port}",
                "}",
                "",
            ]

    caddyfile_path = get_caddy_dir() / "Caddyfile"
    caddyfile_path.write_text("\n".join(lines), encoding="utf-8")
    return str(caddyfile_path)


class CaddyManager:

    ADMIN_PORT = 2019

    def __init__(self, config: dict, log_fn=None):
        self.config = config
        self._log = log_fn or print
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def log(self, msg: str):
        self._log(msg)

    @property
    def http_port(self) -> int:
        return self.config.get("caddy_http_port", 8080)

    @property
    def https_port(self) -> int:
        return self.config.get("caddy_https_port", 8443)

    @property
    def landing_port(self) -> int:
        return self.config.get("landing_port", 8080)

    def is_available(self) -> bool:
        return is_caddy_available()

    def is_running(self) -> bool:
        # Check admin API first (most reliable)
        if is_caddy_admin_running(self.ADMIN_PORT):
            return True
        # Fall back to process check
        if is_caddy_process_running():
            return True
        # Last resort: port check
        return is_port_open(self.https_port) or is_port_open(self.http_port)

    def get_ca_cert_path(self) -> Optional[Path]:
        return get_caddy_ca_cert_path()

    def install_ca(self) -> tuple[bool, str]:
        return install_caddy_ca_system(log_fn=self._log)

    def export_ca(self, dest: str) -> tuple[bool, str]:
        return export_caddy_ca_cert(dest)

    def start(self, apps: list) -> tuple[bool, str]:
        if not is_caddy_available():
            return False, "Caddy binary not found."

        if self.is_running():
            self._log("[Caddy] Already running.")
            return True, "Caddy already running."

        caddyfile = generate_caddyfile(
            apps,
            http_port=self.http_port,
            https_port=self.https_port,
            landing_port=self.landing_port,
            admin_port=self.ADMIN_PORT,
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

        # Wait up to 20 seconds for admin API to respond
        for _ in range(40):
            time.sleep(0.5)
            if is_caddy_admin_running(self.ADMIN_PORT):
                self._log(f"[Caddy] Running — HTTP:{self.http_port} HTTPS:{self.https_port}")
                # Trust CA in background — non-blocking
                threading.Thread(
                    target=self._try_auto_trust,
                    daemon=True,
                    name="PGOps-Caddy-Trust",
                ).start()
                return True, (
                    f"Caddy started. "
                    f"HTTP port {self.http_port}, HTTPS port {self.https_port}."
                )

        return False, "Caddy did not start in time (admin API not responding)."

    def _try_auto_trust(self):
        """Try to silently install the CA. Runs in a background thread."""
        # Give Caddy a moment to generate its CA
        time.sleep(3)
        try:
            ok, msg = install_caddy_ca_system(log_fn=self._log)
            if ok:
                self._log("[Caddy] CA trusted automatically.")
            else:
                self._log(f"[Caddy] Auto-trust skipped: {msg}")
        except Exception as e:
            self._log(f"[Caddy] Auto-trust error (non-fatal): {e}")

    def reload(self) -> tuple[bool, str]:
        """Reload config via Caddy admin API (zero downtime)."""
        if not self.is_running():
            return False, "Caddy not running."

        caddyfile = str(get_caddy_dir() / "Caddyfile")
        if not Path(caddyfile).exists():
            return False, "Caddyfile not found."

        # Use admin API for hot reload
        try:
            import urllib.request
            import json

            # Convert Caddyfile to JSON config via caddy adapter
            env = _build_caddy_env()
            r = subprocess.run(
                [str(get_caddy_bin()), "adapt", "--config", caddyfile],
                capture_output=True,
                text=True,
                env=env,
                **_popen_kwargs(),
            )
            if r.returncode != 0:
                return False, f"Caddy adapt failed: {r.stderr}"

            json_config = r.stdout.strip()

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.ADMIN_PORT}/load",
                data=json_config.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    self._log("[Caddy] Config reloaded via admin API.")
                    return True, "Caddy reloaded."
                return False, f"Admin API returned {resp.status}"
        except Exception as e:
            self._log(f"[Caddy] Admin API reload failed, trying CLI: {e}")

        # Fallback: CLI reload
        env = _build_caddy_env()
        r = subprocess.run(
            [str(get_caddy_bin()), "reload", "--config", caddyfile],
            capture_output=True,
            text=True,
            env=env,
            **_popen_kwargs(),
        )
        if r.returncode == 0:
            self._log("[Caddy] Config reloaded via CLI.")
            return True, "Caddy reloaded."
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
                    capture_output=True,
                    **_popen_kwargs(),
                )
            else:
                subprocess.run(["pkill", "-f", "caddy run"], capture_output=True)

        self._log("[Caddy] Stopped.")
        return True, "Caddy stopped."

    def update_apps(self, apps: list) -> tuple[bool, str]:
        generate_caddyfile(
            apps,
            http_port=self.http_port,
            https_port=self.https_port,
            landing_port=self.landing_port,
            admin_port=self.ADMIN_PORT,
        )
        if self.is_running():
            return self.reload()
        return True, "Caddyfile updated (Caddy not running)."

    def get_status_detail(self) -> dict:
        ca_path = get_caddy_ca_cert_path()
        return {
            "running":      self.is_running(),
            "available":    is_caddy_available(),
            "http_port":    self.http_port,
            "https_port":   self.https_port,
            "ca_available": ca_path is not None,
            "ca_path":      str(ca_path) if ca_path else "",
        }

    def console_url(self) -> str:
        try:
            from core.pg_manager import PostgresManager
        except Exception:
            pass
        return f"http://127.0.0.1:{self.http_port}"
