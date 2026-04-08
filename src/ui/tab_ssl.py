from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QMessageBox, QFileDialog, QApplication,
)
from PyQt6.QtCore import Qt, QTimer

from core.pg_manager import BASE_DIR, DATA_DIR
from core.ssl_manager import (
    generate_certificate, enable_ssl, disable_ssl,
    get_ssl_status, get_cert_info, is_ssl_configured, export_ca_cert,
)
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


def _copy_row(label, value):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(label)
    lbl.setFixedWidth(80)
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
    return w


class SslTab(QWidget):
    """
    Standalone SSL/TLS page.
    on_log(msg) passed in.
    All SSL operations are self-contained (no callbacks needed).
    manager passed in to check is_initialized().
    """

    def __init__(self, config, manager, on_log, parent=None):
        super().__init__(parent)
        self.config   = config
        self._manager = manager
        self._on_log  = on_log
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
        sub = QLabel("Encrypt database connections on the LAN with a self-signed certificate.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        # ── Status card ────────────────────────────────────────────────────────
        st_card = self._card("SSL / TLS Status")
        sc = st_card.layout()

        self.ssl_status_lbl = QLabel("Checking...")
        self.ssl_status_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:15px;font-weight:700;background:transparent;"
        )
        sc.addWidget(self.ssl_status_lbl)

        self.ssl_cert_lbl = _lbl("", C_TEXT3, 11)
        self.ssl_cert_lbl.setWordWrap(True)
        sc.addWidget(self.ssl_cert_lbl)

        ssl_btns = QHBoxLayout()
        self.btn_ssl_on  = _btn("Enable SSL",  "#166534", "#15803d", "#86efac", h=36)
        self.btn_ssl_off = _btn("Disable SSL", "#7f1d1d", "#991b1b", "#fca5a5", h=36)
        self.btn_ssl_on.clicked.connect(self._enable_ssl)
        self.btn_ssl_off.clicked.connect(self._disable_ssl)
        ssl_btns.addWidget(self.btn_ssl_on)
        ssl_btns.addWidget(self.btn_ssl_off)
        ssl_btns.addStretch()
        sc.addLayout(ssl_btns)
        v.addWidget(st_card)

        # ── Certificate card ───────────────────────────────────────────────────
        cert_card = self._card("Certificate")
        cc = cert_card.layout()
        cc.addWidget(_lbl(
            "PGOps generates a self-signed RSA certificate valid for 10 years.  "
            "Share server.crt with clients that need certificate verification.", C_TEXT3, 11
        ))
        gen_row = QHBoxLayout()
        self.btn_gen_cert  = _btn("Generate New Certificate", C_BLUE, "#3b7de8", h=36)
        self.btn_exp_cert  = _btn("Export server.crt", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        self.btn_gen_cert.clicked.connect(self._gen_cert)
        self.btn_exp_cert.clicked.connect(self._exp_cert)
        gen_row.addWidget(self.btn_gen_cert)
        gen_row.addWidget(self.btn_exp_cert)
        gen_row.addStretch()
        cc.addLayout(gen_row)
        v.addWidget(cert_card)

        # ── Connection strings card ────────────────────────────────────────────
        conn_card = self._card("Connecting with SSL")
        cnc = conn_card.layout()
        port = self.config["port"]
        cnc.addWidget(_lbl("Use these once SSL is enabled:"))
        cnc.addWidget(_copy_row(
            "URL",
            f"postgresql://user:pass@pgops.local:{port}/dbname?sslmode=require"
        ))
        cnc.addWidget(_copy_row("Laravel",  "DB_SSLMODE=require  (add to .env)"))
        cnc.addWidget(_copy_row("psycopg2", "sslmode='require'  (add to connect())"))
        cnc.addWidget(_lbl(
            "sslmode=require encrypts the connection without verifying the cert.  "
            "sslmode=verify-ca also verifies the cert (distribute server.crt to clients).",
            C_TEXT3, 11
        ))
        v.addWidget(conn_card)
        v.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        QTimer.singleShot(200, self._update_status)

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

    def _update_status(self):
        try:
            status    = get_ssl_status(DATA_DIR)
            cert_info = get_cert_info(BASE_DIR)
        except Exception:
            return
        if status["enabled"]:
            self.ssl_status_lbl.setText("SSL ENABLED")
            self.ssl_status_lbl.setStyleSheet(
                f"color:{C_GREEN};font-size:15px;font-weight:700;background:transparent;"
            )
        else:
            self.ssl_status_lbl.setText("SSL DISABLED")
            self.ssl_status_lbl.setStyleSheet(
                f"color:{C_RED};font-size:15px;font-weight:700;background:transparent;"
            )
        if cert_info and "expires" in cert_info:
            self.ssl_cert_lbl.setText(
                f"Subject: {cert_info.get('subject','')}  |  "
                f"Expires: {cert_info.get('expires','')}  |  "
                f"Serial: {cert_info.get('serial','')}"
            )
        elif not is_ssl_configured(BASE_DIR):
            self.ssl_cert_lbl.setText("No certificate found — generate one first.")

    def _gen_cert(self):
        self.btn_gen_cert.setEnabled(False)
        from PyQt6.QtCore import QThread, pyqtSignal as pS

        class W(QThread):
            done = pS(bool, str)
            def run(self): self.done.emit(*generate_certificate(BASE_DIR))

        w = W(self)
        def on_done(ok, msg):
            self.btn_gen_cert.setEnabled(True)
            self._on_log(msg)
            self._update_status()
            if not ok:
                QMessageBox.critical(self, "Error", msg)
        w.done.connect(on_done)
        w.start()
        self._w = w

    def _enable_ssl(self):
        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(self, "No Certificate", "Generate a certificate first."); return
        if not self._manager.is_initialized():
            QMessageBox.warning(self, "Not Initialized", "Start the server at least once first."); return
        ok, msg = enable_ssl(BASE_DIR, DATA_DIR)
        self._on_log(msg)
        self._update_status()
        if ok:
            QMessageBox.information(self, "SSL Enabled", "SSL enabled. Restart the server to apply.")
        else:
            QMessageBox.critical(self, "Error", msg)

    def _disable_ssl(self):
        ok, msg = disable_ssl(DATA_DIR)
        self._on_log(msg)
        self._update_status()

    def _exp_cert(self):
        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(self, "No Certificate", "Generate a certificate first."); return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Certificate", "pgops-server.crt",
            "Certificate Files (*.crt);;All Files (*)"
        )
        if dest:
            ok, msg = export_ca_cert(BASE_DIR, dest)
            self._on_log(msg)
            if ok:
                QMessageBox.information(self, "Exported", msg)

    def refresh_status(self):
        self._update_status()
