"""
tab_ssl.py  (v2 — mkcert edition)

Replaces the previous self-signed cert workflow with mkcert.
mkcert installs a local CA into the system trust store so browsers,
curl, psql, etc. all trust generated certs automatically.

Sections:
  1. mkcert Setup   — download, install CA, generate cert
  2. PostgreSQL TLS — enable/disable SSL in postgresql.conf using mkcert cert
  3. Caddy HTTPS    — status only (Caddy uses the same mkcert cert)
"""

import webbrowser
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QMessageBox, QFileDialog,
    QApplication, QProgressBar, QTabWidget, QTextEdit,
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


def _mono_row(label_text: str, value: str):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(label_text)
    lbl.setFixedWidth(90)
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
                self.done.emit(bool(result[0]), str(result[1]) if len(result) > 1 else "")
            else:
                self.done.emit(bool(result), "")
        except Exception as e:
            self.done.emit(False, str(e))


class SslTab(QWidget):
    def __init__(self, config, manager, on_log, caddy_manager=None, parent=None):
        super().__init__(parent)
        self.config   = config
        self._manager = manager
        self._on_log  = on_log
        self._caddy   = caddy_manager
        self._workers: list = []
        self._build()

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
            "mkcert creates a trusted local certificate authority. "
            "Once installed, browsers and apps trust PGOps certificates automatically — no warnings."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        v.addWidget(self._mkcert_section())
        v.addWidget(self._postgres_section())
        v.addWidget(self._caddy_section())

        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        QTimer.singleShot(300, self.refresh_status)

    # ── mkcert section ─────────────────────────────────────────────────────────

    def _mkcert_section(self):
        card = self._card("Certificate Authority  —  mkcert")
        cv = card.layout()

        desc = QLabel(
            "mkcert installs a local CA into your system trust stores (Windows, macOS, "
            "Firefox, Chrome). Any cert it generates is trusted everywhere on this machine. "
            "Clients on other devices can import the CA certificate once to get full trust."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        cv.addWidget(desc)

        # Status row
        status_row = QHBoxLayout()
        self._mkcert_binary_lbl = _lbl("Binary: checking...", C_TEXT3, 11)
        self._mkcert_ca_lbl     = _lbl("CA: checking...", C_TEXT3, 11)
        self._mkcert_cert_lbl   = _lbl("Certificate: checking...", C_TEXT3, 11)
        status_row.addWidget(self._mkcert_binary_lbl)
        status_row.addSpacing(20)
        status_row.addWidget(self._mkcert_ca_lbl)
        status_row.addSpacing(20)
        status_row.addWidget(self._mkcert_cert_lbl)
        status_row.addStretch()
        cv.addLayout(status_row)

        # Progress bar (shown during setup)
        self._mkcert_prog = QProgressBar()
        self._mkcert_prog.setVisible(False)
        self._mkcert_prog.setFixedHeight(3)
        self._mkcert_prog.setTextVisible(False)
        self._mkcert_prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_GREEN};}}"
        )
        cv.addWidget(self._mkcert_prog)

        # Action buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)

        self.btn_mkcert_setup  = _btn("Full Setup (Download + Trust CA + Generate Cert)",
                                      C_BLUE, "#3b7de8", h=36)
        self.btn_mkcert_regen  = _btn("Regenerate Cert", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        self.btn_export_ca     = _btn("Export CA for Clients", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)

        self.btn_mkcert_setup.clicked.connect(self._full_setup)
        self.btn_mkcert_regen.clicked.connect(self._regen_cert)
        self.btn_export_ca.clicked.connect(self._export_ca)

        btns.addWidget(self.btn_mkcert_setup)
        btns.addWidget(self.btn_mkcert_regen)
        btns.addWidget(self.btn_export_ca)
        btns.addStretch()
        cv.addLayout(btns)

        # Cert details
        self._cert_details_lbl = _lbl("", C_TEXT3, 11)
        self._cert_details_lbl.setWordWrap(True)
        cv.addWidget(self._cert_details_lbl)

        # Client device trust instructions
        client_card = QWidget()
        client_card.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER2};border-radius:8px;"
        )
        clv = QVBoxLayout(client_card)
        clv.setContentsMargins(14, 12, 14, 12)
        clv.setSpacing(8)

        cl_title = QLabel("Trust on Other Devices (import exported CA once per device)")
        cl_title.setStyleSheet(
            f"color:{C_TEXT};font-size:12px;font-weight:700;background:transparent;"
        )
        clv.addWidget(cl_title)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:4px;}}"
            f"QTabBar::tab{{background:{C_SURFACE};color:{C_TEXT3};"
            f"padding:4px 12px;border:1px solid {C_BORDER};"
            f"border-bottom:none;border-radius:3px 3px 0 0;font-size:11px;}}"
            f"QTabBar::tab:selected{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )
        steps = {
            "Windows": (
                "1. Click 'Export CA for Clients' → save as pgops-ca.crt\n"
                "2. Double-click pgops-ca.crt\n"
                "3. Click 'Install Certificate' → Local Machine → Next\n"
                "4. 'Place all certificates in the following store'\n"
                "5. Browse → 'Trusted Root Certification Authorities' → Finish\n"
                "6. Click Yes on the security prompt\n"
                "7. Restart your browser"
            ),
            "macOS": (
                "1. Click 'Export CA for Clients' → save as pgops-ca.crt\n"
                "2. Double-click pgops-ca.crt → Keychain Access opens\n"
                "3. Find 'mkcert ...' in the list, double-click it\n"
                "4. Expand 'Trust' → 'When using this certificate' → 'Always Trust'\n"
                "5. Close → enter your password to confirm\n"
                "6. Restart your browser"
            ),
            "Android": (
                "1. Export CA and copy pgops-ca.crt to the device (email or USB)\n"
                "2. Settings → Security → Install from storage (or 'Install a certificate')\n"
                "3. Select pgops-ca.crt → name it 'PGOps CA'\n"
                "4. The certificate is now trusted for Wi-Fi and apps\n"
                "(Chrome on Android uses the system store — no extra step needed)"
            ),
            "iOS": (
                "1. Export CA and AirDrop or email pgops-ca.crt to your iPhone/iPad\n"
                "2. Tap the file → 'Allow' → Settings shows 'Profile Downloaded'\n"
                "3. Settings → General → VPN & Device Management → Install\n"
                "4. Settings → General → About → Certificate Trust Settings\n"
                "5. Enable full trust for the mkcert root CA\n"
                "6. Safari and other apps now trust PGOps certificates"
            ),
            "Linux": (
                "Ubuntu/Debian:\n"
                "  sudo cp pgops-ca.crt /usr/local/share/ca-certificates/pgops-ca.crt\n"
                "  sudo update-ca-certificates\n\n"
                "Fedora/RHEL:\n"
                "  sudo cp pgops-ca.crt /etc/pki/ca-trust/source/anchors/\n"
                "  sudo update-ca-trust extract\n\n"
                "Then restart your browser."
            ),
        }
        for name, instructions in steps.items():
            te = QTextEdit(instructions)
            te.setReadOnly(True)
            te.setFixedHeight(110)
            te.setStyleSheet(
                f"background:{C_SURFACE};color:{C_TEXT2};"
                f"font-family:'Consolas','Courier New',monospace;"
                f"font-size:11px;border:none;padding:8px;"
            )
            tabs.addTab(te, name)
        clv.addWidget(tabs)
        cv.addWidget(client_card)
        return card

    # ── PostgreSQL TLS section ─────────────────────────────────────────────────

    def _postgres_section(self):
        card = self._card("PostgreSQL TLS  —  Encrypted Database Connections")
        cv = card.layout()

        desc = _lbl(
            "Enables TLS on PostgreSQL using the mkcert certificate. "
            "Apps connect with sslmode=require. "
            "The mkcert cert must be generated first.",
            C_TEXT3, 12,
        )
        desc.setWordWrap(True)
        cv.addWidget(desc)

        # Status
        status_row = QHBoxLayout()
        self.ssl_status_lbl = QLabel("Checking...")
        self.ssl_status_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:13px;font-weight:700;background:transparent;"
        )
        status_row.addWidget(self.ssl_status_lbl)
        status_row.addStretch()
        cv.addLayout(status_row)

        self.ssl_cert_lbl = _lbl("", C_TEXT3, 11)
        self.ssl_cert_lbl.setWordWrap(True)
        cv.addWidget(self.ssl_cert_lbl)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_ssl_on  = _btn("Enable SSL",  "#166534", "#15803d", "#86efac", h=34)
        self.btn_ssl_off = _btn("Disable SSL", "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_ssl_on.clicked.connect(self._enable_ssl)
        self.btn_ssl_off.clicked.connect(self._disable_ssl)
        btns.addWidget(self.btn_ssl_on)
        btns.addWidget(self.btn_ssl_off)
        btns.addStretch()
        cv.addLayout(btns)

        # Connection string examples
        port = self.config.get("port", 5432)
        conn_card = QWidget()
        conn_card.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER2};border-radius:8px;"
        )
        cv2 = QVBoxLayout(conn_card)
        cv2.setContentsMargins(14, 12, 14, 12)
        cv2.setSpacing(8)
        cv2.addWidget(_lbl("CLIENT CONNECTION STRINGS", C_TEXT3, 10))
        cv2.addWidget(_mono_row(
            "URL",
            f"postgresql://user:pass@pgops.local:{port}/dbname?sslmode=require"
        ))
        cv2.addWidget(_mono_row("Laravel", "DB_SSLMODE=require  (in .env)"))
        cv2.addWidget(_mono_row("psycopg2", "sslmode='require'  (in connect())"))
        cv.addWidget(conn_card)

        cv.addWidget(_lbl(
            "Restart PostgreSQL after enabling or disabling SSL.",
            C_TEXT3, 11,
        ))
        return card

    # ── Caddy status section ───────────────────────────────────────────────────

    def _caddy_section(self):
        card = self._card("HTTPS for Web Apps  —  Caddy + mkcert")
        cv = card.layout()

        desc = QLabel(
            "Caddy uses the same mkcert certificate to serve all *.pgops.local domains over HTTPS. "
            "No additional configuration is required — once mkcert setup is complete and "
            "Caddy is running, all apps are available over HTTPS."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        cv.addWidget(desc)

        status_row = QHBoxLayout()
        self._caddy_ssl_badge = QLabel("Checking...")
        self._caddy_ssl_badge.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;background:transparent;"
        )
        status_row.addWidget(self._caddy_ssl_badge)
        status_row.addStretch()
        cv.addLayout(status_row)

        self._caddy_url_lbl = _lbl("", C_BLUE, 12)
        cv.addWidget(self._caddy_url_lbl)

        btns = QHBoxLayout()
        self.btn_open_https = _btn(
            "Open https://pgops.local →", "#166534", "#15803d", "#86efac", h=34
        )
        self.btn_open_https.clicked.connect(
            lambda: webbrowser.open("https://pgops.local")
        )
        btns.addWidget(self.btn_open_https)
        btns.addStretch()
        cv.addLayout(btns)
        return card

    # ── Card helper ────────────────────────────────────────────────────────────

    def _card(self, title: str) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)
        t = QLabel(title)
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        v.addWidget(t)
        v.addWidget(_sep())
        return card

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh_status(self):
        self._update_mkcert_status()
        self._update_pg_ssl_status()
        self._update_caddy_status()

    def _update_mkcert_status(self):
        try:
            from core.mkcert_manager import is_available, is_ca_installed
            from core.ssl_manager import cert_path, key_path, get_cert_info
            binary_ok = is_available()
            ca_ok     = is_ca_installed() if binary_ok else False
            cert_ok   = cert_path().exists() and key_path().exists()

            self._mkcert_binary_lbl.setText(
                f"Binary: {'✓ installed' if binary_ok else '✗ missing'}"
            )
            self._mkcert_binary_lbl.setStyleSheet(
                f"color:{C_GREEN if binary_ok else C_RED};"
                f"font-size:11px;background:transparent;"
            )

            self._mkcert_ca_lbl.setText(
                f"CA: {'✓ trusted' if ca_ok else '✗ not installed'}"
            )
            self._mkcert_ca_lbl.setStyleSheet(
                f"color:{C_GREEN if ca_ok else C_AMBER};"
                f"font-size:11px;background:transparent;"
            )

            self._mkcert_cert_lbl.setText(
                f"Cert: {'✓ generated' if cert_ok else '✗ missing'}"
            )
            self._mkcert_cert_lbl.setStyleSheet(
                f"color:{C_GREEN if cert_ok else C_RED};"
                f"font-size:11px;background:transparent;"
            )

            if cert_ok:
                info = get_cert_info()
                if info and "expires" in info:
                    sans_preview = ", ".join(info.get("sans", [])[:4])
                    if len(info.get("sans", [])) > 4:
                        sans_preview += f" +{len(info['sans']) - 4} more"
                    self._cert_details_lbl.setText(
                        f"Expires: {info['expires']}  ·  SANs: {sans_preview}"
                    )
                else:
                    self._cert_details_lbl.setText("")
            else:
                self._cert_details_lbl.setText("")

            all_ok = binary_ok and ca_ok and cert_ok
            self.btn_mkcert_setup.setVisible(not all_ok)
            self.btn_mkcert_regen.setEnabled(binary_ok)
            self.btn_export_ca.setEnabled(ca_ok)

        except Exception as e:
            self._mkcert_binary_lbl.setText(f"Status error: {e}")

    def _update_pg_ssl_status(self):
        try:
            from core.ssl_manager import get_ssl_status, cert_path, key_path
            status = get_ssl_status(DATA_DIR)

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

            cert_ok = cert_path().exists() and key_path().exists()
            if not cert_ok:
                self.ssl_cert_lbl.setText(
                    "mkcert certificate not found — run Full Setup first."
                )
            else:
                self.ssl_cert_lbl.setText(
                    f"Using: {cert_path()}"
                )
        except Exception as e:
            self.ssl_cert_lbl.setText(f"Error: {e}")

    def _update_caddy_status(self):
        if not self._caddy:
            self._caddy_ssl_badge.setText("Caddy not configured")
            return

        running  = self._caddy.is_running()
        try:
            from core.ssl_manager import cert_path, key_path
            cert_ok = cert_path().exists() and key_path().exists()
        except Exception:
            cert_ok = False

        if running and cert_ok:
            self._caddy_ssl_badge.setText("● RUNNING WITH TRUSTED CERT")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_GREEN};font-size:12px;font-weight:700;background:transparent;"
            )
            if self._caddy:
                url = self._caddy.console_url()
                self._caddy_url_lbl.setText(f"https://pgops.local  →  {url}")
        elif running:
            self._caddy_ssl_badge.setText("● RUNNING (no mkcert cert — using Caddy internal CA)")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_AMBER};font-size:12px;font-weight:700;background:transparent;"
            )
        else:
            self._caddy_ssl_badge.setText("● CADDY STOPPED")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_RED};font-size:12px;font-weight:700;background:transparent;"
            )
            self._caddy_url_lbl.setText("")

    # ── mkcert action handlers ─────────────────────────────────────────────────

    def _full_setup(self):
        self.btn_mkcert_setup.setEnabled(False)
        self._mkcert_prog.setVisible(True)
        self._mkcert_prog.setValue(0)

        def fn(prog_cb):
            from core.mkcert_manager import setup_mkcert
            ok, msg = setup_mkcert(progress_callback=prog_cb, log_fn=self._on_log)
            if ok:
                # Populate certs/pgops.crt and certs/pgops.key
                from core.ssl_manager import generate_certificate
                ok2, msg2 = generate_certificate(log_fn=self._on_log)
                if not ok2:
                    return False, f"CA installed but cert generation failed: {msg2}"
                return True, msg + "\n" + msg2
            return ok, msg

        def done(ok, msg):
            self._mkcert_prog.setVisible(False)
            self.btn_mkcert_setup.setEnabled(True)
            self._on_log(f"[mkcert] {msg}")
            self.refresh_status()
            if ok:
                QMessageBox.information(
                    self, "mkcert Setup Complete",
                    f"{msg}\n\n"
                    "Your browser will now trust pgops.local and all app subdomains "
                    "without any certificate warnings.\n\n"
                    "For other devices, click 'Export CA for Clients' and follow "
                    "the import instructions in the tab below."
                )
            else:
                QMessageBox.critical(self, "Setup Failed", msg)

        w = _Worker(fn)
        w.done.connect(done)
        w.progress.connect(self._mkcert_prog.setValue)
        w.start()
        self._workers.append(w)

    def _regen_cert(self):
        self.btn_mkcert_regen.setEnabled(False)

        def fn(_prog):
            from core.ssl_manager import generate_certificate
            return generate_certificate(log_fn=self._on_log)

        def done(ok, msg):
            self.btn_mkcert_regen.setEnabled(True)
            self._on_log(f"[mkcert] {msg}")
            self.refresh_status()
            # If Caddy is running, reload it to pick up the new cert
            if ok and self._caddy and self._caddy.is_running():
                ok2, msg2 = self._caddy.reload()
                self._on_log(f"[Caddy] {msg2}")
            if not ok:
                QMessageBox.warning(self, "Regenerate Failed", msg)

        w = _Worker(fn)
        w.done.connect(done)
        w.start()
        self._workers.append(w)

    def _export_ca(self):
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export CA Certificate", "pgops-ca.crt",
            "Certificate Files (*.crt *.pem);;All Files (*)"
        )
        if dest:
            from core.ssl_manager import export_ca_cert
            ok, msg = export_ca_cert(dest, log_fn=self._on_log)
            self._on_log(f"[mkcert] {msg}")
            if ok:
                QMessageBox.information(
                    self, "CA Exported",
                    f"CA certificate saved to:\n{dest}\n\n"
                    "Import this on other devices using the instructions below."
                )
            else:
                QMessageBox.warning(self, "Export Failed", msg)

    # ── PostgreSQL SSL action handlers ─────────────────────────────────────────

    def _enable_ssl(self):
        from core.ssl_manager import cert_path, key_path, enable_ssl_with_paths
        if not cert_path().exists() or not key_path().exists():
            QMessageBox.warning(
                self, "No Certificate",
                "mkcert certificate not found in certs/pgops.crt.\n"
                "Run 'Full Setup' first."
            )
            return

        if not self._manager.is_initialized():
            QMessageBox.warning(
                self, "Not Initialized",
                "Start the server at least once before enabling SSL."
            )
            return

        ok, msg = enable_ssl_with_paths(DATA_DIR)
        self._on_log(msg)
        self._update_pg_ssl_status()
        if ok:
            QMessageBox.information(
                self, "SSL Enabled",
                "PostgreSQL SSL enabled.\nRestart the database server to apply."
            )
        else:
            QMessageBox.critical(self, "Error", msg)

    def _disable_ssl(self):
        from core.ssl_manager import disable_ssl
        ok, msg = disable_ssl(DATA_DIR)
        self._on_log(msg)
        self._update_pg_ssl_status()