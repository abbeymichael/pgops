"""
ssl_manager.py
TLS certificate management for PGOps — backed by mkcert.

Design
------
- The authoritative cert lives at  <app_root>/certs/pgops.crt
  and its key at                   <app_root>/certs/pgops.key
  These fixed paths are used by Caddy, PostgreSQL, and pgAdmin.
- mkcert generates the cert so the local CA (already trusted by the system)
  signs it — zero browser warnings on the machine that ran the setup.
- PostgreSQL is configured to use the cert by copying it into pgdata and
  updating postgresql.conf; the source of truth is always certs/.
- get_cert_info() reads the cert directly from certs/ and returns rich
  metadata including SANs (used by tab_ssl to show the domains covered).
- enable_ssl_with_paths() is the primary API called by tab_ssl; the older
  enable_ssl(base_dir, data_dir) is kept as a thin compatibility wrapper.
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path


# ── App-root resolution ───────────────────────────────────────────────────────

def _get_app_root() -> Path:
    """
    Return the PGOps app root directory.
    When frozen (PyInstaller), this is the directory that contains the exe.
    In development it is the repo root (three levels up from this file).
    """
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


# ── Fixed cert paths ──────────────────────────────────────────────────────────

def get_certs_dir() -> Path:
    """Return <app_root>/certs/, creating it if necessary."""
    d = _get_app_root() / "certs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cert_path() -> Path:
    """Absolute path to pgops.crt — used by Caddy, Postgres, pgAdmin."""
    return get_certs_dir() / "pgops.crt"


def key_path() -> Path:
    """Absolute path to pgops.key."""
    return get_certs_dir() / "pgops.key"


def is_cert_generated() -> bool:
    return cert_path().exists() and key_path().exists()


# ── mkcert helpers ────────────────────────────────────────────────────────────

def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def _run_mkcert(*args, log_fn=None) -> tuple[bool, str]:
    """Run mkcert with the given arguments and return (ok, combined_output)."""
    from core.mkcert_manager import get_mkcert_bin
    bin_path = get_mkcert_bin()
    if not bin_path.exists():
        return False, f"mkcert binary not found at {bin_path}. Run Full Setup first."

    cmd = [str(bin_path)] + list(args)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        output = (r.stdout + r.stderr).strip()
        if log_fn and output:
            log_fn(output)
        return r.returncode == 0, output
    except Exception as exc:
        return False, f"mkcert invocation failed: {exc}"


# ── Certificate generation ────────────────────────────────────────────────────

def generate_certificate(log_fn=None) -> tuple[bool, str]:
    """
    Use mkcert to generate a certificate that covers pgops.local, all its
    subdomains, localhost, and the current LAN IPs.

    Output is written directly to:
      certs/pgops.crt
      certs/pgops.key

    mkcert supports -cert-file / -key-file flags to control the output paths
    exactly, so no renaming is needed.
    """
    # Build SAN list
    domains = [
        "pgops.local",
        "*.pgops.local",
        "localhost",
        "127.0.0.1",
    ]

    try:
        from core.network_info import get_all_interfaces
        for iface in get_all_interfaces():
            ip = iface.get("ip", "")
            if ip and ip not in domains and not ip.startswith("169.254"):
                domains.append(ip)
    except Exception:
        pass

    if "192.168.137.1" not in domains:
        domains.append("192.168.137.1")

    if log_fn:
        log_fn(f"[ssl_manager] Generating mkcert certificate for: {', '.join(domains)}")

    ok, msg = _run_mkcert(
        "-cert-file", str(cert_path()),
        "-key-file",  str(key_path()),
        *domains,
        log_fn=log_fn,
    )

    if not ok:
        return False, f"mkcert certificate generation failed:\n{msg}"

    if platform.system() != "Windows":
        try:
            os.chmod(key_path(), 0o600)
        except Exception:
            pass

    info = get_cert_info()
    exp = info.get("expires", "unknown")
    return True, (
        f"Certificate generated via mkcert. Valid until {exp}.\n"
        f"Cert : {cert_path()}\n"
        f"Key  : {key_path()}"
    )


# ── PostgreSQL SSL ────────────────────────────────────────────────────────────

def enable_ssl_with_paths(
    data_dir: Path,
    crt_file: str = "",
    key_file: str = "",
) -> tuple[bool, str]:
    """
    Copy the mkcert cert into pgdata and enable SSL in postgresql.conf.

    crt_file / key_file default to the canonical certs/pgops.{crt,key} if
    not supplied.  This is the primary entry-point called by tab_ssl.
    """
    data_dir = Path(data_dir)
    crt = Path(crt_file) if crt_file else cert_path()
    key = Path(key_file) if key_file else key_path()

    if not crt.exists() or not key.exists():
        return False, (
            "Certificate not found.\n"
            f"Expected:\n  {crt}\n  {key}\n\n"
            "Run Full Setup on the SSL tab first."
        )

    if not data_dir.exists():
        return False, f"PostgreSQL data directory not found: {data_dir}"

    pg_crt = data_dir / "server.crt"
    pg_key = data_dir / "server.key"

    try:
        shutil.copy2(crt, pg_crt)
        shutil.copy2(key, pg_key)
    except Exception as exc:
        return False, f"Failed to copy SSL files to pgdata: {exc}"

    if platform.system() != "Windows":
        try:
            os.chmod(pg_key, 0o600)
        except Exception:
            pass

    ok, msg = _set_ssl_conf(data_dir, enabled=True)
    if not ok:
        return False, msg

    return True, (
        "PostgreSQL SSL enabled using the mkcert certificate.\n"
        "Restart the database server to apply.\n\n"
        f"Source : {crt}\n"
        f"Copied : {pg_crt}\n\n"
        "Connect with:  sslmode=require"
    )


def enable_ssl(base_dir: Path, data_dir: Path) -> tuple[bool, str]:
    """
    Backwards-compatibility wrapper — ignores base_dir and uses the
    canonical certs/ paths.
    """
    return enable_ssl_with_paths(data_dir)


def disable_ssl(data_dir: Path) -> tuple[bool, str]:
    """Turn off SSL in postgresql.conf without touching the cert files."""
    data_dir = Path(data_dir)
    ok, msg = _set_ssl_conf(data_dir, enabled=False)
    if not ok:
        return False, msg
    return True, "SSL disabled. Restart the database server to apply."


def _set_ssl_conf(data_dir: Path, enabled: bool) -> tuple[bool, str]:
    """Update or append SSL directives in postgresql.conf."""
    conf = Path(data_dir) / "postgresql.conf"
    if not conf.exists():
        return False, "postgresql.conf not found — initialise the cluster first."

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
    except Exception as exc:
        return False, f"Cannot write postgresql.conf: {exc}"

    return True, f"ssl = {value} written to postgresql.conf"


# ── Status helpers ────────────────────────────────────────────────────────────

def get_ssl_status(data_dir: Path) -> dict:
    """
    Return current SSL state from postgresql.conf plus cert presence info.
    Called by tab_ssl to drive the status labels.
    """
    conf = Path(data_dir) / "postgresql.conf"
    enabled  = False
    ssl_cert = ""
    ssl_key  = ""

    if conf.exists():
        import re
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^[ \t]*ssl[ \t]*=[ \t]*(\w+)", text, re.MULTILINE)
            if m:
                enabled = m.group(1).lower() == "on"
            mc = re.search(
                r"^[ \t]*ssl_cert_file[ \t]*=[ \t]*'([^']*)'", text, re.MULTILINE
            )
            if mc:
                ssl_cert = mc.group(1)
            mk = re.search(
                r"^[ \t]*ssl_key_file[ \t]*=[ \t]*'([^']*)'", text, re.MULTILINE
            )
            if mk:
                ssl_key = mk.group(1)
        except Exception:
            pass

    return {
        "enabled":     enabled,
        "cert_exists": cert_path().exists(),
        "key_exists":  key_path().exists(),
        "ssl_cert":    ssl_cert,
        "ssl_key":     ssl_key,
        "cert_path":   str(cert_path()),
        "key_path":    str(key_path()),
    }


def get_cert_info() -> dict:
    """
    Parse the mkcert-generated cert and return:
      expires  — expiry date string (YYYY-MM-DD)
      subject  — CN value
      serial   — first 12 chars of serial number
      sans     — list of DNS names and IP strings from the SAN extension

    Returns {} if the cert does not exist, {"error": ...} on parse failure.
    Requires the 'cryptography' package (pip install cryptography).
    """
    crt = cert_path()
    if not crt.exists():
        return {}

    try:
        from cryptography import x509
        from cryptography.x509 import DNSName, IPAddress

        cert = x509.load_pem_x509_certificate(crt.read_bytes())

        try:
            exp = cert.not_valid_after_utc.strftime("%Y-%m-%d")
        except AttributeError:
            exp = cert.not_valid_after.strftime("%Y-%m-%d")

        cn_attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        subject = cn_attrs[0].value if cn_attrs else "unknown"

        sans: list[str] = []
        try:
            san_ext = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            for entry in san_ext.value:
                if isinstance(entry, DNSName):
                    sans.append(entry.value)
                elif isinstance(entry, IPAddress):
                    sans.append(str(entry.value))
        except x509.ExtensionNotFound:
            pass

        return {
            "expires": exp,
            "subject": subject,
            "serial":  str(cert.serial_number)[:12],
            "sans":    sans,
        }

    except ImportError:
        return {
            "expires": "unknown (install 'cryptography' for details)",
            "sans":    [],
        }
    except Exception as exc:
        return {"error": str(exc)}


def export_ca_cert(dest, log_fn=None) -> tuple[bool, str]:
    """
    Export the mkcert root CA so users can import it on other devices.
    Delegates to mkcert_manager which knows the CAROOT path.
    """
    try:
        from core.mkcert_manager import export_ca_cert as _mk_export
        return _mk_export(dest, log_fn=log_fn)
    except Exception as exc:
        return False, f"CA export failed: {exc}"


# ── pgAdmin helpers ───────────────────────────────────────────────────────────

def get_pgadmin_ssl_config() -> dict:
    """
    Return the SSL paths block for pgAdmin's config_local.py.

    In config_local.py:
        DEFAULT_SERVER_SSL_CERT = get_pgadmin_ssl_config()["cert"]
        DEFAULT_SERVER_SSL_KEY  = get_pgadmin_ssl_config()["key"]
    """
    return {
        "cert":        str(cert_path()),
        "key":         str(key_path()),
        "cert_exists": cert_path().exists(),
        "key_exists":  key_path().exists(),
    }