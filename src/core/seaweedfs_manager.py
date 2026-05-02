"""
seaweedfs_manager.py
Manages the SeaweedFS object storage server.
Mirrors the structure of the former minio_manager.py for consistency.

SeaweedFS architecture used here:
  - weed server   → combined master + volume + filer + S3 in one process
  - S3 API        → listens on 127.0.0.1:8333  (replaces MinIO port 9000)
  - filer HTTP    → listens on 127.0.0.1:8888  (replaces MinIO console port 9001)
  - master        → listens on 127.0.0.1:9333  (internal, not exposed externally)

URL strategy (post-Caddy/mkcert migration):
  - All external-facing URLs use the mkcert-secured Caddy subdomains:
      S3 API endpoint  → https://s3.pgops.local:<https_port>
      Filer console    → https://filer.pgops.local:<https_port>
  - SeaweedFS itself still listens on plain HTTP internally (127.0.0.1:8333).
    Caddy terminates TLS and reverse-proxies to it.
  - Laravel .env must use the HTTPS Caddy URL as AWS_ENDPOINT so that
    apps on the LAN can reach storage without certificate warnings.
  - The raw internal URL (http://127.0.0.1:8333) is only used for weed
    alias registration and internal health checks.

The weed shell client (bundled alongside the server binary as the same
executable) is used for all bucket/user/policy administration, mirroring
the role that mc (MinIO Client) played previously.
"""

import os
import sys
import subprocess
import platform
import shutil
import socket
import time
import requests
from pathlib import Path


# ── Download URLs ─────────────────────────────────────────────────────────────
# SeaweedFS releases a single binary that contains both the server and the
# shell client.  The binary name is just "weed" (or "weed.exe" on Windows).
SEAWEEDFS_DOWNLOAD = {
    "Windows": "https://github.com/seaweedfs/seaweedfs/releases/latest/download/windows_amd64.tar.gz",
    "Darwin":  "https://github.com/seaweedfs/seaweedfs/releases/latest/download/darwin_amd64.tar.gz",
}

# Bundled asset names (place in assets/ before building)
SEAWEEDFS_BUNDLED = {
    "Windows": "weed.exe",
    "Darwin":  "weed",
}


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        import subprocess as sp
        return {"creationflags": sp.CREATE_NO_WINDOW}
    return {}


def get_seaweedfs_dir() -> Path:
    """Directory where the weed binary lives."""
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "seaweedfs-bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_dir() -> Path:
    from core.pg_manager import get_app_data_dir
    d = get_app_data_dir() / "seaweedfs-data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_assets_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent.parent / "assets"


def _bin_path() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return get_seaweedfs_dir() / f"weed{ext}"


def weed_bin() -> Path:
    return _bin_path()


def is_binaries_available() -> bool:
    return weed_bin().exists()


