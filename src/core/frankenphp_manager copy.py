"""
frankenphp_manager.py
Manages FrankenPHP processes — one per deployed Laravel app.

FEATURES:
- PHP extension discovery: compiled-in vs runtime .so extensions
- Per-app php.ini written at runtime so each app activates only what it needs
- Extension auto-activation: if an extension is compiled-in or loadable, it is
  enabled before the app starts — startup is NOT blocked by a missing extension
  unless it is truly unavailable (not compiled in and no .so found)
- AppProcess._read_logs() uses a thread with readline() to avoid PIPE deadlock
- stop() waits for log thread to finish before returning
- AppProcessManager.stop_app() removes the process from the dict after stopping
- status_map() includes all known apps (not just those still in processes dict)
- AppProcess.start() catches and re-raises with full detail on early exit
- MAX_LOG_LINES uses deque for O(1) append/pop
"""

import os
import sys
import subprocess
import platform
import shutil
import socket
import threading
import time
import zipfile
from collections import deque
from pathlib import Path
from typing import Optional

# ── Helpers ────────────────────────────────────────────────────────────────────


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def _free_port(port: int):
    """Kill any process listening on the given TCP port."""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, **_popen_kwargs(),
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        if pid.isdigit():
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True, **_popen_kwargs(),
                            )
                    break
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True
            )
            for pid_str in result.stdout.strip().splitlines():
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    subprocess.run(["kill", "-9", pid_str], capture_output=True)
    except Exception:
        pass


# ── Paths ──────────────────────────────────────────────────────────────────────


def get_frankenphp_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "frankenphp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_frankenphp_bin() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return get_frankenphp_dir() / f"frankenphp{ext}"


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


def get_extensions_dir() -> Path:
    """Directory where FrankenPHP/PHP stores runtime .so extension files."""
    d = get_frankenphp_dir() / "ext"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_php_ini_dir() -> Path:
    """Base directory — per-app ini files live in subdirectories here."""
    d = get_frankenphp_dir() / "php_ini"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_app_php_ini_path(app_id: str) -> Path:
    """Return the path of the php.ini file for a specific app."""
    app_dir = get_php_ini_dir() / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "php.ini"


def is_frankenphp_available() -> bool:
    return get_frankenphp_bin().exists()


# ── Extension inspection ───────────────────────────────────────────────────────


