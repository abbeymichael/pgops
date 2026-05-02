"""
orchestrator.py
================
ServiceOrchestrator — the single authority that starts, stops, and monitors
every PGOps service.

Design contract
---------------
  DECLARE → PREFLIGHT → START (in dependency order) → MONITOR → STOP (reverse order)

The orchestrator replaces the previous pattern of:
  QTimer.singleShot(500, ...) + QTimer.singleShot(600, ...) + ...
which gave no ordering guarantees and swallowed port-collision errors.

Usage (from main_window.py)
---------------------------
    from core.orchestrator import ServiceOrchestrator

    orch = ServiceOrchestrator(
        config          = self.config,
        starters        = {...},   # service_id → callable() → (bool, str)
        stoppers        = {...},   # service_id → callable() → (bool, str)
        health_checks   = None,    # optional overrides (defaults from registry)
        log_fn          = self._log,
        on_state_change = self._on_service_state_change,  # UI callback
    )

    # Start everything (runs in a background thread — non-blocking)
    orch.start_all()

    # Start one service (pre-flight included)
    orch.start_service("rustfs")

    # Stop everything in reverse order
    orch.stop_all()

    # Current snapshot for the UI
    states = orch.snapshot()   # dict[service_id, ServiceState]
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.service_registry import (
    ServiceSpec,
    build_registry,
    startup_order,
    shutdown_order,
)
from core.preflight import (
    PreflightReport,
    run_preflight,
    check_service_ports,
)


# ── Service lifecycle states ──────────────────────────────────────────────────

class State(Enum):
    DECLARED   = auto()   # registered but not yet started
    PREFLIGHT  = auto()   # pre-flight checks running
    STARTING   = auto()   # start() called, waiting for health probe
    HEALTHY    = auto()   # health probe passed
    DEGRADED   = auto()   # was healthy, probe now fails (transient)
    STOPPED    = auto()   # cleanly stopped
    FAILED     = auto()   # start failed or health never reached
    SKIPPED    = auto()   # blocked by preflight (port conflict) or missing binary
    OPTIONAL   = auto()   # optional service — skipped without error


@dataclass
class ServiceState:
    service_id:  str
    state:       State      = State.DECLARED
    message:     str        = ""
    started_at:  float      = 0.0
    stopped_at:  float      = 0.0
    fail_reason: str        = ""
    # Port conflicts found during preflight (if any)
    conflicts:   list       = field(default_factory=list)


# ── Orchestrator ──────────────────────────────────────────────────────────────

class ServiceOrchestrator:
    """
    Deterministic service lifecycle manager.

    Parameters
    ----------
    config : dict
        Live config dict (read-only; call rebuild_registry() after changes).
    starters : dict[str, Callable[[], tuple[bool, str]]]
        Map of service_id → function that starts the service.
        Must return (success: bool, message: str).
    stoppers : dict[str, Callable[[], tuple[bool, str]]]
        Map of service_id → function that stops the service.
    data_dirs : list[Path], optional
        Directories to check for write permission during pre-flight.
    log_fn : Callable[[str], None], optional
        Log sink — receives plain strings.
    on_state_change : Callable[[str, ServiceState], None], optional
        Called (from a background thread) whenever a service changes state.
        Implementations should post to the Qt main thread via a signal.
    """

    def __init__(
        self,
        config:          dict,
        starters:        Dict[str, Callable],
        stoppers:        Dict[str, Callable],
        data_dirs:       Optional[List[Path]] = None,
        log_fn:          Optional[Callable]   = None,
        on_state_change: Optional[Callable]   = None,
    ):
        self._config          = config
        self._starters        = starters
        self._stoppers        = stoppers
        self._data_dirs       = data_dirs or []
        self._log_fn          = log_fn or print
        self._on_state_change = on_state_change

        self._registry: Dict[str, ServiceSpec]  = build_registry(config)
        self._states:   Dict[str, ServiceState] = {
            sid: ServiceState(service_id=sid)
            for sid in self._registry
        }

        self._lock     = threading.Lock()
        self._stop_evt = threading.Event()

        # Background monitor thread (started lazily)
        self._monitor_thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def rebuild_registry(self, config: dict):
        """Rebuild the registry after a config change (port numbers etc.)."""
        with self._lock:
            self._config   = config
            self._registry = build_registry(config)
            # Preserve existing state entries; add new ones
            for sid in self._registry:
                if sid not in self._states:
                    self._states[sid] = ServiceState(service_id=sid)

    def snapshot(self) -> Dict[str, ServiceState]:
        """Return a shallow copy of all service states (thread-safe)."""
        with self._lock:
            return dict(self._states)

    def get_state(self, service_id: str) -> Optional[ServiceState]:
        with self._lock:
            return self._states.get(service_id)

    # ── Start / stop ──────────────────────────────────────────────────────────

    def start_all(self, skip_preflight: bool = False) -> PreflightReport:
        """
        Start all declared services in dependency order.
        Runs the full pre-flight first (port conflict detection + stale socket
        cleanup + permission checks).
        Returns the PreflightReport so the caller can surface warnings.
        Non-blocking: the actual startup loop runs in a background thread.
        """
        report = self._run_preflight()
        thread = threading.Thread(
            target   = self._startup_loop,
            args     = (report,),
            daemon   = True,
            name     = "pgops-orchestrator-startup",
        )
        thread.start()
        return report

    def stop_all(self):
        """
        Stop all services in reverse dependency order (synchronous).
        Blocks until all stoppers have returned.
        """
        self._stop_evt.set()
        order = shutdown_order(self._registry)
        for sid in order:
            if sid not in self._stoppers:
                continue
            st = self._get_state(sid)
            if st.state not in (State.HEALTHY, State.DEGRADED, State.STARTING):
                continue
            self._log(f"Stopping {self._registry[sid].name}…")
            self._set_state(sid, State.STOPPED, "Stopping…")
            try:
                ok, msg = self._stoppers[sid]()
            except Exception as exc:
                ok, msg = False, str(exc)
            self._set_state(
                sid,
                State.STOPPED if ok else State.FAILED,
                msg,
            )
            self._log(f"[{self._registry[sid].name}] {msg}")

    def start_service(self, service_id: str) -> Tuple[bool, str]:
        """
        Start a single service (pre-flight on its ports + wait for health).
        Synchronous — intended for the UI "Start" button on individual cards.
        Returns (success, message).
        """
        spec = self._registry.get(service_id)
        if not spec:
            return False, f"Unknown service '{service_id}'."

        # Per-service preflight
        conflicts = check_service_ports(spec, log_fn=self._log_fn)
        if conflicts:
            msgs = [c.message() for c in conflicts]
            combined = " | ".join(msgs)
            self._set_state(service_id, State.SKIPPED, combined)
            hints = "\n".join(c.fix_hint() for c in conflicts)
            return False, f"Port conflict: {combined}\n\nFix: {hints}"

        # Remove stale sockets for this service
        for sock in spec.stale_sockets:
            if sock.exists():
                try:
                    sock.unlink()
                    self._log(f"[Preflight] Removed stale socket: {sock.name}")
                except Exception as exc:
                    self._log(f"[Preflight] Could not remove {sock}: {exc}")

        return self._start_one(service_id)

    def stop_service(self, service_id: str) -> Tuple[bool, str]:
        """Stop a single service. Synchronous."""
        stopper = self._stoppers.get(service_id)
        if not stopper:
            return False, f"No stopper registered for '{service_id}'."
        try:
            ok, msg = stopper()
        except Exception as exc:
            ok, msg = False, str(exc)
        self._set_state(service_id, State.STOPPED if ok else State.FAILED, msg)
        return ok, msg

    # ── Monitor (background health re-check) ──────────────────────────────────

    def start_monitoring(self, interval: float = 5.0):
        """
        Start a background thread that re-checks health probes every
        `interval` seconds and transitions HEALTHY → DEGRADED when a
        service unexpectedly stops responding.
        """
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_evt.clear()
        self._monitor_thread = threading.Thread(
            target   = self._monitor_loop,
            args     = (interval,),
            daemon   = True,
            name     = "pgops-orchestrator-monitor",
        )
        self._monitor_thread.start()

    def stop_monitoring(self):
        self._stop_evt.set()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, msg: str):
        try:
            self._log_fn(msg)
        except Exception:
            pass

    def _get_state(self, sid: str) -> ServiceState:
        with self._lock:
            return self._states[sid]

    def _set_state(self, sid: str, state: State, message: str = ""):
        with self._lock:
            st = self._states[sid]
            st.state   = state
            st.message = message
            if state == State.HEALTHY:
                st.started_at = time.monotonic()
            elif state in (State.STOPPED, State.FAILED):
                st.stopped_at = time.monotonic()
        if self._on_state_change:
            try:
                self._on_state_change(sid, self._states[sid])
            except Exception:
                pass

    def _run_preflight(self) -> PreflightReport:
        self._log("[Orchestrator] Running pre-flight checks…")
        report = run_preflight(
            registry  = self._registry,
            data_dirs = self._data_dirs,
            log_fn    = self._log_fn,
        )
        # Mark blocked services
        for sid in report.blocked_services:
            if sid in self._states:
                conflicts = [c for c in report.port_conflicts if c.service_id == sid]
                with self._lock:
                    self._states[sid].conflicts = conflicts
                self._set_state(sid, State.SKIPPED, report.port_conflicts[0].message() if report.port_conflicts else "Blocked by preflight")

        # Log the full report
        for line in report.summary_lines():
            self._log(f"[Preflight] {line}")

        return report

    def _start_one(self, sid: str) -> Tuple[bool, str]:
        """
        Call the registered starter for sid, then wait for the health probe.
        Returns (ok, message).
        """
        spec    = self._registry[sid]
        starter = self._starters.get(sid)

        self._set_state(sid, State.STARTING, f"Starting {spec.name}…")
        self._log(f"[Orchestrator] Starting {spec.name}…")

        if starter is None:
            # No starter registered — this service is managed externally
            # (e.g. the internal landing server is started by its own object)
            # Treat as healthy if the probe passes.
            if spec.is_healthy():
                self._set_state(sid, State.HEALTHY, f"{spec.name} already running.")
                return True, f"{spec.name} already running."
            self._set_state(sid, State.SKIPPED, "No starter registered — skipping.")
            return True, "No starter registered — skipping."

        try:
            result = starter()
            if isinstance(result, tuple):
                ok, msg = result[0], result[1] if len(result) > 1 else ""
            else:
                ok, msg = bool(result), ""
        except Exception as exc:
            ok, msg = False, str(exc)

        if not ok:
            reason = f"Starter failed: {msg}"
            self._set_state(sid, State.FAILED, reason)
            self._log(f"[Orchestrator] ✗ {spec.name} failed to start: {msg}")
            return False, reason

        # Wait for health
        if spec.health_probe:
            self._log(f"[Orchestrator] Waiting for {spec.name} health probe…")
            healthy = spec.wait_until_healthy(log_fn=self._log_fn)
            if not healthy:
                reason = (
                    f"{spec.name} started but health probe timed out "
                    f"after {spec.startup_timeout:.0f}s."
                )
                self._set_state(sid, State.FAILED, reason)
                self._log(f"[Orchestrator] ✗ {reason}")
                return False, reason

        final_msg = f"{spec.name} is healthy."
        self._set_state(sid, State.HEALTHY, final_msg)
        self._log(f"[Orchestrator] ✓ {final_msg}")
        return True, final_msg

    def _startup_loop(self, report: PreflightReport):
        """
        Background thread: start services in dependency order.
        Blocked / failed dependencies cause their dependents to be skipped.
        """
        order  = startup_order(self._registry)
        failed = set(report.blocked_services)  # already blocked by preflight

        for sid in order:
            spec = self._registry[sid]

            # Skip if pre-flight blocked this service
            if sid in failed:
                self._log(
                    f"[Orchestrator] Skipping {spec.name} "
                    f"(blocked by preflight or dependency failure)."
                )
                continue

            # Skip if no starter registered and not already healthy
            starter = self._starters.get(sid)
            if starter is None and not spec.is_healthy():
                # Not a fatal error — the service may be managed elsewhere
                self._set_state(sid, State.SKIPPED, "Managed externally or not configured.")
                continue

            # Check that all dependencies are healthy
            dep_ok = True
            for dep_id in spec.depends_on:
                dep_state = self._get_state(dep_id)
                if dep_state.state not in (State.HEALTHY,):
                    # Allow optional dependencies to be skipped without blocking
                    dep_spec = self._registry.get(dep_id)
                    if dep_spec and dep_spec.optional:
                        self._log(
                            f"[Orchestrator] {spec.name}: optional dependency "
                            f"'{dep_id}' not healthy — continuing anyway."
                        )
                    else:
                        self._log(
                            f"[Orchestrator] Skipping {spec.name}: "
                            f"required dependency '{dep_id}' is not healthy "
                            f"(state={dep_state.state.name})."
                        )
                        failed.add(sid)
                        self._set_state(
                            sid,
                            State.SKIPPED,
                            f"Dependency '{dep_id}' not healthy.",
                        )
                        dep_ok = False
                        break

            if not dep_ok:
                continue

            # If already healthy (e.g. autostart already ran), skip
            if spec.is_healthy():
                self._set_state(sid, State.HEALTHY, f"{spec.name} already running.")
                continue

            ok, msg = self._start_one(sid)
            if not ok:
                if spec.optional:
                    self._log(
                        f"[Orchestrator] ⚠ Optional service {spec.name} failed: {msg}"
                    )
                    # Don't add to failed — optional deps don't block others
                else:
                    failed.add(sid)

        self._log("[Orchestrator] Startup sequence complete.")

    def _monitor_loop(self, interval: float):
        """Background thread: periodically re-check health of running services."""
        while not self._stop_evt.wait(timeout=interval):
            with self._lock:
                snapshot = dict(self._states)

            for sid, st in snapshot.items():
                if st.state not in (State.HEALTHY, State.DEGRADED):
                    continue
                spec = self._registry.get(sid)
                if not spec or spec.health_probe is None:
                    continue

                try:
                    alive = spec.is_healthy()
                except Exception:
                    alive = False

                if not alive and st.state == State.HEALTHY:
                    self._set_state(sid, State.DEGRADED, f"{spec.name} stopped responding.")
                    self._log(
                        f"[Monitor] ⚠ {spec.name} stopped responding — "
                        f"state → DEGRADED."
                    )
                elif alive and st.state == State.DEGRADED:
                    self._set_state(sid, State.HEALTHY, f"{spec.name} recovered.")
                    self._log(f"[Monitor] ✓ {spec.name} recovered.")


# ── Convenience: human-readable state label + colour hint ────────────────────

STATE_LABEL: Dict[State, str] = {
    State.DECLARED:  "Declared",
    State.PREFLIGHT: "Pre-flight",
    State.STARTING:  "Starting…",
    State.HEALTHY:   "Running",
    State.DEGRADED:  "Degraded",
    State.STOPPED:   "Stopped",
    State.FAILED:    "Failed",
    State.SKIPPED:   "Skipped",
    State.OPTIONAL:  "Optional",
}

# CSS-style colour tokens (match ui/theme.py palette)
STATE_COLOR: Dict[State, str] = {
    State.DECLARED:  "#6b7280",   # grey
    State.PREFLIGHT: "#f59e0b",   # amber
    State.STARTING:  "#3b82f6",   # blue
    State.HEALTHY:   "#22c55e",   # green
    State.DEGRADED:  "#f97316",   # orange
    State.STOPPED:   "#6b7280",   # grey
    State.FAILED:    "#ef4444",   # red
    State.SKIPPED:   "#a78bfa",   # violet
    State.OPTIONAL:  "#6b7280",   # grey
}
