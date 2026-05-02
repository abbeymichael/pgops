"""
mdns_server.py
mDNS (Zeroconf/Bonjour) server for PGOps.

Registers pgops.local and every deployed app as <appname>.pgops.local so that
any device on the same WiFi/LAN can reach them with zero client configuration.
No admin privileges required.

Design
------
- pgops.local         → host LAN IP  (main landing page / PostgreSQL host)
- <app>.pgops.local   → host LAN IP  (each deployed app, routed by Caddy)

mDNS does NOT support wildcard records, so every app subdomain must be
registered explicitly via its own ServiceInfo entry.

Platform support
----------------
- Windows 10/11  — built-in mDNS stack (Bonjour-compatible via mDNS/DNS-SD)
- macOS / iOS    — native Bonjour, zero extra config
- Android 12+    — nsd_manager / mDNS in Android 12+; works on most LANs
- Linux          — avahi-daemon or systemd-resolved handles .local

Public API  (mirrors DNSServerThread shape so callers need minimal changes)
-----------
    server = MDNSServer(host_ip="192.168.1.5", log_fn=print)
    server.start()          -> (bool, str)
    server.stop()           -> (bool, str)
    server.is_running()     -> bool
    server.update_ip(ip)    -> None   (re-registers with new IP)
    server.register_app(app_id, domain)    -> None
    server.unregister_app(app_id)          -> None
    server.registered_apps()              -> list[str]  (app_ids)

Hosts-file helpers (kept for local-machine fallback) are imported from
dns_server.py which now only contains those functions.
"""

import socket
import threading
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── mDNS service type used for all PGOps entries ──────────────────────────────
# We use _pgops._tcp.local. as the service type so records are grouped
# together and don't pollute the _http._tcp. namespace.
_SERVICE_TYPE = "_pgops._tcp.local."


def _ip_to_bytes(ip: str) -> bytes:
    """Convert a dotted-decimal IPv4 string to 4 bytes."""
    return socket.inet_aton(ip)


def _make_service_info(name: str, host_ip: str, port: int = 80) -> "ServiceInfo":
    """
    Build a zeroconf ServiceInfo for a .local hostname.

    zeroconf registers:
      - An A record:   <name>.local → host_ip
      - An SRV record: <service-name>._pgops._tcp.local → <name>.local:port

    Parameters
    ----------
    name     : hostname WITHOUT the .local suffix  (e.g. "pgops" or "myapp.pgops")
    host_ip  : IPv4 address string
    port     : TCP port the service listens on (not critical for our use-case,
               but must be a valid int in [1, 65535])
    """
    from zeroconf import ServiceInfo

    # ServiceInfo.server must end with a trailing dot and .local.
    server_fqdn = f"{name}.local."

    # Service instance name must be unique within the type
    instance_name = f"{name}.{_SERVICE_TYPE}"

    return ServiceInfo(
        type_=_SERVICE_TYPE,
        name=instance_name,
        addresses=[_ip_to_bytes(host_ip)],
        port=port,
        properties={
            b"host": name.encode(),
            b"app":  b"PGOps",
        },
        server=server_fqdn,
    )


