"""
caddy_manager.py
Manages the Caddy reverse proxy for PGOps web app hosting.

SSL Strategy:
  - Caddy's built-in `tls internal` uses its own local CA
  - On first run, Caddy generates a root CA in its data dir
  - We export that CA cert so the SSL tab can help users trust it
  - All *.pgops.test subdomains get valid HTTPS certs automatically

Caddyfile uses `tls internal` so every site gets a signed cert from
Caddy's local CA — no self-signed warnings once the CA is trusted.
"""

import os
import sys
import subprocess
import platform
import socket
import time
import shutil
from pathlib import Path
from typing import Optional

import psutil


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
    for p in psutil.process_iter(['name']):
        name = p.info.get("name", "")
        if name and "caddy" in name.lower():
            return True
    return False


def is_port_open(port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except Exception:
        return False


def setup_caddy_binary(progress_callback=None) -> tuple[bool, str]:
    """Extract from assets/ or download Caddy binary."""
    dest = get_caddy_bin()
    if dest.exists():
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

    return False, "Bundled Caddy binary not found. Place caddy binary in assets/ folder."


def get_caddy_ca_cert_path() -> Optional[Path]:
    """
    Find Caddy's internal CA root certificate.
    Caddy stores it at: <data_dir>/caddy/pki/authorities/local/root.crt
    """
    caddy_data = get_caddy_data_dir()
    ca_path = caddy_data / "pki" / "authorities" / "local" / "root.crt"
    if ca_path.exists():
        return ca_path
    return None


def export_caddy_ca_cert(dest_path: str) -> tuple[bool, str]:
    """Export Caddy's internal CA cert so users can trust it."""
    ca = get_caddy_ca_cert_path()
    if not ca:
        return False, (
            "Caddy CA not found. Start Caddy at least once to generate the CA, "
            "then export it."
        )
    shutil.copy2(ca, dest_path)
    return True, f"Caddy CA certificate exported to {dest_path}"


def install_caddy_ca_system(log_fn=None) -> tuple[bool, str]:
    """
    Attempt to install Caddy's CA into the system trust store.
    Uses `caddy trust` command which handles platform differences.
    """
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
            return True, "Caddy CA installed into system trust store. Browsers will trust *.pgops.test."
        return False, f"caddy trust failed: {out}"
    except Exception as e:
        return False, f"caddy trust error: {e}"


def _build_caddy_env() -> dict:
    """Build environment with Caddy's data dir configured."""
    env = {**os.environ}
    caddy_data = str(get_caddy_data_dir())
    env["XDG_DATA_HOME"] = caddy_data          # Linux
    env["CADDY_DATA_DIR"] = caddy_data          # explicit override
    env["HOME"] = caddy_data                    # macOS fallback
    if platform.system() == "Windows":
        env["APPDATA"] = caddy_data
        env["LOCALAPPDATA"] = caddy_data
    return env


def generate_caddyfile(
    apps: list,
    http_port: int = 80,
    https_port: int = 443,
    landing_port: int = 8080,
) -> str:
    """
    Generate a Caddyfile that:
    - Redirects HTTP → HTTPS for all domains
    - Uses `tls internal` for automatic cert generation via Caddy's built-in CA
    - Routes pgops.test → landing server
    - Routes *.pgops.test → respective app servers
    """
    caddy_dir = get_caddy_dir()
    caddy_data = str(get_caddy_data_dir())

    lines = [
        "{",
        f"    admin 127.0.0.1:2019",
        f"    http_port {http_port}",
        f"    https_port {https_port}",
        # Tell Caddy where to store its data (certs, CA, etc.)
        f"    storage file_system {{",
        f"        root {caddy_data}",
        f"    }}",
        # Use Caddy's internal CA — generates trusted certs for all domains
        f"    pki {{",
        f"        ca local {{",
        f"            name \"PGOps Local CA\"",
        f"        }}",
        f"    }}",
        "}",
        "",
        # Landing page — pgops.test root
        "pgops.test {",
        f"    tls internal",
        f"    reverse_proxy localhost:{landing_port}",
        "}",
        "",
        # HTTP → HTTPS redirect for pgops.test
        f"http://pgops.test {{",
        f"    redir https://{{host}}{{uri}} permanent",
        "}",
        "",
    ]

    # Add each running app
    for app in apps:
        if app.get("status") in ("running", "starting"):
            domain = app.get("domain")
            port = app.get("internal_port", 8081)
            if domain:
                lines += [
                    f"{domain} {{",
                    f"    tls internal",
                    f"    reverse_proxy localhost:{port}",
                    "}",
                    "",
                    f"http://{domain} {{",
                    f"    redir https://{{host}}{{uri}} permanent",
                    "}",
                    "",
                ]

    caddyfile_path = caddy_dir / "Caddyfile"
    caddyfile_path.write_text("\n".join(lines), encoding="utf-8")
    return str(caddyfile_path)


class CaddyManager:

    def __init__(self, config: dict, log_fn=None):
        self.config = config
        self._log = log_fn or print
        self._proc: Optional[subprocess.Popen] = None

    def log(self, msg: str):
        self._log(msg)

    @property
    def http_port(self) -> int:
        return self.config.get("caddy_http_port", 80)

    @property
    def https_port(self) -> int:
        return self.config.get("caddy_https_port", 443)

    @property
    def landing_port(self) -> int:
        return self.config.get("landing_port", 8080)

    def is_available(self) -> bool:
        return is_caddy_available()

    def is_running(self) -> bool:
        if is_caddy_process_running():
            return True
        if is_port_open(self.https_port) or is_port_open(self.http_port):
            return True
        return False

    def get_ca_cert_path(self) -> Optional[Path]:
        return get_caddy_ca_cert_path()

    def install_ca(self) -> tuple[bool, str]:
        """Install Caddy's CA into the system trust store."""
        return install_caddy_ca_system(log_fn=self._log)

    def export_ca(self, dest: str) -> tuple[bool, str]:
        """Export Caddy CA cert for manual installation."""
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
        )
        self._log(f"[Caddy] Caddyfile written → {caddyfile}")

        env = _build_caddy_env()
        cmd = [str(get_caddy_bin()), "run", "--config", caddyfile]

        try:
            kwargs = _popen_kwargs()
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
            kwargs["env"] = env
            self._proc = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start Caddy: {exc}"

        # Wait up to 15 seconds for Caddy to come up
        for _ in range(30):
            time.sleep(0.5)
            if self.is_running():
                self._log(f"[Caddy] Running on ports {self.http_port}/{self.https_port}.")
                # Attempt auto-trust of the CA
                self._try_auto_trust()
                return True, f"Caddy started. HTTPS on port {self.https_port}, HTTP on {self.http_port}."

        return False, "Caddy did not start in time."

    def _try_auto_trust(self):
        """Try to silently install the CA. Failure is non-fatal."""
        try:
            ok, msg = install_caddy_ca_system(log_fn=self._log)
            if ok:
                self._log("[Caddy] CA trusted automatically.")
            else:
                self._log(f"[Caddy] Auto-trust skipped (manual trust needed): {msg}")
        except Exception as e:
            self._log(f"[Caddy] Auto-trust error (non-fatal): {e}")

    def reload(self) -> tuple[bool, str]:
        if not self.is_running():
            return False, "Caddy not running."

        caddyfile = str(get_caddy_dir() / "Caddyfile")
        env = _build_caddy_env()
        r = subprocess.run(
            [str(get_caddy_bin()), "reload", "--config", caddyfile],
            capture_output=True,
            text=True,
            env=env,
            **_popen_kwargs(),
        )
        if r.returncode == 0:
            self._log("[Caddy] Config reloaded.")
            return True, "Caddy reloaded."
        return False, (r.stdout + r.stderr).strip()

    def stop(self) -> tuple[bool, str]:
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

    def update_apps(self, apps: list) -> tuple[bool, str]:
        generate_caddyfile(
            apps,
            http_port=self.http_port,
            https_port=self.https_port,
            landing_port=self.landing_port,
        )
        if self.is_running():
            return self.reload()
        return True, "Caddyfile updated."

    def get_status_detail(self) -> dict:
        """Return detailed status for the SSL/DNS tab."""
        ca_path = get_caddy_ca_cert_path()
        return {
            "running": self.is_running(),
            "available": is_caddy_available(),
            "http_port": self.http_port,
            "https_port": self.https_port,
            "ca_available": ca_path is not None,
            "ca_path": str(ca_path) if ca_path else "",
        }