class SeaweedFSManager:
    # Internal ports — SeaweedFS components
    S3_PORT     = 8333   # S3-compatible API  (replaces MinIO port 9000)
    FILER_PORT  = 8888   # Filer HTTP UI      (replaces MinIO console port 9001)
    MASTER_PORT = 9333   # Master server      (internal, not exposed via Caddy)

    def __init__(self, config: dict, log_fn=None):
        self.config = config
        self._log   = log_fn or print
        self._proc  = None

    def log(self, msg: str):
        self._log(msg)

    # ── Config properties ─────────────────────────────────────────────────────

    @property
    def admin_user(self) -> str:
        return self.config.get("username", "postgres")

    @property
    def admin_password(self) -> str:
        return self.config.get("password", "postgres")

    @property
    def s3_port(self) -> int:
        """Internal S3 API port (was minio_api_port)."""
        return self.config.get("seaweedfs_s3_port", self.S3_PORT)

    @property
    def filer_port(self) -> int:
        """Internal Filer HTTP port (was minio_console_port)."""
        return self.config.get("seaweedfs_filer_port", self.FILER_PORT)

    @property
    def master_port(self) -> int:
        """Internal master port — never exposed externally."""
        return self.config.get("seaweedfs_master_port", self.MASTER_PORT)

    @property
    def https_port(self) -> int:
        """Caddy HTTPS port — used to build the public-facing URLs."""
        return self.config.get("caddy_https_port", 8443)

    # ── Binary setup ──────────────────────────────────────────────────────────

    def is_binaries_available(self) -> bool:
        return weed_bin().exists()

    def setup_binaries(self, progress_callback=None) -> tuple[bool, str]:
        """
        Extract the weed binary from assets/ if available, otherwise download
        from the SeaweedFS GitHub releases page.
        """
        system = platform.system()
        dest   = weed_bin()

        if dest.exists():
            self.log("SeaweedFS binary already available.")
            if progress_callback:
                progress_callback(100)
            return True, "SeaweedFS binary ready."

        # ── Try bundled asset first ────────────────────────────────────────
        bundled_name = SEAWEEDFS_BUNDLED.get(system, "")
        if bundled_name:
            bundled = get_assets_dir() / bundled_name
            if bundled.exists():
                self.log("Extracting bundled SeaweedFS binary...")
                shutil.copy2(bundled, dest)
                if system != "Windows":
                    dest.chmod(0o755)
                if progress_callback:
                    progress_callback(100)
                return True, "SeaweedFS binary extracted from bundle."

        # ── Download from GitHub ───────────────────────────────────────────
        url = SEAWEEDFS_DOWNLOAD.get(system, "")
        if not url:
            return False, f"No download URL for SeaweedFS on {system}."

        self.log("Downloading SeaweedFS...")
        try:
            import tarfile, tempfile

            if progress_callback:
                progress_callback(5)

            resp = requests.get(url, stream=True, timeout=180)
            resp.raise_for_status()
            total      = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tf:
                tmp_path = tf.name
                for chunk in resp.iter_content(chunk_size=65536):
                    tf.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(5 + int(downloaded / total * 80))

            # Extract — the archive contains a single "weed" binary
            extract_dir = get_seaweedfs_dir() / "_extract"
            extract_dir.mkdir(exist_ok=True)

            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(extract_dir)

            weed_name = "weed.exe" if system == "Windows" else "weed"
            found = next(extract_dir.rglob(weed_name), None)

            if found and found.exists():
                shutil.copy2(found, dest)
                if system != "Windows":
                    dest.chmod(0o755)
                shutil.rmtree(extract_dir, ignore_errors=True)
                Path(tmp_path).unlink(missing_ok=True)
                if progress_callback:
                    progress_callback(100)
                return True, "SeaweedFS binary downloaded and installed."

            shutil.rmtree(extract_dir, ignore_errors=True)
            Path(tmp_path).unlink(missing_ok=True)
            return False, "SeaweedFS binary not found in downloaded archive."

        except Exception as e:
            return False, f"Failed to download SeaweedFS: {e}"

    # ── S3 credentials config file ────────────────────────────────────────────

    def _get_s3_config_path(self) -> Path:
        """
        SeaweedFS S3 needs a config JSON that declares access/secret keys.
        We store it next to the data directory.
        """
        d = get_data_dir()
        return d / "s3_config.json"

    def _write_s3_config(self):
        """
        Write (or overwrite) the s3_config.json that grants the admin user
        full access.  SeaweedFS reads this on startup via -s3.config=...
        """
        import json
        config = {
            "identities": [
                {
                    "name": self.admin_user,
                    "credentials": [
                        {
                            "accessKey": self.admin_user,
                            "secretKey": self.admin_password,
                        }
                    ],
                    "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                }
            ]
        }
        path = self._get_s3_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return path

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def is_running(self) -> bool:
        """Check if SeaweedFS S3 API is listening on its internal port."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", self.s3_port))
            s.close()
            return result == 0
        except Exception:
            return False

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            self.log("SeaweedFS already running.")
            return True, "SeaweedFS already running."

        if not is_binaries_available():
            return False, "SeaweedFS binary not found. Run setup first."

        data_dir   = get_data_dir()
        s3_cfg     = self._write_s3_config()

        # weed server launches master + volume + filer + S3 in one process.
        # Key flags:
        #   -dir               — where volume data is stored
        #   -s3                — enable S3 API
        #   -s3.port           — S3 API port
        #   -s3.config         — credentials / IAM config file
        #   -filer             — enable filer
        #   -filer.port        — filer HTTP port
        #   -master.port       — master port (internal)
        #   -volume.port       — volume port (internal, default 8080; shift to
        #                        avoid collision with landing server)
        cmd = [
            str(weed_bin()), "server",
            "-dir",              str(data_dir),
            "-master.port",      str(self.master_port),
            "-volume.port",      "8334",          # internal, not exposed
            "-filer",
            "-filer.port",       str(self.filer_port),
            "-s3",
            "-s3.port",          str(self.s3_port),
            "-s3.config",        str(s3_cfg),
            # Bind everything to loopback only
            "-ip",               "127.0.0.1",
        ]

        try:
            kwargs             = _popen_kwargs()
            kwargs["stdout"]   = subprocess.DEVNULL
            kwargs["stderr"]   = subprocess.DEVNULL
            self._proc         = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            return False, f"Failed to start SeaweedFS: {e}"

        for _ in range(40):
            time.sleep(0.5)
            if self.is_running():
                self.log(f"SeaweedFS started on S3 port {self.s3_port}.")
                return True, f"SeaweedFS started on S3 port {self.s3_port}."

        return False, "SeaweedFS did not start in time."

    def stop(self) -> tuple[bool, str]:
        if not self.is_running():
            return True, "SeaweedFS not running."

        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        if self.is_running():
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "weed.exe"],
                    capture_output=True, **_popen_kwargs(),
                )
            else:
                subprocess.run(["pkill", "-f", "weed server"], capture_output=True)

        self.log("SeaweedFS stopped.")
        return True, "SeaweedFS stopped."

    # ── URL helpers ───────────────────────────────────────────────────────────
    #
    # Rule: anything shown to the user or written into .env files uses the
    # HTTPS Caddy subdomain. The raw internal URL is only used for health
    # checks and direct weed shell calls inside this process.

    def _caddy_base(self, subdomain: str) -> str:
        """Return https://<subdomain>:<https_port> (omit port if 443)."""
        port = self.https_port
        if port == 443:
            return f"https://{subdomain}"
        return f"https://{subdomain}:{port}"

    def api_url(self) -> str:
        """
        Public HTTPS URL for the SeaweedFS S3 API — use this in .env files.
        Goes through Caddy → mkcert TLS.
        Caddy subdomain: s3.pgops.local  (was minio.pgops.local)
        """
        return self._caddy_base("s3.pgops.local")

    def console_url(self) -> str:
        """
        Public HTTPS URL for the SeaweedFS Filer UI — use this to open the
        browser.  Goes through Caddy → mkcert TLS.
        Caddy subdomain: filer.pgops.local  (was console.pgops.local)
        """
        return self._caddy_base("filer.pgops.local")

    def internal_api_url(self) -> str:
        """Raw internal S3 URL used only by health checks."""
        return f"http://127.0.0.1:{self.s3_port}"

    # Back-compat wrapper — callers that used endpoint_url() still work.
    def endpoint_url(self, use_local: bool = False) -> str:
        return self.api_url()

    # ── Bucket policy helpers ─────────────────────────────────────────────────
    #
    # SeaweedFS S3 does not bundle a separate client CLI like mc.
    # Bucket-level anonymous access is controlled via the S3 bucket-policy
    # REST API (PUT /<bucket>?policy).  We use the requests library so there
    # is no external binary dependency.

    def _s3_request(
        self,
        method: str,
        path: str,
        params: dict = None,
        data: bytes = None,
        headers: dict = None,
    ) -> requests.Response:
        """
        Issue a signed-ish request against the internal S3 endpoint.
        SeaweedFS accepts plain HTTP on localhost without SigV4 when the
        s3.config identities are used.  We pass HTTP Basic auth as a
        fallback; in practice SeaweedFS only requires the access/secret
        keys for operations that mutate IAM state, not for bucket policy.
        """
        url = f"http://127.0.0.1:{self.s3_port}{path}"
        return requests.request(
            method,
            url,
            params=params,
            data=data,
            headers=headers or {},
            auth=(self.admin_user, self.admin_password),
            timeout=10,
        )

    def set_bucket_public(self, bucket: str) -> tuple[bool, str]:
        """
        Make a bucket publicly readable (anonymous GET/LIST allowed).
        Applies an S3 bucket policy that grants s3:GetObject to everyone.
        """
        import json
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
        try:
            r = self._s3_request(
                "PUT",
                f"/{bucket}",
                params={"policy": ""},
                data=json.dumps(policy).encode(),
                headers={"Content-Type": "application/json"},
            )
            if r.status_code in (200, 204):
                return True, f"Bucket '{bucket}' is now public (read-only)."
            return False, f"HTTP {r.status_code}: {r.text.strip()}"
        except Exception as e:
            return False, str(e)

    def set_bucket_private(self, bucket: str) -> tuple[bool, str]:
        """
        Make a bucket private (no anonymous access).
        Deletes the bucket policy so only authenticated requests are allowed.
        """
        try:
            r = self._s3_request(
                "DELETE",
                f"/{bucket}",
                params={"policy": ""},
            )
            if r.status_code in (200, 204):
                return True, f"Bucket '{bucket}' is now private."
            return False, f"HTTP {r.status_code}: {r.text.strip()}"
        except Exception as e:
            return False, str(e)

    def get_bucket_policy(self, bucket: str) -> str:
        """
        Return 'public' or 'private'.
        GETs the bucket policy and inspects for a Principal=* Allow statement.
        """
        try:
            r = self._s3_request("GET", f"/{bucket}", params={"policy": ""})
            if r.status_code == 200:
                import json as _json
                data = _json.loads(r.text)
                for stmt in data.get("Statement", []):
                    if (
                        stmt.get("Effect") == "Allow"
                        and stmt.get("Principal") in ("*", {"AWS": "*"})
                    ):
                        return "public"
            return "private"
        except Exception:
            return "private"

    # ── Folder (prefix) helpers ───────────────────────────────────────────────
    #
    # S3 has no real folders — a "folder" is a key prefix ending in '/'.
    # We create one by uploading a zero-byte placeholder object: prefix/.keep

    def create_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        """
        Create a folder (prefix) inside a bucket by uploading a .keep
        placeholder via the S3 PUT Object API.
        `folder` should NOT have a leading slash. Trailing slash added here.
        """
        folder = folder.strip("/")
        if not folder:
            return False, "Folder name cannot be empty."

        key = f"{folder}/.keep"
        try:
            r = self._s3_request("PUT", f"/{bucket}/{key}", data=b"")
            if r.status_code in (200, 201):
                return True, f"Folder '{folder}' created in '{bucket}'."
            return False, f"HTTP {r.status_code}: {r.text.strip()}"
        except Exception as e:
            return False, str(e)

    def list_folders(self, bucket: str, prefix: str = "") -> list[str]:
        """
        List the immediate sub-folders (common prefixes) inside a
        bucket/prefix using the S3 ListObjectsV2 API with delimiter='/'.
        Returns a list of folder names (without trailing slash).
        """
        params = {
            "list-type": "2",
            "delimiter": "/",
            "max-keys":  "1000",
        }
        if prefix:
            params["prefix"] = prefix.strip("/") + "/"
        try:
            r = self._s3_request("GET", f"/{bucket}", params=params)
            if r.status_code != 200:
                return []
            import xml.etree.ElementTree as ET
            ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(r.text)
            folders = []
            for cp in root.findall("s3:CommonPrefixes", ns):
                p = cp.findtext("s3:Prefix", namespaces=ns) or ""
                # strip trailing slash and leading prefix
                name = p.rstrip("/")
                if prefix:
                    name = name[len(prefix.strip("/")) + 1:]
                if name:
                    folders.append(name)
            return folders
        except Exception:
            return []

    def delete_folder(self, bucket: str, folder: str) -> tuple[bool, str]:
        """
        Recursively delete a folder (prefix) and all objects under it.
        Uses ListObjectsV2 + Delete Objects (multi-delete).
        """
        folder = folder.strip("/") + "/"
        if folder == "/":
            return False, "Folder name cannot be empty."

        # List all objects under the prefix
        params = {
            "list-type": "2",
            "prefix":    folder,
            "max-keys":  "1000",
        }
        try:
            r = self._s3_request("GET", f"/{bucket}", params=params)
            if r.status_code != 200:
                return False, f"Could not list objects: HTTP {r.status_code}"

            import xml.etree.ElementTree as ET
            ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(r.text)
            keys = [
                c.findtext("s3:Key", namespaces=ns)
                for c in root.findall("s3:Contents", ns)
            ]

            if not keys:
                return True, f"Folder '{folder.rstrip('/')}' deleted (was already empty)."

            # Build a multi-delete XML body
            objects_xml = "".join(
                f"<Object><Key>{k}</Key></Object>" for k in keys if k
            )
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Delete>"
                f"{objects_xml}"
                "</Delete>"
            ).encode("utf-8")

            import hashlib, base64
            md5 = base64.b64encode(hashlib.md5(body).digest()).decode()

            dr = self._s3_request(
                "POST",
                f"/{bucket}",
                params={"delete": ""},
                data=body,
                headers={
                    "Content-Type":  "application/xml",
                    "Content-MD5":   md5,
                    "Content-Length": str(len(body)),
                },
            )
            if dr.status_code in (200, 204):
                return True, f"Folder '{folder.rstrip('/')}' deleted from '{bucket}'."
            return False, f"Delete failed: HTTP {dr.status_code}: {dr.text.strip()}"
        except Exception as e:
            return False, str(e)

    # ── Connection info (legacy) ──────────────────────────────────────────────

    def get_lan_ip(self) -> str:
        try:
            from core.network_info import get_all_interfaces, get_best_ip
            ifaces = get_all_interfaces()
            return get_best_ip(ifaces, self.config.get("preferred_ip", ""))
        except Exception:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return "127.0.0.1"
