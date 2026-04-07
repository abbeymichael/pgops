from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QFrame, QTextEdit, QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, QTimer
from ui.theme import *
from ui.widgets import CopyField, ConnField, PulseDot, mk_lbl, mk_sep


def _card(parent=None):
    w = QWidget(parent)
    w.setStyleSheet(
        f"background:{C_SURFACE};border:1px solid {C_BORDER};"
        f"border-radius:10px;"
    )
    return w


class ServerTab(QWidget):
    def __init__(self, manager, config, minio, pgadmin,
                 on_start, on_stop, on_download,
                 on_start_pgadmin, on_stop_pgadmin, on_open_pgadmin, on_reset_pgadmin,
                 log_fn, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._config = config
        self._minio = minio
        self._pgadmin = pgadmin
        self._log = log_fn
        self._cb_start = on_start
        self._cb_stop = on_stop
        self._cb_dl = on_download
        self._cb_pga_start = on_start_pgadmin
        self._cb_pga_stop = on_stop_pgadmin
        self._cb_pga_open = on_open_pgadmin
        self._cb_pga_reset = on_reset_pgadmin
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._page_header())

        self._prog = QProgressBar()
        self._prog.setVisible(False)
        self._prog.setFixedHeight(3)
        self._prog.setTextVisible(False)
        self._prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_BLUE};}}"
        )
        root.addWidget(self._prog)

        self._warn_bar = self._build_warn_bar()
        self._warn_bar.setVisible(False)
        root.addWidget(self._warn_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")

        body = QWidget()
        body.setStyleSheet(f"background:#1a1d23;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(28, 24, 28, 28)
        bv.setSpacing(18)

        cols = QHBoxLayout()
        cols.setSpacing(18)
        cols.addWidget(self._controls_card(), 4)
        cols.addWidget(self._connection_card(), 6)
        bv.addLayout(cols)

        row2 = QHBoxLayout()
        row2.setSpacing(18)
        row2.addWidget(self._load_card(), 5)
        row2.addWidget(self._logs_card(), 5)
        bv.addLayout(row2)

        bv.addWidget(self._pgadmin_card())
        scroll.setWidget(body)
        root.addWidget(scroll)

    def _page_header(self):
        w = QWidget()
        w.setFixedHeight(72)
        w.setStyleSheet(f"background:#1a1d23;border-bottom:1px solid {C_BORDER};")
        h = QHBoxLayout(w)
        h.setContentsMargins(28, 0, 28, 0)

        col = QVBoxLayout()
        col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self._title = QLabel("Main Cluster")
        self._title.setStyleSheet(
            f"color:{C_TEXT};font-size:24px;font-weight:800;background:transparent;"
        )
        prod = QLabel("PRODUCTION")
        prod.setStyleSheet(
            f"color:{C_TEXT3};background:{C_SURFACE};border:1px solid {C_BORDER2};"
            f"border-radius:4px;font-size:9px;font-weight:800;"
            f"letter-spacing:1.5px;padding:3px 8px;"
        )
        title_row.addWidget(self._title)
        title_row.addWidget(prod)
        title_row.addStretch()
        col.addLayout(title_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        self._dot = PulseDot(C_TEXT3)
        self._state_lbl = QLabel("Stopped")
        self._state_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        self._uptime_lbl = QLabel("")
        self._uptime_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        sub_row.addWidget(self._dot)
        sub_row.addWidget(self._state_lbl)
        sub_row.addWidget(self._uptime_lbl)
        sub_row.addStretch()
        col.addLayout(sub_row)

        h.addLayout(col)
        h.addStretch()

        svc = QLabel("⊙  SYSTEM TRAY ACTIVE")
        svc.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;letter-spacing:1.5px;"
            f"background:{C_SURFACE};border:1px solid {C_BORDER2};"
            f"border-radius:5px;padding:5px 12px;"
        )
        h.addWidget(svc)
        return w

    def _build_warn_bar(self):
        w = QWidget()
        w.setFixedHeight(44)
        w.setStyleSheet(f"background:#2a1e0a;border-bottom:1px solid #4a3010;")
        h = QHBoxLayout(w)
        h.setContentsMargins(28, 0, 28, 0)
        h.setSpacing(12)
        icon = QLabel("⚠")
        icon.setStyleSheet(f"color:{C_AMBER};font-size:14px;background:transparent;")
        msg = QLabel("PostgreSQL binaries not found. Click Setup to download them.")
        msg.setStyleSheet(f"color:#fbbf24;font-size:12px;background:transparent;")
        h.addWidget(icon)
        h.addWidget(msg)
        h.addStretch()
        self._btn_dl = QPushButton("⚙  Setup PostgreSQL →")
        self._btn_dl.setFixedHeight(28)
        self._btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_dl.setStyleSheet(
            f"QPushButton{{background:#4a3010;color:#fbbf24;border:none;"
            f"border-radius:5px;font-size:11px;font-weight:700;padding:0 14px;}}"
            f"QPushButton:hover{{background:#5a3f18;}}"
        )
        self._btn_dl.clicked.connect(self._cb_dl)
        h.addWidget(self._btn_dl)
        return w

    def _controls_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        t = QLabel("Server Controls")
        t.setStyleSheet(f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;")
        sub = QLabel("Execute direct orchestration commands.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(t)
        v.addWidget(sub)
        v.addSpacing(8)

        self.btn_start = QPushButton("▶   START SERVER")
        self.btn_start.setFixedHeight(52)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet(
            f"QPushButton{{background:#27ae60;color:white;border:none;"
            f"border-radius:8px;font-size:14px;font-weight:800;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:#2ecc71;}}"
            f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
        )
        self.btn_start.clicked.connect(self._cb_start)
        v.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■   STOP SERVER")
        self.btn_stop.setFixedHeight(52)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setStyleSheet(
            f"QPushButton{{background:#c0392b;color:white;border:none;"
            f"border-radius:8px;font-size:14px;font-weight:800;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:#e74c3c;}}"
            f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
        )
        self.btn_stop.clicked.connect(self._cb_stop)
        v.addWidget(self.btn_stop)

        self.btn_setup = QPushButton("⚙   Setup PostgreSQL")
        self.btn_setup.setFixedHeight(44)
        self.btn_setup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_setup.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};border:1px solid {C_BORDER2};"
            f"border-radius:8px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        self.btn_setup.clicked.connect(self._cb_dl)
        v.addWidget(self.btn_setup)
        v.addStretch()
        return card

    def _connection_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        hdr = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel("Connection Details")
        t.setStyleSheet(f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;")
        sub = QLabel("Credentials and parameters for the main instance.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        col.addWidget(t)
        col.addWidget(sub)
        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(32, 32)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER};border-radius:7px;font-size:14px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        hdr.addLayout(col)
        hdr.addStretch()
        hdr.addWidget(edit_btn)
        v.addLayout(hdr)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self._f_host = ConnField("HOST", "-")
        self._f_port = ConnField("PORT", str(self._config.get("port", 5432)))
        self._f_user = ConnField("USERNAME", self._config.get("username", "postgres"))
        row1.addWidget(self._f_host)
        row1.addWidget(self._f_port)
        row1.addWidget(self._f_user)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self._f_pass = ConnField("PASSWORD", self._config.get("password", ""), password=True)
        self._f_db   = ConnField("DATABASE",  self._config.get("database", "mydb"))
        row2.addWidget(self._f_pass)
        row2.addWidget(self._f_db)
        v.addLayout(row2)

        uri_lbl = QLabel("STANDARD CONNECTION URI")
        uri_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        v.addWidget(uri_lbl)

        uri_row = QHBoxLayout()
        uri_row.setSpacing(10)
        self._uri_lbl = QLabel("postgresql://postgres:postgres@-:5432/mydb")
        self._uri_lbl.setWordWrap(False)
        self._uri_lbl.setStyleSheet(
            f"background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:10px 14px;"
            f"font-family:'Consolas','Courier New',monospace;font-size:11px;"
        )
        copy_uri = QPushButton("⧉  COPY URI")
        copy_uri.setFixedHeight(38)
        copy_uri.setFixedWidth(110)
        copy_uri.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_uri.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};border-radius:8px;"
            f"font-size:11px;font-weight:700;letter-spacing:0.5px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        copy_uri.clicked.connect(lambda: (
            QApplication.clipboard().setText(self._uri_lbl.text()),
            copy_uri.setText("✓ COPIED"),
            QTimer.singleShot(1400, lambda: copy_uri.setText("⧉  COPY URI"))
        ))
        uri_row.addWidget(self._uri_lbl, 1)
        uri_row.addWidget(copy_uri, 0)
        v.addLayout(uri_row)
        return card

    def _load_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)

        lbl = QLabel("CONNECTION LOAD")
        lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        v.addWidget(lbl)

        chart = QWidget()
        chart.setFixedHeight(100)
        chart.setStyleSheet("background:transparent;")
        ch = QHBoxLayout(chart)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(5)
        ch.setAlignment(Qt.AlignmentFlag.AlignBottom)

        import random
        random.seed(7)
        vals = [random.randint(25, 90) for _ in range(14)]
        peak = max(vals)
        for i, val in enumerate(vals):
            bar = QFrame()
            bar.setFixedWidth(18)
            h_px = max(8, int(val / 100 * 90))
            bar.setFixedHeight(h_px)
            color = C_BLUE if val == peak else f"{C_BLUE}50"
            bar.setStyleSheet(f"background:{color};border-radius:3px 3px 0 0;")
            ch.addWidget(bar)
        ch.addStretch()
        v.addWidget(chart)
        return card

    def _logs_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)

        hdr = QHBoxLayout()
        lbl = QLabel("LIVE LOGS")
        lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        rt = QLabel("Real-time")
        rt.setStyleSheet(
            f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
            f"border-radius:4px;font-size:10px;font-weight:700;padding:2px 8px;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(rt)
        v.addLayout(hdr)

        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setStyleSheet(
            f"background:transparent;color:{C_TEXT3};"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:11px;border:none;padding:0;"
        )
        self._log_box.setPlaceholderText("Waiting for server...")
        v.addWidget(self._log_box)

        view_all = QPushButton("View All Logs →")
        view_all.setFixedHeight(26)
        view_all.setCursor(Qt.CursorShape.PointingHandCursor)
        view_all.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;font-size:11px;text-align:left;}}"
            f"QPushButton:hover{{color:{C_TEXT2};}}"
        )
        v.addWidget(view_all)
        return card

    def _pgadmin_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        hdr = QHBoxLayout()
        t = QLabel("pgAdmin 4 — Database Web UI")
        t.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;")
        self._pga_badge = QLabel("● STOPPED")
        self._pga_badge.setStyleSheet(
            f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
            f"border-radius:4px;font-size:10px;font-weight:800;"
            f"letter-spacing:1px;padding:3px 10px;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._pga_badge)
        v.addLayout(hdr)

        info = QHBoxLayout()
        url_key = QLabel("URL")
        url_key.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        self._pga_url = QLabel("http://pgops.local:5050")
        self._pga_url.setStyleSheet(
            f"color:{C_BLUE};font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;background:transparent;"
        )
        cred = QLabel("Login: admin@pgops.com  /  pgopsadmin")
        cred.setStyleSheet(
            f"color:{C_TEXT3};font-family:'Consolas','Courier New',monospace;"
            f"font-size:11px;background:transparent;"
        )
        info.addWidget(url_key)
        info.addSpacing(8)
        info.addWidget(self._pga_url)
        info.addSpacing(20)
        info.addWidget(cred)
        info.addStretch()
        v.addLayout(info)

        btns = QHBoxLayout()
        btns.setSpacing(8)

        def _make(text, bg, hover, fg="white"):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{hover};}}"
            )
            return b

        self.btn_pga_start = _make("Start pgAdmin", "#166534", "#15803d", "#86efac")
        self.btn_pga_stop  = _make("Stop",          "#7f1d1d", "#991b1b", "#fca5a5")
        self.btn_pga_open  = _make("Open in Browser →", C_BLUE, "#3b7de8")
        self.btn_pga_reset = _make("Reset & Restart", "#78350f", "#92400e", "#fef3c7")

        self.btn_pga_start.clicked.connect(self._cb_pga_start)
        self.btn_pga_stop.clicked.connect(self._cb_pga_stop)
        self.btn_pga_open.clicked.connect(self._cb_pga_open)
        self.btn_pga_reset.clicked.connect(self._cb_pga_reset)

        for b in (self.btn_pga_start, self.btn_pga_stop, self.btn_pga_open, self.btn_pga_reset):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)

        if not self._pgadmin.is_available():
            note = QLabel("pgAdmin 4 not found in the PostgreSQL bundle — run Setup PostgreSQL first.")
            note.setStyleSheet(
                f"background:#2a1e0a;color:#fbbf24;padding:8px 12px;"
                f"border-radius:6px;font-size:11px;"
            )
            note.setWordWrap(True)
            v.addWidget(note)

        return card

    def update_server_status(self, running, config, conn_str):
        self._config = config
        if running:
            self._dot.set_color(C_GREEN)
            self._state_lbl.setText("Running")
            self._state_lbl.setStyleSheet(f"color:{C_GREEN};font-size:12px;background:transparent;")
            host = config.get("_host", "-")
            self._f_host.set_value(host)
            self._f_port.set_value(str(config.get("port", 5432)))
            self._f_user.set_value(config.get("username", ""))
            self._f_pass.set_value(config.get("password", ""))
            self._f_db.set_value(config.get("database", ""))
            self._uri_lbl.setText(conn_str)
            self._uri_lbl.setStyleSheet(
                f"background:{C_SURFACE2};color:{C_TEXT};"
                f"border:1px solid {C_BORDER};border-radius:8px;"
                f"padding:10px 14px;"
                f"font-family:'Consolas','Courier New',monospace;font-size:11px;"
            )
        else:
            self._dot.set_color(C_TEXT3)
            self._state_lbl.setText("Stopped")
            self._state_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")

    def update_pgadmin_status(self, running, available):
        if not available:
            self._pga_badge.setText("NOT AVAILABLE")
            self._pga_badge.setStyleSheet(
                f"color:{C_TEXT3};background:{C_SURFACE2};border:1px solid {C_BORDER};"
                f"border-radius:4px;font-size:10px;font-weight:800;letter-spacing:1px;padding:3px 10px;"
            )
        elif running:
            self._pga_badge.setText("● RUNNING")
            self._pga_badge.setStyleSheet(
                f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;letter-spacing:1px;padding:3px 10px;"
            )
        else:
            self._pga_badge.setText("● STOPPED")
            self._pga_badge.setStyleSheet(
                f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;letter-spacing:1px;padding:3px 10px;"
            )

    def show_warn(self, visible):
        self._warn_bar.setVisible(visible)

    def set_progress(self, visible, val=0):
        self._prog.setVisible(visible)
        if visible:
            self._prog.setValue(val)

    def append_log(self, msg):
        self._log_box.append(str(msg))
        self._log_box.verticalScrollBar().setValue(self._log_box.verticalScrollBar().maximum())
