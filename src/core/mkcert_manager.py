"""
mkcert_manager.py
Manages mkcert for automatic LAN-trusted TLS certificates.

mkcert creates a local CA that is trusted by all browsers/OS on the host machine,
and can be exported so LAN devices can trust it too — no browser warnings anywhere.

Key advantages over Caddy's internal CA:
  - One-click install into system trust store (mkcert -install)
  - CA certificate is easy to export and install on LAN devices
  - Works with PostgreSQL TLS, Caddy HTTPS, and any other service
  - Standard tool, well-documented for end users

Flow:
  1. setup_mkcert()        — download/extract mkcert binary
  2. install_ca()          — run `mkcert -install` → adds CA to system trust
  3. generate_cert()       — run `mkcert pgops.test *.pgops.test localhost 127.0.0.1 <LAN-IP>`
  4. Caddy uses tls cert_file key_file instead of `tls internal`
  5. PostgreSQL uses the same cert+key

On LAN devices:
  - export_ca_cert() gives them the rootCA.pem
  - They install it once → all *.pgops.test domains trusted forever
"""

import os
import sys
import platform
import shutil
import subprocess
import socket
import requests
from pathlib import Path
from typing import Optional, Callable


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


# ── Paths ─────────────────────────────────────────────────────────────────────

def get_mkcert_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "mkcert"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_mkcert_bin() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return get_mkcert_dir() / f"mkcert{ext}"


def get_certs_dir() -> Path:
    """Where generated cert/key files are stored."""
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "certs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cert_path() -> Path:
    return get_certs_dir() / "pgops.crt"


def get_key_path() -> Path:
    return get_certs_dir() / "pgops.key"


def get_ca_cert_path() -> Optional[Path]:
    """
    Find the mkcert rootCA.pem.
    mkcert stores it in CAROOT (platform-specific or env override).
    """
    caroot = _get_caroot()
    if caroot:
        ca = Path(caroot) / "rootCA.pem"
        if ca.exists():
            return ca
    return None


def _get_caroot() -> Optional[str]:
    """Return mkcert's CAROOT directory."""
    # Honour env override
    env_caroot = os.environ.get("CAROOT")
    if env_caroot and Path(env_caroot).exists():
        return env_caroot

    # Ask mkcert directly if binary is present
    if get_mkcert_bin().exists():
        try:
            r = subprocess.run(
                [str(get_mkcert_bin()), "-CAROOT"],
                capture_output=True,
                text=True,
                timeout=10,
                **_popen_kwargs(),
            )
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass

    # Platform defaults
    sys_name = platform.system()
    if sys_name == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            return os.path.join(local, "mkcert")
    elif sys_name == "Darwin":
        return str(Path.home() / "Library" / "Application Support" / "mkcert")
    else:
        xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return os.path.join(xdg, "mkcert")
    return None


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


# ── Binary availability ───────────────────────────────────────────────────────

def is_available() -> bool:
    return get_mkcert_bin().exists()


def is_ca_installed() -> bool:
    """Returns True if the mkcert rootCA exists (regardless of trust)."""
    return get_ca_cert_path() is not None


def is_cert_generated() -> bool:
    return get_cert_path().exists() and get_key_path().exists()


# ── Setup (download binary) ───────────────────────────────────────────────────

def setup_mkcert(progress_callback: Optional[Callable] = None) -> tuple[bool, str]:
    """
    Extract mkcert from assets/ bundle or download from GitHub releases.
    Returns (ok, message).
    """
    dest = get_mkcert_bin()
    if dest.exists():
        if progress_callback:
            progress_callback(100)
        return True, "mkcert already available."

    # Try bundled asset first
    sys_name = platform.system()
    machine  = platform.machine().lower()

    bundled_name = "mkcert.exe" if sys_name == "Windows" else "mkcert"
    bundled = get_assets_dir() / bundled_name
    if bundled.exists():
        shutil.copy2(bundled, dest)
        if sys_name != "Windows":
            dest.chmod(0o755)
        if progress_callback:
            progress_callback(100)
        return True, "mkcert extracted from bundle."

    # Download from GitHub releases
    if sys_name == "Windows":
        fname = "mkcert-v1.4.4-windows-amd64.exe"
    elif sys_name == "Darwin":
        arch = "arm64" if ("arm" in machine or "aarch" in machine) else "amd64"
        fname = f"mkcert-v1.4.4-darwin-{arch}"
    else:
        fname = "mkcert-v1.4.4-linux-amd64"

    url = f"https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/{fname}"

    try:
        if progress_callback:
            progress_callback(5)

        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        total      = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(5 + int(downloaded / total * 93))

        if sys_name != "Windows":
            dest.chmod(0o755)

        if progress_callback:
            progress_callback(100)
        return True, "mkcert downloaded and ready."

    except Exception as exc:
        dest.unlink(missing_ok=True)
        return False, (
            f"Failed to download mkcert: {exc}\n\n"
            f"Download manually from https://github.com/FiloSottile/mkcert/releases "
            f"and place as:\n{dest}"
        )


# ── CA installation ───────────────────────────────────────────────────────────

