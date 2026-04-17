"""
landing_server.py
Tiny HTTP server on 127.0.0.1:8080.
Serves the pgops.test landing page — Caddy proxies pgops.test → here.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional


LANDING_HOST = "127.0.0.1"
LANDING_PORT = 8080   # Caddy proxies pgops.test → here; set via config["landing_port"]

_STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f1117; color: #e2e8f0; min-height: 100vh;
  }
  .header {
    background: #1a1d24; border-bottom: 1px solid #2a2d35;
    padding: 18px 32px; display: flex; align-items: center; gap: 14px;
  }
  .logo {
    background: linear-gradient(135deg, #4f8ef7, #2563eb);
    color: white; font-weight: 900; font-size: 14px;
    width: 36px; height: 36px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
  }
  .header h1 { font-size: 18px; font-weight: 700; }
  .header .sub { font-size: 12px; color: #64748b; margin-top: 2px; }
  .content { max-width: 900px; margin: 40px auto; padding: 0 24px; }
  h2 { font-size: 14px; font-weight: 700; color: #64748b;
       letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 16px; }
  .apps-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
               gap: 16px; margin-bottom: 40px; }
  .app-card {
    background: #1a1d24; border: 1px solid #2a2d35; border-radius: 12px;
    padding: 20px; transition: border-color .2s;
  }
  .app-card:hover { border-color: #4f8ef7; }
  .app-name { font-size: 16px; font-weight: 700; margin-bottom: 6px; }
  .app-domain a {
    color: #4f8ef7; text-decoration: none; font-family: monospace; font-size: 13px;
  }
  .app-domain a:hover { text-decoration: underline; }
  .badge {
    display: inline-block; font-size: 10px; font-weight: 700;
    letter-spacing: 1px; padding: 2px 8px; border-radius: 4px; margin-top: 10px;
  }
  .badge.running { color: #2ecc71; background: #0a2016; border: 1px solid #2ecc7144; }
  .badge.stopped { color: #e74c3c; background: #2a0d0d; border: 1px solid #e74c3c44; }
  .empty { color: #475569; text-align: center; padding: 48px; }
  .setup { background: #1a1d24; border: 1px solid #2a2d35; border-radius: 12px; padding: 24px; }
  .setup h3 { font-size: 14px; font-weight: 700; margin-bottom: 12px; }
  .setup p { font-size: 13px; color: #94a3b8; margin-bottom: 16px; }
  .ip-block {
    background: #0f1117; border: 1px solid #2a2d35; border-radius: 8px;
    padding: 12px 16px; font-family: monospace; font-size: 16px;
    font-weight: 700; color: #4f8ef7; margin-bottom: 16px;
    display: inline-block;
  }
  details { margin-top: 12px; }
  summary { cursor: pointer; font-size: 13px; color: #64748b; padding: 6px 0; }
  pre {
    background: #0f1117; border: 1px solid #2a2d35; border-radius: 6px;
    padding: 12px; font-size: 12px; color: #94a3b8;
    margin-top: 8px; white-space: pre-wrap; word-break: break-word;
  }
  footer { text-align: center; color: #334155; font-size: 11px; padding: 32px; }
</style>
"""

_SETUP_HTML = """
<div class="setup">
  <h3>Point your device to this DNS server</h3>
  <p>Do this once per device. After that, all app subdomains (*.pgops.test) work automatically.</p>
  <div class="ip-block">{host_ip}</div>
  <details>
    <summary>Windows</summary>
    <pre>1. Settings → Network &amp; Internet → Change adapter options
2. Right-click your network → Properties
3. Internet Protocol Version 4 → Properties
4. Use the following DNS server: {host_ip}
5. Click OK</pre>
  </details>
  <details>
    <summary>macOS</summary>
    <pre>1. System Settings → Network → your network → Details
2. DNS tab → + → enter {host_ip}
3. Click OK</pre>
  </details>
  <details>
    <summary>Android</summary>
    <pre>1. Settings → WiFi → long-press network → Modify
2. Advanced → IP settings → Static
3. DNS 1: {host_ip}</pre>
  </details>
  <details>
    <summary>iOS</summary>
    <pre>1. Settings → WiFi → ℹ → Configure DNS → Manual
2. Add Server: {host_ip}</pre>
  </details>
</div>
"""


class _Handler(BaseHTTPRequestHandler):
    # Injected by LandingServer
    get_apps: Callable = lambda: []
    get_host_ip: Callable = lambda: "127.0.0.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return

        apps    = self.get_apps()
        host_ip = self.get_host_ip()

        # Apps section
        if apps:
            cards = ""
            for app in apps:
                status  = app.get("status", "stopped")
                badge   = f'<span class="badge {status}">{status.upper()}</span>'
                domain  = app.get("domain", "")
                cards += f"""
                <div class="app-card">
                  <div class="app-name">{app.get("display_name", app["id"])}</div>
                  <div class="app-domain">
                    <a href="https://{domain}" target="_blank">{domain}</a>
                  </div>
                  {badge}
                </div>"""
            apps_html = f'<div class="apps-grid">{cards}</div>'
        else:
            apps_html = '<div class="empty">No apps deployed yet. Use PGOps to deploy a Laravel app.</div>'

        setup = _SETUP_HTML.replace("{host_ip}", host_ip)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PGOps — Local Server</title>
  {_STYLE}
</head>
<body>
  <div class="header">
    <div class="logo">PG</div>
    <div>
      <h1>PGOps Local Server</h1>
      <div class="sub">pgops.test — your local app platform</div>
    </div>
  </div>
  <div class="content">
    <h2>Running Apps</h2>
    {apps_html}
    <h2>Device Setup</h2>
    {setup}
  </div>
  <footer>PGOps — Portable PostgreSQL + App Platform · pgops.test</footer>
</body>
</html>"""

        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


class LandingServer:
    """
    Serves the pgops.test root page on LANDING_PORT (8080).
    Caddy proxies pgops.test → here.
    """

    def __init__(self, get_apps: Callable, get_host_ip: Callable, log_fn=None, port: int = LANDING_PORT):
        self._get_apps    = get_apps
        self._get_host_ip = get_host_ip
        self._log         = log_fn or print
        self._port        = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> tuple[bool, str]:
        if self._server:
            return True, "Landing server already running."

        class _H(_Handler):
            get_apps    = self._get_apps
            get_host_ip = self._get_host_ip

        port = self._port
        try:
            self._server = HTTPServer((LANDING_HOST, port), _H)
        except OSError as exc:
            return False, f"Landing server bind failed on port {port}: {exc}"

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="PGOps-Landing",
        )
        self._thread.start()
        msg = f"[Landing] Server running on {LANDING_HOST}:{port}"
        self._log(msg)
        return True, msg

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        self._log("[Landing] Server stopped.")

    def is_running(self) -> bool:
        return self._server is not None
