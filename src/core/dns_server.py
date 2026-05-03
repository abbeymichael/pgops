"""
dns_server.py
Hosts-file helpers for PGOps.

The DNS server (dnslib) has been replaced by mDNS (see mdns_server.py).
This module now only contains the hosts-file injection utilities that serve
as a local-machine fallback when mDNS is unavailable or blocked.

Public API
----------
    inject_hosts(host_ip, app_domains)  -> (bool, str)
    remove_hosts()                      -> (bool, str)
    is_hosts_injected()                 -> bool
    get_hosts_current_ip()              -> Optional[str]
    get_hosts_file()                    -> Path
    get_client_setup_instructions()     -> dict[str, str]   (kept for compat)
    test_resolution()                   -> (bool, str)      (kept for compat)
"""

import re
import socket
from pathlib import Path
from typing import Optional


# ── Markers ───────────────────────────────────────────────────────────────────

HOSTS_MARKER_START = "# PGOps BEGIN"
HOSTS_MARKER_END   = "# PGOps END"


# ── Path helper ───────────────────────────────────────────────────────────────

def get_hosts_file() -> Path:
    import platform
    if platform.system() == "Windows":
        return Path(r"C:\Windows\System32\drivers\etc\hosts")
    return Path("/etc/hosts")


# ── Hosts-file content builder ────────────────────────────────────────────────

def get_hosts_entries(host_ip: str, app_domains: list = None) -> str:
    """Build the hosts file block for pgops.local and all app subdomains."""
    base_domains = [
        "pgops.local",
        "www.pgops.local",
        "pgadmin.pgops.local",
        "storage.pgops.local",
        "storage-console.pgops.local",
    ]
    extra = app_domains or []
    all_domains = base_domains + [d for d in extra if d not in base_domains]

    lines = [HOSTS_MARKER_START]
    for domain in sorted(set(all_domains)):
        lines.append(f"{host_ip}  {domain}")
    lines.append(HOSTS_MARKER_END)
    return "\n".join(lines) + "\n"


# ── Injection ─────────────────────────────────────────────────────────────────

def inject_hosts(host_ip: str, app_domains: list = None) -> tuple[bool, str]:
    """
    Write pgops.local entries into the system hosts file.
    Requires Administrator (Windows) or sudo (macOS/Linux).
    """
    hosts = get_hosts_file()
    try:
        content = hosts.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return False, f"Cannot read hosts file: {exc}"

    # Remove any existing PGOps block
    content = _remove_pgops_block(content)

    # Append new block
    new_block = get_hosts_entries(host_ip, app_domains)
    content = content.rstrip("\n") + "\n\n" + new_block

    try:
        hosts.write_text(content, encoding="utf-8")
        domains = ["pgops.local"] + (app_domains or [])
        return True, f"Hosts file updated: {', '.join(domains[:4])} → {host_ip}"
    except PermissionError:
        return False, (
            "Permission denied writing hosts file.\n\n"
            "Windows: Run PGOps as Administrator.\n"
            "macOS/Linux: Run with sudo."
        )
    except Exception as exc:
        return False, f"Failed to update hosts file: {exc}"


def remove_hosts() -> tuple[bool, str]:
    """Remove PGOps entries from the system hosts file."""
    hosts = get_hosts_file()
    try:
        content = hosts.read_text(encoding="utf-8", errors="replace")
        new_content = _remove_pgops_block(content)
        hosts.write_text(new_content, encoding="utf-8")
        return True, "PGOps entries removed from hosts file."
    except PermissionError:
        return False, "Permission denied. Run as Administrator/sudo."
    except Exception as exc:
        return False, f"Failed to update hosts file: {exc}"


def _remove_pgops_block(content: str) -> str:
    """Remove everything between PGOps markers (inclusive)."""
    pattern = re.compile(
        r"\n*" + re.escape(HOSTS_MARKER_START) + r".*?" + re.escape(HOSTS_MARKER_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


# ── Status helpers ────────────────────────────────────────────────────────────

def is_hosts_injected() -> bool:
    """Check if a PGOps block exists in the system hosts file."""
    try:
        content = get_hosts_file().read_text(encoding="utf-8", errors="replace")
        return HOSTS_MARKER_START in content
    except Exception:
        return False


def get_hosts_current_ip() -> Optional[str]:
    """Return the IP currently set for pgops.local in the hosts file."""
    try:
        content = get_hosts_file().read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            stripped = line.strip()
            if "pgops.local" in stripped and not stripped.startswith("#"):
                parts = stripped.split()
                if len(parts) >= 2:
                    return parts[0]
    except Exception:
        pass
    return None


# ── Compatibility shims ───────────────────────────────────────────────────────
# These were on DNSServerThread / dns_server previously.
# Kept so existing callers that imported them directly don't break.

def test_resolution(hostname: str = "pgops.local") -> tuple[bool, str]:
    """Test whether pgops.local resolves via the system resolver."""
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return True, f"{hostname} → {ip}"
    except Exception as exc:
        return False, f"Cannot resolve {hostname}: {exc}"


def get_client_setup_instructions(host_ip: str = "", dns_port: int = 5353) -> dict:
    """
    Kept for backwards compatibility — delegates to mdns_server.
    host_ip / dns_port params are ignored (mDNS needs no DNS server config).
    """
    from core.mdns_server import get_client_setup_instructions as _mk
    return _mk()