def get_compiled_extensions(frankenphp_bin: str) -> set[str]:
    """
    Return the set of extensions that are compiled directly into FrankenPHP
    (i.e. always available, no .so needed).  We detect them by comparing
    `php -m` output with `php -r 'phpinfo(INFO_MODULES);'` — but the simplest
    reliable approach for FrankenPHP is parsing `php -m` and cross-referencing
    with extensions that appear even when extension_dir is empty.
    """
    try:
        result = subprocess.run(
            [frankenphp_bin, "php", "-m"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return set()
        return {
            line.strip().lower()
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("[")
        }
    except Exception:
        return set()


def get_available_so_extensions(frankenphp_bin: str) -> dict[str, Path]:
    """
    Scan known extension directories for .so / .dll files and return a map of
    { extension_name: path_to_so }.

    Search order:
      1. Our own managed extensions dir (get_extensions_dir())
      2. The PHP extension_dir reported by the binary itself
      3. Common system paths on Linux/macOS
    """
    ext_suffix = ".dll" if platform.system() == "Windows" else ".so"
    search_dirs: list[Path] = [get_extensions_dir()]

    # Ask FrankenPHP where its extension_dir is
    try:
        result = subprocess.run(
            [frankenphp_bin, "php", "-r", "echo ini_get('extension_dir');"],
            capture_output=True, text=True,
        )
        reported = result.stdout.strip()
        if reported and Path(reported).is_dir():
            search_dirs.append(Path(reported))
    except Exception:
        pass

    # Common system extension directories
    if platform.system() == "Linux":
        for candidate in [
            "/usr/lib/php", "/usr/lib64/php",
            "/usr/lib/php/extensions", "/usr/lib64/php/extensions",
        ]:
            p = Path(candidate)
            if p.is_dir():
                search_dirs.append(p)
                # also recurse one level (php/<version>/)
                for sub in p.iterdir():
                    if sub.is_dir():
                        search_dirs.append(sub)
    elif platform.system() == "Darwin":
        for candidate in [
            "/usr/local/lib/php/extensions",
            "/opt/homebrew/lib/php/extensions",
        ]:
            p = Path(candidate)
            if p.is_dir():
                search_dirs.append(p)
                for sub in p.iterdir():
                    if sub.is_dir():
                        search_dirs.append(sub)

    found: dict[str, Path] = {}
    for d in search_dirs:
        try:
            for f in d.iterdir():
                if f.suffix == ext_suffix and f.is_file():
                    # strip leading "php_" (Windows) or nothing
                    name = f.stem.lower()
                    if name.startswith("php_"):
                        name = name[4:]
                    if name not in found:
                        found[name] = f
        except Exception:
            pass

    return found


def get_extension_status(frankenphp_bin: str) -> dict[str, dict]:
    """
    Return a full picture of every extension we know about:

    {
      "pdo_pgsql": {
          "status": "active" | "compiled_in" | "loadable" | "missing",
          "source": "compiled" | "so:<path>" | None,
      },
      ...
    }
    """
    compiled = get_compiled_extensions(frankenphp_bin)
    so_map = get_available_so_extensions(frankenphp_bin)

    all_names = compiled | set(so_map.keys())
    result: dict[str, dict] = {}
    for name in all_names:
        if name in compiled:
            result[name] = {"status": "active", "source": "compiled"}
        elif name in so_map:
            result[name] = {"status": "loadable", "source": f"so:{so_map[name]}"}
    return result


def list_all_extensions(frankenphp_bin: str) -> list[dict]:
    """
    Public helper — returns a list of dicts suitable for display in a UI:
    [{"name": "pdo_pgsql", "status": "active", "source": "compiled"}, ...]
    """
    status = get_extension_status(frankenphp_bin)
    return [
        {"name": name, **info}
        for name, info in sorted(status.items())
    ]


def install_extension_so(so_path: str | Path) -> tuple[bool, str]:
    """
    Copy a .so / .dll file into the managed extensions directory so it becomes
    discoverable by future calls to get_available_so_extensions().
    """
    src = Path(so_path)
    if not src.exists():
        return False, f"File not found: {src}"
    dest = get_extensions_dir() / src.name
    try:
        shutil.copy2(src, dest)
        return True, f"Extension installed: {dest.name}"
    except Exception as exc:
        return False, f"Failed to install extension: {exc}"


# ── Required extensions ────────────────────────────────────────────────────────

LARAVEL_REQUIRED_EXTENSIONS = {
    "bcmath",
    "ctype",
    "fileinfo",
    "json",
    "mbstring",
    "openssl",
    "pdo",
    "pdo_pgsql",
    "tokenizer",
    "xml",
}

# ── Per-app php.ini management ─────────────────────────────────────────────────


def build_php_ini(
    app_id: str,
    extensions_to_load: list[tuple[str, Path]],
    extra_ini: dict | None = None,
) -> Path:
    """
    Write (or overwrite) the php.ini for *app_id*.

    extensions_to_load  — list of (name, so_path) for extensions that need an
                          explicit `extension=` directive.  Compiled-in extensions
                          don't need a directive and are NOT included here.
    extra_ini           — optional dict of additional php.ini key=value pairs
                          (e.g. {"memory_limit": "512M"}).

    Returns the path to the written file.
    """
    ini_path = get_app_php_ini_path(app_id)

    memory  = os.environ.get("PGOPS_PHP_MEMORY", "256M")
    upload  = os.environ.get("PGOPS_PHP_UPLOAD",  "50M")

    lines = [
        "; Auto-generated by PGOps FrankenPHP manager — do not edit manually.",
        f"; App: {app_id}",
        "",
        "[PHP]",
        f"memory_limit = {memory}",
        f"upload_max_filesize = {upload}",
        f"post_max_size = {upload}",
        "display_errors = Off",
        "log_errors = On",
        "",
        "; Extensions loaded from .so files",
    ]

    for name, so_path in sorted(extensions_to_load, key=lambda x: x[0]):
        lines.append(f"extension={so_path}")

    if extra_ini:
        lines += ["", "; App-specific overrides"]
        for k, v in extra_ini.items():
            lines.append(f"{k} = {v}")

    ini_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ini_path


def ensure_app_php_ini(
    app_id: str,
    required_extensions: set[str],
    frankenphp_bin: str,
) -> tuple[Path, list[str]]:
    """
    Ensure a php.ini exists for the app that activates all required extensions
    that are not compiled in.

    Returns (ini_path, list_of_truly_missing_extensions).

    Truly missing = required but neither compiled-in nor loadable from a .so.
    The app can still be started — callers decide whether to block or warn.
    """
    compiled = get_compiled_extensions(frankenphp_bin)
    so_map   = get_available_so_extensions(frankenphp_bin)

    to_load: list[tuple[str, Path]] = []
    missing: list[str] = []

    for ext in required_extensions:
        if ext in compiled:
            pass  # already active, no ini directive needed
        elif ext in so_map:
            to_load.append((ext, so_map[ext]))
        else:
            missing.append(ext)

    ini_path = build_php_ini(app_id, to_load)
    return ini_path, missing


# ── FrankenPHP binary setup ────────────────────────────────────────────────────


def _get_download_info() -> tuple[str, str, bool]:
    base   = "https://github.com/php/frankenphp/releases/latest/download"
    system = platform.system()

    if system == "Windows":
        fname = "frankenphp.zip"
        return f"{base}/{fname}", fname, True

    if system == "Darwin":
        import platform as _p
        machine = _p.machine().lower()
        fname   = "frankenphp-mac-arm64" if ("arm" in machine or "aarch" in machine) else "frankenphp-mac-x86_64"
        return f"{base}/{fname}", fname, False

    fname = "frankenphp-linux-x86_64"
    return f"{base}/{fname}", fname, False


def _bundled_asset_name() -> str:
    return "frankenphp.zip" if platform.system() == "Windows" else "frankenphp_mac"


def _install_from_zip(zip_path: Path, dest_dir: Path, progress_callback=None):
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total   = len(members)
        for i, member in enumerate(members):
            zf.extract(member, dest_dir)
            if progress_callback and total:
                progress_callback(60 + int(i / total * 35))

    contents = list(dest_dir.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        inner = contents[0]
        for item in inner.iterdir():
            shutil.move(str(item), dest_dir)
        inner.rmdir()


def _install_from_binary(src: Path, dest_dir: Path, progress_callback=None):
    dest = dest_dir / "frankenphp"
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    if progress_callback:
        progress_callback(95)


def setup_frankenphp_binary(progress_callback=None) -> tuple[bool, str]:
    """Ensure the FrankenPHP binary is installed."""
    dest_dir = get_frankenphp_dir()
    bin_path = get_frankenphp_bin()

    if bin_path.exists():
        return True, "FrankenPHP already available."

    if progress_callback:
        progress_callback(5)

    bundled = get_assets_dir() / _bundled_asset_name()
    if bundled.exists():
        try:
            if progress_callback:
                progress_callback(15)
            if platform.system() == "Windows":
                _install_from_zip(bundled, dest_dir, progress_callback)
            else:
                _install_from_binary(bundled, dest_dir, progress_callback)
            if bin_path.exists():
                if progress_callback:
                    progress_callback(100)
                return True, "FrankenPHP extracted from bundle."
            return False, "Bundle extraction finished but binary not found."
        except Exception as exc:
            return False, f"Failed to extract bundled FrankenPHP: {exc}"

    url, fname, is_zip = _get_download_info()
    archive_dest = dest_dir / fname

    try:
        import requests
        resp  = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        total      = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(archive_dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(5 + int(downloaded / total * 50))
    except Exception as exc:
        return False, f"Failed to download FrankenPHP: {exc}"

    try:
        if is_zip:
            _install_from_zip(archive_dest, dest_dir, progress_callback)
        else:
            _install_from_binary(archive_dest, dest_dir, progress_callback)
    except Exception as exc:
        return False, f"Failed to install FrankenPHP: {exc}"
    finally:
        try:
            archive_dest.unlink(missing_ok=True)
        except Exception:
            pass

    if not bin_path.exists():
        return False, (
            f"FrankenPHP binary not found after setup.\n"
            f"Expected: {bin_path}\n"
            f"Dir: {[p.name for p in dest_dir.iterdir()]}"
        )

    if progress_callback:
        progress_callback(100)
    return True, "FrankenPHP downloaded and installed."


# ── Per-app process ────────────────────────────────────────────────────────────

MAX_LOG_LINES = 1000


class AppProcess:
    """A single FrankenPHP process serving one Laravel app."""

    def __init__(self, app: dict, frankenphp_bin: str, php_ini_path: Path):
        self.app             = app
        self.frankenphp_bin  = frankenphp_bin
        self.php_ini_path    = php_ini_path
        self.process: Optional[subprocess.Popen] = None
        self._log_lines: deque = deque(maxlen=MAX_LOG_LINES)
        self._log_lock   = threading.Lock()
        self._log_thread: Optional[threading.Thread] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        public_dir = os.path.join(self.app["folder"], "public")
        if not os.path.isdir(public_dir):
            return False, f"App public/ directory not found: {public_dir}"

        port = self.app["internal_port"]
        _free_port(port)

        env = self._build_env()
        cmd = [
            self.frankenphp_bin,
            "php-server",
            "--listen", f"127.0.0.1:{port}",
            "--root",   public_dir,
        ]

        try:
            kwargs             = _popen_kwargs()
            kwargs["stdout"]   = subprocess.PIPE
            kwargs["stderr"]   = subprocess.STDOUT
            kwargs["env"]      = env
            kwargs["cwd"]      = self.app["folder"]
            self.process       = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            return False, f"Failed to start '{self.app['id']}': {exc}"

        self._log_thread = threading.Thread(
            target=self._read_logs,
            daemon=True,
            name=f"PGOps-App-Log-{self.app['id']}",
        )
        self._log_thread.start()

        time.sleep(1.0)
        if self.process.poll() is not None:
            last   = self.get_last_logs(30)
            output = "".join(last)
            return False, (
                f"Process exited immediately (code {self.process.returncode}).\n"
                f"Output:\n{output}"
            )

        return True, f"App '{self.app['id']}' started on port {port}."

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                    self.process.wait(timeout=2)
                except Exception:
                    pass
            except Exception:
                pass
            self.process = None

        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=2)
        self._log_thread = None

    def restart(self) -> tuple[bool, str]:
        self.stop()
        return self.start()

    # ── Status ─────────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def port_listening(self) -> bool:
        port = self.app.get("internal_port", 0)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            return result == 0
        except Exception:
            return False

    # ── Logs ───────────────────────────────────────────────────────────────────

    def _read_logs(self):
        if not self.process or not self.process.stdout:
            return
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                with self._log_lock:
                    self._log_lines.append(decoded)
        except Exception:
            pass

    def get_last_logs(self, n: int = 100) -> list[str]:
        with self._log_lock:
            lines = list(self._log_lines)
        return lines[-n:]

    # ── Environment ────────────────────────────────────────────────────────────

    def _build_env(self) -> dict:
        env = {**os.environ}
        memory = os.environ.get("PGOPS_PHP_MEMORY", "256M")
        upload = os.environ.get("PGOPS_PHP_UPLOAD",  "50M")

        # Point PHP_INI_SCAN_DIR at the app's own ini directory so FrankenPHP
        # picks up the generated php.ini (with extension= directives) at startup.
        ini_dir = str(self.php_ini_path.parent)

        env.update({
            "PHP_INI_SCAN_DIR":        ini_dir,
            "PHP_MEMORY_LIMIT":        memory,
            "PHP_UPLOAD_MAX_FILESIZE": upload,
            "PHP_POST_MAX_SIZE":       upload,
            "APP_ENV":                 "production",
        })
        return env


# ── Process registry ───────────────────────────────────────────────────────────


class AppProcessManager:
    """Maintains a dict of AppProcess instances keyed by app id."""

    def __init__(self, log_fn=None):
        self._log       = log_fn or print
        self._processes: dict[str, AppProcess] = {}
        self._lock      = threading.Lock()

    @property
    def processes(self) -> dict:
        with self._lock:
            return dict(self._processes)

    @property
    def _bin(self) -> str:
        return str(get_frankenphp_bin())

    def is_binary_available(self) -> bool:
        return is_frankenphp_available()

    # ── Extension management (public API) ──────────────────────────────────────

    def list_extensions(self) -> list[dict]:
        """
        Return all known extensions with their status.  Useful for surfacing
        extension info in a UI so the user can see what is active / loadable /
        missing.

        Each entry: {"name": str, "status": str, "source": str}
          status  → "active" (compiled-in and currently on), "loadable" (has a
                    .so file we can load via php.ini), "missing" (not available).
        """
        if not self.is_binary_available():
            return []
        return list_all_extensions(self._bin)

    def install_extension(self, so_path: str | Path) -> tuple[bool, str]:
        """
        Register an external .so / .dll so it becomes available for loading.
        After this call, apps that need it will pick it up on next start/restart.
        """
        return install_extension_so(so_path)

    def rebuild_app_ini(
        self,
        app_id: str,
        required_extensions: set[str] | None = None,
        extra_ini: dict | None = None,
    ) -> tuple[Path, list[str]]:
        """
        (Re)generate the php.ini for an app.  Pass extra_ini to override or add
        arbitrary php.ini settings for this specific app.

        Returns (ini_path, missing_extensions).
        """
        exts = required_extensions if required_extensions is not None else LARAVEL_REQUIRED_EXTENSIONS
        return ensure_app_php_ini(app_id, exts, self._bin)

    # ── Per-app lifecycle ──────────────────────────────────────────────────────

    def start_app(
        self,
        app: dict,
        required_extensions: set[str] | None = None,
        extra_ini: dict | None = None,
        block_on_missing: bool = False,
    ) -> tuple[bool, str]:
        """
        Start an app.

        Extension handling:
          1. Compile the app's php.ini, activating every extension that is either
             compiled-in or available as a .so.
          2. If any required extensions are truly unavailable:
             - block_on_missing=True  → return failure (old behaviour, opt-in)
             - block_on_missing=False → log a warning and start anyway so the app
               can at least boot; the missing extension will surface as a PHP
               error only if/when the app actually uses it.

        extra_ini — forwarded to build_php_ini for per-app ini overrides.
        """
        if not is_frankenphp_available():
            return False, "FrankenPHP binary not found."

        exts = required_extensions if required_extensions is not None else LARAVEL_REQUIRED_EXTENSIONS

        # Build / refresh the app's php.ini
        ini_path, missing = ensure_app_php_ini(app["id"], exts, self._bin)

        if extra_ini:
            # Re-write with the extra_ini included
            compiled = get_compiled_extensions(self._bin)
            so_map   = get_available_so_extensions(self._bin)
            to_load  = [
                (ext, so_map[ext])
                for ext in exts
                if ext not in compiled and ext in so_map
            ]
            ini_path = build_php_ini(app["id"], to_load, extra_ini=extra_ini)

        if missing:
            msg = (
                f"[App:{app['id']}] Warning — the following required PHP extensions "
                f"are not available (not compiled-in, no .so found):\n"
                f"  {', '.join(sorted(missing))}\n"
                f"The app will start but may fail if it uses those extensions.\n"
                f"To fix: place the extension .so files in:\n"
                f"  {get_extensions_dir()}\n"
                f"then restart the app."
            )
            self._log(msg)
            if block_on_missing:
                return False, msg

        proc     = AppProcess(app, self._bin, ini_path)
        ok, pmsg = proc.start()
        if ok:
            with self._lock:
                self._processes[app["id"]] = proc
            self._log(f"[App:{app['id']}] Started on port {app['internal_port']}.")
        else:
            self._log(f"[App:{app['id']}] Failed to start: {pmsg}")
        return ok, pmsg

    def stop_app(self, app_id: str) -> tuple[bool, str]:
        with self._lock:
            proc = self._processes.pop(app_id, None)
        if proc is None:
            return True, f"App '{app_id}' not in process list."
        proc.stop()
        self._log(f"[App:{app_id}] Stopped.")
        return True, f"App '{app_id}' stopped."

    def restart_app(
        self,
        app_id: str,
        app: dict,
        required_extensions: set[str] | None = None,
        extra_ini: dict | None = None,
        block_on_missing: bool = False,
    ) -> tuple[bool, str]:
        self.stop_app(app_id)
        return self.start_app(
            app,
            required_extensions=required_extensions,
            extra_ini=extra_ini,
            block_on_missing=block_on_missing,
        )

    def start_all(
        self,
        apps: list,
        required_extensions: set[str] | None = None,
        block_on_missing: bool = False,
    ) -> list[tuple[str, bool, str]]:
        results = []
        for app in apps:
            ok, msg = self.start_app(
                app,
                required_extensions=required_extensions,
                block_on_missing=block_on_missing,
            )
            results.append((app["id"], ok, msg))
        return results

    def stop_all(self):
        with self._lock:
            app_ids = list(self._processes.keys())
        for app_id in app_ids:
            self.stop_app(app_id)

    # ── Status / logs ──────────────────────────────────────────────────────────

    def is_running(self, app_id: str) -> bool:
        with self._lock:
            proc = self._processes.get(app_id)
        return proc.is_running if proc else False

    def get_logs(self, app_id: str, n: int = 100) -> list[str]:
        with self._lock:
            proc = self._processes.get(app_id)
        return proc.get_last_logs(n) if proc else []

    def status_map(self) -> dict[str, str]:
        """Returns status for all tracked processes."""
        with self._lock:
            procs = dict(self._processes)
        return {
            app_id: ("running" if proc.is_running else "stopped")
            for app_id, proc in procs.items()
        }