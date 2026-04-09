"""
dns_server.py
Pure-Python DNS server for PGOps.
Resolves *.pgops.test → current LAN IP of the PGOps host.
All other queries are forwarded to upstream DNS (8.8.8.8).

Port Strategy:
  - Tries port 53 first (needs admin/root)
  - Falls back to port 5353 as an alternative mDNS port
  - Also offers hosts-file injection as a zero-config alternative
    for the local machine (no admin needed for hosts file on Windows
    if running as admin, or using sudo on macOS/Linux)

Requires: dnslib  (pip install dnslib)
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
    domains = ["pgops.test"] + (app_domains or [])
    lines = [HOSTS_MARKER_START]
    for domain in domains:
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
    """Remove everything between PGOps markers."""
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
            if "pgops.test" in line and not line.strip().startswith("#"):
                parts = line.split()
                if parts:
                    return parts[0]
    except Exception:
        pass
    return None


# ── DNS Resolver ──────────────────────────────────────────────────────────────

class _PGOpsResolver:
    """
    Answers *.pgops.test and pgops.test with the host IP.
    All other queries are forwarded to an upstream resolver.
    """

    UPSTREAM      = "8.8.8.8"
    UPSTREAM_PORT = 53
    TIMEOUT       = 3.0

    def __init__(self, host_ip: str):
        self.host_ip = host_ip

    def resolve(self, request, handler):
        try:
            from dnslib import RR, QTYPE, A, DNSRecord
        except ImportError:
            return request.reply()

        reply = request.reply()
        qname = str(request.q.qname).rstrip(".")

        if qname == "pgops.test" or qname.endswith(".pgops.test"):
            reply.add_answer(
                RR(
                    rname=request.q.qname,
                    rtype=QTYPE.A,
                    rdata=A(self.host_ip),
                    ttl=60,
                )
            )
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


# ── DNS Server Thread ─────────────────────────────────────────────────────────

class DNSServerThread:
    """
    Wraps dnslib.server.DNSServer in a daemon thread.
    Tries port 53 (admin) then 5353.
    Also manages hosts file injection as a reliable fallback.
    """

    DEFAULT_PORT  = 53
    FALLBACK_PORT = 5353

    def __init__(self, host_ip: str, log_fn=None):
        self.host_ip   = host_ip
        self._log      = log_fn or print
        self._server   = None
        self._thread: Optional[threading.Thread] = None
        self._running  = False
        self.port      = self.DEFAULT_PORT
        self._resolver = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, prefer_port: int = 53) -> tuple[bool, str]:
        if self._running:
            return True, "DNS server already running."

        try:
            from dnslib.server import DNSServer
        except ImportError:
            return False, "dnslib not installed. Run: pip install dnslib"

        self._resolver = _PGOpsResolver(self.host_ip)

        for port in (prefer_port, self.FALLBACK_PORT):
            try:
                server = DNSServer(self._resolver, port=port, address="0.0.0.0")
                self._server = server
                self.port = port
                break
            except (PermissionError, OSError):
                if port == self.FALLBACK_PORT:
                    # Both ports failed — report it but don't error out
                    # hosts file injection can still work
                    return False, (
                        f"Cannot bind DNS to port {prefer_port} or {self.FALLBACK_PORT}.\n"
                        "Run PGOps as Administrator (Windows) or sudo (macOS/Linux) "
                        "for port 53, or use hosts file injection instead."
                    )
                continue

        self._thread = threading.Thread(
            target=self._server.start, daemon=True, name="PGOps-DNS"
        )
        self._thread.start()
        self._running = True

        qualifier = "" if self.port == 53 else f" (fallback port {self.port})"
        msg = (
            f"[DNS] Server running on 0.0.0.0:{self.port}{qualifier}. "
            f"Resolving *.pgops.test → {self.host_ip}"
        )
        self._log(msg)
        return True, msg

    def stop(self) -> tuple[bool, str]:
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
        """Live-update the resolved IP without restarting."""
        self.host_ip = new_ip
        if self._resolver:
            self._resolver.host_ip = new_ip
        self._log(f"[DNS] IP updated → {new_ip}")

    def is_running(self) -> bool:
        return self._running

    def status_str(self) -> str:
        if not self._running:
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

def test_resolution(hostname: str = "pgops.test", timeout: float = 3.0) -> tuple[bool, str]:
    """Test whether pgops.test resolves correctly on this machine."""
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return True, f"{hostname} → {ip} ✓"
    except Exception as exc:
        return False, f"Cannot resolve {hostname}: {exc}"


def get_client_setup_instructions(host_ip: str) -> dict[str, str]:
    """Per-platform DNS configuration instructions."""
    return {
        "Windows": (
            f"Option A — Hosts file (easiest, local machine only):\n"
            f"  Click 'Inject Hosts File' in PGOps (requires Admin).\n\n"
            f"Option B — DNS server (all LAN devices):\n"
            f"1. Settings → Network & Internet → Change adapter options\n"
            f"2. Right-click your adapter → Properties\n"
            f"3. Internet Protocol Version 4 → Properties\n"
            f"4. Use this DNS server: {host_ip}\n"
            f"5. Click OK → OK\n\n"
            f"Option C — PowerShell (current session):\n"
            f"  Set-DnsClientServerAddress -InterfaceAlias 'Wi-Fi' "
            f"-ServerAddresses {host_ip}"
        ),
        "macOS": (
            f"Option A — Hosts file (easiest, local machine only):\n"
            f"  Click 'Inject Hosts File' in PGOps.\n\n"
            f"Option B — DNS server (all LAN devices):\n"
            f"1. System Settings → Network → select network → Details\n"
            f"2. DNS tab → + → enter {host_ip}\n"
            f"3. Click OK\n\n"
            f"Option C — Terminal:\n"
            f"  networksetup -setdnsservers Wi-Fi {host_ip}"
        ),
        "Android": (
            f"1. Settings → Wi-Fi → long-press your network → Modify\n"
            f"2. Advanced options → IP settings → Static\n"
            f"3. DNS 1: {host_ip}\n"
            f"4. Save\n\n"
            f"(Android 9+): Settings → Network & Internet → Private DNS\n"
            f"→ Off (then use static IP method above)"
        ),
        "iOS": (
            f"1. Settings → Wi-Fi → tap ℹ next to your network\n"
            f"2. Configure DNS → Manual\n"
            f"3. Add Server: {host_ip}\n"
            f"4. Remove existing servers\n"
            f"5. Tap Save"
        ),
        "Linux": (
            f"Option A — Hosts file:\n"
            f"  sudo sh -c 'echo \"{host_ip} pgops.test\" >> /etc/hosts'\n\n"
            f"Option B — NetworkManager:\n"
            f"  nmcli con mod 'Your-Connection' ipv4.dns '{host_ip}'\n"
            f"  nmcli con up 'Your-Connection'\n\n"
            f"Option C — systemd-resolved:\n"
            f"  sudo resolvectl dns <interface> {host_ip}"
        ),
    }
