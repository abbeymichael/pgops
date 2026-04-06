"""
auth.py
Simple master password authentication for PGOps.
Password is stored as a bcrypt hash — never in plaintext.
"""

import json
import os
import platform
from pathlib import Path


def get_auth_file() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    d = base / "PGOps"
    d.mkdir(parents=True, exist_ok=True)
    return d / "auth.json"


def _hash_password(password: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    except ImportError:
        # Fallback using hashlib if bcrypt not available
        import hashlib, secrets
        salt = secrets.token_hex(32)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 300_000)
        return f"pbkdf2:{salt}:{h.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        if stored_hash.startswith("pbkdf2:"):
            import hashlib
            _, salt, expected = stored_hash.split(":", 2)
            h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 300_000)
            return h.hex() == expected
        else:
            import bcrypt
            return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        return False


def is_password_set() -> bool:
    f = get_auth_file()
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text())
        return bool(data.get("password_hash"))
    except Exception:
        return False


def set_password(password: str) -> tuple[bool, str]:
    if len(password) < 4:
        return False, "Password must be at least 4 characters."
    try:
        h = _hash_password(password)
        f = get_auth_file()
        data = {}
        if f.exists():
            try:
                data = json.loads(f.read_text())
            except Exception:
                pass
        data["password_hash"] = h
        f.write_text(json.dumps(data, indent=2))
        return True, "Password set successfully."
    except Exception as e:
        return False, f"Failed to set password: {e}"


def verify_password(password: str) -> bool:
    f = get_auth_file()
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text())
        stored = data.get("password_hash", "")
        return _verify_password(password, stored)
    except Exception:
        return False


def reset_password() -> tuple[bool, str]:
    """Remove the password entirely — next launch will prompt to set a new one."""
    f = get_auth_file()
    if f.exists():
        try:
            data = json.loads(f.read_text())
            data.pop("password_hash", None)
            f.write_text(json.dumps(data, indent=2))
        except Exception:
            f.unlink(missing_ok=True)
    return True, "Password removed. Set a new one on next launch."
