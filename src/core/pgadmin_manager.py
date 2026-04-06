"""
pgadmin_manager.py
Launches pgAdmin 4 that ships inside the EDB PostgreSQL zip.
Runs it in server mode so it is accessible at http://pgops.local:5050
from any browser on the LAN.

EDB zip extracts to:
  pgsql/
    pgAdmin 4/
      runtime/
        pgAdmin4.exe          <- desktop mode (not what we want)
      venv/
        Scripts/python.exe    <- Windows
        bin/python            <- macOS/Linux
      web/
        pgAdmin4.py           <- server entry point
      conf/
        config_distro.py
"""

import os
import sys
import subprocess
import platform
import socket
import time
import json
from pathlib import Path


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp

        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_pgadmin_dir() -> Path:
    """pgAdmin 4 directory inside the extracted PostgreSQL bundle."""
    from core.pg_manager import PG_DIR

    return PG_DIR / "pgAdmin 4"


def get_pgadmin_python() -> Path:
    """
    Locate the Python interpreter bundled with pgAdmin.
    Handles both 'venv' layout and 'python' layout used by some EDB bundles.
    """

    base = get_pgadmin_dir()

    if platform.system() == "Windows":
        candidates = [
            base / "venv" / "Scripts" / "python.exe",
            base / "python" / "python.exe",
        ]
    else:
        candidates = [
            base / "venv" / "bin" / "python",
            base / "python" / "bin" / "python",
        ]

    for path in candidates:
        if path.exists():
            return path

    # return first candidate for error reporting
    return candidates[0]


def get_pgadmin_web() -> Path:
    """pgAdmin4.py server entry point."""
    return get_pgadmin_dir() / "web" / "pgAdmin4.py"


def get_pgadmin_runtime() -> Path:
    """pgAdmin4.exe (desktop mode) — used as fallback."""
    if platform.system() == "Windows":
        return get_pgadmin_dir() / "runtime" / "pgAdmin4.exe"
    return get_pgadmin_dir() / "pgAdmin4.app" / "Contents" / "MacOS" / "pgAdmin4"


def is_available() -> bool:
    """Check if pgAdmin 4 is present in the PostgreSQL bundle."""
    d = get_pgadmin_dir()
    return d.exists() and (
        get_pgadmin_python().exists() or get_pgadmin_runtime().exists()
    )


def get_data_dir() -> Path:
    """Where pgAdmin stores its config, sessions, and SQLite db."""
    from core.pg_manager import get_app_data_dir

    d = get_app_data_dir() / "pgadmin4-data"
    d.mkdir(parents=True, exist_ok=True)
    return d


PGADMIN_PORT = 5050
DEFAULT_EMAIL = "admin@pgops.local"
DEFAULT_PASSWORD = "pgopsadmin"


