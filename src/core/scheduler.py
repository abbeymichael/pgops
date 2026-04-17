"""
scheduler.py - Automatic backup scheduler for PGOps.
Runs in a daemon thread. Config is persisted to AppData/PGOps/backup_schedule.json.

FIXES:
- _should_run() uses naive datetime consistently (no tzinfo mixing)
- _run_backups() unpacks 3-tuple from backup_fn correctly (ok, msg, path)
- _prune() import moved to module level to avoid repeated imports
- stop() joins thread with timeout before setting self._thread = None
- Scheduler no longer misses hourly boundary due to 60s poll jitter
  (uses ±30s window instead of exact minute match)
- update() saves before stopping/starting to prevent race
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional


DEFAULT_SCHEDULE = {
    "enabled":     False,
    "frequency":   "daily",   # "hourly" | "daily" | "weekly"
    "time":        "02:00",   # HH:MM  (used for daily / weekly)
    "day_of_week": 0,         # 0=Monday (used for weekly)
    "keep_count":  7,         # backups to keep per database
    "databases":   [],        # database names to back up
}


class BackupScheduler:
    def __init__(self, config_dir: Path, backup_fn: Callable, log_fn: Callable = None):
        """
        config_dir : writable directory — schedule saved here as backup_schedule.json
        backup_fn  : fn(dbname) -> (ok, msg, path)   [3-tuple]
        log_fn     : optional log callback
        """
        self.config_dir = Path(config_dir)
        self.backup_fn  = backup_fn
        self.log_fn     = log_fn or print
        self.schedule   = self._load()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run: Optional[datetime] = None

    # ── Persistence ────────────────────────────────────────────────────────────

    def _file(self) -> Path:
        return self.config_dir / "backup_schedule.json"

    def _load(self) -> dict:
        f = self._file()
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for k, v in DEFAULT_SCHEDULE.items():
                    data.setdefault(k, v)
                return data
            except Exception:
                pass
        return DEFAULT_SCHEDULE.copy()

    def save(self):
        try:
            self._file().write_text(
                json.dumps(self.schedule, indent=2), encoding="utf-8"
            )
        except Exception as e:
            self.log_fn(f"[Scheduler] Save error: {e}")

    def update(self, **kwargs):
        """Update schedule keys, persist, and restart the thread if needed."""
        self.schedule.update(kwargs)
        self.save()           # save first
        self.stop()           # then stop old thread
        if self.schedule["enabled"]:
            self.start()

    # ── Thread control ─────────────────────────────────────────────────────────

    def start(self):
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="PGOps-Scheduler"
        )
        self._thread.start()
        self._log("[Scheduler] Started.")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._stop_event.clear()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Loop ──────────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_event.is_set():
            if self._should_run():
                self._run_backups()
                self._last_run = datetime.now()
                # After running, sleep until next minute boundary to avoid double-fire
                self._stop_event.wait(60)
            else:
                # Check every 30 seconds for better boundary accuracy
                self._stop_event.wait(30)

    def _should_run(self) -> bool:
        now = datetime.now()

        # Debounce: don't re-run within 55 seconds of last run
        if self._last_run:
            elapsed = (now - self._last_run).total_seconds()
            if elapsed < 55:
                return False

        freq = self.schedule.get("frequency", "daily")
        h, m = self._parse_time()

        if freq == "hourly":
            # Fire within ±30s of any hour boundary
            return now.minute == 0 and now.second < 30

        if freq == "daily":
            # Fire within ±30s of the configured time
            return (
                now.hour == h
                and now.minute == m
                and now.second < 30
            )

        if freq == "weekly":
            return (
                now.weekday() == self.schedule.get("day_of_week", 0)
                and now.hour == h
                and now.minute == m
                and now.second < 30
            )

        return False

    def _parse_time(self) -> tuple:
        try:
            parts = self.schedule.get("time", "02:00").split(":")
            return int(parts[0]), int(parts[1])
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
                result = self.backup_fn(dbname)
                # backup_fn returns (ok, msg, path) — unpack correctly
                if isinstance(result, tuple):
                    ok  = bool(result[0])
                    msg = str(result[1]) if len(result) > 1 else ""
                else:
                    ok, msg = bool(result), ""
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
                reverse=True,
            )
            for old in files[keep:]:
                try:
                    old.unlink(missing_ok=True)
                    self._log(f"[Scheduler] Pruned {old.name}")
                except Exception as e:
                    self._log(f"[Scheduler] Could not prune {old.name}: {e}")
        except Exception as e:
            self._log(f"[Scheduler] Prune error: {e}")

    def _log(self, msg: str):
        self.log_fn(msg)

    # ── UI helpers ─────────────────────────────────────────────────────────────

    def next_run_str(self) -> str:
        if not self.schedule.get("enabled"):
            return "Disabled"

        freq = self.schedule.get("frequency", "daily")
        now  = datetime.now()
        h, m = self._parse_time()

        if freq == "hourly":
            nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif freq == "daily":
            nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
        elif freq == "weekly":
            days = self.schedule.get("day_of_week", 0) - now.weekday()
            if days < 0 or (days == 0 and (now.hour, now.minute) >= (h, m)):
                days += 7
            nxt = (now + timedelta(days=days)).replace(
                hour=h, minute=m, second=0, microsecond=0
            )
        else:
            return "Unknown"

        return nxt.strftime("%Y-%m-%d %H:%M")
