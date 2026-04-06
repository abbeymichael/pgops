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
    Reset pgAdmin credentials using a self-contained script.
    Tries Flask-Security first, then falls back to bcrypt directly.
    The script is written to a temp file and run as a subprocess so that
    pgAdmin's own Python environment is used — not the PGOps Python.
    """
    db_path  = get_data_dir() / "pgadmin4.db"
    web_dir  = get_pgadmin_dir() / "web"

    if not db_path.exists():
        log_fn("[pgAdmin] DB not found yet — skipping credential reset.")
        return False

    # Build the reset script. Use raw string paths to avoid backslash issues.
    web_dir_str = str(web_dir).replace("\\", "\\\\")
    db_path_str = str(db_path).replace("\\", "\\\\")

    script = f"""
import sys, os, sqlite3

web_dir  = r"{web_dir}"
db_path  = r"{db_path}"
new_email    = "{DEFAULT_EMAIL}"
new_password = "{DEFAULT_PASSWORD}"

# ── Method 1: Flask-Security via pgAdmin's full stack ────────────────────────
try:
    sys.path.insert(0, web_dir)
    os.chdir(web_dir)

    import config
    from pgadmin import create_app
    app = create_app()
    with app.app_context():
        from flask_security.utils import hash_password
        from pgadmin.model import db, User
        user = User.query.order_by(User.id).first()
        if user:
            user.email    = new_email
            user.password = hash_password(new_password)
            user.active   = True
            db.session.commit()
            print("OK_FLASK:" + new_email)
            sys.exit(0)
        else:
            print("NO_USER")
            sys.exit(1)
except Exception as e1:
    print("FLASK_FAIL:" + str(e1)[:200])

# ── Method 2: bcrypt directly into SQLite ────────────────────────────────────
try:
    import bcrypt
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(12)).decode()

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
    if not cur.fetchone():
        print("NO_USER_TABLE")
        conn.close()
        sys.exit(1)

    cur.execute("SELECT id, email FROM user ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("NO_USERS")
        conn.close()
        sys.exit(1)

    cur.execute(
        "UPDATE user SET email=?, password=?, active=1 WHERE id=?",
        (new_email, hashed, row[0])
    )
    conn.commit()
    conn.close()
    print("OK_BCRYPT:" + new_email)
    sys.exit(0)
except Exception as e2:
    print("BCRYPT_FAIL:" + str(e2)[:200])
    sys.exit(1)
"""

    script_file = get_data_dir() / "_pgadmin_reset.py"
    try:
        script_file.write_text(script, encoding="utf-8")
    except Exception as e:
        log_fn(f"[pgAdmin] Could not write reset script: {e}")
        return False

    try:
        r = subprocess.run(
            [str(python), str(script_file)],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(web_dir),       # run from pgAdmin's web dir
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        log_fn(f"[pgAdmin] Reset output: {out[:400]}")

        if "OK_" in r.stdout:
            log_fn(f"[pgAdmin] Credentials set → {DEFAULT_EMAIL} / {DEFAULT_PASSWORD}")
            return True

        log_fn(f"[pgAdmin] Reset failed (rc={r.returncode}). Manual login may be required.")
        return False

    except subprocess.TimeoutExpired:
        log_fn("[pgAdmin] Credential reset timed out.")
        return False
    except Exception as e:
        log_fn(f"[pgAdmin] Credential reset exception: {e}")
        return False
    finally:
        try:
            script_file.unlink(missing_ok=True)
        except Exception:
            pass


def _nuke_pgadmin_db(log_fn) -> bool:
    """
    Delete the pgAdmin SQLite database so it gets recreated fresh on next start.
    This forces pgAdmin to re-run its setup with the env vars we pass.
    """
    db_path = get_data_dir() / "pgadmin4.db"
    sessions_dir = get_data_dir() / "sessions"
    try:
        if db_path.exists():
            db_path.unlink()
            log_fn("[pgAdmin] Removed stale pgadmin4.db — will be recreated fresh.")
        if sessions_dir.exists():
            import shutil
            shutil.rmtree(sessions_dir, ignore_errors=True)
        return True
    except Exception as e:
        log_fn(f"[pgAdmin] Could not remove DB: {e}")
        return False


class PgAdminManager:

    def __init__(self, pg_config: dict, log_fn=None):
        self.pg_config = pg_config
        self._log = log_fn or print
        self._proc = None
        self.port  = PGADMIN_PORT
        self._creds_reset = False

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

    def start(self, fresh: bool = False) -> tuple[bool, str]:
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

        # If asked for a fresh start, nuke the DB so env-var credentials apply
        if fresh:
            _nuke_pgadmin_db(self.log)
            self._creds_reset = False

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

                # Give the DB another second to finish initialising before we touch it
                time.sleep(1.5)

                if not self._creds_reset:
                    self.log("[pgAdmin] Setting credentials…")
                    ok = _reset_credentials(python, self.log)
                    if ok:
                        self._creds_reset = True
                    else:
                        # Last resort: nuke DB and ask user to restart
                        self.log(
                            "[pgAdmin] Credential reset failed. "
                            "Use 'Reset & Restart pgAdmin' to force fresh credentials."
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

    def reset_and_restart(self) -> tuple[bool, str]:
        """
        Stop pgAdmin, nuke its database, and restart fresh.
        After this the env-var credentials (DEFAULT_EMAIL / DEFAULT_PASSWORD) apply
        without needing the credential-reset script to succeed.
        """
        self.stop()
        time.sleep(1)
        return self.start(fresh=True)

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