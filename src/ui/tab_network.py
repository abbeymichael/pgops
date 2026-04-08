from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QScrollArea, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont

from core.network_info import get_all_interfaces
from core.mdns import verify_mdns_resolution
from core.hotspot import start_hotspot, stop_hotspot, open_hotspot_settings
from core.config import save_config
from ui.theme import (
    C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_RED, C_AMBER, C_PURPLE,
    TABLE_STYLE,
)


def _btn(text, bg=C_BLUE, hover="#3b7de8", fg="white", h=36):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 16px;font-size:12px;font-weight:700;}}"
        f"QPushButton:hover{{background:{hover};}}"
    )
    return b


def _lbl(text, color=C_TEXT2, size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;background:transparent;")
    return l


def _inp(val=""):
    f = QLineEdit(val)
    f.setFixedHeight(36)
    f.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 11px;color:{C_TEXT};font-size:13px;}}"
        f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
    )
    return f


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


def _copy_row(label, value):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(label)
    lbl.setFixedWidth(70)
    lbl.setStyleSheet(f"color:{C_TEXT3};font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;")
    field = QLineEdit(value)
    field.setReadOnly(True)
    field.setFixedHeight(32)
    field.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 10px;color:{C_TEXT};"
        f"font-family:'Consolas','Courier New',monospace;font-size:12px;}}"
    )
    copy_btn = QPushButton("Copy")
    copy_btn.setFixedSize(50, 30)
    copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    copy_btn.setStyleSheet(
        f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
        f"border:1px solid {C_BORDER2};border-radius:5px;font-size:11px;font-weight:600;}}"
        f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
    )
    copy_btn.clicked.connect(lambda: (
        QApplication.clipboard().setText(field.text()),
        copy_btn.setText("✓"),
        QTimer.singleShot(1200, lambda: copy_btn.setText("Copy"))
    ))
    row.addWidget(lbl)
    row.addWidget(field)
    row.addWidget(copy_btn)
    w._field = field
    return w


