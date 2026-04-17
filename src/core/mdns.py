"""
mdns.py
Broadcasts this machine as 'pgops.test' on the LAN using mDNS (Zeroconf).

FIXES:
- ServiceInfo server= field now correctly ends with ".local." (required by zeroconf)
- stop() unregisters service before closing Zeroconf instance
- restart() is safe to call if not running
- start() is idempotent — returns True if already running
- _get_best_ip() has robust fallback chain
- Zeroconf instance stored safely with lock to prevent concurrent access
"""

import socket
import platform
import threading
import logging
from typing import Optional

logging.getLogger("zeroconf").setLevel(logging.ERROR)


class MDNSBroadcaster:
    """
    Registers this machine as 'pgops.test' on the local network.
    Also registers a PostgreSQL service record.
    """

    SERVICE_TYPE = "_postgresql._tcp.local."
    SERVICE_NAME = "PGOps._postgresql._tcp.local."
    HOSTNAME     = "pgops"   # → pgops.local. as the A record hostname

    def __init__(self, port: int = 5432, log_fn=None):
        self.port     = port
        self._log     = log_fn or print
        self._zc      = None
        self._info    = None
        self._running = False
        self._lock    = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return True, "mDNS already running."

        try:
            from zeroconf import Zeroconf, ServiceInfo

            ip = self._get_best_ip()
            ip_bytes = socket.inet_aton(ip)

            # server= must end with ".local." — this is the A record hostname
            # Zeroconf will register pgops.local → ip as an A record
            info = ServiceInfo(
                type_=self.SERVICE_TYPE,
                name=self.SERVICE_NAME,
                addresses=[ip_bytes],
                port=self.port,
                properties={
                    b"host":    self.HOSTNAME.encode(),
                    b"version": b"1.0",
                    b"app":     b"PGOps",
                },
                server=f"{self.HOSTNAME}.local.",  # trailing dot is required
            )

            zc = Zeroconf()
            zc.register_service(info)

            with self._lock:
                self._zc      = zc
                self._info    = info
                self._running = True

            self._log(f"[mDNS] Broadcasting as {self.HOSTNAME}.local → {ip}:{self.port}")
            return True, f"pgops.test active → {ip}"

        except ImportError:
            return False, (
                "zeroconf package not installed.\n"
                "Run: pip install zeroconf"
            )
        except Exception as e:
            return False, f"mDNS start failed: {e}"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self._running:
                return True, "mDNS not running."
            zc   = self._zc
            info = self._info
            self._zc      = None
            self._info    = None
            self._running = False

        try:
            if zc and info:
                zc.unregister_service(info)
            if zc:
                zc.close()
        except Exception as e:
            return False, f"mDNS stop error: {e}"

        self._log("[mDNS] Stopped.")
        return True, "mDNS stopped."

    def restart(self) -> tuple[bool, str]:
        """Restart — call this when IP changes."""
        self.stop()
        return self.start()

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def current_hostname(self) -> str:
        return f"{self.HOSTNAME}.local"

    # ── Internals ──────────────────────────────────────────────────────────────

    def _get_best_ip(self) -> str:
        """Get the best non-loopback IP to broadcast."""
        # Try network_info first (most accurate)
        try:
            from core.network_info import get_all_interfaces, get_best_ip
            ifaces = get_all_interfaces()
            ip = get_best_ip(ifaces)
            if ip and ip != "127.0.0.1":
                return ip
        except Exception:
            pass

        # UDP socket trick — works without sending any data
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and ip != "0.0.0.0":
                return ip
        except Exception:
            pass

        # Hostname resolution fallback
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and ip != "127.0.0.1":
                return ip
        except Exception:
            pass

        return "127.0.0.1"


def verify_mdns_resolution(
    hostname: str = "pgops.local", timeout: float = 3.0
) -> tuple[bool, str]:
    """Try to resolve pgops.local from this machine."""
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
        return True, f"{hostname} resolves to {ip}"
    except Exception as e:
        # Also try .test suffix
        try:
            ip2 = socket.getaddrinfo("pgops.test", None, socket.AF_INET)[0][4][0]
            return True, f"pgops.test resolves to {ip2}"
        except Exception:
            pass
        return False, f"Could not resolve {hostname}: {e}"


def get_mdns_instructions() -> dict:
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
