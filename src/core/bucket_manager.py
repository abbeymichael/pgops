"""
bucket_manager.py
SeaweedFS bucket, credential, and object management.

Architecture
────────────
• Local SQLite store  (seaweedfs-data/pgops_storage.db)
  - Persists access key + secret so they survive restarts.
  - Makes credential lookup O(1) — no IAM walk per bucket.
  - Tracks bucket metadata (policy, created_at, app_name).

• SeaweedFS IAM API  (http://127.0.0.1:<s3_port>/?Action=…)
  - CreateUser / CreateAccessKey / AttachUserPolicy / DeleteUser etc.
  - Mirrors AWS IAM XML API.

• SeaweedFS S3 API   (http://127.0.0.1:<s3_port>/<bucket>)
  - Standard S3 REST: ListObjectsV2, PutObject, GetObject, DeleteObject,
    CreateMultipartUpload, UploadPart, CompleteMultipartUpload,
    DeleteObjects (multi-delete), GetBucketPolicy, PutBucketPolicy.

• Presigned URLs are generated locally using HMAC-SHA256 (AWS SigV4
  query-string signing) so they work with any S3-compatible client.

Authentication notes
────────────────────
  • All direct S3 API calls use AWS Signature V4 (Authorization header).
    SeaweedFS S3 does NOT recognise HTTP Basic Auth for S3 operations —
    a Basic Auth header is silently treated as anonymous, which causes
    403 AccessDenied on any mutating operation (CreateBucket, PutObject …).
  • The IAM API endpoint (/?Action=…) does accept Basic Auth and continues
    to use it via _iam().
  • _sigv4_headers() builds the required Authorization + x-amz-date +
    x-amz-content-sha256 headers for every direct S3 call.

S3 compatibility notes for apps migrating from MinIO
──────────────────────────────────────────────────────
  • Path-style endpoints only: AWS_USE_PATH_STYLE_ENDPOINT=true
  • Region: us-east-1  (SeaweedFS accepts any value; us-east-1 is safest)
  • Each bucket gets its own access key + secret scoped to that bucket only.
  • The admin credentials (from config) have full access — never expose them
    to app .env files; use the per-bucket credentials instead.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import string
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

import requests

# ── S3 XML namespace ──────────────────────────────────────────────────────────
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

# Bucket-size cache: {bucket_name: (timestamp, size_str)}
_SIZE_CACHE: dict[str, tuple[float, str]] = {}
_SIZE_CACHE_TTL = 120  # seconds


# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    from core.config import load_config
    return load_config()


def _s3_url(path: str = "") -> str:
    port = _cfg().get("seaweedfs_s3_port", 8333)
    return f"http://127.0.0.1:{port}{path}"


def _auth() -> tuple[str, str]:
    cfg = _cfg()
    return cfg.get("username", "postgres"), cfg.get("password", "postgres")


def _filer_url(path: str = "") -> str:
    port = _cfg().get("seaweedfs_filer_port", 8888)
    return f"http://127.0.0.1:{port}{path}"


# ── Local credential store ────────────────────────────────────────────────────

def _db_path() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "seaweedfs-data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "pgops_storage.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buckets (
            name        TEXT PRIMARY KEY,
            app_name    TEXT NOT NULL DEFAULT '',
            access_key  TEXT NOT NULL DEFAULT '',
            secret_key  TEXT NOT NULL DEFAULT '',
            policy_name TEXT NOT NULL DEFAULT '',
            is_public   INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _store_bucket(name: str, app_name: str, access_key: str,
                  secret_key: str, policy_name: str, is_public: bool):
    with _get_db() as conn:
        conn.execute("""
            INSERT INTO buckets (name, app_name, access_key, secret_key,
                                 policy_name, is_public)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                app_name   = excluded.app_name,
                access_key = excluded.access_key,
                secret_key = excluded.secret_key,
                policy_name= excluded.policy_name,
                is_public  = excluded.is_public
        """, (name, app_name, access_key, secret_key, policy_name,
              1 if is_public else 0))


def _update_bucket_policy_flag(name: str, is_public: bool):
    with _get_db() as conn:
        conn.execute(
            "UPDATE buckets SET is_public=? WHERE name=?",
            (1 if is_public else 0, name)
        )


def _remove_bucket_record(name: str):
    with _get_db() as conn:
        conn.execute("DELETE FROM buckets WHERE name=?", (name,))


def _get_bucket_record(name: str) -> Optional[dict]:
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM buckets WHERE name=?", (name,)
        ).fetchone()
        return dict(row) if row else None


def _all_bucket_records() -> dict[str, dict]:
    with _get_db() as conn:
        rows = conn.execute("SELECT * FROM buckets").fetchall()
        return {r["name"]: dict(r) for r in rows}


# ── Key / secret generators ───────────────────────────────────────────────────

def _gen_secret(length: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _gen_access_key(prefix: str = "") -> str:
    suffix = "".join(
        secrets.choice(string.ascii_uppercase + string.digits)
        for _ in range(12)
    )
    if prefix:
        clean = "".join(c for c in prefix.upper() if c.isalnum())[:8]
        return f"{clean}{suffix}"
    return suffix


# ── AWS Signature V4 — direct S3 request signing ─────────────────────────────
#
# SeaweedFS S3 requires AWS Signature V4 for authenticated operations.
# HTTP Basic Auth (requests' auth=(user, pw)) is silently treated as
# anonymous by the SeaweedFS S3 gateway, causing 403 on any mutating
# call (CreateBucket, PutObject, DeleteObject …).
#
# Usage:
#   headers = _sigv4_headers("PUT", f"/{bucket_name}", params={"policy": ""})
#   r = requests.put(url, params={"policy": ""}, data=body, headers=headers)
#
# Rules:
#   • Pass the same `params` dict to both _sigv4_headers and requests so
#     the canonical query string matches the URL that is actually sent.
#   • For extra S3 / x-amz-* headers that must be signed (e.g.
#     x-amz-copy-source), pass them via `amz_headers`.
#   • Content-Type, Content-MD5, Content-Length do NOT need to be signed;
#     add them to the dict returned by this function before passing to
#     requests (they are not included in the signature).
# ─────────────────────────────────────────────────────────────────────────────

def _sigv4_headers(
    method: str,
    path: str,
    params: dict | None = None,
    amz_headers: dict | None = None,
) -> dict:
    """
    Build AWS Signature V4 Authorization headers for a direct S3 request
    against the internal SeaweedFS endpoint.

    Returns a dict of HTTP headers ready to pass to requests. Merge any
    additional headers (Content-Type, Content-MD5 …) into the returned dict
    after calling this function; they are not included in the signature.
    """
    access_key, secret_key = _auth()
    region  = "us-east-1"
    service = "s3"
    port    = _cfg().get("seaweedfs_s3_port", 8333)
    host    = f"127.0.0.1:{port}"

    now        = datetime.now(timezone.utc)
    datestamp  = now.strftime("%Y%m%d")
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")

    # Use UNSIGNED-PAYLOAD so we never need to read file contents twice.
    # SeaweedFS honours this just like AWS does for streaming uploads.
    payload_hash = "UNSIGNED-PAYLOAD"

    # ── Canonical query string ────────────────────────────────────────────────
    # Must sort by encoded key name, then by encoded value.
    # quote(v, safe='') encodes everything except RFC 3986 unreserved chars
    # (A-Z a-z 0-9 - _ . ~), which is exactly what SigV4 requires.
    if params:
        canonical_qs = "&".join(
            f"{quote(str(k), safe='')}={quote(str(v), safe='')}"
            for k, v in sorted(params.items())
        )
    else:
        canonical_qs = ""

    # ── Headers to sign ───────────────────────────────────────────────────────
    headers_to_sign: dict[str, str] = {
        "host":                 host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date":           amz_date,
    }
    if amz_headers:
        for k, v in amz_headers.items():
            headers_to_sign[k.lower()] = v

    signed_header_names = ";".join(sorted(headers_to_sign))
    canonical_headers   = "".join(
        f"{k}:{v}\n" for k, v in sorted(headers_to_sign.items())
    )

    # ── Canonical request ─────────────────────────────────────────────────────
    canonical_request = "\n".join([
        method.upper(),
        path,
        canonical_qs,
        canonical_headers,
        signed_header_names,
        payload_hash,
    ])

    # ── String to sign ────────────────────────────────────────────────────────
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign   = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    # ── Signing key ───────────────────────────────────────────────────────────
    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(
            _sign(
                _sign(f"AWS4{secret_key}".encode(), datestamp),
                region,
            ),
            service,
        ),
        "aws4_request",
    )
    signature = hmac.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    # ── Return headers (host is set automatically by requests) ────────────────
    result: dict[str, str] = {
        "x-amz-date":           amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_header_names}, Signature={signature}"
        ),
    }
    # Re-include any caller-supplied amz_headers so they are sent on the wire
    # (they were already folded into the signature above).
    if amz_headers:
        result.update(amz_headers)

    return result


# ── IAM helper ────────────────────────────────────────────────────────────────
# The IAM API (/?Action=…) uses HTTP Basic Auth — keep as-is.

def _iam(action: str, params: dict) -> requests.Response:
    user, pw = _auth()
    return requests.post(
        _s3_url("/"),
        params={"Action": action, **params},
        auth=(user, pw),
        timeout=10,
    )


# ── Bucket operations ─────────────────────────────────────────────────────────

def list_buckets() -> list[dict]:
    """
    Return buckets visible to admin, enriched with local DB metadata.
    O(1) credential lookup per bucket — no IAM walk.
    """
    try:
        r = requests.get(
            _s3_url("/"),
            headers=_sigv4_headers("GET", "/"),
            timeout=10,
        )
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        records = _all_bucket_records()
        buckets = []
        for b in root.findall(".//s3:Bucket", _S3_NS):
            name = b.findtext("s3:Name", namespaces=_S3_NS)
            if not name:
                continue
            rec = records.get(name, {})
            buckets.append({
                "name":       name,
                "app_name":   rec.get("app_name", ""),
                "access_key": rec.get("access_key", ""),
                "secret_key": rec.get("secret_key", ""),
                "is_public":  bool(rec.get("is_public", 0)),
                "created_at": rec.get("created_at", ""),
            })
        return buckets
    except Exception:
        return []


def get_bucket_size(bucket_name: str, force: bool = False) -> str:
    """
    Sum object sizes via ListObjectsV2 with TTL cache so table refresh
    doesn't hammer S3 on every paint.
    """
    now = time.monotonic()
    if not force and bucket_name in _SIZE_CACHE:
        ts, val = _SIZE_CACHE[bucket_name]
        if now - ts < _SIZE_CACHE_TTL:
            return val

    total_bytes = 0
    continuation_token = None
    try:
        while True:
            params: dict = {"list-type": "2", "max-keys": "1000"}
            if continuation_token:
                params["continuation-token"] = continuation_token
            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                headers=_sigv4_headers("GET", f"/{bucket_name}", params=params),
                timeout=15,
            )
            if r.status_code != 200:
                break
            root = ET.fromstring(r.text)
            for obj in root.findall("s3:Contents", _S3_NS):
                try:
                    total_bytes += int(
                        obj.findtext("s3:Size", namespaces=_S3_NS) or "0"
                    )
                except ValueError:
                    pass
            truncated = (
                root.findtext("s3:IsTruncated", namespaces=_S3_NS) or "false"
            )
            if truncated.lower() != "true":
                break
            continuation_token = root.findtext(
                "s3:NextContinuationToken", namespaces=_S3_NS
            )
            if not continuation_token:
                break
    except Exception:
        result = "—"
        _SIZE_CACHE[bucket_name] = (now, result)
        return result

    if total_bytes < 1024:
        result = f"{total_bytes} B"
    elif total_bytes < 1024 ** 2:
        result = f"{total_bytes / 1024:.1f} KB"
    elif total_bytes < 1024 ** 3:
        result = f"{total_bytes / 1024 ** 2:.1f} MB"
    else:
        result = f"{total_bytes / 1024 ** 3:.2f} GB"

    _SIZE_CACHE[bucket_name] = (now, result)
    return result


def get_bucket_credentials(bucket_name: str) -> Optional[dict]:
    """O(1) lookup from local DB — returns full creds including secret."""
    return _get_bucket_record(bucket_name)


def get_bucket_policy(bucket_name: str) -> str:
    """Return 'public' or 'private' by querying the S3 bucket policy."""
    params = {"policy": ""}
    try:
        r = requests.get(
            _s3_url(f"/{bucket_name}"),
            params=params,
            headers=_sigv4_headers("GET", f"/{bucket_name}", params=params),
            timeout=10,
        )
        if r.status_code == 200:
            data = json.loads(r.text)
            for stmt in data.get("Statement", []):
                if stmt.get("Effect") == "Allow" and stmt.get("Principal") in (
                    "*", {"AWS": "*"}
                ):
                    return "public"
        return "private"
    except Exception:
        return "private"


def create_bucket(
    bucket_name: str,
    app_name: str = "",
    is_public: bool = False,
) -> tuple[bool, str, dict]:
    """
    Create a bucket + dedicated IAM user/policy. Stores credentials locally.
    Returns (ok, message, credentials_dict).
    """
    bucket_name = bucket_name.lower().replace(" ", "-").replace("_", "-")
    if len(bucket_name) < 3:
        return False, "Bucket name must be at least 3 characters.", {}

    # 1. Create the S3 bucket
    try:
        r = requests.put(
            _s3_url(f"/{bucket_name}"),
            headers=_sigv4_headers("PUT", f"/{bucket_name}"),
            timeout=10,
        )
        if r.status_code not in (200, 201, 204, 409):
            return False, f"Failed to create bucket: HTTP {r.status_code} — {r.text.strip()}", {}
    except Exception as e:
        return False, f"Failed to create bucket: {e}", {}

    # 2. Generate credentials
    access_key  = _gen_access_key(app_name or bucket_name)
    secret_key  = _gen_secret(40)
    policy_name = f"policy-{bucket_name}"

    # 3. IAM policy scoped to this bucket
    policy_document = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                "s3:ListBucket", "s3:GetBucketLocation",
                "s3:ListBucketMultipartUploads", "s3:ListMultipartUploadParts",
                "s3:AbortMultipartUpload",
            ],
            "Resource": [
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*",
            ],
        }],
    })

    steps = [
        ("CreatePolicy",    {"PolicyName": policy_name, "PolicyDocument": policy_document}),
        ("CreateUser",      {"UserName": access_key}),
        ("CreateAccessKey", {"UserName": access_key, "SecretKey": secret_key,
                             "AccessKeyId": access_key}),
        ("AttachUserPolicy",{"UserName": access_key,
                             "PolicyArn": f"arn:aws:iam:::policy/{policy_name}"}),
    ]
    for action, params in steps:
        try:
            r = _iam(action, params)
            if r.status_code not in (200, 201, 409):
                return False, f"{action} failed: HTTP {r.status_code} — {r.text.strip()}", {}
        except Exception as e:
            return False, f"{action} failed: {e}", {}

    # 4. Apply public policy if requested
    if is_public:
        _apply_public_policy(bucket_name)

    # 5. Persist to local DB
    _store_bucket(bucket_name, app_name, access_key, secret_key,
                  policy_name, is_public)

    creds = {
        "bucket":      bucket_name,
        "access_key":  access_key,
        "secret_key":  secret_key,
        "policy":      policy_name,
        "is_public":   is_public,
    }
    return True, f"Bucket '{bucket_name}' created successfully.", creds


def drop_bucket(bucket_name: str) -> tuple[bool, str]:
    """Remove bucket + all contents + IAM user + policy + local DB record."""
    policy_name = f"policy-{bucket_name}"
    rec         = _get_bucket_record(bucket_name)
    ak          = rec["access_key"] if rec else None

    # 1. Clean up IAM for the stored user
    if ak:
        for action, params in [
            ("DetachUserPolicy", {"UserName": ak,
                                  "PolicyArn": f"arn:aws:iam:::policy/{policy_name}"}),
            ("DeleteAccessKey",  {"UserName": ak, "AccessKeyId": ak}),
            ("DeleteUser",       {"UserName": ak}),
        ]:
            try:
                _iam(action, params)
            except Exception:
                pass

    # 2. Delete the IAM policy
    try:
        _iam("DeletePolicy",
             {"PolicyArn": f"arn:aws:iam:::policy/{policy_name}"})
    except Exception:
        pass

    # 3. Empty then delete the bucket
    _empty_bucket(bucket_name)
    try:
        r = requests.delete(
            _s3_url(f"/{bucket_name}"),
            headers=_sigv4_headers("DELETE", f"/{bucket_name}"),
            timeout=10,
        )
        if r.status_code not in (200, 204, 404):
            return False, f"Failed to delete bucket: HTTP {r.status_code} — {r.text.strip()}"
    except Exception as e:
        return False, f"Failed to delete bucket: {e}"

    # 4. Remove local record + cache
    _remove_bucket_record(bucket_name)
    _SIZE_CACHE.pop(bucket_name, None)

    return True, f"Bucket '{bucket_name}' and all its data have been removed."


def rotate_keys(
    bucket_name: str,
    old_access_key: str,
) -> tuple[bool, str, dict]:
    """Revoke old credentials, issue fresh ones, update local DB."""
    policy_name = f"policy-{bucket_name}"
    rec         = _get_bucket_record(bucket_name)
    app_name    = rec["app_name"] if rec else ""

    # Remove old IAM user
    for action, params in [
        ("DetachUserPolicy", {"UserName": old_access_key,
                              "PolicyArn": f"arn:aws:iam:::policy/{policy_name}"}),
        ("DeleteAccessKey",  {"UserName": old_access_key,
                              "AccessKeyId": old_access_key}),
        ("DeleteUser",       {"UserName": old_access_key}),
    ]:
        try:
            _iam(action, params)
        except Exception:
            pass

    # Create new credentials
    new_access_key = _gen_access_key(app_name or bucket_name)
    new_secret_key = _gen_secret(40)

    for action, params in [
        ("CreateUser",       {"UserName": new_access_key}),
        ("CreateAccessKey",  {"UserName": new_access_key,
                              "SecretKey": new_secret_key,
                              "AccessKeyId": new_access_key}),
        ("AttachUserPolicy", {"UserName": new_access_key,
                              "PolicyArn": f"arn:aws:iam:::policy/{policy_name}"}),
    ]:
        try:
            r = _iam(action, params)
            if r.status_code not in (200, 201):
                return False, f"{action} failed: HTTP {r.status_code}", {}
        except Exception as e:
            return False, f"{action} failed: {e}", {}

    _store_bucket(bucket_name, app_name, new_access_key, new_secret_key,
                  policy_name, bool(rec.get("is_public", False)) if rec else False)

    creds = {
        "bucket":     bucket_name,
        "access_key": new_access_key,
        "secret_key": new_secret_key,
    }
    return True, "Keys rotated successfully.", creds


def set_bucket_public(bucket_name: str) -> tuple[bool, str]:
    ok = _apply_public_policy(bucket_name)
    if ok:
        _update_bucket_policy_flag(bucket_name, True)
        return True, f"Bucket '{bucket_name}' is now public."
    return False, "Failed to apply public policy."


def set_bucket_private(bucket_name: str) -> tuple[bool, str]:
    params = {"policy": ""}
    try:
        r = requests.delete(
            _s3_url(f"/{bucket_name}"),
            params=params,
            headers=_sigv4_headers("DELETE", f"/{bucket_name}", params=params),
            timeout=10,
        )
        if r.status_code in (200, 204):
            _update_bucket_policy_flag(bucket_name, False)
            return True, f"Bucket '{bucket_name}' is now private."
        return False, f"HTTP {r.status_code}: {r.text.strip()}"
    except Exception as e:
        return False, str(e)


def _apply_public_policy(bucket_name: str) -> bool:
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
        }],
    })
    params = {"policy": ""}
    hdrs = _sigv4_headers("PUT", f"/{bucket_name}", params=params)
    hdrs["Content-Type"] = "application/json"
    try:
        r = requests.put(
            _s3_url(f"/{bucket_name}"),
            params=params,
            data=policy.encode(),
            headers=hdrs,
            timeout=10,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def _empty_bucket(bucket_name: str):
    """Delete all objects in a bucket so it can be removed."""
    import base64
    continuation_token = None
    while True:
        params: dict = {"list-type": "2", "max-keys": "1000"}
        if continuation_token:
            params["continuation-token"] = continuation_token
        try:
            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                headers=_sigv4_headers("GET", f"/{bucket_name}", params=params),
                timeout=15,
            )
            if r.status_code != 200:
                break
            root = ET.fromstring(r.text)
            keys = [
                c.findtext("s3:Key", namespaces=_S3_NS)
                for c in root.findall("s3:Contents", _S3_NS)
            ]
            if keys:
                objects_xml = "".join(
                    f"<Object><Key>{k}</Key></Object>" for k in keys if k
                )
                body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    f"<Delete>{objects_xml}</Delete>"
                ).encode("utf-8")
                md5 = base64.b64encode(
                    hashlib.md5(body).digest()
                ).decode()
                del_params = {"delete": ""}
                del_hdrs = _sigv4_headers(
                    "POST", f"/{bucket_name}", params=del_params
                )
                del_hdrs.update({
                    "Content-Type":   "application/xml",
                    "Content-MD5":    md5,
                    "Content-Length": str(len(body)),
                })
                requests.post(
                    _s3_url(f"/{bucket_name}"),
                    params=del_params,
                    data=body,
                    headers=del_hdrs,
                    timeout=30,
                )
            truncated = (
                root.findtext("s3:IsTruncated", namespaces=_S3_NS) or "false"
            )
            if truncated.lower() != "true":
                break
            continuation_token = root.findtext(
                "s3:NextContinuationToken", namespaces=_S3_NS
            )
            if not continuation_token:
                break
        except Exception:
            break


# ── Object operations ─────────────────────────────────────────────────────────

def list_objects(
    bucket_name: str,
    prefix: str = "",
    delimiter: str = "/",
    max_keys: int = 1000,
) -> dict:
    """
    List objects + common prefixes (virtual folders) in a bucket/prefix.

    Returns:
        {
          "prefixes": ["folder1/", "folder2/"],   # virtual folders
          "objects":  [
              {
                "key":           "folder1/file.jpg",
                "size":          12345,
                "size_str":      "12.1 KB",
                "last_modified": "2025-01-15 14:22:00",
                "etag":          "abc123",
                "is_folder":     False,
              },
              ...
          ],
          "truncated":            False,
          "next_continuation_token": None,
        }
    """
    params: dict = {
        "list-type": "2",
        "max-keys":  str(max_keys),
    }
    if prefix:
        params["prefix"] = prefix
    if delimiter:
        params["delimiter"] = delimiter

    try:
        r = requests.get(
            _s3_url(f"/{bucket_name}"),
            params=params,
            headers=_sigv4_headers("GET", f"/{bucket_name}", params=params),
            timeout=15,
        )
        if r.status_code != 200:
            return {"prefixes": [], "objects": [], "truncated": False,
                    "next_continuation_token": None,
                    "error": f"HTTP {r.status_code}"}
        root = ET.fromstring(r.text)

        prefixes = []
        for cp in root.findall("s3:CommonPrefixes", _S3_NS):
            p = cp.findtext("s3:Prefix", namespaces=_S3_NS)
            if p:
                prefixes.append(p)

        objects = []
        for c in root.findall("s3:Contents", _S3_NS):
            key  = c.findtext("s3:Key", namespaces=_S3_NS) or ""
            size = int(c.findtext("s3:Size", namespaces=_S3_NS) or "0")
            lm   = c.findtext("s3:LastModified", namespaces=_S3_NS) or ""
            etag = (c.findtext("s3:ETag", namespaces=_S3_NS) or "").strip('"')

            # Parse ISO 8601 → friendly string
            try:
                dt = datetime.fromisoformat(lm.replace("Z", "+00:00"))
                lm_str = dt.astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                lm_str = lm[:16] if len(lm) >= 16 else lm

            objects.append({
                "key":           key,
                "size":          size,
                "size_str":      _fmt_size(size),
                "last_modified": lm_str,
                "etag":          etag,
                "is_folder":     key.endswith("/") and size == 0,
            })

        truncated = (
            root.findtext("s3:IsTruncated", namespaces=_S3_NS) or "false"
        ).lower() == "true"
        next_token = root.findtext(
            "s3:NextContinuationToken", namespaces=_S3_NS
        )

        return {
            "prefixes":                  prefixes,
            "objects":                   objects,
            "truncated":                 truncated,
            "next_continuation_token":   next_token,
        }
    except Exception as e:
        return {"prefixes": [], "objects": [], "truncated": False,
                "next_continuation_token": None, "error": str(e)}


def upload_object(
    bucket_name: str,
    key: str,
    file_path: Path,
    progress_callback=None,
    multipart_threshold: int = 50 * 1024 * 1024,  # 50 MB
    part_size: int = 10 * 1024 * 1024,             # 10 MB
) -> tuple[bool, str]:
    """
    Upload a local file to bucket/key.
    Uses multipart upload for files > multipart_threshold.
    progress_callback(pct: int) is called with 0-100.
    """
    file_path = Path(file_path)
    file_size = file_path.stat().st_size

    if progress_callback:
        progress_callback(0)

    if file_size <= multipart_threshold:
        # Simple single-part upload
        try:
            hdrs = _sigv4_headers("PUT", f"/{bucket_name}/{key}")
            hdrs["Content-Length"] = str(file_size)
            with open(file_path, "rb") as f:
                r = requests.put(
                    _s3_url(f"/{bucket_name}/{key}"),
                    data=f,
                    headers=hdrs,
                    timeout=300,
                )
            if r.status_code in (200, 201):
                if progress_callback:
                    progress_callback(100)
                return True, f"Uploaded '{key}'."
            return False, f"Upload failed: HTTP {r.status_code} — {r.text.strip()}"
        except Exception as e:
            return False, f"Upload failed: {e}"

    # ── Multipart upload ───────────────────────────────────────────────────
    try:
        # Initiate
        init_params = {"uploads": ""}
        r = requests.post(
            _s3_url(f"/{bucket_name}/{key}"),
            params=init_params,
            headers=_sigv4_headers(
                "POST", f"/{bucket_name}/{key}", params=init_params
            ),
            timeout=30,
        )
        if r.status_code not in (200, 201):
            return False, f"Multipart initiate failed: HTTP {r.status_code}"
        root      = ET.fromstring(r.text)
        upload_id = root.findtext(".//{*}UploadId") or ""
        if not upload_id:
            return False, "Could not parse UploadId from multipart initiate."

        parts       = []
        part_number = 1
        uploaded    = 0

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(part_size)
                if not chunk:
                    break
                part_params = {
                    "partNumber": str(part_number),
                    "uploadId":   upload_id,
                }
                r = requests.put(
                    _s3_url(f"/{bucket_name}/{key}"),
                    params=part_params,
                    data=chunk,
                    headers=_sigv4_headers(
                        "PUT", f"/{bucket_name}/{key}", params=part_params
                    ),
                    timeout=120,
                )
                if r.status_code not in (200, 201):
                    # Abort on failure
                    abort_params = {"uploadId": upload_id}
                    requests.delete(
                        _s3_url(f"/{bucket_name}/{key}"),
                        params=abort_params,
                        headers=_sigv4_headers(
                            "DELETE", f"/{bucket_name}/{key}",
                            params=abort_params,
                        ),
                        timeout=10,
                    )
                    return False, f"Part {part_number} upload failed: HTTP {r.status_code}"
                etag = r.headers.get("ETag", "").strip('"')
                parts.append((part_number, etag))
                uploaded    += len(chunk)
                part_number += 1
                if progress_callback and file_size:
                    progress_callback(int(uploaded / file_size * 95))

        # Complete multipart
        parts_xml = "".join(
            f"<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>"
            for n, e in parts
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<CompleteMultipartUpload>{parts_xml}</CompleteMultipartUpload>"
        ).encode("utf-8")
        complete_params = {"uploadId": upload_id}
        complete_hdrs   = _sigv4_headers(
            "POST", f"/{bucket_name}/{key}", params=complete_params
        )
        complete_hdrs["Content-Type"] = "application/xml"
        r = requests.post(
            _s3_url(f"/{bucket_name}/{key}"),
            params=complete_params,
            data=body,
            headers=complete_hdrs,
            timeout=60,
        )
        if r.status_code in (200, 201):
            if progress_callback:
                progress_callback(100)
            return True, f"Uploaded '{key}' ({_fmt_size(file_size)})."
        return False, f"Multipart complete failed: HTTP {r.status_code} — {r.text.strip()}"
    except Exception as e:
        return False, f"Multipart upload failed: {e}"


def download_object(
    bucket_name: str,
    key: str,
    dest_path: Path,
    progress_callback=None,
) -> tuple[bool, str]:
    """Stream a single object to dest_path."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(0)
    try:
        r = requests.get(
            _s3_url(f"/{bucket_name}/{key}"),
            headers=_sigv4_headers("GET", f"/{bucket_name}/{key}"),
            stream=True,
            timeout=60,
        )
        if r.status_code != 200:
            return False, f"Download failed: HTTP {r.status_code}"
        total      = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(int(downloaded / total * 100))
        if progress_callback:
            progress_callback(100)
        return True, f"Downloaded to {dest_path}"
    except Exception as e:
        return False, f"Download failed: {e}"


