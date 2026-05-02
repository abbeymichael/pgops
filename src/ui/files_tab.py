"""
files_tab.py
RustFS storage management UI.

Layout
──────
  ┌──────────────── header bar ─────────────────────────────┐
  │  Persistent Storage   [RUSTFS]  ● RUNNING  ▶ ■  Open │
  ├──────────┬──────────────────────────────────────────────┤
  │  BUCKETS │  breadcrumb  /  object toolbar               │
  │  ──────  ├──────────────────────────────────────────────┤
  │  name    │  object browser table                        │
  │  name ◀  │                                              │
  │  name    │                                              │
  │  ──────  ├──────────────────────────────────────────────┤
  │  +New    │  detail / credential panel (collapsible)     │
  └──────────┴──────────────────────────────────────────────┘

S3 compatibility
────────────────
  Credentials shown always use:
    AWS_USE_PATH_STYLE_ENDPOINT=true
    AWS_DEFAULT_REGION=us-east-1
  These are the two settings MinIO-to-RustFS migrations most often miss.
"""

import os
import platform
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QDialogButtonBox, QAbstractItemView, QFrame,
    QTextEdit, QProgressBar, QMessageBox, QFileDialog,
    QScrollArea, QApplication, QComboBox, QListWidget,
    QListWidgetItem, QSplitter, QInputDialog,
    QSizePolicy, QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QColor, QFont, QCursor

# ── Colour tokens ─────────────────────────────────────────────────────────────
C_BG      = "#1a1d23"
C_SURFACE = "#20232b"
C_SURF2   = "#262930"
C_SURF3   = "#2c2f38"
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
C_TEAL    = "#14b8a6"

TABLE_STYLE = f"""
QTableWidget{{
    background:{C_SURFACE};color:{C_TEXT};border:none;
    gridline-color:{C_BORDER};font-size:12px;
}}
QTableWidget::item{{padding:5px 10px;}}
QTableWidget::item:selected{{background:{C_BLUE}44;color:{C_TEXT};}}
QTableWidget::item:alternate{{background:{C_BG};}}
QHeaderView::section{{
    background:{C_SURF2};color:{C_TEXT3};padding:6px 10px;
    border:none;border-bottom:1px solid {C_BORDER};
    font-size:10px;font-weight:700;letter-spacing:0.8px;
}}
QScrollBar:vertical{{background:{C_BG};width:6px;border-radius:3px;}}
QScrollBar::handle:vertical{{background:{C_BORDER2};border-radius:3px;}}
QScrollBar:horizontal{{background:{C_BG};height:6px;border-radius:3px;}}
QScrollBar::handle:horizontal{{background:{C_BORDER2};border-radius:3px;}}
"""

SIDEBAR_STYLE = f"""
QListWidget{{
    background:{C_SURFACE};border:none;color:{C_TEXT};
    font-size:13px;outline:none;
}}
QListWidget::item{{
    padding:9px 14px;border-radius:6px;margin:1px 6px;
}}
QListWidget::item:selected{{
    background:{C_BLUE}33;color:{C_TEXT};
}}
QListWidget::item:hover:!selected{{
    background:{C_SURF2};
}}
"""

DIALOG_STYLE = f"background:{C_SURFACE};color:{C_TEXT};"

_INP = (
    f"background:{C_SURF2};border:1px solid {C_BORDER2};border-radius:6px;"
    f"padding:6px 10px;color:{C_TEXT};font-size:13px;"
)


# ── Widget factories ──────────────────────────────────────────────────────────

def _btn(text, bg=C_BLUE, hover="#3b6de8", fg="white", h=32, w=None):
    b = QPushButton(text)
    b.setFixedHeight(h)
    if w:
        b.setFixedWidth(w)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 14px;font-size:12px;font-weight:600;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
    )
    return b


def _lbl(text, color=C_TEXT3, size=12, bold=False):
    l = QLabel(text)
    w = "700" if bold else "400"
    l.setStyleSheet(
        f"color:{color};font-size:{size}px;font-weight:{w};background:transparent;"
    )
    return l


def _inp(val="", placeholder=""):
    f = QLineEdit(val)
    if placeholder:
        f.setPlaceholderText(placeholder)
    f.setStyleSheet(_INP)
    return f


def _sep():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background:{C_BORDER};border:none;max-height:1px;")
    return line


def _mono(text: str, color=C_TEXT) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{color};font-family:'Consolas','Courier New',monospace;"
        f"font-size:12px;background:transparent;"
    )
    l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return l


# ── Background worker ─────────────────────────────────────────────────────────

class Worker(QThread):
    done     = pyqtSignal(bool, str)
    progress = pyqtSignal(int)
    result   = pyqtSignal(object)   # for workers that return rich data

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            res = self.fn(self.progress.emit)
            if isinstance(res, tuple):
                ok  = bool(res[0])
                msg = str(res[1]) if len(res) > 1 else ""
                if len(res) > 2:
                    self.result.emit(res[2])
            else:
                ok, msg = bool(res), ""
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


# ── Copy field widget ─────────────────────────────────────────────────────────

