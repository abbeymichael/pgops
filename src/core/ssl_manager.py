"""
ssl_manager.py
Generates a self-signed TLS certificate and configures PostgreSQL to use it.
Apps then connect with sslmode=require for encrypted LAN connections.
"""

import subprocess
import platform
import datetime
from pathlib import Path


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_ssl_dir(base_dir: Path) -> Path:
    d = base_dir / "ssl"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cert_path(base_dir: Path) -> Path:
    return get_ssl_dir(base_dir) / "server.crt"


def key_path(base_dir: Path) -> Path:
    return get_ssl_dir(base_dir) / "server.key"


def is_ssl_configured(base_dir: Path) -> bool:
    return cert_path(base_dir).exists() and key_path(base_dir).exists()


def generate_certificate(base_dir: Path, hostname: str = "pgops.test") -> tuple[bool, str]:
    """
    Generate a self-signed TLS certificate valid for 10 years.
    Uses the cryptography library — no openssl binary needed.
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509 import IPAddress, DNSName
        import ipaddress
    except ImportError:
        return False, (
            "cryptography package not installed.\n"
            "Run: pip install cryptography"
        )

    ssl_dir = get_ssl_dir(base_dir)

    # Generate private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PGOps"),
    ])

    # SAN: include pgops.test, localhost, 127.0.0.1, and common LAN ranges
    san_entries = [
        DNSName(hostname),
        DNSName("localhost"),
        DNSName("pgops"),
        IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]

    # Try to include current LAN IP
    try:
        from core.network_info import get_all_interfaces, get_best_ip
        ifaces = get_all_interfaces()
        ip_str = get_best_ip(ifaces)
        if ip_str and ip_str != "127.0.0.1":
            san_entries.append(IPAddress(ipaddress.IPv4Address(ip_str)))
        # Also add hotspot IP
        if not any(i["ip"] == "192.168.137.1" for i in ifaces):
            san_entries.append(IPAddress(ipaddress.IPv4Address("192.168.137.1")))
    except Exception:
        san_entries.append(IPAddress(ipaddress.IPv4Address("192.168.137.1")))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    # Write private key (PostgreSQL requires no passphrase)
    key_file = key_path(base_dir)
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    # Write certificate
    crt_file = cert_path(base_dir)
    crt_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # PostgreSQL requires key file to have restricted permissions on Unix
    if platform.system() != "Windows":
        import os
        os.chmod(key_file, 0o600)

    exp_date = (datetime.datetime.utcnow() + datetime.timedelta(days=3650)).strftime("%Y-%m-%d")
    return True, f"Certificate generated. Valid until {exp_date}.\nFile: {crt_file}"


def enable_ssl(base_dir: Path, data_dir: Path) -> tuple[bool, str]:
    """
    Copy certs to pgdata and enable SSL in postgresql.conf.
    """
    if not is_ssl_configured(base_dir):
        return False, "No certificate found. Generate one first."

    # Copy cert and key into pgdata (PostgreSQL reads them from there)
    pg_crt = data_dir / "server.crt"
    pg_key = data_dir / "server.key"

    import shutil
    shutil.copy2(cert_path(base_dir), pg_crt)
    shutil.copy2(key_path(base_dir), pg_key)

    if platform.system() != "Windows":
        import os
        os.chmod(pg_key, 0o600)

    # Update postgresql.conf
    ok, msg = _set_ssl_conf(data_dir, enabled=True)
    if not ok:
        return False, msg

    return True, (
        "SSL enabled. Restart the server to apply.\n\n"
        "Apps should now connect with:  sslmode=require"
    )


def disable_ssl(data_dir: Path) -> tuple[bool, str]:
    ok, msg = _set_ssl_conf(data_dir, enabled=False)
    if not ok:
        return False, msg
    return True, "SSL disabled. Restart the server to apply."


def _set_ssl_conf(data_dir: Path, enabled: bool) -> tuple[bool, str]:
    conf = data_dir / "postgresql.conf"
    if not conf.exists():
        return False, "postgresql.conf not found — initialize the cluster first."

    import re
    text = conf.read_text()
    value = "on" if enabled else "off"

    def replace_or_append(text, key, val):
        pattern = re.compile(rf"^#?\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
        line = f"{key} = {val}"
        if pattern.search(text):
            return pattern.sub(line, text)
        return text + f"\n{line}\n"

    text = replace_or_append(text, "ssl", value)
    if enabled:
        text = replace_or_append(text, "ssl_cert_file", "'server.crt'")
        text = replace_or_append(text, "ssl_key_file",  "'server.key'")

    conf.write_text(text)
    return True, f"ssl = {value} written to postgresql.conf"


def get_ssl_status(data_dir: Path) -> dict:
    """Return current SSL config state."""
    conf = data_dir / "postgresql.conf"
    enabled = False
    if conf.exists():
        text = conf.read_text()
        import re
        m = re.search(r"^\s*ssl\s*=\s*(\w+)", text, re.MULTILINE)
        if m:
            enabled = m.group(1).lower() == "on"
    return {
        "enabled": enabled,
        "cert_exists": cert_path(data_dir.parent).exists(),
        "key_exists":  key_path(data_dir.parent).exists(),
    }


def get_cert_info(base_dir: Path) -> dict:
    """Return cert expiry and subject info."""
    crt = cert_path(base_dir)
    if not crt.exists():
        return {}
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
        return {
            "expires": cert.not_valid_after_utc.strftime("%Y-%m-%d"),
            "subject": cert.subject.get_attributes_for_oid(
                x509.oid.NameOID.COMMON_NAME
            )[0].value,
            "serial":  str(cert.serial_number)[:12],
        }
    except Exception as e:
        return {"error": str(e)}


def export_ca_cert(base_dir: Path, dest: Path) -> tuple[bool, str]:
    """Copy the server cert to a location the user can distribute to clients."""
    crt = cert_path(base_dir)
    if not crt.exists():
        return False, "No certificate to export."
    import shutil
    shutil.copy2(crt, dest)
    return True, f"Certificate exported to {dest}"