def delete_objects(
    bucket_name: str,
    keys: list[str],
) -> tuple[bool, str]:
    """Delete one or more objects. Uses multi-delete for efficiency."""
    import base64

    if not keys:
        return True, "Nothing to delete."

    objects_xml = "".join(
        f"<Object><Key>{k}</Key></Object>" for k in keys
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Delete>{objects_xml}</Delete>"
    ).encode("utf-8")
    md5 = base64.b64encode(hashlib.md5(body).digest()).decode()

    params = {"delete": ""}
    hdrs   = _sigv4_headers("POST", f"/{bucket_name}", params=params)
    hdrs.update({
        "Content-Type":   "application/xml",
        "Content-MD5":    md5,
        "Content-Length": str(len(body)),
    })

    try:
        r = requests.post(
            _s3_url(f"/{bucket_name}"),
            params=params,
            data=body,
            headers=hdrs,
            timeout=30,
        )
        if r.status_code in (200, 204):
            return True, f"Deleted {len(keys)} object(s)."
        return False, f"Delete failed: HTTP {r.status_code} — {r.text.strip()}"
    except Exception as e:
        return False, f"Delete failed: {e}"


def delete_prefix(
    bucket_name: str,
    prefix: str,
    progress_callback=None,
) -> tuple[bool, str]:
    """Recursively delete all objects under a prefix (virtual folder delete)."""
    all_keys = []
    continuation_token = None

    # Collect all keys under prefix
    while True:
        params: dict = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if continuation_token:
            params["continuation-token"] = continuation_token
        try:
            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                headers=_sigv4_headers("GET", f"/{bucket_name}", params=params),
                timeout=15,
            )
            if r.status_code != 200:
                return False, f"Could not list prefix: HTTP {r.status_code}"
            root = ET.fromstring(r.text)
            for c in root.findall("s3:Contents", _S3_NS):
                k = c.findtext("s3:Key", namespaces=_S3_NS)
                if k:
                    all_keys.append(k)
            truncated = (
                root.findtext("s3:IsTruncated", namespaces=_S3_NS) or "false"
            ).lower() == "true"
            if not truncated:
                break
            continuation_token = root.findtext(
                "s3:NextContinuationToken", namespaces=_S3_NS
            )
            if not continuation_token:
                break
        except Exception as e:
            return False, f"List failed: {e}"

    if not all_keys:
        return True, f"Prefix '{prefix}' was already empty."

    # Delete in batches of 1000
    total  = len(all_keys)
    errors = 0
    for i in range(0, total, 1000):
        batch = all_keys[i:i + 1000]
        ok, _ = delete_objects(bucket_name, batch)
        if not ok:
            errors += len(batch)
        if progress_callback:
            progress_callback(int(min(i + 1000, total) / total * 100))

    if errors:
        return False, f"Deleted {total - errors}/{total} objects ({errors} failed)."
    return True, f"Deleted {total} object(s) under '{prefix}'."


