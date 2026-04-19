"""
login_dialog.py
Login screen shown on every launch.
Setup screen shown on first launch to create the master password.

Palette remapped to match app-wide theme tokens:
  C_BG / C_SURFACE / C_SURFACE2 / C_BORDER / C_BORDER2
  C_TEXT / C_TEXT2 / C_TEXT3
  C_BLUE / C_GREEN / C_RED / C_AMBER
  Font: 'Segoe UI', -apple-system, sans-serif  (matches APP_STYLE)

Behaviour:
  - ForgotPasswordDialog slides in-place as an overlay (no new window)
  - All plain text labels are flat — no border, no background box
  - _hint_box is a left accent bar + indented text only
  - _BgWidget paints a subtle radial glow + fine grid using app colours
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QRadialGradient

from core.auth import verify_password, set_password, reset_password, is_password_set


# ── Palette — mirrors app-wide theme tokens ────────────────────────────────────
BG           = "#141518"   # C_BG
PANEL_BG     = "#1e2128"   # C_SURFACE
PANEL_BG2    = "#252830"   # C_SURFACE2
PANEL_BORDER = "#2a2d35"   # C_BORDER
BORDER2      = "#32363f"   # C_BORDER2
INPUT_BG     = "#1e2128"   # C_SURFACE  (inputs sit on surface)
INPUT_BORDER = "#2a2d35"   # C_BORDER
INPUT_FOCUS  = "#4f8ef7"   # C_BLUE
ACCENT       = "#4f8ef7"   # C_BLUE
TEXT         = "#e8eaf0"   # C_TEXT
MUTED        = "#9499a8"   # C_TEXT2
SUBTLE       = "#555b6e"   # C_TEXT3
DANGER       = "#e74c3c"   # C_RED
SUCCESS      = "#2ecc71"   # C_GREEN
WARN         = "#f39c12"   # C_AMBER

GLOBAL_STYLE = f"""
QDialog, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Segoe UI', -apple-system, sans-serif;
    font-size: 12px;
}}
QLabel {{ background: transparent; border: none; }}
QLineEdit {{
    background: {INPUT_BG};
    border: 1px solid {INPUT_BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    color: {TEXT};
    font-family: 'Segoe UI', -apple-system, sans-serif;
    font-size: 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {INPUT_FOCUS};
    background: {PANEL_BG2};
}}
"""


# ── Background: subtle radial glow + fine grid ────────────────────────────────
class _BgWidget(QWidget):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor(BG))

        # Soft blue radial glow — very low opacity to stay subtle on this palette
        grad = QRadialGradient(w / 2, 0, w * 0.55)
        glow = QColor(ACCENT)
        glow.setAlpha(18)
        grad.setColorAt(0, glow)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(grad))

        # Fine grid using border colour
        grid_col = QColor(PANEL_BORDER)
        grid_col.setAlpha(50)
        pen = QPen(grid_col)
        pen.setWidth(1)
        p.setPen(pen)
        step = 36
        for x in range(0, w + step, step):
            p.drawLine(x, 0, x, h)
        for y in range(0, h + step, step):
            p.drawLine(0, y, w, y)

        p.end()


# ── Drop shadow ────────────────────────────────────────────────────────────────
def _shadow(radius=20, alpha=80):
    s = QGraphicsDropShadowEffect()
    c = QColor("#000000")
    c.setAlpha(alpha)
    s.setColor(c)
    s.setBlurRadius(radius)
    s.setOffset(0, 4)
    return s


# ── Primary button ─────────────────────────────────────────────────────────────
def _gradient_btn(text: str, h: int = 40) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2d6be4, stop:1 {ACCENT});
            color: #ffffff;
            border: none;
            border-radius: 6px;
            font-family: 'Segoe UI', -apple-system, sans-serif;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3a78f0, stop:1 #6aaaf9);
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #1f55c4, stop:1 #2d6be4);
        }}
        QPushButton:disabled {{
            background: {PANEL_BG2};
            color: {SUBTLE};
        }}
    """)
    return b


