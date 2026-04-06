"""
activity_monitor.py
Live PostgreSQL activity dashboard.
Shows active connections, database sizes, server stats.
All queries run in background threads — UI never blocks.
"""

import platform
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QSizePolicy, QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont


# ─── Worker ───────────────────────────────────────────────────────────────────
class StatsWorker(QThread):
    result = pyqtSignal(dict, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn(), "")
        except Exception as e:
            self.result.emit({}, str(e))


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _lbl(text, color="#94a3b8", size=12, bold=False):
    l = QLabel(text)
    style = f"color:{color};font-size:{size}px;"
    if bold:
        style += "font-weight:bold;"
    l.setStyleSheet(style)
    return l


def _card(title: str, value: str = "—", color: str = "#3b82f6") -> tuple[QWidget, QLabel]:
    """A small stat card widget. Returns (widget, value_label)."""
    w = QWidget()
    w.setStyleSheet(
        f"background:#0a1020;border:1px solid #1e293b;"
        f"border-radius:8px;padding:4px;"
    )
    v = QVBoxLayout(w)
    v.setContentsMargins(12, 10, 12, 10)
    v.setSpacing(4)

    t = QLabel(title)
    t.setStyleSheet("color:#64748b;font-size:11px;")

    val = QLabel(value)
    val.setStyleSheet(f"color:{color};font-size:20px;font-weight:700;")

    v.addWidget(t)
    v.addWidget(val)
    return w, val


TABLE_STYLE = """
QTableWidget{
    background:#0a1020;color:#e2e8f0;border:none;
    gridline-color:#1e293b;font-size:12px;
}
QTableWidget::item{padding:5px 8px;}
QTableWidget::item:selected{background:#1e293b;}
QTableWidget::item:alternate{background:#080f1e;}
QHeaderView::section{
    background:#0f172a;color:#475569;padding:6px 8px;
    border:none;border-bottom:1px solid #1e293b;
    font-size:11px;font-weight:bold;
}
"""


def _get_conn(host, port, user, password, dbname="postgres"):
    import psycopg2
    return psycopg2.connect(
        host=host, port=port, user=user,
        password=password, dbname=dbname,
        connect_timeout=4,
        options="-c statement_timeout=5000"
    )


