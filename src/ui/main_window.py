import sys
import platform
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox, QCheckBox,
    QSpinBox, QTabWidget, QProgressBar, QMessageBox, QFileDialog,
    QSystemTrayIcon, QMenu, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QDialogButtonBox, QComboBox, QAbstractItemView,
    QTimeEdit, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QTime
from PyQt6.QtGui import QColor, QIcon, QPixmap, QAction

from core.pg_manager import PostgresManager, BASE_DIR, DATA_DIR, LOG_FILE, _bin
from core.config import load_config, save_config
from core.pg_manager import get_app_data_dir
from core.hotspot import start_hotspot, stop_hotspot, open_hotspot_settings, get_hotspot_status
from core.network_info import get_all_interfaces, get_best_ip, is_hotspot_active
from core.mdns import MDNSBroadcaster, verify_mdns_resolution, get_mdns_instructions
from core.scheduler import BackupScheduler
from core.service_manager import (
    service_exists, service_running, install_service,
    uninstall_service, start_service, stop_service, is_admin
)
import core.db_manager as dbm
from ui.table_browser import TableBrowser
from ui.login_dialog import ChangePasswordDialog as ChangePwDialog
from ui.files_tab import FilesTab
from core.minio_manager import MinIOManager
from core.pgadmin_manager import PgAdminManager
from ui.activity_monitor import ActivityMonitor
from core.ssl_manager import (
    generate_certificate, enable_ssl, disable_ssl,
    get_ssl_status, get_cert_info, is_ssl_configured,
    export_ca_cert, cert_path, key_path
)


# ─── Worker with progress signal ─────────────────────────────────────────────
class Worker(QThread):
    done     = pyqtSignal(bool, str)
    progress = pyqtSignal(int)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
            if isinstance(result, tuple):
                ok  = bool(result[0])
                msg = str(result[1]) if len(result) > 1 else ""
            elif result is None:
                ok, msg = True, ""
            else:
                ok, msg = bool(result), ""
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


# ─── UI helpers ───────────────────────────────────────────────────────────────
def _btn(text, bg="#1d4ed8", hover="#1e40af", fg="white", h=38):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 14px;font-size:13px;font-weight:600;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:#1e293b;color:#475569;}}"
    )
    return b

def _inp(val="", pw=False, placeholder=""):
    f = QLineEdit(val)
    if pw: f.setEchoMode(QLineEdit.EchoMode.Password)
    if placeholder: f.setPlaceholderText(placeholder)
    f.setStyleSheet(
        "background:#1e293b;border:1px solid #334155;border-radius:5px;"
        "padding:5px 10px;color:#e2e8f0;font-size:13px;"
    )
    return f

def _lbl(text, color="#94a3b8", size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;")
    return l

def _group(title):
    g = QGroupBox(title)
    QVBoxLayout(g).setSpacing(6)
    return g

def _page():
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(22, 18, 22, 18)
    v.setSpacing(14)
    return w, v

def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#1e293b;")
    return f


class CopyRow(QWidget):
    def __init__(self, label, value=""):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(8)
        lbl = _lbl(label)
        lbl.setFixedWidth(84)
        self.field = QLineEdit(value)
        self.field.setReadOnly(True)
        self.field.setStyleSheet(
            "background:#1e293b;border:1px solid #334155;border-radius:5px;"
            "padding:5px 10px;color:#e2e8f0;font-family:monospace;font-size:12px;"
        )
        btn = QPushButton("Copy")
        btn.setFixedSize(50, 26)
        btn.setStyleSheet(
            "QPushButton{background:#334155;color:#94a3b8;border:none;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#475569;color:#fff;}"
        )
        btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(self.field.text()),
            btn.setText("OK"),
            QTimer.singleShot(1200, lambda: btn.setText("Copy"))
        ))
        row.addWidget(lbl)
        row.addWidget(self.field)
        row.addWidget(btn)

    def set(self, v):
        self.field.setText(v)


class StatusBadge(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stopped()

    def _s(self, text, fg, bg):
        self.setText(f"  {text}  ")
        self.setStyleSheet(
            f"color:{fg};background:{bg};border:1px solid {fg}44;"
            f"border-radius:13px;font-size:12px;font-weight:bold;padding:0 8px;"
        )

    def running(self):   self._s("RUNNING",   "#22c55e", "#0a1c0f")
    def stopped(self):   self._s("STOPPED",   "#ef4444", "#1c0a0a")
    def starting(self):  self._s("STARTING",  "#f59e0b", "#1c1208")


class CreateDbDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Database")
        self.setFixedWidth(400)
        self.setStyleSheet("background:#0f172a;color:#e2e8f0;")
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        for lbl_text, attr, pw in [
            ("Database Name", "db_name", False),
            ("Owner Username", "owner", False),
            ("Owner Password", "password", True),
            ("Confirm Password", "confirm", True),
        ]:
            layout.addWidget(_lbl(lbl_text, "#94a3b8"))
            field = _inp(pw=pw)
            setattr(self, attr, field)
            layout.addWidget(field)
        self.error_lbl = _lbl("", "#ef4444")
        self.error_lbl.setVisible(False)
        layout.addWidget(self.error_lbl)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet("QPushButton{background:#1e293b;color:#e2e8f0;border:none;border-radius:5px;padding:6px 18px;}QPushButton:hover{background:#334155;}")
        layout.addWidget(btns)

    def _validate(self):
        name = self.db_name.text().strip()
        owner = self.owner.text().strip()
        pw = self.password.text()
        if not name or not owner or not pw:
            self._err("All fields required."); return
        if pw != self.confirm.text():
            self._err("Passwords do not match."); return
        if " " in name or " " in owner:
            self._err("No spaces allowed."); return
        self.accept()

    def _err(self, msg):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)

    def values(self):
        return self.db_name.text().strip(), self.owner.text().strip(), self.password.text()


