"""
api_server.py
Lightweight HTTP API server on 127.0.0.1:7420.
Used exclusively by the pgops CLI — never exposed on the LAN.
Uses only the Python standard library (http.server + json).
"""

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs


API_HOST = "127.0.0.1"
API_PORT = 7420


# ── Request handler ───────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    """Routes HTTP requests to the registered handler callbacks."""

    # Injected by APIServer
    router: dict = {}

    def log_message(self, *args):
        pass   # suppress default access log

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400):
        self._send_json({"error": message}, status)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def _route(self, method: str):
        parsed  = urlparse(self.path)
        path    = parsed.path.rstrip("/")
        key     = (method, path)
        handler = self.router.get(key)

        if handler is None:
            # Try wildcard match (e.g. /api/apps/{id}/start)
            handler, path_params = _match_route(self.router, method, path)
        else:
            path_params = {}

        if handler is None:
            self._send_error("Not found", 404)
            return

        try:
            body = self._read_body() if method in ("POST", "PUT", "PATCH") else {}
            result = handler(body=body, path_params=path_params, query=parsed.query)
            self._send_json(result or {})
        except Exception as exc:
            traceback.print_exc()
            self._send_error(str(exc), 500)

    def do_GET(self):    self._route("GET")
    def do_POST(self):   self._route("POST")
    def do_DELETE(self): self._route("DELETE")


def _match_route(
    router: dict, method: str, path: str
) -> tuple[Optional[Callable], dict]:
    """
    Match a path against registered route patterns.
    Pattern tokens starting with '{' are treated as named capture groups.
    Example: /api/apps/{id}/start matches /api/apps/inventory/start
             with path_params = {"id": "inventory"}
    """
    for (m, pattern), handler in router.items():
        if m != method:
            continue
        p_parts   = pattern.split("/")
        r_parts   = path.split("/")
        if len(p_parts) != len(r_parts):
            continue
        params = {}
        matched = True
        for pp, rp in zip(p_parts, r_parts):
            if pp.startswith("{") and pp.endswith("}"):
                params[pp[1:-1]] = rp
            elif pp != rp:
                matched = False
                break
        if matched:
            return handler, params
    return None, {}


# ── API server ────────────────────────────────────────────────────────────────

