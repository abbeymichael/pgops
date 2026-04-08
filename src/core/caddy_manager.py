"""
caddy_manager.py
Manages the Caddy reverse proxy for PGOps web app hosting.
Generates a Caddyfile from the app registry and reloads Caddy on changes.
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
    """Detect running Caddy process."""
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

    return False, "Bundled Caddy binary not found."


# ─────────────────────────────────────────────────────────────
# Caddyfile generation
# ─────────────────────────────────────────────────────────────

def generate_caddyfile(
    apps: list,
    http_port: int = 80,
    landing_port: int = 8080,
) -> str:

    caddy_dir = get_caddy_dir()

    lines = [
        "{",
        "    admin 127.0.0.1:2019",
        f"    http_port {http_port}",
        "}",
        "",
        "pgops.test {",
        f"    reverse_proxy localhost:{landing_port}",
        "}",
        "",
    ]

    for app in apps:
        if app.get("status") in ("running", "starting"):
            domain = app.get("domain")
            port = app.get("internal_port", 8081)

            if domain:
                lines += [
                    f"{domain} {{",
                    f"    reverse_proxy localhost:{port}",
                    "}",
                    "",
                ]

    caddyfile_path = caddy_dir / "Caddyfile"
    caddyfile_path.write_text("\n".join(lines))

    return str(caddyfile_path)


# ─────────────────────────────────────────────────────────────
# Manager class
# ─────────────────────────────────────────────────────────────

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
    def landing_port(self) -> int:
        return self.config.get("landing_port", 8080)

    def is_available(self) -> bool:
        return is_caddy_available()

    def is_running(self) -> bool:
        """
        Reliable running detection.
        Checks process first, then port.
        """
        if is_caddy_process_running():
            return True

        if is_port_open(self.http_port):
            return True

        return False

    # ─────────────────────────────────────────────────────────

    def start(self, apps: list) -> tuple[bool, str]:

        if not is_caddy_available():
            return False, "Caddy binary not found."

        if self.is_running():
            self.log("[Caddy] Already running.")
            return True, "Caddy already running."

        caddyfile = generate_caddyfile(
            apps,
            http_port=self.http_port,
            landing_port=self.landing_port,
        )

        self.log(f"[Caddy] Caddyfile written → {caddyfile}")

        cmd = [str(get_caddy_bin()), "run", "--config", caddyfile]

        try:
            kwargs = _popen_kwargs()
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL

            self._proc = subprocess.Popen(cmd, **kwargs)

        except Exception as exc:
            return False, f"Failed to start Caddy: {exc}"

        # Wait up to 10 seconds
        for _ in range(25):
            time.sleep(0.4)

            if self.is_running():
                self.log(f"[Caddy] Running on port {self.http_port}.")
                return True, f"Caddy started on port {self.http_port}."

        return False, "Caddy did not start in time."

    # ─────────────────────────────────────────────────────────

    def reload(self) -> tuple[bool, str]:

        if not self.is_running():
            return False, "Caddy not running."

        caddyfile = str(get_caddy_dir() / "Caddyfile")

        r = subprocess.run(
            [str(get_caddy_bin()), "reload", "--config", caddyfile],
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )

        if r.returncode == 0:
            self.log("[Caddy] Config reloaded.")
            return True, "Caddy reloaded."

        return False, (r.stdout + r.stderr).strip()

    # ─────────────────────────────────────────────────────────

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

        # fallback kill
        if is_caddy_process_running():

            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "caddy.exe"],
                    capture_output=True,
                    **_popen_kwargs(),
                )
            else:
                subprocess.run(
                    ["pkill", "-f", "caddy run"],
                    capture_output=True
                )

        self.log("[Caddy] Stopped.")
        return True, "Caddy stopped."

    # ─────────────────────────────────────────────────────────

    def update_apps(self, apps: list) -> tuple[bool, str]:

        generate_caddyfile(
            apps,
            http_port=self.http_port,
            landing_port=self.landing_port,
        )

        if self.is_running():
            return self.reload()

        return True, "Caddyfile updated."