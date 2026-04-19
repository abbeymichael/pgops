from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QWidget, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QKeyEvent, QColor, QFont, QPixmap, QPainter, QPen, QBrush, QLinearGradient

from core.auth import verify_password, set_password, reset_password, is_password_set


# ── Palette ────────────────────────────────────────────────────────────────────
BG          = "#10121a"
PANEL_BG    = "#161b2e"
PANEL_BORDER= "#1e2640"
INPUT_BG    = "#0d1117"
INPUT_BORDER= "#252d42"
INPUT_FOCUS = "#4f5fde"
ACCENT      = "#4f5fde"
ACCENT2     = "#7b8af5"
TEXT        = "#e8eaf6"
MUTED       = "#5a6380"
SUBTLE      = "#2a3352"
DANGER      = "#e05a5a"
SUCCESS     = "#4caf88"
MONO        = "Consolas, 'Courier New', monospace"

GLOBAL_STYLE = f"""
QDialog, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
}}
QLabel {{ background: transparent; }}
QLineEdit {{
    background: {INPUT_BG};
    border: 1px solid {INPUT_BORDER};
    border-radius: 6px;
    padding: 11px 14px;
    color: {TEXT};
    font-size: 13px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {INPUT_FOCUS};
    background: #0f1520;
}}
QLineEdit::placeholder {{
    color: {MUTED};
}}
"""

# ── Reusable helpers ───────────────────────────────────────────────────────────

def _shadow(radius=24, color="#000000", alpha=120):
    s = QGraphicsDropShadowEffect()
    c = QColor(color)
    c.setAlpha(alpha)
    s.setColor(c)
    s.setBlurRadius(radius)
    s.setOffset(0, 4)
    return s


def _gradient_btn(text: str, h: int = 44) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT}, stop:1 {ACCENT2});
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.4px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #5a6af0, stop:1 #8c9bff);
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3d4fcc, stop:1 #6a7af0);
        }}
        QPushButton:disabled {{
            background: {SUBTLE};
            color: {MUTED};
        }}
    """)
    return b


def _ghost_btn(text: str, h: int = 38) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {MUTED};
            border: 1px solid {SUBTLE};
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }}
        QPushButton:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
        QPushButton:pressed {{ background: {SUBTLE}; }}
    """)
    return b


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {PANEL_BORDER}; border: none;")
    return line


