import json
import os
import platform
from pathlib import Path


def get_app_data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"

    d = base / "PGOps"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_FILE = get_app_data_dir() / "config.json"

DEFAULT_CONFIG = {
    "username": "postgres",
    "password": "postgres",
    "database": "mydb",
    "port": 5432,
    "autostart": False,
    "preferred_ip": "",

    # Caddy reverse-proxy ports.
    # 80/443 are the standard ports — no port suffix needed in URLs.
    # On Windows these require running PGOps as Administrator (or granting the
    # process permission via: netsh http add urlacl ...).
    # On macOS/Linux, set CAP_NET_BIND_SERVICE or run with sudo.
    # If you can't use privileged ports, change to 8080/8443 here.
    "caddy_http_port":  80,
    "caddy_https_port": 443,

    # Internal landing-page server (Caddy proxies pgops.local → here)
    "landing_port": 8080,

    # MinIO ports (direct binary, Caddy proxies subdomains to these)
    "minio_api_port":     9000,
    "minio_console_port": 9001,

    # pgAdmin port (when running)
    "pgadmin_port": 5050,
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