class _CopyField(QWidget):
    """Labelled value with a copy button — used in credential panels."""

    def __init__(self, label: str, value: str, password=False, parent=None):
        super().__init__(parent)
        self._value = value
        self.setStyleSheet(
            f"background:{C_BG};border:1px solid {C_BORDER};"
            f"border-radius:8px;"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(3)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.2px;background:transparent;border:none;"
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        if password:
            display = "•" * max(14, len(value))
        else:
            display = value if len(value) <= 26 else value[:22] + "…"

        val_lbl = QLabel(display)
        val_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:12px;font-weight:600;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;border:none;"
        )
        val_lbl.setToolTip(value)

        copy_btn = QPushButton("⧉")
        copy_btn.setFixedSize(24, 24)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURF2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:4px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        copy_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(value),
                copy_btn.setText("✓"),
                QTimer.singleShot(1200, lambda: copy_btn.setText("⧉"))
            )
        )

        row.addWidget(val_lbl, 1)
        row.addWidget(copy_btn, 0)
        v.addWidget(lbl)
        v.addLayout(row)


# ── Create Bucket dialog ──────────────────────────────────────────────────────

class CreateBucketDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Bucket")
        self.setFixedWidth(500)
        self.setStyleSheet(DIALOG_STYLE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        _h = QLabel("New Storage Bucket")
        _h.setStyleSheet(
            f"color:{C_TEXT};font-size:16px;font-weight:700;background:transparent;"
        )
        lay.addWidget(_h)

        lay.addWidget(_lbl("BUCKET NAME", size=10))
        self.name_field = _inp(placeholder="e.g. my-app-files  (lowercase, 3–63 chars, hyphens OK)")
        lay.addWidget(self.name_field)

        lay.addWidget(_lbl("APP / LABEL  (optional)", size=10))
        self.app_field = _inp(placeholder="e.g. MyApp  (used to prefix the access key)")
        lay.addWidget(self.app_field)

        lay.addWidget(_lbl("ACCESS POLICY", size=10))
        self.policy_combo = QComboBox()
        self.policy_combo.addItems([
            "Private  —  authenticated access only (recommended)",
            "Public   —  anyone can download files without credentials",
        ])
        self.policy_combo.setStyleSheet(
            f"QComboBox{{background:{C_SURF2};color:{C_TEXT};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"padding:6px 10px;font-size:12px;}}"
            f"QComboBox::drop-down{{border:none;width:24px;}}"
            f"QComboBox QAbstractItemView{{background:{C_SURF2};color:{C_TEXT};"
            f"selection-background-color:{C_BLUE}55;"
            f"border:1px solid {C_BORDER2};}}"
        )
        lay.addWidget(self.policy_combo)

        # Info box
        info_box = QLabel(
            "PGOps will automatically create:\n"
            "  •  The S3 bucket\n"
            "  •  A dedicated IAM user scoped to this bucket only\n"
            "  •  An access key + secret  (stored securely — never lost)\n"
            "  •  A policy granting full object CRUD on this bucket only\n\n"
            "Other buckets' credentials cannot access this one."
        )
        info_box.setWordWrap(True)
        info_box.setStyleSheet(
            f"background:{C_BG};color:{C_TEXT3};padding:12px 14px;"
            f"border-radius:8px;font-size:11px;border:1px solid {C_BORDER};"
        )
        lay.addWidget(info_box)

        self.error_lbl = _lbl("", C_RED)
        self.error_lbl.setVisible(False)
        lay.addWidget(self.error_lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            f"QPushButton{{background:{C_SURF2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"padding:6px 20px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        lay.addWidget(btns)

    def _validate(self):
        name = self.name_field.text().strip()
        if len(name) < 3:
            self._err("Bucket name must be at least 3 characters.")
            return
        if any(c in name for c in " _/\\"):
            self._err("Use lowercase letters, numbers, and hyphens only.")
            return
        if len(name) > 63:
            self._err("Bucket name must be 63 characters or fewer.")
            return
        self.accept()

    def _err(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)

    def values(self):
        """Returns (bucket_name, app_name, is_public)."""
        return (
            self.name_field.text().strip(),
            self.app_field.text().strip(),
            self.policy_combo.currentIndex() == 1,
        )


# ── Credentials dialog ────────────────────────────────────────────────────────

class CredentialsDialog(QDialog):
    """Full credential display shown after create / rotate."""

    def __init__(self, creds: dict, endpoint: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generated Credentials")
        self.setFixedWidth(600)
        self.setStyleSheet(DIALOG_STYLE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(0)

        # Header
        hrow = QHBoxLayout()
        title = QLabel("Generated Credentials")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:17px;font-weight:700;background:transparent;"
        )
        x = QPushButton("✕")
        x.setFixedSize(28, 28)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;border-radius:5px;font-size:14px;}}"
            f"QPushButton:hover{{background:{C_BORDER};color:{C_TEXT};}}"
        )
        x.clicked.connect(self.accept)
        hrow.addWidget(title)
        hrow.addStretch()
        hrow.addWidget(x)
        lay.addLayout(hrow)

        sub = _lbl(
            "Store the Secret Access Key securely — it is saved in PGOps and can be "
            "viewed again via the Credentials panel at any time.",
            size=11,
        )
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(16)

        bucket  = creds.get("bucket", "")
        acc_key = creds.get("access_key", "")
        sec_key = creds.get("secret_key", "")

        # 2-column grid of copy fields
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_CopyField("BUCKET NAME",    bucket))
        top.addWidget(_CopyField("DEFAULT REGION", "us-east-1"))
        lay.addLayout(top)
        lay.addSpacing(10)

        bot = QHBoxLayout()
        bot.setSpacing(12)
        bot.addWidget(_CopyField("ACCESS KEY ID",     acc_key))
        bot.addWidget(_CopyField("SECRET ACCESS KEY", sec_key, password=True))
        lay.addLayout(bot)
        lay.addSpacing(16)

        # Endpoint
        ep = QLabel(f"Endpoint:  {endpoint}")
        ep.setStyleSheet(
            f"color:{C_GREEN};font-size:11px;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:{C_BG};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:6px 12px;"
        )
        lay.addWidget(ep)
        lay.addSpacing(14)

        # Laravel .env block
        env_hdr = _lbl("LARAVEL .ENV CONFIGURATION", size=9)
        env_hdr.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        lay.addWidget(env_hdr)
        lay.addSpacing(6)

        from core.bucket_manager import get_laravel_env
        env_text = get_laravel_env(bucket, acc_key, sec_key, endpoint)

        env_wrap = QWidget()
        env_wrap.setStyleSheet(
            f"background:{C_BG};border:1px solid {C_BORDER};border-radius:8px;"
        )
        ewl = QVBoxLayout(env_wrap)
        ewl.setContentsMargins(0, 0, 0, 0)
        ewl.setSpacing(0)

        copy_row = QHBoxLayout()
        copy_row.setContentsMargins(12, 8, 10, 0)
        copy_row.addStretch()
        copy_btn = QPushButton("⧉  COPY")
        copy_btn.setFixedHeight(24)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURF2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:4px;"
            f"font-size:10px;font-weight:700;padding:0 10px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        copy_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(env_text),
                copy_btn.setText("✓  COPIED"),
                QTimer.singleShot(1400, lambda: copy_btn.setText("⧉  COPY"))
            )
        )
        copy_row.addWidget(copy_btn)
        cw = QWidget()
        cw.setStyleSheet("background:transparent;")
        cw.setLayout(copy_row)
        ewl.addWidget(cw)

        env_box = QTextEdit(env_text)
        env_box.setReadOnly(True)
        env_box.setFixedHeight(142)
        env_box.setStyleSheet(
            f"background:transparent;color:#86efac;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;border:none;padding:4px 14px 12px;"
        )
        ewl.addWidget(env_box)
        lay.addWidget(env_wrap)
        lay.addSpacing(18)

        finish = QPushButton("Done")
        finish.setFixedHeight(40)
        finish.setFixedWidth(120)
        finish.setCursor(Qt.CursorShape.PointingHandCursor)
        finish.setStyleSheet(
            f"QPushButton{{background:{C_TEXT};color:{C_BG};"
            f"border:none;border-radius:8px;"
            f"font-size:13px;font-weight:700;}}"
            f"QPushButton:hover{{background:#d0d4e0;}}"
        )
        finish.clicked.connect(self.accept)
        fr = QHBoxLayout()
        fr.addStretch()
        fr.addWidget(finish)
        lay.addLayout(fr)


