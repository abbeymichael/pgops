from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame
from PyQt6.QtCore import Qt
from ui.theme import *


class HeaderBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet(f"background:{C_BG};border-bottom:1px solid {C_BORDER};")

        h = QHBoxLayout(self)
        h.setContentsMargins(24, 0, 20, 0)
        h.setSpacing(0)

        self._section = QLabel("THE COMMAND CONSOLE")
        self._section.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;font-weight:700;"
            f"letter-spacing:2px;background:transparent;"
        )
        h.addWidget(self._section)

        self._divider = QFrame()
        self._divider.setFrameShape(QFrame.Shape.VLine)
        self._divider.setFixedWidth(1)
        self._divider.setFixedHeight(16)
        self._divider.setStyleSheet(f"background:{C_BORDER2};border:none;")
        h.addSpacing(18)
        h.addWidget(self._divider)
        h.addSpacing(18)

        self._page_title = QLabel("")
        self._page_title.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:700;background:transparent;"
        )
        h.addWidget(self._page_title)

        h.addStretch()

        search = QLineEdit()
        search.setPlaceholderText("Quick Search...")
        search.setFixedSize(200, 32)
        search.setStyleSheet(
            f"QLineEdit{{background:{C_SURFACE};border:1px solid {C_BORDER};"
            f"border-radius:16px;padding:0 14px 0 14px;"
            f"color:{C_TEXT2};font-size:12px;}}"
            f"QLineEdit:focus{{border:1px solid {C_BLUE}44;color:{C_TEXT};}}"
        )
        h.addWidget(search)
        h.addSpacing(10)

        for icon in ("🔔", "▤"):
            btn = QPushButton(icon)
            btn.setFixedSize(32, 32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:{C_SURFACE};border:1px solid {C_BORDER};"
                f"border-radius:7px;font-size:13px;color:{C_TEXT2};}}"
                f"QPushButton:hover{{background:{C_SURFACE2};color:{C_TEXT};}}"
            )
            h.addWidget(btn)
            h.addSpacing(6)

        user = QPushButton("  Admin-01")
        user.setFixedHeight(32)
        user.setCursor(Qt.CursorShape.PointingHandCursor)
        user.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:7px;"
            f"font-size:12px;font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{background:{C_SURFACE2};}}"
        )
        h.addWidget(user)

    def set_title(self, section, page=""):
        self._section.setText(section.upper() if section else "THE COMMAND CONSOLE")
        self._page_title.setText(page)
        self._divider.setVisible(bool(page))
