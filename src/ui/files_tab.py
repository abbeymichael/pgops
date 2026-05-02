"""
files_tab.py
UI for SeaweedFS file storage management.
Mirrors the databases tab — each bucket has its own access key and secret.

URL policy:
  All URLs shown to the user and written into .env blocks use the mkcert-secured
  Caddy subdomains (https://s3.pgops.local / https://filer.pgops.local).
  The raw internal http://127.0.0.1:8333 is never surfaced in the UI.
"""

import platform
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QDialogButtonBox, QAbstractItemView, QFrame,
    QTextEdit, QProgressBar, QMessageBox, QFileDialog,
    QScrollArea, QGroupBox, QTabWidget, QApplication,
    QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QInputDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

# ── Colour tokens — match tab_server.py / theme.py ───────────────────────────
C_BG      = "#1a1d23"
C_SURFACE = "#20232b"
C_SURFACE2= "#262930"
C_BORDER  = "#2e3140"
C_BORDER2 = "#3a3e50"
C_TEXT    = "#e8eaf0"
C_TEXT2   = "#b0b8cc"
C_TEXT3   = "#6b7394"
C_GREEN   = "#22c55e"
C_RED     = "#ef4444"
C_BLUE    = "#4f7ef8"
C_AMBER   = "#f59e0b"
C_PURPLE  = "#a855f7"

TABLE_STYLE = f"""
QTableWidget{{
    background:{C_SURFACE};color:{C_TEXT};border:0px solid {C_BORDER};
    border-radius:8px;gridline-color:{C_BORDER};font-size:12px;
}}
QTableWidget::item{{padding:6px 10px;}}
QTableWidget::item:selected{{background:{C_BLUE}55;color:{C_TEXT};}}
QTableWidget::item:alternate{{background:{C_BG};}}
QHeaderView::section{{
    background:{C_SURFACE2};color:{C_TEXT3};padding:7px 10px;
    border:none;border-bottom:1px solid {C_BORDER};
    font-size:10px;font-weight:700;letter-spacing:1px;
}}
QScrollBar:vertical{{background:{C_BG};width:6px;border-radius:3px;}}
QScrollBar::handle:vertical{{background:{C_BORDER2};border-radius:3px;}}
"""

DIALOG_STYLE = f"background:{C_SURFACE};color:{C_TEXT};"


def _card(parent=None):
    w = QWidget(parent)
    w.setStyleSheet(
        f"background:{C_SURFACE};border:1px solid {C_BORDER};"
        f"border-radius:10px;"
    )
    return w


def _make_hdr_btn(text, bg, hover, fg="white"):
    b = QPushButton(text)
    b.setFixedHeight(34)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:7px;font-size:12px;font-weight:600;padding:0 14px;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
    )
    return b


def _btn(text, bg=C_BLUE, hover="#3b6de8", fg="white", h=36):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 14px;font-size:12px;font-weight:600;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
    )
    return b


def _inp(val="", placeholder=""):
    f = QLineEdit(val)
    if placeholder:
        f.setPlaceholderText(placeholder)
    f.setStyleSheet(
        f"background:{C_SURFACE2};border:1px solid {C_BORDER2};border-radius:6px;"
        f"padding:6px 10px;color:{C_TEXT};font-size:13px;"
        f"selection-background-color:{C_BLUE}55;"
    )
    return f