# ── Credential side-panel (inside main layout) ────────────────────────────────

class _CredPanel(QWidget):
    """
    Expandable panel shown below the object browser when a bucket is selected.
    Shows all credentials and the Laravel .env block.
    """

    rotate_requested = pyqtSignal(str, str)   # bucket_name, old_access_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C_SURFACE};border-top:1px solid {C_BORDER};"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        # Header row
        hrow = QHBoxLayout()
        self._title = _lbl("CREDENTIALS", size=10, bold=True)
        self._title.setStyleSheet(
            f"color:{C_TEXT2};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;"
        )
        hrow.addWidget(self._title)
        hrow.addStretch()
        self._rotate_btn = _btn("Rotate Keys", C_SURF2, C_BORDER2, C_TEXT2, h=26)
        self._rotate_btn.clicked.connect(self._on_rotate)
        hrow.addWidget(self._rotate_btn)
        lay.addLayout(hrow)

        # Fields row
        self._fields_row = QHBoxLayout()
        self._fields_row.setSpacing(10)
        lay.addLayout(self._fields_row)

        # Env block
        env_hdr_row = QHBoxLayout()
        env_hdr_row.addWidget(_lbl("LARAVEL .ENV", size=9))
        env_hdr_row.addStretch()
        self._copy_env_btn = QPushButton("⧉ Copy")
        self._copy_env_btn.setFixedHeight(22)
        self._copy_env_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_env_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURF2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:4px;"
            f"font-size:10px;padding:0 8px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        self._copy_env_btn.clicked.connect(self._copy_env)
        env_hdr_row.addWidget(self._copy_env_btn)
        lay.addLayout(env_hdr_row)

        self._env_box = QTextEdit()
        self._env_box.setReadOnly(True)
        self._env_box.setFixedHeight(108)
        self._env_box.setStyleSheet(
            f"background:{C_BG};color:#86efac;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:11px;border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:6px 10px;"
        )
        lay.addWidget(self._env_box)

        self._bucket_name  = ""
        self._access_key   = ""
        self._env_text     = ""

    def load(self, bucket_name: str, endpoint: str):
        """Populate from local DB — no network call."""
        from core.bucket_manager import get_bucket_credentials, get_laravel_env
        self._bucket_name = bucket_name
        rec = get_bucket_credentials(bucket_name)
        if not rec:
            self._show_empty(bucket_name)
            return

        self._access_key = rec.get("access_key", "")
        secret_key       = rec.get("secret_key", "")
        is_public        = bool(rec.get("is_public", 0))
        policy_tag       = "PUBLIC" if is_public else "PRIVATE"
        policy_color     = C_AMBER if is_public else C_GREEN

        self._title.setText(
            f"CREDENTIALS  —  {bucket_name}"
        )

        # Clear old fields
        while self._fields_row.count():
            item = self._fields_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for label, val, pw in [
            ("BUCKET",           bucket_name,      False),
            ("ACCESS KEY ID",    self._access_key,  False),
            ("SECRET ACCESS KEY", secret_key,       True),
            ("REGION",           "us-east-1",       False),
            ("POLICY",           policy_tag,        False),
        ]:
            f = _CopyField(label, val, pw)
            self._fields_row.addWidget(f)

        self._env_text = get_laravel_env(
            bucket_name, self._access_key, secret_key, endpoint
        )
        self._env_box.setPlainText(self._env_text)
        self._rotate_btn.setVisible(True)

    def _show_empty(self, bucket_name: str):
        self._title.setText(f"CREDENTIALS  —  {bucket_name}  (not managed by PGOps)")
        while self._fields_row.count():
            item = self._fields_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        note = _lbl(
            "No credentials found. This bucket was created outside PGOps. "
            "Use 'Rotate Keys' to generate new credentials and take ownership.",
            size=11,
        )
        note.setWordWrap(True)
        self._fields_row.addWidget(note)
        self._env_box.clear()
        self._rotate_btn.setVisible(True)

    def _copy_env(self):
        if self._env_text:
            QApplication.clipboard().setText(self._env_text)
            self._copy_env_btn.setText("✓ Copied")
            QTimer.singleShot(1400, lambda: self._copy_env_btn.setText("⧉ Copy"))

    def _on_rotate(self):
        self.rotate_requested.emit(self._bucket_name, self._access_key)