class NetworkTab(QWidget):
    """
    Standalone Network page.
    on_mdns_start/stop/test — pass in from main_window
    on_pin/unpin            — pass in from main_window
    on_log(msg)
    """

    def __init__(self, config, mdns, manager,
                 on_mdns_start, on_mdns_stop, on_mdns_test,
                 on_pin, on_unpin, on_log,
                 parent=None):
        super().__init__(parent)
        self.config        = config
        self._mdns         = mdns
        self._manager      = manager
        self._on_mdns_start = on_mdns_start
        self._on_mdns_stop  = on_mdns_stop
        self._on_mdns_test  = on_mdns_test
        self._on_pin        = on_pin
        self._on_unpin      = on_unpin
        self._on_log        = on_log
        self._build()

    def update_config(self, config):
        self.config = config

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

        title = QLabel("Network")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:22px;font-weight:800;background:transparent;"
        )
        sub = QLabel("Manage network interfaces, mDNS broadcasting, and WiFi hotspot.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        # ── Interfaces card ────────────────────────────────────────────────────
        iface_card = self._card("Available Network Interfaces")
        ic = iface_card.layout()

        self.iface_table = QTableWidget(0, 3)
        self.iface_table.setHorizontalHeaderLabels(["Adapter", "IP Address", "Type"])
        self.iface_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.iface_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.iface_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.iface_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.iface_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.iface_table.setStyleSheet(TABLE_STYLE)
        self.iface_table.verticalHeader().setVisible(False)
        self.iface_table.setMaximumHeight(180)
        ic.addWidget(self.iface_table)

        pin_row = QHBoxLayout()
        pin_row.addWidget(_lbl("Pinned IP:"))
        pin_row.addSpacing(8)
        self.pinned_ip_lbl = QLabel(self.config.get("preferred_ip", "") or "Auto-detect")
        self.pinned_ip_lbl.setStyleSheet(
            f"color:{C_GREEN};font-size:13px;"
            f"font-family:'Consolas','Courier New',monospace;font-weight:bold;"
        )
        pin_row.addWidget(self.pinned_ip_lbl)
        pin_row.addStretch()
        for text, fn in [
            ("Pin Selected", self._pin_ip),
            ("Auto-detect",  self._unpin_ip),
            ("↻  Refresh",   self._refresh_ifaces),
        ]:
            b = _btn(text, C_SURFACE2, C_BORDER2, C_TEXT2, h=30)
            b.clicked.connect(fn)
            pin_row.addWidget(b)
        ic.addLayout(pin_row)
        ic.addWidget(_lbl(
            "Hotspot IP (192.168.137.1) is always fixed — pin it when using hotspot mode "
            "so your apps always use the same address.", C_TEXT3, 11
        ))
        v.addWidget(iface_card)

        # ── mDNS card ──────────────────────────────────────────────────────────
        mdns_card = self._card("Local Domain  —  pgops.test")
        mc = mdns_card.layout()

        self.mdns_status_lbl = QLabel("Checking...")
        self.mdns_status_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:13px;font-weight:700;background:transparent;"
        )
        mc.addWidget(self.mdns_status_lbl)

        self._mdns_host_row = _copy_row("Host", "pgops.test")
        mc.addWidget(self._mdns_host_row)

        mdns_btns = QHBoxLayout()
        for text, fn in [
            ("Start Broadcasting", self._on_mdns_start),
            ("Stop",               self._on_mdns_stop),
            ("Test Resolution",    self._on_mdns_test),
        ]:
            bg = "#166534" if "Start" in text else "#7f1d1d" if "Stop" in text else C_SURFACE2
            hov = "#15803d" if "Start" in text else "#991b1b" if "Stop" in text else C_BORDER2
            fg = "#86efac" if "Start" in text else "#fca5a5" if "Stop" in text else C_TEXT2
            b = _btn(text, bg, hov, fg, h=32)
            b.clicked.connect(fn)
            mdns_btns.addWidget(b)
        mc.addLayout(mdns_btns)

        port = self.config["port"]
        self._mdns_conn_row = _copy_row(
            "Conn",
            f"postgresql://user:pass@pgops.test:{port}/dbname"
        )
        mc.addWidget(self._mdns_conn_row)
        mc.addWidget(_lbl(
            "pgops.test broadcasts automatically on every launch.  "
            "Windows 10/11: native.  Older Windows: install Bonjour.  "
            "macOS/iOS: native.  Linux: avahi-daemon.  Android: usually works.",
            C_TEXT3, 11
        ))
        v.addWidget(mdns_card)

        # ── Hotspot card ───────────────────────────────────────────────────────
        hs_card = self._card("WiFi Hotspot  —  Windows Mobile Hotspot")
        hv = hs_card.layout()

        r1 = QHBoxLayout()
        self.hs_ssid = _inp("PGOps-Net")
        self.hs_pw   = _inp("postgres123")
        for lt, fld in [("SSID", self.hs_ssid), ("Password (8+)", self.hs_pw)]:
            l = _lbl(lt.upper(), C_TEXT3, 10)
            l.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1px;background:transparent;"
            )
            l.setFixedWidth(120)
            r1.addWidget(l)
            r1.addWidget(fld)
        hv.addLayout(r1)

        r2 = QHBoxLayout()
        for text, fn in [
            ("Start Hotspot",  self._start_hotspot),
            ("Stop Hotspot",   self._stop_hotspot),
            ("Open Settings",  self._open_hs_settings),
        ]:
            bg  = "#166534" if "Start" in text else "#7f1d1d" if "Stop" in text else C_SURFACE2
            hov = "#15803d" if "Start" in text else "#991b1b" if "Stop" in text else C_BORDER2
            fg  = "#86efac" if "Start" in text else "#fca5a5" if "Stop" in text else C_TEXT2
            b = _btn(text, bg, hov, fg, h=34)
            b.clicked.connect(fn)
            r2.addWidget(b)
        hv.addLayout(r2)

        self.hs_msg = _lbl("", C_TEXT2, 12)
        self.hs_msg.setWordWrap(True)
        hv.addWidget(self.hs_msg)
        v.addWidget(hs_card)

        # ── Firewall card ──────────────────────────────────────────────────────
        fw_card = self._card("Firewall  —  run once as Administrator")
        fv = fw_card.layout()
        fw_row = _copy_row(
            "CMD",
            f'netsh advfirewall firewall add rule name="PGOps" dir=in '
            f'action=allow protocol=TCP localport={self.config["port"]}'
        )
        fv.addWidget(fw_row)
        fv.addWidget(_lbl("Run this once so other devices can reach the database.", C_TEXT3, 11))
        v.addWidget(fw_card)

        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        QTimer.singleShot(300, self._refresh_ifaces)

    def _card(self, title):
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

    def _refresh_ifaces(self):
        try:
            ifaces = get_all_interfaces()
        except Exception as e:
            self._on_log(f"Interface scan error: {e}"); return

        self.iface_table.setRowCount(0)
        pinned = self.config.get("preferred_ip", "")
        TYPE_C = {
            "hotspot": C_GREEN, "lan": C_BLUE, "wifi": C_PURPLE,
            "loopback": C_TEXT3, "other": C_TEXT2,
        }
        TYPE_L = {
            "hotspot": "Hotspot (fixed)", "lan": "Ethernet LAN",
            "wifi": "Wi-Fi", "loopback": "Loopback", "other": "Other",
        }
        for iface in ifaces:
            row = self.iface_table.rowCount()
            self.iface_table.insertRow(row)
            color = TYPE_C.get(iface["type"], C_TEXT2)
            for col, val in enumerate([
                iface["name"], iface["ip"], TYPE_L.get(iface["type"], iface["type"])
            ]):
                item = QTableWidgetItem(val)
                item.setForeground(QColor(color))
                if iface["ip"] == pinned or iface["type"] == "hotspot":
                    f = QFont(); f.setBold(True); item.setFont(f)
                if col == 1:
                    item.setData(Qt.ItemDataRole.UserRole, iface["ip"])
                self.iface_table.setItem(row, col, item)
        self.pinned_ip_lbl.setText(pinned if pinned else "Auto-detect")

    def _pin_ip(self):
        row = self.iface_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select an IP", "Click a row first."); return
        item = self.iface_table.item(row, 1)
        if not item: return
        ip = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self._on_pin(ip)
        self.pinned_ip_lbl.setText(ip)

    def _unpin_ip(self):
        self._on_unpin()
        self.pinned_ip_lbl.setText("Auto-detect")

    def update_mdns_status(self, is_running, ip=""):
        if is_running:
            self.mdns_status_lbl.setText(f"BROADCASTING  pgops.test  →  {ip}")
            self.mdns_status_lbl.setStyleSheet(
                f"color:{C_GREEN};font-size:13px;font-weight:700;background:transparent;"
            )
        else:
            self.mdns_status_lbl.setText("Not broadcasting — click Start Broadcasting to resume")
            self.mdns_status_lbl.setStyleSheet(
                f"color:{C_RED};font-size:13px;font-weight:700;background:transparent;"
            )

    def _start_hotspot(self):
        ok, msg = start_hotspot(self.hs_ssid.text(), self.hs_pw.text())
        self.hs_msg.setText(msg)
        self.hs_msg.setStyleSheet(
            f"color:{C_GREEN if ok else C_RED};font-size:12px;background:transparent;"
        )
        self._on_log(msg)

    def _stop_hotspot(self):
        ok, msg = stop_hotspot()
        self.hs_msg.setText(msg)
        self.hs_msg.setStyleSheet(
            f"color:{C_GREEN if ok else C_RED};font-size:12px;background:transparent;"
        )
        self._on_log(msg)

    def _open_hs_settings(self):
        ok, msg = open_hotspot_settings()
        self._on_log(msg)