class MDNSServer:
    """
    Registers PGOps and its deployed apps on the LAN via mDNS.

    Thread-safety: all mutations go through self._lock.
    """

    # Port used in ServiceInfo records — must be non-zero but Caddy handles
    # actual HTTP/HTTPS routing, so the value here is informational only.
    _HTTP_PORT  = 80
    _HTTPS_PORT = 443

    def __init__(self, host_ip: str, log_fn=None):
        self.host_ip = host_ip
        self._log    = log_fn or print
        self._lock   = threading.Lock()

        # zeroconf instance and the ServiceInfo objects we have registered
        self._zc: Optional["Zeroconf"] = None
        self._infos: dict[str, "ServiceInfo"] = {}  # key → ServiceInfo
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        """Start the mDNS server and register pgops.local."""
        with self._lock:
            if self._running:
                return True, "mDNS server already running."

        try:
            from zeroconf import Zeroconf
        except ImportError:
            return False, (
                "zeroconf package not installed.\n"
                "Run:  pip install zeroconf"
            )

        try:
            zc = Zeroconf()
        except Exception as exc:
            return False, f"Failed to initialise zeroconf: {exc}"

        # Register pgops.local (main entry point)
        info = _make_service_info("pgops", self.host_ip, self._HTTP_PORT)
        try:
            zc.register_service(info)
        except Exception as exc:
            try:
                zc.close()
            except Exception:
                pass
            return False, f"Failed to register pgops.local: {exc}"

        with self._lock:
            self._zc = zc
            self._infos["pgops"] = info
            self._running = True

        self._log(f"[mDNS] pgops.local → {self.host_ip}")
        return True, f"mDNS running — pgops.local → {self.host_ip}"

    def stop(self) -> tuple[bool, str]:
        """Unregister all services and shut down zeroconf."""
        with self._lock:
            if not self._running:
                return True, "mDNS server not running."
            zc     = self._zc
            infos  = dict(self._infos)
            self._zc     = None
            self._infos  = {}
            self._running = False

        if zc is not None:
            try:
                for info in infos.values():
                    try:
                        zc.unregister_service(info)
                    except Exception:
                        pass
                zc.close()
            except Exception as exc:
                return False, f"mDNS stop error: {exc}"

        self._log("[mDNS] Stopped — all .local records withdrawn.")
        return True, "mDNS stopped."

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # ── IP update ─────────────────────────────────────────────────────────────

    def update_ip(self, new_ip: str):
        """
        Re-register all services with the new IP address.
        Called when the host's LAN IP changes (e.g. DHCP renewal, hotspot toggle).
        """
        if new_ip == self.host_ip:
            return
        old_ip = self.host_ip
        self.host_ip = new_ip

        if not self.is_running():
            return

        with self._lock:
            zc    = self._zc
            keys  = list(self._infos.keys())

        if zc is None:
            return

        # Unregister old, register new for each service
        for key in keys:
            with self._lock:
                old_info = self._infos.get(key)
            if old_info is None:
                continue

            # Determine the hostname from the key
            hostname = _key_to_hostname(key)
            new_info = _make_service_info(hostname, new_ip, self._HTTP_PORT)

            try:
                zc.unregister_service(old_info)
            except Exception:
                pass
            try:
                zc.register_service(new_info)
                with self._lock:
                    self._infos[key] = new_info
            except Exception as exc:
                self._log(f"[mDNS] re-register failed for {key}: {exc}")

        self._log(f"[mDNS] IP updated {old_ip} → {new_ip} ({len(keys)} records)")

    # ── App registration ──────────────────────────────────────────────────────

    def register_app(self, app_id: str, domain: str = "") -> None:
        """
        Register an app subdomain so it resolves on the LAN.

        domain  — full domain string e.g. "myapp.pgops.local"; if omitted
                  the hostname is derived from app_id as "<app_id>.pgops".
        """
        if not self.is_running():
            return

        # Build the hostname (without .local suffix) from the domain or app_id
        if domain:
            # Strip trailing .local. or .local
            hostname = domain.rstrip(".").removesuffix(".local")
        else:
            hostname = f"{app_id}.pgops"

        key = _hostname_to_key(hostname)

        with self._lock:
            if key in self._infos:
                return   # already registered
            zc = self._zc

        if zc is None:
            return

        info = _make_service_info(hostname, self.host_ip, self._HTTP_PORT)
        try:
            zc.register_service(info)
            with self._lock:
                self._infos[key] = info
            self._log(f"[mDNS] Registered {hostname}.local → {self.host_ip}")
        except Exception as exc:
            self._log(f"[mDNS] Failed to register {hostname}.local: {exc}")

    def unregister_app(self, app_id: str) -> None:
        """Remove an app's mDNS record."""
        hostname = f"{app_id}.pgops"
        key = _hostname_to_key(hostname)

        with self._lock:
            info = self._infos.pop(key, None)
            zc   = self._zc

        if info is None or zc is None:
            return
        try:
            zc.unregister_service(info)
            self._log(f"[mDNS] Unregistered {hostname}.local")
        except Exception as exc:
            self._log(f"[mDNS] Unregister failed for {hostname}.local: {exc}")

    def registered_apps(self) -> list[str]:
        """Return the list of app_ids currently registered (excluding pgops itself)."""
        with self._lock:
            return [k for k in self._infos if k != "pgops"]

    # ── Bulk app sync ─────────────────────────────────────────────────────────

    def sync_apps(self, apps: list[dict]) -> None:
        """
        Reconcile registered mDNS records with the current app list.
        Registers new apps and unregisters removed ones.

        apps — list of app dicts from app_manager.load_apps(), each must have
               at least {"id": str, "domain": str}.
        """
        if not self.is_running():
            return

        desired: dict[str, str] = {}   # key → hostname
        for app in apps:
            domain   = app.get("domain", "")
            app_id   = app.get("id", "")
            if not domain or not app_id:
                continue
            hostname = domain.rstrip(".").removesuffix(".local")
            key = _hostname_to_key(hostname)
            desired[key] = hostname

        with self._lock:
            current_keys = set(self._infos.keys()) - {"pgops"}

        desired_keys = set(desired.keys())

        # Register new
        for key in desired_keys - current_keys:
            hostname = desired[key]
            self.register_app("", domain=f"{hostname}.local")

        # Unregister removed
        for key in current_keys - desired_keys:
            # Recover the app_id from the key
            app_id = key.replace("__dot__", ".")
            self.unregister_app(app_id)

    # ── Status ────────────────────────────────────────────────────────────────

    def status_str(self) -> str:
        if not self.is_running():
            return "Not running"
        with self._lock:
            count = len(self._infos)
        return f"Running — {count} .local record(s) → {self.host_ip}"

    # ── Hosts file helpers (delegates to dns_server) ──────────────────────────
    # These are kept for the local-machine fallback on the DNS tab.

    def inject_hosts(self, app_domains: list[str] = None) -> tuple[bool, str]:
        from core.dns_server import inject_hosts
        return inject_hosts(self.host_ip, app_domains)

    def remove_hosts(self) -> tuple[bool, str]:
        from core.dns_server import remove_hosts
        return remove_hosts()

    def is_hosts_injected(self) -> bool:
        from core.dns_server import is_hosts_injected
        return is_hosts_injected()

    def get_hosts_ip(self):
        from core.dns_server import get_hosts_current_ip
        return get_hosts_current_ip()