# ── Object browser ────────────────────────────────────────────────────────────

class _ObjectBrowser(QWidget):
    """
    Right-side panel: breadcrumb nav + object table + action toolbar.
    Emits signals so FilesTab can wire up workers.
    """

    upload_requested   = pyqtSignal(str, str)         # bucket, prefix
    download_requested = pyqtSignal(str, str)         # bucket, key
    delete_requested   = pyqtSignal(str, list)        # bucket, [keys]
    copy_url_requested = pyqtSignal(str, str)         # bucket, key
    folder_requested   = pyqtSignal(str, str)         # bucket, prefix

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG};")

        self._bucket  = ""
        self._prefix  = ""       # current folder prefix
        self._history = []       # breadcrumb stack of prefixes

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = QWidget()
        tb.setFixedHeight(48)
        tb.setStyleSheet(
            f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};"
        )
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(14, 0, 14, 0)
        tbh.setSpacing(6)

        # Breadcrumb
        self._breadcrumb = QLabel("Select a bucket →")
        self._breadcrumb.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;"
        )
        tbh.addWidget(self._breadcrumb, 1)

        # Action buttons
        self._btn_up     = _btn("↑ Up",       C_SURF2,   C_BORDER2, C_TEXT2, h=28)
        self._btn_new_f  = _btn("+ Folder",   C_SURF2,   C_BORDER2, C_TEXT2, h=28)
        self._btn_upload = _btn("⬆ Upload",   "#166534", "#15803d", "#86efac", h=28)
        self._btn_dl     = _btn("⬇ Download", C_SURF2,   C_BORDER2, C_TEXT2,  h=28)
        self._btn_del    = _btn("Delete",     "#7f1d1d", "#991b1b", "#fca5a5", h=28)
        self._btn_link   = _btn("⧉ Link",     C_SURF2,   C_BORDER2, C_TEXT2,  h=28)
        self._btn_ref    = _btn("⟳",          C_SURF2,   C_BORDER2, C_TEXT2,  h=28, w=32)

        self._btn_up.clicked.connect(self._go_up)
        self._btn_new_f.clicked.connect(self._new_folder)
        self._btn_upload.clicked.connect(self._upload)
        self._btn_dl.clicked.connect(self._download)
        self._btn_del.clicked.connect(self._delete)
        self._btn_link.clicked.connect(self._copy_link)
        self._btn_ref.clicked.connect(self.refresh)

        for b in (self._btn_up, self._btn_new_f, self._btn_upload,
                  self._btn_dl, self._btn_del, self._btn_link, self._btn_ref):
            tbh.addWidget(b)

        lay.addWidget(tb)

        # ── Table ─────────────────────────────────────────────────────────
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Size", "Last Modified", "ETag", "Type"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(TABLE_STYLE)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self._table, 1)

        # ── Status bar ────────────────────────────────────────────────────
        sb = QWidget()
        sb.setFixedHeight(26)
        sb.setStyleSheet(
            f"background:{C_SURFACE};border-top:1px solid {C_BORDER};"
        )
        sbh = QHBoxLayout(sb)
        sbh.setContentsMargins(14, 0, 14, 0)
        self._status_lbl = _lbl("", size=11)
        sbh.addWidget(self._status_lbl)
        sbh.addStretch()
        self._count_lbl = _lbl("", size=11)
        sbh.addWidget(self._count_lbl)
        lay.addWidget(sb)

        self._set_buttons_enabled(False)

    def load_bucket(self, bucket: str):
        self._bucket  = bucket
        self._prefix  = ""
        self._history = []
        self._set_buttons_enabled(True)
        self.refresh()

    def refresh(self):
        if not self._bucket:
            return
        self._status_lbl.setText("Loading…")
        from core.bucket_manager import list_objects
        data = list_objects(self._bucket, prefix=self._prefix, delimiter="/")

        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        if "error" in data:
            self._status_lbl.setText(f"Error: {data['error']}")
            return

        rows = 0

        # Virtual folders (common prefixes) first
        for pfx in data.get("prefixes", []):
            display = pfx[len(self._prefix):]  # strip current prefix
            r = self._table.rowCount()
            self._table.insertRow(r)
            name_item = QTableWidgetItem(f"📁  {display.rstrip('/')}")
            name_item.setData(Qt.ItemDataRole.UserRole, ("prefix", pfx))
            name_item.setForeground(QColor(C_AMBER))
            self._table.setItem(r, 0, name_item)
            for col in (1, 2, 3):
                self._table.setItem(r, col, QTableWidgetItem("—"))
            self._table.setItem(r, 4, QTableWidgetItem("Folder"))
            rows += 1

        # Objects
        for obj in data.get("objects", []):
            key = obj["key"]
            if key == self._prefix:
                continue  # skip the folder placeholder itself
            display = key[len(self._prefix):]
            r = self._table.rowCount()
            self._table.insertRow(r)

            name_item = QTableWidgetItem(f"   {display}")
            name_item.setData(Qt.ItemDataRole.UserRole, ("object", key))
            self._table.setItem(r, 0, name_item)

            size_item = QTableWidgetItem(obj["size_str"])
            size_item.setData(Qt.ItemDataRole.UserRole + 1, obj["size"])
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(r, 1, size_item)
            self._table.setItem(r, 2, QTableWidgetItem(obj["last_modified"]))
            self._table.setItem(r, 3, QTableWidgetItem(obj["etag"][:12] + "…"
                                                        if len(obj["etag"]) > 12
                                                        else obj["etag"]))
            self._table.setItem(r, 4, QTableWidgetItem(
                _ext_type(display)
            ))
            rows += 1

        self._table.setSortingEnabled(True)
        self._update_breadcrumb()
        truncated = data.get("truncated", False)
        self._status_lbl.setText(
            "Results may be truncated — use a more specific prefix to drill down."
            if truncated else ""
        )
        self._count_lbl.setText(
            f"{rows} item{'s' if rows != 1 else ''}  in  {self._bucket}/{self._prefix}"
        )

    def _update_breadcrumb(self):
        if not self._bucket:
            self._breadcrumb.setText("Select a bucket →")
            return
        parts  = [self._bucket]
        parts += [p for p in self._prefix.rstrip("/").split("/") if p]
        self._breadcrumb.setText("  /  ".join(parts))

    def _on_double_click(self, index):
        row  = index.row()
        item = self._table.item(row, 0)
        if not item:
            return
        kind, val = item.data(Qt.ItemDataRole.UserRole)
        if kind == "prefix":
            self._history.append(self._prefix)
            self._prefix = val
            self.refresh()

    def _context_menu(self, pos):
        row  = self._table.rowAt(pos.y())
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        kind, val = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{C_SURFACE};color:{C_TEXT};"
            f"border:1px solid {C_BORDER2};border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:6px 18px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{C_BLUE}44;}}"
        )
        if kind == "object":
            menu.addAction("⬇  Download",          self._download)
            menu.addAction("⧉  Copy Presigned URL", self._copy_link)
            menu.addSeparator()
            menu.addAction("🗑  Delete",            self._delete)
        else:
            menu.addAction("📂  Open Folder",  lambda: self._enter_prefix(val))
            menu.addSeparator()
            menu.addAction("🗑  Delete Folder", self._delete)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _enter_prefix(self, pfx: str):
        self._history.append(self._prefix)
        self._prefix = pfx
        self.refresh()

    def _go_up(self):
        if self._history:
            self._prefix = self._history.pop()
        else:
            self._prefix = ""
        self.refresh()

    def _selected_items(self):
        """Return list of (kind, value) for all selected rows."""
        rows = set(i.row() for i in self._table.selectedIndexes())
        items = []
        for r in rows:
            item = self._table.item(r, 0)
            if item:
                items.append(item.data(Qt.ItemDataRole.UserRole))
        return items

    def _upload(self):
        if not self._bucket:
            return
        self.upload_requested.emit(self._bucket, self._prefix)

    def _download(self):
        items = self._selected_items()
        keys  = [v for k, v in items if k == "object"]
        if not keys:
            QMessageBox.information(self, "Nothing Selected",
                "Select one or more files to download.")
            return
        for key in keys:
            self.download_requested.emit(self._bucket, key)

    def _delete(self):
        items  = self._selected_items()
        keys   = [v for k, v in items if k == "object"]
        pfxs   = [v for k, v in items if k == "prefix"]
        if not keys and not pfxs:
            QMessageBox.information(self, "Nothing Selected",
                "Select one or more items to delete.")
            return
        n = len(keys) + len(pfxs)
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Permanently delete {n} item(s)?\n\n"
            "Folders will have all their contents removed. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        all_keys = keys + pfxs   # prefixes handled server-side as prefix delete
        self.delete_requested.emit(self._bucket, all_keys)

    def _copy_link(self):
        items = self._selected_items()
        keys  = [v for k, v in items if k == "object"]
        if not keys:
            QMessageBox.information(self, "Nothing Selected",
                "Select a file to get a presigned URL.")
            return
        self.copy_url_requested.emit(self._bucket, keys[0])

    def _new_folder(self):
        if not self._bucket:
            return
        self.folder_requested.emit(self._bucket, self._prefix)

    def _set_buttons_enabled(self, enabled: bool):
        for b in (self._btn_upload, self._btn_new_f,
                  self._btn_ref, self._btn_up):
            b.setEnabled(enabled)
        self._btn_dl.setEnabled(False)
        self._btn_del.setEnabled(False)
        self._btn_link.setEnabled(False)
        if enabled:
            self._table.selectionModel().selectionChanged.connect(
                self._on_selection_change
            )

    def _on_selection_change(self, *_):
        has = bool(self._table.selectedIndexes())
        self._btn_dl.setEnabled(has)
        self._btn_del.setEnabled(has)
        self._btn_link.setEnabled(has)


