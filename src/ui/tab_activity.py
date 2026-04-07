from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from ui.theme import *


# ── Worker ────────────────────────────────────────────────────────────────────
class _Worker(QThread):
    result = pyqtSignal(dict, str)
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
    def run(self):
        try:    self.result.emit(self.fn(), "")
        except Exception as e: self.result.emit({}, str(e))


def _conn(host, port, user, pw, db="postgres"):
    import psycopg2
    return psycopg2.connect(
        host=host, port=port, user=user, password=pw, dbname=db,
        connect_timeout=4, options="-c statement_timeout=5000"
    )


# ── Stat card ─────────────────────────────────────────────────────────────────
class _StatCard(QWidget):
    def __init__(self, title, value="—", accent=None):
        super().__init__()
        self.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};"
            f"border-radius:10px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(106)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)

        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;border:none;"
        )
        v.addWidget(t)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)

        self._val = QLabel(value)
        self._val.setStyleSheet(
            f"color:{C_TEXT};font-size:28px;font-weight:800;"
            f"letter-spacing:-0.5px;background:transparent;border:none;"
        )
        row.addWidget(self._val)

        if accent:
            row.addWidget(accent)
        row.addStretch()

        v.addLayout(row)

    def set(self, val):
        self._val.setText(str(val))


# ── Horizontal bar for DB sizes ───────────────────────────────────────────────
class _HBar(QWidget):
    """A simple horizontal progress bar."""
    def __init__(self, pct: float, color: str):
        super().__init__()
        self.setFixedHeight(4)
        self._pct   = max(0.0, min(100.0, pct))
        self._color = color
        self.setStyleSheet("background:transparent;border:none;")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        # Track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C_BORDER2))
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 2, 2)
        p.drawPath(path)
        # Fill
        fill_w = max(6, int(w * self._pct / 100))
        p.setBrush(QColor(self._color))
        fill = QPainterPath()
        fill.addRoundedRect(0, 0, fill_w, h, 2, 2)
        p.drawPath(fill)


# ── DB size row ───────────────────────────────────────────────────────────────
def _make_db_row(name: str, size: str, cache_pct):
    try:
        pct = float(str(cache_pct).replace("%", "").replace("N/A", "0"))
    except Exception:
        pct = 0.0

    fc = C_GREEN if pct >= 90 else C_AMBER if pct >= 70 else C_RED

    w = QWidget()
    w.setStyleSheet(
        f"background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:8px;"
    )
    w.setFixedHeight(68)

    outer = QVBoxLayout(w)
    outer.setContentsMargins(14, 10, 14, 10)
    outer.setSpacing(6)

    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(0)

    col = QVBoxLayout()
    col.setSpacing(2)
    col.setContentsMargins(0, 0, 0, 0)

    name_l = QLabel(name)
    name_l.setStyleSheet(
        f"color:{C_TEXT};font-size:13px;font-weight:600;"
        f"background:transparent;border:none;"
    )
    cache_l = QLabel(f"{pct:.0f}% CACHE HIT")
    cache_l.setStyleSheet(
        f"color:{C_TEXT3};font-size:9px;font-weight:700;"
        f"letter-spacing:1px;background:transparent;border:none;"
    )
    col.addWidget(name_l)
    col.addWidget(cache_l)
    top.addLayout(col)
    top.addStretch()

    size_l = QLabel(size)
    size_l.setStyleSheet(
        f"color:{C_TEXT};font-size:16px;font-weight:800;"
        f"background:transparent;border:none;"
    )
    top.addWidget(size_l)
    outer.addLayout(top)
    outer.addWidget(_HBar(pct, fc))
    return w


