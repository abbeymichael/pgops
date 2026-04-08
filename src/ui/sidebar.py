from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from ui.theme import *

NAV = [
    ("server",    "Servers",   "▣"),
    ("activity",  "Activity",  "≋"),
    ("databases", "Databases", "⊞"),
    ("apps",      "Apps",      "◉"),       # Phase 2
    ("browser",   "Explorer",  "◈"),
    ("files",     "Storage",   "☁"),
    ("settings",  "Settings",  "⚙"),
]

ADV_NAV = [
    ("backup",    "Backup",    "↥"),
    ("schedule",  "Schedule",  "◷"),
    ("ssl",       "SSL / TLS", "⊕"),
    ("service",   "Service",   "⬛"),
    ("network",   "Network",   "⬡"),
    ("dns",       "DNS",       "⊘"),       # Phase 2
    ("log",       "Log",       "≡"),
]


class _NavBtn(QWidget):
    clicked = pyqtSignal()

    def __init__(self, nav_id: str, icon: str, label: str):
        super().__init__()
        self.nav_id  = nav_id
        self._active = False

        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none; outline: none;")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 14, 0)
        row.setSpacing(10)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFixedWidth(18)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 14px; "
            f"background: transparent; border: none;"
        )
        row.addWidget(self._icon_lbl)

        self._text_lbl = QLabel(label)
        self._text_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._text_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._text_lbl.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 13px; font-weight: 500; "
            f"background: transparent; border: none;"
        )
        row.addWidget(self._text_lbl)

        self._apply(False)

    def _apply(self, on: bool):
        self._active = on
        self.setAutoFillBackground(on)

        if on:
            p = self.palette()
            p.setColor(self.backgroundRole(), QColor(C_SURFACE))
            self.setPalette(p)
            self.setStyleSheet(
                f"border: none; outline: none; "
                f"border-left: 3px solid {C_BLUE};"
            )
            self._icon_lbl.setStyleSheet(
                f"color: {C_BLUE}; font-size: 14px; "
                f"background: transparent; border: none;"
            )
            self._text_lbl.setStyleSheet(
                f"color: {C_TEXT}; font-size: 13px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
        else:
            self.setStyleSheet("border: none; outline: none;")
            self._icon_lbl.setStyleSheet(
                f"color: {C_TEXT3}; font-size: 14px; "
                f"background: transparent; border: none;"
            )
            self._text_lbl.setStyleSheet(
                f"color: {C_TEXT2}; font-size: 13px; font-weight: 500; "
                f"background: transparent; border: none;"
            )

    def set_active(self, on: bool):
        self._apply(on)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def enterEvent(self, e):
        if not self._active:
            self.setAutoFillBackground(True)
            p = self.palette()
            p.setColor(self.backgroundRole(), QColor(C_SURFACE))
            self.setPalette(p)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._active:
            self.setAutoFillBackground(False)
        super().leaveEvent(e)


class Sidebar(QWidget):
    nav_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        self.setStyleSheet(
            f"Sidebar {{ "
            f"  background: {C_BG}; "
            f"  border-right: 1px solid {C_BORDER}; "
            f"}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._logo())

        nav_area = QWidget()
        nav_area.setStyleSheet("background: transparent; border: none;")
        nv = QVBoxLayout(nav_area)
        nv.setContentsMargins(0, 10, 0, 4)
        nv.setSpacing(1)

        self._btns: dict[str, _NavBtn] = {}

        for nav_id, label, icon in NAV:
            btn = _NavBtn(nav_id, icon, label)
            btn.clicked.connect(lambda nid=nav_id: self._select(nid))
            self._btns[nav_id] = btn
            nv.addWidget(btn)

        nv.addSpacing(8)
        sep_wrap = QWidget()
        sep_wrap.setStyleSheet("background: transparent; border: none;")
        sw = QHBoxLayout(sep_wrap)
        sw.setContentsMargins(16, 0, 16, 0)
        sw.setSpacing(0)
        sep_line = QWidget()
        sep_line.setFixedHeight(1)
        sep_line.setStyleSheet(f"background: {C_BORDER}; border: none;")
        sw.addWidget(sep_line)
        nv.addWidget(sep_wrap)
        nv.addSpacing(8)

        for nav_id, label, icon in ADV_NAV:
            btn = _NavBtn(nav_id, icon, label)
            btn.clicked.connect(lambda nid=nav_id: self._select(nid))
            self._btns[nav_id] = btn
            nv.addWidget(btn)

        nv.addStretch()
        root.addWidget(nav_area, 1)
        root.addWidget(self._bottom())

        self._select("server")

    def _logo(self):
        w = QWidget()
        w.setFixedHeight(64)
        w.setStyleSheet(f"QWidget {{ background: {C_BG}; border: none; }}")

        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        inner = QWidget()
        inner.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(inner)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(10)

        box = QLabel("PG")
        box.setFixedSize(34, 34)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #4f8ef7, stop:1 #2563eb);"
            "border-radius: 8px; color: white;"
            "font-size: 13px; font-weight: 900; border: none;"
        )

        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)

        name = QLabel("PGOps")
        name.setStyleSheet(
            f"color: {C_TEXT}; font-size: 14px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        ver = QLabel("V2.0.0 ORCHESTRATOR")
        ver.setStyleSheet(
            f"color: {C_TEXT3}; font-size: 9px; font-weight: 700; "
            f"letter-spacing: 1.5px; background: transparent; border: none;"
        )
        col.addWidget(name)
        col.addWidget(ver)

        h.addWidget(box)
        h.addLayout(col)
        outer.addWidget(inner)

        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {C_BORDER}; border: none;")
        outer.addWidget(divider)
        return w

    def _bottom(self):
        w = QWidget()
        w.setStyleSheet(f"background: {C_BG}; border: none;")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 16)
        v.setSpacing(4)

        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {C_BORDER}; border: none;")
        v.addWidget(divider)
        v.addSpacing(8)

        for label in ("Documentation", "Support"):
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent; color: {C_TEXT3};"
                f"  border: none; font-size: 12px;"
                f"  text-align: left; padding-left: 4px;"
                f"}}"
                f"QPushButton:hover {{ color: {C_TEXT2}; }}"
            )
            v.addWidget(btn)

        v.addSpacing(4)
        new_btn = QPushButton("  + New Instance")
        new_btn.setFixedHeight(38)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #4f8ef7, stop:1 #7c3aed);"
            "  color: white; border: none; border-radius: 8px;"
            "  font-size: 12px; font-weight: 700; letter-spacing: 0.3px;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #3b7de8, stop:1 #6d28d9);"
            "}"
        )
        v.addWidget(new_btn)
        return w

    def _select(self, nav_id: str):
        for nid, btn in self._btns.items():
            btn.set_active(nid == nav_id)
        self.nav_changed.emit(nav_id)

    def select(self, nav_id: str):
        self._select(nav_id)
