"""
tab_dns.py
Network Discovery tab — mDNS (Bonjour / Zeroconf) management for PGOps.

mDNS broadcasts pgops.local and every deployed app subdomain (<app>.pgops.local)
on the LAN so that other devices can reach them with ZERO configuration — just
connect to the same Wi-Fi.

Hosts-file injection is still offered as a local-machine fallback for
environments where mDNS is blocked (corporate firewalls, VPNs, etc.).
"""

import webbrowser
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


# ── Small helpers ──────────────────────────────────────────────────────────────

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


def _make_qr_pixmap(url: str, size: int = 180):
    try:
        import qrcode, io
        qr  = qrcode.make(url)
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


# ── Tab widget ─────────────────────────────────────────────────────────────────

class DnsTab(QWidget):
    """
    mDNS / Network Discovery management tab.

    Constructor parameters
    ----------------------
    mdns_server  — MDNSServer instance (from core.mdns_server)
    get_host_ip  — callable() → str  (returns current LAN IP)
    on_log       — optional callable(str)
    """

    def __init__(self, mdns_server, get_host_ip, on_log=None, parent=None):
        super().__init__(parent)
        self._mdns      = mdns_server
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
        v.addWidget(_lbl("Network Discovery", C_TEXT, 22, bold=True))
        v.addWidget(_lbl(
            "mDNS (Bonjour/Zeroconf) broadcasts pgops.local on your LAN so any device "
            "connected to the same Wi-Fi can reach PGOps with no configuration.",
            C_TEXT3, 12,
        ))

        # Status banner
        v.addWidget(self._status_banner())

        # mDNS control card
        v.addWidget(self._mdns_card())

        # Hosts file fallback card
        v.addWidget(self._hosts_card())

        # Per-platform instructions
        v.addWidget(self._instructions_card())

        # QR code
        v.addWidget(self._qr_card())

        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ── Status banner ──────────────────────────────────────────────────────────

    def _status_banner(self):
        w = QWidget()
        w.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(20, 14, 20, 14)
        h.setSpacing(20)

        # mDNS status
        mdns_col = QVBoxLayout()
        mdns_col.setSpacing(4)
        ml = _lbl("MDNS BROADCAST", C_TEXT3, 9, bold=True)
        ml.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        self._mdns_status_pill = QLabel("CHECKING...")
        self._mdns_status_pill.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;font-weight:700;background:transparent;"
        )
        mdns_col.addWidget(ml)
        mdns_col.addWidget(self._mdns_status_pill)
        h.addLayout(mdns_col)

        div = QWidget()
        div.setFixedSize(1, 36)
        div.setStyleSheet(f"background:{C_BORDER2};border:none;")
        h.addWidget(div)

        # Hosts file status
        hosts_col = QVBoxLayout()
        hosts_col.setSpacing(4)
        hl = _lbl("HOSTS FILE (LOCAL)", C_TEXT3, 9, bold=True)
        hl.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        self._hosts_status_pill = QLabel("CHECKING...")
        self._hosts_status_pill.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;font-weight:700;background:transparent;"
        )
        hosts_col.addWidget(hl)
        hosts_col.addWidget(self._hosts_status_pill)
        h.addLayout(hosts_col)

        div2 = QWidget()
        div2.setFixedSize(1, 36)
        div2.setStyleSheet(f"background:{C_BORDER2};border:none;")
        h.addWidget(div2)

        # Host IP
        ip_col = QVBoxLayout()
        ip_col.setSpacing(4)
        il = _lbl("HOST IP ADDRESS", C_TEXT3, 9, bold=True)
        il.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
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

        # Registered records count
        self._records_lbl = _lbl("", C_TEXT3, 11)
        h.addWidget(self._records_lbl)
        h.addSpacing(10)

        # Test button
        test_btn = _btn("Test Resolution", C_SURFACE2, C_BORDER2, C_TEXT2, h=32)
        test_btn.clicked.connect(self._test_resolution)
        h.addWidget(test_btn)

        self._test_result = QLabel("")
        self._test_result.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        h.addWidget(self._test_result)

        return w

    # ── mDNS control card ──────────────────────────────────────────────────────

    def _mdns_card(self):
        card = self._card("mDNS Broadcast  —  Zero-Config LAN Discovery")
        cv = card.layout()

        desc = QLabel(
            "When mDNS is running, every device on the same Wi-Fi can open "
            "http://pgops.local in their browser — no DNS settings, no hosts "
            "file edits required. Each deployed app is also reachable as "
            "http://<appname>.pgops.local."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        cv.addWidget(desc)

        # Registered apps list
        self._apps_lbl = _lbl("", C_TEXT3, 11)
        self._apps_lbl.setWordWrap(True)
        cv.addWidget(self._apps_lbl)

        btns = QHBoxLayout()
        self.btn_mdns_start = _btn("▶  Start mDNS", "#166534", "#15803d", "#86efac", h=34)
        self.btn_mdns_stop  = _btn("■  Stop",       "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_mdns_start.clicked.connect(self._start_mdns)
        self.btn_mdns_stop.clicked.connect(self._stop_mdns)
        btns.addWidget(self.btn_mdns_start)
        btns.addWidget(self.btn_mdns_stop)
        btns.addStretch()
        cv.addLayout(btns)

        note = QLabel(
            "mDNS starts automatically when PGOps launches. "
            "It requires no elevated privileges and uses UDP port 5353."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"background:#1e2a1e;color:#86efac;padding:10px 14px;"
            f"border-radius:6px;font-size:11px;"
        )
        cv.addWidget(note)
        return card

    # ── Hosts file card ────────────────────────────────────────────────────────

    def _hosts_card(self):
        card = self._card("Hosts File  —  Local Machine Fallback")
        cv = card.layout()

        desc = QLabel(
            "If mDNS is blocked on your machine (corporate firewall, VPN, etc.), "
            "inject pgops.local directly into the system hosts file. "
            "This only affects the machine running PGOps — other devices still "
            "use mDNS. Requires Administrator / sudo."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        cv.addWidget(desc)

        self._hosts_detail_lbl = _lbl("", C_TEXT3, 11)
        self._hosts_detail_lbl.setWordWrap(True)
        cv.addWidget(self._hosts_detail_lbl)

        btns = QHBoxLayout()
        self.btn_inject   = _btn("Inject Hosts File",  "#166534", "#15803d", "#86efac", h=34)
        self.btn_remove_h = _btn("Remove Entries",     "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_inject.clicked.connect(self._inject_hosts)
        self.btn_remove_h.clicked.connect(self._remove_hosts)
        btns.addWidget(self.btn_inject)
        btns.addWidget(self.btn_remove_h)
        btns.addStretch()
        cv.addLayout(btns)

        return card

    # ── Instructions card ──────────────────────────────────────────────────────

    def _instructions_card(self):
        card = self._card("Connecting Other Devices")
        cv = card.layout()

        cv.addWidget(_lbl(
            "With mDNS running, other devices just need to be on the same Wi-Fi network. "
            "No DNS changes, no IP addresses to remember.",
            C_TEXT3, 12,
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

        from core.mdns_server import get_client_setup_instructions
        instructions = get_client_setup_instructions()

        self._instr_texts: dict[str, QTextEdit] = {}
        for name, text in instructions.items():
            te = QTextEdit(text)
            te.setReadOnly(True)
            te.setFixedHeight(140)
            te.setStyleSheet(
                f"background:{C_SURFACE2};color:{C_TEXT2};"
                f"font-family:'Consolas','Courier New',monospace;"
                f"font-size:12px;border:none;padding:10px;"
            )
            self._instr_texts[name] = te
            tabs.addTab(te, name)

        cv.addWidget(tabs)
        return card

    # ── QR card ────────────────────────────────────────────────────────────────

    def _qr_card(self):
        card = self._card("Quick Connect — Scan on Other Devices")
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
        right.addWidget(_lbl("http://pgops.local", C_BLUE, 15, bold=True))
        right.addWidget(_lbl(
            "Scan on any device to open the PGOps landing page.\n"
            "No DNS configuration needed — just connect to the same Wi-Fi.",
            C_TEXT3, 12,
        ))

        copy_row = QHBoxLayout()
        copy_btn = _btn("Copy URL", C_SURFACE2, C_BORDER2, C_TEXT2, h=30)
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText("http://pgops.local"),
            copy_btn.setText("✓ Copied"),
            QTimer.singleShot(1400, lambda: copy_btn.setText("Copy URL")),
        ))
        open_btn = _btn("Open in Browser", C_BLUE, "#3b7de8", h=30)
        open_btn.clicked.connect(lambda: webbrowser.open("http://pgops.local"))
        copy_row.addWidget(copy_btn)
        copy_row.addWidget(open_btn)
        copy_row.addStretch()
        right.addLayout(copy_row)
        right.addStretch()
        h.addLayout(right)
        h.addStretch()
        cv.addLayout(h)
        return card

    # ── Card helper ────────────────────────────────────────────────────────────

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

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh(self):
        host_ip = self._get_ip()
        self._ip_display.setText(host_ip)

        # mDNS status
        mdns_running = self._mdns.is_running()
        if mdns_running:
            self._mdns_status_pill.setText("● RUNNING")
            self._mdns_status_pill.setStyleSheet(
                f"color:{C_GREEN};font-size:12px;font-weight:700;background:transparent;"
            )
            apps = self._mdns.registered_apps()
            rec_count = 1 + len(apps)   # pgops.local + app subdomains
            self._records_lbl.setText(f"{rec_count} .local record(s) active")
            if apps:
                self._apps_lbl.setText(
                    "Registered apps: " + ", ".join(f"{a}.pgops.local" for a in apps)
                )
            else:
                self._apps_lbl.setText("No app subdomains registered yet.")
        else:
            self._mdns_status_pill.setText("● STOPPED")
            self._mdns_status_pill.setStyleSheet(
                f"color:{C_RED};font-size:12px;font-weight:700;background:transparent;"
            )
            self._records_lbl.setText("")
            self._apps_lbl.setText("")

        # Hosts file status
        from core.dns_server import is_hosts_injected, get_hosts_current_ip
        injected    = is_hosts_injected()
        injected_ip = get_hosts_current_ip()

        if injected and injected_ip:
            if injected_ip == host_ip:
                self._hosts_status_pill.setText("● ACTIVE")
                self._hosts_status_pill.setStyleSheet(
                    f"color:{C_GREEN};font-size:12px;font-weight:700;background:transparent;"
                )
                self._hosts_detail_lbl.setText(
                    f"✓ pgops.local → {injected_ip}  (up to date)"
                )
            else:
                self._hosts_status_pill.setText("⚠ STALE IP")
                self._hosts_status_pill.setStyleSheet(
                    f"color:{C_AMBER};font-size:12px;font-weight:700;background:transparent;"
                )
                self._hosts_detail_lbl.setText(
                    f"pgops.local → {injected_ip}  "
                    f"(outdated — current IP is {host_ip})"
                )
        else:
            self._hosts_status_pill.setText("● NOT SET")
            self._hosts_status_pill.setStyleSheet(
                f"color:{C_TEXT3};font-size:12px;font-weight:700;background:transparent;"
            )
            self._hosts_detail_lbl.setText(
                "Not injected. Click 'Inject Hosts File' to add a local entry."
            )

        # QR code
        px = _make_qr_pixmap("http://pgops.local", 170)
        if px:
            self._qr_lbl.setPixmap(px)
        else:
            self._qr_lbl.setText("Install qrcode\npip install qrcode")
            self._qr_lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:11px;"
                f"background:{C_SURFACE2};border:1px solid {C_BORDER};border-radius:8px;"
            )

    # ── Button handlers ────────────────────────────────────────────────────────

    def _start_mdns(self):
        ok, msg = self._mdns.start()
        self._on_log(f"[mDNS] {msg}")
        if not ok:
            QMessageBox.warning(self, "mDNS", msg)
        self.refresh()

    def _stop_mdns(self):
        reply = QMessageBox.question(
            self, "Stop mDNS",
            "Stopping mDNS means other devices can no longer reach pgops.local "
            "or app subdomains automatically.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self._mdns.stop()
        self._on_log(f"[mDNS] {msg}")
        self.refresh()

    def _inject_hosts(self):
        from core.app_manager import load_apps
        apps = load_apps()
        # Build the list of .local domains for deployed apps
        app_domains = []
        for app in apps:
            domain = app.get("domain", "")
            if domain:
                # domain is stored as e.g. "myapp.pgops.local" — keep as-is
                app_domains.append(domain)
        ok, msg = self._mdns.inject_hosts(app_domains=app_domains)
        self._on_log(f"[Hosts] {msg}")
        if ok:
            QMessageBox.information(
                self, "Hosts File Updated",
                f"{msg}\n\nYou can now open http://pgops.local in your browser."
            )
        else:
            QMessageBox.warning(self, "Hosts File Error", msg)
        self.refresh()

    def _remove_hosts(self):
        ok, msg = self._mdns.remove_hosts()
        self._on_log(f"[Hosts] {msg}")
        self.refresh()

    def _test_resolution(self):
        from core.dns_server import test_resolution
        ok, msg = test_resolution("pgops.local")
        self._test_result.setText(msg)
        color = C_GREEN if ok else C_RED
        self._test_result.setStyleSheet(
            f"color:{color};font-size:11px;background:transparent;"
        )
        self._on_log(f"[mDNS Test] {msg}")