class ChangePasswordDialog(QDialog):
    def __init__(self, role, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Change Password - {role}")
        self.setFixedWidth(360)
        self.setStyleSheet("background:#0f172a;color:#e2e8f0;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(_lbl(f"New password for: {role}", "#94a3b8"))
        self.pw = _inp(pw=True)
        self.cf = _inp(pw=True)
        self.err = _lbl("", "#ef4444")
        self.err.setVisible(False)
        layout.addWidget(self.pw)
        layout.addWidget(_lbl("Confirm", "#94a3b8"))
        layout.addWidget(self.cf)
        layout.addWidget(self.err)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet("QPushButton{background:#1e293b;color:#e2e8f0;border:none;border-radius:5px;padding:6px 18px;}QPushButton:hover{background:#334155;}")
        layout.addWidget(btns)

    def _validate(self):
        if not self.pw.text():
            self.err.setText("Empty."); self.err.setVisible(True); return
        if self.pw.text() != self.cf.text():
            self.err.setText("Mismatch."); self.err.setVisible(True); return
        self.accept()

    def value(self): return self.pw.text()


DARK_STYLE = """
QMainWindow,QWidget{background:#0f172a;color:#e2e8f0;}
QGroupBox{border:1px solid #1e293b;border-radius:8px;margin-top:14px;
  padding:12px 12px 10px 12px;font-size:12px;color:#475569;}
QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;color:#475569;}
QLabel{color:#cbd5e1;}
QScrollBar:vertical{background:#0f172a;width:8px;border-radius:4px;}
QScrollBar::handle:vertical{background:#334155;border-radius:4px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QMessageBox{background:#0f172a;}QDialog{background:#0f172a;}
QCheckBox{color:#cbd5e1;}
QTimeEdit{background:#1e293b;border:1px solid #334155;border-radius:5px;padding:5px;color:#e2e8f0;font-size:13px;}
QSpinBox{background:#1e293b;border:1px solid #334155;border-radius:5px;padding:5px;color:#e2e8f0;font-size:13px;}
QComboBox{background:#1e293b;border:1px solid #334155;border-radius:5px;padding:5px 10px;color:#e2e8f0;font-size:13px;}
QComboBox::drop-down{border:none;}
QComboBox QAbstractItemView{background:#1e293b;color:#e2e8f0;selection-background-color:#334155;}
"""

TAB_STYLE = """
QTabWidget::pane{border:none;background:#0f172a;}
QTabBar::tab{background:#080f1e;color:#475569;padding:10px 16px;border:none;font-size:12px;}
QTabBar::tab:selected{background:#0f172a;color:#e2e8f0;border-bottom:2px solid #3b82f6;}
QTabBar::tab:hover{color:#94a3b8;}
"""

TABLE_STYLE = """
QTableWidget{background:#0a1020;color:#e2e8f0;border:1px solid #1e293b;
  border-radius:6px;gridline-color:#1e293b;font-size:12px;}
QTableWidget::item{padding:5px;}
QTableWidget::item:selected{background:#1e40af;}
QTableWidget::item:alternate{background:#080f1e;}
QHeaderView::section{background:#1e293b;color:#64748b;padding:6px;
  border:none;font-size:12px;font-weight:bold;}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.manager = PostgresManager(self.config, log_callback=self._log)
        self._workers = []
        self._selected_backup_path = None
        self._db_list = []

        self.scheduler = BackupScheduler(
            config_dir=get_app_data_dir(),
            backup_fn=self._scheduled_backup_fn,
            log_fn=self._log,
        )

        self.mdns  = MDNSBroadcaster(port=self.config["port"], log_fn=self._log)
        self.minio    = MinIOManager(self.config, log_fn=self._log)
        self.pgadmin  = PgAdminManager(self.config, log_fn=self._log)

        self.setWindowTitle("PGOps")
        self.setMinimumSize(960, 680)
        self.resize(1100, 740)
        self.setStyleSheet(DARK_STYLE)

        self._build_ui()
        self._build_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(3000)

        QTimer.singleShot(1500, self._initial_load)

        if self.config.get("autostart"):
            QTimer.singleShot(800, self._start)

        if self.scheduler.schedule.get("enabled"):
            self.scheduler.start()

        QTimer.singleShot(500, self._auto_start_mdns)

    def _initial_load(self):
        self._poll()
        if self.manager.is_running():
            self._load_databases_async()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vb = QVBoxLayout(root)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)
        vb.addWidget(self._header())
        vb.addWidget(self._tabs())

    def _header(self):
        bar = QWidget()
        bar.setFixedHeight(62)
        bar.setStyleSheet("background:#080f1e;border-bottom:1px solid #1e293b;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 0, 18, 0)
        icon = QLabel("PG")
        icon.setStyleSheet("color:#3b82f6;font-size:20px;font-weight:900;")
        title = QLabel("PGOps")
        title.setStyleSheet("color:#fff;font-size:17px;font-weight:700;")
        sub = QLabel("Portable PostgreSQL Server")
        sub.setStyleSheet("color:#475569;font-size:11px;")
        col = QVBoxLayout(); col.setSpacing(1)
        col.addWidget(title); col.addWidget(sub)
        self.badge = StatusBadge()
        self.svc_badge = QLabel()
        self.svc_badge.setStyleSheet("color:#475569;font-size:11px;")
        right_col = QVBoxLayout(); right_col.setSpacing(2)
        right_col.addWidget(self.badge); right_col.addWidget(self.svc_badge)
        h.addWidget(icon); h.addSpacing(10); h.addLayout(col)
        h.addStretch(); h.addLayout(right_col)
        return bar

    def _tabs(self):
        t = QTabWidget()
        t.setStyleSheet(TAB_STYLE)
        t.addTab(self._tab_server(),    "  Server  ")
        t.addTab(self._tab_activity(),  "  Activity  ")
        t.addTab(self._tab_files(),     "  Files  ")
        t.addTab(self._tab_databases(), "  Databases  ")
        t.addTab(self._tab_browser(),   "  Table Browser  ")
        t.addTab(self._tab_backup(),    "  Backup & Restore  ")
        t.addTab(self._tab_schedule(),  "  Schedule  ")
        t.addTab(self._tab_ssl(),       "  SSL / TLS  ")
        t.addTab(self._tab_service(),   "  Service  ")
        t.addTab(self._tab_settings(),  "  Settings  ")
        t.addTab(self._tab_network(),   "  Network  ")
        t.addTab(self._tab_log(),       "  Log  ")
        t.currentChanged.connect(self._on_tab_changed)
        self._tabs_widget = t
        return t

    def _tab_files(self):
        self.files_tab = FilesTab(self.minio)
        return self.files_tab

    def _on_tab_changed(self, idx: int):
        tab_name = self._tabs_widget.tabText(idx).strip()
        if tab_name == "Activity":
            if hasattr(self, 'activity') and self.manager.is_running():
                self.activity.start_monitoring()
        else:
            if hasattr(self, 'activity'):
                self.activity.stop_monitoring()

    def _tab_activity(self):
        self.activity = ActivityMonitor(self.config)
        return self.activity

    # ── SSL / TLS tab ─────────────────────────────────────────────────────────
    def _tab_ssl(self):
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea{background:#0f172a;border:none;}"
            "QScrollBar:vertical{background:#0f172a;width:8px;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#334155;border-radius:4px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        inner = QWidget()
        inner.setStyleSheet("background:#0f172a;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(22, 18, 22, 24)
        v.setSpacing(16)

        status_box = _group("SSL / TLS Status")
        sv = status_box.layout()

        self.ssl_status_lbl = QLabel("Checking...")
        self.ssl_status_lbl.setStyleSheet("color:#94a3b8;font-size:14px;font-weight:bold;")
        sv.addWidget(self.ssl_status_lbl)

        self.ssl_cert_info_lbl = _lbl("", "#64748b", 11)
        self.ssl_cert_info_lbl.setWordWrap(True)
        sv.addWidget(self.ssl_cert_info_lbl)

        ssl_btn_row = QHBoxLayout()
        self.btn_ssl_enable  = _btn("Enable SSL",  "#065f46", "#047857", h=36)
        self.btn_ssl_disable = _btn("Disable SSL", "#7f1d1d", "#991b1b", "#fca5a5", h=36)
        self.btn_ssl_enable.clicked.connect(self._enable_ssl)
        self.btn_ssl_disable.clicked.connect(self._disable_ssl)
        ssl_btn_row.addWidget(self.btn_ssl_enable)
        ssl_btn_row.addWidget(self.btn_ssl_disable)
        ssl_btn_row.addStretch()
        sv.addLayout(ssl_btn_row)
        v.addWidget(status_box)

        cert_box = _group("Certificate")
        cv2 = cert_box.layout()
        cv2.addWidget(_lbl(
            "PGOps generates a self-signed certificate valid for 10 years. "
            "Share server.crt with client apps that need certificate verification.",
            "#64748b", 11
        ))
        gen_row = QHBoxLayout()
        self.btn_gen_cert    = _btn("Generate New Certificate", "#1d4ed8", "#1e40af", h=36)
        self.btn_export_cert = _btn("Export server.crt",        "#1e293b", "#334155", "#94a3b8", h=36)
        self.btn_gen_cert.clicked.connect(self._generate_cert)
        self.btn_export_cert.clicked.connect(self._export_cert)
        gen_row.addWidget(self.btn_gen_cert)
        gen_row.addWidget(self.btn_export_cert)
        gen_row.addStretch()
        cv2.addLayout(gen_row)
        v.addWidget(cert_box)

        conn_box = _group("Connecting with SSL")
        cnv = conn_box.layout()
        port = self.config["port"]
        cnv.addWidget(_lbl("Use these once SSL is enabled:", "#94a3b8"))
        cnv.addWidget(CopyRow(
            "URL",
            "postgresql://user:pass@pgops.local:" + str(port) + "/dbname?sslmode=require"
        ))
        cnv.addWidget(CopyRow("Laravel",  "DB_SSLMODE=require  (add to .env)"))
        cnv.addWidget(CopyRow("psycopg2", "sslmode='require'  (add to connect())"))
        cnv.addWidget(_lbl(
            "sslmode=require: encrypts the connection.\n"
            "sslmode=verify-ca: also verifies the cert (give clients server.crt).",
            "#475569", 11
        ))
        v.addWidget(conn_box)

        v.addStretch()
        scroll.setWidget(inner)
        outer_layout.addWidget(scroll)

        QTimer.singleShot(200, self._update_ssl_status)
        return outer

    # ── SSL actions ───────────────────────────────────────────────────────────
    def _update_ssl_status(self):
        if not hasattr(self, "ssl_status_lbl"):
            return
        try:
            status = get_ssl_status(DATA_DIR)
            cert_info = get_cert_info(BASE_DIR)
        except Exception:
            return
        if status["enabled"]:
            self.ssl_status_lbl.setText("SSL ENABLED")
            self.ssl_status_lbl.setStyleSheet("color:#22c55e;font-size:14px;font-weight:bold;")
        else:
            self.ssl_status_lbl.setText("SSL DISABLED")
            self.ssl_status_lbl.setStyleSheet("color:#ef4444;font-size:14px;font-weight:bold;")
        if cert_info and "expires" in cert_info:
            self.ssl_cert_info_lbl.setText(
                "Certificate: " + cert_info.get("subject", "") +
                "  |  Expires: " + cert_info.get("expires", "") +
                "  |  Serial: "  + cert_info.get("serial", "")
            )
        elif not is_ssl_configured(BASE_DIR):
            self.ssl_cert_info_lbl.setText("No certificate found -- generate one first.")

    def _generate_cert(self):
        self.btn_gen_cert.setEnabled(False)
        def fn(_prog): return generate_certificate(BASE_DIR)
        def done(ok, msg):
            self.btn_gen_cert.setEnabled(True)
            self._log(msg)
            self._update_ssl_status()
            if not ok: QMessageBox.critical(self, "Error", msg)
        self._run(fn, done)

    def _enable_ssl(self):
        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(self, "No Certificate", "Generate a certificate first.")
            return
        if not self.manager.is_initialized():
            QMessageBox.warning(self, "Not Initialized", "Start the server at least once first.")
            return
        def fn(_prog): return enable_ssl(BASE_DIR, DATA_DIR)
        def done(ok, msg):
            self._log(msg)
            self._update_ssl_status()
            if ok:
                QMessageBox.information(self, "SSL Enabled", "SSL enabled. Restart the server to apply.")
            else:
                QMessageBox.critical(self, "Error", msg)
        self._run(fn, done)

    def _disable_ssl(self):
        def fn(_prog): return disable_ssl(DATA_DIR)
        def done(ok, msg):
            self._log(msg)
            self._update_ssl_status()
        self._run(fn, done)

    def _export_cert(self):
        if not is_ssl_configured(BASE_DIR):
            QMessageBox.warning(self, "No Certificate", "Generate a certificate first.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Certificate", "pgops-server.crt",
            "Certificate Files (*.crt);;All Files (*)"
        )
        if dest:
            ok, msg = export_ca_cert(BASE_DIR, dest)
            self._log(msg)
            if ok: QMessageBox.information(self, "Exported", msg)

    # ── Server tab ────────────────────────────────────────────────────────────
    def _tab_server(self):
        w, v = _page()
        row = QHBoxLayout()
        self.btn_start = _btn("Start Server", "#1d4ed8", "#1e40af")
        self.btn_stop  = _btn("Stop Server",  "#7f1d1d", "#991b1b", "#fca5a5")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        row.addWidget(self.btn_start); row.addWidget(self.btn_stop)
        v.addLayout(row)

        self.prog = QProgressBar()
        self.prog.setVisible(False); self.prog.setFixedHeight(6)
        self.prog.setStyleSheet("QProgressBar{background:#1e293b;border-radius:3px;}QProgressBar::chunk{background:#3b82f6;border-radius:3px;}")
        v.addWidget(self.prog)

        self.notice = QLabel("PostgreSQL binaries not found. Click Setup to get started.")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("background:#451a03;color:#fdba74;padding:10px 14px;border-radius:6px;font-size:12px;")
        self.notice.setVisible(False)
        self.btn_dl = _btn("Setup PostgreSQL", "#92400e", "#b45309", "#fef3c7")
        self.btn_dl.clicked.connect(self._download)
        self.btn_dl.setVisible(False)
        v.addWidget(self.notice); v.addWidget(self.btn_dl)

        box = _group("Admin Connection")
        bv = box.layout()
        self.cr_host = CopyRow("Host", "-")
        self.cr_port = CopyRow("Port", str(self.config["port"]))
        self.cr_user = CopyRow("Username", self.config["username"])
        self.cr_pass = CopyRow("Password", self.config["password"])
        self.cr_db   = CopyRow("Database", self.config["database"])
        self.cr_conn = CopyRow("String", "-")
        for r in (self.cr_host, self.cr_port, self.cr_user, self.cr_pass, self.cr_db, _sep(), self.cr_conn):
            bv.addWidget(r)
        v.addWidget(box)

        # pgAdmin section
        pgadmin_box = _group("pgAdmin 4 — Database Web UI")
        pv = pgadmin_box.layout()

        self.pgadmin_status_lbl = QLabel("Checking...")
        self.pgadmin_status_lbl.setStyleSheet("color:#94a3b8;font-size:13px;font-weight:bold;")
        pv.addWidget(self.pgadmin_status_lbl)

        self.pgadmin_url_row = CopyRow("URL", f"http://pgops.local:5050")
        pv.addWidget(self.pgadmin_url_row)

        creds_lbl = QLabel("Default login:  admin@pgops.com  /  pgopsadmin")
        creds_lbl.setStyleSheet("color:#64748b;font-size:11px;font-family:monospace;")
        pv.addWidget(creds_lbl)

        pgadmin_btn_row = QHBoxLayout()
        self.btn_pgadmin_start = _btn("Start pgAdmin",   "#065f46", "#047857", h=34)
        self.btn_pgadmin_stop  = _btn("Stop",            "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_pgadmin_open  = _btn("Open in Browser", "#1d4ed8", "#1e40af", h=34)
        self.btn_pgadmin_reset = _btn("Reset & Restart", "#92400e", "#b45309", "#fef3c7", h=34)
        self.btn_pgadmin_start.clicked.connect(self._start_pgadmin)
        self.btn_pgadmin_stop.clicked.connect(self._stop_pgadmin)
        self.btn_pgadmin_open.clicked.connect(self._open_pgadmin)
        self.btn_pgadmin_reset.clicked.connect(self._reset_pgadmin)
        for b in (self.btn_pgadmin_start, self.btn_pgadmin_stop,
                  self.btn_pgadmin_open, self.btn_pgadmin_reset):
            pgadmin_btn_row.addWidget(b)
        pgadmin_btn_row.addStretch()
        pv.addLayout(pgadmin_btn_row)

        reset_note = QLabel(
            "If login fails: click Reset & Restart — wipes the pgAdmin database "
            "and recreates it with the credentials shown above."
        )
        reset_note.setWordWrap(True)
        reset_note.setStyleSheet(
            "background:#1c1208;color:#f59e0b;padding:8px;"
            "border-radius:5px;font-size:11px;"
        )
        pv.addWidget(reset_note)

        if not self.pgadmin.is_available():
            unavail = QLabel(
                "pgAdmin 4 not found. It is included in the EDB PostgreSQL zip — "
                "click Setup PostgreSQL on the Server tab first."
            )
            unavail.setWordWrap(True)
            unavail.setStyleSheet(
                "background:#1c1208;color:#f59e0b;padding:8px;"
                "border-radius:5px;font-size:11px;"
            )
            pv.addWidget(unavail)

        v.addWidget(pgadmin_box)
        v.addStretch()
        return w

    # ── Databases tab ─────────────────────────────────────────────────────────
    def _tab_databases(self):
        w, v = _page()
        tb = QHBoxLayout()
        self.btn_db_refresh = _btn("Refresh", "#1e293b", "#334155", "#94a3b8", h=32)
        self.btn_db_create  = _btn("New Database", "#065f46", "#047857", h=32)
        self.btn_db_drop    = _btn("Drop Selected", "#7f1d1d", "#991b1b", "#fca5a5", h=32)
        self.btn_db_chpw    = _btn("Change Password", "#1e293b", "#334155", "#94a3b8", h=32)
        self.btn_db_refresh.clicked.connect(self._load_databases_async)
        self.btn_db_create.clicked.connect(self._create_database)
        self.btn_db_drop.clicked.connect(self._drop_database)
        self.btn_db_chpw.clicked.connect(self._change_password)
        for b in (self.btn_db_refresh, self.btn_db_create, self.btn_db_drop, self.btn_db_chpw):
            tb.addWidget(b)
        tb.addStretch()
        v.addLayout(tb)

        self.db_table = QTableWidget(0, 3)
        self.db_table.setHorizontalHeaderLabels(["Database", "Owner", "Connection String"])
        self.db_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.db_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.db_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.db_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.db_table.setAlternatingRowColors(True)
        self.db_table.setStyleSheet(TABLE_STYLE)
        self.db_table.verticalHeader().setVisible(False)
        v.addWidget(self.db_table)
        v.addWidget(_lbl("Each database has its own owner and password.", "#475569", 11))
        return w

    # ── Table Browser tab ─────────────────────────────────────────────────────
    def _tab_browser(self):
        self.browser = TableBrowser(self.config)
        return self.browser

    # ── Backup & Restore tab ──────────────────────────────────────────────────
    def _tab_backup(self):
        w, v = _page()

        bk = _group("Backup")
        bkv = bk.layout()

        r1 = QHBoxLayout()
        r1.addWidget(_lbl("Database", "#94a3b8"))
        self.bk_db_combo = QComboBox()
        r1.addWidget(self.bk_db_combo)
        r1.addStretch()
        bkv.addLayout(r1)

        r2 = QHBoxLayout()
        self.bk_dir_lbl = QLineEdit(str(dbm.BACKUP_DIR))
        self.bk_dir_lbl.setReadOnly(True)
        self.bk_dir_lbl.setStyleSheet("background:#1e293b;border:1px solid #334155;border-radius:5px;padding:5px 10px;color:#64748b;font-size:12px;")
        browse_btn = _btn("Browse...", "#1e293b", "#334155", "#94a3b8", h=32)
        browse_btn.clicked.connect(self._browse_backup_dir)
        r2.addWidget(_lbl("Save to", "#94a3b8"))
        r2.addWidget(self.bk_dir_lbl)
        r2.addWidget(browse_btn)
        bkv.addLayout(r2)

        self.bk_prog = QProgressBar()
        self.bk_prog.setVisible(False); self.bk_prog.setFixedHeight(6)
        self.bk_prog.setStyleSheet("QProgressBar{background:#1e293b;border-radius:3px;}QProgressBar::chunk{background:#22c55e;border-radius:3px;}")
        bkv.addWidget(self.bk_prog)

        self.btn_backup = _btn("Backup Now", "#1d4ed8", "#1e40af")
        self.btn_backup.clicked.connect(self._do_backup)
        bkv.addWidget(self.btn_backup)
        v.addWidget(bk)

        rs = _group("Restore")
        rsv = rs.layout()

        tb2 = QHBoxLayout()
        self.btn_rs_refresh = _btn("Refresh List", "#1e293b", "#334155", "#94a3b8", h=32)
        self.btn_rs_browse  = _btn("Open File...", "#1e293b", "#334155", "#94a3b8", h=32)
        self.btn_rs_refresh.clicked.connect(self._refresh_backups)
        self.btn_rs_browse.clicked.connect(self._browse_backup_file)
        tb2.addWidget(self.btn_rs_refresh); tb2.addWidget(self.btn_rs_browse); tb2.addStretch()
        rsv.addLayout(tb2)

        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["File", "Size (MB)", "Created"])
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setAlternatingRowColors(True)
        self.backup_table.setStyleSheet(TABLE_STYLE)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setMaximumHeight(160)
        self.backup_table.itemSelectionChanged.connect(self._on_backup_selected)
        rsv.addWidget(self.backup_table)

        r3 = QHBoxLayout()
        r3.addWidget(_lbl("Restore into", "#94a3b8"))
        self.rs_db_inp = _inp(placeholder="database name (existing or new)")
        r3.addWidget(self.rs_db_inp)
        rsv.addLayout(r3)

        self.rs_prog = QProgressBar()
        self.rs_prog.setVisible(False); self.rs_prog.setFixedHeight(6)
        self.rs_prog.setStyleSheet("QProgressBar{background:#1e293b;border-radius:3px;}QProgressBar::chunk{background:#f59e0b;border-radius:3px;}")
        rsv.addWidget(self.rs_prog)

        self.btn_restore = _btn("Restore Selected Backup", "#7c3aed", "#6d28d9")
        self.btn_restore.clicked.connect(self._do_restore)
        rsv.addWidget(self.btn_restore)
        v.addWidget(rs)
        v.addStretch()
        return w

    # ── Schedule tab ──────────────────────────────────────────────────────────
    def _tab_schedule(self):
        w, v = _page()
        sch = self.scheduler.schedule
        box = _group("Automatic Backup Schedule")
        bv = box.layout()

        self.sched_enabled = QCheckBox("Enable scheduled backups")
        self.sched_enabled.setChecked(sch.get("enabled", False))
        bv.addWidget(self.sched_enabled)
        bv.addWidget(_sep())

        for label, attr, widget in [
            ("Frequency",        "sched_freq", None),
            ("At time (HH:MM)",  "sched_time", None),
            ("Day (for weekly)", "sched_dow",  None),
            ("Keep last N",      "sched_keep", None),
        ]:
            r = QHBoxLayout()
            l = _lbl(label, "#94a3b8"); l.setFixedWidth(140)
            r.addWidget(l)
            if label == "Frequency":
                self.sched_freq = QComboBox()
                self.sched_freq.addItems(["hourly", "daily", "weekly"])
                self.sched_freq.setCurrentText(sch.get("frequency", "daily"))
                r.addWidget(self.sched_freq)
            elif label == "At time (HH:MM)":
                self.sched_time = QTimeEdit()
                t = sch.get("time", "02:00").split(":")
                self.sched_time.setTime(QTime(int(t[0]), int(t[1])))
                r.addWidget(self.sched_time)
            elif label == "Day (for weekly)":
                self.sched_dow = QComboBox()
                self.sched_dow.addItems(["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"])
                self.sched_dow.setCurrentIndex(sch.get("day_of_week", 0))
                r.addWidget(self.sched_dow)
            elif label == "Keep last N":
                self.sched_keep = QSpinBox()
                self.sched_keep.setRange(1, 365)
                self.sched_keep.setValue(sch.get("keep_count", 7))
                r.addWidget(self.sched_keep)
            r.addStretch()
            bv.addLayout(r)

        bv.addWidget(_sep())
        bv.addWidget(_lbl("Databases to include:", "#94a3b8"))
        self.sched_db_list = QTableWidget(0, 2)
        self.sched_db_list.setHorizontalHeaderLabels(["", "Database"])
        self.sched_db_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sched_db_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sched_db_list.setStyleSheet(TABLE_STYLE)
        self.sched_db_list.verticalHeader().setVisible(False)
        self.sched_db_list.setMaximumHeight(140)
        bv.addWidget(self.sched_db_list)

        self.next_run_lbl = _lbl("", "#64748b", 11)
        bv.addWidget(self.next_run_lbl)
        v.addWidget(box)

        save_btn = _btn("Save Schedule", "#1d4ed8", "#1e40af")
        save_btn.clicked.connect(self._save_schedule)
        v.addWidget(save_btn)
        self.sched_status_lbl = _lbl("", "#22c55e", 12)
        v.addWidget(self.sched_status_lbl)
        v.addStretch()
        return w

    # ── Service tab ───────────────────────────────────────────────────────────
    def _tab_service(self):
        w, v = _page()
        info = _group("Windows Service Mode")
        iv = info.layout()
        iv.addWidget(QLabel(
            "Installing PostgreSQL as a Windows service means it starts automatically "
            "when the PC boots -- before anyone logs in. Ideal for dedicated PCs and VMs.\n\n"
            "Requires running PGOps as Administrator to install or remove."
        ))
        v.addWidget(info)

        svc = _group("Service Control")
        sv = svc.layout()
        self.svc_status_lbl = QLabel("Checking...")
        self.svc_status_lbl.setStyleSheet("color:#94a3b8;font-size:13px;")
        sv.addWidget(self.svc_status_lbl)

        btn_row = QHBoxLayout()
        self.btn_svc_install   = _btn("Install Service",  "#065f46", "#047857", h=36)
        self.btn_svc_uninstall = _btn("Remove Service",   "#7f1d1d", "#991b1b", "#fca5a5", h=36)
        self.btn_svc_start     = _btn("Start Service",    "#1d4ed8", "#1e40af", h=36)
        self.btn_svc_stop      = _btn("Stop Service",     "#1e293b", "#334155", "#94a3b8", h=36)
        self.btn_svc_install.clicked.connect(self._install_service)
        self.btn_svc_uninstall.clicked.connect(self._uninstall_service)
        self.btn_svc_start.clicked.connect(self._start_service)
        self.btn_svc_stop.clicked.connect(self._stop_service)
        for b in (self.btn_svc_install, self.btn_svc_uninstall, self.btn_svc_start, self.btn_svc_stop):
            btn_row.addWidget(b)
        sv.addLayout(btn_row)

        if not is_admin():
            warn = QLabel("Not running as Administrator -- service operations require admin rights.")
            warn.setStyleSheet("color:#f59e0b;background:#1c1208;padding:8px;border-radius:5px;font-size:12px;")
            warn.setWordWrap(True)
            sv.addWidget(warn)
        v.addWidget(svc)
        v.addStretch()
        return v.parentWidget() if False else w

    # ── Settings tab ─────────────────────────────────────────────────────────
    def _tab_settings(self):
        w, v = _page()
        box = _group("Admin Server Configuration")
        f = box.layout()
        self.s_user = _inp(self.config["username"])
        self.s_pass = _inp(self.config["password"])
        self.s_db   = _inp(self.config["database"])
        self.s_port = QSpinBox(); self.s_port.setRange(1024, 65535); self.s_port.setValue(self.config["port"])
        self.s_auto = QCheckBox("Auto-start server when app launches")
        self.s_auto.setChecked(self.config.get("autostart", False))
        for label, widget in [("Admin Username", self.s_user), ("Admin Password", self.s_pass),
                               ("Default Database", self.s_db), ("Port", self.s_port)]:
            row = QHBoxLayout()
            lbl = _lbl(label); lbl.setFixedWidth(130)
            row.addWidget(lbl); row.addWidget(widget)
            f.addLayout(row)
        f.addWidget(self.s_auto)
        v.addWidget(box)
        save_btn = _btn("Save Settings"); save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._save_settings)
        v.addWidget(save_btn)
        warn = _lbl("Changing admin credentials requires stopping the server and deleting pgdata/ to reinitialize.", "#475569", 11)
        warn.setWordWrap(True); v.addWidget(warn)

        v.addWidget(_sep())

        pw_box = _group("App Password")
        pv = pw_box.layout()
        pv.addWidget(_lbl("Change the master password used to unlock PGOps on launch.", "#64748b", 11))
        btn_change_pw = _btn("Change Password", "#1e293b", "#334155", "#94a3b8", h=36)
        btn_change_pw.clicked.connect(self._change_app_password)
        pv.addWidget(btn_change_pw)
        v.addWidget(pw_box)

        v.addStretch()
        return w

    # ── Network tab ───────────────────────────────────────────────────────────
    def _tab_network(self):
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea{background:#0f172a;border:none;}"
            "QScrollBar:vertical{background:#0f172a;width:8px;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#334155;border-radius:4px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        inner = QWidget()
        inner.setStyleSheet("background:#0f172a;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(22, 18, 22, 24)
        v.setSpacing(16)

        iface_box = _group("Available Network Interfaces")
        iv = iface_box.layout()

        self.iface_table = QTableWidget(0, 3)
        self.iface_table.setHorizontalHeaderLabels(["Adapter", "IP Address", "Type"])
        self.iface_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.iface_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.iface_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.iface_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.iface_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.iface_table.setStyleSheet(TABLE_STYLE)
        self.iface_table.verticalHeader().setVisible(False)
        self.iface_table.setMinimumHeight(120)
        self.iface_table.setMaximumHeight(180)
        iv.addWidget(self.iface_table)

        pin_row = QHBoxLayout()
        pin_row.addWidget(_lbl("Pinned host IP:", "#94a3b8"))
        self.pinned_ip_lbl = QLabel(self.config.get("preferred_ip", "") or "Auto-detect")
        self.pinned_ip_lbl.setStyleSheet("color:#22c55e;font-size:13px;font-family:monospace;font-weight:bold;")
        pin_row.addWidget(self.pinned_ip_lbl)
        pin_row.addStretch()
        btn_pin   = _btn("Pin Selected", "#1d4ed8", "#1e40af", h=30)
        btn_unpin = _btn("Auto-detect",  "#1e293b", "#334155", "#94a3b8", h=30)
        btn_refresh_ifaces = _btn("Refresh", "#1e293b", "#334155", "#94a3b8", h=30)
        btn_pin.clicked.connect(self._pin_selected_ip)
        btn_unpin.clicked.connect(self._unpin_ip)
        btn_refresh_ifaces.clicked.connect(self._refresh_interfaces)
        for b in (btn_pin, btn_unpin, btn_refresh_ifaces):
            pin_row.addWidget(b)
        iv.addLayout(pin_row)

        iv.addWidget(_lbl(
            "Hotspot IP (192.168.137.1) is always fixed -- pin it when using hotspot mode "
            "so your apps always use the same address.",
            "#64748b", 11
        ))
        v.addWidget(iface_box)

        mdns_box = _group("Local Domain  --  pgops.local")
        mv = mdns_box.layout()

        self.mdns_status_lbl = QLabel("Checking...")
        self.mdns_status_lbl.setStyleSheet("color:#94a3b8;font-size:13px;font-weight:bold;")
        mv.addWidget(self.mdns_status_lbl)

        self.mdns_host_row = CopyRow("Host", "pgops.local")
        mv.addWidget(self.mdns_host_row)

        mdns_btn_row = QHBoxLayout()
        btn_mdns_start = _btn("Start Broadcasting", "#065f46", "#047857", h=32)
        btn_mdns_stop  = _btn("Stop",               "#7f1d1d", "#991b1b", "#fca5a5", h=32)
        btn_mdns_test  = _btn("Test Resolution",    "#1e293b", "#334155", "#94a3b8", h=32)
        btn_mdns_start.clicked.connect(self._start_mdns)
        btn_mdns_stop.clicked.connect(self._stop_mdns)
        btn_mdns_test.clicked.connect(self._test_mdns)
        for b in (btn_mdns_start, btn_mdns_stop, btn_mdns_test):
            mdns_btn_row.addWidget(b)
        mv.addLayout(mdns_btn_row)

        mv.addWidget(CopyRow("Conn", f"postgresql://user:pass@pgops.local:{self.config['port']}/dbname"))

        mv.addWidget(_lbl(
            "pgops.local broadcasts automatically on every launch. All your apps should use pgops.local as the database host.  "
            "Windows 10/11: native.  Older Windows: install Bonjour.  "
            "macOS/iOS: native.  Linux: avahi-daemon.  Android: usually works.",
            "#475569", 11
        ))
        v.addWidget(mdns_box)

        hs = _group("WiFi Hotspot -- Windows Mobile Hotspot")
        hv = hs.layout()

        r1 = QHBoxLayout()
        self.hs_ssid = _inp("PGOps-Net")
        self.hs_pw   = _inp("postgres123")
        for lt, fld in [("SSID", self.hs_ssid), ("Password (8+ chars)", self.hs_pw)]:
            l = _lbl(lt); l.setFixedWidth(140)
            r1.addWidget(l); r1.addWidget(fld)
        hv.addLayout(r1)

        r2 = QHBoxLayout()
        hs_start    = _btn("Start Hotspot", "#065f46", "#047857", h=34)
        hs_stop     = _btn("Stop Hotspot",  "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        hs_settings = _btn("Open Settings", "#1e293b", "#334155", "#94a3b8", h=34)
        hs_start.clicked.connect(self._start_hotspot)
        hs_stop.clicked.connect(self._stop_hotspot)
        hs_settings.clicked.connect(self._open_hotspot_settings)
        r2.addWidget(hs_start); r2.addWidget(hs_stop); r2.addWidget(hs_settings)
        hv.addLayout(r2)

        self.hs_msg = _lbl("", "#94a3b8", 12)
        self.hs_msg.setWordWrap(True)
        hv.addWidget(self.hs_msg)
        v.addWidget(hs)

        fw = _group("Firewall -- run once as Administrator")
        fv = fw.layout()
        self.fw_cmd = CopyRow("CMD", f'netsh advfirewall firewall add rule name="PGOps" dir=in action=allow protocol=TCP localport={self.config["port"]}')
        fv.addWidget(self.fw_cmd)
        fv.addWidget(_lbl("Run this once so other devices can reach the database.", "#475569", 11))
        v.addWidget(fw)

        v.addStretch()

        scroll.setWidget(inner)
        outer_layout.addWidget(scroll)

        QTimer.singleShot(300, self._refresh_interfaces)
        return outer

    # ── Log tab ───────────────────────────────────────────────────────────────
    def _tab_log(self):
        w, v = _page()
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background:#020617;color:#86efac;font-family:monospace;font-size:12px;border:1px solid #1e293b;border-radius:6px;padding:8px;")
        clr = _btn("Clear Log", "#1e293b", "#334155", "#94a3b8", h=30)
        clr.clicked.connect(self.log_box.clear)
        v.addWidget(self.log_box); v.addWidget(clr)
        return w

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _build_tray(self):
        px = QPixmap(16, 16); px.fill(QColor("#3b82f6"))
        self.tray = QSystemTrayIcon(QIcon(px), self)
        m = QMenu()
        m.addAction(QAction("Show",         self, triggered=self.show))
        m.addSeparator()
        m.addAction(QAction("Start Server", self, triggered=self._start))
        m.addAction(QAction("Stop Server",  self, triggered=self._stop))
        m.addSeparator()
        m.addAction(QAction("Quit",         self, triggered=self._quit))
        self.tray.setContextMenu(m)
        self.tray.activated.connect(
            lambda r: self.show() if r == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def closeEvent(self, e):
        e.ignore(); self.hide()
        self.tray.showMessage("PGOps", "Running in system tray.", QSystemTrayIcon.MessageIcon.Information, 2000)

    def _quit(self):
        self.scheduler.stop()
        self.mdns.stop()
        if self.minio.is_running():
            self.minio.stop()
        if self.pgadmin.is_running():
            self.pgadmin.stop()
        if self.manager.is_running() and not service_exists():
            self.manager.stop()
        QApplication.quit()

    # ── Server actions ────────────────────────────────────────────────────────
    def _start(self):
        if not self.manager.is_binaries_available():
            self.notice.setVisible(True); self.btn_dl.setVisible(True); return
        self.badge.starting(); self.btn_start.setEnabled(False)
        def fn(_prog): return self.manager.start(), ""
        self._run(fn, self._on_start_done)

    def _on_start_done(self, ok, msg):
        self.btn_start.setEnabled(True); self._poll()
        if ok:
            self._load_databases_async(); self._refresh_backups()
            self._update_ssl_status()
            if not self.minio.is_running() and self.minio.is_binaries_available():
                def _start_minio(_p): return self.minio.start()
                self._run(_start_minio, lambda ok, msg: self._log(f"[MinIO] {msg}"))
            if not self.pgadmin.is_running() and self.pgadmin.is_available():
                def _start_pgadmin(_p): return self.pgadmin.start()
                self._run(_start_pgadmin, lambda ok, msg: (
                    self._log(f"[pgAdmin] {msg}"),
                    self._update_pgadmin_status()
                ))

    def _stop(self):
        self.btn_stop.setEnabled(False)
        if self.minio.is_running():
            self.minio.stop()
        if self.pgadmin.is_running():
            self.pgadmin.stop()
        def fn(_prog): return self.manager.stop(), ""
        self._run(fn, lambda ok, msg: (self.btn_stop.setEnabled(True), self._poll()))

    def _download(self):
        self.btn_dl.setEnabled(False); self.prog.setVisible(True); self.prog.setValue(0)
        def fn(prog_cb):
            self.manager.setup_binaries(progress_callback=prog_cb)
            return True, ""
        w = self._run(fn, self._on_dl_done)
        w.progress.connect(self.prog.setValue)

    def _on_dl_done(self, ok, msg):
        self.prog.setVisible(False); self.btn_dl.setEnabled(True)
        if ok:
            self.notice.setVisible(False); self.btn_dl.setVisible(False)
            self._log("Setup complete. Click Start Server.")
        else:
            self._log(f"Setup failed: {msg}")

    # ── Database loading ───────────────────────────────────────────────────────
    def _load_databases_async(self):
        if not self.manager.is_running():
            return
        cfg = self.config
        def fn(_prog):
            dbs = dbm.list_databases(cfg["username"], cfg["password"], cfg["port"])
            return True, dbs

        def done(ok, raw):
            if ok:
                try:
                    dbs = dbm.list_databases(cfg["username"], cfg["password"], cfg["port"])
                    self._populate_db_list(dbs)
                except Exception as e:
                    self._log(f"DB list error: {e}")

        self._run(fn, done)

    def _populate_db_list(self, dbs):
        self._db_list = dbs
        ip   = self.manager.get_lan_ip()
        port = self.config["port"]

        self.db_table.setRowCount(0)
        self.bk_db_combo.clear()

        for db in dbs:
            row = self.db_table.rowCount()
            self.db_table.insertRow(row)
            self.db_table.setItem(row, 0, QTableWidgetItem(db["name"]))
            self.db_table.setItem(row, 1, QTableWidgetItem(db["owner"]))
            conn = f"postgresql://{db['owner']}:<pw>@{ip}:{port}/{db['name']}"
            self.db_table.setItem(row, 2, QTableWidgetItem(conn))
            self.bk_db_combo.addItem(db["name"])

        self.browser.refresh_databases(dbs)
        self._refresh_sched_db_list(dbs)

    def _refresh_sched_db_list(self, dbs):
        enabled_dbs = set(self.scheduler.schedule.get("databases", []))
        self.sched_db_list.setRowCount(0)
        for db in dbs:
            name = db["name"] if isinstance(db, dict) else db
            row = self.sched_db_list.rowCount()
            self.sched_db_list.insertRow(row)
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.CheckState.Checked if name in enabled_dbs else Qt.CheckState.Unchecked)
            self.sched_db_list.setItem(row, 0, chk)
            self.sched_db_list.setItem(row, 1, QTableWidgetItem(name))

    def _create_database(self):
        if not self.manager.is_running():
            QMessageBox.warning(self, "Server Not Running", "Start the server first."); return
        dlg = CreateDbDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        dbname, owner, password = dlg.values()
        def fn(_prog):
            return dbm.create_database(dbname, owner, password, self.config["username"], self.config["password"], self.config["port"])
        def done(ok, msg):
            self._log(msg)
            if ok: self._load_databases_async()
            else: QMessageBox.critical(self, "Error", msg)
        self._run(fn, done)

    def _drop_database(self):
        row = self.db_table.currentRow()
        if row < 0: return
        dbname = self.db_table.item(row, 0).text()
        if QMessageBox.question(self, "Drop Database",
            f"Permanently delete '{dbname}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes: return
        def fn(_prog):
            return dbm.drop_database(dbname, self.config["username"], self.config["password"], self.config["port"])
        self._run(fn, lambda ok, msg: (self._log(msg), self._load_databases_async()))

    def _change_password(self):
        row = self.db_table.currentRow()
        if row < 0: return
        owner = self.db_table.item(row, 1).text()
        dlg = ChangePasswordDialog(owner, self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        new_pw = dlg.value()
        def fn(_prog):
            return dbm.change_role_password(owner, new_pw, self.config["username"], self.config["password"], self.config["port"])
        self._run(fn, lambda ok, msg: self._log(msg))

    # ── Backup & Restore ──────────────────────────────────────────────────────
    def _browse_backup_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Backup Folder", str(dbm.BACKUP_DIR))
        if d: self.bk_dir_lbl.setText(d)

    def _refresh_backups(self):
        backups = dbm.list_backups()
        self.backup_table.setRowCount(0)
        for b in backups:
            row = self.backup_table.rowCount()
            self.backup_table.insertRow(row)
            item = QTableWidgetItem(b["name"])
            item.setData(Qt.ItemDataRole.UserRole, str(b["path"]))
            self.backup_table.setItem(row, 0, item)
            self.backup_table.setItem(row, 1, QTableWidgetItem(str(b["size_mb"])))
            self.backup_table.setItem(row, 2, QTableWidgetItem(b["modified"]))

    def _on_backup_selected(self):
        row = self.backup_table.currentRow()
        if row >= 0:
            item = self.backup_table.item(row, 0)
            if item:
                path_str = item.data(Qt.ItemDataRole.UserRole)
                self._selected_backup_path = Path(path_str) if path_str else None
                if path_str:
                    self.rs_db_inp.setText(Path(path_str).stem.rsplit("_", 2)[0])

    def _browse_backup_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Backup File", str(dbm.BACKUP_DIR), "Dump Files (*.dump);;All Files (*)")
        if f:
            self._selected_backup_path = Path(f)
            self.rs_db_inp.setText(Path(f).stem.rsplit("_", 2)[0])
            self._log(f"Selected: {f}")

    def _do_backup(self):
        if not self.manager.is_running():
            QMessageBox.warning(self, "Server Not Running", "Start the server first."); return
        dbname = self.bk_db_combo.currentText()
        if not dbname:
            QMessageBox.warning(self, "No Database", "No databases available."); return
        dest = Path(self.bk_dir_lbl.text())
        self.bk_prog.setVisible(True); self.bk_prog.setValue(0)
        self.btn_backup.setEnabled(False)

        user = self.config["username"]
        pw   = self.config["password"]
        port = self.config["port"]

        def fn(prog_cb):
            return dbm.backup_database(dbname, user, pw, port,
                                       dest_dir=dest, progress_callback=prog_cb)

        def done(ok, msg):
            self.bk_prog.setVisible(False)
            self.btn_backup.setEnabled(True)
            self._log(msg)
            self._refresh_backups()
            if not ok:
                QMessageBox.critical(self, "Backup Failed", msg)

        w = self._run(fn, done)
        w.progress.connect(self.bk_prog.setValue)

    def _do_restore(self):
        if not self.manager.is_running():
            QMessageBox.warning(self, "Server Not Running", "Start the server first."); return
        if not self._selected_backup_path:
            QMessageBox.warning(self, "No Backup", "Select a backup file first."); return
        dbname = self.rs_db_inp.text().strip()
        if not dbname:
            QMessageBox.warning(self, "No Target", "Enter a database name to restore into."); return
        if QMessageBox.question(self, "Restore",
            f"Restore '{self._selected_backup_path.name}' into '{dbname}'?\nExisting data will be replaced.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes: return

        self.rs_prog.setVisible(True); self.rs_prog.setValue(0)
        self.btn_restore.setEnabled(False)

        user = self.config["username"]
        pw   = self.config["password"]
        port = self.config["port"]
        backup_path = self._selected_backup_path

        def fn(prog_cb):
            return dbm.restore_database(backup_path, dbname, user, pw, port,
                                        progress_callback=prog_cb)

        def done(ok, msg):
            self.rs_prog.setVisible(False)
            self.btn_restore.setEnabled(True)
            self._log(msg)
            self._load_databases_async()
            if not ok:
                QMessageBox.critical(self, "Restore Failed", msg)

        w = self._run(fn, done)
        w.progress.connect(self.rs_prog.setValue)

    # ── Schedule ──────────────────────────────────────────────────────────────
    def _save_schedule(self):
        selected_dbs = []
        for row in range(self.sched_db_list.rowCount()):
            chk  = self.sched_db_list.item(row, 0)
            name = self.sched_db_list.item(row, 1)
            if chk and name and chk.checkState() == Qt.CheckState.Checked:
                selected_dbs.append(name.text())
        t = self.sched_time.time()
        self.scheduler.update(
            enabled=self.sched_enabled.isChecked(),
            frequency=self.sched_freq.currentText(),
            time=f"{t.hour():02d}:{t.minute():02d}",
            day_of_week=self.sched_dow.currentIndex(),
            keep_count=self.sched_keep.value(),
            databases=selected_dbs,
        )
        status = "Scheduler running." if self.scheduler.schedule["enabled"] else "Scheduler disabled."
        self.sched_status_lbl.setText(status)
        self.next_run_lbl.setText(f"Next run: {self.scheduler.next_run_str()}")
        self._log(f"Schedule saved. {status}")

    def _scheduled_backup_fn(self, dbname):
        return dbm.backup_database(dbname, self.config["username"], self.config["password"], self.config["port"])

    # ── Service ───────────────────────────────────────────────────────────────
    def _update_service_status(self):
        if platform.system() != "Windows":
            self.svc_status_lbl.setText("Service management is Windows-only.")
            return
        if service_exists():
            running = service_running()
            state, color = ("RUNNING", "#22c55e") if running else ("STOPPED", "#ef4444")
            self.svc_status_lbl.setText(f"Service installed -- {state}")
            self.svc_status_lbl.setStyleSheet(f"color:{color};font-size:13px;")
            self.svc_badge.setText("(service mode)")
        else:
            self.svc_status_lbl.setText("Service not installed -- app mode")
            self.svc_status_lbl.setStyleSheet("color:#475569;font-size:13px;")
            self.svc_badge.setText("")

    def _install_service(self):
        if not is_admin():
            QMessageBox.warning(self, "Admin Required", "Right-click PGOps.exe → Run as Administrator, then try again."); return
        if not self.manager.is_initialized():
            QMessageBox.warning(self, "Not Initialized", "Start the server at least once first."); return
        def fn(_prog): return install_service(_bin("pg_ctl"), DATA_DIR, LOG_FILE, self.config["port"])
        def done(ok, msg):
            self._log(msg); self._update_service_status()
            if not ok: QMessageBox.critical(self, "Error", msg)
        self._run(fn, done)

    def _uninstall_service(self):
        if not is_admin():
            QMessageBox.warning(self, "Admin Required", "Run as Administrator to remove the service."); return
        def fn(_prog): return uninstall_service()
        self._run(fn, lambda ok, msg: (self._log(msg), self._update_service_status()))

    def _start_service(self):
        def fn(_prog): return start_service()
        self._run(fn, lambda ok, msg: (self._log(msg), self._update_service_status()))

    def _stop_service(self):
        def fn(_prog): return stop_service()
        self._run(fn, lambda ok, msg: (self._log(msg), self._update_service_status()))

    # ── Settings ──────────────────────────────────────────────────────────────
    def _save_settings(self):
        self.config.update({
            "username": self.s_user.text().strip(), "password": self.s_pass.text().strip(),
            "database": self.s_db.text().strip(),   "port": self.s_port.value(),
            "autostart": self.s_auto.isChecked(),
        })
        save_config(self.config)
        self.manager.config = self.config
        self.browser.update_config(self.config)
        self.activity.update_config(self.config)
        self._log("Settings saved. Restart server to apply.")
        QMessageBox.information(self, "Saved", "Settings saved successfully.")

    # ── App password ──────────────────────────────────────────────────────────
    def _change_app_password(self):
        dlg = ChangePwDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Password Changed", "Master password updated successfully.")
            self._log("App password changed.")

    # ── pgAdmin actions ───────────────────────────────────────────────────────
    def _start_pgadmin(self):
        if not self.pgadmin.is_available():
            QMessageBox.warning(self, "Not Available", "pgAdmin 4 not found in PostgreSQL bundle. Run Setup PostgreSQL first.")
            return
        self.btn_pgadmin_start.setEnabled(False)
        def fn(_prog): return self.pgadmin.start()
        def done(ok, msg):
            self.btn_pgadmin_start.setEnabled(True)
            self._log(f"[pgAdmin] {msg}")
            self._update_pgadmin_status()
            if ok:
                import webbrowser
                webbrowser.open(self.pgadmin.url())
        self._run(fn, done)

    def _stop_pgadmin(self):
        def fn(_prog): return self.pgadmin.stop()
        self._run(fn, lambda ok, msg: (
            self._log(f"[pgAdmin] {msg}"),
            self._update_pgadmin_status()
        ))

    def _open_pgadmin(self):
        if not self.pgadmin.is_running():
            QMessageBox.information(self, "pgAdmin Not Running",
                "Start pgAdmin first using the Start pgAdmin button.")
            return
        import webbrowser
        webbrowser.open(self.pgadmin.url())

    def _reset_pgadmin(self):
        reply = QMessageBox.question(
            self, "Reset pgAdmin",
            "This will stop pgAdmin, delete its database, and restart it fresh.\n\n"
            "All pgAdmin settings (saved connections, preferences) will be lost.\n"
            "Your PostgreSQL databases and data are NOT affected.\n\n"
            "After reset, log in with:\n"
            "  Email:    admin@pgops.com\n"
            "  Password: pgopsadmin\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_pgadmin_reset.setEnabled(False)
        self.btn_pgadmin_start.setEnabled(False)
        self._log("[pgAdmin] Resetting and restarting…")

        def fn(_prog):
            return self.pgadmin.reset_and_restart()

        def done(ok, msg):
            self.btn_pgadmin_reset.setEnabled(True)
            self.btn_pgadmin_start.setEnabled(True)
            self._log(f"[pgAdmin] {msg}")
            self._update_pgadmin_status()
            if ok:
                import webbrowser
                webbrowser.open(self.pgadmin.url())

        self._run(fn, done)

    def _update_pgadmin_status(self):
        if not hasattr(self, "pgadmin_status_lbl"):
            return
        if not self.pgadmin.is_available():
            self.pgadmin_status_lbl.setText("Not available -- Setup PostgreSQL first")
            self.pgadmin_status_lbl.setStyleSheet("color:#475569;font-size:13px;font-weight:bold;")
            return
        if self.pgadmin.is_running():
            self.pgadmin_status_lbl.setText(f"RUNNING  --  {self.pgadmin.url()}")
            self.pgadmin_status_lbl.setStyleSheet("color:#22c55e;font-size:13px;font-weight:bold;")
            self.pgadmin_url_row.set(self.pgadmin.url())
        else:
            self.pgadmin_status_lbl.setText("STOPPED")
            self.pgadmin_status_lbl.setStyleSheet("color:#ef4444;font-size:13px;font-weight:bold;")

    # ── Network helpers ───────────────────────────────────────────────────────
    def _start_hotspot(self):
        ok, msg = start_hotspot(self.hs_ssid.text(), self.hs_pw.text())
        self.hs_msg.setText(msg)
        self.hs_msg.setStyleSheet(f"color:{'#22c55e' if ok else '#ef4444'};font-size:12px;")
        self._log(msg)

    def _stop_hotspot(self):
        ok, msg = stop_hotspot()
        self.hs_msg.setText(msg)
        self.hs_msg.setStyleSheet(f"color:{'#22c55e' if ok else '#ef4444'};font-size:12px;")
        self._log(msg)

    def _open_hotspot_settings(self):
        ok, msg = open_hotspot_settings()
        self._log(msg)

    def _auto_start_mdns(self):
        ok, msg = self.mdns.start()
        self._log(msg)
        self._update_mdns_status()

    def _start_mdns(self):
        ok, msg = self.mdns.start()
        self._log(msg)
        self._update_mdns_status()

    def _stop_mdns(self):
        reply = QMessageBox.question(
            self, "Stop Broadcasting",
            "pgops.local is the hostname all your apps use for connections.\n"
            "Stopping it will make pgops.local unreachable.\n\n"
            "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self.mdns.stop()
        self._log(msg)
        self._update_mdns_status()

    def _test_mdns(self):
        ok, msg = verify_mdns_resolution()
        self._log(f"[mDNS Test] {msg}")
        color = "#22c55e" if ok else "#ef4444"
        self.mdns_status_lbl.setStyleSheet(f"color:{color};font-size:13px;font-weight:bold;")
        self.mdns_status_lbl.setText(msg)

    def _update_mdns_status(self):
        if not hasattr(self, 'mdns_status_lbl'):
            return
        if self.mdns.is_running():
            ip = self.manager.get_lan_ip()
            self.mdns_status_lbl.setText("BROADCASTING  pgops.local  ->  " + ip)
            self.mdns_status_lbl.setStyleSheet("color:#22c55e;font-size:13px;font-weight:bold;")
            self.mdns_host_row.set("pgops.local")
        else:
            self.mdns_status_lbl.setText("Not broadcasting -- click Start Broadcasting to resume")
            self.mdns_status_lbl.setStyleSheet("color:#ef4444;font-size:13px;font-weight:bold;")

    def _refresh_interfaces(self):
        try:
            ifaces = get_all_interfaces()
        except Exception as e:
            self._log(f"Interface scan error: {e}")
            return

        self.iface_table.setRowCount(0)
        pinned = self.config.get("preferred_ip", "")
        type_colors = {
            "hotspot":  "#22c55e",
            "lan":      "#3b82f6",
            "wifi":     "#a78bfa",
            "loopback": "#475569",
            "other":    "#94a3b8",
        }
        type_labels = {
            "hotspot":  "Hotspot (fixed)",
            "lan":      "Ethernet LAN",
            "wifi":     "Wi-Fi",
            "loopback": "Loopback",
            "other":    "Other",
        }
        for iface in ifaces:
            row = self.iface_table.rowCount()
            self.iface_table.insertRow(row)
            name_item = QTableWidgetItem(iface["name"])
            ip_item   = QTableWidgetItem(iface["ip"])
            type_item = QTableWidgetItem(type_labels.get(iface["type"], iface["type"]))
            color = type_colors.get(iface["type"], "#94a3b8")
            for item in (name_item, ip_item, type_item):
                item.setForeground(QColor(color))
            if iface["ip"] == pinned or iface["type"] == "hotspot":
                from PyQt6.QtGui import QFont
                f = QFont(); f.setBold(True)
                for item in (name_item, ip_item, type_item):
                    item.setFont(f)
            ip_item.setData(Qt.ItemDataRole.UserRole, iface["ip"])
            self.iface_table.setItem(row, 0, name_item)
            self.iface_table.setItem(row, 1, ip_item)
            self.iface_table.setItem(row, 2, type_item)

        pinned_display = pinned if pinned else "Auto-detect"
        self.pinned_ip_lbl.setText(pinned_display)

    def _pin_selected_ip(self):
        row = self.iface_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select an IP", "Click a row in the interface table first.")
            return
        ip_item = self.iface_table.item(row, 1)
        if not ip_item: return
        ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
        self.config["preferred_ip"] = ip
        save_config(self.config)
        self.manager.config = self.config
        self.pinned_ip_lbl.setText(ip)
        self._log(f"Pinned host IP: {ip}")
        self._poll()

    def _unpin_ip(self):
        self.config["preferred_ip"] = ""
        save_config(self.config)
        self.manager.config = self.config
        self.pinned_ip_lbl.setText("Auto-detect")
        self._log("IP pin removed -- auto-detect enabled.")
        self._poll()

    # ── Poll ──────────────────────────────────────────────────────────────────
    def _poll(self):
        running = self.manager.is_running()
        if running:
            self.badge.running()
            d = self.manager.connection_details()
            self.cr_host.set(d["host"]); self.cr_port.set(str(d["port"]))
            self.cr_user.set(d["username"]); self.cr_pass.set(d["password"])
            self.cr_db.set(d["database"]); self.cr_conn.set(self.manager.connection_string())
        else:
            self.badge.stopped()
        if not self.manager.is_binaries_available():
            self.notice.setVisible(True); self.btn_dl.setVisible(True)
        self._update_service_status()
        self._update_mdns_status()
        self._update_pgadmin_status()
        if hasattr(self, 'next_run_lbl'):
            self.next_run_lbl.setText(f"Next run: {self.scheduler.next_run_str()}")

    # ── Internals ─────────────────────────────────────────────────────────────
    def _log(self, msg):
        if hasattr(self, 'log_box'):
            self.log_box.append(str(msg))
            self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _run(self, fn, on_done) -> Worker:
        w = Worker(fn)
        w.done.connect(on_done)
        w.start()
        self._workers.append(w)
        self._workers = [x for x in self._workers if x.isRunning()]
        return w