"""
ip_watcher.py
Background thread that monitors the host LAN IP and triggers updates when it changes.

When the IP changes:
  - mkcert certificate is regenerated (adds new IP to SAN)
  - Caddy config is reloaded
  - DNS server resolver IP is updated
  - mDNS broadcaster is restarted
  - Registered callbacks are called with the new IP

Usage:
    watcher = IPWatcher(
        get_ip_fn=manager.get_lan_ip,
        on_change_callbacks=[caddy.update_ip, dns.update_ip, ...],
        log_fn=self._log,
    )
    watcher.start()
    watcher.stop()
"""

import threading
import time
import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)


class IPWatcher:
    """
    Polls the current LAN IP every POLL_INTERVAL seconds.
    Fires on_change callbacks when the IP changes.
    """

    POLL_INTERVAL = 10   # seconds

    def __init__(
        self,
        get_ip_fn: Callable[[], str],
        on_change_callbacks: list[Callable[[str], None]] = None,
        log_fn: Callable[[str], None] = None,
    ):
        self._get_ip       = get_ip_fn
        self._callbacks    = on_change_callbacks or []
        self._log          = log_fn or print
        self._current_ip   = ""
        self._thread: Optional[threading.Thread] = None
        self._stop_event   = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._current_ip = self._get_ip()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="PGOps-IPWatcher",
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._stop_event.clear()

    def add_callback(self, fn: Callable[[str], None]):
        self._callbacks.append(fn)

    def current_ip(self) -> str:
        return self._current_ip

    def force_check(self):
        """Immediately check the IP and fire callbacks if changed."""
        new_ip = self._safe_get_ip()
        if new_ip and new_ip != self._current_ip and new_ip != "127.0.0.1":
            self._on_change(new_ip)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_event.is_set():
            new_ip = self._safe_get_ip()
            if new_ip and new_ip != self._current_ip and new_ip != "127.0.0.1":
                self._on_change(new_ip)
            self._stop_event.wait(self.POLL_INTERVAL)

    def _safe_get_ip(self) -> str:
        try:
            return self._get_ip()
        except Exception:
            return self._current_ip

    def _on_change(self, new_ip: str):
        old_ip = self._current_ip
        self._current_ip = new_ip
        self._log(f"[IPWatcher] IP changed: {old_ip} → {new_ip}")
        for cb in self._callbacks:
            try:
                cb(new_ip)
            except Exception as exc:
                self._log(f"[IPWatcher] Callback error: {exc}")
