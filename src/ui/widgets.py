from PyQt6.QtWidgets import QPushButton, QLabel, QLineEdit, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QApplication
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFont
from ui.theme import *


def mk_btn(text, bg, hover, fg="#ffffff", h=36, radius=6):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;border-radius:{radius}px;"
        f"font-size:12px;font-weight:700;padding:0 16px;letter-spacing:0.3px;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
    )
    return b


def mk_ghost(text, h=36):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:transparent;color:{C_TEXT2};border:1px solid {C_BORDER2};"
        f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
        f"QPushButton:hover{{background:{C_SURFACE2};color:{C_TEXT};border-color:{C_TEXT3};}}"
        f"QPushButton:disabled{{color:{C_TEXT3};}}"
    )
    return b


def mk_inp(val="", placeholder="", password=False, readonly=False):
    f = QLineEdit(val)
    if placeholder:
        f.setPlaceholderText(placeholder)
    if password:
        f.setEchoMode(QLineEdit.EchoMode.Password)
    f.setReadOnly(readonly)
    color = C_TEXT2 if readonly else C_TEXT
    f.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:7px 11px;color:{color};"
        f"font-size:13px;font-family:'Consolas','Courier New',monospace;}}"
        f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
        f"QLineEdit:read-only{{color:{C_TEXT2};}}"
    )
    return f


def mk_lbl(text, color=C_TEXT2, size=12, bold=False, mono=False):
    l = QLabel(text)
    ff = "'Consolas','Courier New',monospace" if mono else "inherit"
    w = "700" if bold else "400"
    l.setStyleSheet(
        f"color:{color};font-size:{size}px;font-weight:{w};"
        f"{'font-family:Consolas,monospace;' if mono else ''}background:transparent;"
    )
    return l


def mk_sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


def mk_section_label(text):
    l = QLabel(text.upper())
    l.setStyleSheet(
        f"color:{C_TEXT3};font-size:10px;font-weight:700;"
        f"letter-spacing:1.8px;background:transparent;"
    )
    return l


class CopyField(QWidget):
    def __init__(self, label, value="", mono=True):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        if label:
            lbl = QLabel(label)
            lbl.setFixedWidth(80)
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1.2px;background:transparent;"
            )
            row.addWidget(lbl)

        ff = "'Consolas','Courier New',monospace" if mono else "inherit"
        self.field = QLineEdit(value)
        self.field.setReadOnly(True)
        self.field.setStyleSheet(
            f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:7px 11px;color:{C_TEXT};"
            f"font-size:12px;font-family:{ff};}}"
        )
        row.addWidget(self.field)

        self._btn = QPushButton("Copy")
        self._btn.setFixedSize(52, 30)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:5px;"
            f"font-size:11px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        self._btn.clicked.connect(self._copy)
        row.addWidget(self._btn)

    def _copy(self):
        QApplication.clipboard().setText(self.field.text())
        self._btn.setText("✓")
        QTimer.singleShot(1400, lambda: self._btn.setText("Copy"))

    def set(self, v):
        self.field.setText(v)

    def get(self):
        return self.field.text()


class ConnField(QWidget):
    def __init__(self, label, value="", password=False):
        super().__init__()
        self.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:8px;"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(5)

        lbl = QLabel(label.upper())
        lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        v.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)

        self._show = not password
        self._raw = value
        self._val_lbl = QLabel("••••••••" if password else value)
        self._val_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:500;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        row.addWidget(self._val_lbl)
        row.addStretch()

        self._icon_btn = QPushButton("👁" if password else "⧉")
        self._icon_btn.setFixedSize(24, 24)
        self._icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;font-size:12px;}}"
            f"QPushButton:hover{{color:{C_TEXT};}}"
        )
        self._password = password
        if password:
            self._icon_btn.clicked.connect(self._toggle)
        else:
            self._icon_btn.clicked.connect(self._copy_val)
        row.addWidget(self._icon_btn)
        v.addLayout(row)

    def _toggle(self):
        self._show = not self._show
        self._val_lbl.setText(self._raw if self._show else "••••••••")

    def _copy_val(self):
        QApplication.clipboard().setText(self._raw)

    def set_value(self, v):
        self._raw = v
        if self._password and not self._show:
            self._val_lbl.setText("••••••••")
        else:
            self._val_lbl.setText(v)


class StatusPill(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        self.stopped()

    def _apply(self, text, fg, bg):
        self.setText(text)
        self.setStyleSheet(
            f"color:{fg};background:{bg};border:1px solid {fg}40;"
            f"border-radius:4px;font-size:10px;font-weight:800;"
            f"letter-spacing:1.2px;padding:0 10px;"
        )

    def running(self):  self._apply("● RUNNING",  C_GREEN,  "#0d2a1a")
    def stopped(self):  self._apply("● STOPPED",  C_RED,    "#2a0d0d")
    def starting(self): self._apply("◌ STARTING", C_AMBER,  "#2a1e0d")


class PulseDot(QWidget):
    def __init__(self, color=C_GREEN, parent=None):
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self._color = color
        self._alpha = 255
        self._step = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(40)

    def _tick(self):
        import math
        self._step = (self._step + 4) % 360
        self._alpha = int(160 + 95 * math.sin(math.radians(self._step)))
        self.update()

    def set_color(self, c):
        self._color = c

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self._color)
        c.setAlpha(self._alpha // 4)
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 9, 9)
        c2 = QColor(self._color)
        p.setBrush(QBrush(c2))
        p.drawEllipse(2, 2, 5, 5)
