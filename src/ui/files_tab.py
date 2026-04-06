"""
files_tab.py
UI for MinIO file storage management.
Mirrors the databases tab — each bucket has its own access key and secret.
"""

import platform
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QDialogButtonBox, QAbstractItemView, QFrame,
    QTextEdit, QProgressBar, QMessageBox, QFileDialog,
    QScrollArea, QGroupBox, QTabWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont


TABLE_STYLE = """
QTableWidget{
    background:#0a1020;color:#e2e8f0;border:1px solid #1e293b;
    border-radius:6px;gridline-color:#1e293b;font-size:12px;
}
QTableWidget::item{padding:5px 8px;}
QTableWidget::item:selected{background:#1e40af;}
QTableWidget::item:alternate{background:#080f1e;}
QHeaderView::section{
    background:#1e293b;color:#64748b;padding:6px;
    border:none;font-size:12px;font-weight:bold;
}
"""

DIALOG_STYLE = "background:#0f172a;color:#e2e8f0;"


def _btn(text, bg="#1d4ed8", hover="#1e40af", fg="white", h=36):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 14px;font-size:12px;font-weight:600;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:#1e293b;color:#475569;}}"
    )
    return b


def _inp(val="", placeholder=""):
    f = QLineEdit(val)
    if placeholder:
        f.setPlaceholderText(placeholder)
    f.setStyleSheet(
        "background:#1e293b;border:1px solid #334155;border-radius:5px;"
        "padding:5px 10px;color:#e2e8f0;font-size:13px;"
    )
    return f


