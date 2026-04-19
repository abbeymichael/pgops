"""
mkcert_manager.py
Manages mkcert for automatic LAN-trusted TLS certificates.

mkcert creates a local CA that is trusted by all browsers/OS on the host machine,
and can be exported so LAN devices can trust it too — no browser warnings anywhere.

Key advantages over self-signed certs or Caddy's internal CA:
  - One-click install into system trust store (mkcert -install)
  - CA certificate is easy to export and install on LAN devices
  - Works with PostgreSQL TLS, Caddy HTTPS, and any other service
  - Standard tool, well-documented for end users

Flow:
  1. setup_mkcert()   — download/extract mkcert binary, install CA, generate cert
  2. Caddy            — uses tls <cert> <key> pointing at certs/pgops.crt
  3. PostgreSQL       — copies the same cert into pgdata on enable_ssl
  4. pgAdmin          — configured to use the same cert via config_local.py

Cert location (fixed, shared by all consumers):
  <app_root>/certs/pgops.crt
  <app_root>/certs/pgops.key

On LAN devices:
  - export_ca_cert() copies rootCA.pem so they can install it once
  - After that, all *.pgops.local domains are trusted automatically
"""

import os
import sys
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


# ── App-root resolution ───────────────────────────────────────────────────────

def _get_app_root() -> Path:
    """
    Return the PGOps application root directory.
    Frozen (PyInstaller): directory containing the executable.
    Development: three levels up from this file (repo root).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


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
    """
    Canonical cert directory: <app_root>/certs/
    This is the SINGLE location used by Caddy, PostgreSQL, and pgAdmin.
    All code that needs cert paths must use this function — never appdata/certs.
    """
    d = _get_app_root() / "certs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cert_path() -> Path:
    """Absolute path to pgops.crt."""
    return get_certs_dir() / "pgops.crt"


# Keep legacy alias used by caddy_manager and older callers
def cert_path() -> Path:
    return get_cert_path()


def get_key_path() -> Path:
    """Absolute path to pgops.key."""
    return get_certs_dir() / "pgops.key"


# Keep legacy alias
def key_path() -> Path:
    return get_key_path()


def get_ca_cert_path() -> Optional[Path]:
    """
    Find the mkcert rootCA.pem in CAROOT.
    Returns None if it does not exist yet.
    """
    caroot = _get_caroot()
    if caroot:
        ca = Path(caroot) / "rootCA.pem"
        if ca.exists():
            return ca
    return None


def _get_caroot() -> Optional[str]:
    """
    Return mkcert's CAROOT directory as a string, or None.
    Priority: CAROOT env var → ask mkcert -CAROOT → platform default.
    """
    env_caroot = os.environ.get("CAROOT", "").strip()
    if env_caroot and Path(env_caroot).exists():
        return env_caroot

    if get_mkcert_bin().exists():
        try:
            r = subprocess.run(
                [str(get_mkcert_bin()), "-CAROOT"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                **_popen_kwargs(),
            )
            if r.returncode == 0:
                caroot = r.stdout.strip()
                if caroot:
                    return caroot
        except Exception:
            pass

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


def _build_mkcert_env() -> dict:
    """
    Build the environment for mkcert subprocesses.
    CAROOT is only set when we have a non-empty value — passing an empty
    string confuses mkcert on some platforms and makes it use a wrong path.
    """
    env = {**os.environ}
    caroot = _get_caroot()
    if caroot:
        env["CAROOT"] = caroot
    return env


def get_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


# ── Binary availability ───────────────────────────────────────────────────────

def is_available() -> bool:
    return get_mkcert_bin().exists()


def is_ca_installed() -> bool:
    """True if the mkcert rootCA.pem exists in CAROOT."""
    return get_ca_cert_path() is not None


def is_cert_generated() -> bool:
    return get_cert_path().exists() and get_key_path().exists()


# ── Full setup ────────────────────────────────────────────────────────────────

def setup_mkcert(
    progress_callback: Optional[Callable] = None,
    log_fn: Optional[Callable] = None,
) -> tuple[bool, str]:
    """
    Complete one-shot setup:
      1. Download / extract the mkcert binary            (0–60 %)
      2. Install the local CA into system trust stores   (60–80 %)
      3. Generate certs/pgops.crt + pgops.key            (80–100 %)

    All three steps are always attempted so the caller never has to chain
    separate calls.  Steps 2 and 3 are skipped gracefully if already done.

    Returns (ok, message).  ok=False means the binary download failed;
    CA install or cert-gen failures are logged but treated as warnings
    because the user may still need to complete the trust prompt manually.
    """
    def _prog(pct: int):
        if progress_callback:
            progress_callback(pct)

    # ── Step 1: binary ────────────────────────────────────────────────────
    _prog(0)
    ok, msg = _ensure_binary(progress_callback=lambda p: _prog(int(p * 0.6)), log_fn=log_fn)
    if not ok:
        return False, msg
    _prog(60)

    # ── Step 2: CA trust ──────────────────────────────────────────────────
    if not is_ca_installed():
        if log_fn:
            log_fn("[mkcert] Installing local CA into system trust store…")
        ok2, msg2 = install_ca(log_fn=log_fn)
        if log_fn:
            log_fn(f"[mkcert] {msg2}")
        # Non-fatal: user may need to approve an OS prompt; we continue.
    else:
        if log_fn:
            log_fn("[mkcert] CA already installed — skipping.")
    _prog(80)

    # ── Step 3: certificate ───────────────────────────────────────────────
    if log_fn:
        log_fn("[mkcert] Generating certificate for pgops.local …")
    ok3, msg3 = generate_cert(log_fn=log_fn)
    if log_fn:
        log_fn(f"[mkcert] {msg3}")
    _prog(100)

    if not ok3:
        return False, f"Binary installed but cert generation failed:\n{msg3}"

    return True, (
        "mkcert setup complete.\n"
        "• Local CA installed and trusted by this machine's browsers.\n"
        f"• Certificate written to {get_cert_path()}\n"
        "• For other devices, export the CA and import it once."
    )


def _ensure_binary(
    progress_callback: Optional[Callable] = None,
    log_fn: Optional[Callable] = None,
) -> tuple[bool, str]:
    """
    Download or extract the mkcert binary if not already present.
    Internal helper used by setup_mkcert().
    """
    dest = get_mkcert_bin()
    if dest.exists():
        if progress_callback:
            progress_callback(100)
        return True, "mkcert binary already present."

    sys_name = platform.system()
    machine  = platform.machine().lower()

    # Try bundled asset first (packaged distributions)
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
        arch  = "arm64" if ("arm" in machine or "aarch" in machine) else "amd64"
        fname = f"mkcert-v1.4.4-darwin-{arch}"
    else:
        fname = "mkcert-v1.4.4-linux-amd64"

    url = f"https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/{fname}"

    try:
        import requests  # imported lazily so the module loads without it
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
    On Windows/macOS this may trigger a UAC / sudo prompt.
    """
    if not is_available():
        return False, "mkcert binary not found. Run Setup first."

    try:
        r = subprocess.run(
            [str(get_mkcert_bin()), "-install"],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            env=_build_mkcert_env(),
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        if log_fn and out:
            log_fn(f"[mkcert] {out}")
        if r.returncode == 0:
            return True, (
                "mkcert CA installed in system trust store. "
                "Browsers will trust pgops.local automatically."
            )
        return False, f"mkcert -install failed (rc={r.returncode}):\n{out}"
    except Exception as exc:
        return False, f"mkcert -install error: {exc}"


def uninstall_ca(log_fn: Optional[Callable] = None) -> tuple[bool, str]:
    """Run `mkcert -uninstall` to remove the local CA from trust stores."""
    if not is_available():
        return False, "mkcert not available."
    try:
        r = subprocess.run(
            [str(get_mkcert_bin()), "-uninstall"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=_build_mkcert_env(),
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        if log_fn and out:
            log_fn(f"[mkcert] {out}")
        return r.returncode == 0, out or "CA uninstalled."
    except Exception as exc:
        return False, str(exc)


# ── Certificate generation ────────────────────────────────────────────────────

def generate_cert(
    extra_ips: Optional[list] = None,
    log_fn: Optional[Callable] = None,
) -> tuple[bool, str]:
    """
    Generate a certificate signed by the mkcert local CA covering:
      - pgops.local, *.pgops.local (wildcard for all app subdomains)
      - localhost, 127.0.0.1, ::1
      - All current LAN IPs (discovered via network_info)
      - 192.168.137.1 (common Windows hotspot gateway)
      - Any extra IPs provided by the caller

    Output:
      <app_root>/certs/pgops.crt   ← used by Caddy, PostgreSQL, pgAdmin
      <app_root>/certs/pgops.key

    The CA is auto-installed if not already present.
    """
    if not is_available():
        return False, "mkcert binary not found. Run Setup first."

    # Auto-install CA if missing — mkcert will refuse to generate a cert without it
    if not is_ca_installed():
        if log_fn:
            log_fn("[mkcert] CA not installed — installing now…")
        ok, msg = install_ca(log_fn=log_fn)
        if not ok:
            return False, f"CA installation failed: {msg}"

    # Build SAN list — order matters for the cert's Common Name (first entry)
    domains: list[str] = [
        "pgops.local",
        "*.pgops.local",
        "localhost",
        "127.0.0.1",
        "::1",
    ]

    try:
        from core.network_info import get_all_interfaces
        for iface in get_all_interfaces():
            ip = iface.get("ip", "")
            if ip and ip not in domains and not ip.startswith("169.254"):
                domains.append(ip)
    except Exception:
        pass

    if extra_ips:
        for ip in extra_ips:
            if ip and ip not in domains:
                domains.append(ip)

    if "192.168.137.1" not in domains:
        domains.append("192.168.137.1")

    cert_out = get_cert_path()
    key_out  = get_key_path()

    cmd = [
        str(get_mkcert_bin()),
        "-cert-file", str(cert_out),
        "-key-file",  str(key_out),
    ] + domains

    if log_fn:
        log_fn(f"[mkcert] Running: {' '.join(cmd[:6])} ... [{len(domains)} SANs]")

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            env=_build_mkcert_env(),
            cwd=str(get_certs_dir()),
            **_popen_kwargs(),
        )
        out = (r.stdout + r.stderr).strip()
        if log_fn and out:
            log_fn(f"[mkcert] {out}")

        if r.returncode != 0:
            return False, f"mkcert certificate generation failed:\n{out}"

        if platform.system() != "Windows":
            try:
                os.chmod(key_out, 0o600)
            except Exception:
                pass

        return True, (
            f"Certificate generated ({len(domains)} SANs). "
            f"Covers: {', '.join(domains[:4])} …\n"
            f"Cert : {cert_out}\n"
            f"Key  : {key_out}"
        )

    except Exception as exc:
        return False, f"Certificate generation error: {exc}"


# ── CA export ─────────────────────────────────────────────────────────────────

def export_ca_cert(
    dest_path,                        # str or Path
    log_fn: Optional[Callable] = None,
) -> tuple[bool, str]:
    """
    Copy rootCA.pem to dest_path so LAN devices can install it once
    and trust all *.pgops.local domains automatically.

    Accepts an optional log_fn so it can be called from ssl_manager and
    tab_ssl with a consistent signature.
    """
    ca = get_ca_cert_path()
    if not ca:
        return False, (
            "mkcert CA not found. Run Full Setup first, then try exporting."
        )
    try:
        shutil.copy2(ca, dest_path)
        msg = (
            f"CA certificate exported to:\n{dest_path}\n\n"
            "Install this file on every LAN device:\n"
            "  Windows : double-click → Install → Trusted Root CAs\n"
            "  macOS   : double-click → Keychain → Always Trust\n"
            "  Linux   : sudo cp <file> /usr/local/share/ca-certificates/ && sudo update-ca-certificates\n"
            "  Android : Settings → Security → Install certificate\n"
            "  iOS     : AirDrop/email → tap → Settings → Trust"
        )
        if log_fn:
            log_fn(f"[mkcert] CA exported to {dest_path}")
        return True, msg
    except Exception as exc:
        return False, f"Export failed: {exc}"


# ── Cert info ─────────────────────────────────────────────────────────────────

def get_cert_info() -> dict:
    """
    Parse the current cert and return:
      expires  — YYYY-MM-DD
      subject  — CN value
      serial   — first 12 chars of serial
      sans     — list of DNS names and IP strings (for tab_ssl display)

    Returns {} if cert not present, {"error": ...} on parse failure.
    """
    crt = get_cert_path()
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
            "subject": cn_attrs[0].value if cn_attrs else "pgops.local",
            "serial":  str(cert.serial_number)[:12],
            "sans":    sans,   # list — used by tab_ssl for SAN preview
        }
    except ImportError:
        return {"expires": "unknown (install 'cryptography')", "sans": []}
    except Exception as exc:
        return {"error": str(exc)}


# ── Status summary ────────────────────────────────────────────────────────────

def get_status() -> dict:
    ca_path = get_ca_cert_path()
    return {
        "available":    is_available(),
        "ca_installed": is_ca_installed(),
        "cert_exists":  is_cert_generated(),
        "cert_path":    str(get_cert_path()),
        "key_path":     str(get_key_path()),
        "ca_path":      str(ca_path) if ca_path else "",
        "cert_info":    get_cert_info(),
    }