# ── Key helpers ───────────────────────────────────────────────────────────────
# zeroconf dict keys cannot contain dots (they're meaningful in DNS), so we
# encode them as __dot__ when used as plain dict keys.

def _hostname_to_key(hostname: str) -> str:
    """Convert a hostname like "myapp.pgops" to a safe dict key."""
    return hostname.replace(".", "__dot__")


def _key_to_hostname(key: str) -> str:
    """Reverse of _hostname_to_key."""
    return key.replace("__dot__", ".")


# ── Client setup instructions ─────────────────────────────────────────────────

def get_client_setup_instructions() -> dict[str, str]:
    """
    Per-platform instructions shown in the DNS tab.
    With mDNS there is usually NOTHING for users to configure.
    """
    return {
        "Windows": (
            "Windows 10/11 supports mDNS (.local domains) natively — no setup needed.\n\n"
            "Connect to the same Wi-Fi network as this machine, then open:\n"
            "  http://pgops.local\n\n"
            "If it doesn't work, install Apple Bonjour (optional):\n"
            "  https://support.apple.com/kb/DL999\n\n"
            "Note: some corporate firewalls block mDNS (UDP 5353).\n"
            "In that case, use the 'Inject Hosts File' option above."
        ),
        "macOS": (
            "macOS supports .local (Bonjour) natively — no setup needed.\n\n"
            "Connect to the same Wi-Fi network, then open:\n"
            "  http://pgops.local\n\n"
            "Apps are available at  http://<appname>.pgops.local"
        ),
        "iOS": (
            "iOS supports .local (Bonjour) natively — no setup needed.\n\n"
            "Connect your iPhone/iPad to the same Wi-Fi network, then open\n"
            "Safari and navigate to:\n"
            "  http://pgops.local\n\n"
            "App subdomains:  http://<appname>.pgops.local"
        ),
        "Android": (
            "Android 12+ supports mDNS natively in most apps and browsers.\n\n"
            "Connect to the same Wi-Fi network, then open Chrome and navigate to:\n"
            "  http://pgops.local\n\n"
            "If .local doesn't resolve, use the host IP address instead.\n"
            "The IP is shown in the status bar above."
        ),
        "Linux": (
            "Install avahi-daemon for .local resolution:\n\n"
            "  Ubuntu/Debian:  sudo apt install avahi-daemon\n"
            "  Fedora/RHEL:    sudo dnf install avahi\n"
            "  Arch:           sudo pacman -S avahi\n\n"
            "Then connect to the same network and open:\n"
            "  http://pgops.local\n\n"
            "Or add a hosts file entry (no daemon needed):\n"
            "  sudo sh -c 'echo \"<HOST_IP> pgops.local\" >> /etc/hosts'"
        ),
    }
