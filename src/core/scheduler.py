"""
scheduler.py - Automatic backup scheduler for PGOps.
Runs in a daemon thread. Config is persisted to AppData/PGOps/backup_schedule.json.
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional


DEFAULT_SCHEDULE = {
    "enabled": False,
    "frequency": "daily",   # "hourly" | "daily" | "weekly"
    "time": "02:00",        # HH:MM  (used for daily / weekly)
    "day_of_week": 0,       # 0=Monday (used for weekly)
    "keep_count": 7,        # backups to keep per database
    "databases": [],        # database names to back up
}


class BackupScheduler:
    def __init__(self, config_dir: Path, backup_fn: Callable, log_fn: Callable = None):
        """
        config_dir : writable directory — schedule saved here as backup_schedule.json
        backup_fn  : fn(dbname) -> (ok, msg, path)
        log_fn     : optional log callback
        """
        self.config_dir = Path(config_dir)
        self.backup_fn  = backup_fn
        self.log_fn     = log_fn or print
        self.schedule   = self._load()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run: Optional[datetime] = None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _file(self) -> Path:
        return self.config_dir / "backup_schedule.json"

    def _load(self) -> dict:
        f = self._file()
        if f.exists():
            try:
                data = json.loads(f.read_text())
                for k, v in DEFAULT_SCHEDULE.items():
                    data.setdefault(k, v)
                return data
            except Exception:
                pass
        return DEFAULT_SCHEDULE.copy()

    def save(self):
        self._file().write_text(json.dumps(self.schedule, indent=2))

    def update(self, **kwargs):
        """Update schedule keys, persist, and restart the thread if needed."""
        self.schedule.update(kwargs)
        self.save()
        self.stop()
        if self.schedule["enabled"]:
            self.start()

    # ── Thread control ────────────────────────────────────────────────────────

    def start(self):
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._log("[Scheduler] Started.")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Loop ─────────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_event.is_set():
            if self._should_run():
                self._run_backups()
                self._last_run = datetime.now()
            self._stop_event.wait(60)   # check every minute

    def _should_run(self) -> bool:
        now = datetime.now()
        if self._last_run and (now - self._last_run).total_seconds() < 55:
            return False
        freq = self.schedule["frequency"]
        if freq == "hourly":
            return now.minute == 0
        h, m = self._parse_time()
        if freq == "daily":
            return now.hour == h and now.minute == m
        if freq == "weekly":
            return now.weekday() == self.schedule["day_of_week"] and now.hour == h and now.minute == m
        return False

    def _parse_time(self) -> tuple:
        try:
            h, m = self.schedule["time"].split(":")
            return int(h), int(m)
        except Exception:
            return 2, 0

    def _run_backups(self):
        databases = self.schedule.get("databases", [])
        if not databases:
            self._log("[Scheduler] No databases configured.")
            return
        self._log(f"[Scheduler] Running backups for {len(databases)} database(s)...")
        for dbname in databases:
            try:
                ok, msg, *_ = self.backup_fn(dbname)
                self._log(f"[Scheduler] [{dbname}] {msg}")
                if ok:
                    self._prune(dbname)
            except Exception as e:
                self._log(f"[Scheduler] [{dbname}] Error: {e}")
        self._log("[Scheduler] Done.")

    def _prune(self, dbname: str):
        """Delete oldest backups beyond keep_count."""
        keep = max(1, self.schedule.get("keep_count", 7))
        try:
            from core.db_manager import BACKUP_DIR
            files = sorted(
                BACKUP_DIR.glob(f"{dbname}_*.dump"),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
            for old in files[keep:]:
                old.unlink(missing_ok=True)
                self._log(f"[Scheduler] Pruned {old.name}")
        except Exception as e:
            self._log(f"[Scheduler] Prune error: {e}")

    def _log(self, msg: str):
        self.log_fn(msg)

    # ── UI helpers ────────────────────────────────────────────────────────────

    def next_run_str(self) -> str:
        if not self.schedule["enabled"]:
            return "Disabled"
        freq = self.schedule["frequency"]
        now  = datetime.now()
        h, m = self._parse_time()
        if freq == "hourly":
            nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif freq == "daily":
            nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
        elif freq == "weekly":
            days = self.schedule["day_of_week"] - now.weekday()
            if days < 0 or (days == 0 and (now.hour, now.minute) >= (h, m)):
                days += 7
            nxt = (now + timedelta(days=days)).replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            return "Unknown"
        return nxt.strftime("%Y-%m-%d %H:%M")
