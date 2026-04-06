
import os
import subprocess
import platform
import socket
import time
from pathlib import Path


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_pgadmin_dir() -> Path:
    from core.pg_manager import PG_DIR
    return PG_DIR / "pgAdmin 4"


def get_pgadmin_python() -> Path:
    base = get_pgadmin_dir()
    if platform.system() == "Windows":
        candidates = [
            base / "python" / "python.exe",
            base / "venv" / "Scripts" / "python.exe",
            base / "runtime" / "python.exe",
            base / "python3.exe",
            base / "python.exe",
        ]
    else:
        candidates = [
            base / "venv" / "bin" / "python3",
            base / "venv" / "bin" / "python",
            base / "python" / "bin" / "python3",
            base / "python" / "bin" / "python",
        ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def find_pgadmin_python() -> Path | None:
    base = get_pgadmin_dir()
    if not base.exists():
        return None
    exe_name = "python.exe" if platform.system() == "Windows" else "python3"
    alt_name  = "python3.exe" if platform.system() == "Windows" else "python"
    for root, dirs, files in os.walk(base):
        depth = len(Path(root).relative_to(base).parts)
        if depth > 5:
            dirs.clear()
            continue
        for f in files:
            if f.lower() in (exe_name.lower(), alt_name.lower()):
                return Path(root) / f
    return None


def get_pgadmin_web() -> Path:
    return get_pgadmin_dir() / "web" / "pgAdmin4.py"


def is_available() -> bool:
    d = get_pgadmin_dir()
    if not d.exists():
        return False
    return (
        get_pgadmin_python().exists()
        or find_pgadmin_python() is not None
    )


def get_data_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "pgadmin4-data"
    d.mkdir(parents=True, exist_ok=True)
    return d


PGADMIN_PORT     = 5050
DEFAULT_EMAIL    = "admin@pgops.local"
DEFAULT_PASSWORD = "pgopsadmin"


def _reset_credentials(python: Path, log_fn) -> bool:
    """
    After pgAdmin has started and created its SQLite DB, use pgAdmin's own
    Python + Flask-Security to set the password to our known value.
    This runs as a separate short-lived process and exits immediately.
    """
    db_path  = get_data_dir() / "pgadmin4.db"
    web_dir  = get_pgadmin_dir() / "web"

    script = f"""
import sys, os
sys.path.insert(0, r"{web_dir}")
os.chdir(r"{web_dir}")

import sqlite3

db_path = r"{db_path}"
conn = sqlite3.connect(db_path)
cur  = conn.cursor()

# Find out what tables exist
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]

if "user" not in tables:
    print("NO_USER_TABLE")
    conn.close()
    sys.exit(1)

# Get the first admin user
cur.execute("SELECT id, email FROM user ORDER BY id LIMIT 1")
row = cur.fetchone()
if not row:
    print("NO_USERS")
    conn.close()
    sys.exit(1)

user_id    = row[0]
user_email = row[1]
new_pw     = "{DEFAULT_PASSWORD}"
new_email  = "{DEFAULT_EMAIL}"

# Hash the password using Flask-Security (same as pgAdmin uses)
try:
    from flask_security.utils import hash_password
    import config
    from pgadmin import create_app
    app = create_app()
    with app.app_context():
        from pgadmin.model import db, User
        user = db.session.get(User, user_id)
        user.email    = new_email
        user.password = hash_password(new_pw)
        user.active   = True
        db.session.commit()
    print("OK_FLASK:" + new_email)
except Exception as e1:
    # Fallback: bcrypt directly into the SQLite column
    try:
        import bcrypt
        hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(12)).decode()
        cur.execute(
            "UPDATE user SET email=?, password=?, active=1 WHERE id=?",
            (new_email, hashed, user_id)
        )
        conn.commit()
        print("OK_BCRYPT:" + new_email)
    except Exception as e2:
        print("FAIL:" + str(e1) + " | " + str(e2))
        sys.exit(1)

conn.close()
"""

    script_file = get_data_dir() / "_reset_creds.py"
    script_file.write_text(script)

    try:
        r = subprocess.run(
            [str(python), str(script_file)],
            capture_output=True, text=True,
            timeout=30,
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        log_fn(f"[pgAdmin] Credential reset: {out[:300]}")

        script_file.unlink(missing_ok=True)

        if "OK_" in r.stdout:
            return True
        log_fn(f"[pgAdmin] Credential reset returned rc={r.returncode}")
        return False
    except Exception as e:
        log_fn(f"[pgAdmin] Credential reset exception: {e}")
        try:
            script_file.unlink(missing_ok=True)
        except Exception:
            pass
        return False


class PgAdminManager:

    def __init__(self, pg_config: dict, log_fn=None):
        self.pg_config = pg_config
        self._log = log_fn or print
        self._proc = None
        self.port  = PGADMIN_PORT
        self._creds_reset = False   # only reset once per data dir lifetime

    def log(self, msg: str):
        self._log(msg)

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

    def _resolve_python(self) -> Path | None:
        p = get_pgadmin_python()
        if p.exists():
            self.log(f"[pgAdmin] Python → {p}")
            return p
        self.log("[pgAdmin] Scanning pgAdmin dir for Python…")
        p2 = find_pgadmin_python()
        if p2:
            self.log(f"[pgAdmin] Python (scan) → {p2}")
            return p2
        return None

    def _write_config(self):
        data_dir = get_data_dir()
        (data_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (data_dir / "storage").mkdir(parents=True, exist_ok=True)

        config_file = get_pgadmin_dir() / "web" / "config_local.py"
        config_file.write_text(f"""
# PGOps-generated pgAdmin configuration — do not edit manually
import os

SERVER_MODE = True

DATA_DIR        = r"{data_dir}"
LOG_FILE        = os.path.join(DATA_DIR, "pgadmin4.log")
SQLITE_PATH     = os.path.join(DATA_DIR, "pgadmin4.db")
SESSION_DB_PATH = os.path.join(DATA_DIR, "sessions")
STORAGE_DIR     = os.path.join(DATA_DIR, "storage")

DEFAULT_SERVER      = "0.0.0.0"
DEFAULT_SERVER_PORT = {self.port}

SECRET_KEY               = "pgops-pgadmin-secret-key"
SECURITY_PASSWORD_SALT   = "pgops-salt"
WTF_CSRF_ENABLED         = True
MASTER_PASSWORD_REQUIRED = False

MAIL_SERVER = ""

CONSOLE_LOG_LEVEL = 40
FILE_LOG_LEVEL    = 40
""")
        self.log(f"[pgAdmin] Config written → {config_file}")

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            return True, f"pgAdmin already running at {self.url()}"

        if not self.is_available():
            return False, "pgAdmin 4 not found in the PostgreSQL bundle."

        python = self._resolve_python()
        web_py = get_pgadmin_web()

        self.log(f"[pgAdmin] pgAdmin dir : {get_pgadmin_dir()}")
        self.log(f"[pgAdmin] Python      : {python}")
        self.log(f"[pgAdmin] pgAdmin4.py : {web_py} (exists={web_py.exists()})")

        if python is None or not python.exists():
            return False, (
                f"pgAdmin Python not found at {get_pgadmin_python()}.\n"
                "Try reinstalling via Setup PostgreSQL."
            )

        if not web_py.exists():
            return False, f"pgAdmin4.py not found at {web_py}"

        self._write_config()

        env = {
            **os.environ,
            "PGADMIN_SETUP_EMAIL":    DEFAULT_EMAIL,
            "PGADMIN_SETUP_PASSWORD": DEFAULT_PASSWORD,
        }

        self.log(f"[pgAdmin] Launching pgAdmin4.py on port {self.port}…")

        try:
            kwargs = _popen_kwargs()
            kwargs["env"]    = env
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            kwargs["cwd"]    = str(get_pgadmin_dir() / "web")

            self._proc = subprocess.Popen([str(python), str(web_py)], **kwargs)

            time.sleep(0.3)
            if self._proc.poll() is not None:
                out, err = self._proc.communicate()
                self.log(f"[pgAdmin] STDOUT: {out.decode(errors='replace')[:1000]}")
                self.log(f"[pgAdmin] STDERR: {err.decode(errors='replace')[:1000]}")
                return False, "pgAdmin exited immediately. Check Log tab."

        except Exception as e:
            return False, f"Failed to launch pgAdmin: {e}"

        # Wait up to 90s for pgAdmin to bind its port
        self.log("[pgAdmin] Waiting for pgAdmin to become ready (up to 90s)…")
        for i in range(180):
            time.sleep(0.5)

            if self._proc.poll() is not None:
                try:
                    out, err = self._proc.communicate(timeout=2)
                    self.log(f"[pgAdmin] STDOUT: {out.decode(errors='replace')[:1000]}")
                    self.log(f"[pgAdmin] STDERR: {err.decode(errors='replace')[:1000]}")
                except Exception:
                    pass
                return False, "pgAdmin exited unexpectedly. Check Log tab."

            if self.is_running():
                self.log(f"[pgAdmin] Ready at {self.url()}")

                # Reset credentials now that the DB definitely exists
                if not self._creds_reset:
                    self.log("[pgAdmin] Setting credentials…")
                    ok = _reset_credentials(python, self.log)
                    if ok:
                        self._creds_reset = True
                        self.log(
                            f"[pgAdmin] Login: {DEFAULT_EMAIL} / {DEFAULT_PASSWORD}"
                        )
                    else:
                        self.log(
                            "[pgAdmin] Could not set credentials automatically. "
                            f"Try logging in with whatever email pgAdmin chose, "
                            f"then change password to: {DEFAULT_PASSWORD}"
                        )

                return True, self.url()

            if (i + 1) % 30 == 0:
                self.log(f"[pgAdmin] Still waiting… ({(i+1)*0.5:.0f}s)")

        # Timed out
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                out, err = self._proc.communicate(timeout=5)
                self.log(f"[pgAdmin] STDOUT: {out.decode(errors='replace')[:2000]}")
                self.log(f"[pgAdmin] STDERR: {err.decode(errors='replace')[:2000]}")
        except Exception:
            pass

        return False, "pgAdmin did not start in 90s. Check Log tab."

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
                capture_output=True, **_popen_kwargs(),
            )
        self._creds_reset = False
        self.log("[pgAdmin] Stopped.")
        return True, "pgAdmin stopped."

    def url(self) -> str:
        return f"http://pgops.local:{self.port}"

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def default_credentials(self) -> dict:
        return {"email": DEFAULT_EMAIL, "password": DEFAULT_PASSWORD}