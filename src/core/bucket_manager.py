"""
bucket_manager.py
Manages MinIO buckets, users, and access policies.
Mirrors db_manager.py — each bucket gets its own access key + secret.
Uses the mc (MinIO Client) CLI for all operations.
"""

import subprocess
import platform
import json
import secrets
import string
from pathlib import Path
from typing import Optional


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


ALIAS = "pgops"


def _mc(args: list, capture=True) -> tuple[bool, str]:
    """Run an mc command against the pgops alias."""
    from core.minio_manager import mc_bin
    cmd = [str(mc_bin())] + args
    try:
        r = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            **_popen_kwargs()
        )
        output = (r.stdout + r.stderr).strip()
        return r.returncode == 0, output
    except Exception as e:
        return False, str(e)


def _gen_secret(length: int = 32) -> str:
    """Generate a random secret key."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _gen_access_key(prefix: str = "") -> str:
    """Generate a short access key ID."""
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits)
                     for _ in range(12))
    if prefix:
        clean = "".join(c for c in prefix.upper() if c.isalnum())[:8]
        return f"{clean}{suffix}"
    return suffix


# ── Bucket operations ─────────────────────────────────────────────────────────

def list_buckets() -> list[dict]:
    """Return list of buckets with name and size info."""
    ok, out = _mc(["ls", "--json", ALIAS])
    if not ok:
        return []
    buckets = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "folder" or data.get("status") == "success":
                name = data.get("key", "").rstrip("/")
                if name:
                    buckets.append({"name": name})
        except Exception:
            continue
    return buckets


def get_bucket_size(bucket_name: str) -> str:
    """Get total size of a bucket."""
    ok, out = _mc(["du", "--json", f"{ALIAS}/{bucket_name}"])
    if ok:
        try:
            data = json.loads(out.splitlines()[0])
            size = data.get("size", 0)
            if size < 1024:
                return f"{size} B"
            elif size < 1024 ** 2:
                return f"{size/1024:.1f} KB"
            elif size < 1024 ** 3:
                return f"{size/1024**2:.1f} MB"
            else:
                return f"{size/1024**3:.2f} GB"
        except Exception:
            pass
    return "—"


def list_users() -> list[dict]:
    """List all MinIO service accounts / users."""
    ok, out = _mc(["admin", "user", "list", "--json", ALIAS])
    if not ok:
        return []
    users = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("status") == "success":
                users.append({
                    "accessKey": data.get("accessKey", ""),
                    "status":    data.get("userStatus", "enabled"),
                })
        except Exception:
            continue
    return users


def create_bucket(
    bucket_name: str,
    app_name: str = "",
) -> tuple[bool, str, dict]:
    """
    Create a bucket and a dedicated access key with policy
    that only allows access to this bucket.
    Returns (ok, message, credentials_dict)
    """
    # Validate name — MinIO bucket names: lowercase, 3-63 chars, no spaces
    bucket_name = bucket_name.lower().replace(" ", "-").replace("_", "-")
    if len(bucket_name) < 3:
        return False, "Bucket name must be at least 3 characters.", {}

    # 1. Create the bucket
    ok, msg = _mc(["mb", f"{ALIAS}/{bucket_name}"])
    if not ok and "already exists" not in msg.lower():
        return False, f"Failed to create bucket: {msg}", {}

    # 2. Generate access credentials
    access_key = _gen_access_key(app_name or bucket_name)
    secret_key  = _gen_secret(40)

    # 3. Create bucket-scoped policy JSON
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket_name}",
                    f"arn:aws:s3:::{bucket_name}/*",
                ],
            }
        ],
    }

    # Write policy to temp file
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tf:
        json.dump(policy, tf)
        policy_file = tf.name

    policy_name = f"policy-{bucket_name}"

    try:
        # 4. Create the policy
        ok2, msg2 = _mc([
            "admin", "policy", "create",
            ALIAS, policy_name, policy_file
        ])
        if not ok2 and "already exists" not in msg2.lower():
            return False, f"Failed to create policy: {msg2}", {}

        # 5. Create the user (access key + secret)
        ok3, msg3 = _mc([
            "admin", "user", "add",
            ALIAS, access_key, secret_key
        ])
        if not ok3:
            return False, f"Failed to create access key: {msg3}", {}

        # 6. Attach policy to user
        ok4, msg4 = _mc([
            "admin", "policy", "attach",
            ALIAS, policy_name,
            "--user", access_key
        ])
        if not ok4:
            return False, f"Failed to attach policy: {msg4}", {}

    finally:
        try:
            os.unlink(policy_file)
        except Exception:
            pass

    creds = {
        "bucket":     bucket_name,
        "access_key": access_key,
        "secret_key": secret_key,
        "policy":     policy_name,
    }

    return True, f"Bucket '{bucket_name}' created with dedicated access key.", creds


def drop_bucket(bucket_name: str) -> tuple[bool, str]:
    """Remove a bucket and all its contents and associated credentials."""
    # Find and remove associated users
    users = list_users()
    policy_name = f"policy-{bucket_name}"

    for user in users:
        ak = user.get("accessKey", "")
        # Check if this user's policy matches the bucket
        ok, out = _mc(["admin", "user", "info", "--json", ALIAS, ak])
        if ok:
            try:
                data = json.loads(out)
                policies = data.get("policyName", "")
                if policy_name in policies:
                    _mc(["admin", "user", "remove", ALIAS, ak])
            except Exception:
                pass

    # Remove the policy
    _mc(["admin", "policy", "remove", ALIAS, policy_name])

    # Remove bucket and all contents
    ok, msg = _mc(["rb", "--force", f"{ALIAS}/{bucket_name}"])
    if not ok and "does not exist" not in msg.lower():
        return False, f"Failed to remove bucket: {msg}"

    return True, f"Bucket '{bucket_name}' and its credentials removed."


def rotate_keys(bucket_name: str, old_access_key: str) -> tuple[bool, str, dict]:
    """
    Generate new access key + secret for a bucket.
    Removes old credentials and creates fresh ones.
    """
    policy_name = f"policy-{bucket_name}"
    app_name = bucket_name.split("-")[0] if "-" in bucket_name else bucket_name

    # Remove old user
    _mc(["admin", "user", "remove", ALIAS, old_access_key])

    # Create new credentials
    new_access_key = _gen_access_key(app_name)
    new_secret_key = _gen_secret(40)

    ok, msg = _mc([
        "admin", "user", "add",
        ALIAS, new_access_key, new_secret_key
    ])
    if not ok:
        return False, f"Failed to create new key: {msg}", {}

    ok2, msg2 = _mc([
        "admin", "policy", "attach",
        ALIAS, policy_name,
        "--user", new_access_key
    ])
    if not ok2:
        return False, f"Failed to attach policy: {msg2}", {}

    creds = {
        "bucket":     bucket_name,
        "access_key": new_access_key,
        "secret_key": new_secret_key,
    }
    return True, "Keys rotated successfully.", creds


def get_bucket_credentials(bucket_name: str) -> Optional[dict]:
    """
    Find the access key associated with a bucket by checking policies.
    Returns credentials dict or None.
    """
    policy_name = f"policy-{bucket_name}"
    users = list_users()
    for user in users:
        ak = user.get("accessKey", "")
        ok, out = _mc(["admin", "user", "info", "--json", ALIAS, ak])
        if ok:
            try:
                data = json.loads(out)
                policies = data.get("policyName", "")
                if policy_name in policies:
                    return {"access_key": ak, "policy": policy_name}
            except Exception:
                continue
    return None


def backup_bucket(
    bucket_name: str,
    dest_dir: Path,
    progress_callback=None,
) -> tuple[bool, str]:
    """Mirror a bucket to a local directory."""
    dest = Path(dest_dir) / bucket_name
    dest.mkdir(parents=True, exist_ok=True)
    if progress_callback:
        progress_callback(10)
    ok, msg = _mc([
        "mirror", "--overwrite",
        f"{ALIAS}/{bucket_name}",
        str(dest),
    ])
    if progress_callback:
        progress_callback(100)
    if not ok:
        return False, f"Backup failed: {msg}"
    return True, f"Bucket '{bucket_name}' backed up to {dest}"


def restore_bucket(
    source_dir: Path,
    bucket_name: str,
    progress_callback=None,
) -> tuple[bool, str]:
    """Restore a bucket from a local mirror."""
    if not Path(source_dir).exists():
        return False, f"Source directory not found: {source_dir}"
    if progress_callback:
        progress_callback(10)
    # Ensure bucket exists
    _mc(["mb", "--ignore-existing", f"{ALIAS}/{bucket_name}"])
    ok, msg = _mc([
        "mirror", "--overwrite",
        str(source_dir),
        f"{ALIAS}/{bucket_name}",
    ])
    if progress_callback:
        progress_callback(100)
    if not ok:
        return False, f"Restore failed: {msg}"
    return True, f"Bucket '{bucket_name}' restored."


def get_laravel_env(
    bucket_name: str,
    access_key: str,
    secret_key: str,
    endpoint: str,
    region: str = "us-east-1",
) -> str:
    """Generate ready-to-paste Laravel .env block."""
    return (
        f"FILESYSTEM_DISK=s3\n"
        f"AWS_ACCESS_KEY_ID={access_key}\n"
        f"AWS_SECRET_ACCESS_KEY={secret_key}\n"
        f"AWS_DEFAULT_REGION={region}\n"
        f"AWS_BUCKET={bucket_name}\n"
        f"AWS_ENDPOINT={endpoint}\n"
        f"AWS_USE_PATH_STYLE_ENDPOINT=true\n"
    )
