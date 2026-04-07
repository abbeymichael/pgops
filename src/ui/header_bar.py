from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFont
from ui.theme import *


class _AvatarButton(QWidget):
    """Circular avatar with initials + dropdown arrow — no border artefacts."""
    clicked = pyqtSignal()

    def __init__(self, initials: str = "A1", parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._lbl = QLabel(initials)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet(
            f"color: {C_TEXT}; font-size: 11px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self._lbl)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Outer ring
        p.setPen(QColor(C_BORDER2))
        p.setBrush(QColor(C_SURFACE2))
        p.drawEllipse(1, 1, 31, 31)
        super().paintEvent(event)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _IconBtn(QWidget):
    """Clean icon button with optional notification badge — no stray borders."""
    clicked = pyqtSignal()

    def __init__(self, icon: str, badge: bool = False, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._badge   = badge
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none; background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._icon = QLabel(icon)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 15px; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self._icon)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C_SURFACE))
            p.drawRoundedRect(2, 2, 29, 29, 7, 7)
        # Notification badge dot
        if self._badge:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C_BLUE))
            p.drawEllipse(20, 4, 8, 8)
        super().paintEvent(event)

    def enterEvent(self, e):
        self._hovered = True
        self._icon.setStyleSheet(
            f"color: {C_TEXT}; font-size: 15px; "
            f"background: transparent; border: none;"
        )
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self._icon.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 15px; "
            f"background: transparent; border: none;"
        )
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _SearchBar(QWidget):
    """Search bar with a leading magnifier label — cleaner than QLineEdit alone."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"background: {C_SURFACE}; "
            f"border: 1px solid {C_BORDER}; "
            f"border-radius: 8px;"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(6)

        icon = QLabel("⌕")
        icon.setFixedWidth(14)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 16px; "
            f"background: transparent; border: none;"
        )
        row.addWidget(icon)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Quick Search...")
        self._input.setStyleSheet(
            f"QLineEdit {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  color: {C_TEXT2};"
            f"  font-size: 12px;"
            f"  padding: 0;"
            f"}}"
            f"QLineEdit:focus {{"
            f"  color: {C_TEXT};"
            f"}}"
        )
        row.addWidget(self._input)

        # Keyboard shortcut hint
        hint = QLabel("⌘K")
        hint.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 10px; font-weight: 600; "
            f"background: {C_SURFACE2}; border: 1px solid {C_BORDER2}; "
            f"border-radius: 4px; padding: 1px 5px;"
        )
        row.addWidget(hint)

    def focusInEvent(self, e):
        self.setStyleSheet(
            f"background: {C_SURFACE}; "
            f"border: 1px solid {C_BLUE}66; "
            f"border-radius: 8px;"
        )
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.setStyleSheet(
            f"background: {C_SURFACE}; "
            f"border: 1px solid {C_BORDER}; "
            f"border-radius: 8px;"
        )
        super().focusOutEvent(e)


class HeaderBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        # Only bottom border — no side/top borders bleeding into children
        self.setStyleSheet(
            f"HeaderBar {{"
            f"  background: {C_BG};"
            f"}}"
        )

        h = QHBoxLayout(self)
        h.setContentsMargins(24, 0, 16, 0)
        h.setSpacing(0)

        # ── Left: breadcrumb ──────────────────────────────────────────────────
        self._section = QLabel("THE COMMAND CONSOLE")
        self._section.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 2px; background: transparent; border: none;"
        )
        h.addWidget(self._section)

        # Vertical divider
        self._divider = QWidget()
        self._divider.setFixedSize(1, 16)
        self._divider.setStyleSheet(
            f"background: {C_BORDER2}; border: none;"
        )
        h.addSpacing(16)
        h.addWidget(self._divider)
        h.addSpacing(16)

        self._page_title = QLabel("")
        self._page_title.setStyleSheet(
            f"color: {C_TEXT}; font-size: 13px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        h.addWidget(self._page_title)

        h.addStretch()

        # ── Right: search + actions ───────────────────────────────────────────
        self._search = _SearchBar()
        h.addWidget(self._search)
        h.addSpacing(10)

        # Notification bell — with badge
        self._bell = _IconBtn("🔔", badge=True)
        h.addWidget(self._bell)
        h.addSpacing(4)

        # Menu / grid icon
        self._menu_btn = _IconBtn("▤")
        h.addWidget(self._menu_btn)
        h.addSpacing(8)

        # Vertical divider before avatar
        sep = QWidget()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet(f"background: {C_BORDER}; border: none;")
        h.addWidget(sep)
        h.addSpacing(12)

        # User section: avatar + name
        user_row = QHBoxLayout()
        user_row.setContentsMargins(0, 0, 0, 0)
        user_row.setSpacing(8)

        self._avatar = _AvatarButton("A1")
        user_row.addWidget(self._avatar)

        user_col = QVBoxLayout()
        user_col.setSpacing(0)
        user_col.setContentsMargins(0, 0, 0, 0)

        self._user_name = QLabel("Admin-01")
        self._user_name.setStyleSheet(
            f"color: {C_TEXT}; font-size: 12px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        self._user_role = QLabel("Administrator")
        self._user_role.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 10px; font-weight: 400; "
            f"background: transparent; border: none;"
        )
        user_col.addWidget(self._user_name)
        user_col.addWidget(self._user_role)
        user_row.addLayout(user_col)

        # Dropdown chevron
        chevron = QLabel("⌄")
        chevron.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 13px; "
            f"background: transparent; border: none;"
        )
        user_row.addWidget(chevron)

        user_wrap = QWidget()
        user_wrap.setStyleSheet("background: transparent; border: none;")
        user_wrap.setLayout(user_row)
        user_wrap.setCursor(Qt.CursorShape.PointingHandCursor)
        h.addWidget(user_wrap)

        # Bottom divider — drawn as a child widget so it doesn't bleed
        self._bottom_line = QWidget(self)
        self._bottom_line.setStyleSheet(f"background: {C_BORDER}; border: none;")
        self._bottom_line.setGeometry(0, 51, 9999, 1)

    def resizeEvent(self, e):
        self._bottom_line.setGeometry(0, self.height() - 1, self.width(), 1)
        super().resizeEvent(e)

    # ── Public API — identical to original ────────────────────────────────────
    def set_title(self, section: str, page: str = ""):
        self._section.setText(
            section.upper() if section else "THE COMMAND CONSOLE"
        )
        self._page_title.setText(page)
        self._divider.setVisible(bool(page))