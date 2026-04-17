"""
ssl_manager.py
Generates a self-signed TLS certificate and configures PostgreSQL to use it.

FIXES:
- cert_path / key_path now correctly reference base_dir/ssl/ subdirectory
- generate_certificate() fetches current LAN IPs at generation time
- enable_ssl() copies certs to DATA_DIR (pgdata) with correct permissions
- postgresql.conf update regex is anchored correctly (no partial matches)
- get_cert_info() uses not_valid_after_utc for Python 3.12 compatibility
- export_ca_cert() uses correct base_dir argument
- disable_ssl() does not delete cert files — only updates conf
"""

import subprocess
import platform
import datetime
import shutil
from pathlib import Path


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_ssl_dir(base_dir: Path) -> Path:
    d = Path(base_dir) / "ssl"
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

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PGOps"),
    ])

    # Build SAN list
    san_entries = [
        DNSName(hostname),
        DNSName(f"*.{hostname}"),   # wildcard for all subdomains
        DNSName("localhost"),
        DNSName("pgops"),
        IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]

    # Add all current LAN IPs
    try:
        from core.network_info import get_all_interfaces, get_best_ip
        ifaces = get_all_interfaces()
        for iface in ifaces:
            ip = iface.get("ip", "")
            if ip and ip != "127.0.0.1" and not ip.startswith("169.254"):
                try:
                    san_entries.append(IPAddress(ipaddress.IPv4Address(ip)))
                except Exception:
                    pass
    except Exception:
        pass

    # Always include common hotspot and loopback IPs
    for extra_ip in ("192.168.137.1", "0.0.0.0"):
        try:
            entry = IPAddress(ipaddress.IPv4Address(extra_ip))
            if entry not in san_entries:
                san_entries.append(entry)
        except Exception:
            pass

    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
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

    exp_date = (now + datetime.timedelta(days=3650)).strftime("%Y-%m-%d")
    return True, (
        f"Certificate generated. Valid until {exp_date}.\n"
        f"File: {crt_file}"
    )


def enable_ssl(base_dir: Path, data_dir: Path) -> tuple[bool, str]:
    """
    Copy certs to pgdata and enable SSL in postgresql.conf.
    base_dir: the PGOps appdata dir (contains ssl/ subdir with certs)
    data_dir: PostgreSQL data directory (pgdata)
    """
    base_dir = Path(base_dir)
    data_dir = Path(data_dir)

    if not is_ssl_configured(base_dir):
        return False, "No certificate found. Generate one first."

    if not data_dir.exists():
        return False, f"PostgreSQL data directory not found: {data_dir}"

    # Copy cert and key into pgdata
    pg_crt = data_dir / "server.crt"
    pg_key = data_dir / "server.key"

    try:
        shutil.copy2(cert_path(base_dir), pg_crt)
        shutil.copy2(key_path(base_dir), pg_key)
    except Exception as e:
        return False, f"Failed to copy SSL files to pgdata: {e}"

    if platform.system() != "Windows":
        import os
        try:
            os.chmod(pg_key, 0o600)
            # PostgreSQL also needs the key owned by the postgres process user
            # On most systems this is the current user when running portably
        except Exception:
            pass

    # Update postgresql.conf
    ok, msg = _set_ssl_conf(data_dir, enabled=True)
    if not ok:
        return False, msg

    return True, (
        "SSL enabled. Restart the server to apply.\n\n"
        "Connect with:  sslmode=require"
    )


def disable_ssl(data_dir: Path) -> tuple[bool, str]:
    data_dir = Path(data_dir)
    ok, msg = _set_ssl_conf(data_dir, enabled=False)
    if not ok:
        return False, msg
    return True, "SSL disabled. Restart the server to apply."


def _set_ssl_conf(data_dir: Path, enabled: bool) -> tuple[bool, str]:
    """Update or append ssl settings in postgresql.conf."""
    conf = Path(data_dir) / "postgresql.conf"
    if not conf.exists():
        return False, "postgresql.conf not found — initialize the cluster first."

    import re
    text = conf.read_text(encoding="utf-8", errors="replace")

    def replace_or_append(src: str, key: str, value: str) -> str:
        # Match lines that are: optional #, optional spaces, key, spaces, =, rest
        pattern = re.compile(
            rf"^[ \t]*#?[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE
        )
        line = f"{key} = {value}"
        if pattern.search(src):
            return pattern.sub(line, src)
        return src + f"\n{line}\n"

    value = "on" if enabled else "off"
    text = replace_or_append(text, "ssl", value)

    if enabled:
        # Use bare filenames — PostgreSQL resolves them relative to data_dir
        text = replace_or_append(text, "ssl_cert_file", "'server.crt'")
        text = replace_or_append(text, "ssl_key_file", "'server.key'")
        text = replace_or_append(text, "ssl_ca_file", "''")

    try:
        conf.write_text(text, encoding="utf-8")
    except Exception as e:
        return False, f"Cannot write postgresql.conf: {e}"

    return True, f"ssl = {value} written to postgresql.conf"


def get_ssl_status(data_dir: Path) -> dict:
    """Return current SSL config state from postgresql.conf."""
    conf = Path(data_dir) / "postgresql.conf"
    enabled = False
    ssl_cert = ""
    ssl_key  = ""
    if conf.exists():
        import re
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^[ \t]*ssl[ \t]*=[ \t]*(\w+)", text, re.MULTILINE)
            if m:
                enabled = m.group(1).lower() == "on"
            mc = re.search(r"^[ \t]*ssl_cert_file[ \t]*=[ \t]*'([^']*)'", text, re.MULTILINE)
            if mc:
                ssl_cert = mc.group(1)
            mk = re.search(r"^[ \t]*ssl_key_file[ \t]*=[ \t]*'([^']*)'", text, re.MULTILINE)
            if mk:
                ssl_key = mk.group(1)
        except Exception:
            pass

    from core.pg_manager import BASE_DIR
    return {
        "enabled":     enabled,
        "cert_exists": cert_path(BASE_DIR).exists(),
        "key_exists":  key_path(BASE_DIR).exists(),
        "ssl_cert":    ssl_cert,
        "ssl_key":     ssl_key,
    }


def get_cert_info(base_dir: Path) -> dict:
    """Return cert expiry and subject info."""
    crt = cert_path(Path(base_dir))
    if not crt.exists():
        return {}
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
        # Use not_valid_after_utc for Python 3.12+, fall back to not_valid_after
        try:
            exp = cert.not_valid_after_utc.strftime("%Y-%m-%d")
        except AttributeError:
            exp = cert.not_valid_after.strftime("%Y-%m-%d")

        cn_attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        return {
            "expires": exp,
            "subject": cn_attrs[0].value if cn_attrs else "unknown",
            "serial":  str(cert.serial_number)[:12],
        }
    except Exception as e:
        return {"error": str(e)}


def export_ca_cert(base_dir: Path, dest: Path) -> tuple[bool, str]:
    """Copy the server cert to a location the user can distribute to clients."""
    crt = cert_path(Path(base_dir))
    if not crt.exists():
        return False, "No certificate to export."
    try:
        shutil.copy2(crt, dest)
        return True, f"Certificate exported to {dest}"
    except Exception as e:
        return False, f"Export failed: {e}"
