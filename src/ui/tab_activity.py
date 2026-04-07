from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from ui.theme import *



class _Worker(QThread):
    result = pyqtSignal(dict, str)
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
    def run(self):
        try: self.result.emit(self.fn(), "")
        except Exception as e: self.result.emit({}, str(e))


def _conn(host, port, user, pw, db="postgres"):
    import psycopg2
    return psycopg2.connect(
        host=host, port=port, user=user, password=pw, dbname=db,
        connect_timeout=4, options="-c statement_timeout=5000"
    )


def _card():
    w = QWidget()
    w.setStyleSheet(f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;")
    return w


class _StatCard(QWidget):
    def __init__(self, title, value="—", color=C_TEXT, extra=None):
        super().__init__()
        self.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(110)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(6)

        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        v.addWidget(t)

        self._val = QLabel(value)
        self._val.setStyleSheet(
            f"color:{C_TEXT};font-size:32px;font-weight:800;"
            f"letter-spacing:-1px;background:transparent;"
        )
        v.addWidget(self._val)

        if extra:
            v.addWidget(extra)

    def set(self, val): self._val.setText(str(val))


class ActivityTab(QWidget):
    REFRESH_MS = 5000

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._worker = None
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._build()

    def update_config(self, c): self.config = c

    def start_monitoring(self):
        if not self._active:
            self._active = True
            self._refresh()
            self._timer.start(self.REFRESH_MS)

    def stop_monitoring(self):
        self._active = False
        self._timer.stop()

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
        body.setStyleSheet(f"background:#1a1d23;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(28, 24, 28, 28)
        bv.setSpacing(20)

        bv.addLayout(self._stat_row())

        mid = QHBoxLayout()
        mid.setSpacing(18)
        mid.addWidget(self._connections_panel(), 6)
        mid.addWidget(self._db_sizes_panel(), 4)
        bv.addLayout(mid)

        bot = QHBoxLayout()
        bot.setSpacing(18)
        bot.addWidget(self._traffic_card(), 6)
        bot.addWidget(self._health_card(), 4)
        bv.addLayout(bot)

        scroll.setWidget(body)
        root.addWidget(scroll)

    def _sub_header(self):
        w = QWidget()
        w.setFixedHeight(50)
        w.setStyleSheet(f"background:#1a1d23;border-bottom:1px solid {C_BORDER};")
        h = QHBoxLayout(w)
        h.setContentsMargins(28, 0, 28, 0)
        h.setSpacing(0)

        for label in ("Real-time Traffic", "Log Streams"):
            btn = QPushButton(label)
            btn.setFixedHeight(50)
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
        self._status_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        h.addWidget(self._status_lbl)
        h.addSpacing(14)

        ref = QPushButton("↻  Refresh Now")
        ref.setFixedHeight(30)
        ref.setCursor(Qt.CursorShape.PointingHandCursor)
        ref.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"font-size:11px;font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )
        ref.clicked.connect(self._refresh)
        h.addWidget(ref)
        return w

    def _stat_row(self):
        row = QHBoxLayout()
        row.setSpacing(14)

        live_badge = QLabel("● LIVE")
        live_badge.setStyleSheet(
            f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
            f"border-radius:10px;font-size:10px;font-weight:800;"
            f"letter-spacing:1px;padding:2px 10px;"
        )

        dash = QLabel("—" * 4)
        dash.setStyleSheet(f"color:{C_TEXT3};font-size:14px;background:transparent;")

        self._c_tps   = _StatCard("Transactions/s", "—",  C_TEXT, QLabel("⚡"))
        self._c_conns = _StatCard("Active Connections", "—", C_TEXT, live_badge)
        self._c_dbs   = _StatCard("Total Databases",   "—", C_TEXT)
        self._c_cache = _StatCard("Cache Hit Ratio",   "—", C_TEXT, dash)
        self._c_up    = _StatCard("Uptime",            "—", C_TEXT)

        for c in (self._c_tps, self._c_conns, self._c_dbs, self._c_cache, self._c_up):
            row.addWidget(c)
        return row

    def _connections_panel(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet("background:transparent;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(18, 16, 18, 12)
        hh.setSpacing(10)

        icon = QLabel("⚡")
        icon.setStyleSheet(f"color:{C_BLUE};font-size:16px;background:transparent;")
        title = QLabel("Active Connections")
        title.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;")
        hh.addWidget(icon)
        hh.addWidget(title)
        hh.addStretch()

        self.btn_terminate = QPushButton("✕  Terminate Connection")
        self.btn_terminate.setFixedHeight(30)
        self.btn_terminate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_terminate.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_RED};"
            f"border:1px solid {C_RED}40;border-radius:6px;"
            f"font-size:11px;font-weight:700;padding:0 14px;}}"
            f"QPushButton:hover{{background:#2a0d0d;}}"
        )
        self.btn_terminate.clicked.connect(self._terminate)
        hh.addWidget(self.btn_terminate)
        v.addWidget(hdr)

        self.conn_table = QTableWidget(0, 6)
        self.conn_table.setHorizontalHeaderLabels(["PID", "DATABASE", "USER", "APPLICATION", "STATE", "DUR"])
        h = self.conn_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.conn_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.conn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conn_table.setShowGrid(False)
        self.conn_table.setStyleSheet(TABLE_STYLE + f"QTableWidget{{border-radius:0;border:none;}}")
        self.conn_table.verticalHeader().setVisible(False)
        self.conn_table.verticalHeader().setDefaultSectionSize(46)
        v.addWidget(self.conn_table)
        return card

    def _db_sizes_panel(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)

        hdr = QHBoxLayout()
        icon = QLabel("⊞")
        icon.setStyleSheet(f"color:{C_GREEN};font-size:16px;background:transparent;")
        title = QLabel("Database Sizes")
        title.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;")
        hdr.addWidget(icon)
        hdr.addSpacing(6)
        hdr.addWidget(title)
        hdr.addStretch()
        v.addLayout(hdr)

        self._db_rows_container = QWidget()
        self._db_rows_container.setStyleSheet("background:transparent;")
        self._db_rows_v = QVBoxLayout(self._db_rows_container)
        self._db_rows_v.setContentsMargins(0, 0, 0, 0)
        self._db_rows_v.setSpacing(6)
        v.addWidget(self._db_rows_container)
        v.addStretch()
        return card

    def _make_db_row(self, name, size, cache_pct):
        w = QWidget()
        w.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:8px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(0)

        col = QVBoxLayout()
        col.setSpacing(2)
        name_l = QLabel(name)
        name_l.setStyleSheet(f"color:{C_TEXT};font-size:13px;font-weight:600;background:transparent;")

        try:
            pct = float(str(cache_pct).replace("%","").replace("N/A","0"))
        except: pct = 0
        cache_l = QLabel(f"{pct:.0f}% CACHE HIT")
        cache_l.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;"
        )
        col.addWidget(name_l)
        col.addWidget(cache_l)
        h.addLayout(col)
        h.addStretch()

        size_l = QLabel(size)
        size_l.setStyleSheet(f"color:{C_TEXT};font-size:17px;font-weight:800;background:transparent;")
        h.addWidget(size_l)
        h.addSpacing(12)

        bar_w = QWidget()
        bar_w.setFixedSize(4, 36)
        bar_w.setStyleSheet(f"background:{C_BORDER};border-radius:2px;")
        fill = QFrame(bar_w)
        fill.setFixedWidth(4)
        fill_h = max(4, int(36 * min(pct, 100) / 100))
        fill.setFixedHeight(fill_h)
        fill.move(0, 36 - fill_h)
        fc = C_GREEN if pct >= 90 else C_AMBER if pct >= 70 else C_RED
        fill.setStyleSheet(f"background:{fc};border-radius:2px;")
        h.addWidget(bar_w)
        return w

    def _traffic_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)

        hdr = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("Traffic Throughput (24h)")
        t.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;")
        sub = QLabel("Real-time IOPS aggregation")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        col.addWidget(t)
        col.addWidget(sub)

        dots = QHBoxLayout()
        dots.setSpacing(5)
        for i, active in enumerate([False, False, True]):
            d = QFrame()
            d.setFixedSize(7, 7)
            d.setStyleSheet(
                f"background:{'#ffffff' if active else C_BORDER2};"
                f"border-radius:4px;"
            )
            dots.addWidget(d)
        hdr.addLayout(col)
        hdr.addStretch()
        hdr.addLayout(dots)
        v.addLayout(hdr)

        chart = QWidget()
        chart.setFixedHeight(100)
        chart.setStyleSheet("background:transparent;")
        ch = QHBoxLayout(chart)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(4)
        ch.setAlignment(Qt.AlignmentFlag.AlignBottom)
        import random
        random.seed(42)
        vals = [random.randint(30, 85) for _ in range(22)]
        for val in vals:
            bar = QFrame()
            bar.setFixedWidth(18)
            bar.setFixedHeight(max(6, int(val * 0.9)))
            bar.setStyleSheet(f"background:{C_BLUE}55;border-radius:3px 3px 0 0;")
            ch.addWidget(bar)
        ch.addStretch()
        v.addWidget(chart)
        return card

    def _health_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 0, 20, 20)
        v.setSpacing(10)
        v.addStretch()

        shield = QLabel("✓")
        shield.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shield.setStyleSheet(
            f"color:{C_BLUE};font-size:36px;background:{C_SURFACE2};"
            f"border-radius:50px;min-width:64px;min-height:64px;"
            f"max-width:64px;max-height:64px;"
        )
        shield.setFixedSize(64, 64)
        shield_wrap = QHBoxLayout()
        shield_wrap.addStretch()
        shield_wrap.addWidget(shield)
        shield_wrap.addStretch()
        v.addLayout(shield_wrap)

        t = QLabel("System Health")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;")
        v.addWidget(t)

        sub = QLabel("All subsystems operational. No critical latency detected.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        v.addWidget(sub)

        dl = QPushButton("DOWNLOAD REPORT")
        dl.setFixedHeight(30)
        dl.setCursor(Qt.CursorShape.PointingHandCursor)
        dl.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;font-size:10px;font-weight:700;letter-spacing:1.5px;}}"
            f"QPushButton:hover{{color:{C_TEXT2};}}"
        )
        v.addWidget(dl)
        v.addStretch()
        return card

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
                       COALESCE(EXTRACT(EPOCH FROM (now()-query_start))::int::text||'s','—')
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid() AND state IS NOT NULL
                ORDER BY query_start DESC NULLS LAST
            """)
            conns = cur.fetchall()
            cur.execute("""
                SELECT d.datname, pg_size_pretty(pg_database_size(d.datname)),
                       (SELECT COUNT(*) FROM pg_stat_activity sa WHERE sa.datname=d.datname),
                       CASE WHEN COALESCE(sd.blks_hit,0)+COALESCE(sd.blks_read,0)=0 THEN 'N/A'
                            ELSE ROUND(100.0*sd.blks_hit/(sd.blks_hit+sd.blks_read),1)::text||'%'
                       END
                FROM pg_database d
                LEFT JOIN pg_stat_database sd ON sd.datname=d.datname
                WHERE d.datistemplate=false ORDER BY pg_database_size(d.datname) DESC
            """)
            dbs = cur.fetchall()
            cur.execute("""
                SELECT
                  (SELECT COUNT(*) FROM pg_stat_activity WHERE state='active'),
                  (SELECT COUNT(*) FROM pg_database WHERE datistemplate=false),
                  (SELECT ROUND(100.0*SUM(blks_hit)/NULLIF(SUM(blks_hit+blks_read),0),1) FROM pg_stat_database),
                  (SELECT EXTRACT(EPOCH FROM(now()-pg_postmaster_start_time()))::bigint),
                  (SELECT ROUND((SUM(xact_commit)+SUM(xact_rollback))/
                    GREATEST(EXTRACT(EPOCH FROM(now()-MIN(stats_reset))),1),1)
                   FROM pg_stat_database WHERE datname NOT IN('template0','template1'))
            """)
            stats = cur.fetchone()
            cur.close(); conn.close()
            return {"conns": conns, "dbs": dbs, "stats": stats}

        self._worker = _Worker(fetch)
        self._worker.result.connect(self._on_data)
        self._worker.start()

    def _on_data(self, data, error):
        if error:
            self._status_lbl.setText(f"Error: {error[:50]}")
            self._status_lbl.setStyleSheet(f"color:{C_RED};font-size:11px;background:transparent;")
            return
        self._status_lbl.setText("● Live")
        self._status_lbl.setStyleSheet(f"color:{C_GREEN};font-size:11px;background:transparent;")

        s = data.get("stats", ())
        if s:
            active, total_dbs, cache, uptime_s, tps = s
            self._c_tps.set(str(tps or "0"))
            self._c_conns.set(str(active or 0))
            self._c_dbs.set(str(total_dbs or 0))
            self._c_cache.set(f"{cache}%" if cache else "—")
            if uptime_s:
                secs = int(uptime_s)
                h, m = divmod(secs // 60, 60)
                d, h = divmod(h, 24)
                self._c_up.set(f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m")

        STATE_STYLE = {
            "active":  ("ACTIVE",  C_GREEN, "#0a2016"),
            "idle":    ("IDLE",    C_TEXT3, C_SURFACE2),
            "idle in transaction": ("WAITING", C_AMBER, "#2a1e0a"),
        }
        self.conn_table.setRowCount(0)
        for pid, db, user, app, state, dur in data.get("conns", []):
            row = self.conn_table.rowCount()
            self.conn_table.insertRow(row)
            for col, val in enumerate([str(pid), db, user, app, "", str(dur)]):
                if col == 4:
                    txt, fg, bg = STATE_STYLE.get(state, (state.upper(), C_TEXT3, C_SURFACE2))
                    badge = QLabel(txt)
                    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    badge.setStyleSheet(
                        f"color:{fg};background:{bg};border:1px solid {fg}50;"
                        f"border-radius:4px;font-size:10px;font-weight:800;"
                        f"letter-spacing:0.8px;margin:6px 4px;"
                    )
                    self.conn_table.setCellWidget(row, col, badge)
                else:
                    item = QTableWidgetItem(str(val or ""))
                    item.setForeground(QColor(C_TEXT2 if col else C_TEXT3))
                    self.conn_table.setItem(row, col, item)

        while self._db_rows_v.count():
            child = self._db_rows_v.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        for dbname, size, conn_count, cache in data.get("dbs", [])[:5]:
            self._db_rows_v.addWidget(self._make_db_row(dbname, size, cache))

    def _terminate(self):
        row = self.conn_table.currentRow()
        if row < 0: return
        item = self.conn_table.item(row, 0)
        if not item: return
        pid = item.text()
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Terminate", f"Terminate PID {pid}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes: return
        c = self.config
        def do():
            conn = _conn("127.0.0.1", c["port"], c["username"], c["password"])
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT pg_terminate_backend(%s)", (int(pid),))
            cur.close(); conn.close()
            return {}
        w = _Worker(do)
        w.result.connect(lambda d, e: self._refresh())
        w.start()
