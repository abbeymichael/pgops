"""
preflight.py
=============
Pre-flight checks that run *before* any service is started.

Responsibilities
----------------
1. PORT CONFLICT DETECTION
   Scan every port declared in the registry.  If a port is already in use,
   determine who owns it (PID + process name on platforms that support it)
   and surface a clear, actionable message instead of letting the service
   crash with "bind: address already in use".

2. STALE SOCKET CLEANUP
   RustFS (and any future gRPC service) leaves behind Unix socket files
   when it crashes on Windows/Linux.  The next start attempt fails with
   "A socket operation encountered a dead network."  We delete those files
   before starting the service.

3. DATA-DIRECTORY PERMISSIONS CHECK
   Ensure the app-data directory (and service-specific sub-dirs) are
   writable.  Catches the "Access is denied" raft state-dir panic.

4. RESULTS SURFACE
   Returns a PreflightReport that the orchestrator (and UI) can inspect to
   decide whether to abort, warn, or proceed.
"""

from __future__ import annotations

import os
import platform
import socket
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.service_registry import ServiceSpec


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class PortConflict:
    port:       int
    service_id: str          # which service declared this port
    owner_pid:  Optional[int] = None
    owner_name: Optional[str] = None

    def message(self) -> str:
        if self.owner_pid and self.owner_name:
            return (
                f"Port {self.port} (needed by '{self.service_id}') is already "
                f"in use by '{self.owner_name}' (PID {self.owner_pid})."
            )
        elif self.owner_pid:
            return (
                f"Port {self.port} (needed by '{self.service_id}') is already "
                f"in use by PID {self.owner_pid}."
            )
        else:
            return (
                f"Port {self.port} (needed by '{self.service_id}') is already "
                f"in use by an unknown process."
            )

    def fix_hint(self) -> str:
        if self.owner_name and "rustfs" in self.owner_name.lower():
            return (
                "A previous RustFS process is still running. "
                "Open Task Manager, find 'rustfs.exe', and end it — "
                "or restart PGOps and use the Stop button before starting again."
            )
        if self.owner_name and "postgres" in self.owner_name.lower():
            return (
                "Another PostgreSQL instance is already using this port. "
                "Stop it or change the port in Settings."
            )
        if self.owner_pid:
            return (
                f"Stop PID {self.owner_pid} before starting PGOps, "
                "or change the conflicting port in Settings → Advanced."
            )
        return "Stop the conflicting process or change the port in Settings."


@dataclass
class StaleSocketRemoval:
    path:    Path
    success: bool
    error:   str = ""


@dataclass
class PermissionIssue:
    path:    Path
    message: str


@dataclass
class PreflightReport:
    port_conflicts:       List[PortConflict]      = field(default_factory=list)
    stale_removals:       List[StaleSocketRemoval] = field(default_factory=list)
    permission_issues:    List[PermissionIssue]    = field(default_factory=list)
    # service_ids that are blocked and must be skipped
    blocked_services:     List[str]               = field(default_factory=list)

    @property
    def has_fatal_conflicts(self) -> bool:
        """True if any non-optional service has a port conflict."""
        return bool(self.blocked_services)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        for c in self.port_conflicts:
            lines.append(f"⚠  {c.message()}")
            lines.append(f"   → {c.fix_hint()}")
        for s in self.stale_removals:
            if s.success:
                lines.append(f"✓  Removed stale socket: {s.path.name}")
            else:
                lines.append(f"✗  Could not remove stale socket {s.path}: {s.error}")
        for p in self.permission_issues:
            lines.append(f"✗  Permission denied: {p.path}  ({p.message})")
        return lines


# ── Port ownership (best-effort, platform-specific) ───────────────────────────

def _port_owner(port: int) -> Tuple[Optional[int], Optional[str]]:
    """
    Return (pid, process_name) for the process listening on the given port,
    or (None, None) if it cannot be determined.
    """
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status in (
                "LISTEN", psutil.CONN_LISTEN
            ):
                pid = conn.pid
                if pid:
                    try:
                        return pid, psutil.Process(pid).name()
                    except Exception:
                        return pid, None
        return None, None
    except ImportError:
        pass

    # Fallback: netstat on Windows
    if platform.system() == "Windows":
        try:
            import subprocess
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,   # CREATE_NO_WINDOW
            ).decode(errors="replace")
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.split()
                    try:
                        pid = int(parts[-1])
                        return pid, None
                    except Exception:
                        pass
        except Exception:
            pass

    return None, None


