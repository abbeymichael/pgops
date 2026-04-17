"""
network_info.py
Discovers all network interfaces and their IPv4 addresses.
Identifies hotspot, LAN, and loopback adapters.

FIXES:
- Windows ipconfig parser now correctly captures adapter name lines
- Added socket-based fallback for both platforms
- Type strings normalised to lowercase consistently
- get_all_interfaces() returns unique IPs only (de-dup across methods)
- get_best_ip() now handles empty interface list gracefully
"""

import socket
import platform
import subprocess


def _popen_kwargs():
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_all_interfaces() -> list[dict]:
    """
    Returns list of dicts:
      { "name": str, "ip": str, "type": str }
    type is one of: "hotspot", "lan", "wifi", "loopback", "other"
    """
    interfaces = []
    seen_ips: set[str] = set()

    if platform.system() == "Windows":
        interfaces = _get_windows_interfaces()
    elif platform.system() == "Darwin":
        interfaces = _get_mac_interfaces()

    # Build seen set from platform scan
    for i in interfaces:
        seen_ips.add(i["ip"])

    # Fallback: socket-based discovery (catches IPs missed by ipconfig/ifconfig)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in seen_ips and not ip.startswith("169.254"):
                seen_ips.add(ip)
                interfaces.append(_classify(ip, ""))
    except Exception:
        pass

    # Second socket fallback using UDP trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in seen_ips and ip != "0.0.0.0":
            seen_ips.add(ip)
            interfaces.append(_classify(ip, ""))
    except Exception:
        pass

    # Always include loopback
    if not any(i["ip"] == "127.0.0.1" for i in interfaces):
        interfaces.append({"name": "Loopback", "ip": "127.0.0.1", "type": "loopback"})

    # Sort: hotspot first, then lan, wifi, other, loopback last
    ORDER = {"hotspot": 0, "lan": 1, "wifi": 2, "other": 3, "loopback": 9}
    interfaces.sort(key=lambda i: ORDER.get(i["type"], 5))

    return interfaces


def _classify(ip: str, name: str) -> dict:
    name_lower = name.lower()
    if ip == "127.0.0.1" or ip.startswith("127."):
        return {"name": "Loopback", "ip": ip, "type": "loopback"}
    if ip == "192.168.137.1":
        return {"name": "Mobile Hotspot", "ip": ip, "type": "hotspot"}
    if "hotspot" in name_lower or "local area connection* " in name_lower:
        return {"name": name or "Mobile Hotspot", "ip": ip, "type": "hotspot"}
    if "wi-fi" in name_lower or "wireless" in name_lower or "wlan" in name_lower:
        return {"name": name or "Wi-Fi", "ip": ip, "type": "wifi"}
    if "ethernet" in name_lower or "local area" in name_lower:
        return {"name": name or "Ethernet", "ip": ip, "type": "lan"}
    # Guess from IP range: 192.168/10/172.16 are typically LAN
    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
        return {"name": name or "Network", "ip": ip, "type": "lan"}
    return {"name": name or "Network", "ip": ip, "type": "other"}


def _get_windows_interfaces() -> list[dict]:
    """Parse ipconfig /all output for IPv4 addresses with adapter names."""
    try:
        r = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        interfaces: list[dict] = []
        current_adapter = ""
        seen: set[str] = set()

        for line in r.stdout.splitlines():
            # Adapter name lines: no leading space, end with colon
            # e.g. "Ethernet adapter Local Area Connection:"
            # e.g. "Wireless LAN adapter Wi-Fi:"
            stripped = line.strip()

            # Adapter section header — no leading whitespace, ends with ':'
            if line and not line.startswith(" ") and not line.startswith("\t"):
                if stripped.endswith(":") and stripped != "Windows IP Configuration":
                    # Strip trailing colon and "adapter " prefix if present
                    current_adapter = stripped.rstrip(":")
                    # Remove common prefixes for cleaner names
                    for prefix in (
                        "Ethernet adapter ",
                        "Wireless LAN adapter ",
                        "Tunnel adapter ",
                        "PPP adapter ",
                    ):
                        if current_adapter.startswith(prefix):
                            current_adapter = current_adapter[len(prefix):]
                            break

            # IPv4 line (ipconfig /all uses "IPv4 Address", ipconfig uses same)
            if "IPv4 Address" in line and ":" in line:
                # Format: "   IPv4 Address. . . . . . . . . : 192.168.1.5(Preferred)"
                parts = line.split(":")
                if len(parts) >= 2:
                    ip = parts[-1].strip()
                    # Remove "(Preferred)" or similar suffixes
                    ip = ip.split("(")[0].strip()
                    if (
                        ip
                        and ip not in seen
                        and not ip.startswith("169.254")
                        and ip != "0.0.0.0"
                    ):
                        seen.add(ip)
                        interfaces.append(_classify(ip, current_adapter))

        return interfaces
    except Exception:
        return []


def _get_mac_interfaces() -> list[dict]:
    """Parse ifconfig output for IPv4 addresses."""
    try:
        r = subprocess.run(
            ["ifconfig"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        interfaces: list[dict] = []
        current = ""
        seen: set[str] = set()

        for line in r.stdout.splitlines():
            # Interface header lines don't start with whitespace
            if line and not line.startswith("\t") and not line.startswith(" "):
                if ":" in line:
                    current = line.split(":")[0].strip()
            elif "inet " in line:
                parts = line.strip().split()
                # ifconfig: "inet 192.168.1.5 netmask ..."
                if len(parts) >= 2:
                    ip = parts[1]
                    if (
                        ip not in seen
                        and not ip.startswith("127.")
                        and not ip.startswith("169.254")
                    ):
                        seen.add(ip)
                        interfaces.append(_classify(ip, current))

        # Always add loopback from macOS
        interfaces.append({"name": "Loopback", "ip": "127.0.0.1", "type": "loopback"})
        return interfaces
    except Exception:
        return []


def get_best_ip(interfaces: list[dict], preferred: str = "") -> str:
    """
    Returns the best IP to use as database host.
    Priority: preferred (if still active) > hotspot > lan > wifi > other
    """
    if not interfaces:
        # Last-resort fallback
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    active_ips = {i["ip"] for i in interfaces}

    if preferred and preferred in active_ips:
        return preferred

    for type_pref in ("hotspot", "lan", "wifi", "other"):
        for iface in interfaces:
            if iface["type"] == type_pref and not iface["ip"].startswith("127."):
                return iface["ip"]

    return "127.0.0.1"


def is_hotspot_active() -> bool:
    """Quick check if the Windows hotspot IP is bound."""
    interfaces = get_all_interfaces()
    return any(i["ip"] == "192.168.137.1" for i in interfaces)
