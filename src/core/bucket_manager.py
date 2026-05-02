"""
bucket_manager.py
Manages SeaweedFS buckets, users, and access policies.
Mirrors db_manager.py — each bucket gets its own access key + secret.

All operations now go directly through the SeaweedFS S3-compatible REST API
(and the SeaweedFS IAM API for user/policy management) rather than through
the mc (MinIO Client) CLI that was used previously.

SeaweedFS IAM endpoint: http://127.0.0.1:<s3_port>/?Action=...
SeaweedFS S3  endpoint: http://127.0.0.1:<s3_port>/<bucket>
"""

import json
import secrets
import string
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
import requests


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_manager():
    """Return the live SeaweedFSManager from the running app, or build a
    lightweight one from the saved config.  Callers that run in a worker
    thread cannot import main_window, so we fall back to constructing a
    fresh manager from the persisted config."""
    try:
        from core.seaweedfs_manager import SeaweedFSManager
        from core.config import load_config
        cfg = load_config()
        return SeaweedFSManager(cfg)
    except Exception:
        return None


def _s3_url(path: str = "") -> str:
    from core.config import load_config
    cfg  = load_config()
    port = cfg.get("seaweedfs_s3_port", 8333)
    return f"http://127.0.0.1:{port}{path}"


def _auth() -> tuple[str, str]:
    from core.config import load_config
    cfg = load_config()
    return cfg.get("username", "postgres"), cfg.get("password", "postgres")


def _iam_request(action: str, extra_params: dict = None) -> dict:
    """
    Call the SeaweedFS IAM-compatible API.
    SeaweedFS exposes IAM at the root S3 endpoint with query-string Actions
    that mirror the AWS IAM API.
    """
    params = {"Action": action, **(extra_params or {})}
    user, pw = _auth()
    url = _s3_url("/")
    try:
        r = requests.post(
            url,
            params=params,
            auth=(user, pw),
            timeout=10,
        )
        if r.status_code in (200, 201):
            # SeaweedFS returns XML; parse just enough for our needs
            return {"ok": True, "body": r.text, "status": r.status_code}
        return {"ok": False, "body": r.text, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "body": str(e), "status": 0}


