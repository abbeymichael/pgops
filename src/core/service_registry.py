"""
service_registry.py
====================
Declarative manifest for every PGOps service.

Each ServiceSpec says:
  - what ports it owns (so no two services can collide)
  - what services must be healthy before it starts
  - how to probe whether it is alive
  - how long to wait for it to become healthy
  - what Unix/Windows socket paths it creates (for stale-socket cleanup)
  - whether it is optional (missing binary → skip, not fatal)

The registry itself is the single source of truth.  Nothing in
main_window.py or any manager should hard-code a port number or an
assumed startup order — it reads from here.
"""

from __future__ import annotations

import platform
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


# ── Probe helpers ─────────────────────────────────────────────────────────────

def _tcp_probe(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if something is listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_probe(url: str, timeout: float = 2.0) -> bool:
    """Return True if url returns any HTTP response (even 4xx/5xx)."""
    try:
        import urllib.request
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception as exc:
        # Any response at all (including HTTP errors) means the port is live
        import urllib.error
        if isinstance(exc, urllib.error.HTTPError):
            return True
        return False


# ── Core dataclass ────────────────────────────────────────────────────────────

@dataclass
class ServiceSpec:
    """
    Describes a single managed service.

    Parameters
    ----------
    name : str
        Human-readable label shown in the UI and logs.
    service_id : str
        Stable key used in dependency lists and dictionaries.
    ports : list[int]
        Every TCP port this service binds.  Pre-flight checks all of them
        before attempting startup.
    depends_on : list[str]
        service_id values that must reach `healthy` state first.
    health_probe : Callable[[], bool]
        Zero-argument callable; returns True when the service is ready.
    startup_timeout : float
        Seconds to wait for health_probe to return True after launch.
    poll_interval : float
        Seconds between health_probe calls during the wait loop.
    optional : bool
        When True a missing binary / failed start is a warning, not an error.
        The orchestrator will skip it and continue with dependents that don't
        strictly need it.
    stale_sockets : list[Path]
        Unix-socket paths (or named-pipe paths) that a previous crashed
        process may have left behind.  Pre-flight deletes them before start.
    description : str
        One-line description shown in the Orchestrator UI panel.
    """

    name:            str
    service_id:      str
    ports:           List[int]           = field(default_factory=list)
    depends_on:      List[str]           = field(default_factory=list)
    health_probe:    Optional[Callable]  = None
    startup_timeout: float               = 20.0
    poll_interval:   float               = 0.5
    optional:        bool                = False
    stale_sockets:   List[Path]          = field(default_factory=list)
    description:     str                 = ""

    def is_healthy(self) -> bool:
        if self.health_probe is None:
            return True
        try:
            return bool(self.health_probe())
        except Exception:
            return False

    def wait_until_healthy(self, log_fn=None) -> bool:
        """
        Block until health_probe returns True or startup_timeout elapses.
        Returns True on success.
        """
        deadline = time.monotonic() + self.startup_timeout
        attempt  = 0
        while time.monotonic() < deadline:
            if self.is_healthy():
                return True
            attempt += 1
            if log_fn and attempt % 4 == 0:
                remaining = max(0.0, deadline - time.monotonic())
                log_fn(
                    f"[Orchestrator] Waiting for {self.name} "
                    f"({remaining:.0f}s remaining)…"
                )
            time.sleep(self.poll_interval)
        return False


# ── Registry builder ──────────────────────────────────────────────────────────

def build_registry(config: dict) -> dict[str, ServiceSpec]:
    """
    Construct the full service registry from the current config dict.
    Returns an ordered dict: service_id → ServiceSpec.

    Call this once at startup (or after config changes) so that port numbers
    are always read from the live config, never from hard-coded constants.
    """

    pg_port      = int(config.get("port",                  5432))
    landing_port = int(config.get("landing_port",          8080))
    api_port     = 7420   # internal API — not user-configurable
    s3_port      = int(config.get("seaweedfs_s3_port",     8333))
    filer_port   = int(config.get("seaweedfs_filer_port",  8888))
    master_port  = int(config.get("seaweedfs_master_port", 9333))
    pgadmin_port = int(config.get("pgadmin_port",          5050))
    caddy_http   = int(config.get("caddy_http_port",       80))
    caddy_https  = int(config.get("caddy_https_port",      443))

    # SeaweedFS internal gRPC port for the master (master_port + 10000)
    master_grpc  = master_port + 10000   # e.g. 19333

    # Stale Unix sockets SeaweedFS leaves behind on Windows/Linux crashes
    tmp = Path("/tmp")
    swfs_sockets = [
        tmp / f"seaweedfs-master-grpc-{master_grpc}.sock",
        tmp / f"seaweedfs-master-{master_port}.sock",
    ]

    registry: dict[str, ServiceSpec] = {}

    # ── 1. PostgreSQL ─────────────────────────────────────────────────────────
    registry["postgres"] = ServiceSpec(
        name            = "PostgreSQL",
        service_id      = "postgres",
        ports           = [pg_port],
        depends_on      = [],
        health_probe    = lambda: _tcp_probe("127.0.0.1", pg_port),
        startup_timeout = 30.0,
        optional        = False,
        description     = f"Database server  ·  port {pg_port}",
    )

    # ── 2. Landing server (pure-Python HTTP — starts fast) ────────────────────
    registry["landing"] = ServiceSpec(
        name            = "Landing Server",
        service_id      = "landing",
        ports           = [landing_port],
        depends_on      = [],          # independent of postgres
        health_probe    = lambda: _tcp_probe("127.0.0.1", landing_port),
        startup_timeout = 10.0,
        optional        = True,
        description     = f"pgops.local root page  ·  port {landing_port}",
    )

    # ── 3. Internal API server ────────────────────────────────────────────────
    registry["api"] = ServiceSpec(
        name            = "Internal API",
        service_id      = "api",
        ports           = [api_port],
        depends_on      = [],
        health_probe    = lambda: _tcp_probe("127.0.0.1", api_port),
        startup_timeout = 10.0,
        optional        = True,
        description     = f"CLI bridge  ·  127.0.0.1:{api_port}",
    )

    # ── 4. SeaweedFS (master + volume + filer + S3 in one process) ───────────
    registry["seaweedfs"] = ServiceSpec(
        name            = "SeaweedFS",
        service_id      = "seaweedfs",
        ports           = [s3_port, filer_port, master_port],
        depends_on      = [],          # independent of postgres
        health_probe    = lambda: _tcp_probe("127.0.0.1", s3_port),
        startup_timeout = 40.0,
        poll_interval   = 1.0,
        optional        = True,
        stale_sockets   = swfs_sockets,
        description     = (
            f"Object storage  ·  S3:{s3_port}  "
            f"Filer:{filer_port}  Master:{master_port}"
        ),
    )

    # ── 5. pgAdmin (depends on postgres being up) ─────────────────────────────
    registry["pgadmin"] = ServiceSpec(
        name            = "pgAdmin 4",
        service_id      = "pgadmin",
        ports           = [pgadmin_port],
        depends_on      = ["postgres"],
        health_probe    = lambda: _tcp_probe("127.0.0.1", pgadmin_port),
        startup_timeout = 60.0,
        poll_interval   = 1.5,
        optional        = True,
        description     = f"Database UI  ·  port {pgadmin_port}",
    )

    # ── 6. Caddy (depends on landing, seaweedfs, pgadmin being ready) ─────────
    registry["caddy"] = ServiceSpec(
        name            = "Caddy",
        service_id      = "caddy",
        ports           = [caddy_http, caddy_https],
        depends_on      = ["landing", "seaweedfs"],   # pgadmin optional
        health_probe    = lambda: _tcp_probe("127.0.0.1", caddy_https),
        startup_timeout = 15.0,
        optional        = True,
        description     = (
            f"Reverse proxy + TLS  ·  "
            f"HTTP:{caddy_http}  HTTPS:{caddy_https}"
        ),
    )

    # ── 7. FrankenPHP / App processes (need Caddy + postgres) ─────────────────
    registry["apps"] = ServiceSpec(
        name            = "Laravel Apps (FrankenPHP)",
        service_id      = "apps",
        ports           = [],          # dynamic per-app ports — not checked here
        depends_on      = ["caddy", "postgres"],
        health_probe    = None,        # checked per-app by AppProcessManager
        startup_timeout = 5.0,
        optional        = True,
        description     = "PHP app processes  ·  one per deployed app",
    )

    return registry


# ── Topological sort ──────────────────────────────────────────────────────────

def startup_order(registry: dict[str, ServiceSpec]) -> list[str]:
    """
    Return service_ids in dependency-respecting startup order
    (Kahn's algorithm — deterministic, detects cycles).
    Raises RuntimeError on circular dependency.
    """
    in_degree: dict[str, int]       = {sid: 0 for sid in registry}
    dependents: dict[str, list[str]] = {sid: [] for sid in registry}

    for sid, spec in registry.items():
        for dep in spec.depends_on:
            if dep in registry:
                in_degree[sid] += 1
                dependents[dep].append(sid)

    queue  = [sid for sid, deg in in_degree.items() if deg == 0]
    order  = []

    while queue:
        # Sort within the same "level" for determinism
        queue.sort()
        node = queue.pop(0)
        order.append(node)
        for child in sorted(dependents[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(order) != len(registry):
        cycle_nodes = [sid for sid in registry if sid not in order]
        raise RuntimeError(
            f"Circular dependency detected among services: {cycle_nodes}"
        )

    return order


def shutdown_order(registry: dict[str, ServiceSpec]) -> list[str]:
    """Reverse of startup_order — shut down dependents before dependencies."""
    return list(reversed(startup_order(registry)))
