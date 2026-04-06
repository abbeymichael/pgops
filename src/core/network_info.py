"""
network_info.py
Discovers all network interfaces and their IPv4 addresses.
Identifies hotspot, LAN, and loopback adapters.
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
    seen_ips = set()

    try:
        import socket
        hostname = socket.gethostname()
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for r in results:
            ip = r[4][0]
            if ip not in seen_ips:
                seen_ips.add(ip)
                interfaces.append(_classify(ip, ""))
    except Exception:
        pass

    # On Windows use ipconfig for richer info including adapter names
    if platform.system() == "Windows":
        interfaces = _get_windows_interfaces()
    elif platform.system() == "Darwin":
        interfaces = _get_mac_interfaces()

    # Always include loopback
    if not any(i["ip"] == "127.0.0.1" for i in interfaces):
        interfaces.append({"name": "Loopback", "ip": "127.0.0.1", "type": "loopback"})

    return interfaces


def _classify(ip: str, name: str) -> dict:
    name_lower = name.lower()
    if ip == "127.0.0.1":
        return {"name": "Loopback", "ip": ip, "type": "loopback"}
    if ip == "192.168.137.1":
        return {"name": "Mobile Hotspot", "ip": ip, "type": "hotspot"}
    if "hotspot" in name_lower or "local area connection* " in name_lower:
        return {"name": name or "Mobile Hotspot", "ip": ip, "type": "hotspot"}
    if "wi-fi" in name_lower or "wireless" in name_lower or "wlan" in name_lower:
        return {"name": name or "Wi-Fi", "ip": ip, "type": "wifi"}
    if "ethernet" in name_lower or "local area" in name_lower:
        return {"name": name or "Ethernet", "ip": ip, "type": "lan"}
    return {"name": name or "Network", "ip": ip, "type": "other"}


def _get_windows_interfaces() -> list[dict]:
    try:
        r = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, **_popen_kwargs()
        )
        interfaces = []
        current_adapter = ""
        seen = set()

        for line in r.stdout.splitlines():
            line_stripped = line.strip()
            # Adapter name lines have no leading spaces
            if line and not line.startswith(" ") and line.endswith(":"):
                current_adapter = line.rstrip(":")
            elif "IPv4 Address" in line and ":" in line:
                ip = line.split(":")[-1].strip().rstrip("(Preferred)").strip()
                if ip and ip not in seen and not ip.startswith("169."):
                    seen.add(ip)
                    iface = _classify(ip, current_adapter)
                    interfaces.append(iface)

        return interfaces
    except Exception:
        return []


def _get_mac_interfaces() -> list[dict]:
    try:
        r = subprocess.run(
            ["ifconfig"], capture_output=True, text=True
        )
        interfaces = []
        current = ""
        seen = set()
        for line in r.stdout.splitlines():
            if not line.startswith("\t") and ":" in line:
                current = line.split(":")[0]
            elif "inet " in line and "127.0.0.1" not in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ip = parts[1]
                    if ip not in seen:
                        seen.add(ip)
                        interfaces.append(_classify(ip, current))
        return interfaces
    except Exception:
        return []


def get_best_ip(interfaces: list[dict], preferred: str = None) -> str:
    """
    Returns the best IP to use as database host.
    Priority: preferred (if still active) > hotspot > lan > wifi > other
    """
    active_ips = {i["ip"] for i in interfaces}

    if preferred and preferred in active_ips:
        return preferred

    for type_pref in ("hotspot", "lan", "wifi", "other"):
        for iface in interfaces:
            if iface["type"] == type_pref and iface["ip"] != "127.0.0.1":
                return iface["ip"]

    return "127.0.0.1"


def is_hotspot_active() -> bool:
    """Quick check if the Windows hotspot IP is bound."""
    interfaces = get_all_interfaces()
    return any(i["ip"] == "192.168.137.1" for i in interfaces)
