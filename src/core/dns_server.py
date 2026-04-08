"""
dns_server.py
Pure-Python DNS server for PGOps.
Resolves *.pgops.local → current LAN IP of the PGOps host.
All other queries are forwarded to upstream DNS (8.8.8.8).

Requires: dnslib  (pip install dnslib)
"""

import socket
import threading
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ── Resolver ──────────────────────────────────────────────────────────────────

class _PGOpsResolver:
    """
    Answers *.pgops.local and pgops.local with the host IP.
    All other queries are forwarded to an upstream resolver.
    """

    UPSTREAM      = "8.8.8.8"
    UPSTREAM_PORT = 53
    TIMEOUT       = 3.0

    def __init__(self, host_ip: str):
        self.host_ip = host_ip  # kept mutable so update_ip() works live

    def resolve(self, request, handler):
        try:
            from dnslib import RR, QTYPE, A, DNSRecord
        except ImportError:
            return request.reply()

        reply = request.reply()
        qname = str(request.q.qname).rstrip(".")

        if qname == "pgops.local" or qname.endswith(".pgops.local"):
            reply.add_answer(
                RR(
                    rname=request.q.qname,
                    rtype=QTYPE.A,
                    rdata=A(self.host_ip),
                    ttl=60,
                )
            )
            log.debug(f"[DNS] {qname} → {self.host_ip}")
        else:
            # Forward to upstream
            try:
                upstream_req = DNSRecord.question(qname)
                raw = upstream_req.send(
                    self.UPSTREAM, self.UPSTREAM_PORT, timeout=self.TIMEOUT
                )
                reply = DNSRecord.parse(raw)
            except Exception as exc:
                log.debug(f"[DNS] upstream forward failed for {qname}: {exc}")

        return reply


# ── Server thread ─────────────────────────────────────────────────────────────

class DNSServerThread:
    """
    Wraps dnslib.server.DNSServer in a daemon thread.
    Call start() once; update_ip() whenever the LAN IP changes; stop() on quit.
    """

    DEFAULT_PORT    = 53
    FALLBACK_PORT   = 5353   # used when 53 is unavailable (no admin rights)

    def __init__(self, host_ip: str, log_fn=None):
        self.host_ip  = host_ip
        self._log     = log_fn or print
        self._server  = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.port     = self.DEFAULT_PORT

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self, prefer_port: int = 53) -> tuple[bool, str]:
        """Start DNS server. Returns (ok, message)."""
        if self._running:
            return True, "DNS server already running."

        try:
            from dnslib.server import DNSServer
        except ImportError:
            return False, (
                "dnslib not installed.\n"
                "Run: pip install dnslib"
            )

        resolver = _PGOpsResolver(self.host_ip)

        # Try the preferred port; fall back to 5353 if we lack privileges
        for port in (prefer_port, self.FALLBACK_PORT):
            try:
                server = DNSServer(resolver, port=port, address="0.0.0.0")
                self._server  = server
                self._resolver = resolver
                self.port     = port
                break
            except PermissionError:
                if port == self.FALLBACK_PORT:
                    return False, (
                        f"Cannot bind to port {prefer_port} or {self.FALLBACK_PORT}.\n"
                        "Run PGOps as Administrator (Windows) or with sudo (macOS) "
                        "to enable DNS on port 53."
                    )
                # Try fallback
                continue
            except OSError as exc:
                if port == self.FALLBACK_PORT:
                    return False, f"DNS server bind error: {exc}"
                continue

        self._thread = threading.Thread(
            target=self._server.start, daemon=True, name="PGOps-DNS"
        )
        self._thread.start()
        self._running = True

        qualifier = "" if self.port == 53 else f" (fallback port {self.port})"
        msg = (
            f"[DNS] Server running on 0.0.0.0:{self.port}{qualifier}. "
            f"Resolving *.pgops.local → {self.host_ip}"
        )
        self._log(msg)
        return True, msg

    def stop(self) -> tuple[bool, str]:
        """Stop the DNS server."""
        if not self._running:
            return True, "DNS server not running."
        try:
            if self._server:
                self._server.stop()
        except Exception as exc:
            self._log(f"[DNS] Stop error: {exc}")
        self._server  = None
        self._running = False
        self._log("[DNS] Server stopped.")
        return True, "DNS server stopped."

    def update_ip(self, new_ip: str):
        """Live-update the IP without restarting."""
        self.host_ip = new_ip
        if self._running and hasattr(self, "_resolver"):
            self._resolver.host_ip = new_ip
            self._log(f"[DNS] IP updated → {new_ip}")

    def is_running(self) -> bool:
        return self._running

    def status_str(self) -> str:
        if not self._running:
            return "Not running"
        return f"Running on port {self.port} — *.pgops.local → {self.host_ip}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def test_resolution(hostname: str = "pgops.local", timeout: float = 3.0) -> tuple[bool, str]:
    """Resolve hostname using the system resolver (tests end-to-end)."""
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return True, f"{hostname} resolves to {ip}"
    except Exception as exc:
        return False, f"Could not resolve {hostname}: {exc}"


def get_client_setup_instructions(host_ip: str) -> dict[str, str]:
    """
    Returns per-platform DNS configuration instructions as plain text.
    Used by the DNS tab UI.
    """
    return {
        "Windows": (
            f"1. Open Settings → Network & Internet → Change adapter options\n"
            f"2. Right-click your network adapter → Properties\n"
            f"3. Select 'Internet Protocol Version 4 (TCP/IPv4)' → Properties\n"
            f"4. Select 'Use the following DNS server addresses'\n"
            f"5. Preferred DNS server: {host_ip}\n"
            f"6. Click OK → OK"
        ),
        "macOS": (
            f"1. System Settings → Network → select your network → Details\n"
            f"2. Click the DNS tab\n"
            f"3. Click + below the DNS Servers list\n"
            f"4. Enter: {host_ip}\n"
            f"5. Click OK"
        ),
        "Android": (
            f"1. Settings → WiFi → long-press your network → Modify network\n"
            f"2. Advanced options → IP settings → Static\n"
            f"3. DNS 1: {host_ip}\n"
            f"4. Save"
        ),
        "iOS": (
            f"1. Settings → WiFi → tap ℹ next to your network\n"
            f"2. Configure DNS → Manual\n"
            f"3. Tap 'Add Server' → enter {host_ip}\n"
            f"4. Remove any other DNS servers\n"
            f"5. Tap Save"
        ),
        "Linux": (
            f"# Temporary (current session only):\n"
            f"sudo resolvectl dns <interface> {host_ip}\n\n"
            f"# Permanent (NetworkManager):\n"
            f"nmcli con mod 'Your Connection' ipv4.dns '{host_ip}'\n"
            f"nmcli con up 'Your Connection'"
        ),
    }
