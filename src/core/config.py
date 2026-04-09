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
    "username":         "postgres",
    "password":         "postgres",
    "database":         "mydb",
    "port":             5432,
    "autostart":        False,
    "preferred_ip":     "",
    "caddy_http_port":  80,
    "caddy_https_port": 443,
    "landing_port":     8080,
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