def _lbl(text, color=C_TEXT3, size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;background:transparent;")
    return l


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
            else:
                ok, msg = bool(result), ""
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


# ─── Credential field widget ──────────────────────────────────────────────────
class _CredField(QWidget):
    """A labelled read-only field with a copy icon button."""

    def __init__(self, label: str, value: str, password: bool = False, parent=None):
        super().__init__(parent)
        self._value = value
        self.setStyleSheet(
            f"background:{C_BG};border:1px solid {C_BORDER};"
            f"border-radius:8px;"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;border:none;"
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        if password:
            self._val_lbl = QLabel("•" * max(14, len(value)))
        else:
            display = value if len(value) <= 22 else value[:18] + "..."
            self._val_lbl = QLabel(display)
        self._val_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:600;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;border:none;"
        )
        self._val_lbl.setToolTip(value)

        copy_btn = QPushButton("⧉")
        copy_btn.setFixedSize(26, 26)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:5px;font-size:13px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        copy_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(value),
                copy_btn.setText("✓"),
                QTimer.singleShot(1200, lambda: copy_btn.setText("⧉"))
            )
        )

        row.addWidget(self._val_lbl, 1)
        row.addWidget(copy_btn, 0)

        v.addWidget(lbl)
        v.addLayout(row)


# ─── Create Bucket Dialog ─────────────────────────────────────────────────────
class CreateBucketDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Bucket")
        self.setFixedWidth(480)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("New Storage Bucket")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:16px;font-weight:700;background:transparent;"
        )
        layout.addWidget(title)

        layout.addSpacing(4)
        layout.addWidget(_lbl("BUCKET NAME", C_TEXT3, 10))
        self.name_field = _inp(placeholder="e.g. my-app-files  (lowercase, no spaces)")
        layout.addWidget(self.name_field)

        layout.addWidget(_lbl("APP / LABEL (optional)", C_TEXT3, 10))
        self.app_field = _inp(placeholder="e.g. MyApp  (used to prefix access key)")
        layout.addWidget(self.app_field)

        # ── Public / Private toggle ──────────────────────────────────────────
        layout.addWidget(_lbl("ACCESS POLICY", C_TEXT3, 10))
        policy_row = QHBoxLayout()
        policy_row.setSpacing(8)
        self.policy_combo = QComboBox()
        self.policy_combo.addItems(["Private  (authenticated access only)", "Public  (anyone can download files)"])
        self.policy_combo.setStyleSheet(
            f"QComboBox{{background:{C_SURFACE2};color:{C_TEXT};border:1px solid {C_BORDER2};"
            f"border-radius:6px;padding:6px 10px;font-size:12px;}}"
            f"QComboBox::drop-down{{border:none;width:24px;}}"
            f"QComboBox QAbstractItemView{{background:{C_SURFACE2};color:{C_TEXT};"
            f"selection-background-color:{C_BLUE}55;border:1px solid {C_BORDER2};}}"
        )
        policy_row.addWidget(self.policy_combo, 1)
        layout.addLayout(policy_row)

        policy_note = QLabel(
            "Private — only your app's access key can read/write files.\n"
            "Public — anyone with the file URL can download (good for public assets)."
        )
        policy_note.setWordWrap(True)
        policy_note.setStyleSheet(
            f"background:{C_BG};color:{C_TEXT3};padding:8px 12px;"
            f"border-radius:6px;font-size:11px;border:1px solid {C_BORDER};"
        )
        layout.addWidget(policy_note)

        info = QLabel(
            "PGOps will automatically create:\n"
            "  •  The storage bucket\n"
            "  •  A dedicated access key\n"
            "  •  A policy scoped to this bucket only\n\n"
            "Other apps cannot access this bucket with their credentials."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"background:{C_BG};color:{C_TEXT3};padding:12px 14px;"
            f"border-radius:8px;font-size:11px;border:1px solid {C_BORDER};"
        )
        layout.addWidget(info)

        self.error_lbl = _lbl("", C_RED)
        self.error_lbl.setVisible(False)
        layout.addWidget(self.error_lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};border:1px solid {C_BORDER2};"
            f"border-radius:6px;padding:6px 20px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
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
        """Returns (bucket_name, app_name, is_public)."""
        is_public = self.policy_combo.currentIndex() == 1
        return self.name_field.text().strip(), self.app_field.text().strip(), is_public