def _gen_secret(length: int = 32) -> str:
    """Generate a random secret key."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _gen_access_key(prefix: str = "") -> str:
    """Generate a short access key ID."""
    suffix = "".join(
        secrets.choice(string.ascii_uppercase + string.digits)
        for _ in range(12)
    )
    if prefix:
        clean = "".join(c for c in prefix.upper() if c.isalnum())[:8]
        return f"{clean}{suffix}"
    return suffix


# ── Bucket operations ─────────────────────────────────────────────────────────

def list_buckets() -> list[dict]:
    """Return list of buckets visible to the admin user."""
    user, pw = _auth()
    try:
        r = requests.get(
            _s3_url("/"),
            auth=(user, pw),
            timeout=10,
        )
        if r.status_code != 200:
            return []

        import xml.etree.ElementTree as ET
        ns   = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        root = ET.fromstring(r.text)
        buckets = []
        for b in root.findall(".//s3:Bucket", ns):
            name = b.findtext("s3:Name", namespaces=ns)
            if name:
                buckets.append({"name": name})
        return buckets
    except Exception:
        return []


def get_bucket_size(bucket_name: str) -> str:
    """
    Approximate total size of a bucket by summing object sizes via
    ListObjectsV2.  Iterates pages until IsTruncated=false.
    """
    user, pw = _auth()
    total_bytes = 0
    continuation_token = None

    try:
        while True:
            params: dict = {
                "list-type": "2",
                "max-keys":  "1000",
            }
            if continuation_token:
                params["continuation-token"] = continuation_token

            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                auth=(user, pw),
                timeout=15,
            )
            if r.status_code != 200:
                break

            import xml.etree.ElementTree as ET
            ns   = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(r.text)

            for obj in root.findall("s3:Contents", ns):
                size_txt = obj.findtext("s3:Size", namespaces=ns) or "0"
                try:
                    total_bytes += int(size_txt)
                except ValueError:
                    pass

            # Pagination
            truncated = root.findtext("s3:IsTruncated", namespaces=ns) or "false"
            if truncated.lower() != "true":
                break
            continuation_token = root.findtext(
                "s3:NextContinuationToken", namespaces=ns
            )
            if not continuation_token:
                break

        size = total_bytes
        if size < 1024:
            return f"{size} B"
        elif size < 1024 ** 2:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 ** 3:
            return f"{size / 1024 ** 2:.1f} MB"
        else:
            return f"{size / 1024 ** 3:.2f} GB"
    except Exception:
        return "—"


def list_users() -> list[dict]:
    """
    List all SeaweedFS IAM users.
    Uses the ListUsers IAM action.
    """
    user, pw = _auth()
    try:
        r = requests.get(
            _s3_url("/"),
            params={"Action": "ListUsers"},
            auth=(user, pw),
            timeout=10,
        )
        if r.status_code != 200:
            return []

        import xml.etree.ElementTree as ET
        # SeaweedFS IAM response namespace
        root    = ET.fromstring(r.text)
        ns_map  = {"iam": "https://iam.amazonaws.com/doc/2010-05-08/"}

        # Try with namespace first, fall back to no-namespace
        members = root.findall(".//iam:member", ns_map)
        if not members:
            members = root.findall(".//member")

        users = []
        for m in members:
            ak = (
                m.findtext("iam:UserName", namespaces=ns_map)
                or m.findtext("UserName")
                or ""
            )
            if ak:
                users.append({"accessKey": ak, "status": "enabled"})
        return users
    except Exception:
        return []


def create_bucket(
    bucket_name: str,
    app_name: str = "",
) -> tuple[bool, str, dict]:
    """
    Create a SeaweedFS bucket and a dedicated IAM user with a bucket-scoped
    policy.
    Returns (ok, message, credentials_dict).
    """
    # Normalise name — S3 bucket rules: lowercase, 3-63 chars, no spaces
    bucket_name = bucket_name.lower().replace(" ", "-").replace("_", "-")
    if len(bucket_name) < 3:
        return False, "Bucket name must be at least 3 characters.", {}

    user, pw = _auth()

    # 1. Create the bucket (PUT /<bucket>)
    try:
        r = requests.put(
            _s3_url(f"/{bucket_name}"),
            auth=(user, pw),
            timeout=10,
        )
        if r.status_code not in (200, 201, 204, 409):
            # 409 = BucketAlreadyOwnedByYou — acceptable
            return False, f"Failed to create bucket: HTTP {r.status_code} {r.text.strip()}", {}
    except Exception as e:
        return False, f"Failed to create bucket: {e}", {}

    # 2. Generate access credentials
    access_key = _gen_access_key(app_name or bucket_name)
    secret_key = _gen_secret(40)
    policy_name = f"policy-{bucket_name}"

    # 3. Create bucket-scoped IAM policy
    policy_document = json.dumps({
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
    })

    try:
        r2 = requests.post(
            _s3_url("/"),
            params={
                "Action":           "CreatePolicy",
                "PolicyName":       policy_name,
                "PolicyDocument":   policy_document,
            },
            auth=(user, pw),
            timeout=10,
        )
        if r2.status_code not in (200, 201, 409):
            return False, f"Failed to create policy: HTTP {r2.status_code} {r2.text.strip()}", {}
    except Exception as e:
        return False, f"Failed to create policy: {e}", {}

    # 4. Create the IAM user
    try:
        r3 = requests.post(
            _s3_url("/"),
            params={
                "Action":          "CreateUser",
                "UserName":        access_key,
            },
            auth=(user, pw),
            timeout=10,
        )
        if r3.status_code not in (200, 201, 409):
            return False, f"Failed to create user: HTTP {r3.status_code} {r3.text.strip()}", {}
    except Exception as e:
        return False, f"Failed to create user: {e}", {}

    # 5. Create access key for the user (stores the secret in SeaweedFS)
    try:
        r4 = requests.post(
            _s3_url("/"),
            params={
                "Action":       "CreateAccessKey",
                "UserName":     access_key,
                "SecretKey":    secret_key,
                "AccessKeyId":  access_key,
            },
            auth=(user, pw),
            timeout=10,
        )
        # SeaweedFS may return 200 or 201; anything else is a problem
        if r4.status_code not in (200, 201):
            return False, f"Failed to create access key: HTTP {r4.status_code} {r4.text.strip()}", {}
    except Exception as e:
        return False, f"Failed to create access key: {e}", {}

    # 6. Attach policy to user
    try:
        r5 = requests.post(
            _s3_url("/"),
            params={
                "Action":    "AttachUserPolicy",
                "UserName":  access_key,
                "PolicyArn": f"arn:aws:iam:::policy/{policy_name}",
            },
            auth=(user, pw),
            timeout=10,
        )
        if r5.status_code not in (200, 201):
            return False, f"Failed to attach policy: HTTP {r5.status_code} {r5.text.strip()}", {}
    except Exception as e:
        return False, f"Failed to attach policy: {e}", {}

    creds = {
        "bucket":     bucket_name,
        "access_key": access_key,
        "secret_key": secret_key,
        "policy":     policy_name,
    }
    return True, f"Bucket '{bucket_name}' created with dedicated access key.", creds


def drop_bucket(bucket_name: str) -> tuple[bool, str]:
    """
    Remove a bucket (and all its contents) plus the associated IAM user
    and policy.
    """
    user, pw = _auth()
    policy_name = f"policy-{bucket_name}"

    # 1. Find and remove associated IAM users
    for u in list_users():
        ak = u.get("accessKey", "")
        try:
            # Check if this user has our bucket policy attached
            r = requests.get(
                _s3_url("/"),
                params={
                    "Action":   "ListAttachedUserPolicies",
                    "UserName": ak,
                },
                auth=(user, pw),
                timeout=10,
            )
            if r.status_code == 200 and policy_name in r.text:
                # Detach policy, delete access keys, delete user
                requests.post(
                    _s3_url("/"),
                    params={
                        "Action":    "DetachUserPolicy",
                        "UserName":  ak,
                        "PolicyArn": f"arn:aws:iam:::policy/{policy_name}",
                    },
                    auth=(user, pw),
                    timeout=10,
                )
                requests.post(
                    _s3_url("/"),
                    params={
                        "Action":       "DeleteAccessKey",
                        "UserName":     ak,
                        "AccessKeyId":  ak,
                    },
                    auth=(user, pw),
                    timeout=10,
                )
                requests.post(
                    _s3_url("/"),
                    params={
                        "Action":    "DeleteUser",
                        "UserName":  ak,
                    },
                    auth=(user, pw),
                    timeout=10,
                )
        except Exception:
            pass

    # 2. Remove the IAM policy
    try:
        requests.post(
            _s3_url("/"),
            params={
                "Action":    "DeletePolicy",
                "PolicyArn": f"arn:aws:iam:::policy/{policy_name}",
            },
            auth=(user, pw),
            timeout=10,
        )
    except Exception:
        pass

    # 3. Delete all objects, then delete the bucket
    _empty_bucket(bucket_name, user, pw)

    try:
        r = requests.delete(
            _s3_url(f"/{bucket_name}"),
            auth=(user, pw),
            timeout=10,
        )
        if r.status_code not in (200, 204, 404):
            return False, f"Failed to remove bucket: HTTP {r.status_code} {r.text.strip()}"
    except Exception as e:
        return False, f"Failed to remove bucket: {e}"

    return True, f"Bucket '{bucket_name}' and its credentials removed."


def _empty_bucket(bucket_name: str, user: str, pw: str):
    """Delete all objects in a bucket so it can be removed."""
    import xml.etree.ElementTree as ET
    import hashlib, base64

    continuation_token = None
    while True:
        params: dict = {"list-type": "2", "max-keys": "1000"}
        if continuation_token:
            params["continuation-token"] = continuation_token
        try:
            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                auth=(user, pw),
                timeout=15,
            )
            if r.status_code != 200:
                break

            ns   = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(r.text)
            keys = [
                c.findtext("s3:Key", namespaces=ns)
                for c in root.findall("s3:Contents", ns)
            ]

            if keys:
                objects_xml = "".join(
                    f"<Object><Key>{k}</Key></Object>" for k in keys if k
                )
                body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<Delete>"
                    f"{objects_xml}"
                    "</Delete>"
                ).encode("utf-8")
                md5 = base64.b64encode(hashlib.md5(body).digest()).decode()
                requests.post(
                    _s3_url(f"/{bucket_name}"),
                    params={"delete": ""},
                    data=body,
                    headers={
                        "Content-Type":   "application/xml",
                        "Content-MD5":    md5,
                        "Content-Length": str(len(body)),
                    },
                    auth=(user, pw),
                    timeout=30,
                )

            truncated = root.findtext("s3:IsTruncated", namespaces=ns) or "false"
            if truncated.lower() != "true":
                break
            continuation_token = root.findtext(
                "s3:NextContinuationToken", namespaces=ns
            )
            if not continuation_token:
                break
        except Exception:
            break


def rotate_keys(
    bucket_name: str, old_access_key: str
) -> tuple[bool, str, dict]:
    """
    Generate a new access key + secret for a bucket.
    Removes old credentials and creates fresh ones.
    """
    policy_name = f"policy-{bucket_name}"
    app_name    = bucket_name.split("-")[0] if "-" in bucket_name else bucket_name
    user, pw    = _auth()

    # Detach policy from old user
    try:
        requests.post(
            _s3_url("/"),
            params={
                "Action":    "DetachUserPolicy",
                "UserName":  old_access_key,
                "PolicyArn": f"arn:aws:iam:::policy/{policy_name}",
            },
            auth=(user, pw),
            timeout=10,
        )
        requests.post(
            _s3_url("/"),
            params={
                "Action":       "DeleteAccessKey",
                "UserName":     old_access_key,
                "AccessKeyId":  old_access_key,
            },
            auth=(user, pw),
            timeout=10,
        )
        requests.post(
            _s3_url("/"),
            params={
                "Action":   "DeleteUser",
                "UserName": old_access_key,
            },
            auth=(user, pw),
            timeout=10,
        )
    except Exception:
        pass

    # Create new credentials
    new_access_key = _gen_access_key(app_name)
    new_secret_key = _gen_secret(40)

    try:
        requests.post(
            _s3_url("/"),
            params={"Action": "CreateUser", "UserName": new_access_key},
            auth=(user, pw),
            timeout=10,
        )
        r2 = requests.post(
            _s3_url("/"),
            params={
                "Action":       "CreateAccessKey",
                "UserName":     new_access_key,
                "SecretKey":    new_secret_key,
                "AccessKeyId":  new_access_key,
            },
            auth=(user, pw),
            timeout=10,
        )
        if r2.status_code not in (200, 201):
            return False, f"Failed to create new key: HTTP {r2.status_code}", {}

        r3 = requests.post(
            _s3_url("/"),
            params={
                "Action":    "AttachUserPolicy",
                "UserName":  new_access_key,
                "PolicyArn": f"arn:aws:iam:::policy/{policy_name}",
            },
            auth=(user, pw),
            timeout=10,
        )
        if r3.status_code not in (200, 201):
            return False, f"Failed to attach policy: HTTP {r3.status_code}", {}
    except Exception as e:
        return False, f"Failed to rotate keys: {e}", {}

    creds = {
        "bucket":     bucket_name,
        "access_key": new_access_key,
        "secret_key": new_secret_key,
    }
    return True, "Keys rotated successfully.", creds


def get_bucket_credentials(bucket_name: str) -> Optional[dict]:
    """
    Find the access key associated with a bucket by checking which IAM user
    has the bucket's policy attached.
    Returns credentials dict or None.
    """
    policy_name = f"policy-{bucket_name}"
    user, pw    = _auth()

    for u in list_users():
        ak = u.get("accessKey", "")
        try:
            r = requests.get(
                _s3_url("/"),
                params={
                    "Action":   "ListAttachedUserPolicies",
                    "UserName": ak,
                },
                auth=(user, pw),
                timeout=10,
            )
            if r.status_code == 200 and policy_name in r.text:
                return {"access_key": ak, "policy": policy_name}
        except Exception:
            continue
    return None


def backup_bucket(
    bucket_name: str,
    dest_dir: Path,
    progress_callback=None,
) -> tuple[bool, str]:
    """
    Mirror a bucket to a local directory by downloading all objects via S3.
    """
    import xml.etree.ElementTree as ET
    user, pw = _auth()
    dest = Path(dest_dir) / bucket_name
    dest.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(5)

    # List all objects
    all_keys = []
    continuation_token = None
    try:
        while True:
            params: dict = {"list-type": "2", "max-keys": "1000"}
            if continuation_token:
                params["continuation-token"] = continuation_token
            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                auth=(user, pw),
                timeout=15,
            )
            if r.status_code != 200:
                return False, f"Could not list bucket: HTTP {r.status_code}"

            ns   = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(r.text)
            for c in root.findall("s3:Contents", ns):
                k = c.findtext("s3:Key", namespaces=ns)
                if k:
                    all_keys.append(k)

            truncated = root.findtext("s3:IsTruncated", namespaces=ns) or "false"
            if truncated.lower() != "true":
                break
            continuation_token = root.findtext(
                "s3:NextContinuationToken", namespaces=ns
            )
            if not continuation_token:
                break
    except Exception as e:
        return False, f"Backup list failed: {e}"

    total  = len(all_keys)
    errors = []

    for i, key in enumerate(all_keys):
        target = dest / key
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = requests.get(
                _s3_url(f"/{bucket_name}/{key}"),
                auth=(user, pw),
                timeout=60,
                stream=True,
            )
            if resp.status_code == 200:
                with open(target, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
            else:
                errors.append(key)
        except Exception:
            errors.append(key)

        if progress_callback and total:
            progress_callback(5 + int((i + 1) / total * 95))

    if progress_callback:
        progress_callback(100)

    if errors:
        return False, f"Backup partial — {len(errors)} object(s) failed."
    return True, f"Bucket '{bucket_name}' backed up to {dest}"


def restore_bucket(
    source_dir: Path,
    bucket_name: str,
    progress_callback=None,
) -> tuple[bool, str]:
    """Restore a bucket from a local mirror by uploading all local files."""
    import os
    source = Path(source_dir)
    if not source.exists():
        return False, f"Source directory not found: {source_dir}"

    user, pw = _auth()

    if progress_callback:
        progress_callback(5)

    # Ensure bucket exists
    requests.put(
        _s3_url(f"/{bucket_name}"),
        auth=(user, pw),
        timeout=10,
    )

    # Collect all files to upload
    all_files = [
        p for p in source.rglob("*") if p.is_file()
    ]
    total  = len(all_files)
    errors = []

    for i, fpath in enumerate(all_files):
        key = str(fpath.relative_to(source)).replace("\\", "/")
        try:
            with open(fpath, "rb") as f:
                resp = requests.put(
                    _s3_url(f"/{bucket_name}/{key}"),
                    data=f,
                    auth=(user, pw),
                    timeout=60,
                )
                if resp.status_code not in (200, 201):
                    errors.append(key)
        except Exception:
            errors.append(key)

        if progress_callback and total:
            progress_callback(5 + int((i + 1) / total * 95))

    if progress_callback:
        progress_callback(100)

    if errors:
        return False, f"Restore partial — {len(errors)} file(s) failed."
    return True, f"Bucket '{bucket_name}' restored."


def get_laravel_env(
    bucket_name: str,
    access_key: str,
    secret_key: str,
    endpoint: str,
    region: str = "us-east-1",
) -> str:
    """Generate ready-to-paste Laravel .env block for SeaweedFS S3."""
    return (
        f"FILESYSTEM_DISK=s3\n"
        f"AWS_ACCESS_KEY_ID={access_key}\n"
        f"AWS_SECRET_ACCESS_KEY={secret_key}\n"
        f"AWS_DEFAULT_REGION={region}\n"
        f"AWS_BUCKET={bucket_name}\n"
        f"AWS_ENDPOINT={endpoint}\n"
        f"AWS_USE_PATH_STYLE_ENDPOINT=true\n"
    )
