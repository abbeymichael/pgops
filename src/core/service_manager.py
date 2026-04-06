"""
service_manager.py
Installs and manages PostgreSQL as a proper Windows service using pg_ctl register.
"""

import subprocess
import platform
from pathlib import Path


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as _sp
        return {"creationflags": _sp.CREATE_NO_WINDOW}
    return {}


def is_windows() -> bool:
    return platform.system() == "Windows"


def _sc(args: list) -> tuple[bool, str]:
    """Run sc.exe (Windows Service Control)."""
    try:
        r = subprocess.run(
            ["sc"] + args,
            capture_output=True, text=True, **_popen_kwargs()
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def service_exists(name: str = "PGOps-PostgreSQL") -> bool:
    """Check if the service is registered (running or stopped)."""
    if not is_windows():
        return False
    ok, out = _sc(["query", name])
    return "STATE" in out


def service_running(name: str = "PGOps-PostgreSQL") -> bool:
    """Check if the service is currently running."""
    if not is_windows():
        return False
    ok, out = _sc(["query", name])
    return "RUNNING" in out


def install_service(
    pg_ctl_path: Path,
    data_dir: Path,
    log_file: Path,
    port: int = 5432,
    name: str = "PGOps-PostgreSQL",
    display_name: str = "PGOps PostgreSQL Server",
) -> tuple[bool, str]:
    """Register PostgreSQL as a Windows service using pg_ctl register."""
    if not is_windows():
        return False, "Windows service only supported on Windows."
    if not pg_ctl_path.exists():
        return False, f"pg_ctl not found at {pg_ctl_path}"

    r = subprocess.run([
        str(pg_ctl_path), "register",
        "-N", name,
        "-D", str(data_dir),
        "-l", str(log_file),
        "-S", "auto",
        "-w",
    ], capture_output=True, text=True, **_popen_kwargs())

    if r.returncode != 0:
        return False, f"Failed to register service:\n{(r.stdout + r.stderr).strip()}"

    _sc(["config", name, "DisplayName=", f'"{display_name}"'])
    _sc(["description", name, "PostgreSQL database server managed by PGOps"])
    return True, f"Service '{name}' installed and set to auto-start."


def uninstall_service(name: str = "PGOps-PostgreSQL") -> tuple[bool, str]:
    """Stop and remove the service."""
    if not is_windows():
        return False, "Not on Windows."
    stop_service(name)
    ok, msg = _sc(["delete", name])
    if not ok:
        return False, f"Failed to remove service: {msg}"
    return True, f"Service '{name}' removed."


def start_service(name: str = "PGOps-PostgreSQL") -> tuple[bool, str]:
    """Start the service."""
    if not is_windows():
        return False, "Not on Windows."
    ok, msg = _sc(["start", name])
    if not ok:
        return False, f"Failed to start service: {msg}"
    return True, "Service started."


def stop_service(name: str = "PGOps-PostgreSQL") -> tuple[bool, str]:
    """Stop the service."""
    if not is_windows():
        return False, "Not on Windows."
    ok, msg = _sc(["stop", name])
    if not ok:
        return False, f"Failed to stop service: {msg}"
    return True, "Service stopped."


def is_admin() -> bool:
    """Check if the current process has admin privileges."""
    if not is_windows():
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