# ─── Credentials Dialog ───────────────────────────────────────────────────────
class CredentialsDialog(QDialog):
    """Shows the generated credentials with the HTTPS Caddy endpoint."""

    def __init__(self, creds: dict, endpoint: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generated Credentials")
        self.setFixedWidth(580)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        title = QLabel("Generated Credentials")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:17px;font-weight:700;background:transparent;"
        )
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;border-radius:6px;font-size:14px;}}"
            f"QPushButton:hover{{background:{C_BORDER};color:{C_TEXT};}}"
        )
        close_btn.clicked.connect(self.accept)
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        hdr_row.addWidget(close_btn)
        layout.addLayout(hdr_row)

        sub = QLabel("Store these securely. You will not be able to see the Secret Key again.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        layout.addWidget(sub)
        layout.addSpacing(18)

        # ── 2x2 credential grid ──────────────────────────────────────────────
        bucket  = creds.get("bucket", "")
        acc_key = creds.get("access_key", "")
        sec_key = creds.get("secret_key", "")
        region  = "us-east-1"

        grid_top = QHBoxLayout()
        grid_top.setSpacing(12)
        grid_top.addWidget(_CredField("BUCKET NAME",    bucket))
        grid_top.addWidget(_CredField("DEFAULT REGION", region))
        layout.addLayout(grid_top)

        layout.addSpacing(12)

        grid_bot = QHBoxLayout()
        grid_bot.setSpacing(12)
        grid_bot.addWidget(_CredField("ACCESS KEY ID",     acc_key))
        grid_bot.addWidget(_CredField("SECRET ACCESS KEY", sec_key, password=True))
        layout.addLayout(grid_bot)

        layout.addSpacing(18)

        # ── Endpoint note — shows HTTPS Caddy URL ────────────────────────────
        ep_note = QLabel(f"Endpoint: {endpoint}")
        ep_note.setStyleSheet(
            f"color:{C_GREEN};font-size:11px;font-family:'Consolas','Courier New',monospace;"
            f"background:{C_BG};border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:6px 12px;"
        )
        layout.addWidget(ep_note)
        layout.addSpacing(10)

        # ── Laravel .env block ───────────────────────────────────────────────
        env_hdr = QLabel("LARAVEL .ENV CONFIGURATION")
        env_hdr.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        layout.addWidget(env_hdr)
        layout.addSpacing(8)

        from core.bucket_manager import get_laravel_env
        env_text = get_laravel_env(bucket, acc_key, sec_key, endpoint)

        env_wrap = QWidget()
        env_wrap.setStyleSheet(
            f"background:{C_BG};border:1px solid {C_BORDER};border-radius:8px;"
        )
        env_wl = QVBoxLayout(env_wrap)
        env_wl.setContentsMargins(0, 0, 0, 0)
        env_wl.setSpacing(0)

        env_top_row = QHBoxLayout()
        env_top_row.setContentsMargins(14, 10, 10, 0)
        env_top_row.addStretch()

        copy_env_btn = QPushButton("⧉  COPY")
        copy_env_btn.setFixedHeight(26)
        copy_env_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_env_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:5px;"
            f"font-size:10px;font-weight:700;padding:0 10px;letter-spacing:0.5px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        copy_env_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(env_text),
                copy_env_btn.setText("✓  COPIED"),
                QTimer.singleShot(1400, lambda: copy_env_btn.setText("⧉  COPY"))
            )
        )
        env_top_row.addWidget(copy_env_btn)

        env_top_widget = QWidget()
        env_top_widget.setStyleSheet("background:transparent;")
        env_top_widget.setLayout(env_top_row)
        env_wl.addWidget(env_top_widget)

        env_box = QTextEdit(env_text)
        env_box.setReadOnly(True)
        env_box.setFixedHeight(148)
        env_box.setStyleSheet(
            f"background:transparent;color:#86efac;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;border:none;padding:4px 14px 12px 14px;"
        )
        env_wl.addWidget(env_box)
        layout.addWidget(env_wrap)

        layout.addSpacing(20)

        # ── Footer button ────────────────────────────────────────────────────
        finish_btn = QPushButton("Finish & Return")
        finish_btn.setFixedHeight(42)
        finish_btn.setFixedWidth(160)
        finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        finish_btn.setStyleSheet(
            f"QPushButton{{background:{C_TEXT};color:{C_BG};"
            f"border:none;border-radius:8px;"
            f"font-size:13px;font-weight:700;}}"
            f"QPushButton:hover{{background:#d0d4e0;}}"
        )
        finish_btn.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(finish_btn)
        layout.addLayout(footer)