def copy_object(
    src_bucket: str,
    src_key: str,
    dst_bucket: str,
    dst_key: str,
) -> tuple[bool, str]:
    """Server-side copy using the S3 CopyObject operation."""
    copy_source = f"/{src_bucket}/{src_key}"
    try:
        r = requests.put(
            _s3_url(f"/{dst_bucket}/{dst_key}"),
            headers=_sigv4_headers(
                "PUT", f"/{dst_bucket}/{dst_key}",
                amz_headers={"x-amz-copy-source": copy_source},
            ),
            timeout=60,
        )
        if r.status_code in (200, 201):
            return True, f"Copied to '{dst_key}'."
        return False, f"Copy failed: HTTP {r.status_code} — {r.text.strip()}"
    except Exception as e:
        return False, f"Copy failed: {e}"


def get_object_url(
    bucket_name: str,
    key: str,
    expires_in: int = 3600,
    use_public_endpoint: bool = True,
) -> str:
    """
    Generate a presigned GET URL (AWS SigV4 query-string signing).
    Works with any S3-compatible client.

    If the bucket is public, returns a plain unsigned URL.
    Otherwise returns a SigV4 presigned URL valid for `expires_in` seconds.
    """
    rec = _get_bucket_record(bucket_name)
    cfg = _cfg()

    # Determine base URL: use Caddy HTTPS if available, else raw internal
    caddy_port = cfg.get("caddy_https_port", 8443)
    import socket as _socket
    caddy_up = False
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(0.5)
        caddy_up = s.connect_ex(("127.0.0.1", caddy_port)) == 0
        s.close()
    except Exception:
        pass

    if caddy_up:
        port_suffix = f":{caddy_port}" if caddy_port != 443 else ""
        base_url = f"https://s3.pgops.local{port_suffix}"
    else:
        s3_port  = cfg.get("seaweedfs_s3_port", 8333)
        base_url = f"http://127.0.0.1:{s3_port}"

    # Public bucket → unsigned URL
    if rec and rec.get("is_public"):
        encoded_key = "/".join(quote(p, safe="") for p in key.split("/"))
        return f"{base_url}/{bucket_name}/{encoded_key}"

    # Private bucket → SigV4 presigned
    if not rec:
        return f"{base_url}/{bucket_name}/{key}"

    access_key = rec["access_key"]
    secret_key = rec["secret_key"]
    region     = "us-east-1"
    service    = "s3"

    now = datetime.now(timezone.utc)
    datestamp  = now.strftime("%Y%m%d")
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")

    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    credential       = f"{access_key}/{credential_scope}"

    encoded_key = "/".join(quote(p, safe="") for p in key.split("/"))
    host        = base_url.split("://", 1)[1]

    query_params = {
        "X-Amz-Algorithm":     "AWS4-HMAC-SHA256",
        "X-Amz-Credential":    credential,
        "X-Amz-Date":          amz_date,
        "X-Amz-Expires":       str(expires_in),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_querystring = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}"
        for k, v in sorted(query_params.items())
    )

    canonical_request = "\n".join([
        "GET",
        f"/{bucket_name}/{encoded_key}",
        canonical_querystring,
        f"host:{host}\n",
        "host",
        "UNSIGNED-PAYLOAD",
    ])

    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(
            _sign(
                _sign(f"AWS4{secret_key}".encode(), datestamp),
                region,
            ),
            service,
        ),
        "aws4_request",
    )
    signature = hmac.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    return (
        f"{base_url}/{bucket_name}/{encoded_key}"
        f"?{canonical_querystring}&X-Amz-Signature={signature}"
    )