def _is_port_in_use(port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except Exception:
        return False


# ── Stale socket cleanup ──────────────────────────────────────────────────────

def _remove_stale_socket(path: Path) -> StaleSocketRemoval:
    if not path.exists():
        # Nothing there — not an issue
        return StaleSocketRemoval(path=path, success=True)

    try:
        path.unlink()
        return StaleSocketRemoval(path=path, success=True)
    except Exception as exc:
        return StaleSocketRemoval(path=path, success=False, error=str(exc))


# ── Directory permission check ────────────────────────────────────────────────

def _check_writable(path: Path) -> Optional[PermissionIssue]:
    """Return a PermissionIssue if path is not writable, else None."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".pgops_write_test"
        probe.write_text("ok")
        probe.unlink()
        return None
    except Exception as exc:
        return PermissionIssue(
            path    = path,
            message = str(exc),
        )


# ── Main preflight runner ─────────────────────────────────────────────────────

def run_preflight(
    registry: Dict[str, ServiceSpec],
    data_dirs: Optional[List[Path]] = None,
    log_fn=None,
) -> PreflightReport:
    """
    Run all pre-flight checks.

    Parameters
    ----------
    registry  : the service registry (service_id → ServiceSpec)
    data_dirs : additional directories to check for write permission
    log_fn    : optional callable(str) for progress messages

    Returns a PreflightReport.  The caller (ServiceOrchestrator) uses
    `report.blocked_services` to decide which services to skip.
    """
    def _log(msg: str):
        if log_fn:
            log_fn(f"[Preflight] {msg}")

    report = PreflightReport()

    # ── 1. Remove stale sockets ───────────────────────────────────────────────
    for spec in registry.values():
        for sock_path in spec.stale_sockets:
            if sock_path.exists():
                _log(f"Found stale socket {sock_path.name} — removing…")
                result = _remove_stale_socket(sock_path)
                report.stale_removals.append(result)
                if result.success:
                    _log(f"Removed stale socket: {sock_path.name}")
                else:
                    _log(f"WARNING: Could not remove {sock_path}: {result.error}")

    # ── 2. Port conflict detection ────────────────────────────────────────────
    # Track which service already claimed each port (first-declared wins)
    claimed: Dict[int, str] = {}

    for service_id, spec in registry.items():
        for port in spec.ports:
            if port == 0:
                continue

            # Check inter-service conflicts first
            if port in claimed:
                _log(
                    f"Configuration conflict: port {port} claimed by both "
                    f"'{claimed[port]}' and '{service_id}'."
                )
                report.port_conflicts.append(
                    PortConflict(port=port, service_id=service_id)
                )
                report.blocked_services.append(service_id)
                continue

            claimed[port] = service_id

            # Check OS-level conflicts (another process already listening)
            if _is_port_in_use(port):
                # Is this the service itself already running? (idempotent check)
                if spec.is_healthy():
                    # Service is already up — not a conflict
                    _log(f"Port {port} in use by already-running {spec.name} — OK")
                    continue

                pid, pname = _port_owner(port)
                conflict = PortConflict(
                    port       = port,
                    service_id = service_id,
                    owner_pid  = pid,
                    owner_name = pname,
                )
                report.port_conflicts.append(conflict)
                if service_id not in report.blocked_services:
                    report.blocked_services.append(service_id)
                _log(conflict.message())
                _log(f"Fix: {conflict.fix_hint()}")

    # ── 3. Data-directory permission checks ───────────────────────────────────
    if data_dirs:
        for d in data_dirs:
            issue = _check_writable(d)
            if issue:
                _log(f"Permission denied on {d}: {issue.message}")
                report.permission_issues.append(issue)

    if not report.port_conflicts and not report.permission_issues:
        _log("All checks passed.")

    return report


# ── Convenience: check a single service before (re)starting it ───────────────

def check_service_ports(spec: ServiceSpec, log_fn=None) -> List[PortConflict]:
    """
    Quick port check for a single ServiceSpec.
    Used by the UI before attempting a manual start.
    """
    conflicts: List[PortConflict] = []
    for port in spec.ports:
        if _is_port_in_use(port) and not spec.is_healthy():
            pid, pname = _port_owner(port)
            c = PortConflict(
                port       = port,
                service_id = spec.service_id,
                owner_pid  = pid,
                owner_name = pname,
            )
            conflicts.append(c)
            if log_fn:
                log_fn(f"[Preflight] {c.message()}")
    return conflicts
