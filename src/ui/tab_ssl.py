"""
tab_ssl.py
Unified SSL / TLS page — mkcert edition.

Architecture:
  - mkcert issues ALL certificates (web HTTPS + PostgreSQL TLS)
  - Caddy serves every domain via the mkcert cert (pgops.test, *.pgops.test)
  - PostgreSQL uses the same mkcert cert for encrypted DB connections
  - LAN devices install the rootCA.pem once → zero browser warnings forever

Sections:
  1. mkcert Setup & CA Trust   — install mkcert, trust CA, export for LAN devices
  2. Domain Map                — shows every domain/port Caddy is routing
  3. PostgreSQL TLS            — enable/disable encrypted DB connections
"""

import platform
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QMessageBox, QFileDialog, QApplication,
    QTabWidget, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal

from core.pg_manager import BASE_DIR, DATA_DIR
from ui.theme import (
    C_BG, C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_RED, C_AMBER,
)


def _btn(text, bg=C_BLUE, hover="#3b7de8", fg="white", h=36):
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


def _lbl(text, color=C_TEXT2, size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;background:transparent;")
    return l


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


def _badge(text: str, color: str):
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{color};font-size:11px;font-weight:700;background:transparent;"
    )
    return l


def _mono_row(label_text: str, value: str):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    lbl = QLabel(label_text)
    lbl.setFixedWidth(100)
    lbl.setStyleSheet(
        f"color:{C_TEXT3};font-size:10px;font-weight:700;"
        f"letter-spacing:1px;background:transparent;"
    )
    field = QLineEdit(value)
    field.setReadOnly(True)
    field.setFixedHeight(32)
    field.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 10px;color:{C_TEXT};"
        f"font-family:'Consolas','Courier New',monospace;font-size:11px;}}"
    )
    copy_btn = QPushButton("Copy")
    copy_btn.setFixedSize(52, 30)
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
    return w


class _Worker(QThread):
    done = pyqtSignal(bool, str)
    progress = pyqtSignal(int)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
            if isinstance(result, tuple):
                ok, msg = bool(result[0]), str(result[1])
            elif result is None:
                ok, msg = True, ""
            else:
                ok, msg = bool(result), ""
            self.done.emit(ok, msg)
        except Exception as exc:
            self.done.emit(False, str(exc))


