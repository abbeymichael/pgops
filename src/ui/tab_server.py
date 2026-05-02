"""
tab_server.py  — Phase 2 edition
Adds Caddy and FrankenPHP infrastructure cards below the pgAdmin card.
pgAdmin card shows https://pgadmin.pgops.local (via Caddy) not the raw port.
"""

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
    def __init__(
        self,
        manager, config, seaweedfs, pgadmin,
        on_start, on_stop, on_download,
        on_start_pgadmin, on_stop_pgadmin, on_open_pgadmin, on_reset_pgadmin,
        # Phase 2 callbacks
        on_setup_caddy, on_start_caddy, on_stop_caddy,
        on_setup_frankenphp, on_start_frankenphp, on_stop_frankenphp,
        caddy_manager, frankenphp_manager,
        # SeaweedFS callbacks
        on_setup_seaweedfs=None, on_start_seaweedfs=None, on_stop_seaweedfs=None,
        log_fn=None, parent=None,
    ):
        super().__init__(parent)
        self._manager    = manager
        self._config     = config
        self._seaweedfs  = seaweedfs
        self._pgadmin    = pgadmin
        self._caddy      = caddy_manager
        self._frankenphp = frankenphp_manager
        self._log        = log_fn or print

        # Callbacks
        self._cb_start         = on_start
        self._cb_stop          = on_stop
        self._cb_dl            = on_download
        self._cb_pga_start     = on_start_pgadmin
        self._cb_pga_stop      = on_stop_pgadmin
        self._cb_pga_open      = on_open_pgadmin
        self._cb_pga_reset     = on_reset_pgadmin
        self._cb_caddy_setup   = on_setup_caddy
        self._cb_caddy_start   = on_start_caddy
        self._cb_caddy_stop    = on_stop_caddy
        self._cb_fphp_setup    = on_setup_frankenphp
        self._cb_fphp_start    = on_start_frankenphp
        self._cb_fphp_stop     = on_stop_frankenphp
        self._cb_swfs_setup    = on_setup_seaweedfs or (lambda: None)
        self._cb_swfs_start    = on_start_seaweedfs or (lambda: None)
        self._cb_swfs_stop     = on_stop_seaweedfs  or (lambda: None)

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

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
        body.setStyleSheet("background:#1a1d23;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(28, 24, 28, 28)
        bv.setSpacing(18)

        # Row 1 – controls + connection details
        cols = QHBoxLayout()
        cols.setSpacing(18)
        cols.addWidget(self._controls_card(), 4)
        cols.addWidget(self._connection_card(), 6)
        bv.addLayout(cols)

        # Row 2 – chart + logs
        row2 = QHBoxLayout()
        row2.setSpacing(18)
        row2.addWidget(self._load_card(), 5)
        row2.addWidget(self._logs_card(), 5)
        bv.addLayout(row2)

        # Row 3 – SeaweedFS object storage
        bv.addWidget(self._seaweedfs_card())

        # Row 4 – pgAdmin
        bv.addWidget(self._pgadmin_card())

        # Row 5 – Caddy
        bv.addWidget(self._caddy_card())

        # Row 6 – FrankenPHP
        bv.addWidget(self._frankenphp_card())

        scroll.setWidget(body)
        root.addWidget(scroll)

    # ── Page header ───────────────────────────────────────────────────────────

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
        self._dot       = PulseDot(C_TEXT3)
        self._state_lbl = QLabel("Stopped")
        self._state_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;background:transparent;"
        )
        self._uptime_lbl = QLabel("")
        self._uptime_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;background:transparent;"
        )
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
        msg  = QLabel("PostgreSQL binaries not found. Click Setup to download them.")
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

    # ── Controls card ─────────────────────────────────────────────────────────

    def _controls_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        t = QLabel("Server Controls")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
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
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};"
            f"border-radius:8px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        self.btn_setup.clicked.connect(self._cb_dl)
        v.addWidget(self.btn_setup)
        v.addStretch()
        return card

    # ── Connection card ───────────────────────────────────────────────────────

    def _connection_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        hdr = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel("Connection Details")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        sub = QLabel("Credentials and parameters for the main instance.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        col.addWidget(t)
        col.addWidget(sub)
        hdr.addLayout(col)
        hdr.addStretch()
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

    # ── Load card ─────────────────────────────────────────────────────────────

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
        for val in vals:
            bar = QFrame()
            bar.setFixedWidth(18)
            bar.setFixedHeight(max(8, int(val / 100 * 90)))
            color = C_BLUE if val == peak else f"{C_BLUE}50"
            bar.setStyleSheet(f"background:{color};border-radius:3px 3px 0 0;")
            ch.addWidget(bar)
        ch.addStretch()
        v.addWidget(chart)
        return card

    # ── Logs card ─────────────────────────────────────────────────────────────

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
        return card

    # ── pgAdmin card ──────────────────────────────────────────────────────────

    def _seaweedfs_card(self):
        """Service card for SeaweedFS object storage (replaces MinIO)."""
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel("SeaweedFS — Object Storage (S3-compatible)")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
        self._swfs_badge = QLabel("● STOPPED")
        self._swfs_badge.setStyleSheet(
            f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
            f"border-radius:4px;font-size:10px;font-weight:800;"
            f"letter-spacing:1px;padding:3px 10px;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._swfs_badge)
        v.addLayout(hdr)

        # URL / port info row
        info = QHBoxLayout()
        s3_lbl = QLabel("S3 API")
        s3_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        self._swfs_s3_url = QLabel(self._swfs_url_text())
        self._swfs_s3_url.setStyleSheet(
            f"color:{C_BLUE};font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;background:transparent;"
        )
        info.addWidget(s3_lbl)
        info.addSpacing(8)
        info.addWidget(self._swfs_s3_url)
        info.addStretch()
        v.addLayout(info)

        # Note about Caddy
        proxy_note = QLabel(
            "ⓘ  S3 API and Filer UI are proxied via Caddy. "
            "Manage buckets from the Storage tab. "
            "Log: <AppData>/seaweedfs.log"
        )
        proxy_note.setWordWrap(True)
        proxy_note.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        v.addWidget(proxy_note)

        # Progress bar for setup
        self._swfs_prog = QProgressBar()
        self._swfs_prog.setVisible(False)
        self._swfs_prog.setFixedHeight(3)
        self._swfs_prog.setTextVisible(False)
        self._swfs_prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_AMBER};}}"
        )
        v.addWidget(self._swfs_prog)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)

        def _mk(text, bg, hover, fg="white"):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{hover};}}"
                f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
            )
            return b

        self.btn_swfs_setup  = _mk("⚙ Setup",        "#78350f", "#92400e", "#fef3c7")
        self.btn_swfs_start  = _mk("▶ Start Storage", "#166534", "#15803d", "#86efac")
        self.btn_swfs_stop   = _mk("■ Stop",          "#7f1d1d", "#991b1b", "#fca5a5")

        self.btn_swfs_setup.clicked.connect(self._cb_swfs_setup)
        self.btn_swfs_start.clicked.connect(self._cb_swfs_start)
        self.btn_swfs_stop.clicked.connect(self._cb_swfs_stop)

        for b in (self.btn_swfs_setup, self.btn_swfs_start, self.btn_swfs_stop):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)

        return card

    def _swfs_url_text(self) -> str:
        """Build the S3 / Filer URL display string from the live SeaweedFS config."""
        try:
            s3_port    = self._seaweedfs.s3_port
            filer_port = self._seaweedfs.filer_port
            https_port = self._seaweedfs.https_port
            if https_port == 443:
                return (
                    f"https://s3.pgops.local  "
                    f"·  Filer: https://filer.pgops.local  "
                    f"·  Internal: 127.0.0.1:{s3_port}"
                )
            return (
                f"https://s3.pgops.local:{https_port}  "
                f"·  Filer: https://filer.pgops.local:{https_port}  "
                f"·  Internal: 127.0.0.1:{s3_port}"
            )
        except Exception:
            return "127.0.0.1:8333 (S3)  ·  127.0.0.1:8888 (Filer)"

    def update_seaweedfs_status(self, running: bool, available: bool):
        """Called from the main_window poll loop to keep the card in sync."""
        self._swfs_s3_url.setText(self._swfs_url_text())

        if not available:
            self._swfs_badge.setText("NOT INSTALLED")
            self._swfs_badge.setStyleSheet(
                f"color:{C_TEXT3};background:{C_SURFACE2};border:1px solid {C_BORDER};"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
            self.btn_swfs_setup.setVisible(True)
        elif running:
            self._swfs_badge.setText("● RUNNING")
            self._swfs_badge.setStyleSheet(
                f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
            self.btn_swfs_setup.setVisible(False)
        else:
            self._swfs_badge.setText("● STOPPED")
            self._swfs_badge.setStyleSheet(
                f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
            self.btn_swfs_setup.setVisible(not available)

    def set_swfs_progress(self, visible: bool, val: int = 0):
        self._swfs_prog.setVisible(visible)
        if visible:
            self._swfs_prog.setValue(val)

    def _pgadmin_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel("pgAdmin 4 — Database Web UI")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
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

        # URL row — shows the Caddy HTTPS subdomain, not the raw port
        info = QHBoxLayout()
        url_key = QLabel("URL")
        url_key.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        # Default shows port; update_pgadmin_status() keeps it in sync
        self._pga_url = QLabel(self._pgadmin_public_url())
        self._pga_url.setStyleSheet(
            f"color:{C_BLUE};font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;background:transparent;"
        )
        cred = QLabel(f"Login: admin@pgops.com  /  pgopsadmin")
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

        # Proxy note
        proxy_note = QLabel(
            "ⓘ  Served via Caddy reverse proxy — Caddy must be running to access this URL."
        )
        proxy_note.setWordWrap(True)
        proxy_note.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        v.addWidget(proxy_note)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)

        def _mk(text, bg, hover, fg="white"):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{hover};}}"
            )
            return b

        self.btn_pga_start = _mk("Start pgAdmin",     "#166534", "#15803d", "#86efac")
        self.btn_pga_stop  = _mk("Stop",               "#7f1d1d", "#991b1b", "#fca5a5")
        self.btn_pga_open  = _mk("Open in Browser →",  C_BLUE,    "#3b7de8")
        self.btn_pga_reset = _mk("Reset & Restart",    "#78350f", "#92400e", "#fef3c7")

        self.btn_pga_start.clicked.connect(self._cb_pga_start)
        self.btn_pga_stop.clicked.connect(self._cb_pga_stop)
        self.btn_pga_open.clicked.connect(self._cb_pga_open)
        self.btn_pga_reset.clicked.connect(self._cb_pga_reset)

        for b in (self.btn_pga_start, self.btn_pga_stop, self.btn_pga_open, self.btn_pga_reset):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)

        if not self._pgadmin.is_available():
            note = QLabel(
                "pgAdmin 4 not found in the PostgreSQL bundle — run Setup PostgreSQL first."
            )
            note.setWordWrap(True)
            note.setStyleSheet(
                f"background:#2a1e0a;color:#fbbf24;padding:8px 12px;"
                f"border-radius:6px;font-size:11px;"
            )
            v.addWidget(note)

        return card

    def _pgadmin_public_url(self) -> str:
        """Compute the correct public URL based on Caddy's https_port."""
        try:
            port = self._caddy.https_port
            if port == 443:
                return "https://pgadmin.pgops.local"
            return f"https://pgadmin.pgops.local:{port}"
        except Exception:
            return "https://pgadmin.pgops.local:8443"

    # ── Caddy card ────────────────────────────────────────────────────────────

    def _caddy_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel("Caddy — Reverse Proxy & HTTPS")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
        self._caddy_badge = QLabel("● STOPPED")
        self._caddy_badge.setStyleSheet(
            f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
            f"border-radius:4px;font-size:10px;font-weight:800;"
            f"letter-spacing:1px;padding:3px 10px;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._caddy_badge)
        v.addLayout(hdr)

        # Subdomain info
        info = QHBoxLayout()
        info.setSpacing(20)
        self._caddy_info_lbl = QLabel(self._caddy_subdomains_text())
        self._caddy_info_lbl.setWordWrap(True)
        self._caddy_info_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-family:'Consolas','Courier New',monospace;"
            f"font-size:11px;background:transparent;"
        )
        info.addWidget(self._caddy_info_lbl)
        info.addStretch()
        v.addLayout(info)

        # Progress bar (for setup download)
        self._caddy_prog = QProgressBar()
        self._caddy_prog.setVisible(False)
        self._caddy_prog.setFixedHeight(3)
        self._caddy_prog.setTextVisible(False)
        self._caddy_prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_BLUE};}}"
        )
        v.addWidget(self._caddy_prog)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)

        def _mk(text, bg, hover, fg="white"):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{hover};}}"
                f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
            )
            return b

        self.btn_caddy_setup  = _mk("Setup Caddy",  "#78350f", "#92400e", "#fef3c7")
        self.btn_caddy_start  = _mk("Start Caddy",  "#166534", "#15803d", "#86efac")
        self.btn_caddy_stop   = _mk("Stop",          "#7f1d1d", "#991b1b", "#fca5a5")

        self.btn_caddy_setup.clicked.connect(self._cb_caddy_setup)
        self.btn_caddy_start.clicked.connect(self._cb_caddy_start)
        self.btn_caddy_stop.clicked.connect(self._cb_caddy_stop)

        for b in (self.btn_caddy_setup, self.btn_caddy_start, self.btn_caddy_stop):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)

        if not self._caddy.is_available():
            self._caddy_note = QLabel(
                "Caddy binary not found. Click Setup Caddy to download it (~30 MB)."
            )
            self._caddy_note.setWordWrap(True)
            self._caddy_note.setStyleSheet(
                f"background:#2a1e0a;color:#fbbf24;padding:8px 12px;"
                f"border-radius:6px;font-size:11px;"
            )
            v.addWidget(self._caddy_note)
        else:
            self._caddy_note = None

        return card

    def _caddy_subdomains_text(self) -> str:
        try:
            port = self._caddy.https_port
            suffix = f":{port}" if port != 443 else ""
        except Exception:
            suffix = ":8443"
        return (
            f"pgops.local{suffix}  ·  "
            f"pgadmin.pgops.local{suffix}  ·  "
            f"s3.pgops.local{suffix}  ·  "
            f"filer.pgops.local{suffix}"
        )

    # ── FrankenPHP card ───────────────────────────────────────────────────────

    def _frankenphp_card(self):
        card = _card()
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel("FrankenPHP — PHP App Server")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
        self._fphp_badge = QLabel("● STOPPED")
        self._fphp_badge.setStyleSheet(
            f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
            f"border-radius:4px;font-size:10px;font-weight:800;"
            f"letter-spacing:1px;padding:3px 10px;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._fphp_badge)
        v.addLayout(hdr)

        # Info row
        info = QHBoxLayout()
        self._fphp_info = QLabel(
            "Serves Laravel apps on internal ports  ·  One process per app"
        )
        self._fphp_info.setStyleSheet(
            f"color:{C_TEXT3};font-family:'Consolas','Courier New',monospace;"
            f"font-size:11px;background:transparent;"
        )
        info.addWidget(self._fphp_info)
        info.addStretch()
        v.addLayout(info)

        # Progress bar (for setup download)
        self._fphp_prog = QProgressBar()
        self._fphp_prog.setVisible(False)
        self._fphp_prog.setFixedHeight(3)
        self._fphp_prog.setTextVisible(False)
        self._fphp_prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_BLUE};}}"
        )
        v.addWidget(self._fphp_prog)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)

        def _mk(text, bg, hover, fg="white"):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{hover};}}"
                f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
            )
            return b

        self.btn_fphp_setup   = _mk("Setup FrankenPHP", "#78350f", "#92400e", "#fef3c7")
        self.btn_fphp_start   = _mk("Start All Apps",   "#166534", "#15803d", "#86efac")
        self.btn_fphp_stop    = _mk("Stop All Apps",    "#7f1d1d", "#991b1b", "#fca5a5")

        self.btn_fphp_setup.clicked.connect(self._cb_fphp_setup)
        self.btn_fphp_start.clicked.connect(self._cb_fphp_start)
        self.btn_fphp_stop.clicked.connect(self._cb_fphp_stop)

        for b in (self.btn_fphp_setup, self.btn_fphp_start, self.btn_fphp_stop):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)

        platform_note = QLabel(
            "Windows: downloaded as a ZIP archive (frankenphp.exe + PHP DLLs).  "
            "macOS: single self-contained binary."
        )
        platform_note.setWordWrap(True)
        platform_note.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        v.addWidget(platform_note)

        if not self._frankenphp.is_binary_available():
            self._fphp_note = QLabel(
                "FrankenPHP not found. Click Setup FrankenPHP to download it (~150 MB)."
            )
            self._fphp_note.setWordWrap(True)
            self._fphp_note.setStyleSheet(
                f"background:#2a1e0a;color:#fbbf24;padding:8px 12px;"
                f"border-radius:6px;font-size:11px;"
            )
            v.addWidget(self._fphp_note)
        else:
            self._fphp_note = None

        return card

    # ── Public update methods (called by main_window._poll) ───────────────────

    def update_server_status(self, running, config, conn_str):
        self._config = config
        if running:
            self._dot.set_color(C_GREEN)
            self._state_lbl.setText("Running")
            self._state_lbl.setStyleSheet(
                f"color:{C_GREEN};font-size:12px;background:transparent;"
            )
            self._f_host.set_value(config.get("_host", "-"))
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
            self._state_lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:12px;background:transparent;"
            )

    def update_pgadmin_status(self, running, available):
        # Keep the URL label in sync with Caddy's current https_port
        self._pga_url.setText(self._pgadmin_public_url())

        if not available:
            self._pga_badge.setText("NOT AVAILABLE")
            self._pga_badge.setStyleSheet(
                f"color:{C_TEXT3};background:{C_SURFACE2};border:1px solid {C_BORDER};"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
        elif running:
            self._pga_badge.setText("● RUNNING")
            self._pga_badge.setStyleSheet(
                f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
        else:
            self._pga_badge.setText("● STOPPED")
            self._pga_badge.setStyleSheet(
                f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )

    def update_caddy_status(self, running: bool, available: bool):
        # Refresh subdomain text in case port changed
        self._caddy_info_lbl.setText(self._caddy_subdomains_text())

        if not available:
            self._caddy_badge.setText("NOT INSTALLED")
            self._caddy_badge.setStyleSheet(
                f"color:{C_TEXT3};background:{C_SURFACE2};border:1px solid {C_BORDER};"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
        elif running:
            self._caddy_badge.setText("● RUNNING")
            self._caddy_badge.setStyleSheet(
                f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
            if self._caddy_note:
                self._caddy_note.setVisible(False)
        else:
            self._caddy_badge.setText("● STOPPED")
            self._caddy_badge.setStyleSheet(
                f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )

    def update_frankenphp_status(self, running_count: int, available: bool):
        if not available:
            self._fphp_badge.setText("NOT INSTALLED")
            self._fphp_badge.setStyleSheet(
                f"color:{C_TEXT3};background:{C_SURFACE2};border:1px solid {C_BORDER};"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
        elif running_count > 0:
            self._fphp_badge.setText(f"● {running_count} RUNNING")
            self._fphp_badge.setStyleSheet(
                f"color:{C_GREEN};background:#0a2016;border:1px solid {C_GREEN}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )
            if self._fphp_note:
                self._fphp_note.setVisible(False)
            self._fphp_info.setText(
                f"Serving {running_count} app(s) on internal ports  ·  One process per app"
            )
        else:
            self._fphp_badge.setText("● STOPPED")
            self._fphp_badge.setStyleSheet(
                f"color:{C_RED};background:#2a0d0d;border:1px solid {C_RED}40;"
                f"border-radius:4px;font-size:10px;font-weight:800;"
                f"letter-spacing:1px;padding:3px 10px;"
            )

    def show_warn(self, visible):
        self._warn_bar.setVisible(visible)

    def set_progress(self, visible, val=0):
        self._prog.setVisible(visible)
        if visible:
            self._prog.setValue(val)

    def set_caddy_progress(self, visible: bool, val: int = 0):
        self._caddy_prog.setVisible(visible)
        if visible:
            self._caddy_prog.setValue(val)

    def set_fphp_progress(self, visible: bool, val: int = 0):
        self._fphp_prog.setVisible(visible)
        if visible:
            self._fphp_prog.setValue(val)

    def append_log(self, msg):
        self._log_box.append(str(msg))
        self._log_box.verticalScrollBar().setValue(
            self._log_box.verticalScrollBar().maximum()
        )