# ── Folder helpers ────────────────────────────────────────────────────────────

def create_folder(bucket_name: str, prefix: str) -> tuple[bool, str]:
    """Create a virtual folder by uploading a zero-byte placeholder."""
    prefix = prefix.strip("/")
    if not prefix:
        return False, "Folder name cannot be empty."
    try:
        r = requests.put(
            _s3_url(f"/{bucket_name}/{prefix}/.keep"),
            data=b"",
            headers=_sigv4_headers("PUT", f"/{bucket_name}/{prefix}/.keep"),
            timeout=10,
        )
        if r.status_code in (200, 201):
            return True, f"Folder '{prefix}' created."
        return False, f"HTTP {r.status_code}: {r.text.strip()}"
    except Exception as e:
        return False, str(e)


# ── Backup / restore ──────────────────────────────────────────────────────────

def backup_bucket(
    bucket_name: str,
    dest_dir: Path,
    progress_callback=None,
) -> tuple[bool, str]:
    """Mirror a bucket to a local directory."""
    dest     = Path(dest_dir) / bucket_name
    dest.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(5)

    all_keys  = []
    cont_tok  = None
    try:
        while True:
            params: dict = {"list-type": "2", "max-keys": "1000"}
            if cont_tok:
                params["continuation-token"] = cont_tok
            r = requests.get(
                _s3_url(f"/{bucket_name}"),
                params=params,
                headers=_sigv4_headers("GET", f"/{bucket_name}", params=params),
                timeout=15,
            )
            if r.status_code != 200:
                return False, f"Could not list bucket: HTTP {r.status_code}"
            root = ET.fromstring(r.text)
            for c in root.findall("s3:Contents", _S3_NS):
                k = c.findtext("s3:Key", namespaces=_S3_NS)
                if k:
                    all_keys.append(k)
            if (root.findtext("s3:IsTruncated", namespaces=_S3_NS) or "").lower() != "true":
                break
            cont_tok = root.findtext("s3:NextContinuationToken", namespaces=_S3_NS)
            if not cont_tok:
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
                headers=_sigv4_headers("GET", f"/{bucket_name}/{key}"),
                stream=True,
                timeout=60,
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
    """Restore a bucket from a local mirror."""
    source = Path(source_dir)
    if not source.exists():
        return False, f"Source directory not found: {source_dir}"

    # Ensure the bucket exists
    requests.put(
        _s3_url(f"/{bucket_name}"),
        headers=_sigv4_headers("PUT", f"/{bucket_name}"),
        timeout=10,
    )

    all_files = [p for p in source.rglob("*") if p.is_file()]
    total     = len(all_files)
    errors    = []

    for i, fpath in enumerate(all_files):
        key = str(fpath.relative_to(source)).replace("\\", "/")
        ok, _ = upload_object(bucket_name, key, fpath)
        if not ok:
            errors.append(key)
        if progress_callback and total:
            progress_callback(int((i + 1) / total * 100))

    if progress_callback:
        progress_callback(100)
    if errors:
        return False, f"Restore partial — {len(errors)} file(s) failed."
    return True, f"Bucket '{bucket_name}' restored from {source_dir}"


# ── Laravel .env helper ───────────────────────────────────────────────────────

def get_laravel_env(
    bucket_name: str,
    access_key: str,
    secret_key: str,
    endpoint: str,
    region: str = "us-east-1",
) -> str:
    return (
        f"FILESYSTEM_DISK=s3\n"
        f"AWS_ACCESS_KEY_ID={access_key}\n"
        f"AWS_SECRET_ACCESS_KEY={secret_key}\n"
        f"AWS_DEFAULT_REGION={region}\n"
        f"AWS_BUCKET={bucket_name}\n"
        f"AWS_ENDPOINT={endpoint}\n"
        f"AWS_USE_PATH_STYLE_ENDPOINT=true\n"
    )


# ── Misc helpers ──────────────────────────────────────────────────────────────

def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    else:
        return f"{size / 1024 ** 3:.2f} GB"


def list_users() -> list[dict]:
    """List IAM users (used only for admin diagnostics)."""
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
        root    = ET.fromstring(r.text)
        ns_map  = {"iam": "https://iam.amazonaws.com/doc/2010-05-08/"}
        members = root.findall(".//iam:member", ns_map) or root.findall(".//member")
        users   = []
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