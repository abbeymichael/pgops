"""
dns_server.py
Pure-Python DNS server for PGOps.
Resolves *.pgops.test → current LAN IP of the PGOps host.
All other queries are forwarded to upstream DNS (8.8.8.8).

FIXES:
- resolve() now returns reply correctly; dnslib BaseResolver subclass fixed
- inject_hosts() injects all app subdomains including wildcards
- DNSServer start() is non-blocking — runs server.start_thread() correctly
- update_ip() is thread-safe with a lock
- hosts file injection preserves existing non-PGOps entries correctly
- test_resolution() forces resolution through our DNS port when running
- get_client_setup_instructions() includes port-aware instructions
"""

import os
import socket
import platform
import threading
import logging
import subprocess
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ── Hosts file helpers ────────────────────────────────────────────────────────

HOSTS_MARKER_START = "# PGOps BEGIN"
HOSTS_MARKER_END   = "# PGOps END"


def get_hosts_file() -> Path:
    if platform.system() == "Windows":
        return Path(r"C:\Windows\System32\drivers\etc\hosts")
    return Path("/etc/hosts")


def get_hosts_entries(host_ip: str, app_domains: list[str] = None) -> str:
    """Build the hosts file block for pgops.test and all app subdomains."""
    domains = ["pgops.test", "www.pgops.test"] + (app_domains or [])
    lines = [HOSTS_MARKER_START]
    for domain in sorted(set(domains)):
        lines.append(f"{host_ip}  {domain}")
    lines.append(HOSTS_MARKER_END)
    return "\n".join(lines) + "\n"


def inject_hosts(host_ip: str, app_domains: list[str] = None) -> tuple[bool, str]:
    """
    Write pgops.test entries into the system hosts file.
    Requires admin/root privileges on most systems.
    """
    hosts = get_hosts_file()
    try:
        content = hosts.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"Cannot read hosts file: {e}"

    # Remove any existing PGOps block
    content = _remove_pgops_block(content)

    # Append new block
    new_block = get_hosts_entries(host_ip, app_domains)
    content = content.rstrip("\n") + "\n\n" + new_block

    try:
        hosts.write_text(content, encoding="utf-8")
        domains = ["pgops.test"] + (app_domains or [])
        return True, f"Hosts file updated: {', '.join(domains)} → {host_ip}"
    except PermissionError:
        return False, (
            "Permission denied writing hosts file.\n\n"
            "Windows: Run PGOps as Administrator.\n"
            "macOS/Linux: Run with sudo."
        )
    except Exception as e:
        return False, f"Failed to update hosts file: {e}"


def remove_hosts(host_ip: str = None) -> tuple[bool, str]:
    """Remove PGOps entries from the hosts file."""
    hosts = get_hosts_file()
    try:
        content = hosts.read_text(encoding="utf-8", errors="replace")
        new_content = _remove_pgops_block(content)
        hosts.write_text(new_content, encoding="utf-8")
        return True, "PGOps entries removed from hosts file."
    except PermissionError:
        return False, "Permission denied. Run as Administrator/sudo."
    except Exception as e:
        return False, f"Failed to update hosts file: {e}"