# ─── Folder Manager Dialog ────────────────────────────────────────────────────
class FolderDialog(QDialog):
    """
    Browse and manage folders (key prefixes) inside a bucket.
    Allows creating and deleting folders.
    """

    def __init__(self, seaweedfs_manager, bucket: str, parent=None):
        super().__init__(parent)
        self.minio  = seaweedfs_manager
        self.bucket = bucket
        self.setWindowTitle(f"Folders — {bucket}")
        self.setFixedSize(460, 500)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel(f"Folders in  {bucket}")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        close_x = QPushButton("✕")
        close_x.setFixedSize(26, 26)
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};border:none;border-radius:5px;}}"
            f"QPushButton:hover{{background:{C_BORDER};color:{C_TEXT};}}"
        )
        close_x.clicked.connect(self.accept)
        hdr.addWidget(close_x)
        layout.addLayout(hdr)

        sub = _lbl(
            "Folders are key prefixes. Deleting a folder removes all objects inside it.",
            C_TEXT3, 11
        )
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self.folder_list = QListWidget()
        self.folder_list.setStyleSheet(
            f"QListWidget{{background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:8px;font-size:13px;padding:4px;}}"
            f"QListWidget::item{{padding:8px 12px;border-radius:4px;}}"
            f"QListWidget::item:selected{{background:{C_BLUE}55;color:{C_TEXT};}}"
            f"QListWidget::item:hover{{background:{C_SURFACE2};}}"
        )
        layout.addWidget(self.folder_list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_new_folder    = _btn("+ New Folder", "#166534", "#15803d", "#86efac", h=34)
        self.btn_delete_folder = _btn("Delete Folder", "#7f1d1d", "#991b1b", "#fca5a5", h=34)
        self.btn_refresh_fld   = _btn("Refresh", C_SURFACE2, C_BORDER2, C_TEXT2, h=34)
        self.btn_new_folder.clicked.connect(self._new_folder)
        self.btn_delete_folder.clicked.connect(self._delete_folder)
        self.btn_refresh_fld.clicked.connect(self._load_folders)
        btn_row.addWidget(self.btn_new_folder)
        btn_row.addWidget(self.btn_delete_folder)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_refresh_fld)
        layout.addLayout(btn_row)

        self._load_folders()

    def _load_folders(self):
        self.folder_list.clear()
        folders = self.minio.list_folders(self.bucket)
        if not folders:
            item = QListWidgetItem("(no folders — bucket is flat)")
            item.setForeground(QColor(C_TEXT3))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.folder_list.addItem(item)
        else:
            for f in sorted(folders):
                item = QListWidgetItem(f"📁  {f}")
                item.setData(Qt.ItemDataRole.UserRole, f)
                self.folder_list.addItem(item)

    def _new_folder(self):
        name, ok = QInputDialog.getText(
            self, "New Folder", "Folder name (no slashes):",
            QLineEdit.EchoMode.Normal, ""
        )
        if not ok or not name.strip():
            return
        name = name.strip().strip("/")
        if "/" in name or "\\" in name:
            QMessageBox.warning(self, "Invalid Name",
                "Folder name cannot contain slashes. Use the name only.")
            return
        success, msg = self.minio.create_folder(self.bucket, name)
        if success:
            self._load_folders()
        else:
            QMessageBox.critical(self, "Error", msg)

    def _delete_folder(self):
        item = self.folder_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            QMessageBox.information(self, "Select a Folder",
                "Click a folder row first.")
            return
        folder = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete Folder",
            f"Permanently delete folder '{folder}' and ALL objects inside it?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        success, msg = self.minio.delete_folder(self.bucket, folder)
        if success:
            self._load_folders()
        else:
            QMessageBox.critical(self, "Error", msg)