class SslTab(QWidget):
    """
    SSL / TLS management page.

    Three sections:
      1. mkcert — setup, CA install, cert generation, LAN device export
      2. Domain map — what Caddy is routing right now
      3. PostgreSQL TLS — encrypt the DB connection
    """

    def __init__(self, config, manager, on_log, caddy_manager=None, parent=None):
        super().__init__(parent)
        self.config   = config
        self._manager = manager
        self._on_log  = on_log
        self._caddy   = caddy_manager
        self._workers: list = []
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:#1a1d23;border:none;")

        inner = QWidget()
        inner.setStyleSheet("background:#1a1d23;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(20)

        title = QLabel("SSL / TLS")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:22px;font-weight:800;background:transparent;"
        )
        sub = QLabel(
            "PGOps uses mkcert to issue trusted certificates for every service. "
            "Install the CA once on each device — then all *.pgops.test domains get a "
            "green padlock automatically, no browser warnings."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        v.addWidget(self._mkcert_section())
        v.addWidget(self._domains_section())
        v.addWidget(self._postgres_section())

        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        QTimer.singleShot(300, self.refresh_status)

    # ── Section 1: mkcert ─────────────────────────────────────────────────────

    def _mkcert_section(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel("mkcert  —  Automatic Trusted Certificates")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        self._mkcert_badge = QLabel("CHECKING...")
        self._mkcert_badge.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._mkcert_badge)
        v.addLayout(hdr)
        v.addWidget(_sep())

        desc = _lbl(
            "mkcert creates a local Certificate Authority trusted by your OS. "
            "Every certificate it issues is trusted by all browsers — no warnings. "
            "LAN devices only need to install the CA once.",
            C_TEXT3, 12
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._mkcert_detail = _lbl("", C_TEXT3, 11)
        self._mkcert_detail.setWordWrap(True)
        v.addWidget(self._mkcert_detail)

        # Action buttons
        btns1 = QHBoxLayout()
        self.btn_mkcert_setup   = _btn("Setup mkcert",       C_BLUE,     "#3b7de8", h=36)
        self.btn_install_ca     = _btn("Install CA (Trust)", "#166534",  "#15803d", "#86efac", h=36)
        self.btn_gen_cert       = _btn("Regenerate Cert",    C_SURFACE2, C_BORDER2, C_TEXT2,  h=36)

        self.btn_mkcert_setup.clicked.connect(self._do_setup_mkcert)
        self.btn_install_ca.clicked.connect(self._do_install_ca)
        self.btn_gen_cert.clicked.connect(self._do_gen_cert)

        btns1.addWidget(self.btn_mkcert_setup)
        btns1.addWidget(self.btn_install_ca)
        btns1.addWidget(self.btn_gen_cert)
        btns1.addStretch()
        v.addLayout(btns1)

        btns2 = QHBoxLayout()
        self.btn_export_ca = _btn("Export CA for LAN Devices", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        self.btn_export_ca.clicked.connect(self._do_export_ca)
        btns2.addWidget(self.btn_export_ca)
        btns2.addStretch()
        v.addLayout(btns2)

        # LAN device install instructions
        inst_card = QWidget()
        inst_card.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER2};border-radius:8px;"
        )
        iv = QVBoxLayout(inst_card)
        iv.setContentsMargins(14, 12, 14, 12)
        iv.setSpacing(8)
        iv.addWidget(_lbl("HOW TO TRUST ON LAN DEVICES  (one time per device)", C_TEXT3, 10))

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:4px;margin-top:-1px;}}"
            f"QTabBar::tab{{background:{C_SURFACE};color:{C_TEXT3};"
            f"padding:4px 12px;border:1px solid {C_BORDER};"
            f"border-bottom:none;border-radius:3px 3px 0 0;font-size:11px;}}"
            f"QTabBar::tab:selected{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )
        instructions = {
            "Windows": (
                "1. Click 'Export CA for LAN Devices' on the HOST machine\n"
                "2. Share pgops-ca.pem to the Windows device (USB / network share)\n"
                "3. Rename to pgops-ca.crt\n"
                "4. Double-click → Install Certificate\n"
                "5. Store: Local Machine → Trusted Root Certification Authorities\n"
                "6. Finish → Yes → OK\n"
                "7. Restart browser\n\n"
                "Chrome/Edge will trust it immediately. Firefox needs its own import\n"
                "(see the Firefox tab)."
            ),
            "macOS": (
                "1. Click 'Export CA for LAN Devices' on the HOST machine\n"
                "2. Share pgops-ca.pem to the Mac (AirDrop / network share)\n"
                "3. Double-click the file → Keychain Access opens\n"
                "4. Find 'mkcert ...' entry → double-click\n"
                "5. Expand Trust → 'When using this certificate' → Always Trust\n"
                "6. Close → enter password\n"
                "7. Restart browser"
            ),
            "iOS / iPadOS": (
                "1. Export pgops-ca.pem from the HOST machine\n"
                "2. Rename to pgops-ca.crt and AirDrop / email it to iPhone/iPad\n"
                "3. Tap the file → 'Profile Downloaded' appears\n"
                "4. Settings → General → VPN & Device Management → install the profile\n"
                "5. Settings → General → About → Certificate Trust Settings\n"
                "6. Enable full trust for 'mkcert ...'\n\n"
                "All *.pgops.test domains will now have a green padlock in Safari."
            ),
            "Android": (
                "1. Export pgops-ca.pem from the HOST machine\n"
                "2. Transfer the file to the Android device\n"
                "3. Settings → Security → Install from storage → select pgops-ca.pem\n"
                "4. Name it 'PGOps CA', credential use: VPN and apps\n\n"
                "Chrome on Android requires an extra step:\n"
                "  Settings → Privacy & Security → Security → Manage device certificates\n"
                "  Confirm the certificate is listed under User tab."
            ),
            "Linux": (
                "Ubuntu / Debian:\n"
                "  sudo cp pgops-ca.pem /usr/local/share/ca-certificates/pgops-ca.crt\n"
                "  sudo update-ca-certificates\n\n"
                "Fedora / RHEL:\n"
                "  sudo cp pgops-ca.pem /etc/pki/ca-trust/source/anchors/pgops-ca.pem\n"
                "  sudo update-ca-trust\n\n"
                "Then restart the browser. Chrome on Linux also reads the system store."
            ),
            "Firefox": (
                "Firefox maintains its own certificate store regardless of OS.\n\n"
                "1. Export pgops-ca.pem from the HOST machine\n"
                "2. Firefox → Settings → Privacy & Security\n"
                "3. Scroll to Certificates → View Certificates\n"
                "4. Authorities tab → Import → select pgops-ca.pem\n"
                "5. Check 'Trust this CA to identify websites'\n"
                "6. OK → restart Firefox\n\n"
                "Required on EVERY device running Firefox, even if the OS already trusts the CA."
            ),
        }
        for name, text in instructions.items():
            te = QTextEdit(text)
            te.setReadOnly(True)
            te.setFixedHeight(120)
            te.setStyleSheet(
                f"background:{C_SURFACE};color:{C_TEXT2};"
                f"font-family:'Consolas','Courier New',monospace;"
                f"font-size:11px;border:none;padding:8px;"
            )
            tabs.addTab(te, name)
        iv.addWidget(tabs)
        v.addWidget(inst_card)

        return card

    # ── Section 2: Domain map ─────────────────────────────────────────────────

    def _domains_section(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        hdr = QHBoxLayout()
        t = QLabel("Domain Map  —  What Caddy Is Routing")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        self._caddy_run_badge = QLabel("CHECKING...")
        self._caddy_run_badge.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._caddy_run_badge)
        v.addLayout(hdr)
        v.addWidget(_sep())

        desc = _lbl(
            "Every service has a permanent HTTPS domain. "
            "Caddy automatically routes traffic to the correct backend port.",
            C_TEXT3, 12
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._domain_table = QTableWidget(0, 3)
        self._domain_table.setHorizontalHeaderLabels(["Domain", "Backend", "Status"])
        self._domain_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._domain_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._domain_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._domain_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._domain_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._domain_table.setAlternatingRowColors(True)
        self._domain_table.verticalHeader().setVisible(False)
        self._domain_table.setFixedHeight(200)
        self._domain_table.setStyleSheet(
            f"QTableWidget{{background:{C_SURFACE};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;gridline-color:{C_BORDER};"
            f"font-size:12px;}}"
            f"QTableWidget::item{{padding:5px 10px;}}"
            f"QTableWidget::item:selected{{background:{C_BLUE}44;color:{C_TEXT};}}"
            f"QTableWidget::item:alternate{{background:{C_SURFACE2};}}"
            f"QHeaderView::section{{background:{C_SURFACE2};color:{C_TEXT3};"
            f"padding:6px 10px;border:none;border-bottom:1px solid {C_BORDER};"
            f"font-size:10px;font-weight:700;letter-spacing:1px;}}"
        )
        v.addWidget(self._domain_table)

        note = _lbl(
            "Stopped services show a 502 — that's expected. Start the service to resolve it.",
            C_TEXT3, 11
        )
        v.addWidget(note)

        return card

    # ── Section 3: PostgreSQL TLS ─────────────────────────────────────────────

    def _postgres_section(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        hdr = QHBoxLayout()
        t = QLabel("PostgreSQL TLS  —  Encrypted Database Connections")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        self.ssl_status_lbl = QLabel("Checking...")
        self.ssl_status_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:13px;font-weight:700;background:transparent;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self.ssl_status_lbl)
        v.addLayout(hdr)
        v.addWidget(_sep())

        desc = _lbl(
            "Encrypts the connection between apps and PostgreSQL using the same mkcert "
            "certificate. Apps connect with sslmode=require — no extra cert distribution needed "
            "because the CA is already trusted.",
            C_TEXT3, 12
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self.ssl_cert_lbl = _lbl("", C_TEXT3, 11)
        self.ssl_cert_lbl.setWordWrap(True)
        v.addWidget(self.ssl_cert_lbl)

        cert_btns = QHBoxLayout()
        self.btn_ssl_on  = _btn("Enable SSL",  "#166534", "#15803d", "#86efac", h=34)
        self.btn_ssl_off = _btn("Disable SSL", "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_ssl_on.clicked.connect(self._enable_ssl)
        self.btn_ssl_off.clicked.connect(self._disable_ssl)
        cert_btns.addWidget(self.btn_ssl_on)
        cert_btns.addWidget(self.btn_ssl_off)
        cert_btns.addStretch()
        v.addLayout(cert_btns)

        port = self.config.get("port", 5432)
        conn_card = QWidget()
        conn_card.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER2};border-radius:8px;"
        )
        cv = QVBoxLayout(conn_card)
        cv.setContentsMargins(14, 12, 14, 12)
        cv.setSpacing(8)
        cv.addWidget(_lbl("CLIENT CONNECTION STRINGS", C_TEXT3, 10))
        cv.addWidget(_mono_row("URL", f"postgresql://user:pass@pgops.test:{port}/dbname?sslmode=require"))
        cv.addWidget(_mono_row("Laravel", "DB_SSLMODE=require  (in .env)"))
        cv.addWidget(_mono_row("psycopg2", "sslmode='require'  (in connect())"))
        v.addWidget(conn_card)

        note = _lbl(
            "After enabling SSL, restart the PostgreSQL server for changes to take effect.",
            C_TEXT3, 11
        )
        note.setWordWrap(True)
        v.addWidget(note)

        return card

    # ── Status refresh ─────────────────────────────────────────────────────────

    def refresh_status(self):
        self._update_mkcert_status()
        self._update_caddy_domain_map()
        self._update_pg_ssl_status()

    def _update_mkcert_status(self):
        try:
            from core.mkcert_manager import get_status
            s = get_status()
        except Exception as exc:
            self._mkcert_badge.setText(f"ERROR: {exc}")
            return

        available    = s.get("available", False)
        ca_installed = s.get("ca_installed", False)
        cert_exists  = s.get("cert_exists", False)
        cert_info    = s.get("cert_info", {})
        ca_path      = s.get("ca_path", "")

        if available and ca_installed and cert_exists:
            self._mkcert_badge.setText("● TRUSTED & READY")
            self._mkcert_badge.setStyleSheet(
                f"color:{C_GREEN};font-size:11px;font-weight:700;background:transparent;"
            )
        elif available and ca_installed:
            self._mkcert_badge.setText("● CA INSTALLED  —  cert missing")
            self._mkcert_badge.setStyleSheet(
                f"color:{C_AMBER};font-size:11px;font-weight:700;background:transparent;"
            )
        elif available:
            self._mkcert_badge.setText("● AVAILABLE  —  CA not installed")
            self._mkcert_badge.setStyleSheet(
                f"color:{C_AMBER};font-size:11px;font-weight:700;background:transparent;"
            )
        else:
            self._mkcert_badge.setText("● NOT SET UP")
            self._mkcert_badge.setStyleSheet(
                f"color:{C_RED};font-size:11px;font-weight:700;background:transparent;"
            )

        parts = []
        if available:
            parts.append("mkcert binary: ready")
        else:
            parts.append("mkcert binary: not found — click Setup mkcert")

        if ca_installed:
            parts.append(f"CA: installed and trusted  ({ca_path})")
        else:
            parts.append("CA: not installed — click Install CA (Trust)")

        if cert_info.get("expires"):
            parts.append(
                f"Certificate: expires {cert_info['expires']}  ·  "
                f"covers {cert_info.get('domains', 'pgops.test, *.pgops.test')}"
            )
        elif cert_exists:
            parts.append("Certificate: present")
        else:
            parts.append("Certificate: not generated — click Regenerate Cert")

        self._mkcert_detail.setText("\n".join(parts))

        self.btn_export_ca.setEnabled(ca_installed)
        self.btn_gen_cert.setEnabled(available)
        self.btn_install_ca.setEnabled(available)

    def _update_caddy_domain_map(self):
        if not self._caddy:
            self._caddy_run_badge.setText("Caddy not configured")
            return

        running = self._caddy.is_running()
        if running:
            self._caddy_run_badge.setText("● RUNNING")
            self._caddy_run_badge.setStyleSheet(
                f"color:{C_GREEN};font-size:11px;font-weight:700;background:transparent;"
            )
        else:
            self._caddy_run_badge.setText("● STOPPED")
            self._caddy_run_badge.setStyleSheet(
                f"color:{C_RED};font-size:11px;font-weight:700;background:transparent;"
            )

        # Build domain rows
        try:
            from core.app_manager import load_apps
            apps = load_apps()
        except Exception:
            apps = []

        https_port = self._caddy.https_port
        minio_api  = self._caddy.minio_api_port
        minio_con  = self._caddy.minio_console_port
        pgadmin_p  = self._caddy.pgadmin_port
        landing_p  = self._caddy.landing_port

        base_rows = [
            ("https://pgops.test",         f"localhost:{landing_p}",  "Landing Page"),
            ("https://minio.pgops.test",    f"localhost:{minio_api}",  "MinIO S3 API"),
            ("https://console.pgops.test",  f"localhost:{minio_con}",  "MinIO Console"),
            ("https://pgadmin.pgops.test",  f"localhost:{pgadmin_p}",  "pgAdmin 4"),
        ]

        app_rows = [
            (
                f"https://{app.get('domain', '')}",
                f"localhost:{app.get('internal_port', '?')}",
                app.get("display_name", app.get("id", "")),
            )
            for app in apps if app.get("domain")
        ]

        all_rows = base_rows + app_rows
        self._domain_table.setRowCount(len(all_rows))

        for i, (domain, backend, label) in enumerate(all_rows):
            self._domain_table.setItem(i, 0, QTableWidgetItem(domain))
            self._domain_table.setItem(i, 1, QTableWidgetItem(backend))
            item = QTableWidgetItem(label)
            if running:
                item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(C_GREEN))
            else:
                item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(C_RED))
            self._domain_table.setItem(i, 2, item)

    def _update_pg_ssl_status(self):
        try:
            from core.ssl_manager import get_ssl_status, get_cert_info, is_ssl_configured
            status    = get_ssl_status(DATA_DIR)
            cert_info = get_cert_info(BASE_DIR)
        except Exception as exc:
            self.ssl_cert_lbl.setText(f"Error reading SSL status: {exc}")
            return

        if status["enabled"]:
            self.ssl_status_lbl.setText("● SSL ENABLED")
            self.ssl_status_lbl.setStyleSheet(
                f"color:{C_GREEN};font-size:13px;font-weight:700;background:transparent;"
            )
        else:
            self.ssl_status_lbl.setText("● SSL DISABLED")
            self.ssl_status_lbl.setStyleSheet(
                f"color:{C_RED};font-size:13px;font-weight:700;background:transparent;"
            )

        if cert_info and "expires" in cert_info:
            self.ssl_cert_lbl.setText(
                f"Subject: {cert_info.get('subject', '')}  ·  "
                f"Expires: {cert_info.get('expires', '')}  ·  "
                f"Serial: {cert_info.get('serial', '')}"
            )
        elif cert_info and "error" in cert_info:
            self.ssl_cert_lbl.setText(f"Cert error: {cert_info['error']}")
        else:
            try:
                if not is_ssl_configured(BASE_DIR):
                    self.ssl_cert_lbl.setText(
                        "PostgreSQL will use the mkcert certificate once generated. "
                        "Click Enable SSL to activate."
                    )
            except Exception:
                pass

    # ── mkcert action handlers ─────────────────────────────────────────────────

    def _do_setup_mkcert(self):
        self.btn_mkcert_setup.setEnabled(False)
        self.btn_mkcert_setup.setText("Setting up...")

        def fn(pc):
            from core.mkcert_manager import setup_mkcert
            return setup_mkcert(progress_callback=pc)

        def done(ok, msg):
            self.btn_mkcert_setup.setEnabled(True)
            self.btn_mkcert_setup.setText("Setup mkcert")
            self._on_log(f"[mkcert] {msg}")
            self._update_mkcert_status()
            if ok:
                # Auto-install CA after setup
                QTimer.singleShot(300, self._do_install_ca)
            else:
                QMessageBox.critical(self, "Setup Failed", msg)

        w = _Worker(fn)
        w.done.connect(done)
        w.start()
        self._workers.append(w)

    def _do_install_ca(self):
        self.btn_install_ca.setEnabled(False)
        self.btn_install_ca.setText("Installing...")

        def fn(_pc):
            from core.mkcert_manager import install_ca
            return install_ca(log_fn=self._on_log)

        def done(ok, msg):
            self.btn_install_ca.setEnabled(True)
            self.btn_install_ca.setText("Install CA (Trust)")
            self._on_log(f"[mkcert] {msg}")
            self._update_mkcert_status()
            if ok:
                QMessageBox.information(
                    self, "CA Installed",
                    f"{msg}\n\nRestart your browser for the change to take effect.\n\n"
                    "For LAN devices, export the CA and install it there too."
                )
                # Auto-generate cert if not present
                from core.mkcert_manager import is_cert_generated
                if not is_cert_generated():
                    QTimer.singleShot(300, self._do_gen_cert)
            else:
                QMessageBox.warning(
                    self, "CA Install Failed",
                    f"{msg}\n\nTry running PGOps as Administrator / with sudo."
                )

        w = _Worker(fn)
        w.done.connect(done)
        w.start()
        self._workers.append(w)

    def _do_gen_cert(self):
        self.btn_gen_cert.setEnabled(False)
        self.btn_gen_cert.setText("Generating...")

        def fn(_pc):
            from core.mkcert_manager import generate_cert
            return generate_cert(log_fn=self._on_log)

        def done(ok, msg):
            self.btn_gen_cert.setEnabled(True)
            self.btn_gen_cert.setText("Regenerate Cert")
            self._on_log(f"[mkcert] {msg}")
            self._update_mkcert_status()
            if ok:
                # Reload Caddy so it picks up the new cert
                if self._caddy and self._caddy.is_running():
                    try:
                        from core.app_manager import load_apps
                        ok2, msg2 = self._caddy.reload(
                            apps=load_apps(),
                            pgadmin_running=False,
                        )
                        self._on_log(f"[Caddy] {msg2}")
                    except Exception as exc:
                        self._on_log(f"[Caddy] reload after cert gen: {exc}")
                self._update_caddy_domain_map()
            else:
                QMessageBox.critical(self, "Certificate Error", msg)

        w = _Worker(fn)
        w.done.connect(done)
        w.start()
        self._workers.append(w)

    def _do_export_ca(self):
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export mkcert CA Certificate",
            "pgops-ca.pem",
            "Certificate Files (*.pem *.crt);;All Files (*)"
        )
        if not dest:
            return
        from core.mkcert_manager import export_ca_cert
        ok, msg = export_ca_cert(dest)
        self._on_log(f"[mkcert] {msg}")
        if ok:
            QMessageBox.information(
                self, "CA Exported",
                f"CA certificate saved to:\n{dest}\n\n"
                "Install this file on every LAN device that needs to access pgops.test.\n"
                "See the trust instructions in the panel above."
            )
        else:
            QMessageBox.warning(self, "Export Failed", msg)

    # ── PostgreSQL SSL handlers ────────────────────────────────────────────────

    def _enable_ssl(self):
        """
        Enable PostgreSQL TLS using the mkcert cert.
        Falls back to the legacy self-signed cert if mkcert cert isn't ready.
        """
        from core.mkcert_manager import is_cert_generated, get_cert_path, get_key_path
        from core.ssl_manager import enable_ssl, is_ssl_configured

        if is_cert_generated():
            # Use mkcert cert — copy it into ssl/ so enable_ssl() finds it
            import shutil
            from core.ssl_manager import get_ssl_dir
            ssl_dir = get_ssl_dir(BASE_DIR)
            shutil.copy2(get_cert_path(), ssl_dir / "server.crt")
            shutil.copy2(get_key_path(),  ssl_dir / "server.key")
            if platform.system() != "Windows":
                import os
                os.chmod(ssl_dir / "server.key", 0o600)

        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(
                self, "No Certificate",
                "No certificate found.\n\n"
                "Go to the mkcert section above and click:\n"
                "  1. Setup mkcert\n"
                "  2. Install CA (Trust)\n"
                "  3. Regenerate Cert\n\n"
                "Then try Enable SSL again."
            )
            return

        if not self._manager.is_initialized():
            QMessageBox.warning(
                self, "Not Initialized",
                "Start the PostgreSQL server at least once first."
            )
            return

        ok, msg = enable_ssl(BASE_DIR, DATA_DIR)
        self._on_log(msg)
        self._update_pg_ssl_status()
        if ok:
            QMessageBox.information(
                self, "SSL Enabled",
                "PostgreSQL SSL enabled.\n"
                "Restart the database server to apply.\n\n"
                "Connect with:  sslmode=require"
            )
        else:
            QMessageBox.critical(self, "Error", msg)

    def _disable_ssl(self):
        from core.ssl_manager import disable_ssl
        ok, msg = disable_ssl(DATA_DIR)
        self._on_log(msg)
        self._update_pg_ssl_status()