def _lbl(text, color="#94a3b8", size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;")
    return l


class Worker(QThread):
    done = pyqtSignal(bool, str)
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
            else:
                ok, msg = bool(result), ""
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


# ─── Create Bucket Dialog ─────────────────────────────────────────────────────
class CreateBucketDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Bucket")
        self.setFixedWidth(440)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(_lbl("Bucket Name", "#94a3b8"))
        self.name_field = _inp(placeholder="e.g. my-app-files (lowercase, no spaces)")
        layout.addWidget(self.name_field)

        layout.addWidget(_lbl("App / Label (optional)", "#94a3b8"))
        self.app_field = _inp(placeholder="e.g. MyApp (used to prefix access key)")
        layout.addWidget(self.app_field)

        info = QLabel(
            "PGOps will automatically create:\n"
            "  - The storage bucket\n"
            "  - A dedicated access key\n"
            "  - A policy scoped to this bucket only\n\n"
            "Other apps cannot access this bucket with their credentials."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "background:#1e293b;color:#64748b;padding:10px;"
            "border-radius:6px;font-size:11px;"
        )
        layout.addWidget(info)

        self.error_lbl = _lbl("", "#ef4444")
        self.error_lbl.setVisible(False)
        layout.addWidget(self.error_lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            "QPushButton{background:#1e293b;color:#e2e8f0;border:none;"
            "border-radius:5px;padding:6px 18px;}"
            "QPushButton:hover{background:#334155;}"
        )
        layout.addWidget(btns)

    def _validate(self):
        name = self.name_field.text().strip()
        if not name:
            self.error_lbl.setText("Bucket name is required.")
            self.error_lbl.setVisible(True)
            return
        if len(name) < 3:
            self.error_lbl.setText("Bucket name must be at least 3 characters.")
            self.error_lbl.setVisible(True)
            return
        if any(c in name for c in " _/\\"):
            self.error_lbl.setText("Use lowercase letters, numbers, and hyphens only.")
            self.error_lbl.setVisible(True)
            return
        self.accept()

    def values(self):
        return self.name_field.text().strip(), self.app_field.text().strip()


# ─── Credentials Dialog ───────────────────────────────────────────────────────
class CredentialsDialog(QDialog):
    """Shows the generated credentials and Laravel .env snippet."""

    def __init__(self, creds: dict, endpoint: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bucket Credentials")
        self.setFixedWidth(560)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Bucket Created Successfully")
        title.setStyleSheet("color:#22c55e;font-size:15px;font-weight:bold;")
        layout.addWidget(title)

        warn = QLabel(
            "Save the secret key now — it cannot be retrieved later.\n"
            "You can rotate keys at any time from the Files tab."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "background:#451a03;color:#fdba74;padding:10px;"
            "border-radius:6px;font-size:12px;"
        )
        layout.addWidget(warn)

        # Credentials
        for label, value in [
            ("Bucket",     creds.get("bucket", "")),
            ("Access Key", creds.get("access_key", "")),
            ("Secret Key", creds.get("secret_key", "")),
            ("Endpoint",   endpoint),
        ]:
            row = QHBoxLayout()
            lbl = _lbl(label)
            lbl.setFixedWidth(90)
            field = QLineEdit(value)
            field.setReadOnly(True)
            field.setStyleSheet(
                "background:#1e293b;border:1px solid #334155;"
                "border-radius:5px;padding:5px 10px;"
                "color:#e2e8f0;font-family:monospace;font-size:12px;"
            )
            copy_btn = QPushButton("Copy")
            copy_btn.setFixedSize(50, 26)
            copy_btn.setStyleSheet(
                "QPushButton{background:#334155;color:#94a3b8;"
                "border:none;border-radius:4px;font-size:11px;}"
                "QPushButton:hover{background:#475569;color:#fff;}"
            )
            copy_btn.clicked.connect(
                lambda checked, v=value, b=copy_btn: (
                    __import__('PyQt6.QtWidgets', fromlist=['QApplication'])
                    .QApplication.clipboard().setText(v),
                    b.setText("OK"),
                    QTimer.singleShot(1200, lambda: b.setText("Copy"))
                )
            )
            row.addWidget(lbl)
            row.addWidget(field)
            row.addWidget(copy_btn)
            layout.addLayout(row)

        # Laravel .env snippet
        from core.bucket_manager import get_laravel_env
        env_text = get_laravel_env(
            creds.get("bucket", ""),
            creds.get("access_key", ""),
            creds.get("secret_key", ""),
            endpoint,
        )
        layout.addWidget(_lbl("Laravel .env  (copy into your app)", "#94a3b8"))
        env_box = QTextEdit(env_text)
        env_box.setReadOnly(True)
        env_box.setFixedHeight(160)
        env_box.setStyleSheet(
            "background:#020617;color:#86efac;font-family:monospace;"
            "font-size:12px;border:1px solid #1e293b;border-radius:6px;padding:8px;"
        )
        layout.addWidget(env_box)

        copy_env_btn = _btn("Copy .env Block", "#1d4ed8", "#1e40af")
        copy_env_btn.clicked.connect(
            lambda: __import__('PyQt6.QtWidgets', fromlist=['QApplication'])
            .QApplication.clipboard().setText(env_text)
        )
        layout.addWidget(copy_env_btn)

        close_btn = _btn("Done", "#065f46", "#047857")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# ─── Files Tab Widget ─────────────────────────────────────────────────────────
class FilesTab(QWidget):
    """
    Full MinIO management tab.
    Instantiate with: FilesTab(minio_manager)
    """

    def __init__(self, minio_manager, parent=None):
        super().__init__(parent)
        self.minio  = minio_manager
        self._workers = []
        self._last_creds = {}   # stores last created creds for re-display
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet("background:#080f1e;border-bottom:1px solid #1e293b;")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(16, 0, 16, 0)
        bh.setSpacing(10)

        # Status
        self.server_badge = QLabel("MinIO: STOPPED")
        self.server_badge.setStyleSheet(
            "color:#ef4444;background:#1c0a0a;border:1px solid #ef444444;"
            "border-radius:12px;padding:2px 12px;font-size:12px;font-weight:bold;"
        )
        bh.addWidget(self.server_badge)
        bh.addStretch()

        # Start / Stop
        self.btn_start = _btn("Start Storage", "#065f46", "#047857", h=30)
        self.btn_stop  = _btn("Stop",          "#7f1d1d", "#991b1b", "#fca5a5", h=30)
        self.btn_setup = _btn("Download MinIO", "#92400e", "#b45309", "#fef3c7", h=30)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_setup.clicked.connect(self._setup)
        bh.addWidget(self.btn_setup)
        bh.addWidget(self.btn_start)
        bh.addWidget(self.btn_stop)

        # Open Console button
        self.btn_console = _btn("Open Web Console", "#1e293b", "#334155", "#94a3b8", h=30)
        self.btn_console.clicked.connect(self._open_console)
        bh.addWidget(self.btn_console)

        root.addWidget(bar)

        # Progress bar
        self.prog = QProgressBar()
        self.prog.setVisible(False)
        self.prog.setFixedHeight(4)
        self.prog.setStyleSheet(
            "QProgressBar{background:#1e293b;border:none;}"
            "QProgressBar::chunk{background:#22c55e;}"
        )
        root.addWidget(self.prog)

        # Main content
        content = QWidget()
        content.setStyleSheet("background:#0f172a;")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(18, 16, 18, 16)
        cv.setSpacing(14)

        # Endpoint info
        self.endpoint_lbl = QLabel("Endpoint: —")
        self.endpoint_lbl.setStyleSheet(
            "color:#64748b;font-size:12px;font-family:monospace;"
        )
        cv.addWidget(self.endpoint_lbl)

        # Toolbar
        tb = QHBoxLayout()
        self.btn_refresh  = _btn("Refresh",          "#1e293b", "#334155", "#94a3b8", h=30)
        self.btn_create   = _btn("New Bucket",        "#065f46", "#047857", h=30)
        self.btn_drop     = _btn("Drop Selected",     "#7f1d1d", "#991b1b", "#fca5a5", h=30)
        self.btn_creds    = _btn("Show Credentials",  "#1e293b", "#334155", "#94a3b8", h=30)
        self.btn_rotate   = _btn("Rotate Keys",       "#1e293b", "#334155", "#94a3b8", h=30)
        self.btn_backup   = _btn("Backup Bucket",     "#1d4ed8", "#1e40af", h=30)
        self.btn_refresh.clicked.connect(self.refresh_buckets)
        self.btn_create.clicked.connect(self._create_bucket)
        self.btn_drop.clicked.connect(self._drop_bucket)
        self.btn_creds.clicked.connect(self._show_credentials)
        self.btn_rotate.clicked.connect(self._rotate_keys)
        self.btn_backup.clicked.connect(self._backup_bucket)
        for b in (self.btn_refresh, self.btn_create, self.btn_drop,
                  self.btn_creds, self.btn_rotate, self.btn_backup):
            tb.addWidget(b)
        tb.addStretch()
        cv.addLayout(tb)

        # Buckets table
        self.bucket_table = QTableWidget(0, 4)
        self.bucket_table.setHorizontalHeaderLabels([
            "Bucket", "Size", "Access Key", "Connection String"
        ])
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.bucket_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.bucket_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bucket_table.setAlternatingRowColors(True)
        self.bucket_table.setStyleSheet(TABLE_STYLE)
        self.bucket_table.verticalHeader().setVisible(False)
        cv.addWidget(self.bucket_table)

        # Laravel info box
        info = QLabel(
            "Each bucket has its own access key and secret. "
            "Your Laravel app connects using FILESYSTEM_DISK=s3 "
            "with AWS_ENDPOINT pointing to pgops.local:9000. "
            "Click New Bucket to get a ready-to-paste .env block."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#334155;font-size:11px;")
        cv.addWidget(info)

        root.addWidget(content)

        # Refresh status every 5s
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(5000)
        QTimer.singleShot(500, self._update_status)

    # ── Server control ────────────────────────────────────────────────────────

    def _start(self):
        if not self.minio.is_binaries_available():
            QMessageBox.information(self, "Setup Required",
                "Click 'Download MinIO' first to get the MinIO binaries.")
            return
        self.btn_start.setEnabled(False)
        self._log_status("Starting MinIO...")

        def fn(_prog):
            return self.minio.start()

        def done(ok, msg):
            self.btn_start.setEnabled(True)
            self._update_status()
            if ok:
                self.refresh_buckets()

        self._run(fn, done)

    def _stop(self):
        self.btn_stop.setEnabled(False)

        def fn(_prog):
            return self.minio.stop()

        def done(ok, msg):
            self.btn_stop.setEnabled(True)
            self._update_status()

        self._run(fn, done)

    def _setup(self):
        self.prog.setVisible(True)
        self.prog.setValue(0)
        self.btn_setup.setEnabled(False)

        def fn(prog_cb):
            return self.minio.setup_binaries(progress_callback=prog_cb)

        def done(ok, msg):
            self.prog.setVisible(False)
            self.btn_setup.setEnabled(True)
            if ok:
                self.btn_setup.setVisible(False)
                self._update_status()
            else:
                QMessageBox.critical(self, "Setup Failed", msg)

        w = self._run(fn, done)
        w.progress.connect(self.prog.setValue)

    def _open_console(self):
        import webbrowser
        # Use IP directly — browsers may force HTTPS on .local domains via HSTS
        # which breaks plain HTTP MinIO console
        ip = self.minio.get_lan_ip()
        url = f"http://{ip}:{self.minio.console_port}"
        webbrowser.open(url)

    # ── Bucket operations ─────────────────────────────────────────────────────

    def refresh_buckets(self):
        if not self.minio.is_running():
            self.bucket_table.setRowCount(0)
            return

        from core.bucket_manager import list_buckets, get_bucket_size, get_bucket_credentials

        buckets = list_buckets()
        endpoint = self.minio.endpoint_url()
        self.bucket_table.setRowCount(0)

        for b in buckets:
            name   = b["name"]
            size   = get_bucket_size(name)
            creds  = get_bucket_credentials(name)
            ak     = creds["access_key"] if creds else "—"
            conn   = f"s3://{name}  |  endpoint: pgops.local:9000"

            row = self.bucket_table.rowCount()
            self.bucket_table.insertRow(row)
            self.bucket_table.setItem(row, 0, QTableWidgetItem(name))
            self.bucket_table.setItem(row, 1, QTableWidgetItem(size))
            self.bucket_table.setItem(row, 2, QTableWidgetItem(ak))
            self.bucket_table.setItem(row, 3, QTableWidgetItem(conn))

    def _create_bucket(self):
        """Create bucket and immediately show credentials dialog."""
        self._create_bucket_with_creds()

    def _create_bucket_with_creds(self):
        """Create bucket and immediately show credentials dialog."""
        if not self.minio.is_running():
            QMessageBox.warning(self, "Storage Not Running",
                "Start the MinIO storage server first.")
            return

        dlg = CreateBucketDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        bucket_name, app_name = dlg.values()
        self.btn_create.setEnabled(False)
        endpoint = self.minio.endpoint_url()

        from core.bucket_manager import create_bucket
        ok, msg, creds = create_bucket(bucket_name, app_name)
        self.btn_create.setEnabled(True)

        if ok:
            self.refresh_buckets()
            creds_dlg = CredentialsDialog(creds, endpoint, self)
            creds_dlg.exec()
        else:
            QMessageBox.critical(self, "Error", msg)

    def _drop_bucket(self):
        row = self.bucket_table.currentRow()
        if row < 0:
            return
        name = self.bucket_table.item(row, 0).text()

        reply = QMessageBox.question(
            self, "Drop Bucket",
            f"Permanently delete bucket '{name}' and ALL its files?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def fn(_prog):
            from core.bucket_manager import drop_bucket
            return drop_bucket(name)

        self._run(fn, lambda ok, msg: (
            QMessageBox.information(self, "Done", msg) if ok else
            QMessageBox.critical(self, "Error", msg),
            self.refresh_buckets()
        ))

    def _show_credentials(self):
        row = self.bucket_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Bucket",
                "Click a bucket row first.")
            return
        name = self.bucket_table.item(row, 0).text()
        from core.bucket_manager import get_bucket_credentials, get_laravel_env
        creds = get_bucket_credentials(name)
        endpoint = self.minio.endpoint_url()

        if not creds:
            QMessageBox.warning(self, "No Credentials Found",
                f"No access key found for bucket '{name}'.\n"
                "It may have been created outside PGOps.\n"
                "Use Rotate Keys to generate new credentials.")
            return

        # Show what we can — secret is not stored, prompt to rotate
        msg = (
            f"Bucket:      {name}\n"
            f"Access Key:  {creds['access_key']}\n"
            f"Secret Key:  (not stored — use Rotate Keys to generate a new one)\n"
            f"Endpoint:    {endpoint}\n\n"
            f"Laravel .env:\n"
            f"FILESYSTEM_DISK=s3\n"
            f"AWS_ACCESS_KEY_ID={creds['access_key']}\n"
            f"AWS_SECRET_ACCESS_KEY=<your_secret>\n"
            f"AWS_DEFAULT_REGION=us-east-1\n"
            f"AWS_BUCKET={name}\n"
            f"AWS_ENDPOINT={endpoint}\n"
            f"AWS_USE_PATH_STYLE_ENDPOINT=true"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Credentials — {name}")
        dlg.setFixedWidth(520)
        dlg.setStyleSheet(DIALOG_STYLE)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 20, 20, 20)
        txt = QTextEdit(msg)
        txt.setReadOnly(True)
        txt.setStyleSheet(
            "background:#020617;color:#86efac;font-family:monospace;"
            "font-size:12px;border:1px solid #1e293b;border-radius:6px;padding:8px;"
        )
        copy_btn = _btn("Copy All")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(msg))
        close_btn = _btn("Close", "#1e293b", "#334155", "#94a3b8")
        close_btn.clicked.connect(dlg.accept)
        row2 = QHBoxLayout()
        row2.addWidget(copy_btn)
        row2.addWidget(close_btn)
        v.addWidget(txt)
        v.addLayout(row2)
        dlg.exec()

    def _rotate_keys(self):
        row = self.bucket_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Bucket",
                "Click a bucket row first.")
            return

        name = self.bucket_table.item(row, 0).text()
        ak_item = self.bucket_table.item(row, 2)
        old_ak = ak_item.text() if ak_item else ""

        if not old_ak or old_ak == "—":
            QMessageBox.warning(self, "No Access Key",
                "No access key found. Create the bucket credentials first.")
            return

        reply = QMessageBox.question(
            self, "Rotate Keys",
            f"Generate new access key and secret for '{name}'?\n\n"
            "The old credentials will stop working immediately.\n"
            "Update your Laravel .env files after rotating.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from core.bucket_manager import rotate_keys
        ok, msg, new_creds = rotate_keys(name, old_ak)
        if ok:
            self.refresh_buckets()
            endpoint = self.minio.endpoint_url()
            creds_dlg = CredentialsDialog(new_creds, endpoint, self)
            creds_dlg.exec()
        else:
            QMessageBox.critical(self, "Error", msg)

    def _backup_bucket(self):
        row = self.bucket_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Bucket",
                "Click a bucket row first.")
            return
        name = self.bucket_table.item(row, 0).text()

        dest = QFileDialog.getExistingDirectory(
            self, "Select Backup Destination"
        )
        if not dest:
            return

        self.prog.setVisible(True)
        self.prog.setValue(0)

        def fn(prog_cb):
            from core.bucket_manager import backup_bucket
            return backup_bucket(name, Path(dest), progress_callback=prog_cb)

        def done(ok, msg):
            self.prog.setVisible(False)
            if ok:
                QMessageBox.information(self, "Backup Complete", msg)
            else:
                QMessageBox.critical(self, "Backup Failed", msg)

        w = self._run(fn, done)
        w.progress.connect(self.prog.setValue)

    # ── Status ────────────────────────────────────────────────────────────────

    def _update_status(self):
        running = self.minio.is_running()
        binaries = self.minio.is_binaries_available()

        if running:
            self.server_badge.setText("MinIO: RUNNING")
            self.server_badge.setStyleSheet(
                "color:#22c55e;background:#0a1c0f;border:1px solid #22c55e44;"
                "border-radius:12px;padding:2px 12px;font-size:12px;font-weight:bold;"
            )
            ep = self.minio.endpoint_url()
            self.endpoint_lbl.setText(
                f"API: {ep}     Console: http://{self.minio.get_lan_ip()}:{self.minio.console_port}"  + "  (use IP, not pgops.local)"
            )
            self.btn_setup.setVisible(False)
        else:
            self.server_badge.setText("MinIO: STOPPED")
            self.server_badge.setStyleSheet(
                "color:#ef4444;background:#1c0a0a;border:1px solid #ef444444;"
                "border-radius:12px;padding:2px 12px;font-size:12px;font-weight:bold;"
            )
            self.endpoint_lbl.setText("Endpoint: — (start storage server)")
            if not binaries:
                self.btn_setup.setVisible(True)

    def _log_status(self, msg: str):
        self.endpoint_lbl.setText(msg)

    # ── Worker helper ─────────────────────────────────────────────────────────

    def _run(self, fn, on_done) -> Worker:
        w = Worker(fn)
        w.done.connect(on_done)
        w.start()
        self._workers.append(w)
        self._workers = [x for x in self._workers if x.isRunning()]
        return w


# Need QApplication for clipboard in CredentialsDialog
from PyQt6.QtWidgets import QApplication
