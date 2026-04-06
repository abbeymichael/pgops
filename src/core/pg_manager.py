import os
import sys
import subprocess
import platform
import zipfile
import shutil
import socket
import requests
from pathlib import Path

import platform as _platform

def _popen_kwargs() -> dict:
    """
    On Windows, prevent subprocess calls from flashing a cmd window.
    On other platforms this is a no-op.
    """
    if _platform.system() == "Windows":
        import subprocess as _sp
        return {"creationflags": _sp.CREATE_NO_WINDOW}
    return {}


PG_VERSION = "16.2"

PG_DOWNLOAD = {
    "Windows": f"https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-1-windows-x64-binaries.zip",
    "Darwin":  f"https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-1-osx-binaries.zip",
}

# Bundled asset filenames (placed in assets/ before building)
PG_BUNDLED = {
    "Windows": "pg_windows.zip",
    "Darwin":  "pg_mac.zip",
}


def get_app_data_dir() -> Path:
    """
    User-writable directory for PG binaries, data, logs.
    Always writable — never inside Program Files.
      Windows : %LOCALAPPDATA%/PGOps
      macOS   : ~/Library/Application Support/PGOps
      dev     : project_root/appdata
    """
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    d = base / "PGOps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_assets_dir() -> Path:
    """
    Read-only assets bundled with the app (pg zip lives here at build time).
    When frozen: sys._MEIPASS/assets
    When dev:    project_root/assets
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


# All mutable data goes to user-writable AppData, never Program Files
BASE_DIR   = get_app_data_dir()
PG_DIR     = BASE_DIR / "pgsql"
DATA_DIR   = BASE_DIR / "pgdata"
LOG_FILE   = BASE_DIR / "postgres.log"


def _bin(name: str) -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return PG_DIR / "bin" / f"{name}{ext}"


class PostgresManager:
    def __init__(self, config: dict, log_callback=None):
        self.config = config
        self._log = log_callback or print

    def log(self, msg: str):
        self._log(msg)

    # ── Binary management ─────────────────────────────────────────────────────

    def is_binaries_available(self) -> bool:
        return _bin("pg_ctl").exists() and _bin("initdb").exists()

    def setup_binaries(self, progress_callback=None):
        """
        Extract bundled zip if available, otherwise fall back to downloading.
        This is the single entry point called by the UI.
        """
        system = platform.system()
        bundled_name = PG_BUNDLED.get(system)
        bundled_path = get_assets_dir() / bundled_name if bundled_name else None

        if bundled_path and bundled_path.exists():
            self.log(f"Bundled PostgreSQL found — extracting...")
            self._extract(bundled_path, progress_callback)
        else:
            self.log("No bundled binaries found — downloading from internet...")
            self.download_binaries(progress_callback)

    def _extract(self, zip_path: Path, progress_callback=None):
        if progress_callback:
            progress_callback(10)

        if PG_DIR.exists():
            shutil.rmtree(PG_DIR)

        self.log(f"Extracting {zip_path.name}...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total = len(members)
            for i, member in enumerate(members):
                zf.extract(member, BASE_DIR)
                if progress_callback:
                    progress_callback(10 + int(i / total * 88))

        if platform.system() == "Darwin":
            for f in (PG_DIR / "bin").iterdir():
                f.chmod(0o755)

        if progress_callback:
            progress_callback(100)
        self.log("PostgreSQL ready.")

    def download_binaries(self, progress_callback=None):
        system = platform.system()
        if system not in PG_DOWNLOAD:
            raise RuntimeError(f"Unsupported OS: {system}")

        url = PG_DOWNLOAD[system]
        archive_path = BASE_DIR / f"pg_{system}.zip"

        self.log(f"Downloading PostgreSQL {PG_VERSION} for {system}...")

        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(archive_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(int(downloaded / total * 80))

        self._extract(archive_path, progress_callback)
        archive_path.unlink(missing_ok=True)

    # ── Cluster management ────────────────────────────────────────────────────

    def is_initialized(self) -> bool:
        return (DATA_DIR / "PG_VERSION").exists()

    def is_running(self) -> bool:
        """
        Check if PostgreSQL is running by reading postmaster.pid directly.
        No subprocess is spawned — avoids the flashing cmd window on Windows.
        """
        pid_file = DATA_DIR / "postmaster.pid"
        if not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().split()[0])
            if platform.system() == "Windows":
                # Use OpenProcess to check if the PID exists — no cmd window
                import ctypes
                SYNCHRONIZE = 0x00100000
                handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            return False

    def initialize_cluster(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.log("Initializing database cluster...")

        pw_file = BASE_DIR / ".pwfile"
        pw_file.write_text(self.config["password"])

        try:
            r = subprocess.run([
                str(_bin("initdb")),
                "-D", str(DATA_DIR),
                "-U", self.config["username"],
                "--pwfile", str(pw_file),
                "--encoding", "UTF8",
                "--auth", "md5",
            ], capture_output=True, **_popen_kwargs(), text=True)

            if r.returncode != 0:
                raise RuntimeError(f"initdb failed:\n{r.stderr}")

            self._write_pg_hba()
            self._write_postgresql_conf()
            self.log("Cluster initialized.")
        finally:
            pw_file.unlink(missing_ok=True)

    def _write_pg_hba(self):
        (DATA_DIR / "pg_hba.conf").write_text(
            "# TYPE  DATABASE  USER  ADDRESS       METHOD\n"
            "local   all       all                 md5\n"
            "host    all       all   127.0.0.1/32  md5\n"
            "host    all       all   0.0.0.0/0     md5\n"
            "host    all       all   ::1/128       md5\n"
        )
        self.log("pg_hba.conf configured for LAN access.")

    def _write_postgresql_conf(self):
        import re
        conf = DATA_DIR / "postgresql.conf"
        text = conf.read_text()

        def replace_or_append(text, key, value):
            pattern = re.compile(rf"^#?\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
            line = f"{key} = {value}"
            if pattern.search(text):
                return pattern.sub(line, text)
            return text + f"\n{line}\n"

        text = replace_or_append(text, "listen_addresses", "'*'")
        text = replace_or_append(text, "port", str(self.config["port"]))
        conf.write_text(text)
        self.log(f"postgresql.conf configured — port {self.config['port']}, listen *")

    def start(self) -> bool:
        if self.is_running():
            self.log("Already running.")
            return True
        if not self.is_initialized():
            self.initialize_cluster()

        self.log("Starting PostgreSQL...")
        r = subprocess.run([
            str(_bin("pg_ctl")), "start",
            "-D", str(DATA_DIR),
            "-l", str(LOG_FILE),
            "-w", "-t", "30",
        ], capture_output=True, **_popen_kwargs(), text=True)

        if r.returncode != 0:
            self.log(f"Start failed:\n{r.stderr}\n{r.stdout}")
            return False

        self.log("PostgreSQL is running.")
        self._ensure_database()
        return True

    def stop(self) -> bool:
        if not self.is_running():
            self.log("Not running.")
            return True

        self.log("Stopping PostgreSQL...")
        r = subprocess.run([
            str(_bin("pg_ctl")), "stop",
            "-D", str(DATA_DIR),
            "-m", "fast", "-w",
        ], capture_output=True, **_popen_kwargs(), text=True)

        if r.returncode != 0:
            self.log(f"Stop failed:\n{r.stderr}")
            return False

        self.log("Stopped.")
        return True

    def _ensure_database(self):
        dbname = self.config["database"]
        env = {**os.environ, "PGPASSWORD": self.config["password"]}

        check = subprocess.run([
            str(_bin("psql")),
            "-U", self.config["username"],
            "-p", str(self.config["port"]),
            "-h", "127.0.0.1",
            "-lqt",
        ], capture_output=True, **_popen_kwargs(), text=True, env=env)

        if dbname in check.stdout:
            self.log(f"Database '{dbname}' exists.")
            return

        r = subprocess.run([
            str(_bin("createdb")),
            "-U", self.config["username"],
            "-p", str(self.config["port"]),
            "-h", "127.0.0.1",
            dbname,
        ], capture_output=True, **_popen_kwargs(), text=True, env=env)

        if r.returncode == 0:
            self.log(f"Database '{dbname}' created.")
        else:
            self.log(f"Warning: could not create database: {r.stderr.strip()}")

    # ── Network helpers ───────────────────────────────────────────────────────

    def get_lan_ip(self) -> str:
        """
        Returns the preferred IP — hotspot IP if active, else pinned IP,
        else best available LAN/WiFi IP.
        """
        try:
            from core.network_info import get_all_interfaces, get_best_ip
            ifaces = get_all_interfaces()
            preferred = self.config.get("preferred_ip", "")
            return get_best_ip(ifaces, preferred)
        except Exception:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return "127.0.0.1"

    def get_all_ips(self) -> list:
        """Return all available network interfaces."""
        try:
            from core.network_info import get_all_interfaces
            return get_all_interfaces()
        except Exception:
            return [{"name": "Network", "ip": self.get_lan_ip(), "type": "other"}]

    def connection_string(self, host: str = None) -> str:
        c = self.config
        h = host or self.get_lan_ip()
        return f"postgresql://{c['username']}:{c['password']}@{h}:{c['port']}/{c['database']}"

    def connection_details(self, host: str = None) -> dict:
        h = host or self.get_lan_ip()
        return {
            "host":     h,
            "port":     self.config["port"],
            "username": self.config["username"],
            "password": self.config["password"],
            "database": self.config["database"],
        }
