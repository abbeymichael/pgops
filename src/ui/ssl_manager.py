"""
ssl_manager.py  (v2 — mkcert-aware)

Adds enable_ssl_with_paths() so the SSL tab can point PostgreSQL at the
mkcert-generated cert + key rather than a self-signed one.

The original generate_certificate() / enable_ssl() API is preserved for
backwards compatibility.
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


# ── New: enable with explicit cert/key paths (for mkcert) ─────────────────────

def enable_ssl_with_paths(
    data_dir: Path,
    cert_file: str,
    key_file: str,
) -> tuple[bool, str]:
    """
    Configure PostgreSQL to use the given cert and key files.
    Unlike enable_ssl(), this does NOT copy files — it writes absolute paths
    into postgresql.conf directly.  This works well with mkcert because the
    cert is regenerated in-place (same path) when the IP changes.
    """
    data_dir = Path(data_dir)
    if not data_dir.exists():
        return False, f"PostgreSQL data directory not found: {data_dir}"

    cert = Path(cert_file)
    key  = Path(key_file)
    if not cert.exists():
        return False, f"Certificate not found: {cert}"
    if not key.exists():
        return False, f"Key not found: {key}"

    # Fix permissions on key file
    if platform.system() != "Windows":
        import os
        try:
            os.chmod(key, 0o600)
        except Exception:
            pass

    # Write postgresql.conf
    ok, msg = _set_ssl_conf_paths(
        data_dir,
        enabled=True,
        cert_file=str(cert).replace("\\", "/"),
        key_file=str(key).replace("\\", "/"),
    )
    if not ok:
        return False, msg

    return True, (
        "SSL enabled with mkcert certificate. "
        "Restart the server to apply.\n\n"
        "Connect with:  sslmode=require"
    )


def _set_ssl_conf_paths(
    data_dir: Path,
    enabled: bool,
    cert_file: str = "",
    key_file: str = "",
) -> tuple[bool, str]:
    """Write SSL settings to postgresql.conf using explicit file paths."""
    conf = Path(data_dir) / "postgresql.conf"
    if not conf.exists():
        return False, "postgresql.conf not found — initialize the cluster first."

    import re
    text = conf.read_text(encoding="utf-8", errors="replace")

    def replace_or_append(src: str, key: str, value: str) -> str:
        pattern = re.compile(
            rf"^[ \t]*#?[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE
        )
        line = f"{key} = {value}"
        if pattern.search(src):
            return pattern.sub(line, src)
        return src + f"\n{line}\n"

    text = replace_or_append(text, "ssl", "on" if enabled else "off")

    if enabled and cert_file and key_file:
        text = replace_or_append(text, "ssl_cert_file", f"'{cert_file}'")
        text = replace_or_append(text, "ssl_key_file",  f"'{key_file}'")
        text = replace_or_append(text, "ssl_ca_file",   "''")
    elif not enabled:
        text = replace_or_append(text, "ssl", "off")

    try:
        conf.write_text(text, encoding="utf-8")
    except Exception as e:
        return False, f"Cannot write postgresql.conf: {e}"

    return True, f"ssl = {'on' if enabled else 'off'} written to postgresql.conf"


# ── Original API (preserved for backwards compatibility) ───────────────────────

def generate_certificate(base_dir: Path, hostname: str = "pgops.test") -> tuple[bool, str]:
    """
    Generate a self-signed TLS certificate valid for 10 years.
    Prefer using mkcert_manager.generate_cert() for browser-trusted certs.
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
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PGOps"),
    ])

    san_entries = [
        DNSName(hostname),
        DNSName(f"*.{hostname}"),
        DNSName("localhost"),
        DNSName("pgops"),
        IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    try:
        from core.network_info import get_all_interfaces
        for iface in get_all_interfaces():
            ip = iface.get("ip", "")
            if ip and ip != "127.0.0.1" and not ip.startswith("169.254"):
                try:
                    san_entries.append(IPAddress(ipaddress.IPv4Address(ip)))
                except Exception:
                    pass
    except Exception:
        pass
    for extra_ip in ("192.168.137.1",):
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
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True,
                content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    key_file = key_path(base_dir)
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    crt_file = cert_path(base_dir)
    crt_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    if platform.system() != "Windows":
        import os
        os.chmod(key_file, 0o600)

    exp_date = (now + datetime.timedelta(days=3650)).strftime("%Y-%m-%d")
    return True, f"Certificate generated. Valid until {exp_date}.\nFile: {crt_file}"


def enable_ssl(base_dir: Path, data_dir: Path) -> tuple[bool, str]:
    """
    Copy certs from base_dir/ssl/ into pgdata and enable SSL.
    Legacy API — new code should call enable_ssl_with_paths() instead.
    """
    base_dir = Path(base_dir)
    data_dir = Path(data_dir)

    if not is_ssl_configured(base_dir):
        return False, "No certificate found. Generate one first."
    if not data_dir.exists():
        return False, f"PostgreSQL data directory not found: {data_dir}"

    pg_crt = data_dir / "certs" / "pgops.crt"
    pg_key = data_dir / "certs" / "pgops.key"

    try:
        shutil.copy2(cert_path(base_dir), pg_crt)
        shutil.copy2(key_path(base_dir), pg_key)
    except Exception as e:
        return False, f"Failed to copy SSL files to pgdata: {e}"

    if platform.system() != "Windows":
        import os
        try:
            os.chmod(pg_key, 0o600)
        except Exception:
            pass

    ok, msg = _set_ssl_conf(data_dir, enabled=True)
    if not ok:
        return False, msg

    return True, "SSL enabled. Restart the server to apply.\n\nConnect with:  sslmode=require"


def disable_ssl(data_dir: Path) -> tuple[bool, str]:
    data_dir = Path(data_dir)
    ok, msg = _set_ssl_conf(data_dir, enabled=False)
    if not ok:
        return False, msg
    return True, "SSL disabled. Restart the server to apply."


def _set_ssl_conf(data_dir: Path, enabled: bool) -> tuple[bool, str]:
    conf = Path(data_dir) / "postgresql.conf"
    if not conf.exists():
        return False, "postgresql.conf not found — initialize the cluster first."

    import re
    text = conf.read_text(encoding="utf-8", errors="replace")

    def replace_or_append(src: str, key: str, value: str) -> str:
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
        text = replace_or_append(text, "ssl_cert_file", "'server.crt'")
        text = replace_or_append(text, "ssl_key_file",  "'server.key'")
        text = replace_or_append(text, "ssl_ca_file",   "''")

    try:
        conf.write_text(text, encoding="utf-8")
    except Exception as e:
        return False, f"Cannot write postgresql.conf: {e}"

    return True, f"ssl = {value} written to postgresql.conf"


def get_ssl_status(data_dir: Path) -> dict:
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
    crt = cert_path(Path(base_dir))
    if not crt.exists():
        return {}
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
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
    crt = cert_path(Path(base_dir))
    if not crt.exists():
        return False, "No certificate to export."
    try:
        shutil.copy2(crt, dest)
        return True, f"Certificate exported to {dest}"
    except Exception as e:
        return False, f"Export failed: {e}"