def install_ca(log_fn: Optional[Callable] = None) -> tuple[bool, str]:
    """
    Run `mkcert -install` to add the local CA to the system trust store.
    On Windows/macOS this may trigger a UAC/password prompt.
    """
    if not is_available():
        return False, "mkcert binary not found. Run Setup mkcert first."

    try:
        env = {**os.environ, "CAROOT": _get_caroot() or ""}
        r = subprocess.run(
            [str(get_mkcert_bin()), "-install"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        if log_fn:
            log_fn(f"[mkcert] {out}")
        if r.returncode == 0:
            return True, "mkcert CA installed in system trust store. Browsers will trust pgops.test automatically."
        return False, f"mkcert -install failed (rc={r.returncode}):\n{out}"
    except Exception as exc:
        return False, f"mkcert -install error: {exc}"


def uninstall_ca(log_fn: Optional[Callable] = None) -> tuple[bool, str]:
    """Run `mkcert -uninstall`."""
    if not is_available():
        return False, "mkcert not available."
    try:
        r = subprocess.run(
            [str(get_mkcert_bin()), "-uninstall"],
            capture_output=True, text=True, timeout=30,
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


# ── Certificate generation ────────────────────────────────────────────────────

def generate_cert(
    extra_ips: Optional[list] = None,
    log_fn: Optional[Callable] = None,
) -> tuple[bool, str]:
    """
    Generate a certificate covering pgops.test and all its subdomains,
    plus localhost and any provided LAN IPs.

    The cert is placed in get_certs_dir() as pgops.crt + pgops.key.
    Both Caddy and PostgreSQL use these same files.
    """
    if not is_available():
        return False, "mkcert binary not found. Run Setup mkcert first."

    # Ensure CA is installed first
    if not is_ca_installed():
        ok, msg = install_ca(log_fn=log_fn)
        if not ok:
            return False, f"CA installation failed: {msg}"

    # Collect domains / IPs
    domains = [
        "pgops.test",
        "*.pgops.test",
        "localhost",
        "127.0.0.1",
        "::1",
    ]

    # Add host LAN IPs
    try:
        from core.network_info import get_all_interfaces
        for iface in get_all_interfaces():
            ip = iface.get("ip", "")
            if ip and ip not in domains and not ip.startswith("169.254"):
                domains.append(ip)
    except Exception:
        pass

    # Add extra IPs from caller
    if extra_ips:
        for ip in extra_ips:
            if ip and ip not in domains:
                domains.append(ip)

    # Always include hotspot IP
    if "192.168.137.1" not in domains:
        domains.append("192.168.137.1")

    certs_dir = get_certs_dir()
    cert_out  = certs_dir / "pgops.crt"
    key_out   = certs_dir / "pgops.key"

    # mkcert puts files in CWD by default — use explicit -cert-file / -key-file
    cmd = [
        str(get_mkcert_bin()),
        "-cert-file", str(cert_out),
        "-key-file",  str(key_out),
    ] + domains

    try:
        env = {**os.environ, "CAROOT": _get_caroot() or ""}
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            cwd=str(certs_dir),
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        if log_fn:
            log_fn(f"[mkcert] {out}")

        if r.returncode != 0:
            return False, f"mkcert certificate generation failed:\n{out}"

        # Restrict key permissions on Unix
        if platform.system() != "Windows":
            os.chmod(key_out, 0o600)

        return True, (
            f"Certificate generated covering: {', '.join(domains[:5])} ...\n"
            f"Cert: {cert_out}\n"
            f"Key:  {key_out}"
        )

    except Exception as exc:
        return False, f"Certificate generation error: {exc}"


# ── CA export ─────────────────────────────────────────────────────────────────

def export_ca_cert(dest_path: str) -> tuple[bool, str]:
    """
    Copy rootCA.pem to dest_path so LAN devices can install it once
    and trust all *.pgops.test domains automatically.
    """
    ca = get_ca_cert_path()
    if not ca:
        return False, (
            "mkcert CA not found. Run 'Setup mkcert' and 'Install CA' first, "
            "then try exporting."
        )
    try:
        shutil.copy2(ca, dest_path)
        return True, (
            f"CA certificate exported to:\n{dest_path}\n\n"
            "Install this file on every LAN device that needs to access pgops.test:\n"
            "  Windows : double-click → Install → Trusted Root CAs\n"
            "  macOS   : double-click → Keychain → Always Trust\n"
            "  Linux   : copy to /usr/local/share/ca-certificates/ → update-ca-certificates\n"
            "  Android : Settings → Security → Install certificate\n"
            "  iOS     : AirDrop/email → tap to install → Settings → Trust"
        )
    except Exception as exc:
        return False, f"Export failed: {exc}"


# ── Cert info ─────────────────────────────────────────────────────────────────

def get_cert_info() -> dict:
    """Return expiry, domains etc. for the current cert."""
    crt = get_cert_path()
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
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        domains = [str(d) for d in san_ext.value][:6]
        return {
            "expires": exp,
            "subject": cn_attrs[0].value if cn_attrs else "pgops.test",
            "domains": ", ".join(domains) + (" ..." if len(san_ext.value) > 6 else ""),
            "serial":  str(cert.serial_number)[:12],
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Status summary ────────────────────────────────────────────────────────────

def get_status() -> dict:
    return {
        "available":    is_available(),
        "ca_installed": is_ca_installed(),
        "cert_exists":  is_cert_generated(),
        "cert_path":    str(get_cert_path()),
        "key_path":     str(get_key_path()),
        "ca_path":      str(get_ca_cert_path()) if get_ca_cert_path() else "",
        "cert_info":    get_cert_info(),
    }