# ── Ghost button ───────────────────────────────────────────────────────────────
def _ghost_btn(text: str, h: int = 36) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {MUTED};
            border: 1px solid {PANEL_BORDER};
            border-radius: 6px;
            font-family: 'Segoe UI', -apple-system, sans-serif;
            font-size: 11px;
            letter-spacing: 0.5px;
        }}
        QPushButton:hover {{
            color: {TEXT};
            border-color: {ACCENT};
        }}
        QPushButton:pressed {{
            background: {PANEL_BG2};
        }}
    """)
    return b


# ── Divider ────────────────────────────────────────────────────────────────────
def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {PANEL_BORDER}; border: none;")
    return line


# ── Flat uppercase tag label ───────────────────────────────────────────────────
def _tag(text: str, color: str = ACCENT) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color}; background: transparent; border: none; "
        f"font-size: 9px; font-weight: 700; letter-spacing: 2px;"
    )
    return lbl


# ── Section heading: left accent bar + uppercase label ────────────────────────
def _section_tag(text: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    bar = QFrame()
    bar.setFixedSize(3, 11)
    bar.setStyleSheet(f"background: {ACCENT}; border-radius: 2px; border: none;")
    row.addWidget(bar, 0, Qt.AlignmentFlag.AlignVCenter)

    lbl = _tag(text)
    row.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addStretch()
    return w


# ── Flat hint block: left accent line + muted text ────────────────────────────
def _hint_box(text: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    bar = QFrame()
    bar.setFixedWidth(2)
    bar.setStyleSheet(f"background: {ACCENT}; border-radius: 1px; border: none;")
    row.addWidget(bar)

    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color: {MUTED}; font-size: 10px; line-height: 160%; "
        f"background: transparent; border: none;"
    )
    row.addWidget(lbl)
    return w


# ── Status bar ─────────────────────────────────────────────────────────────────
def _status_bar(node: str = "PG0-ALPHA-01") -> QWidget:
    bar = QWidget()
    bar.setFixedHeight(26)
    bar.setStyleSheet(f"background: {BG}; border-top: 1px solid {PANEL_BORDER};")
    row = QHBoxLayout(bar)
    row.setContentsMargins(16, 0, 16, 0)
    row.setSpacing(8)

    dot = QLabel("●")
    dot.setStyleSheet(f"color: {SUCCESS}; font-size: 7px; background: transparent; border: none;")
    row.addWidget(dot)

    status = QLabel("SYSTEM READY")
    status.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1.5px; background: transparent; border: none;")
    row.addWidget(status)

    sep = QLabel("·")
    sep.setStyleSheet(f"color: {PANEL_BORDER}; font-size: 9px; background: transparent; border: none;")
    row.addWidget(sep)

    node_lbl = QLabel(f"NODE: {node}")
    node_lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1.5px; background: transparent; border: none;")
    row.addWidget(node_lbl)

    row.addStretch()

    right = QLabel("PGOPS TECHNOLOGIES")
    right.setStyleSheet(f"color: {PANEL_BORDER}; font-size: 9px; letter-spacing: 1.5px; background: transparent; border: none;")
    row.addWidget(right)
    return bar


# ── Panel card ─────────────────────────────────────────────────────────────────
class _Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {PANEL_BG};
                border: 1px solid {PANEL_BORDER};
                border-radius: 8px;
            }}
        """)
        self.setGraphicsEffect(_shadow())


