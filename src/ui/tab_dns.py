"""
tab_dns.py
DNS Tab — shows DNS server status, client setup instructions, QR code.
"""

import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QTabWidget, QTextEdit, QApplication,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage

from ui.theme import (
    C_BG, C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_RED,
)


def _btn(text, bg=C_BLUE, hover="#3b7de8", fg="white", h=32):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 14px;font-size:12px;font-weight:700;}}"
        f"QPushButton:hover{{background:{hover};}}"
    )
    return b


def _lbl(text, color=C_TEXT2, size=12, bold=False):
    l = QLabel(text)
    w = "700" if bold else "400"
    l.setStyleSheet(
        f"color:{color};font-size:{size}px;font-weight:{w};background:transparent;"
    )
    return l


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


def _copy_btn(value: str) -> QPushButton:
    b = QPushButton("Copy")
    b.setFixedSize(52, 28)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
        f"border:1px solid {C_BORDER2};border-radius:5px;"
        f"font-size:11px;font-weight:600;}}"
        f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
    )
    def _do():
        QApplication.clipboard().setText(value)
        b.setText("✓")
        QTimer.singleShot(1300, lambda: b.setText("Copy"))
    b.clicked.connect(_do)
    return b


def _make_qr_pixmap(url: str, size: int = 200) -> QPixmap:
    """Generate a QR code pixmap for the given URL. Returns None on failure."""
    try:
        import qrcode
        from PIL import Image
        import io

        qr = qrcode.make(url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        img = QImage.fromData(buf.getvalue())
        return QPixmap.fromImage(img).scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception:
        return None


class DnsTab(QWidget):
    """
    DNS Tab — status card, client setup instructions, QR code.
    dns_server: DNSServerThread instance
    get_host_ip: callable returning current LAN IP string
    on_log: callable for logging
    """

    def __init__(self, dns_server, get_host_ip, on_log=None, parent=None):
        super().__init__(parent)
        self._dns       = dns_server
        self._get_ip    = get_host_ip
        self._on_log    = on_log or print
        self._build()
        QTimer.singleShot(300, self._refresh_status)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:#1a1d23;border:none;")

        inner = QWidget()
        inner.setStyleSheet("background:#1a1d23;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(20)

        v.addWidget(_lbl("DNS Server", C_TEXT, 22, bold=True))
        v.addWidget(_lbl(
            "PGOps runs a local DNS server so every device resolves *.pgops.test automatically.",
            C_TEXT3, 12
        ))

        v.addWidget(self._status_card())
        v.addWidget(self._instructions_card())
        v.addWidget(self._qr_card())
        v.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ── Status card ───────────────────────────────────────────────────────────

    def _status_card(self):
        card = self._card("DNS Server Status")
        cv = card.layout()

        self._status_lbl = QLabel("Checking...")
        self._status_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:15px;font-weight:700;background:transparent;"
        )
        cv.addWidget(self._status_lbl)

        # IP row
        ip_row = QHBoxLayout()
        ip_row.setSpacing(10)
        ip_label = _lbl("CURRENT HOST IP", C_TEXT3, 10)
        ip_label.setFixedWidth(130)
        self._ip_lbl = QLabel("—")
        self._ip_lbl.setStyleSheet(
            f"color:{C_BLUE};font-size:16px;font-weight:800;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        self._copy_ip_btn = _copy_btn("")
        ip_row.addWidget(ip_label)
        ip_row.addWidget(self._ip_lbl)
        ip_row.addWidget(self._copy_ip_btn)
        ip_row.addStretch()
        cv.addLayout(ip_row)

        btns = QHBoxLayout()
        self._btn_start = _btn("Start DNS Server", "#166534", "#15803d", "#86efac", h=34)
        self._btn_stop  = _btn("Stop",             "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self._btn_test  = _btn("Test Resolution",  C_SURFACE2, C_BORDER2, C_TEXT2,  h=34)
        self._btn_start.clicked.connect(self._start)
        self._btn_stop.clicked.connect(self._stop)
        self._btn_test.clicked.connect(self._test)
        for b in (self._btn_start, self._btn_stop, self._btn_test):
            btns.addWidget(b)
        btns.addStretch()
        cv.addLayout(btns)

        self._test_result = _lbl("", C_TEXT3, 11)
        cv.addWidget(self._test_result)
        return card

    # ── Instructions card ─────────────────────────────────────────────────────

    def _instructions_card(self):
        card = self._card("Client Setup — Point Devices to this DNS Server")
        cv = card.layout()
        cv.addWidget(_lbl(
            "Do this once per device. After that, all *.pgops.test subdomains work automatically.",
            C_TEXT3, 12
        ))

        # Platform tabs
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(
            f"QTabWidget::pane{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;}}"
            f"QTabBar::tab{{background:{C_SURFACE};color:{C_TEXT3};"
            f"padding:6px 14px;border:1px solid {C_BORDER};"
            f"border-bottom:none;border-radius:4px 4px 0 0;font-size:11px;font-weight:600;}}"
            f"QTabBar::tab:selected{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )

        self._instr_texts: dict[str, QTextEdit] = {}
        for platform_name in ("Windows", "macOS", "Android", "iOS", "Linux"):
            te = QTextEdit()
            te.setReadOnly(True)
            te.setFixedHeight(120)
            te.setStyleSheet(
                f"background:{C_SURFACE2};color:{C_TEXT2};"
                f"font-size:12px;border:none;padding:10px;"
            )
            self._instr_texts[platform_name] = te
            tab_widget.addTab(te, platform_name)
        cv.addWidget(tab_widget)
        return card

    # ── QR card ───────────────────────────────────────────────────────────────

    def _qr_card(self):
        card = self._card("Quick Setup — Scan QR Code")
        cv = card.layout()
        cv.addWidget(_lbl(
            "Scan to open the PGOps setup page on any device. "
            "The page shows DNS instructions for that device's platform.",
            C_TEXT3, 12
        ))

        h = QHBoxLayout()
        self._qr_lbl = QLabel()
        self._qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_lbl.setFixedSize(200, 200)
        self._qr_lbl.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER};border-radius:8px;"
        )
        h.addWidget(self._qr_lbl)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(_lbl("pgops.test/setup", C_BLUE, 14, bold=True))
        right.addWidget(_lbl(
            "Open this URL on any device on your network to see\n"
            "the full DNS configuration instructions.",
            C_TEXT3, 12
        ))
        open_btn = _btn("Open in Browser", C_BLUE, "#3b7de8", h=34)
        open_btn.clicked.connect(lambda: webbrowser.open("http://pgops.test"))
        right.addWidget(open_btn)
        right.addStretch()
        h.addLayout(right)
        h.addStretch()
        cv.addLayout(h)
        return card

    # ── Card helper ───────────────────────────────────────────────────────────

    def _card(self, title: str) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)
        t = QLabel(title)
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
        v.addWidget(t)
        v.addWidget(_sep())
        return card

    # ── Status refresh ────────────────────────────────────────────────────────

    def _refresh_status(self):
        running = self._dns.is_running()
        host_ip = self._get_ip()

        # Status label
        if running:
            port = self._dns.port
            qualifier = "" if port == 53 else f" (port {port})"
            self._status_lbl.setText(f"● RUNNING{qualifier}  —  *.pgops.test → {host_ip}")
            self._status_lbl.setStyleSheet(
                f"color:{C_GREEN};font-size:14px;font-weight:700;background:transparent;"
            )
        else:
            self._status_lbl.setText("● STOPPED")
            self._status_lbl.setStyleSheet(
                f"color:{C_RED};font-size:14px;font-weight:700;background:transparent;"
            )

        # IP + copy button
        self._ip_lbl.setText(host_ip)
        # Rebuild copy button with current IP
        self._copy_ip_btn.clicked.disconnect()
        def _copy_ip():
            QApplication.clipboard().setText(host_ip)
            self._copy_ip_btn.setText("✓")
            QTimer.singleShot(1300, lambda: self._copy_ip_btn.setText("Copy"))
        self._copy_ip_btn.clicked.connect(_copy_ip)

        # Instructions
        from core.dns_server import get_client_setup_instructions
        instructions = get_client_setup_instructions(host_ip)
        for platform_name, text in instructions.items():
            te = self._instr_texts.get(platform_name)
            if te:
                te.setPlainText(text)

        # QR code
        qr_url = f"http://pgops.test"
        px = _make_qr_pixmap(qr_url, 190)
        if px:
            self._qr_lbl.setPixmap(px)
        else:
            self._qr_lbl.setText("Install qrcode library\npip install qrcode")
            self._qr_lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:11px;"
                f"background:{C_SURFACE2};border:1px solid {C_BORDER};border-radius:8px;"
            )

    # ── Button handlers ───────────────────────────────────────────────────────

    def _start(self):
        ok, msg = self._dns.start()
        self._on_log(msg)
        self._refresh_status()

    def _stop(self):
        ok, msg = self._dns.stop()
        self._on_log(msg)
        self._refresh_status()

    def _test(self):
        from core.dns_server import test_resolution
        ok, msg = test_resolution()
        self._test_result.setText(msg)
        color = C_GREEN if ok else C_RED
        self._test_result.setStyleSheet(
            f"color:{color};font-size:11px;background:transparent;"
        )
        self._on_log(f"[DNS Test] {msg}")

    def refresh(self):
        self._refresh_status()
