from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QBrush
from ui.theme import *

NAV = [
    ("server",    "Servers",   "▣"),
    ("activity",  "Activity",  "≋"),
    ("databases", "Databases", "⊞"),
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
    ("log",       "Log",       "≡"),
]


class _NavBtn(QPushButton):
    def __init__(self, nav_id, icon, label):
        super().__init__()
        self.nav_id = nav_id
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)

        self._icon = QLabel(icon)
        self._icon.setFixedWidth(16)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._lbl = QLabel(label)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        row.addWidget(self._icon)
        row.addWidget(self._lbl)
        row.addStretch()

        self._set_state(False)
        self.toggled.connect(self._set_state)

    def _set_state(self, on):
        if on:
            self.setStyleSheet(
                f"QPushButton{{background:{C_SURFACE};border:none;"
                f"border-left:2px solid {C_BLUE};border-radius:0;}}"
                f"QPushButton:hover{{background:{C_SURFACE};}}"
            )
            self._icon.setStyleSheet(f"color:{C_BLUE};font-size:13px;background:transparent;")
            self._lbl.setStyleSheet(f"color:{C_TEXT};font-size:13px;font-weight:600;background:transparent;")
        else:
            self.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;"
                f"border-left:2px solid transparent;border-radius:0;}}"
                f"QPushButton:hover{{background:{C_SURFACE}22;}}"
            )
            self._icon.setStyleSheet(f"color:{C_TEXT3};font-size:13px;background:transparent;")
            self._lbl.setStyleSheet(f"color:{C_TEXT2};font-size:13px;font-weight:400;background:transparent;")


class Sidebar(QWidget):
    nav_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        self.setStyleSheet(f"background:{C_BG};border-right:1px solid {C_BORDER};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._logo())

        nav_area = QWidget()
        nav_area.setStyleSheet("background:transparent;")
        nv = QVBoxLayout(nav_area)
        nv.setContentsMargins(0, 8, 0, 0)
        nv.setSpacing(1)

        self._btns = {}
        for nav_id, label, icon in NAV:
            btn = _NavBtn(nav_id, icon, label)
            btn.clicked.connect(lambda _, nid=nav_id: self._select(nid))
            self._btns[nav_id] = btn
            nv.addWidget(btn)

        sep_wrap_w = QWidget()
        sep_wrap_w.setFixedHeight(17)
        sep_wrap_w.setStyleSheet("background:transparent;")
        sep_wrap = QHBoxLayout(sep_wrap_w)
        sep_wrap.setContentsMargins(16, 8, 16, 8)
        sep_line = QWidget()
        sep_line.setFixedHeight(1)
        sep_line.setStyleSheet(f"background:{C_BORDER};")
        sep_wrap.addWidget(sep_line)
        nv.addWidget(sep_wrap_w)

        for nav_id, label, icon in ADV_NAV:
            btn = _NavBtn(nav_id, icon, label)
            btn.clicked.connect(lambda _, nid=nav_id: self._select(nid))
            self._btns[nav_id] = btn
            nv.addWidget(btn)

        nv.addStretch()
        root.addWidget(nav_area, 1)
        root.addWidget(self._bottom())

        self._select("server")

    def _logo(self):
        w = QWidget()
        w.setFixedHeight(60)
        w.setStyleSheet(f"background:{C_BG};border-bottom:1px solid {C_BORDER};")
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(10)

        box = QLabel("PG")
        box.setFixedSize(32, 32)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #4f8ef7,stop:1 #2563eb);"
            f"border-radius:7px;color:white;font-size:13px;font-weight:900;"
        )

        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel("PGOps")
        name.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;")
        ver = QLabel("V1.2.0 ORCHESTRATOR")
        ver.setStyleSheet(f"color:{C_TEXT3};font-size:9px;font-weight:700;letter-spacing:1.5px;background:transparent;")
        col.addWidget(name)
        col.addWidget(ver)

        h.addWidget(box)
        h.addLayout(col)
        return w

    def _bottom(self):
        w = QWidget()
        w.setStyleSheet(f"background:{C_BG};border-top:1px solid {C_BORDER};")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 16)
        v.setSpacing(4)

        for label in ("Documentation", "Support"):
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C_TEXT3};"
                f"border:none;font-size:12px;text-align:left;padding-left:2px;}}"
                f"QPushButton:hover{{color:{C_TEXT2};}}"
            )
            v.addWidget(btn)

        new_btn = QPushButton("  + New Instance")
        new_btn.setFixedHeight(38)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #4f8ef7,stop:1 #7c3aed);"
            f"color:white;border:none;border-radius:8px;"
            f"font-size:12px;font-weight:700;letter-spacing:0.3px;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #3b7de8,stop:1 #6d28d9);}}"
        )
        v.addWidget(new_btn)
        return w

    def _select(self, nav_id):
        for nid, btn in self._btns.items():
            btn.setChecked(nid == nav_id)
        self.nav_changed.emit(nav_id)

    def select(self, nav_id):
        self._select(nav_id)
