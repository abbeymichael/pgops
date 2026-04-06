"""
mdns.py
Broadcasts this machine as 'pgops.local' on the LAN using mDNS (Zeroconf).
Any device on the same network resolves pgops.local to the current host IP.
No DNS server, no router config — works on LAN and Windows hotspot automatically.
"""

import socket
import platform
import threading
import logging
from typing import Optional

# Suppress zeroconf's verbose logging
logging.getLogger("zeroconf").setLevel(logging.ERROR)


class MDNSBroadcaster:
    """
    Registers this machine as 'pgops.local' on the local network.
    Also registers a PostgreSQL service record so tools like pgAdmin
    can discover the server automatically via service browsing.
    """

    SERVICE_TYPE = "_postgresql._tcp.local."
    SERVICE_NAME = "PGOps._postgresql._tcp.local."
    HOSTNAME     = "pgops"           # resolves as pgops.local

    def __init__(self, port: int = 5432, log_fn=None):
        self.port    = port
        self._log    = log_fn or print
        self._zc     = None
        self._info   = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        """Start broadcasting pgops.local. Returns (ok, message)."""
        if self._running:
            return True, "mDNS already running."
        try:
            from zeroconf import Zeroconf, ServiceInfo
            import socket

            ip = self._get_best_ip()
            ip_bytes = socket.inet_aton(ip)

            self._info = ServiceInfo(
                type_=self.SERVICE_TYPE,
                name=self.SERVICE_NAME,
                addresses=[ip_bytes],
                port=self.port,
                properties={
                    b"host":    self.HOSTNAME.encode(),
                    b"version": b"1.0",
                    b"app":     b"PGOps",
                },
                server=f"{self.HOSTNAME}.local.",
            )

            self._zc = Zeroconf()
            self._zc.register_service(self._info)
            self._running = True
            self._log(f"[mDNS] Broadcasting as pgops.local → {ip}:{self.port}")
            return True, f"pgops.local is active → {ip}"

        except ImportError:
            return False, (
                "zeroconf package not installed.\n"
                "Run: pip install zeroconf"
            )
        except Exception as e:
            return False, f"mDNS start failed: {e}"

    def stop(self) -> tuple[bool, str]:
        """Stop broadcasting."""
        if not self._running:
            return True, "mDNS not running."
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
                self._zc.close()
            self._zc = None
            self._info = None
            self._running = False
            self._log("[mDNS] Stopped.")
            return True, "mDNS stopped."
        except Exception as e:
            return False, f"mDNS stop error: {e}"

    def restart(self) -> tuple[bool, str]:
        """Restart — call this when IP changes."""
        self.stop()
        return self.start()

    def is_running(self) -> bool:
        return self._running

    def current_hostname(self) -> str:
        return f"{self.HOSTNAME}.local"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_best_ip(self) -> str:
        """Get the best non-loopback IP to broadcast."""
        try:
            from core.network_info import get_all_interfaces, get_best_ip
            ifaces = get_all_interfaces()
            return get_best_ip(ifaces)
        except Exception:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return "127.0.0.1"


def verify_mdns_resolution(hostname: str = "pgops.local", timeout: float = 3.0) -> tuple[bool, str]:
    """
    Try to resolve pgops.local from this machine.
    Useful for testing that mDNS is working.
    """
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return True, f"{hostname} resolves to {ip}"
    except Exception as e:
        return False, f"Could not resolve {hostname}: {e}"


def get_mdns_instructions() -> dict:
    """
    Returns per-OS instructions for connecting to pgops.local.
    """
    return {
        "Windows": (
            "Windows 10/11 supports mDNS natively.\n"
            "Connect using:  pgops.local  as the host.\n\n"
            "If it doesn't resolve, install Bonjour:\n"
            "https://support.apple.com/kb/DL999"
        ),
        "macOS": (
            "macOS supports mDNS natively — no setup needed.\n"
            "Connect using:  pgops.local  as the host."
        ),
        "Linux": (
            "Install avahi-daemon:\n"
            "  sudo apt install avahi-daemon   (Ubuntu/Debian)\n"
            "  sudo dnf install avahi          (Fedora)\n"
            "Then connect using:  pgops.local"
        ),
        "Android": (
            "Most Android apps resolve .local hostnames automatically.\n"
            "If not, use the IP address shown in PGOps instead."
        ),
        "iOS": (
            "iOS supports mDNS natively.\n"
            "Connect using:  pgops.local  as the host."
        ),
    }