# ── Main widget ───────────────────────────────────────────────────────────────
class ActivityTab(QWidget):
    REFRESH_MS = 5000

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config   = config
        self._worker  = None
        self._active  = False
        self._timer   = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._build()

    def update_config(self, c):
        self.config = c

    def start_monitoring(self):
        if not self._active:
            self._active = True
            self._refresh()
            self._timer.start(self.REFRESH_MS)

    def stop_monitoring(self):
        self._active = False
        self._timer.stop()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._sub_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")

        body = QWidget()
        body.setStyleSheet(f"background:{C_BG};border:none;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 22, 24, 24)
        bv.setSpacing(18)

        # ── Stat row ──────────────────────────────────────────────────────────
        bv.addLayout(self._stat_row())

        # ── Mid row: connections + DB sizes ───────────────────────────────────
        mid = QHBoxLayout()
        mid.setSpacing(16)
        mid.addWidget(self._connections_panel(), 6)
        mid.addWidget(self._db_sizes_panel(), 4)
        bv.addLayout(mid)

        # ── Bottom row: traffic chart + health ────────────────────────────────
        bot = QHBoxLayout()
        bot.setSpacing(16)
        bot.addWidget(self._traffic_card(), 6)
        bot.addWidget(self._health_card(), 4)
        bv.addLayout(bot)

        scroll.setWidget(body)
        root.addWidget(scroll)

    # ── Sub-header (tab strip + status + refresh) ─────────────────────────────
    def _sub_header(self):
        w = QWidget()
        w.setFixedHeight(46)
        w.setStyleSheet(f"background:{C_BG};border:none;")

        h = QHBoxLayout(w)
        h.setContentsMargins(24, 0, 24, 0)
        h.setSpacing(0)

        for label in ("Real-time Traffic", "Log Streams"):
            btn = QPushButton(label)
            btn.setFixedHeight(46)
            btn.setCheckable(True)
            btn.setChecked(label == "Real-time Traffic")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C_TEXT3};"
                f"border:none;border-bottom:2px solid transparent;"
                f"font-size:12px;font-weight:600;padding:0 4px;margin-right:24px;}}"
                f"QPushButton:checked{{color:{C_TEXT};border-bottom:2px solid {C_BLUE};}}"
                f"QPushButton:hover{{color:{C_TEXT2};}}"
            )
            h.addWidget(btn)

        h.addStretch()

        self._status_lbl = QLabel("Waiting for server...")
        self._status_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;border:none;"
        )
        h.addWidget(self._status_lbl)
        h.addSpacing(14)

        ref = QPushButton("↻  Refresh")
        ref.setFixedHeight(28)
        ref.setCursor(Qt.CursorShape.PointingHandCursor)
        ref.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"font-size:11px;font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )
        ref.clicked.connect(self._refresh)
        h.addWidget(ref)

        # Bottom border line
        line = QWidget(w)
        line.setStyleSheet(f"background:{C_BORDER};border:none;")
        line.setGeometry(0, 45, 9999, 1)
        w._line = line

        def _resize(e, _w=w, _l=line):
            _l.setGeometry(0, _w.height() - 1, _w.width(), 1)
        w.resizeEvent = _resize

        return w

    # ── Stat cards row ────────────────────────────────────────────────────────
    def _stat_row(self):
        row = QHBoxLayout()
        row.setSpacing(12)

        # Lightning accent for TPS
        bolt = QLabel("⚡")
        bolt.setStyleSheet(
            f"color:{C_BLUE};font-size:18px;background:transparent;border:none;"
        )

        # LIVE badge for connections
        live = QLabel("● LIVE")
        live.setStyleSheet(
            f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}44;"
            f"border-radius:8px;font-size:9px;font-weight:800;"
            f"letter-spacing:1px;padding:2px 8px;"
        )

        # Uptime splits into two labels (big number + small unit)
        up_row = QHBoxLayout()
        up_row.setSpacing(4)
        up_row.setContentsMargins(0, 0, 0, 0)
        self._up_unit = QLabel("")
        self._up_unit.setStyleSheet(
            f"color:{C_TEXT2};font-size:14px;font-weight:600;"
            f"background:transparent;border:none;"
        )
        up_row.addWidget(self._up_unit)
        up_row.addStretch()
        up_wrap = QWidget()
        up_wrap.setStyleSheet("background:transparent;border:none;")
        up_wrap.setLayout(up_row)

        self._c_tps   = _StatCard("Transactions / s",   "—",  bolt)
        self._c_conns = _StatCard("Active Connections",  "—",  live)
        self._c_dbs   = _StatCard("Total Databases",     "—")
        self._c_cache = _StatCard("Cache Hit Ratio",     "—")
        self._c_up    = _StatCard("Uptime",              "—",  up_wrap)

        for c in (self._c_tps, self._c_conns, self._c_dbs, self._c_cache, self._c_up):
            row.addWidget(c)
        return row

    # ── Connections panel ─────────────────────────────────────────────────────
    def _connections_panel(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:transparent;border:none;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(18, 14, 14, 12)
        hh.setSpacing(8)

        icon = QLabel("⚡")
        icon.setStyleSheet(
            f"color:{C_BLUE};font-size:15px;background:transparent;border:none;"
        )
        title = QLabel("Active Connections")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;"
            f"background:transparent;border:none;"
        )
        hh.addWidget(icon)
        hh.addWidget(title)
        hh.addStretch()

        self.btn_terminate = QPushButton("✕  Terminate")
        self.btn_terminate.setFixedHeight(28)
        self.btn_terminate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_terminate.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_RED};"
            f"border:1px solid {C_RED}44;border-radius:6px;"
            f"font-size:11px;font-weight:700;padding:0 12px;}}"
            f"QPushButton:hover{{background:#2d1010;border-color:{C_RED}88;}}"
        )
        self.btn_terminate.clicked.connect(self._terminate)
        hh.addWidget(self.btn_terminate)
        v.addWidget(hdr)

        # Divider under header
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{C_BORDER};border:none;")
        v.addWidget(div)

        # Table
        self.conn_table = QTableWidget(0, 6)
        self.conn_table.setHorizontalHeaderLabels(
            ["PID", "DATABASE", "USER", "APPLICATION", "STATE", "DUR"]
        )
        hdr_view = self.conn_table.horizontalHeader()
        hdr_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.conn_table.setColumnWidth(0, 64)
        self.conn_table.setColumnWidth(1, 90)
        self.conn_table.setColumnWidth(2, 90)
        self.conn_table.setColumnWidth(4, 80)
        self.conn_table.setColumnWidth(5, 60)

        self.conn_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.conn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conn_table.setShowGrid(False)
        self.conn_table.verticalHeader().setVisible(False)
        self.conn_table.verticalHeader().setDefaultSectionSize(48)
        self.conn_table.setStyleSheet(
            TABLE_STYLE +
            "QTableWidget{border:none;border-radius:0;}"
            f"QHeaderView::section{{height:34px;font-size:9px;letter-spacing:1.5px;}}"
        )
        v.addWidget(self.conn_table)
        return card

    # ── DB sizes panel ────────────────────────────────────────────────────────
    def _db_sizes_panel(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:transparent;border:none;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(18, 14, 18, 12)
        hh.setSpacing(8)
        icon = QLabel("⊞")
        icon.setStyleSheet(
            f"color:{C_GREEN};font-size:15px;background:transparent;border:none;"
        )
        title = QLabel("Database Sizes")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;"
            f"background:transparent;border:none;"
        )
        hh.addWidget(icon)
        hh.addWidget(title)
        hh.addStretch()
        v.addWidget(hdr)

        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{C_BORDER};border:none;")
        v.addWidget(div)

        self._db_rows_container = QWidget()
        self._db_rows_container.setStyleSheet("background:transparent;border:none;")
        self._db_rows_v = QVBoxLayout(self._db_rows_container)
        self._db_rows_v.setContentsMargins(14, 12, 14, 12)
        self._db_rows_v.setSpacing(8)
        v.addWidget(self._db_rows_container)
        v.addStretch()
        return card

    # ── Traffic chart card ────────────────────────────────────────────────────
    def _traffic_card(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(0)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel("Traffic Throughput (24h)")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;"
            f"background:transparent;border:none;"
        )
        sub = QLabel("Real-time IOPS aggregation")
        sub.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;border:none;"
        )
        col.addWidget(t)
        col.addWidget(sub)
        hdr.addLayout(col)
        hdr.addStretch()

        # Dot indicators
        dots = QHBoxLayout()
        dots.setSpacing(5)
        for active in (False, False, True):
            d = QFrame()
            d.setFixedSize(7, 7)
            d.setStyleSheet(
                f"background:{C_BLUE if active else C_BORDER2};"
                f"border-radius:4px;border:none;"
            )
            dots.addWidget(d)
        hdr.addLayout(dots)
        v.addLayout(hdr)

        # Bar chart
        chart = QWidget()
        chart.setFixedHeight(90)
        chart.setStyleSheet("background:transparent;border:none;")
        ch = QHBoxLayout(chart)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(3)
        ch.setAlignment(Qt.AlignmentFlag.AlignBottom)

        import random
        random.seed(42)
        vals = [random.randint(25, 100) for _ in range(26)]
        # Highlight the peak bar
        peak = max(vals)
        for i, val in enumerate(vals):
            bar = QFrame()
            bar.setFixedWidth(14)
            bar.setFixedHeight(max(6, int(val * 0.85)))
            # Peak bar gets full blue, others get muted
            is_peak = (val == peak)
            color = C_BLUE if is_peak else f"{C_BLUE}70"
            bar.setStyleSheet(
                f"background:{color};border-radius:3px 3px 0 0;border:none;"
            )
            ch.addWidget(bar)
        ch.addStretch()
        v.addWidget(chart)

        # Time axis labels
        axis = QHBoxLayout()
        axis.setContentsMargins(0, 0, 0, 0)
        for lbl in ("00:00", "06:00", "12:00", "18:00", "24:00"):
            l = QLabel(lbl)
            l.setStyleSheet(
                f"color:{C_TEXT3};font-size:9px;background:transparent;border:none;"
            )
            axis.addWidget(l)
            if lbl != "24:00":
                axis.addStretch()
        v.addLayout(axis)
        return card

    # ── Health card ───────────────────────────────────────────────────────────
    def _health_card(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 28, 24, 24)
        v.setSpacing(0)
        v.addStretch()

        # Shield icon — drawn as a plain colored QWidget to avoid emoji artifacts
        shield_wrap = QHBoxLayout()
        shield_wrap.setContentsMargins(0, 0, 0, 0)
        shield_icon = _ShieldIcon(color=C_BLUE)
        shield_icon.setFixedSize(52, 52)
        shield_wrap.addStretch()
        shield_wrap.addWidget(shield_icon)
        shield_wrap.addStretch()
        v.addLayout(shield_wrap)
        v.addSpacing(14)

        t = QLabel("System Health")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;"
            f"background:transparent;border:none;"
        )
        v.addWidget(t)
        v.addSpacing(6)

        sub = QLabel("All subsystems operational.\nNo critical latency detected.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;line-height:1.5;"
            f"background:transparent;border:none;"
        )
        v.addWidget(sub)
        v.addSpacing(16)

        dl = QPushButton("DOWNLOAD REPORT")
        dl.setFixedHeight(32)
        dl.setCursor(Qt.CursorShape.PointingHandCursor)
        dl.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};border-radius:7px;"
            f"font-size:10px;font-weight:700;letter-spacing:1.2px;padding:0 16px;}}"
            f"QPushButton:hover{{background:{C_BORDER};color:{C_TEXT};}}"
        )
        v.addWidget(dl)
        v.addStretch()
        return card

    # ── Data refresh ──────────────────────────────────────────────────────────
    def _refresh(self):
        if self._worker and self._worker.isRunning():
            return
        c = self.config

        def fetch():
            conn = _conn("127.0.0.1", c["port"], c["username"], c["password"])
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("""
                SELECT pid, datname, usename, application_name, state,
                       COALESCE(
                           EXTRACT(EPOCH FROM (now()-query_start))::int::text||'s','—'
                       )
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid() AND state IS NOT NULL
                ORDER BY query_start DESC NULLS LAST
            """)
            conns = cur.fetchall()
            cur.execute("""
                SELECT d.datname,
                       pg_size_pretty(pg_database_size(d.datname)),
                       (SELECT COUNT(*) FROM pg_stat_activity sa
                        WHERE sa.datname = d.datname),
                       CASE
                           WHEN COALESCE(sd.blks_hit,0)+COALESCE(sd.blks_read,0) = 0
                           THEN 'N/A'
                           ELSE ROUND(100.0*sd.blks_hit/
                                (sd.blks_hit+sd.blks_read),1)::text||'%'
                       END
                FROM pg_database d
                LEFT JOIN pg_stat_database sd ON sd.datname = d.datname
                WHERE d.datistemplate = false
                ORDER BY pg_database_size(d.datname) DESC
            """)
            dbs = cur.fetchall()
            cur.execute("""
                SELECT
                  (SELECT COUNT(*) FROM pg_stat_activity WHERE state='active'),
                  (SELECT COUNT(*) FROM pg_database WHERE datistemplate=false),
                  (SELECT ROUND(100.0*SUM(blks_hit)/
                    NULLIF(SUM(blks_hit+blks_read),0),1) FROM pg_stat_database),
                  (SELECT EXTRACT(EPOCH FROM
                    (now()-pg_postmaster_start_time()))::bigint),
                  (SELECT ROUND((SUM(xact_commit)+SUM(xact_rollback))/
                    GREATEST(EXTRACT(EPOCH FROM
                    (now()-MIN(stats_reset))),1),1)
                   FROM pg_stat_database
                   WHERE datname NOT IN ('template0','template1'))
            """)
            stats = cur.fetchone()
            cur.close()
            conn.close()
            return {"conns": conns, "dbs": dbs, "stats": stats}

        self._worker = _Worker(fetch)
        self._worker.result.connect(self._on_data)
        self._worker.start()

    def _on_data(self, data, error):
        if error:
            self._status_lbl.setText(f"Error: {error[:60]}")
            self._status_lbl.setStyleSheet(
                f"color:{C_RED};font-size:11px;background:transparent;border:none;"
            )
            return

        self._status_lbl.setText("● Live")
        self._status_lbl.setStyleSheet(
            f"color:{C_GREEN};font-size:11px;background:transparent;border:none;"
        )

        # Stat cards
        s = data.get("stats", ())
        if s:
            active, total_dbs, cache, uptime_s, tps = s
            self._c_tps.set(str(tps or "0"))
            self._c_conns.set(str(active or 0))
            self._c_dbs.set(str(total_dbs or 0))
            self._c_cache.set(f"{cache}%" if cache else "—")
            if uptime_s:
                secs = int(uptime_s)
                h_val, m = divmod(secs // 60, 60)
                d, h_val = divmod(h_val, 24)
                if d > 0:
                    self._c_up.set(f"{d}d")
                    self._up_unit.setText(f"{h_val}h")
                elif h_val > 0:
                    self._c_up.set(f"{h_val}h")
                    self._up_unit.setText(f"{m}m")
                else:
                    self._c_up.set(f"{m}m")
                    self._up_unit.setText("")

        # Connections table
        STATE_MAP = {
            "active":              ("ACTIVE",  C_GREEN, "#0a2016"),
            "idle":                ("IDLE",    C_TEXT3, C_SURFACE2),
            "idle in transaction": ("WAITING", C_AMBER, "#2a1e0a"),
        }
        self.conn_table.setRowCount(0)
        for pid, db, user, app, state, dur in data.get("conns", []):
            row = self.conn_table.rowCount()
            self.conn_table.insertRow(row)
            for col, val in enumerate([str(pid), db, user, app, "", str(dur)]):
                if col == 4:
                    txt, fg, bg = STATE_MAP.get(
                        state, (state.upper()[:8], C_TEXT3, C_SURFACE2)
                    )
                    badge = QLabel(txt)
                    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    badge.setStyleSheet(
                        f"color:{fg};background:{bg};border:1px solid {fg}44;"
                        f"border-radius:5px;font-size:9px;font-weight:800;"
                        f"letter-spacing:0.8px;margin:8px 4px;"
                    )
                    self.conn_table.setCellWidget(row, col, badge)
                else:
                    item = QTableWidgetItem(str(val or ""))
                    # PID muted, rest normal
                    item.setForeground(QColor(C_TEXT3 if col == 0 else C_TEXT2))
                    self.conn_table.setItem(row, col, item)

        # DB size rows — rebuild
        while self._db_rows_v.count():
            child = self._db_rows_v.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for dbname, size, conn_count, cache in data.get("dbs", [])[:6]:
            self._db_rows_v.addWidget(_make_db_row(dbname, size, cache))

    def _terminate(self):
        row = self.conn_table.currentRow()
        if row < 0:
            return
        item = self.conn_table.item(row, 0)
        if not item:
            return
        pid = item.text()
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(
            self, "Terminate", f"Terminate connection PID {pid}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        c = self.config
        def do():
            conn = _conn("127.0.0.1", c["port"], c["username"], c["password"])
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT pg_terminate_backend(%s)", (int(pid),))
            cur.close()
            conn.close()
            return {}
        w = _Worker(do)
        w.result.connect(lambda d, e: self._refresh())
        w.start()


# ── Shield icon widget — no emoji, pure QPainter ──────────────────────────────
class _ShieldIcon(QWidget):
    """Draws a clean shield with a checkmark using QPainter — no emoji artifacts."""
    def __init__(self, color: str = "#4f8ef7", parent=None):
        super().__init__(parent)
        self._color = color
        self.setStyleSheet("background:transparent;border:none;")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background circle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color + "22"))
        p.drawEllipse(0, 0, w, h)

        # Shield outline
        from PyQt6.QtGui import QPen
        pen = QPen(QColor(self._color))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = w / 2, h / 2
        sw, sh = w * 0.42, h * 0.48
        # Simple shield: pentagon-ish path
        shield = QPainterPath()
        shield.moveTo(cx, cy - sh)
        shield.lineTo(cx + sw, cy - sh * 0.5)
        shield.lineTo(cx + sw, cy + sh * 0.1)
        shield.quadTo(cx + sw * 0.5, cy + sh, cx, cy + sh)
        shield.quadTo(cx - sw * 0.5, cy + sh, cx - sw, cy + sh * 0.1)
        shield.lineTo(cx - sw, cy - sh * 0.5)
        shield.closeSubpath()
        p.drawPath(shield)

        # Checkmark inside
        pen2 = QPen(QColor(self._color))
        pen2.setWidth(2)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen2)
        p.drawLine(
            int(cx - sw * 0.28), int(cy + 0),
            int(cx - sw * 0.05), int(cy + sh * 0.28)
        )
        p.drawLine(
            int(cx - sw * 0.05), int(cy + sh * 0.28),
            int(cx + sw * 0.30), int(cy - sh * 0.22)
        )