# ── Eye-toggle password field ──────────────────────────────────────────────────
class EyeLineEdit(QWidget):
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.field = QLineEdit()
        self.field.setPlaceholderText(placeholder)
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setStyleSheet(f"""
            QLineEdit {{
                background: {INPUT_BG};
                border: 1px solid {INPUT_BORDER};
                border-right: none;
                border-radius: 6px 0 0 6px;
                padding: 8px 12px;
                color: {TEXT};
                font-family: 'Segoe UI', -apple-system, sans-serif;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {INPUT_FOCUS};
                background: {PANEL_BG2};
            }}
        """)
        row.addWidget(self.field)

        self._eye = QPushButton("○")
        self._eye.setFixedSize(34, 40)
        self._eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye.setStyleSheet(f"""
            QPushButton {{
                background: {INPUT_BG};
                border: 1px solid {INPUT_BORDER};
                border-left: none;
                border-radius: 0 6px 6px 0;
                color: {MUTED};
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {TEXT};
                border-color: {INPUT_FOCUS};
            }}
        """)
        self._visible = False
        self._eye.clicked.connect(self._toggle)
        row.addWidget(self._eye)

    def _toggle(self):
        self._visible = not self._visible
        self.field.setEchoMode(
            QLineEdit.EchoMode.Normal if self._visible else QLineEdit.EchoMode.Password
        )
        self._eye.setText("●" if self._visible else "○")

    @property
    def text(self): return self.field.text
    @property
    def returnPressed(self): return self.field.returnPressed
    @property
    def textChanged(self): return self.field.textChanged
    def setFocus(self): self.field.setFocus()
    def clear(self): self.field.clear()