def _remove_pgops_block(content: str) -> str:
    """Remove everything between PGOps markers (inclusive)."""
    pattern = re.compile(
        r"\n*" + re.escape(HOSTS_MARKER_START) + r".*?" + re.escape(HOSTS_MARKER_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def is_hosts_injected() -> bool:
    """Check if PGOps block exists in hosts file."""
    try:
        content = get_hosts_file().read_text(encoding="utf-8", errors="replace")
        return HOSTS_MARKER_START in content
    except Exception:
        return False


def get_hosts_current_ip() -> Optional[str]:
    """Get the IP currently set in the hosts file for pgops.test."""
    try:
        content = get_hosts_file().read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            stripped = line.strip()
            if "pgops.test" in stripped and not stripped.startswith("#"):
                parts = stripped.split()
                if len(parts) >= 2:
                    return parts[0]
    except Exception:
        pass
    return None


# ── DNS Resolver ──────────────────────────────────────────────────────────────

class _PGOpsResolver:
    """
    Answers *.pgops.test and pgops.test with the host IP.
    All other queries are forwarded to an upstream resolver.
    Implements the dnslib BaseResolver interface correctly.
    """

    UPSTREAM      = "8.8.8.8"
    UPSTREAM_PORT = 53
    TIMEOUT       = 3.0

    def __init__(self, host_ip: str):
        self.host_ip = host_ip
        self._lock = threading.Lock()

    def set_ip(self, ip: str):
        with self._lock:
            self.host_ip = ip

    def get_ip(self) -> str:
        with self._lock:
            return self.host_ip

    # dnslib calls this method
    def resolve(self, request, handler):
        try:
            from dnslib import RR, QTYPE, A
        except ImportError:
            return request.reply()

        reply = request.reply()
        qname = str(request.q.qname).rstrip(".")
        host_ip = self.get_ip()

        if qname == "pgops.test" or qname.endswith(".pgops.test"):
            reply.add_answer(
                RR(
                    rname=request.q.qname,
                    rtype=QTYPE.A,
                    rdata=A(host_ip),
                    ttl=60,
                )
            )
        else:
            # Forward to upstream
            try:
                from dnslib import DNSRecord
                upstream_req = DNSRecord.question(qname)
                raw = upstream_req.send(
                    self.UPSTREAM, self.UPSTREAM_PORT, timeout=self.TIMEOUT
                )
                upstream_reply = DNSRecord.parse(raw)
                # Copy answers from upstream into our reply
                for rr in upstream_reply.rr:
                    reply.add_answer(rr)
            except Exception as exc:
                log.debug(f"[DNS] upstream forward failed for {qname}: {exc}")

        return reply


# ── DNS Server Thread ─────────────────────────────────────────────────────────

class DNSServerThread:
    """
    Wraps dnslib.server.DNSServer in a background thread (non-blocking).
    Tries port 53 (admin) then 5353.
    Also manages hosts file injection as a reliable fallback.
    """

    DEFAULT_PORT  = 53
    FALLBACK_PORT = 5353

    def __init__(self, host_ip: str, log_fn=None):
        self.host_ip   = host_ip
        self._log      = log_fn or print
        self._server   = None
        self._running  = False
        self.port      = self.DEFAULT_PORT
        self._resolver: Optional[_PGOpsResolver] = None
        self._lock     = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, prefer_port: int = 53) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return True, "DNS server already running."

        try:
            from dnslib.server import DNSServer, DNSLogger
        except ImportError:
            return False, "dnslib not installed. Run: pip install dnslib"

        self._resolver = _PGOpsResolver(self.host_ip)

        # Suppress dnslib's noisy logging
        class _SilentLogger(DNSLogger):
            def log_prefix(self, handler): return ""
            def log_recv(self, *a, **k): pass
            def log_send(self, *a, **k): pass
            def log_request(self, *a, **k): pass
            def log_reply(self, *a, **k): pass
            def log_truncated(self, *a, **k): pass
            def log_error(self, *a, **k): pass
            def log_data(self, *a, **k): pass

        server = None
        bound_port = None
        for port in (prefer_port, self.FALLBACK_PORT):
            try:
                s = DNSServer(
                    self._resolver,
                    port=port,
                    address="0.0.0.0",
                    logger=_SilentLogger(),
                )
                server = s
                bound_port = port
                break
            except (PermissionError, OSError) as e:
                self._log(f"[DNS] Cannot bind port {port}: {e}")
                if port == self.FALLBACK_PORT:
                    return False, (
                        f"Cannot bind DNS to port {prefer_port} or {self.FALLBACK_PORT}.\n"
                        "Run PGOps as Administrator (Windows) or sudo (macOS/Linux) "
                        "for port 53, or use hosts file injection instead."
                    )
                continue

        if server is None:
            return False, "Failed to create DNS server."

        # start_thread() is non-blocking — it starts the server in a daemon thread
        try:
            server.start_thread()
        except Exception as e:
            return False, f"DNS server start failed: {e}"

        with self._lock:
            self._server = server
            self.port = bound_port
            self._running = True

        qualifier = "" if bound_port == 53 else f" (port {bound_port})"
        msg = (
            f"[DNS] Server running on 0.0.0.0:{bound_port}{qualifier}. "
            f"Resolving *.pgops.test → {self.host_ip}"
        )
        self._log(msg)
        return True, msg

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self._running:
                return True, "DNS server not running."
            server = self._server
            self._server = None
            self._running = False

        try:
            if server:
                server.stop()
        except Exception as exc:
            self._log(f"[DNS] Stop error: {exc}")

        self._log("[DNS] Server stopped.")
        return True, "DNS server stopped."

    def update_ip(self, new_ip: str):
        """Live-update the resolved IP without restarting."""
        self.host_ip = new_ip
        if self._resolver:
            self._resolver.set_ip(new_ip)
        self._log(f"[DNS] IP updated → {new_ip}")

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def status_str(self) -> str:
        if not self.is_running():
            return "Not running"
        return f"Running on port {self.port} — *.pgops.test → {self.host_ip}"

    # ── Hosts file helpers (delegated) ────────────────────────────────────────

    def inject_hosts(self, app_domains: list[str] = None) -> tuple[bool, str]:
        return inject_hosts(self.host_ip, app_domains)

    def remove_hosts(self) -> tuple[bool, str]:
        return remove_hosts()

    def is_hosts_injected(self) -> bool:
        return is_hosts_injected()

    def get_hosts_ip(self) -> Optional[str]:
        return get_hosts_current_ip()


# ── Resolution test ────────────────────────────────────────────────────────────

def test_resolution(
    hostname: str = "pgops.test",
    dns_port: int = 0,
) -> tuple[bool, str]:
    """
    Test whether pgops.test resolves correctly.
    If dns_port > 0, queries our local DNS server directly.
    Otherwise uses the system resolver.
    """
    if dns_port > 0:
        try:
            from dnslib import DNSRecord, QTYPE
            q = DNSRecord.question(hostname, qtype=QTYPE.A)
            raw = q.send("127.0.0.1", dns_port, timeout=3.0)
            reply = DNSRecord.parse(raw)
            if reply.rr:
                ip = str(reply.rr[0].rdata)
                return True, f"{hostname} → {ip} (via local DNS)"
            return False, f"No answer from local DNS for {hostname}"
        except Exception as exc:
            return False, f"Local DNS query failed: {exc}"

    # System resolver fallback
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return True, f"{hostname} → {ip}"
    except Exception as exc:
        return False, f"Cannot resolve {hostname}: {exc}"


def get_client_setup_instructions(host_ip: str, dns_port: int = 53) -> dict[str, str]:
    """Per-platform DNS configuration instructions."""
    port_note = "" if dns_port == 53 else f"\n  (Note: DNS is on port {dns_port}, not 53 — use hosts file method instead)"

    return {
        "Windows": (
            f"Option A — Hosts file (easiest, local machine only):\n"
            f"  Click 'Inject Hosts File' in PGOps (requires Admin).\n\n"
            f"Option B — DNS server (all LAN devices):{port_note}\n"
            f"1. Settings → Network & Internet → Change adapter options\n"
            f"2. Right-click your adapter → Properties\n"
            f"3. Internet Protocol Version 4 → Properties\n"
            f"4. Use this DNS server: {host_ip}\n"
            f"5. Click OK → OK"
        ),
        "macOS": (
            f"Option A — Hosts file (easiest, local machine only):\n"
            f"  Click 'Inject Hosts File' in PGOps.\n\n"
            f"Option B — DNS server:{port_note}\n"
            f"1. System Settings → Network → select network → Details\n"
            f"2. DNS tab → + → enter {host_ip}\n"
            f"3. Click OK\n\n"
            f"Terminal: networksetup -setdnsservers Wi-Fi {host_ip}"
        ),
        "Android": (
            f"1. Settings → Wi-Fi → long-press your network → Modify\n"
            f"2. Advanced options → IP settings → Static\n"
            f"3. DNS 1: {host_ip}\n"
            f"4. Save"
        ),
        "iOS": (
            f"1. Settings → Wi-Fi → tap ℹ next to your network\n"
            f"2. Configure DNS → Manual\n"
            f"3. Add Server: {host_ip}\n"
            f"4. Remove existing servers\n"
            f"5. Tap Save"
        ),
        "Linux": (
            f"Hosts file (fastest):\n"
            f"  sudo sh -c 'echo \"{host_ip} pgops.test\" >> /etc/hosts'\n\n"
            f"NetworkManager:\n"
            f"  nmcli con mod 'YourConnection' ipv4.dns '{host_ip}'\n"
            f"  nmcli con up 'YourConnection'"
        ),
    }