class PgAdminManager:

    def __init__(self, pg_config: dict, log_fn=None):
        """
        pg_config : the main PGOps config dict (username, password, port)
        log_fn    : log callback
        """
        self.pg_config = pg_config
        self._log = log_fn or print
        self._proc = None
        self.port = PGADMIN_PORT

    def log(self, msg: str):
        self._log(msg)

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return is_available()

    def is_running(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", self.port))
            s.close()
            return result == 0
        except Exception:
            return False

    # ── Config ────────────────────────────────────────────────────────────────

    def _write_config(self):
        """
        Write pgAdmin config_local.py so it runs in server mode
        on our chosen port with the correct data directory.
        """
        data_dir = get_data_dir()
        (data_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (data_dir / "storage").mkdir(parents=True, exist_ok=True)
        config_dir = get_pgadmin_dir() / "web"
        config_file = config_dir / "config_local.py"

        # Escape paths for Python string literals
        data_str = str(data_dir).replace("\\", "\\\\")

        config_content = f"""
# PGOps-generated pgAdmin configuration
# Do not edit — regenerated on each start

import os

# Run as a web server, not desktop app
SERVER_MODE = True

# Data storage
DATA_DIR = r"{data_dir}"
LOG_FILE = os.path.join(DATA_DIR, "pgadmin4.log")
SQLITE_PATH = os.path.join(DATA_DIR, "pgadmin4.db")
SESSION_DB_PATH = os.path.join(DATA_DIR, "sessions")
STORAGE_DIR = os.path.join(DATA_DIR, "storage")

# Network
DEFAULT_SERVER = "0.0.0.0"
DEFAULT_SERVER_PORT = {self.port}

# Security
SECRET_KEY = "pgops-pgadmin-secret-key-change-in-production"
SECURITY_PASSWORD_SALT = "pgops-salt"
WTF_CSRF_ENABLED = True

# First-run setup (skip email confirmation)
MASTER_PASSWORD_REQUIRED = False

# Mail (disabled)
MAIL_SERVER = ""

# Logging
CONSOLE_LOG_LEVEL = 40  # ERROR only
FILE_LOG_LEVEL = 40
"""
        config_file.write_text(config_content)
        self.log(f"pgAdmin config written to {config_file}")

    def _ensure_default_user(self):
        """
        Create the default admin user in pgAdmin's SQLite database
        so the user does not have to register on first visit.
        Uses pgAdmin's setup.py if available.
        """
        setup_py = get_pgadmin_dir() / "web" / "setup.py"
        python = get_pgadmin_python()

        if not setup_py.exists() or not python.exists():
            return

        data_db = get_data_dir() / "pgadmin4.db"
        if data_db.exists():
            return  # already initialised

        self.log("Initialising pgAdmin database...")
        env = {
            **os.environ,
            "PGADMIN_SETUP_EMAIL": DEFAULT_EMAIL,
            "PGADMIN_SETUP_PASSWORD": DEFAULT_PASSWORD,
        }
        try:
            subprocess.run(
                [str(python), str(setup_py)],
                env=env,
                capture_output=True,
                cwd=str(get_pgadmin_dir() / "web"),
                **_popen_kwargs(),
                timeout=30,
            )
            self.log(f"pgAdmin default user: {DEFAULT_EMAIL} / {DEFAULT_PASSWORD}")
        except Exception as e:
            self.log(f"pgAdmin setup warning: {e}")

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            return True, f"pgAdmin already running at http://pgops.local:{self.port}"

        if not self.is_available():
            return False, (
                "pgAdmin 4 not found in the PostgreSQL bundle.\n"
                "It is included in the EDB PostgreSQL zip — ensure PostgreSQL\n"
                "binaries have been set up first."
            )

        python = get_pgadmin_python()
        web_py = get_pgadmin_web()

        if not python.exists():
            return False, f"pgAdmin Python not found at {python}"
        if not web_py.exists():
            return False, f"pgAdmin4.py not found at {web_py}"

        self._write_config()
        self._ensure_default_user()

        self.log(f"Starting pgAdmin 4 on port {self.port}...")

        env = {
            **os.environ,
            "PGADMIN_CONFIG_SERVER_MODE": "True",
            "PGADMIN_CONFIG_DEFAULT_SERVER_PORT": str(self.port),
        }

        try:
            kwargs = _popen_kwargs()
            kwargs["env"] = env
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            kwargs["cwd"] = str(get_pgadmin_dir() / "web")

            self._proc = subprocess.Popen([str(python), str(web_py)], **kwargs)
            if self._proc.poll() is not None:
                 out, err = self._proc.communicate()
                 self.log(out.decode())
                 self.log(err.decode())

        except Exception as e:
            return False, f"Failed to start pgAdmin: {e}"

        # Wait up to 15s for it to come up (pgAdmin is slow to start)
        for _ in range(60):
            time.sleep(0.5)
            if self.is_running():
                url = f"http://pgops.local:{self.port}"
                self.log(f"pgAdmin 4 ready at {url}")
                return True, url

        return (
            False,
            "pgAdmin did not start in time. Check PostgreSQL bundle integrity.",
        )

    def stop(self) -> tuple[bool, str]:
        if not self.is_running():
            return True, "pgAdmin not running."

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

        if platform.system() == "Windows" and self.is_running():
            subprocess.run(
                ["taskkill", "/F", "/IM", "python.exe", "/T"],
                capture_output=True,
                **_popen_kwargs(),
            )

        self.log("pgAdmin stopped.")
        return True, "pgAdmin stopped."

    # ── Connection info ───────────────────────────────────────────────────────

    def url(self) -> str:
        return f"http://pgops.local:{self.port}"

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def default_credentials(self) -> dict:
        return {
            "email": DEFAULT_EMAIL,
            "password": DEFAULT_PASSWORD,
        }