def _ext_type(name: str) -> str:
    ext = Path(name).suffix.lower()
    mapping = {
        ".jpg": "Image", ".jpeg": "Image", ".png": "Image",
        ".gif": "Image", ".webp": "Image", ".svg": "Image",
        ".pdf": "PDF", ".doc": "Word", ".docx": "Word",
        ".xls": "Excel", ".xlsx": "Excel",
        ".mp4": "Video", ".mov": "Video", ".avi": "Video",
        ".mp3": "Audio", ".wav": "Audio",
        ".zip": "Archive", ".tar": "Archive", ".gz": "Archive",
        ".json": "JSON", ".xml": "XML", ".csv": "CSV",
        ".html": "HTML", ".htm": "HTML",
        ".php": "PHP", ".py": "Python", ".js": "JavaScript",
    }
    return mapping.get(ext, ext.lstrip(".").upper() or "File")


# ── Bucket sidebar ────────────────────────────────────────────────────────────

class _BucketSidebar(QWidget):
    bucket_selected = pyqtSignal(str)
    create_clicked  = pyqtSignal()
    drop_clicked    = pyqtSignal(str)
    backup_clicked  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"background:{C_SURFACE};border-right:1px solid {C_BORDER};"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Section header
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(
            f"background:{C_SURF2};border-bottom:1px solid {C_BORDER};"
        )
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(14, 0, 10, 0)
        hh.addWidget(_lbl("BUCKETS", size=10, bold=True))
        hh.addStretch()
        ref_btn = QPushButton("⟳")
        ref_btn.setFixedSize(24, 24)
        ref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ref_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;border-radius:4px;font-size:14px;}}"
            f"QPushButton:hover{{background:{C_BORDER};color:{C_TEXT};}}"
        )
        ref_btn.clicked.connect(self.load)
        hh.addWidget(ref_btn)
        lay.addWidget(hdr)

        # List
        self._list = QListWidget()
        self._list.setStyleSheet(SIDEBAR_STYLE)
        self._list.currentRowChanged.connect(self._on_row)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self._list, 1)

        # Footer
        foot = QWidget()
        foot.setFixedHeight(44)
        foot.setStyleSheet(f"border-top:1px solid {C_BORDER};")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(10, 6, 10, 6)
        new_btn = _btn("+ New Bucket", "#166534", "#15803d", "#86efac", h=30)
        new_btn.clicked.connect(self.create_clicked)
        fh.addWidget(new_btn)
        lay.addWidget(foot)

        self._buckets: list[dict] = []

    def load(self):
        from core.bucket_manager import list_buckets
        self._buckets = list_buckets()
        self._list.clear()
        for b in self._buckets:
            name    = b["name"]
            is_pub  = b.get("is_public", False)
            badge   = " 🔓" if is_pub else " 🔒"
            item    = QListWidgetItem(name + badge)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(
                f"{name}\n"
                f"App: {b.get('app_name') or '—'}\n"
                f"Policy: {'Public' if is_pub else 'Private'}\n"
                f"Created: {b.get('created_at', '')[:10]}"
            )
            self._list.addItem(item)

    def _on_row(self, row: int):
        if row < 0:
            return
        item = self._list.item(row)
        if item:
            self.bucket_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def _context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{C_SURFACE};color:{C_TEXT};"
            f"border:1px solid {C_BORDER2};border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:6px 18px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{C_BLUE}44;}}"
        )
        menu.addAction("⬇  Backup bucket", lambda: self.backup_clicked.emit(name))
        menu.addSeparator()
        menu.addAction("🗑  Drop bucket",   lambda: self.drop_clicked.emit(name))
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def current_bucket(self) -> str:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""


