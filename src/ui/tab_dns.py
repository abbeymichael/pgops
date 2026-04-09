"""
tab_dns.py
DNS Tab — unified DNS resolution management for pgops.test.

Two resolution strategies:
  1. Hosts File Injection  — reliable for local machine, zero network config
  2. DNS Server            — serves all LAN devices if port 53 is available

The tab makes it crystal clear which method is active and guides the user.
"""

import webbrowser
import platform
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QTabWidget, QTextEdit, QApplication,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage

from ui.theme import (
    C_BG, C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_RED, C_AMBER,
)


def _btn(text, bg=C_BLUE, hover="#3b7de8", fg="white", h=34):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 16px;font-size:12px;font-weight:700;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
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


def _status_pill(text, fg, bg):
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{fg};background:{bg};border:1px solid {fg}44;"
        f"border-radius:4px;font-size:10px;font-weight:800;"
        f"letter-spacing:1px;padding:3px 10px;"
    )
    return l


def _make_qr_pixmap(url: str, size: int = 180) -> QPixmap:
    try:
        import qrcode
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
    DNS / Resolution management tab.
    Provides both hosts-file injection (local) and DNS server (LAN-wide).
    """

    def __init__(self, dns_server, get_host_ip, on_log=None, parent=None):
        super().__init__(parent)
        self._dns       = dns_server
        self._get_ip    = get_host_ip
        self._on_log    = on_log or print
        self._build()
        QTimer.singleShot(400, self.refresh)

    # ── Build ──────────────────────────────────────────────────────────────────

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
        v.setSpacing(18)

        # Page header
        v.addWidget(_lbl("DNS & Host Resolution", C_TEXT, 22, bold=True))
        v.addWidget(_lbl(
            "Make pgops.test and *.pgops.test resolve to this machine on any device.",
            C_TEXT3, 12
        ))

        # Current status banner
        v.addWidget(self._status_banner())

        # Method 1: Hosts File (local machine)
        v.addWidget(self._hosts_card())

        # Method 2: DNS Server (LAN-wide)
        v.addWidget(self._dns_server_card())

        # LAN device setup instructions
        v.addWidget(self._instructions_card())

        # QR code
        v.addWidget(self._qr_card())

        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ── Status banner ─────────────────────────────────────────────────────────

    def _status_banner(self):
        w = QWidget()
        w.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(20, 14, 20, 14)
        h.setSpacing(16)

        # Hosts status
        hosts_col = QVBoxLayout()
        hosts_col.setSpacing(4)
        hl = _lbl("LOCAL MACHINE", C_TEXT3, 9, bold=True)
        hl.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;letter-spacing:1.5px;background:transparent;"
        )
        self._hosts_status_pill = QLabel("CHECKING...")
        self._hosts_status_pill.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;font-weight:700;background:transparent;"
        )
        hosts_col.addWidget(hl)
        hosts_col.addWidget(self._hosts_status_pill)
        h.addLayout(hosts_col)

        # Divider
        div = QWidget()
        div.setFixedSize(1, 36)
        div.setStyleSheet(f"background:{C_BORDER2};border:none;")
        h.addWidget(div)

        # DNS server status
        dns_col = QVBoxLayout()
        dns_col.setSpacing(4)
        dl = _lbl("LAN DNS SERVER", C_TEXT3, 9, bold=True)
        dl.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;letter-spacing:1.5px;background:transparent;"
        )
        self._dns_status_pill = QLabel("CHECKING...")
        self._dns_status_pill.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;font-weight:700;background:transparent;"
        )
        dns_col.addWidget(dl)
        dns_col.addWidget(self._dns_status_pill)
        h.addLayout(dns_col)

        # Divider
        div2 = QWidget()
        div2.setFixedSize(1, 36)
        div2.setStyleSheet(f"background:{C_BORDER2};border:none;")
        h.addWidget(div2)

        # Current IP
        ip_col = QVBoxLayout()
        ip_col.setSpacing(4)
        il = _lbl("HOST IP ADDRESS", C_TEXT3, 9, bold=True)
        il.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;letter-spacing:1.5px;background:transparent;"
        )
        self._ip_display = QLabel("—")
        self._ip_display.setStyleSheet(
            f"color:{C_BLUE};font-size:16px;font-weight:800;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        ip_col.addWidget(il)
        ip_col.addWidget(self._ip_display)
        h.addLayout(ip_col)

        h.addStretch()

        # Test resolution button
        test_btn = _btn("Test Resolution", C_SURFACE2, C_BORDER2, C_TEXT2, h=32)
        test_btn.clicked.connect(self._test_resolution)
        h.addWidget(test_btn)

        self._test_result = QLabel("")
        self._test_result.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        h.addWidget(self._test_result)

        return w

    # ── Hosts file card ───────────────────────────────────────────────────────

    def _hosts_card(self):
        card = self._card("Method 1 — Hosts File  (Local Machine Only, Recommended)")
        cv = card.layout()

        desc = QLabel(
            "Adds pgops.test to your system's hosts file. Instant, reliable, no DNS server needed. "
            "Only affects the machine running PGOps. Requires Administrator / sudo."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        cv.addWidget(desc)

        self._hosts_inject_lbl = QLabel("")
        self._hosts_inject_lbl.setWordWrap(True)
        self._hosts_inject_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        cv.addWidget(self._hosts_inject_lbl)

        btns = QHBoxLayout()
        self.btn_inject   = _btn("Inject Hosts File",  "#166534", "#15803d", "#86efac", h=34)
        self.btn_remove_h = _btn("Remove Entries",     "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_inject.clicked.connect(self._inject_hosts)
        self.btn_remove_h.clicked.connect(self._remove_hosts)
        btns.addWidget(self.btn_inject)
        btns.addWidget(self.btn_remove_h)
        btns.addStretch()
        cv.addLayout(btns)

        note = QLabel(
            "After injecting: open https://pgops.test in your browser. "
            "Accept the certificate warning once, or trust Caddy's CA from the SSL tab."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"background:#1e2a1e;color:#86efac;padding:10px 14px;"
            f"border-radius:6px;font-size:11px;"
        )
        cv.addWidget(note)
        return card

    # ── DNS server card ───────────────────────────────────────────────────────

    def _dns_server_card(self):
        card = self._card("Method 2 — DNS Server  (All LAN Devices)")
        cv = card.layout()

        desc = QLabel(
            "Runs a DNS server so every device on your network can resolve pgops.test automatically. "
            "Requires Administrator / sudo for port 53. Point other devices' DNS to the Host IP above."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        cv.addWidget(desc)

        # Port info
        self._dns_port_lbl = QLabel("")
        self._dns_port_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;"
        )
        cv.addWidget(self._dns_port_lbl)

        btns = QHBoxLayout()
        self.btn_dns_start  = _btn("Start DNS Server",  "#166534", "#15803d", "#86efac", h=34)
        self.btn_dns_stop   = _btn("Stop",              "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_dns_start.clicked.connect(self._start_dns)
        self.btn_dns_stop.clicked.connect(self._stop_dns)
        btns.addWidget(self.btn_dns_start)
        btns.addWidget(self.btn_dns_stop)
        btns.addStretch()
        cv.addLayout(btns)

        warn = QLabel(
            "If port 53 is denied, PGOps uses port 5353. "
            "Clients must then set DNS to host-ip:5353 — most systems don't support custom ports natively. "
            "Use hosts file injection for the local machine instead."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            f"background:#2a1e0a;color:#fbbf24;padding:10px 14px;"
            f"border-radius:6px;font-size:11px;"
        )
        cv.addWidget(warn)
        return card

    # ── Instructions card ─────────────────────────────────────────────────────

    def _instructions_card(self):
        card = self._card("Configure Other Devices  (LAN-Wide)")
        cv = card.layout()
        cv.addWidget(_lbl(
            "Point other devices to this machine's DNS server, or manually add hosts entries on each device.",
            C_TEXT3, 12
        ))

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;}}"
            f"QTabBar::tab{{background:{C_SURFACE};color:{C_TEXT3};"
            f"padding:6px 14px;border:1px solid {C_BORDER};"
            f"border-bottom:none;border-radius:4px 4px 0 0;font-size:11px;font-weight:600;}}"
            f"QTabBar::tab:selected{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )
        self._instr_texts: dict[str, QTextEdit] = {}
        for name in ("Windows", "macOS", "Android", "iOS", "Linux"):
            te = QTextEdit()
            te.setReadOnly(True)
            te.setFixedHeight(130)
            te.setStyleSheet(
                f"background:{C_SURFACE2};color:{C_TEXT2};"
                f"font-family:'Consolas','Courier New',monospace;"
                f"font-size:12px;border:none;padding:10px;"
            )
            self._instr_texts[name] = te
            tabs.addTab(te, name)
        cv.addWidget(tabs)
        return card

    # ── QR card ───────────────────────────────────────────────────────────────

    def _qr_card(self):
        card = self._card("Quick Setup — Scan on Other Devices")
        cv = card.layout()

        h = QHBoxLayout()
        self._qr_lbl = QLabel()
        self._qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_lbl.setFixedSize(180, 180)
        self._qr_lbl.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER};border-radius:8px;"
        )
        h.addWidget(self._qr_lbl)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(_lbl("https://pgops.test", C_BLUE, 15, bold=True))
        right.addWidget(_lbl(
            "Scan on any device to open the PGOps landing page.\n"
            "The page shows DNS setup instructions for that device.",
            C_TEXT3, 12
        ))

        copy_row = QHBoxLayout()
        copy_btn = _btn("Copy URL", C_SURFACE2, C_BORDER2, C_TEXT2, h=30)
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText("https://pgops.test"),
            copy_btn.setText("✓ Copied"),
            QTimer.singleShot(1400, lambda: copy_btn.setText("Copy URL"))
        ))
        open_btn = _btn("Open in Browser", C_BLUE, "#3b7de8", h=30)
        open_btn.clicked.connect(lambda: webbrowser.open("https://pgops.test"))
        copy_row.addWidget(copy_btn)
        copy_row.addWidget(open_btn)
        copy_row.addStretch()
        right.addLayout(copy_row)
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

    # ── Refresh / update ──────────────────────────────────────────────────────

    def refresh(self):
        host_ip = self._get_ip()
        self._ip_display.setText(host_ip)

        # Hosts file status
        from core.dns_server import is_hosts_injected, get_hosts_current_ip
        injected = is_hosts_injected()
        injected_ip = get_hosts_current_ip()

        if injected and injected_ip:
            if injected_ip == host_ip:
                self._hosts_status_pill.setText("● ACTIVE")
                self._hosts_status_pill.setStyleSheet(
                    f"color:{C_GREEN};font-size:12px;font-weight:700;background:transparent;"
                )
                self._hosts_inject_lbl.setText(
                    f"✓ pgops.test → {injected_ip}  (up to date)"
                )
            else:
                self._hosts_status_pill.setText("⚠ STALE IP")
                self._hosts_status_pill.setStyleSheet(
                    f"color:{C_AMBER};font-size:12px;font-weight:700;background:transparent;"
                )
                self._hosts_inject_lbl.setText(
                    f"pgops.test → {injected_ip}  (outdated — current IP is {host_ip})"
                )
        else:
            self._hosts_status_pill.setText("● NOT SET")
            self._hosts_status_pill.setStyleSheet(
                f"color:{C_RED};font-size:12px;font-weight:700;background:transparent;"
            )
            self._hosts_inject_lbl.setText("Not injected — click 'Inject Hosts File' below.")

        # DNS server status
        dns_running = self._dns.is_running()
        if dns_running:
            port = self._dns.port
            qualifier = "" if port == 53 else f" (port {port})"
            self._dns_status_pill.setText(f"● RUNNING{qualifier}")
            self._dns_status_pill.setStyleSheet(
                f"color:{C_GREEN};font-size:12px;font-weight:700;background:transparent;"
            )
            self._dns_port_lbl.setText(
                f"Listening on 0.0.0.0:{port}  ·  *.pgops.test → {host_ip}"
            )
        else:
            self._dns_status_pill.setText("● STOPPED")
            self._dns_status_pill.setStyleSheet(
                f"color:{C_RED};font-size:12px;font-weight:700;background:transparent;"
            )
            self._dns_port_lbl.setText("Not running")

        # Instructions
        from core.dns_server import get_client_setup_instructions
        instructions = get_client_setup_instructions(host_ip)
        for name, text in instructions.items():
            if name in self._instr_texts:
                self._instr_texts[name].setPlainText(text)

        # QR code
        px = _make_qr_pixmap("https://pgops.test", 170)
        if px:
            self._qr_lbl.setPixmap(px)
        else:
            self._qr_lbl.setText("Install qrcode\npip install qrcode")
            self._qr_lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:11px;"
                f"background:{C_SURFACE2};border:1px solid {C_BORDER};border-radius:8px;"
            )

    # ── Button handlers ───────────────────────────────────────────────────────

    def _inject_hosts(self):
        from core.app_manager import load_apps
        apps = load_apps()
        domains = [a.get("domain", "") for a in apps if a.get("domain")]
        ok, msg = self._dns.inject_hosts(app_domains=domains)
        self._on_log(f"[Hosts] {msg}")
        if ok:
            QMessageBox.information(
                self, "Hosts File Updated",
                f"{msg}\n\nYou can now open https://pgops.test in your browser.\n"
                "Accept the certificate, or trust the Caddy CA from the SSL tab."
            )
        else:
            QMessageBox.warning(self, "Hosts File Error", msg)
        self.refresh()

    def _remove_hosts(self):
        ok, msg = self._dns.remove_hosts()
        self._on_log(f"[Hosts] {msg}")
        self.refresh()

    def _start_dns(self):
        ok, msg = self._dns.start()
        self._on_log(msg)
        if not ok:
            QMessageBox.warning(
                self, "DNS Server",
                f"{msg}\n\nTip: Use 'Inject Hosts File' for the local machine instead — "
                "it requires no special permissions and works immediately."
            )
        self.refresh()

    def _stop_dns(self):
        ok, msg = self._dns.stop()
        self._on_log(msg)
        self.refresh()

    def _test_resolution(self):
        from core.dns_server import test_resolution
        ok, msg = test_resolution()
        self._test_result.setText(msg)
        color = C_GREEN if ok else C_RED
        self._test_result.setStyleSheet(
            f"color:{color};font-size:11px;background:transparent;"
        )
        self._on_log(f"[DNS Test] {msg}")