class APIServer:
    """
    Minimal HTTP server that provides the pgops CLI interface.
    Only binds to 127.0.0.1 — never reachable from LAN.
    """

    def __init__(
        self,
        app_registry_fn: Callable,      # fn() -> list[dict]
        process_manager,                 # AppProcessManager
        postgres_manager,                # PostgresManager
        seaweedfs_manager,               # SeaweedFSManager
        caddy_manager,                   # CaddyManager
        admin_config: dict,
        log_fn=None,
    ):
        self._apps_fn    = app_registry_fn
        self._procs      = process_manager
        self._pg         = postgres_manager
        self._seaweedfs  = seaweedfs_manager
        self._caddy      = caddy_manager
        self._cfg        = admin_config
        self._log        = log_fn or print
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Build route table
        self._router: dict = {}
        self._register_routes()

    # ── Route registration ────────────────────────────────────────────────────

    def _register_routes(self):
        r = self._router

        r[("GET",    "/api/status")]             = self._status
        r[("GET",    "/api/apps")]               = self._list_apps
        r[("POST",   "/api/apps/deploy")]        = self._deploy
        r[("POST",   "/api/apps/{id}/start")]    = self._start_app
        r[("POST",   "/api/apps/{id}/stop")]     = self._stop_app
        r[("POST",   "/api/apps/{id}/restart")]  = self._restart_app
        r[("POST",   "/api/apps/{id}/pull")]     = self._pull_app
        r[("GET",    "/api/apps/{id}/logs")]     = self._get_logs
        r[("DELETE", "/api/apps/{id}")]          = self._delete_app
        r[("POST",   "/api/db/create")]          = self._db_create
        r[("GET",    "/api/db/list")]            = self._db_list
        r[("POST",   "/api/backup/{db}")]        = self._backup_db

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _status(self, **_):
        return {
            "pgops":      "running",
            "postgres":   self._pg.is_running(),
            "seaweedfs":  self._seaweedfs.is_running(),
            "caddy":      self._caddy.is_running(),
            "apps":       len(self._apps_fn()),
        }

    def _list_apps(self, **_):
        apps = self._apps_fn()
        status_map = self._procs.status_map()
        for app in apps:
            live = status_map.get(app["id"])
            if live:
                app["live_status"] = live
        return {"apps": apps}

    def _deploy(self, body: dict, **_):
        from core.app_manager import provision_app, upsert_app
        from core.frankenphp_manager import get_frankenphp_bin

        slug        = body.get("slug", "")
        display     = body.get("display_name", slug)
        source_type = body.get("source_type", "zip")
        source_path = body.get("source_path", "")
        git_branch  = body.get("git_branch", "main")

        steps = []
        def _prog(step, status):
            steps.append({"step": step, "status": status})

        app = provision_app(
            slug=slug,
            display_name=display,
            source_type=source_type,
            source_path=source_path,
            git_branch=git_branch,
            admin_config=self._cfg,
            progress=_prog,
        )
        # Start the process
        self._procs.start_app(app)
        # Reload Caddy
        self._caddy.update_apps(self._apps_fn())

        return {"app": app, "steps": steps}

    def _start_app(self, path_params: dict, **_):
        app_id = path_params.get("id")
        from core.app_manager import get_app_by_id, set_app_status
        app = get_app_by_id(app_id)
        if not app:
            raise RuntimeError(f"App '{app_id}' not found.")
        ok, msg = self._procs.start_app(app)
        if ok:
            set_app_status(app_id, "running")
            self._caddy.update_apps(self._apps_fn())
        return {"ok": ok, "message": msg}

    def _stop_app(self, path_params: dict, **_):
        app_id = path_params.get("id")
        from core.app_manager import set_app_status
        ok, msg = self._procs.stop_app(app_id)
        if ok:
            set_app_status(app_id, "stopped")
            self._caddy.update_apps(self._apps_fn())
        return {"ok": ok, "message": msg}

    def _restart_app(self, path_params: dict, **_):
        app_id = path_params.get("id")
        from core.app_manager import get_app_by_id, set_app_status
        app = get_app_by_id(app_id)
        if not app:
            raise RuntimeError(f"App '{app_id}' not found.")
        ok, msg = self._procs.restart_app(app_id, app)
        return {"ok": ok, "message": msg}

    def _pull_app(self, path_params: dict, **_):
        app_id = path_params.get("id")
        from core.app_manager import pull_app, get_app_by_id

        steps = []
        def _prog(step, status):
            steps.append({"step": step, "status": status})

        app = pull_app(app_id, progress=_prog)
        ok, msg = self._procs.restart_app(app_id, app)
        self._caddy.update_apps(self._apps_fn())
        return {"ok": ok, "steps": steps, "message": msg}

    def _get_logs(self, path_params: dict, query: str = "", **_):
        app_id = path_params.get("id")
        qs     = parse_qs(query)
        n      = int(qs.get("lines", ["100"])[0])
        lines  = self._procs.get_logs(app_id, n)
        return {"app_id": app_id, "lines": lines}

    def _delete_app(self, path_params: dict, **_):
        app_id = path_params.get("id")
        from core.app_manager import delete_app

        steps = []
        def _prog(step, status):
            steps.append({"step": step, "status": status})

        self._procs.stop_app(app_id)
        delete_app(app_id, self._cfg, progress=_prog)
        self._caddy.update_apps(self._apps_fn())
        return {"ok": True, "steps": steps}

    def _db_create(self, body: dict, **_):
        import core.db_manager as dbm
        name     = body.get("name", "")
        username = body.get("username", "")
        password = body.get("password", "")
        ok, msg  = dbm.create_database(
            name, username, password,
            self._cfg["username"], self._cfg["password"], self._cfg["port"]
        )
        return {"ok": ok, "message": msg}

    def _db_list(self, **_):
        import core.db_manager as dbm
        dbs = dbm.list_databases(
            self._cfg["username"], self._cfg["password"], self._cfg["port"]
        )
        return {"databases": dbs}

    def _backup_db(self, path_params: dict, **_):
        db = path_params.get("db")
        import core.db_manager as dbm
        ok, msg, path = dbm.backup_database(
            db, self._cfg["username"], self._cfg["password"], self._cfg["port"]
        )
        return {"ok": ok, "message": msg, "file": str(path) if path else None}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        if self._server:
            return True, "API server already running."

        class _H(_Handler):
            router = self._router

        try:
            self._server = HTTPServer((API_HOST, API_PORT), _H)
        except OSError as exc:
            return False, f"API server bind failed on port {API_PORT}: {exc}"

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="PGOps-API",
        )
        self._thread.start()
        msg = f"[API] Internal API server running on {API_HOST}:{API_PORT}"
        self._log(msg)
        return True, msg

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        self._log("[API] Internal API server stopped.")

    def is_running(self) -> bool:
        return self._server is not None