# ── Main FilesTab ─────────────────────────────────────────────────────────────

class FilesTab(QWidget):
    """
    Full RustFS storage management tab.
    Instantiate with: FilesTab(rustfs_manager)
    """

    def __init__(self, rustfs_manager, parent=None):
        super().__init__(parent)
        self.rustfs    = rustfs_manager
        self._workers = []
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(64)
        hdr.setStyleSheet(
            f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};"
        )
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(24, 0, 24, 0)
        hh.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        pg_title = QLabel("Persistent Storage")
        pg_title.setStyleSheet(
            f"color:{C_TEXT};font-size:16px;font-weight:700;background:transparent;"
        )
        badge = QLabel("RUSTFS")
        badge.setStyleSheet(
            f"color:{C_TEXT3};background:{C_SURF2};border:1px solid {C_BORDER2};"
            f"border-radius:4px;font-size:9px;font-weight:800;"
            f"letter-spacing:1.5px;padding:3px 8px;"
        )
        title_row.addWidget(pg_title)
        title_row.addWidget(badge)
        title_row.addStretch()
        title_col.addLayout(title_row)

        self.server_badge = QLabel("● STOPPED")
        self.server_badge.setStyleSheet(
            f"color:{C_RED};font-size:11px;background:transparent;"
        )
        self.endpoint_lbl = QLabel("Start storage to connect")
        self.endpoint_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        sub_row = QHBoxLayout()
        sub_row.setSpacing(12)
        sub_row.addWidget(self.server_badge)
        sub_row.addWidget(self.endpoint_lbl)
        sub_row.addStretch()
        title_col.addLayout(sub_row)
        hh.addLayout(title_col, 1)

        self.btn_start   = _btn("▶  Start",   "#166534", "#15803d", "#86efac", h=32)
        self.btn_stop    = _btn("■  Stop",    "#7f1d1d", "#991b1b", "#fca5a5", h=32)
        self.btn_console = _btn("Open Console →", C_SURF2, C_BORDER2, C_TEXT2, h=32)
        self.btn_setup   = _btn("⚙ Setup", "#78350f", "#92400e", "#fef3c7", h=32)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_console.clicked.connect(self._open_console)
        self.btn_setup.clicked.connect(self._setup)

        for b in (self.btn_setup, self.btn_start, self.btn_stop, self.btn_console):
            hh.addWidget(b)
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

        # ── Body: sidebar + right panel ───────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background:{C_BG};")
        bh = QHBoxLayout(body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)

        # Sidebar
        self._sidebar = _BucketSidebar()
        self._sidebar.bucket_selected.connect(self._on_bucket_selected)
        self._sidebar.create_clicked.connect(self._create_bucket)
        self._sidebar.drop_clicked.connect(self._drop_bucket)
        self._sidebar.backup_clicked.connect(self._backup_bucket)
        bh.addWidget(self._sidebar)

        # Right panel: object browser on top, cred panel below
        right = QWidget()
        right.setStyleSheet(f"background:{C_BG};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self._browser = _ObjectBrowser()
        self._browser.upload_requested.connect(self._upload)
        self._browser.download_requested.connect(self._download)
        self._browser.delete_requested.connect(self._delete_objects)
        self._browser.copy_url_requested.connect(self._copy_url)
        self._browser.folder_requested.connect(self._new_folder)
        rv.addWidget(self._browser, 1)

        self._cred_panel = _CredPanel()
        self._cred_panel.setFixedHeight(230)
        self._cred_panel.rotate_requested.connect(self._rotate_keys)
        rv.addWidget(self._cred_panel)

        bh.addWidget(right, 1)
        root.addWidget(body, 1)

        # ── Timers ────────────────────────────────────────────────────────
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(5000)
        QTimer.singleShot(400, self._update_status)

    # ── Bucket selection ──────────────────────────────────────────────────────

    def _on_bucket_selected(self, bucket: str):
        self._browser.load_bucket(bucket)
        self._cred_panel.load(bucket, self.rustfs.api_url())

    # ── Server controls ───────────────────────────────────────────────────────

    def _start(self):
        if not self.rustfs.is_binaries_available():
            QMessageBox.information(self, "Setup Required",
                "Click '⚙ Setup' first to download the RustFS binary.")
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.endpoint_lbl.setText("Starting…")

        def fn(_prog):
            return self.rustfs.start()

        def done(ok, msg):
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self._update_status()
            if ok:
                self._sidebar.load()
            else:
                QMessageBox.critical(
                    self, "RustFS Failed to Start",
                    f"{msg}\n\nCheck the log file for details."
                )

        self._run(fn, done)

    def _stop(self):
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(False)

        def fn(_prog):
            return self.rustfs.stop()

        def done(ok, msg):
            self.btn_stop.setEnabled(True)
            self.btn_start.setEnabled(True)
            self._update_status()
            if not ok:
                QMessageBox.warning(self, "Stop Warning", msg)

        self._run(fn, done)

    def _setup(self):
        self.prog.setVisible(True)
        self.prog.setValue(0)
        self.btn_setup.setEnabled(False)

        def fn(prog_cb):
            return self.rustfs.setup_binaries(progress_callback=prog_cb)

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
        import webbrowser, socket as _socket
        if not self.rustfs.is_running():
            QMessageBox.information(self, "Storage Not Running",
                "Start RustFS first.")
            return
        caddy_port = self.rustfs.https_port
        caddy_up = False
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(1)
            caddy_up = s.connect_ex(("127.0.0.1", caddy_port)) == 0
            s.close()
        except Exception:
            pass
        if caddy_up:
            url = self.rustfs.console_url()
        else:
            url = f"http://127.0.0.1:{self.rustfs.console_port}"
        webbrowser.open(url)

    def _update_status(self):
        running  = self.rustfs.is_running()
        binaries = self.rustfs.is_binaries_available()

        if running:
            self.server_badge.setText("● RUNNING")
            self.server_badge.setStyleSheet(
                f"color:{C_GREEN};font-size:11px;background:transparent;"
            )
            self.endpoint_lbl.setText(
                f"API: {self.rustfs.api_url()}    Console: {self.rustfs.console_url()}"
            )
            self.btn_setup.setVisible(False)
        else:
            self.server_badge.setText("● STOPPED")
            self.server_badge.setStyleSheet(
                f"color:{C_RED};font-size:11px;background:transparent;"
            )
            self.endpoint_lbl.setText("Start storage to connect")
            self.btn_setup.setVisible(not binaries)

    # ── Bucket operations ─────────────────────────────────────────────────────

    def _create_bucket(self):
        if not self.rustfs.is_running():
            QMessageBox.warning(self, "Storage Not Running",
                "Start RustFS first.")
            return
        dlg = CreateBucketDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        bucket_name, app_name, is_public = dlg.values()
        endpoint = self.rustfs.api_url()

        from core.bucket_manager import create_bucket
        ok, msg, creds = create_bucket(bucket_name, app_name, is_public)
        if not ok:
            QMessageBox.critical(self, "Error", msg)
            return

        self._sidebar.load()
        CredentialsDialog(creds, endpoint, self).exec()

    def _drop_bucket(self, name: str):
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

        def done(ok, msg):
            if ok:
                self._sidebar.load()
                QMessageBox.information(self, "Done", msg)
            else:
                QMessageBox.critical(self, "Error", msg)

        self._run(fn, done)

    def _rotate_keys(self, bucket: str, old_ak: str):
        reply = QMessageBox.question(
            self, "Rotate Keys",
            f"Generate new access key and secret for '{bucket}'?\n\n"
            "The old credentials will stop working immediately.\n"
            "Update your .env files after rotating.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from core.bucket_manager import rotate_keys
        ok, msg, new_creds = rotate_keys(bucket, old_ak)
        if ok:
            self._cred_panel.load(bucket, self.rustfs.api_url())
            CredentialsDialog(new_creds, self.rustfs.api_url(), self).exec()
        else:
            QMessageBox.critical(self, "Error", msg)

    def _backup_bucket(self, name: str):
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

    # ── Object operations ─────────────────────────────────────────────────────

    def _upload(self, bucket: str, prefix: str):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Files to Upload")
        if not paths:
            return
        self.prog.setVisible(True)
        self.prog.setValue(0)
        total = len(paths)
        done_count = [0]
        errors     = []

        def _upload_one(path_str, idx):
            fpath = Path(path_str)
            key   = prefix + fpath.name

            def fn(prog_cb):
                from core.bucket_manager import upload_object
                return upload_object(bucket, key, fpath,
                                     progress_callback=prog_cb)

            def on_done(ok, msg):
                done_count[0] += 1
                if not ok:
                    errors.append(fpath.name)
                pct = int(done_count[0] / total * 100)
                self.prog.setValue(pct)
                if done_count[0] == total:
                    self.prog.setVisible(False)
                    self._browser.refresh()
                    if errors:
                        QMessageBox.warning(self, "Upload Partial",
                            f"{len(errors)} file(s) failed:\n" +
                            "\n".join(errors))

            w = self._run(fn, on_done)
            w.progress.connect(
                lambda p: self.prog.setValue(
                    int(((done_count[0] - 1) / total + p / 100 / total) * 100)
                )
            )

        for i, p in enumerate(paths):
            _upload_one(p, i)

    def _download(self, bucket: str, key: str):
        fname = Path(key).name
        dest, _ = QFileDialog.getSaveFileName(self, "Save File As", fname)
        if not dest:
            return
        self.prog.setVisible(True)
        self.prog.setValue(0)

        def fn(prog_cb):
            from core.bucket_manager import download_object
            return download_object(bucket, key, Path(dest),
                                   progress_callback=prog_cb)

        def done(ok, msg):
            self.prog.setVisible(False)
            if ok:
                QMessageBox.information(self, "Download Complete", msg)
            else:
                QMessageBox.critical(self, "Download Failed", msg)

        w = self._run(fn, done)
        w.progress.connect(self.prog.setValue)

    def _delete_objects(self, bucket: str, keys: list):
        self.prog.setVisible(True)
        self.prog.setValue(0)

        def fn(prog_cb):
            from core.bucket_manager import delete_objects, delete_prefix
            plain_keys = [k for k in keys if not k.endswith("/")]
            prefixes   = [k for k in keys if k.endswith("/")]
            errors = []
            total  = len(plain_keys) + len(prefixes)
            done   = 0

            if plain_keys:
                ok, msg = delete_objects(bucket, plain_keys)
                if not ok:
                    errors.append(msg)
                done += len(plain_keys)
                prog_cb(int(done / total * 100))

            for pfx in prefixes:
                ok, msg = delete_prefix(bucket, pfx)
                if not ok:
                    errors.append(msg)
                done += 1
                prog_cb(int(done / total * 100))

            if errors:
                return False, "; ".join(errors)
            return True, f"Deleted {total} item(s)."

        def done(ok, msg):
            self.prog.setVisible(False)
            self._browser.refresh()
            if not ok:
                QMessageBox.critical(self, "Delete Error", msg)

        w = self._run(fn, done)
        w.progress.connect(self.prog.setValue)

    def _copy_url(self, bucket: str, key: str):
        from core.bucket_manager import get_object_url
        url = get_object_url(bucket, key, expires_in=3600)
        QApplication.clipboard().setText(url)
        QMessageBox.information(
            self, "Presigned URL Copied",
            f"URL copied to clipboard.\n\nValid for 1 hour.\n\n{url[:80]}…"
            if len(url) > 80 else f"URL copied to clipboard.\n\n{url}"
        )

    def _new_folder(self, bucket: str, prefix: str):
        name, ok = QInputDialog.getText(
            self, "New Folder",
            f"Folder name inside  {bucket}/{prefix}:",
            QLineEdit.EchoMode.Normal, ""
        )
        if not ok or not name.strip():
            return
        name = name.strip().strip("/")
        if "/" in name or "\\" in name:
            QMessageBox.warning(self, "Invalid Name",
                "Folder name cannot contain slashes.")
            return
        from core.bucket_manager import create_folder
        full_prefix = prefix + name
        s_ok, msg = create_folder(bucket, full_prefix)
        if s_ok:
            self._browser.refresh()
        else:
            QMessageBox.critical(self, "Error", msg)

    # ── Worker helper ─────────────────────────────────────────────────────────

    def _run(self, fn, on_done) -> Worker:
        w = Worker(fn)
        w.done.connect(on_done)
        w.start()
        self._workers.append(w)
        self._workers = [x for x in self._workers if x.isRunning()]
        return w