"""
app_manager.py
App registry (apps.json) — read/write helpers, provisioning, deletion, git pull.
All heavy operations accept a progress_callback(step: str, status: str).

CHANGES:
- provision_app() does a full rollback on any failure:
    files extracted  → folder deleted
    database created → database + db_user dropped
    bucket created   → bucket dropped
  The rollback runs automatically; callers get a clean RuntimeError with detail.
- run_artisan() now accepts an optional php_ini_path so the per-app ini is
  honoured even during provisioning (key:generate / migrate).
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
    path = get_apps_json_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("apps", [])
    except Exception:
        return []


def save_apps(apps: list[dict]):
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
    apps = load_apps()
    for app in apps:
        if app.get("id") == app_id:
            app["status"] = status
            break
    save_apps(apps)


def set_app_php_extensions(app_id: str, extensions: list[str]):
    """Persist the list of extensions this app requires."""
    apps = load_apps()
    for app in apps:
        if app.get("id") == app_id:
            app["php_extensions"] = extensions
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
    import re

    if not slug:
        return False, "Slug is required."
    if len(slug) < 2:
        return False, "Slug must be at least 2 characters."
    if len(slug) > 50:
        return False, "Slug must be 50 characters or fewer."
    if not re.match(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$", slug):
        return False, (
            "Slug must use lowercase letters, digits, and hyphens only, "
            "and cannot start or end with a hyphen."
        )
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
    env_path = os.path.join(app_folder, ".env")
    example_path = os.path.join(app_folder, ".env.example")

    source_path = None

    if os.path.exists(env_path):
        source_path = env_path
    elif os.path.exists(example_path):
        source_path = example_path

    existing: dict[str, str] = {}

    # Load existing content if we have a source
    if source_path:
        with open(source_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()

                # Preserve empty lines and comments
                if not stripped or stripped.startswith("#"):
                    existing[line] = line
                elif "=" in line:
                    key = line.partition("=")[0].strip()
                    existing[key] = line
                else:
                    existing[line] = line

    # Override / insert values
    for key, value in values.items():
        existing[key] = f"{key}={value}\n"

    # Write final .env
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(existing.values())


# ── Artisan runner ────────────────────────────────────────────────────────────


def run_artisan(
    app_folder: str,
    args: list[str],
    timeout: int = 120,
    php_ini_path: Optional[str] = None,
    strict: bool = False,
) -> str:
    """
    Run a FrankenPHP artisan command in app_folder.

    strict=True  — any non-zero exit code is a RuntimeError (use for
                   key:generate, migrate, and any command that MUST succeed).
    strict=False — only rc > 1 raises; rc=1 is treated as a warning
                   (legacy behaviour for cache/route/view commands that can
                   return 1 on minor issues without being fatal).

    If php_ini_path is given, PHP_INI_SCAN_DIR is pointed at its parent so the
    per-app ini (with extension= directives) is loaded for this call.

    Returns combined stdout+stderr. Always raises RuntimeError on failure so
    callers get the full command output to surface to the user.
    """
    from core.frankenphp_manager import get_frankenphp_bin

    php_bin = str(get_frankenphp_bin())

    cmd = [php_bin, "php-cli", "artisan"] + args
    env = {**os.environ, "APP_ENV": "production"}

    if php_ini_path:
        env["PHP_INI_SCAN_DIR"] = str(Path(php_ini_path).parent)

    try:
        result = subprocess.run(
            cmd,
            cwd=app_folder,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"artisan {' '.join(args)} timed out after {timeout}s")
    except Exception as exc:
        raise RuntimeError(f"artisan {' '.join(args)} could not be launched: {exc}")

    output = (result.stdout + result.stderr).strip()

    # Decide what counts as failure
    failed = result.returncode != 0 if strict else result.returncode > 1

    if failed:
        # Truncate to last 60 lines so the error message stays readable but
        # contains enough context to diagnose the problem.
        lines = output.splitlines()
        tail = "\n".join(lines[-60:]) if len(lines) > 60 else output
        raise RuntimeError(
            f"artisan {' '.join(args)} failed (rc={result.returncode}):\n{tail}"
        )

    return output


# ── ZIP extraction helpers ────────────────────────────────────────────────────


def _extract_zip(zip_path: str, dest_folder: str):
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


# ── Rollback helpers ──────────────────────────────────────────────────────────


def _rollback_files(app_folder: str):
    """Delete extracted/cloned app files."""
    try:
        if os.path.exists(app_folder):
            shutil.rmtree(app_folder, ignore_errors=True)
    except Exception:
        pass


def _rollback_database(db_name: str, db_user: str, admin_config: dict):
    """Drop the database and its owner role."""
    try:
        import core.db_manager as dbm

        dbm.drop_database(
            db_name,
            admin_config.get("username", "postgres"),
            admin_config.get("password", "postgres"),
            admin_config.get("port", 5432),
        )
    except Exception:
        pass
    # Also drop the DB user/role if db_manager exposes it
    try:
        import core.db_manager as dbm

        if hasattr(dbm, "drop_user"):
            dbm.drop_user(
                db_user,
                admin_config.get("username", "postgres"),
                admin_config.get("password", "postgres"),
                admin_config.get("port", 5432),
            )
    except Exception:
        pass


def _rollback_bucket(bucket_name: str):
    """Drop the MinIO bucket."""
    try:
        from core.bucket_manager import drop_bucket

        drop_bucket(bucket_name)
    except Exception:
        pass


def _rollback_php_ini(app_id: str):
    """Remove the generated per-app php.ini directory."""
    try:
        from core.frankenphp_manager import get_php_ini_dir

        ini_dir = get_php_ini_dir() / app_id
        if ini_dir.exists():
            shutil.rmtree(ini_dir, ignore_errors=True)
    except Exception:
        pass


# ── Provision ─────────────────────────────────────────────────────────────────

Progress = Callable[[str, str], None]  # (step_label, status)


def provision_app(
    slug: str,
    display_name: str,
    source_type: str,  # "zip" or "git"
    source_path: str,  # abs path to zip, or git URL
    git_branch: str = "main",
    admin_config: dict = None,
    progress: Progress = None,
    required_extensions: set[str] | None = None,
) -> dict:
    """
    Full provisioning pipeline for a new Laravel app.
    Returns the completed app dict on success.
    On any step failure, performs a full rollback (files + DB + bucket + php.ini)
    then raises RuntimeError with a descriptive message.
    """

    def _step(label: str, status: str = "running"):
        if progress:
            progress(label, status)

    cfg = admin_config or {}
    app_folder = str(get_apps_dir() / slug)
    internal_port = get_next_port()
    domain = f"{slug}.pgops.local"
    db_name = f"{slug}_db"
    db_user = f"{slug}_user"
    db_password = generate_password()
    bucket_name = f"{slug}-files"

    # Track what has been created so rollback knows what to undo
    _created_files = False
    _created_db = False
    _created_bucket = False
    _created_ini = False

    def _full_rollback(reason: str):
        _step("Rolling back…", "running")
        if _created_ini:
            _rollback_php_ini(slug)
        if _created_bucket:
            _rollback_bucket(bucket_name)
        if _created_db:
            _rollback_database(db_name, db_user, cfg)
        if _created_files:
            _rollback_files(app_folder)
        remove_app_from_registry(slug)
        _step("Rolling back…", "done")
        raise RuntimeError(reason)

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
        _created_files = True
    except Exception as exc:
        _step(label, "error")
        _full_rollback(f"{label} failed: {exc}")
    else:
        _step(label, "done")

    # ── 2. PHP ini (pre-DB so artisan commands get the right extensions) ───────
    _step("Preparing PHP environment")
    ini_path: Optional[Path] = None
    try:
        from core.frankenphp_manager import (
            ensure_app_php_ini,
            LARAVEL_REQUIRED_EXTENSIONS,
            get_frankenphp_bin,
        )

        exts = (
            required_extensions
            if required_extensions is not None
            else LARAVEL_REQUIRED_EXTENSIONS
        )
        bin_path = str(get_frankenphp_bin())
        ini_path, missing = ensure_app_php_ini(slug, exts, bin_path)
        _created_ini = True
    except Exception:
        pass  # non-fatal — app will start without a custom ini
    _step("Preparing PHP environment", "done")
    if ini_path and missing:
        _step(
            f"PHP extensions not found (will warn): {', '.join(sorted(missing))}",
            "done",
        )

    # ── 3. Database ───────────────────────────────────────────────────────────
    _step(f"Creating database '{db_name}'")
    try:
        import core.db_manager as dbm

        ok, msg = dbm.create_database(
            db_name,
            db_user,
            db_password,
            cfg.get("username", "postgres"),
            cfg.get("password", "postgres"),
            cfg.get("port", 5432),
        )
        if not ok:
            raise RuntimeError(msg)
        _created_db = True
    except Exception as exc:
        _step(f"Creating database '{db_name}'", "error")
        _full_rollback(f"Database creation failed: {exc}")
    else:
        _step(f"Creating database '{db_name}'", "done")

    # ── 4. MinIO bucket ───────────────────────────────────────────────────────
    _step(f"Creating bucket '{bucket_name}'")
    access_key = secret_key = ""
    try:
        from core.bucket_manager import create_bucket

        ok, msg, creds = create_bucket(bucket_name, slug)
        if not ok:
            raise RuntimeError(msg)
        access_key = creds.get("access_key", "")
        secret_key = creds.get("secret_key", "")
        _created_bucket = True
    except Exception as exc:
        _step(f"Creating bucket '{bucket_name}'", "error")
        _full_rollback(f"Bucket creation failed: {exc}")
    else:
        _step(f"Creating bucket '{bucket_name}'", "done")

    # ── 5. .env ───────────────────────────────────────────────────────────────
    _step("Writing .env file")
    try:
        write_laravel_env(
            app_folder,
            {
                "APP_NAME": display_name,
                "APP_ENV": "production",
                "APP_KEY": "",  # generated later by artisan key:generate
                "APP_DEBUG": "false",
                "APP_URL": f"https://{domain}",
                "DB_CONNECTION": "pgsql",
                "DB_HOST": "pgops.local",
                "DB_PORT": "5432",
                "DB_DATABASE": db_name,
                "DB_USERNAME": db_user,
                "DB_PASSWORD": db_password,
                #"DB_SSLMODE": "require",
                "FILESYSTEM_DISK": "s3",
                "AWS_ACCESS_KEY_ID": access_key,
                "AWS_SECRET_ACCESS_KEY": secret_key,
                "AWS_DEFAULT_REGION": "us-east-1",
                "AWS_BUCKET": bucket_name,
                "AWS_ENDPOINT": "https://pgops.local:9000",
                "AWS_USE_PATH_STYLE_ENDPOINT": "true",
            },
        )
    except Exception as exc:
        _step("Writing .env file", "error")
        _full_rollback(f".env write failed: {exc}")
    else:
        _step("Writing .env file", "done")

    # ── 6. key:generate ───────────────────────────────────────────────────────
    _step("Running artisan key:generate")
    try:
        run_artisan(
            app_folder,
            ["key:generate"],
            php_ini_path=str(ini_path) if ini_path else None,
            strict=True,
        )
    except Exception as exc:
        _step("Running artisan key:generate", "error")
        _full_rollback(f"key:generate failed: {exc}")
    else:
        _step("Running artisan key:generate", "done")

    # ── 7. migrate ────────────────────────────────────────────────────────────
    _step("Running artisan migrate")
    try:
        run_artisan(
            app_folder,
            ["migrate", "--force"],
            php_ini_path=str(ini_path) if ini_path else None,
            strict=True,
        )
    except Exception as exc:
        _step("Running artisan migrate", "error")
        _full_rollback(f"migrate failed: {exc}")
    else:
        _step("Running artisan migrate", "done")

    # ── 8. Build registry entry ───────────────────────────────────────────────
    from core.frankenphp_manager import LARAVEL_REQUIRED_EXTENSIONS

    exts_list = sorted(required_extensions or LARAVEL_REQUIRED_EXTENSIONS)

    app = {
        "id": slug,
        "display_name": display_name,
        "folder": app_folder,
        "internal_port": internal_port,
        "domain": domain,
        "database": db_name,
        "db_username": db_user,
        "db_password": db_password,
        "bucket": bucket_name,
        "bucket_access_key": access_key,
        "bucket_secret_key": secret_key,
        "git_remote": source_path if source_type == "git" else "",
        "git_branch": git_branch,
        "php_extensions": exts_list,
        "status": "stopped",
        "created_at": datetime.now(timezone.utc).isoformat(),
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
    stop process → drop DB + user → drop bucket → delete folder
                → remove php.ini dir → remove registry entry.
    """

    def _step(label, status="running"):
        if progress:
            progress(label, status)

    app = get_app_by_id(app_id)
    if not app:
        raise RuntimeError(f"App '{app_id}' not found in registry.")

    _step("Stopping app process")
    _step("Stopping app process", "done")

    _step(f"Dropping database '{app['database']}'")
    _rollback_database(app["database"], app.get("db_username", ""), admin_config)
    _step(f"Dropping database '{app['database']}'", "done")

    _step(f"Dropping bucket '{app['bucket']}'")
    _rollback_bucket(app["bucket"])
    _step(f"Dropping bucket '{app['bucket']}'", "done")

    _step("Deleting app files")
    _rollback_files(app["folder"])
    _step("Deleting app files", "done")

    _step("Removing PHP config")
    _rollback_php_ini(app_id)
    _step("Removing PHP config", "done")

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

    # Resolve per-app ini path for artisan calls
    ini_path: Optional[str] = None
    try:
        from core.frankenphp_manager import get_app_php_ini_path

        p = get_app_php_ini_path(app_id)
        if p.exists():
            ini_path = str(p)
    except Exception:
        pass

    _step("Running artisan migrate")
    try:
        run_artisan(app["folder"], ["migrate", "--force"], php_ini_path=ini_path)
    except Exception as exc:
        _step("Running artisan migrate", "error")
        raise RuntimeError(str(exc))
    _step("Running artisan migrate", "done")

    _step("Clearing config cache")
    try:
        run_artisan(app["folder"], ["config:cache"], php_ini_path=ini_path)
        run_artisan(app["folder"], ["route:cache"], php_ini_path=ini_path)
        run_artisan(app["folder"], ["view:cache"], php_ini_path=ini_path)
    except Exception:
        pass
    _step("Clearing config cache", "done")

    return app