def _tag(text: str, color: str = ACCENT) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {color};
        background: transparent;
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 2.5px;
    """)
    return lbl


def _icon_box(icon: str, size: int = 48) -> QLabel:
    lbl = QLabel(icon)
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(f"""
        background: {SUBTLE};
        border-radius: 12px;
        color: {ACCENT2};
        font-size: {size // 2}px;
    """)
    return lbl


def _hint_box(text: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet(f"""
        QWidget {{
            background: {INPUT_BG};
            border: 1px solid {SUBTLE};
            border-radius: 6px;
        }}
    """)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(10)

    bullet = QLabel("ℹ")
    bullet.setStyleSheet(f"color: {ACCENT2}; font-size: 14px;")
    lay.addWidget(bullet, 0, Qt.AlignmentFlag.AlignTop)

    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; line-height: 160%;")
    lay.addWidget(lbl)
    return w


def _status_bar(left: str = "SYSTEM READY", right: str = "PGOPS TECHNOLOGIES") -> QWidget:
    bar = QWidget()
    bar.setFixedHeight(28)
    bar.setStyleSheet(f"background: {BG}; border-top: 1px solid {PANEL_BORDER};")
    row = QHBoxLayout(bar)
    row.setContentsMargins(16, 0, 16, 0)

    dot = QLabel("●")
    dot.setStyleSheet(f"color: {SUCCESS}; font-size: 8px; background: transparent;")
    row.addWidget(dot)

    ll = QLabel(left)
    ll.setStyleSheet(f"color: {MUTED}; font-size: 9px; letter-spacing: 1.5px; background: transparent;")
    row.addWidget(ll)

    # node label
    node = QLabel("NODE: PG0-ALPHA-01")
    node.setStyleSheet(f"color: {MUTED}; font-size: 9px; letter-spacing: 1.5px; background: transparent;")
    row.addWidget(node)

    row.addStretch()

    rr = QLabel(right)
    rr.setStyleSheet(f"color: {MUTED}; font-size: 9px; letter-spacing: 1.5px; background: transparent;")
    row.addWidget(rr)
    return bar


# ── Eye toggle helper ──────────────────────────────────────────────────────────

def _add_eye_toggle(field: QLineEdit, layout_owner: QWidget) -> None:
    """Wrap field to add show/hide password eye icon."""
    field._visible = False
    eye = QPushButton("👁")
    eye.setFixedSize(34, 34)
    eye.setCursor(Qt.CursorShape.PointingHandCursor)
    eye.setStyleSheet(f"""
        QPushButton {{
            background: transparent; border: none;
            color: {MUTED}; font-size: 14px;
        }}
        QPushButton:hover {{ color: {TEXT}; }}
    """)
    # We attach the button as a right-action overlay using a wrapper widget
    field._eye_btn = eye

    def _toggle():
        field._visible = not field._visible
        field.setEchoMode(
            QLineEdit.EchoMode.Normal if field._visible else QLineEdit.EchoMode.Password
        )

    eye.clicked.connect(_toggle)


class EyeLineEdit(QWidget):
    """QLineEdit with an embedded eye-toggle button."""
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.field = QLineEdit()
        self.field.setPlaceholderText(placeholder)
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(self.field)

        self._eye = QPushButton("👁")
        self._eye.setFixedSize(38, 44)
        self._eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye.setStyleSheet(f"""
            QPushButton {{
                background: {INPUT_BG};
                border: 1px solid {INPUT_BORDER};
                border-left: none;
                border-radius: 0 6px 6px 0;
                color: {MUTED};
                font-size: 14px;
            }}
            QPushButton:hover {{ color: {TEXT}; border-color: {INPUT_FOCUS}; }}
        """)
        self._visible = False
        self._eye.clicked.connect(self._toggle)
        row.addWidget(self._eye)

        # Remove right-radius from field to merge with eye
        self.field.setStyleSheet(f"""
            QLineEdit {{
                background: {INPUT_BG};
                border: 1px solid {INPUT_BORDER};
                border-right: none;
                border-radius: 6px 0 0 6px;
                padding: 11px 14px;
                color: {TEXT};
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {INPUT_FOCUS};
                background: #0f1520;
            }}
        """)

    def _toggle(self):
        self._visible = not self._visible
        self.field.setEchoMode(
            QLineEdit.EchoMode.Normal if self._visible else QLineEdit.EchoMode.Password
        )

    # Proxy useful QLineEdit properties
    @property
    def text(self): return self.field.text
    @property
    def returnPressed(self): return self.field.returnPressed
    @property
    def textChanged(self): return self.field.textChanged
    def setFocus(self): self.field.setFocus()
    def clear(self): self.field.clear()


# ── Forgot Password dropdown ───────────────────────────────────────────────────

class ForgotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.toggle_btn = QPushButton("Forgot Password?  ▾")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {MUTED};
                border: none;
                font-size: 11px;
                text-align: center;
                padding: 4px;
            }}
            QPushButton:hover {{ color: {TEXT}; }}
        """)
        self.toggle_btn.clicked.connect(self._toggle)
        lay.addWidget(self.toggle_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self.detail = QWidget()
        self.detail.setVisible(False)
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(0, 8, 0, 0)
        hint = QLabel(
            "<b style='color:#e8eaf6'>Hint:</b>  Check your configuration file at:<br>"
            f"<span style='color:{ACCENT2}; font-family:{MONO}'>~/.pgops/orchestrator.yaml</span>"
        )
        hint.setStyleSheet(f"""
            background: {INPUT_BG};
            border: 1px solid {SUBTLE};
            border-radius: 6px;
            color: {MUTED};
            font-size: 11px;
            padding: 10px 14px;
        """)
        hint.setWordWrap(True)
        dl.addWidget(hint)
        lay.addWidget(self.detail)

    def _toggle(self):
        self._expanded = not self._expanded
        self.detail.setVisible(self._expanded)
        self.toggle_btn.setText(
            "Forgot Password?  ▴" if self._expanded else "Forgot Password?  ▾"
        )


# ── Panel widget ───────────────────────────────────────────────────────────────

class _Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {PANEL_BG};
                border: 1px solid {PANEL_BORDER};
                border-radius: 10px;
            }}
        """)
        self.setGraphicsEffect(_shadow(32))


# ═══════════════════════════════════════════════════════════════════════════════
# LOGIN DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGOps")
        self.setFixedSize(460, 580)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.CustomizeWindowHint
        )
        self.setStyleSheet(GLOBAL_STYLE)
        self._attempts = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Main content area ──
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(36, 36, 36, 28)
        cl.setSpacing(0)

        # Logo row
        icon = _icon_box("⊞", 52)
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon)
        icon_row.addStretch()
        cl.addLayout(icon_row)
        cl.addSpacing(16)

        app_title = QLabel("PGOps")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_title.setStyleSheet(
            f"color: {TEXT}; font-size: 26px; font-weight: 700; letter-spacing: 1px;"
        )
        cl.addWidget(app_title)

        ver = _tag("V1.2.0 ORCHESTRATOR")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(ver)
        cl.addSpacing(28)

        # Panel
        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(28, 24, 28, 24)
        pl.setSpacing(0)

        heading = QLabel("Access Command Console")
        heading.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        pl.addWidget(heading)
        pl.addSpacing(6)

        sub = QLabel("Enter your master application password to unlock the orchestration interface.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {MUTED}; font-size: 12px; line-height: 150%;")
        pl.addWidget(sub)
        pl.addSpacing(20)
        pl.addWidget(_divider())
        pl.addSpacing(20)

        # Field label
        lbl_pw = _tag("APP PASSWORD")
        pl.addWidget(lbl_pw)
        pl.addSpacing(6)

        self.pw_eye = EyeLineEdit("• • • • • • • •")
        self.pw_eye.returnPressed.connect(self._login)
        pl.addWidget(self.pw_eye)
        pl.addSpacing(10)

        # Error label
        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(f"color: {DANGER}; font-size: 11px;")
        self.error_lbl.setVisible(False)
        pl.addWidget(self.error_lbl)
        pl.addSpacing(6)

        self.btn_login = _gradient_btn("Login")
        pl.addWidget(self.btn_login)
        self.btn_login.clicked.connect(self._login)

        pl.addSpacing(16)
        pl.addWidget(ForgotWidget())

        cl.addWidget(panel)
        cl.addStretch()

        root.addWidget(content, 1)
        root.addWidget(_status_bar())

        self.pw_eye.setFocus()

    def _login(self):
        pw = self.pw_eye.text()
        if not pw:
            self._show_error("Please enter your password.")
            return

        if verify_password(pw):
            self.accept()
        else:
            self._attempts += 1
            self.pw_eye.clear()
            self.pw_eye.setFocus()

            if self._attempts >= 5:
                self._show_error(
                    f"Incorrect password ({self._attempts} attempts). "
                    "Use 'Forgot Password?' to reset."
                )
            else:
                remaining = 5 - self._attempts
                self._show_error(
                    f"Incorrect password. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
                )
            self._shake()

    def _show_error(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)

    def _shake(self):
        orig = self.x()
        for i, offset in enumerate([6, -6, 4, -4, 2, -2, 0]):
            QTimer.singleShot(i * 40, lambda x=orig + offset: self.move(x, self.y()))


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP PASSWORD DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class SetupPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGOps Orchestrator — Initial Configuration")
        self.setFixedSize(480, 620)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.CustomizeWindowHint
        )
        self.setStyleSheet(GLOBAL_STYLE)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(36, 36, 36, 28)
        cl.setSpacing(0)

        # Logo + titles
        icon = _icon_box("🛡", 52)
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon)
        icon_row.addStretch()
        cl.addLayout(icon_row)
        cl.addSpacing(14)

        app_title = QLabel("PGOps Orchestrator")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_title.setStyleSheet(
            f"color: {TEXT}; font-size: 24px; font-weight: 700;"
        )
        cl.addWidget(app_title)

        init_tag = _tag("INITIAL CONFIGURATION", ACCENT2)
        init_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(init_tag)
        cl.addSpacing(24)

        # Panel
        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(28, 24, 28, 24)
        pl.setSpacing(0)

        heading = QLabel("Secure the Console")
        heading.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        pl.addWidget(heading)
        pl.addSpacing(6)

        sub = QLabel(
            "Define a local password to protect your orchestration layer. "
            "This is stored locally on this machine."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        pl.addWidget(sub)
        pl.addSpacing(20)
        pl.addWidget(_divider())
        pl.addSpacing(20)

        # Field label row (with hint)
        lbl_row = QHBoxLayout()
        lbl_row.addWidget(_tag("CREATE APP PASSWORD"))
        lbl_row.addStretch()
        min_hint = QLabel("Min 4 characters")
        min_hint.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        lbl_row.addWidget(min_hint)
        pl.addLayout(lbl_row)
        pl.addSpacing(6)

        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw1.setPlaceholderText("New Password")
        pl.addWidget(self.pw1)
        pl.addSpacing(8)

        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2.setPlaceholderText("Confirm Password")
        self.pw2.returnPressed.connect(self._save)
        pl.addWidget(self.pw2)
        pl.addSpacing(8)

        # Strength
        self.strength_lbl = QLabel("")
        self.strength_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        pl.addWidget(self.strength_lbl)
        self.pw1.textChanged.connect(self._check_strength)
        pl.addSpacing(6)

        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(f"color: {DANGER}; font-size: 11px;")
        self.error_lbl.setVisible(False)
        pl.addWidget(self.error_lbl)
        pl.addSpacing(10)

        btn_init = _gradient_btn("Initialize PGOps")
        btn_init.clicked.connect(self._save)
        pl.addWidget(btn_init)
        pl.addSpacing(16)

        hint_box = _hint_box(
            "PGOps uses this password to protect your <b style='color:#e8eaf6'>server "
            "interface</b>, not your database data. Database credentials "
            "remain managed via your encrypted Vault."
        )
        pl.addWidget(hint_box)

        cl.addWidget(panel)
        cl.addStretch()

        root.addWidget(content, 1)
        root.addWidget(_status_bar("SYSTEM READY", "PGOPS TECHNOLOGIES"))

        self.pw1.setFocus()

    def _check_strength(self, pw: str):
        if not pw:
            self.strength_lbl.setText("")
            return
        score = 0
        if len(pw) >= 8:  score += 1
        if len(pw) >= 12: score += 1
        if any(c.isupper() for c in pw): score += 1
        if any(c.isdigit() for c in pw): score += 1
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in pw): score += 1

        for threshold, label, color in [
            (1, "Weak",   DANGER),
            (2, "Fair",   "#f59e0b"),
            (3, "Good",   ACCENT),
            (5, "Strong", SUCCESS),
        ]:
            if score <= threshold:
                self.strength_lbl.setText(f"Strength: {label}")
                self.strength_lbl.setStyleSheet(
                    f"color:{color};font-size:11px;"
                )
                return
        self.strength_lbl.setText("Strength: Strong")
        self.strength_lbl.setStyleSheet(f"color:{SUCCESS};font-size:11px;")

    def _save(self):
        pw1 = self.pw1.text()
        pw2 = self.pw2.text()
        if not pw1:
            self._err("Please choose a password.")
            return
        if len(pw1) < 4:
            self._err("Password must be at least 4 characters.")
            return
        if pw1 != pw2:
            self._err("Passwords do not match.")
            self.pw2.clear()
            self.pw2.setFocus()
            return
        ok, msg = set_password(pw1)
        if ok:
            self.accept()
        else:
            self._err(msg)

    def _err(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)


# ═══════════════════════════════════════════════════════════════════════════════
# CHANGE PASSWORD DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Master Password")
        self.setFixedSize(440, 400)
        self.setStyleSheet(GLOBAL_STYLE)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 32, 32, 24)
        cl.setSpacing(0)

        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(28, 24, 28, 24)
        pl.setSpacing(0)

        heading = QLabel("Change Master Password")
        heading.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        pl.addWidget(heading)
        pl.addSpacing(16)
        pl.addWidget(_divider())
        pl.addSpacing(16)

        for attr, placeholder in [
            ("current_pw", "Current password"),
            ("new_pw1",    "New password (min 4 characters)"),
            ("new_pw2",    "Confirm new password"),
        ]:
            f = QLineEdit()
            f.setEchoMode(QLineEdit.EchoMode.Password)
            f.setPlaceholderText(placeholder)
            setattr(self, attr, f)
            pl.addWidget(f)
            pl.addSpacing(8)

        self.new_pw2.returnPressed.connect(self._save)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(f"color: {DANGER}; font-size: 11px;")
        self.error_lbl.setVisible(False)
        pl.addWidget(self.error_lbl)
        pl.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_cancel = _ghost_btn("Cancel")
        btn_save   = _gradient_btn("Change Password", h=38)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(10)
        btn_row.addWidget(btn_save)
        pl.addLayout(btn_row)

        cl.addWidget(panel)
        cl.addStretch()
        root.addWidget(content, 1)
        root.addWidget(_status_bar())

        self.current_pw.setFocus()

    def _save(self):
        cur  = self.current_pw.text()
        new1 = self.new_pw1.text()
        new2 = self.new_pw2.text()

        if not verify_password(cur):
            self._err("Current password is incorrect.")
            self.current_pw.clear()
            self.current_pw.setFocus()
            return
        if len(new1) < 4:
            self._err("New password must be at least 4 characters.")
            return
        if new1 != new2:
            self._err("New passwords do not match.")
            self.new_pw2.clear()
            self.new_pw2.setFocus()
            return

        ok, msg = set_password(new1)
        if ok:
            self.accept()
        else:
            self._err(msg)

    def _err(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)