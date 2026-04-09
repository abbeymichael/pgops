"""
tab_ssl.py
Unified SSL / TLS page.

Covers two distinct SSL concerns:
  1. PostgreSQL SSL    — encrypts DB connections (existing ssl_manager)
  2. Caddy CA Trust   — makes browser trust Caddy's internal HTTPS certs
                        so *.pgops.test gets a green padlock in browsers

The page makes both crystal clear and actionable.
"""

import platform
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QMessageBox, QFileDialog, QApplication,
    QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal

from core.pg_manager import BASE_DIR, DATA_DIR
from ui.theme import (
    C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
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
    """A label + read-only monospace field + copy button row."""
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


class _WorkerThread(QThread):
    done = pyqtSignal(bool, str)
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
    def run(self):
        try:
            ok, msg = self.fn()
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class SslTab(QWidget):
    """
    Unified SSL page covering both Caddy HTTPS and PostgreSQL TLS.
    """

    def __init__(self, config, manager, on_log, caddy_manager=None, parent=None):
        super().__init__(parent)
        self.config        = config
        self._manager      = manager
        self._on_log       = on_log
        self._caddy        = caddy_manager
        self._workers      = []
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
            "Manage HTTPS for web apps (Caddy CA) and encrypted database connections (PostgreSQL TLS)."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        # Section 1: Caddy HTTPS (most important for browser trust)
        v.addWidget(self._caddy_section())

        # Section 2: PostgreSQL SSL
        v.addWidget(self._postgres_section())

        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        QTimer.singleShot(300, self.refresh_status)

    # ── Caddy CA section ──────────────────────────────────────────────────────

    def _caddy_section(self):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        hdr = QHBoxLayout()
        t = QLabel("HTTPS for pgops.test  —  Caddy Internal CA")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        self._caddy_ssl_badge = QLabel("CHECKING...")
        self._caddy_ssl_badge.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(self._caddy_ssl_badge)
        v.addLayout(hdr)
        v.addWidget(_sep())

        # How it works
        how = QLabel(
            "Caddy automatically issues SSL certificates for every domain it serves using its built-in CA. "
            "Once you trust the Caddy CA, all *.pgops.test subdomains get a green padlock — "
            "no more browser warnings."
        )
        how.setWordWrap(True)
        how.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(how)

        # Status info
        self._caddy_ca_path_lbl = _lbl("CA certificate: checking...", C_TEXT3, 11)
        v.addWidget(self._caddy_ca_path_lbl)

        # Action buttons
        btns = QHBoxLayout()
        self.btn_trust_auto = _btn("Trust CA (Auto-Install)", C_BLUE, "#3b7de8", h=36)
        self.btn_export_ca  = _btn("Export CA Certificate",  C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        self.btn_open_https = _btn("Open https://pgops.test →", "#166534", "#15803d", "#86efac", h=36)

        self.btn_trust_auto.clicked.connect(self._trust_caddy_ca_auto)
        self.btn_export_ca.clicked.connect(self._export_caddy_ca)
        self.btn_open_https.clicked.connect(lambda: webbrowser.open("https://pgops.test"))

        btns.addWidget(self.btn_trust_auto)
        btns.addWidget(self.btn_export_ca)
        btns.addWidget(self.btn_open_https)
        btns.addStretch()
        v.addLayout(btns)

        # Manual trust instructions
        manual_card = QWidget()
        manual_card.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER2};border-radius:8px;"
        )
        mv = QVBoxLayout(manual_card)
        mv.setContentsMargins(14, 12, 14, 12)
        mv.setSpacing(8)

        ml = QLabel("Manual Trust Instructions (if auto-install fails)")
        ml.setStyleSheet(
            f"color:{C_TEXT};font-size:12px;font-weight:700;background:transparent;"
        )
        mv.addWidget(ml)

        steps = QTabWidget()
        steps.setStyleSheet(
            f"QTabWidget::pane{{background:{C_BG if False else C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:4px;margin-top:-1px;}}"
            f"QTabBar::tab{{background:{C_SURFACE};color:{C_TEXT3};"
            f"padding:4px 12px;border:1px solid {C_BORDER};"
            f"border-bottom:none;border-radius:3px 3px 0 0;font-size:11px;}}"
            f"QTabBar::tab:selected{{background:{C_SURFACE2};color:{C_TEXT};}}"
        )

        trust_steps = {
            "Windows": (
                "1. Click 'Export CA Certificate' → save as pgops-ca.crt\n"
                "2. Double-click pgops-ca.crt\n"
                "3. Click 'Install Certificate'\n"
                "4. Store location: Local Machine → Next\n"
                "5. 'Place all certificates in the following store'\n"
                "6. Browse → 'Trusted Root Certification Authorities'\n"
                "7. Finish → Yes → OK\n"
                "8. Restart your browser"
            ),
            "macOS": (
                "1. Click 'Export CA Certificate' → save as pgops-ca.crt\n"
                "2. Double-click pgops-ca.crt → opens Keychain Access\n"
                "3. In Keychain Access, find 'PGOps Local CA'\n"
                "4. Double-click it → expand 'Trust'\n"
                "5. 'When using this certificate' → 'Always Trust'\n"
                "6. Close → enter your password\n"
                "7. Restart your browser"
            ),
            "Firefox": (
                "Firefox uses its own cert store:\n"
                "1. Click 'Export CA Certificate' → save as pgops-ca.crt\n"
                "2. Firefox → Settings → Privacy & Security\n"
                "3. Scroll to Certificates → View Certificates\n"
                "4. Authorities tab → Import → select pgops-ca.crt\n"
                "5. Check 'Trust this CA to identify websites'\n"
                "6. OK → restart Firefox"
            ),
            "Linux": (
                "Ubuntu/Debian:\n"
                "  sudo cp pgops-ca.crt /usr/local/share/ca-certificates/\n"
                "  sudo update-ca-certificates\n\n"
                "Fedora/RHEL:\n"
                "  sudo cp pgops-ca.crt /etc/pki/ca-trust/source/anchors/\n"
                "  sudo update-ca-trust\n\n"
                "Then restart your browser."
            ),
        }
        for name, instructions in trust_steps.items():
            te = QLineEdit()
            from PyQt6.QtWidgets import QTextEdit
            te = QTextEdit(instructions)
            te.setReadOnly(True)
            te.setFixedHeight(110)
            te.setStyleSheet(
                f"background:{C_SURFACE};color:{C_TEXT2};"
                f"font-family:'Consolas','Courier New',monospace;"
                f"font-size:11px;border:none;padding:8px;"
            )
            steps.addTab(te, name)
        mv.addWidget(steps)
        v.addWidget(manual_card)

        return card

    # ── PostgreSQL SSL section ─────────────────────────────────────────────────

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
            "Encrypts connections between apps and the PostgreSQL server. "
            "Uses a self-signed RSA certificate valid for 10 years. "
            "Apps connect with sslmode=require.",
            C_TEXT3, 12
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self.ssl_cert_lbl = _lbl("", C_TEXT3, 11)
        self.ssl_cert_lbl.setWordWrap(True)
        v.addWidget(self.ssl_cert_lbl)

        # Cert actions
        cert_btns = QHBoxLayout()
        self.btn_gen_cert  = _btn("Generate Certificate", C_BLUE, "#3b7de8", h=34)
        self.btn_ssl_on    = _btn("Enable SSL", "#166534", "#15803d", "#86efac", h=34)
        self.btn_ssl_off   = _btn("Disable SSL", "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_exp_cert  = _btn("Export server.crt", C_SURFACE2, C_BORDER2, C_TEXT2, h=34)

        self.btn_gen_cert.clicked.connect(self._gen_cert)
        self.btn_ssl_on.clicked.connect(self._enable_ssl)
        self.btn_ssl_off.clicked.connect(self._disable_ssl)
        self.btn_exp_cert.clicked.connect(self._exp_cert)

        cert_btns.addWidget(self.btn_gen_cert)
        cert_btns.addWidget(self.btn_ssl_on)
        cert_btns.addWidget(self.btn_ssl_off)
        cert_btns.addWidget(self.btn_exp_cert)
        cert_btns.addStretch()
        v.addLayout(cert_btns)

        # Connection string examples
        port = self.config["port"]
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

    # ── Status refresh ────────────────────────────────────────────────────────

    def refresh_status(self):
        self._update_caddy_status()
        self._update_pg_ssl_status()

    def _update_caddy_status(self):
        if not self._caddy:
            self._caddy_ssl_badge.setText("Caddy not configured")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_TEXT3};font-size:11px;background:transparent;"
            )
            self._caddy_ca_path_lbl.setText("Caddy manager not available.")
            return

        status = self._caddy.get_status_detail()
        caddy_running = status.get("running", False)
        ca_available  = status.get("ca_available", False)
        ca_path       = status.get("ca_path", "")

        if caddy_running and ca_available:
            self._caddy_ssl_badge.setText("● HTTPS ACTIVE")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_GREEN};font-size:11px;font-weight:700;background:transparent;"
            )
        elif caddy_running:
            self._caddy_ssl_badge.setText("● CADDY RUNNING (certs generating...)")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_AMBER};font-size:11px;font-weight:700;background:transparent;"
            )
        else:
            self._caddy_ssl_badge.setText("● CADDY STOPPED")
            self._caddy_ssl_badge.setStyleSheet(
                f"color:{C_RED};font-size:11px;font-weight:700;background:transparent;"
            )

        if ca_available and ca_path:
            self._caddy_ca_path_lbl.setText(
                f"CA certificate: {ca_path}\n"
                "Click 'Trust CA (Auto-Install)' to add it to your system trust store, "
                "or export it for manual installation."
            )
            self.btn_export_ca.setEnabled(True)
            self.btn_trust_auto.setEnabled(True)
        else:
            self._caddy_ca_path_lbl.setText(
                "CA not yet generated. Start Caddy first — it creates the CA automatically on first run."
            )
            self.btn_export_ca.setEnabled(False)
            self.btn_trust_auto.setEnabled(False)

    def _update_pg_ssl_status(self):
        try:
            from core.ssl_manager import get_ssl_status, get_cert_info, is_ssl_configured
            status    = get_ssl_status(DATA_DIR)
            cert_info = get_cert_info(BASE_DIR)
        except Exception:
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
        elif not is_ssl_configured(BASE_DIR):
            self.ssl_cert_lbl.setText("No certificate found — generate one first.")

    # ── Caddy CA handlers ─────────────────────────────────────────────────────

    def _trust_caddy_ca_auto(self):
        if not self._caddy:
            QMessageBox.warning(self, "Caddy Not Available", "Caddy manager not configured.")
            return
        self.btn_trust_auto.setEnabled(False)
        self.btn_trust_auto.setText("Trusting...")

        def fn():
            return self._caddy.install_ca()

        w = _WorkerThread(fn)
        def done(ok, msg):
            self.btn_trust_auto.setEnabled(True)
            self.btn_trust_auto.setText("Trust CA (Auto-Install)")
            self._on_log(f"[SSL] {msg}")
            if ok:
                QMessageBox.information(
                    self, "CA Trusted",
                    f"{msg}\n\n"
                    "Restart your browser for the change to take effect.\n"
                    "All *.pgops.test sites will show a green padlock."
                )
            else:
                QMessageBox.warning(
                    self, "Auto-Trust Failed",
                    f"{msg}\n\n"
                    "Try the manual instructions in the 'Manual Trust Instructions' section."
                )
            self._update_caddy_status()
        w.done.connect(done)
        w.start()
        self._workers.append(w)

    def _export_caddy_ca(self):
        if not self._caddy:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Caddy CA Certificate", "pgops-caddy-ca.crt",
            "Certificate Files (*.crt *.pem);;All Files (*)"
        )
        if dest:
            ok, msg = self._caddy.export_ca(dest)
            self._on_log(f"[SSL] {msg}")
            if ok:
                QMessageBox.information(
                    self, "CA Exported",
                    f"CA certificate saved to:\n{dest}\n\n"
                    "Follow the manual trust instructions to install it in your browser or OS."
                )
            else:
                QMessageBox.warning(self, "Export Failed", msg)

    # ── PostgreSQL SSL handlers ───────────────────────────────────────────────

    def _gen_cert(self):
        self.btn_gen_cert.setEnabled(False)
        from core.ssl_manager import generate_certificate

        w = _WorkerThread(lambda: generate_certificate(BASE_DIR))
        def done(ok, msg):
            self.btn_gen_cert.setEnabled(True)
            self._on_log(msg)
            self._update_pg_ssl_status()
            if not ok:
                QMessageBox.critical(self, "Error", msg)
        w.done.connect(done)
        w.start()
        self._workers.append(w)

    def _enable_ssl(self):
        from core.ssl_manager import is_ssl_configured, enable_ssl
        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(self, "No Certificate", "Generate a certificate first.")
            return
        if not self._manager.is_initialized():
            QMessageBox.warning(self, "Not Initialized", "Start the server at least once first.")
            return
        ok, msg = enable_ssl(BASE_DIR, DATA_DIR)
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

    def _exp_cert(self):
        from core.ssl_manager import is_ssl_configured, export_ca_cert
        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(self, "No Certificate", "Generate a certificate first.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export PostgreSQL Certificate", "pgops-server.crt",
            "Certificate Files (*.crt);;All Files (*)"
        )
        if dest:
            ok, msg = export_ca_cert(BASE_DIR, dest)
            self._on_log(msg)
            if ok:
                QMessageBox.information(self, "Exported", msg)