# ─── Activity Monitor Widget ──────────────────────────────────────────────────
class ActivityMonitor(QWidget):
    """
    Instantiate with: ActivityMonitor(config)
    config = {"username":..., "password":..., "port":..., ...}
    """

    REFRESH_MS = 5000   # auto-refresh every 5 seconds

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config  = config
        self._conn   = None
        self._worker = None
        self._active = False

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        # Don't auto-start — only refresh when tab is visible

    # ── Public API ────────────────────────────────────────────────────────────

    def update_config(self, config: dict):
        self.config = config

    def start_monitoring(self):
        """Called when the tab becomes visible."""
        if not self._active:
            self._active = True
            self._refresh()
            self._timer.start(self.REFRESH_MS)

    def stop_monitoring(self):
        """Called when the tab is hidden."""
        self._active = False
        self._timer.stop()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background:#080f1e;border-bottom:1px solid #1e293b;")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(14, 0, 14, 0)
        bh.setSpacing(10)

        bh.addWidget(_lbl("Activity Monitor", "#e2e8f0", 13, bold=True))
        bh.addStretch()

        self.status_lbl = _lbl("Waiting for server...", "#475569", 11)
        bh.addWidget(self.status_lbl)

        self.btn_refresh = QPushButton("↻  Refresh Now")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setStyleSheet(
            "QPushButton{background:#1e293b;color:#94a3b8;border:none;"
            "border-radius:5px;padding:0 12px;font-size:12px;}"
            "QPushButton:hover{background:#334155;color:#fff;}"
        )
        self.btn_refresh.clicked.connect(self._refresh)
        bh.addWidget(self.btn_refresh)

        self.auto_lbl = _lbl("Auto-refresh: 5s", "#334155", 11)
        bh.addWidget(self.auto_lbl)

        root.addWidget(bar)

        # ── Stat cards ────────────────────────────────────────────────────────
        cards_widget = QWidget()
        cards_widget.setStyleSheet("background:#080f1e;border-bottom:1px solid #1e293b;")
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(14, 10, 14, 10)
        cards_layout.setSpacing(10)
        cards_widget.setFixedHeight(90)

        card_defs = [
            ("Active Connections", "#3b82f6"),
            ("Total Databases",    "#22c55e"),
            ("Cache Hit Ratio",    "#a78bfa"),
            ("Uptime",             "#f59e0b"),
            ("Transactions/s",     "#ec4899"),
        ]
        self._cards = {}
        for title, color in card_defs:
            w, val_lbl = _card(title, "—", color)
            cards_layout.addWidget(w)
            self._cards[title] = val_lbl

        root.addWidget(cards_widget)

        # ── Main content: connections + db sizes ──────────────────────────────
        content = QWidget()
        content.setStyleSheet("background:#0f172a;")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(14)

        # Active connections table
        conn_hdr = QLabel("Active Connections")
        conn_hdr.setStyleSheet("color:#64748b;font-size:11px;font-weight:bold;letter-spacing:1px;")
        cv.addWidget(conn_hdr)

        self.conn_table = QTableWidget(0, 6)
        self.conn_table.setHorizontalHeaderLabels([
            "PID", "Database", "User", "Application", "State", "Duration"
        ])
        self.conn_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.conn_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.conn_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.conn_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.conn_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.conn_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.conn_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.conn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conn_table.setAlternatingRowColors(True)
        self.conn_table.setStyleSheet(TABLE_STYLE)
        self.conn_table.verticalHeader().setVisible(False)
        self.conn_table.setMaximumHeight(200)
        cv.addWidget(self.conn_table)

        # Terminate connection button
        term_btn = QPushButton("Terminate Selected Connection")
        term_btn.setFixedHeight(30)
        term_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:#fca5a5;border:none;"
            "border-radius:5px;padding:0 12px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#991b1b;}"
        )
        term_btn.clicked.connect(self._terminate_connection)
        cv.addWidget(term_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1e293b;")
        cv.addWidget(sep)

        # Database sizes table
        db_hdr = QLabel("Database Sizes")
        db_hdr.setStyleSheet("color:#64748b;font-size:11px;font-weight:bold;letter-spacing:1px;")
        cv.addWidget(db_hdr)

        self.db_table = QTableWidget(0, 4)
        self.db_table.setHorizontalHeaderLabels([
            "Database", "Size", "Connections", "Cache Hit %"
        ])
        self.db_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.db_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.db_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.db_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.db_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.db_table.setAlternatingRowColors(True)
        self.db_table.setStyleSheet(TABLE_STYLE)
        self.db_table.verticalHeader().setVisible(False)
        cv.addWidget(self.db_table)

        root.addWidget(content)

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _refresh(self):
        if self._worker and self._worker.isRunning():
            return   # previous query still running, skip

        c = self.config

        def fetch():
            conn = _get_conn("127.0.0.1", c["port"], c["username"], c["password"])
            conn.autocommit = True
            cur = conn.cursor()

            # Active connections
            cur.execute("""
                SELECT pid,
                       datname,
                       usename,
                       application_name,
                       state,
                       COALESCE(
                           EXTRACT(EPOCH FROM (now() - query_start))::int::text || 's',
                           '—'
                       ) AS duration
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                  AND state IS NOT NULL
                ORDER BY query_start DESC NULLS LAST
            """)
            connections = cur.fetchall()

            # Database stats — each column explicitly aggregated, no GROUP BY issues
            cur.execute("""
                SELECT
                    d.datname,
                    pg_size_pretty(pg_database_size(d.datname)) AS size,
                    (SELECT COUNT(*) FROM pg_stat_activity sa
                     WHERE sa.datname = d.datname) AS conn_count,
                    CASE
                        WHEN COALESCE(sd.blks_hit, 0) + COALESCE(sd.blks_read, 0) = 0
                        THEN 'N/A'
                        ELSE ROUND(
                            100.0 * sd.blks_hit /
                            (sd.blks_hit + sd.blks_read), 1
                        )::text || '%%'
                    END AS cache_hit
                FROM pg_database d
                LEFT JOIN pg_stat_database sd ON sd.datname = d.datname
                WHERE d.datistemplate = false
                ORDER BY pg_database_size(d.datname) DESC
            """)
            databases = cur.fetchall()

            # Server stats — all subqueries, no aggregation conflicts
            cur.execute("""
                SELECT
                    (SELECT COUNT(*)
                     FROM pg_stat_activity
                     WHERE state = 'active') AS active_conns,

                    (SELECT COUNT(*)
                     FROM pg_database
                     WHERE datistemplate = false) AS total_dbs,

                    (SELECT ROUND(
                         100.0 * SUM(blks_hit) /
                         NULLIF(SUM(blks_hit + blks_read), 0), 1
                     ) FROM pg_stat_database) AS cache_hit,

                    (SELECT EXTRACT(EPOCH FROM
                         (now() - pg_postmaster_start_time())
                     )::bigint) AS uptime_secs,

                    (SELECT ROUND(
                         (SUM(xact_commit) + SUM(xact_rollback)) /
                         GREATEST(
                             EXTRACT(EPOCH FROM
                                 (now() - MIN(stats_reset))
                             ), 1
                         ), 1
                     ) FROM pg_stat_database
                     WHERE datname NOT IN ('template0','template1')
                    ) AS tps
            """)
            stats = cur.fetchone()

            cur.close()
            conn.close()

            return {
                "connections": connections,
                "databases":   databases,
                "stats":       stats,
            }

        self._worker = StatsWorker(fetch)
        self._worker.result.connect(self._on_data)
        self._worker.start()

    def _on_data(self, data: dict, error: str):
        if error:
            self.status_lbl.setText(f"Error: {error[:80]}")
            self.status_lbl.setStyleSheet("color:#ef4444;font-size:11px;")
            return

        self.status_lbl.setText("Live")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:11px;")

        stats = data.get("stats", ())
        if stats:
            active_conns, total_dbs, cache_hit, uptime_secs, tps = stats

            self._cards["Active Connections"].setText(str(active_conns or 0))
            self._cards["Total Databases"].setText(str(total_dbs or 0))
            self._cards["Cache Hit Ratio"].setText(
                f"{cache_hit}%" if cache_hit else "—"
            )
            # Format uptime
            if uptime_secs:
                secs = int(uptime_secs)
                h, m = divmod(secs // 60, 60)
                d, h = divmod(h, 24)
                if d > 0:
                    uptime_str = f"{d}d {h}h"
                elif h > 0:
                    uptime_str = f"{h}h {m}m"
                else:
                    uptime_str = f"{m}m"
                self._cards["Uptime"].setText(uptime_str)
            self._cards["Transactions/s"].setText(str(tps or "0"))

        # Populate connections table
        conns = data.get("connections", [])
        self.conn_table.setRowCount(0)
        state_colors = {
            "active":  "#22c55e",
            "idle":    "#64748b",
            "idle in transaction": "#f59e0b",
            "fastpath function call": "#a78bfa",
        }
        for row_data in conns:
            pid, dbname, user, app, state, duration = row_data
            row = self.conn_table.rowCount()
            self.conn_table.insertRow(row)
            items = [
                QTableWidgetItem(str(pid or "")),
                QTableWidgetItem(str(dbname or "")),
                QTableWidgetItem(str(user or "")),
                QTableWidgetItem(str(app or "")),
                QTableWidgetItem(str(state or "")),
                QTableWidgetItem(str(duration or "")),
            ]
            color = state_colors.get(state, "#94a3b8")
            items[4].setForeground(QColor(color))
            for i, item in enumerate(items):
                self.conn_table.setItem(row, i, item)

        # Populate database sizes table
        dbs = data.get("databases", [])
        self.db_table.setRowCount(0)
        for dbname, size, conn_count, cache_hit in dbs:
            row = self.db_table.rowCount()
            self.db_table.insertRow(row)
            self.db_table.setItem(row, 0, QTableWidgetItem(str(dbname)))
            self.db_table.setItem(row, 1, QTableWidgetItem(str(size)))
            self.db_table.setItem(row, 2, QTableWidgetItem(str(conn_count)))
            hit_item = QTableWidgetItem(str(cache_hit))
            # Color code cache hit
            if cache_hit and cache_hit != "—":
                try:
                    val = float(cache_hit.replace("%", ""))
                    color = "#22c55e" if val >= 90 else "#f59e0b" if val >= 70 else "#ef4444"
                    hit_item.setForeground(QColor(color))
                except Exception:
                    pass
            self.db_table.setItem(row, 3, hit_item)

    def _terminate_connection(self):
        row = self.conn_table.currentRow()
        if row < 0:
            return
        pid_item = self.conn_table.item(row, 0)
        if not pid_item:
            return
        pid = pid_item.text()

        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Terminate Connection",
            f"Terminate connection PID {pid}?\nThe client will receive a disconnection error.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        c = self.config
        def do_terminate():
            conn = _get_conn("127.0.0.1", c["port"], c["username"], c["password"])
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT pg_terminate_backend(%s)", (int(pid),))
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result

        w = StatsWorker(do_terminate)
        w.result.connect(lambda data, err: self._refresh())
        w.start()