# ─── Files Tab Widget ─────────────────────────────────────────────────────────
class FilesTab(QWidget):
    """
    Full SeaweedFS storage management tab.
    Instantiate with: FilesTab(seaweedfs_manager)
    """

    def __init__(self, seaweedfs_manager, parent=None):
        super().__init__(parent)
        self.minio    = seaweedfs_manager
        self._workers = []
        self._last_creds = {}
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Page header ───────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(72)
        hdr.setStyleSheet(f"background:{C_BG};border-bottom:1px solid {C_BORDER};")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(28, 0, 28, 0)

        col = QVBoxLayout()
        col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        page_title = QLabel("Persistent Storage")
        page_title.setStyleSheet(
            f"color:{C_TEXT};font-size:24px;font-weight:800;background:transparent;"
        )
        badge = QLabel("SEAWEEDFS")
        badge.setStyleSheet(
            f"color:{C_TEXT3};background:{C_SURFACE};border:1px solid {C_BORDER2};"
            f"border-radius:4px;font-size:9px;font-weight:800;"
            f"letter-spacing:1.5px;padding:3px 8px;"
        )
        title_row.addWidget(page_title)
        title_row.addWidget(badge)
        title_row.addStretch()
        col.addLayout(title_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        self.server_badge = QLabel("● STOPPED")
        self.server_badge.setStyleSheet(
            f"color:{C_RED};font-size:12px;background:transparent;"
        )
        sub_row.addWidget(self.server_badge)
        sub_row.addStretch()
        col.addLayout(sub_row)

        hh.addLayout(col)
        hh.addStretch()

        self.btn_start = _make_hdr_btn("▶  Start Storage", "#166534", "#15803d", "#86efac")
        self.btn_stop  = _make_hdr_btn("■  Stop",          "#7f1d1d", "#991b1b", "#fca5a5")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        hh.addWidget(self.btn_start)
        hh.addSpacing(8)
        hh.addWidget(self.btn_stop)
        root.addWidget(hdr)

        # ── Progress bar ──────────────────────────────────────────────────
        self.prog = QProgressBar()
        self.prog.setVisible(False)
        self.prog.setFixedHeight(3)
        self.prog.setTextVisible(False)
        self.prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_GREEN};}}"
        )
        root.addWidget(self.prog)

        # ── Scrollable body ───────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")

        body = QWidget()
        body.setStyleSheet(f"background:{C_BG};")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(28, 24, 28, 28)
        bv.setSpacing(18)

        # ── Status / endpoint card ────────────────────────────────────────
        status_card = _card()
        sc = QHBoxLayout(status_card)
        sc.setContentsMargins(20, 14, 20, 14)
        sc.setSpacing(14)

        ep_col = QVBoxLayout()
        ep_col.setSpacing(3)
        ep_title = QLabel("Storage Endpoint")
        ep_title.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:700;background:transparent;"
        )
        self.endpoint_lbl = QLabel("Endpoint: — (start storage server)")
        self.endpoint_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;"
        )
        ep_col.addWidget(ep_title)
        ep_col.addWidget(self.endpoint_lbl)
        sc.addLayout(ep_col, 1)

        self.btn_setup = _make_hdr_btn("⚙  Setup SeaweedFS", "#78350f", "#92400e", "#fef3c7")
        self.btn_setup.clicked.connect(self._setup)
        self.btn_console = _make_hdr_btn("Open Filer UI →", C_SURFACE2, C_BORDER2, C_TEXT2)
        self.btn_console.clicked.connect(self._open_console)
        sc.addWidget(self.btn_setup)
        sc.addWidget(self.btn_console)
        bv.addWidget(status_card)

        # ── Buckets card ──────────────────────────────────────────────────
        buckets_card = _card()
        bc = QVBoxLayout(buckets_card)
        bc.setContentsMargins(22, 20, 22, 20)
        bc.setSpacing(14)

        buckets_hdr = QHBoxLayout()
        bh_col = QVBoxLayout()
        bh_col.setSpacing(3)
        bt = QLabel("Storage Buckets")
        bt.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        bsub = QLabel("Manage buckets, access policies, folders, and credentials.")
        bsub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        bh_col.addWidget(bt)
        bh_col.addWidget(bsub)
        buckets_hdr.addLayout(bh_col)
        buckets_hdr.addStretch()

        # Toolbar buttons
        self.btn_refresh    = _btn("Refresh",        C_SURFACE2, C_BORDER2, C_TEXT2,  h=32)
        self.btn_create     = _btn("+ New Bucket",    "#166534",  "#15803d", "#86efac", h=32)
        self.btn_drop       = _btn("Drop",            "#7f1d1d",  "#991b1b", "#fca5a5", h=32)
        self.btn_creds      = _btn("Credentials",     C_SURFACE2, C_BORDER2, C_TEXT2,  h=32)
        self.btn_rotate     = _btn("Rotate Keys",     C_SURFACE2, C_BORDER2, C_TEXT2,  h=32)
        self.btn_policy     = _btn("Toggle Public",   C_SURFACE2, C_BORDER2, C_TEXT2,  h=32)
        self.btn_folders    = _btn("📁 Folders",      C_SURFACE2, C_BORDER2, C_TEXT2,  h=32)
        self.btn_backup     = _btn("Backup",          C_BLUE,     "#3b6de8", "white",   h=32)

        self.btn_refresh.clicked.connect(self.refresh_buckets)
        self.btn_create.clicked.connect(self._create_bucket)
        self.btn_drop.clicked.connect(self._drop_bucket)
        self.btn_creds.clicked.connect(self._show_credentials)
        self.btn_rotate.clicked.connect(self._rotate_keys)
        self.btn_policy.clicked.connect(self._toggle_policy)
        self.btn_folders.clicked.connect(self._manage_folders)
        self.btn_backup.clicked.connect(self._backup_bucket)

        tb = QHBoxLayout()
        tb.setSpacing(8)
        for b in (self.btn_refresh, self.btn_create, self.btn_drop,
                  self.btn_creds, self.btn_rotate, self.btn_policy,
                  self.btn_folders, self.btn_backup):
            tb.addWidget(b)

        buckets_hdr.addLayout(tb)
        bc.addLayout(buckets_hdr)

        # Table: Bucket | Size | Policy | Access Key | Endpoint
        self.bucket_table = QTableWidget(0, 5)
        self.bucket_table.setHorizontalHeaderLabels([
            "Bucket", "Size", "Policy", "Access Key", "Endpoint"
        ])
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.bucket_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        self.bucket_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.bucket_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bucket_table.setAlternatingRowColors(True)
        self.bucket_table.setStyleSheet(TABLE_STYLE)
        self.bucket_table.verticalHeader().setVisible(False)
        self.bucket_table.setMinimumHeight(180)
        bc.addWidget(self.bucket_table)

        info = QLabel(
            "Each bucket has its own access key and secret. "
            "Private buckets require credentials — public buckets allow anonymous downloads. "
            "Your Laravel app connects via FILESYSTEM_DISK=s3 with AWS_ENDPOINT pointing to "
            "https://s3.pgops.local (mkcert-secured, no certificate warnings). "
            "Use 📁 Folders to create key-prefix folders inside a bucket."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        bc.addWidget(info)
        bv.addWidget(buckets_card)

        scroll.setWidget(body)
        root.addWidget(scroll)

        # ── Timers ────────────────────────────────────────────────────────
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(5000)
        QTimer.singleShot(500, self._update_status)

    # ── Server control ────────────────────────────────────────────────────────

    def _start(self):
        if not self.minio.is_binaries_available():
            QMessageBox.information(self, "Setup Required",
                "Click 'Setup SeaweedFS' first to get the SeaweedFS binary.")
            return
        self.btn_start.setEnabled(False)
        self._log_status("Starting SeaweedFS...")

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
        """Open the SeaweedFS Filer UI via the mkcert-secured Caddy URL."""
        import webbrowser
        webbrowser.open(self.minio.console_url())

    # ── Bucket operations ─────────────────────────────────────────────────────

    def refresh_buckets(self):
        if not self.minio.is_running():
            self.bucket_table.setRowCount(0)
            return

        from core.bucket_manager import list_buckets, get_bucket_size, get_bucket_credentials

        buckets  = list_buckets()
        endpoint = self.minio.api_url()   # HTTPS Caddy URL
        self.bucket_table.setRowCount(0)

        for b in buckets:
            name   = b["name"]
            size   = get_bucket_size(name)
            policy = self.minio.get_bucket_policy(name)
            creds  = get_bucket_credentials(name)
            ak     = creds["access_key"] if creds else "—"

            row = self.bucket_table.rowCount()
            self.bucket_table.insertRow(row)

            self.bucket_table.setItem(row, 0, QTableWidgetItem(name))
            self.bucket_table.setItem(row, 1, QTableWidgetItem(size))

            # Policy badge — colour-coded
            policy_item = QTableWidgetItem(policy.upper())
            if policy == "public":
                policy_item.setForeground(QColor(C_AMBER))
            else:
                policy_item.setForeground(QColor(C_GREEN))
            self.bucket_table.setItem(row, 2, policy_item)

            self.bucket_table.setItem(row, 3, QTableWidgetItem(ak))
            self.bucket_table.setItem(row, 4, QTableWidgetItem(endpoint))

    def _create_bucket(self):
        """Create bucket with public/private policy, then show credentials."""
        if not self.minio.is_running():
            QMessageBox.warning(self, "Storage Not Running",
                "Start the SeaweedFS storage server first.")
            return

        dlg = CreateBucketDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        bucket_name, app_name, is_public = dlg.values()
        self.btn_create.setEnabled(False)
        endpoint = self.minio.api_url()   # HTTPS Caddy URL

        from core.bucket_manager import create_bucket
        ok, msg, creds = create_bucket(bucket_name, app_name)
        self.btn_create.setEnabled(True)

        if not ok:
            QMessageBox.critical(self, "Error", msg)
            return

        # Apply public policy if requested
        if is_public:
            pub_ok, pub_msg = self.minio.set_bucket_public(bucket_name)
            if not pub_ok:
                QMessageBox.warning(self, "Policy Warning",
                    f"Bucket created, but could not set public policy:\n{pub_msg}")

        self.refresh_buckets()
        creds_dlg = CredentialsDialog(creds, endpoint, self)
        creds_dlg.exec()

    def _drop_bucket(self):
        row = self.bucket_table.currentRow()
        if row < 0:
            return
        name = self.bucket_table.item(row, 0).text()

        reply = QMessageBox.question(
            self, "Drop Bucket",
            f"Permanently delete bucket '{name}' and ALL its files?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
            QMessageBox.information(self, "Select a Bucket", "Click a bucket row first.")
            return
        name = self.bucket_table.item(row, 0).text()
        from core.bucket_manager import get_bucket_credentials
        creds    = get_bucket_credentials(name)
        endpoint = self.minio.api_url()   # HTTPS Caddy URL

        if not creds:
            QMessageBox.warning(self, "No Credentials Found",
                f"No access key found for bucket '{name}'.\n"
                "It may have been created outside PGOps.\n"
                "Use Rotate Keys to generate new credentials.")
            return

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
        v.setSpacing(10)

        t = QLabel(f"Credentials — {name}")
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        v.addWidget(t)

        txt = QTextEdit(msg)
        txt.setReadOnly(True)
        txt.setStyleSheet(
            f"background:{C_BG};color:#86efac;font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;border:1px solid {C_BORDER};border-radius:8px;padding:10px;"
        )
        copy_btn  = _btn("Copy All", C_BLUE, "#3b6de8")
        close_btn = _btn("Close", C_SURFACE2, C_BORDER2, C_TEXT2)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(msg))
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
            QMessageBox.information(self, "Select a Bucket", "Click a bucket row first.")
            return

        name    = self.bucket_table.item(row, 0).text()
        ak_item = self.bucket_table.item(row, 3)
        old_ak  = ak_item.text() if ak_item else ""

        if not old_ak or old_ak == "—":
            QMessageBox.warning(self, "No Access Key",
                "No access key found. Create the bucket credentials first.")
            return

        reply = QMessageBox.question(
            self, "Rotate Keys",
            f"Generate new access key and secret for '{name}'?\n\n"
            "The old credentials will stop working immediately.\n"
            "Update your Laravel .env files after rotating.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from core.bucket_manager import rotate_keys
        ok, msg, new_creds = rotate_keys(name, old_ak)
        if ok:
            self.refresh_buckets()
            endpoint  = self.minio.api_url()   # HTTPS Caddy URL
            creds_dlg = CredentialsDialog(new_creds, endpoint, self)
            creds_dlg.exec()
        else:
            QMessageBox.critical(self, "Error", msg)

    def _toggle_policy(self):
        """Toggle the selected bucket between public and private."""
        row = self.bucket_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Bucket", "Click a bucket row first.")
            return

        name          = self.bucket_table.item(row, 0).text()
        policy_item   = self.bucket_table.item(row, 2)
        current_policy = policy_item.text().lower() if policy_item else "private"

        if current_policy == "public":
            # Switch to private
            reply = QMessageBox.question(
                self, "Make Private",
                f"Make '{name}' private?\n\n"
                "Anonymous downloads will stop working immediately.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            ok, msg = self.minio.set_bucket_private(name)
        else:
            # Switch to public
            reply = QMessageBox.question(
                self, "Make Public",
                f"Make '{name}' publicly readable?\n\n"
                "Anyone with a file URL will be able to download files "
                "without authentication.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            ok, msg = self.minio.set_bucket_public(name)

        if ok:
            self.refresh_buckets()
        else:
            QMessageBox.critical(self, "Policy Error", msg)

    def _manage_folders(self):
        """Open the folder manager dialog for the selected bucket."""
        row = self.bucket_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Bucket",
                "Click a bucket row first.")
            return
        name = self.bucket_table.item(row, 0).text()
        if not self.minio.is_running():
            QMessageBox.warning(self, "Storage Not Running",
                "Start the SeaweedFS storage server first.")
            return
        dlg = FolderDialog(self.minio, name, self)
        dlg.exec()

    def _backup_bucket(self):
        row = self.bucket_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Bucket", "Click a bucket row first.")
            return
        name = self.bucket_table.item(row, 0).text()

        dest = QFileDialog.getExistingDirectory(self, "Select Backup Destination")
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
        running  = self.minio.is_running()
        binaries = self.minio.is_binaries_available()

        if running:
            self.server_badge.setText("● RUNNING")
            self.server_badge.setStyleSheet(
                f"color:{C_GREEN};font-size:12px;background:transparent;"
            )
            api_url     = self.minio.api_url()
            console_url = self.minio.console_url()
            self.endpoint_lbl.setText(
                f"API: {api_url}     Console: {console_url}"
            )
            self.btn_setup.setVisible(False)
        else:
            self.server_badge.setText("● STOPPED")
            self.server_badge.setStyleSheet(
                f"color:{C_RED};font-size:12px;background:transparent;"
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