# ── Password strength bar ──────────────────────────────────────────────────────
class StrengthBar(QWidget):
    COLORS = {0: BG, 1: DANGER, 2: WARN, 3: ACCENT, 4: SUCCESS}
    LABELS = {0: "", 1: "WEAK", 2: "FAIR", 3: "GOOD", 4: "STRONG"}

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._bars = []
        for _ in range(4):
            seg = QFrame()
            seg.setFixedHeight(3)
            seg.setStyleSheet(f"background: {BORDER2}; border-radius: 2px; border: none;")
            lay.addWidget(seg)
            self._bars.append(seg)

        self._label = QLabel("")
        self._label.setFixedWidth(46)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._label.setStyleSheet(f"color: {MUTED}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        lay.addWidget(self._label)

    def set_score(self, score: int):
        score = max(0, min(4, score))
        color = self.COLORS.get(score, BORDER2)
        for i, bar in enumerate(self._bars):
            bar.setStyleSheet(
                f"background: {color if i < score else BORDER2}; border-radius: 2px; border: none;"
            )
        self._label.setText(self.LABELS.get(score, ""))
        self._label.setStyleSheet(f"color: {color}; font-size: 9px; letter-spacing: 1.5px; border: none;")


# ═══════════════════════════════════════════════════════════════════════════════
# FORGOT PASSWORD — inline sliding overlay (stays inside LoginDialog window)
# ═══════════════════════════════════════════════════════════════════════════════

class _ForgotOverlay(QWidget):
    """Slides in from the right over the login content. Not a separate dialog."""

    def __init__(self, parent: QWidget, on_back):
        super().__init__(parent)
        self.on_back = on_back
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {BG};")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        topbar = QWidget()
        topbar.setStyleSheet("background: transparent;")
        tb_row = QHBoxLayout(topbar)
        tb_row.setContentsMargins(20, 10, 20, 0)

        status_lbl = QLabel("● SYSTEM READY")
        status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        tb_row.addWidget(status_lbl)
        tb_row.addStretch()

        badge = QLabel("PASSWORD RECOVERY")
        badge.setStyleSheet(f"color: {WARN}; font-size: 9px; letter-spacing: 1.5px; border: none; background: transparent;")
        tb_row.addWidget(badge)
        tb_row.addStretch()

        node_lbl = QLabel("NODE: PG0-ALPHA-01")
        node_lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        tb_row.addWidget(node_lbl)
        root.addWidget(topbar)

        # Content
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(36, 20, 36, 16)
        cl.setSpacing(0)

        icon_lbl = QLabel("⚠")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"color: {WARN}; font-size: 28px; background: transparent; border: none;")
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon_lbl)
        icon_row.addStretch()
        cl.addLayout(icon_row)
        cl.addSpacing(10)

        title = QLabel("Reset Password")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {TEXT}; font-size: 20px; font-weight: 700; border: none;")
        cl.addWidget(title)

        sub_tag = _tag("ACCOUNT RECOVERY", WARN)
        sub_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(sub_tag)
        cl.addSpacing(16)

        # Panel
        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(26, 20, 26, 20)
        pl.setSpacing(0)

        pl.addWidget(_section_tag("RECOVERY STEPS"))
        pl.addSpacing(10)

        intro = QLabel(
            "The master password cannot be recovered. Delete the local auth file "
            "and relaunch PGOps to set a new one."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {MUTED}; font-size: 11px; line-height: 160%; border: none;")
        pl.addWidget(intro)
        pl.addSpacing(14)
        pl.addWidget(_divider())
        pl.addSpacing(14)

        for num, text in [
            ("01", "Close this dialog and quit PGOps completely."),
            ("02", "Delete the auth file for your operating system:"),
            ("03", "Relaunch PGOps — you will be prompted to set a new password."),
        ]:
            step_row = QHBoxLayout()
            step_row.setSpacing(10)

            num_lbl = QLabel(num)
            num_lbl.setFixedWidth(24)
            num_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            num_lbl.setStyleSheet(
                f"color: {ACCENT}; font-size: 10px; font-weight: 700; "
                f"background: transparent; border: none; padding-top: 2px;"
            )
            step_row.addWidget(num_lbl)

            text_lbl = QLabel(text)
            text_lbl.setWordWrap(True)
            text_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px; line-height: 155%; border: none;")
            step_row.addWidget(text_lbl, 1)
            pl.addLayout(step_row)
            pl.addSpacing(8)

            if num == "02":
                for platform, path in [
                    ("Windows", "%LOCALAPPDATA%\\PGOps\\auth.json"),
                    ("macOS",   "~/Library/Application Support/PGOps/auth.json"),
                    ("Linux",   "~/.config/PGOps/auth.json"),
                ]:
                    pw = QWidget()
                    pw.setStyleSheet(f"background: {PANEL_BG2}; border: none; border-radius: 4px;")
                    pw_row = QHBoxLayout(pw)
                    pw_row.setContentsMargins(12, 6, 12, 6)
                    pw_row.setSpacing(12)

                    plat_lbl = QLabel(platform)
                    plat_lbl.setFixedWidth(52)
                    plat_lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1px; border: none;")
                    pw_row.addWidget(plat_lbl)

                    path_lbl = QLabel(path)
                    path_lbl.setStyleSheet(f"color: {MUTED}; font-size: 10px; border: none;")
                    pw_row.addWidget(path_lbl, 1)
                    pl.addWidget(pw)
                    pl.addSpacing(3)
                pl.addSpacing(6)

        pl.addWidget(_divider())
        pl.addSpacing(12)

        note = QLabel("⚠  Databases and stored credentials are not affected by this reset.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {WARN}; font-size: 10px; border: none;")
        pl.addWidget(note)
        pl.addSpacing(14)

        btn_back = _ghost_btn("← Back to Login")
        btn_back.clicked.connect(self.on_back)
        pl.addWidget(btn_back)

        cl.addWidget(panel)
        cl.addStretch()
        root.addWidget(content, 1)
        root.addWidget(_status_bar())


# ═══════════════════════════════════════════════════════════════════════════════
# LOGIN DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGOps")
        self.setFixedSize(460, 560)
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

        self._bg = _BgWidget(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.lower()

        # Login content widget
        self._login_widget = QWidget(self)
        self._login_widget.setGeometry(0, 0, self.width(), self.height())
        self._login_widget.setStyleSheet("background: transparent;")
        self._build_login_content(self._login_widget)

        # Forgot overlay — parked off-screen to the right
        self._forgot_widget = _ForgotOverlay(self, on_back=self._slide_back)
        self._forgot_widget.setGeometry(self.width(), 0, self.width(), self.height())

    def _build_login_content(self, parent: QWidget):
        cl_root = QVBoxLayout(parent)
        cl_root.setContentsMargins(0, 0, 0, 0)
        cl_root.setSpacing(0)

        # Top bar
        topbar = QWidget()
        topbar.setStyleSheet("background: transparent;")
        tb_row = QHBoxLayout(topbar)
        tb_row.setContentsMargins(20, 10, 20, 0)
        tb_row.setSpacing(0)

        status_lbl = QLabel("● SYSTEM READY")
        status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        tb_row.addWidget(status_lbl)
        tb_row.addStretch()

        badge = QLabel("V1.2.0 ORCHESTRATOR")
        badge.setStyleSheet(f"color: {ACCENT}; font-size: 9px; letter-spacing: 1.5px; border: none; background: transparent;")
        tb_row.addWidget(badge)
        tb_row.addStretch()

        node_lbl = QLabel("NODE: PG0-ALPHA-01")
        node_lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        tb_row.addWidget(node_lbl)
        cl_root.addWidget(topbar)

        # Content
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(36, 24, 36, 16)
        cl.setSpacing(0)

        icon_lbl = QLabel("⊞")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            f"color: {ACCENT}; font-size: 30px; background: transparent; border: none;"
        )
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon_lbl)
        icon_row.addStretch()
        cl.addLayout(icon_row)
        cl.addSpacing(12)

        app_title = QLabel("PGOps")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_title.setStyleSheet(
            f"color: {TEXT}; font-size: 24px; font-weight: 700; letter-spacing: 0.5px; border: none;"
        )
        cl.addWidget(app_title)

        ver_tag = _tag("V1.2.0 ORCHESTRATOR")
        ver_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(ver_tag)
        cl.addSpacing(22)

        # Panel
        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(26, 20, 26, 20)
        pl.setSpacing(0)

        pl.addWidget(_section_tag("AUTHENTICATION"))
        pl.addSpacing(8)

        heading = QLabel("Access Command Console")
        heading.setStyleSheet(f"color: {TEXT}; font-size: 14px; font-weight: 600; border: none;")
        pl.addWidget(heading)
        pl.addSpacing(4)

        sub = QLabel("Enter your master password to unlock the orchestration interface.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {MUTED}; font-size: 11px; line-height: 150%; border: none;")
        pl.addWidget(sub)
        pl.addSpacing(16)
        pl.addWidget(_divider())
        pl.addSpacing(16)

        lbl_row = QHBoxLayout()
        lbl_row.addWidget(_tag("APP PASSWORD"))
        lbl_row.addStretch()
        pl.addLayout(lbl_row)
        pl.addSpacing(6)

        self.pw_eye = EyeLineEdit("Enter password")
        self.pw_eye.returnPressed.connect(self._login)
        pl.addWidget(self.pw_eye)
        pl.addSpacing(10)

        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(
            f"color: {DANGER}; font-size: 10px; border: none; "
            f"background: rgba(231,76,60,0.07); border-radius: 4px; padding: 5px 10px;"
        )
        self.error_lbl.setVisible(False)
        pl.addWidget(self.error_lbl)
        pl.addSpacing(8)

        self.btn_login = _gradient_btn("LOGIN")
        self.btn_login.clicked.connect(self._login)
        pl.addWidget(self.btn_login)
        pl.addSpacing(12)

        forgot_btn = QPushButton("Forgot Password?")
        forgot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {MUTED};
                border: none;
                font-family: 'Segoe UI', -apple-system, sans-serif;
                font-size: 11px;
                text-decoration: underline;
                padding: 4px;
            }}
            QPushButton:hover {{ color: {TEXT}; }}
        """)
        forgot_btn.clicked.connect(self._slide_forgot)
        pl.addWidget(forgot_btn, 0, Qt.AlignmentFlag.AlignCenter)

        cl.addWidget(panel)
        cl.addStretch()
        cl_root.addWidget(content, 1)
        cl_root.addWidget(_status_bar())

        self.pw_eye.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, '_login_widget'):
            self._login_widget.setGeometry(0, 0, self.width(), self.height())

    # ── Slide animations ────────────────────────────────────────────────────────
    def _slide_forgot(self):
        w, h = self.width(), self.height()
        self._forgot_widget.setGeometry(w, 0, w, h)
        self._forgot_widget.show()
        self._forgot_widget.raise_()

        anim_login = QPropertyAnimation(self._login_widget, b"geometry", self)
        anim_login.setDuration(260)
        anim_login.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_login.setStartValue(QRect(0, 0, w, h))
        anim_login.setEndValue(QRect(-w, 0, w, h))

        anim_forgot = QPropertyAnimation(self._forgot_widget, b"geometry", self)
        anim_forgot.setDuration(260)
        anim_forgot.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_forgot.setStartValue(QRect(w, 0, w, h))
        anim_forgot.setEndValue(QRect(0, 0, w, h))

        anim_login.start()
        anim_forgot.start()
        self._anim_a, self._anim_b = anim_login, anim_forgot

    def _slide_back(self):
        w, h = self.width(), self.height()
        self._login_widget.setGeometry(-w, 0, w, h)
        self._login_widget.show()

        anim_login = QPropertyAnimation(self._login_widget, b"geometry", self)
        anim_login.setDuration(260)
        anim_login.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_login.setStartValue(QRect(-w, 0, w, h))
        anim_login.setEndValue(QRect(0, 0, w, h))

        anim_forgot = QPropertyAnimation(self._forgot_widget, b"geometry", self)
        anim_forgot.setDuration(260)
        anim_forgot.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_forgot.setStartValue(QRect(0, 0, w, h))
        anim_forgot.setEndValue(QRect(w, 0, w, h))

        anim_login.start()
        anim_forgot.start()
        self._anim_c, self._anim_d = anim_login, anim_forgot
        QTimer.singleShot(270, self.pw_eye.setFocus)

    # ── Auth logic ──────────────────────────────────────────────────────────────
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

        self._bg = _BgWidget(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.lower()

        # Top bar
        topbar = QWidget()
        topbar.setStyleSheet("background: transparent;")
        tb_row = QHBoxLayout(topbar)
        tb_row.setContentsMargins(20, 10, 20, 0)

        status_lbl = QLabel("● SYSTEM READY")
        status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        tb_row.addWidget(status_lbl)
        tb_row.addStretch()

        badge = QLabel("INITIAL CONFIGURATION")
        badge.setStyleSheet(f"color: {MUTED}; font-size: 9px; letter-spacing: 1.5px; border: none; background: transparent;")
        tb_row.addWidget(badge)
        tb_row.addStretch()

        node_lbl = QLabel("NODE: PG0-ALPHA-01")
        node_lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1.5px; border: none;")
        tb_row.addWidget(node_lbl)
        root.addWidget(topbar)

        # Content
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(36, 20, 36, 16)
        cl.setSpacing(0)

        icon_lbl = QLabel("🛡")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: 28px; background: transparent; border: none;")
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon_lbl)
        icon_row.addStretch()
        cl.addLayout(icon_row)
        cl.addSpacing(12)

        app_title = QLabel("PGOps Orchestrator")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_title.setStyleSheet(f"color: {TEXT}; font-size: 20px; font-weight: 700; border: none;")
        cl.addWidget(app_title)

        init_tag = _tag("INITIAL CONFIGURATION", MUTED)
        init_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(init_tag)
        cl.addSpacing(20)

        # Panel
        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(26, 20, 26, 20)
        pl.setSpacing(0)

        pl.addWidget(_section_tag("SECURE THE CONSOLE"))
        pl.addSpacing(8)

        heading = QLabel("Secure the Console")
        heading.setStyleSheet(f"color: {TEXT}; font-size: 14px; font-weight: 600; border: none;")
        pl.addWidget(heading)
        pl.addSpacing(4)

        sub = QLabel(
            "Define a local password to protect your orchestration layer. "
            "Stored locally on this machine only."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {MUTED}; font-size: 11px; border: none;")
        pl.addWidget(sub)
        pl.addSpacing(16)
        pl.addWidget(_divider())
        pl.addSpacing(16)

        lbl_row = QHBoxLayout()
        lbl_row.addWidget(_tag("CREATE APP PASSWORD"))
        lbl_row.addStretch()
        min_hint = QLabel("Min 4 characters")
        min_hint.setStyleSheet(f"color: {SUBTLE}; font-size: 9px; letter-spacing: 1px; border: none;")
        lbl_row.addWidget(min_hint)
        pl.addLayout(lbl_row)
        pl.addSpacing(6)

        self.pw1 = EyeLineEdit("New Password")
        self.pw1.textChanged.connect(self._check_strength)
        pl.addWidget(self.pw1)
        pl.addSpacing(6)

        self.strength_bar = StrengthBar()
        pl.addWidget(self.strength_bar)
        pl.addSpacing(10)

        self.pw2 = EyeLineEdit("Confirm Password")
        self.pw2.returnPressed.connect(self._save)
        pl.addWidget(self.pw2)
        pl.addSpacing(10)

        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(
            f"color: {DANGER}; font-size: 10px; border: none; "
            f"background: rgba(231,76,60,0.07); border-radius: 4px; padding: 5px 10px;"
        )
        self.error_lbl.setVisible(False)
        pl.addWidget(self.error_lbl)
        pl.addSpacing(8)

        btn_init = _gradient_btn("INITIALIZE PGOPS")
        btn_init.clicked.connect(self._save)
        pl.addWidget(btn_init)
        pl.addSpacing(14)

        pl.addWidget(_hint_box(
            "PGOps uses this password to protect the server interface only. "
            "Database credentials remain managed via your encrypted Vault."
        ))

        cl.addWidget(panel)
        cl.addStretch()
        root.addWidget(content, 1)
        root.addWidget(_status_bar())

        self.pw1.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg.setGeometry(0, 0, self.width(), self.height())

    def _check_strength(self, pw: str):
        if not pw:
            self.strength_bar.set_score(0)
            return
        score = 0
        if len(pw) >= 8:  score += 1
        if len(pw) >= 12: score += 1
        if any(c.isupper() for c in pw): score += 1
        if any(c.isdigit() for c in pw): score += 1
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in pw): score += 1
        if score >= 4: bar = 4
        elif score >= 3: bar = 3
        elif score >= 2: bar = 2
        elif score >= 1: bar = 1
        else: bar = 0
        self.strength_bar.set_score(bar)

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

        self._bg = _BgWidget(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.lower()

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 28, 32, 20)
        cl.setSpacing(0)

        panel = _Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(26, 20, 26, 20)
        pl.setSpacing(0)

        pl.addWidget(_section_tag("CHANGE PASSWORD"))
        pl.addSpacing(8)

        heading = QLabel("Change Master Password")
        heading.setStyleSheet(f"color: {TEXT}; font-size: 14px; font-weight: 600; border: none;")
        pl.addWidget(heading)
        pl.addSpacing(16)
        pl.addWidget(_divider())
        pl.addSpacing(16)

        for attr, placeholder in [
            ("current_pw", "Current password"),
            ("new_pw1",    "New password (min 4 characters)"),
            ("new_pw2",    "Confirm new password"),
        ]:
            f = EyeLineEdit(placeholder)
            setattr(self, attr, f)
            pl.addWidget(f)
            pl.addSpacing(8)

        self.new_pw2.returnPressed.connect(self._save)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(
            f"color: {DANGER}; font-size: 10px; border: none; "
            f"background: rgba(231,76,60,0.07); border-radius: 4px; padding: 5px 10px;"
        )
        self.error_lbl.setVisible(False)
        pl.addWidget(self.error_lbl)
        pl.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_cancel = _ghost_btn("Cancel")
        btn_save   = _gradient_btn("CHANGE PASSWORD", h=36)
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg.setGeometry(0, 0, self.width(), self.height())

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