"""
app_manager.py
App registry (apps.json) — read/write helpers, provisioning, deletion, git pull.
All heavy operations accept a progress_callback(step: str, status: str).
"""

import json
import os
import sys
import shutil
import secrets
import string
import subprocess
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


# ── Directory helpers ─────────────────────────────────────────────────────────

def get_apps_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "apps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_apps_json_path() -> Path:
    from core.pg_manager import get_app_data_dir
    return get_app_data_dir() / "apps.json"


# ── Registry I/O ─────────────────────────────────────────────────────────────

def load_apps() -> list[dict]:
    """Load apps from apps.json. Returns [] if file doesn't exist."""
    path = get_apps_json_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("apps", [])
    except Exception:
        return []


def save_apps(apps: list[dict]):
    """Persist app list to apps.json."""
    path = get_apps_json_path()
    path.write_text(
        json.dumps({"apps": apps}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_app_by_id(app_id: str) -> Optional[dict]:
    for app in load_apps():
        if app.get("id") == app_id:
            return app
    return None


def upsert_app(app: dict):
    """Insert or replace an app entry by id."""
    apps = load_apps()
    for i, a in enumerate(apps):
        if a.get("id") == app["id"]:
            apps[i] = app
            save_apps(apps)
            return
    apps.append(app)
    save_apps(apps)


def remove_app_from_registry(app_id: str):
    apps = [a for a in load_apps() if a.get("id") != app_id]
    save_apps(apps)


def set_app_status(app_id: str, status: str):
    """Update just the status field of an app."""
    apps = load_apps()
    for app in apps:
        if app.get("id") == app_id:
            app["status"] = status
            break
    save_apps(apps)


# ── Port assignment ───────────────────────────────────────────────────────────

FIRST_APP_PORT = 8081


def get_next_port() -> int:
    apps = load_apps()
    if not apps:
        return FIRST_APP_PORT
    used = [a.get("internal_port", 0) for a in apps]
    return max(used) + 1


# ── Slug validation ───────────────────────────────────────────────────────────

def validate_slug(slug: str) -> tuple[bool, str]:
    """Validate a project slug (used as folder name and subdomain)."""
    import re
    if not slug:
        return False, "Slug is required."
    if len(slug) < 2:
        return False, "Slug must be at least 2 characters."
    if len(slug) > 50:
        return False, "Slug must be 50 characters or fewer."
    if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', slug):
        return False, (
            "Slug must use lowercase letters, digits, and hyphens only, "
            "and cannot start or end with a hyphen."
        )
    # Check for duplicate
    existing = {a["id"] for a in load_apps()}
    if slug in existing:
        return False, f"An app with the slug '{slug}' already exists."
    return True, ""


# ── Password generation ───────────────────────────────────────────────────────

def generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── .env helpers ──────────────────────────────────────────────────────────────

def write_laravel_env(app_folder: str, values: dict):
    """
    Write a Laravel .env file.
    Starts from .env.example if present, then overlays the provided values.
    Existing keys in .env.example are replaced; new keys are appended.
    """
    env_path = os.path.join(app_folder, ".env")
    example  = os.path.join(app_folder, ".env.example")

    # Parse existing example
    existing: dict[str, str] = {}
    if os.path.exists(example):
        with open(example, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    existing[stripped] = line  # preserve comments / blanks
                elif "=" in line:
                    k = line.partition("=")[0].strip()
                    existing[k] = line

    # Overlay provided values
    for key, value in values.items():
        existing[key] = f"{key}={value}\n"

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(existing.values())


# ── Artisan runner ────────────────────────────────────────────────────────────

def run_artisan(app_folder: str, args: list[str], timeout: int = 120) -> str:
    """
    Run a FrankenPHP artisan command in app_folder.
    Returns stdout+stderr. Raises RuntimeError on non-zero exit.
    """
    from core.frankenphp_manager import get_frankenphp_bin
    php_bin = str(get_frankenphp_bin())

    cmd = [php_bin, "php", "artisan"] + args
    env = {**os.environ, "APP_ENV": "production"}

    result = subprocess.run(
        cmd,
        cwd=app_folder,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"artisan {' '.join(args)} failed (rc={result.returncode}):\n{output}"
        )
    return output


# ── ZIP extraction helpers ────────────────────────────────────────────────────

def _extract_zip(zip_path: str, dest_folder: str):
    """
    Extract a zip. If the zip contains a single top-level directory,
    its contents are moved up one level (common Laravel zip pattern).
    """
    import zipfile
    os.makedirs(dest_folder, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_folder)

    contents = os.listdir(dest_folder)
    if len(contents) == 1:
        inner = os.path.join(dest_folder, contents[0])
        if os.path.isdir(inner):
            for item in os.listdir(inner):
                shutil.move(os.path.join(inner, item), dest_folder)
            os.rmdir(inner)


# ── Provision ─────────────────────────────────────────────────────────────────

Progress = Callable[[str, str], None]   # (step_label, status)


def provision_app(
    slug: str,
    display_name: str,
    source_type: str,           # "zip" or "git"
    source_path: str,           # abs path to zip, or git URL
    git_branch: str = "main",
    admin_config: dict = None,  # postgres admin credentials
    progress: Progress = None,
) -> dict:
    """
    Full provisioning pipeline for a new Laravel app.
    Returns the completed app dict on success.
    Raises RuntimeError on any step failure.
    """

    def _step(label: str, status: str = "running"):
        if progress:
            progress(label, status)

    cfg = admin_config or {}
    app_folder    = str(get_apps_dir() / slug)
    internal_port = get_next_port()
    domain        = f"{slug}.pgops.local"
    db_name       = f"{slug}_db"
    db_user       = f"{slug}_user"
    db_password   = generate_password()
    bucket_name   = f"{slug}-files"

    # ── 1. Source ─────────────────────────────────────────────────────────────
    label = "Extracting files" if source_type == "zip" else "Cloning repository"
    _step(label)
    try:
        if source_type == "zip":
            _extract_zip(source_path, app_folder)
        elif source_type == "git":
            import git as gitpython
            gitpython.Repo.clone_from(source_path, app_folder, branch=git_branch)
        else:
            raise RuntimeError(f"Unknown source_type: {source_type}")
    except Exception as exc:
        _step(label, "error")
        raise RuntimeError(f"{label} failed: {exc}")
    _step(label, "done")

    # ── 2. Database ───────────────────────────────────────────────────────────
    _step(f"Creating database '{db_name}'")
    try:
        import core.db_manager as dbm
        ok, msg = dbm.create_database(
            db_name, db_user, db_password,
            cfg.get("username", "postgres"),
            cfg.get("password", "postgres"),
            cfg.get("port", 5432),
        )
        if not ok:
            raise RuntimeError(msg)
    except Exception as exc:
        _step(f"Creating database '{db_name}'", "error")
        raise RuntimeError(f"Database creation failed: {exc}")
    _step(f"Creating database '{db_name}'", "done")

    # ── 3. MinIO bucket ───────────────────────────────────────────────────────
    _step(f"Creating bucket '{bucket_name}'")
    access_key = secret_key = ""
    try:
        from core.bucket_manager import create_bucket
        ok, msg, creds = create_bucket(bucket_name, slug)
        if not ok:
            raise RuntimeError(msg)
        access_key = creds.get("access_key", "")
        secret_key = creds.get("secret_key", "")
    except Exception as exc:
        _step(f"Creating bucket '{bucket_name}'", "error")
        raise RuntimeError(f"Bucket creation failed: {exc}")
    _step(f"Creating bucket '{bucket_name}'", "done")

    # ── 4. .env ───────────────────────────────────────────────────────────────
    _step("Writing .env file")
    try:
        write_laravel_env(app_folder, {
            "APP_NAME":                    display_name,
            "APP_ENV":                     "production",
            "APP_KEY":                     "",           # filled by key:generate
            "APP_DEBUG":                   "false",
            "APP_URL":                     f"http://{domain}",
            "DB_CONNECTION":               "pgsql",
            "DB_HOST":                     "pgops.local",
            "DB_PORT":                     "5432",
            "DB_DATABASE":                 db_name,
            "DB_USERNAME":                 db_user,
            "DB_PASSWORD":                 db_password,
            "DB_SSLMODE":                  "require",
            "FILESYSTEM_DISK":             "s3",
            "AWS_ACCESS_KEY_ID":           access_key,
            "AWS_SECRET_ACCESS_KEY":       secret_key,
            "AWS_DEFAULT_REGION":          "us-east-1",
            "AWS_BUCKET":                  bucket_name,
            "AWS_ENDPOINT":                "http://pgops.local:9000",
            "AWS_USE_PATH_STYLE_ENDPOINT": "true",
        })
    except Exception as exc:
        _step("Writing .env file", "error")
        raise RuntimeError(f".env write failed: {exc}")
    _step("Writing .env file", "done")

    # ── 5. key:generate ───────────────────────────────────────────────────────
    _step("Running artisan key:generate")
    try:
        run_artisan(app_folder, ["key:generate"])
    except Exception as exc:
        _step("Running artisan key:generate", "error")
        raise RuntimeError(str(exc))
    _step("Running artisan key:generate", "done")

    # ── 6. migrate ────────────────────────────────────────────────────────────
    _step("Running artisan migrate")
    try:
        run_artisan(app_folder, ["migrate", "--force"])
    except Exception as exc:
        _step("Running artisan migrate", "error")
        raise RuntimeError(str(exc))
    _step("Running artisan migrate", "done")

    # ── 7. Build registry entry ───────────────────────────────────────────────
    app = {
        "id":               slug,
        "display_name":     display_name,
        "folder":           app_folder,
        "internal_port":    internal_port,
        "domain":           domain,
        "database":         db_name,
        "db_username":      db_user,
        "db_password":      db_password,
        "bucket":           bucket_name,
        "bucket_access_key": access_key,
        "bucket_secret_key": secret_key,
        "git_remote":       source_path if source_type == "git" else "",
        "git_branch":       git_branch,
        "status":           "running",
        "created_at":       datetime.now(timezone.utc).isoformat(),
    }

    upsert_app(app)
    return app


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_app(
    app_id: str,
    admin_config: dict,
    progress: Progress = None,
):
    """
    Remove an app completely:
    stop process → drop DB → drop bucket → delete folder → remove registry entry.
    """

    def _step(label, status="running"):
        if progress:
            progress(label, status)

    app = get_app_by_id(app_id)
    if not app:
        raise RuntimeError(f"App '{app_id}' not found in registry.")

    _step("Stopping app process")
    # Caller should stop the process first; this is a safety belt
    _step("Stopping app process", "done")

    _step(f"Dropping database '{app['database']}'")
    try:
        import core.db_manager as dbm
        dbm.drop_database(
            app["database"],
            admin_config.get("username", "postgres"),
            admin_config.get("password", "postgres"),
            admin_config.get("port", 5432),
        )
    except Exception:
        pass   # best-effort
    _step(f"Dropping database '{app['database']}'", "done")

    _step(f"Dropping bucket '{app['bucket']}'")
    try:
        from core.bucket_manager import drop_bucket
        drop_bucket(app["bucket"])
    except Exception:
        pass   # best-effort
    _step(f"Dropping bucket '{app['bucket']}'", "done")

    _step("Deleting app files")
    try:
        shutil.rmtree(app["folder"], ignore_errors=True)
    except Exception:
        pass
    _step("Deleting app files", "done")

    remove_app_from_registry(app_id)


# ── Git pull / update ─────────────────────────────────────────────────────────

def pull_app(
    app_id: str,
    progress: Progress = None,
):
    """
    git pull → migrate → clear caches → return app dict.
    Caller is responsible for restarting the process.
    """

    def _step(label, status="running"):
        if progress:
            progress(label, status)

    app = get_app_by_id(app_id)
    if not app:
        raise RuntimeError(f"App '{app_id}' not found.")

    if not app.get("git_remote"):
        raise RuntimeError(f"App '{app_id}' has no git remote configured.")

    _step("Pulling latest from git")
    try:
        import git as gitpython
        repo = gitpython.Repo(app["folder"])
        origin = repo.remotes.origin
        origin.pull()
    except Exception as exc:
        _step("Pulling latest from git", "error")
        raise RuntimeError(f"git pull failed: {exc}")
    _step("Pulling latest from git", "done")

    _step("Running artisan migrate")
    try:
        run_artisan(app["folder"], ["migrate", "--force"])
    except Exception as exc:
        _step("Running artisan migrate", "error")
        raise RuntimeError(str(exc))
    _step("Running artisan migrate", "done")

    _step("Clearing config cache")
    try:
        run_artisan(app["folder"], ["config:cache"])
        run_artisan(app["folder"], ["route:cache"])
        run_artisan(app["folder"], ["view:cache"])
    except Exception:
        pass   # non-fatal
    _step("Clearing config cache", "done")

    return app
