from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QSpinBox, QFrame, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt

from ui.theme import (
    C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_RED,
)


def _btn(text, bg=C_BLUE, hover="#3b7de8", fg="white", h=36):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 16px;font-size:12px;font-weight:700;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
    )
    return b


def _lbl(text, color=C_TEXT2, size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;background:transparent;")
    return l


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


def _inp(val="", pw=False):
    f = QLineEdit(val)
    if pw:
        f.setEchoMode(QLineEdit.EchoMode.Password)
    f.setFixedHeight(36)
    f.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 11px;color:{C_TEXT};font-size:13px;}}"
        f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
    )
    return f


class SettingsTab(QWidget):
    """
    Standalone Settings page.
    on_save(config_dict) — called when user saves
    on_change_pw()       — called when Change Password clicked
    on_log(msg)
    """

    def __init__(self, config, on_save, on_change_pw, on_log, parent=None):
        super().__init__(parent)
        self.config       = config
        self._on_save     = on_save
        self._on_change_pw = on_change_pw
        self._on_log      = on_log
        self._build()

    def update_config(self, config):
        self.config = config

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:#1a1d23;border:none;")

        inner = QWidget()
        inner.setStyleSheet("background:#1a1d23;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(20)

        title = QLabel("Settings")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:22px;font-weight:800;background:transparent;"
        )
        sub = QLabel("Configure PostgreSQL server credentials and application preferences.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        # ── Server config card ─────────────────────────────────────────────────
        srv_card = QWidget()
        srv_card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        sc = QVBoxLayout(srv_card)
        sc.setContentsMargins(22, 20, 22, 20)
        sc.setSpacing(14)

        sc_title = QLabel("Admin Server Configuration")
        sc_title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        sc.addWidget(sc_title)
        sc.addWidget(_sep())

        LABEL_W = 150
        self.s_user = _inp(self.config["username"])
        self.s_pass = _inp(self.config["password"])
        self.s_db   = _inp(self.config["database"])
        self.s_port = QSpinBox()
        self.s_port.setRange(1024, 65535)
        self.s_port.setValue(self.config["port"])
        self.s_port.setFixedHeight(36)
        self.s_port.setStyleSheet(
            f"QSpinBox{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:0 10px;color:{C_TEXT};font-size:13px;}}"
        )

        for label, widget in [
            ("Admin Username", self.s_user),
            ("Admin Password", self.s_pass),
            ("Default Database", self.s_db),
            ("Port", self.s_port),
        ]:
            r = QHBoxLayout()
            lbl = _lbl(label.upper(), C_TEXT3, 10)
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1px;background:transparent;"
            )
            lbl.setFixedWidth(LABEL_W)
            r.addWidget(lbl)
            r.addWidget(widget)
            sc.addLayout(r)

        self.s_auto = QCheckBox("Auto-start server when app launches")
        self.s_auto.setChecked(self.config.get("autostart", False))
        self.s_auto.setStyleSheet(
            f"QCheckBox{{color:{C_TEXT2};font-size:12px;spacing:8px;}}"
            f"QCheckBox::indicator{{width:15px;height:15px;border-radius:4px;"
            f"border:1px solid {C_BORDER2};background:{C_SURFACE2};}}"
            f"QCheckBox::indicator:checked{{background:{C_BLUE};border:1px solid {C_BLUE};}}"
        )
        sc.addWidget(self.s_auto)

        warn = _lbl(
            "Changing credentials requires stopping the server and deleting pgdata/ to reinitialize.",
            C_TEXT3, 11
        )
        warn.setWordWrap(True)
        sc.addWidget(warn)

        save_btn = _btn("Save Settings", C_BLUE, "#3b7de8", h=40)
        save_btn.clicked.connect(self._save)
        sc.addWidget(save_btn)
        v.addWidget(srv_card)

        # ── App password card ──────────────────────────────────────────────────
        pw_card = QWidget()
        pw_card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        pc = QVBoxLayout(pw_card)
        pc.setContentsMargins(22, 20, 22, 20)
        pc.setSpacing(12)

        pc_title = QLabel("App Password")
        pc_title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        pc.addWidget(pc_title)
        pc.addWidget(_sep())
        pc.addWidget(_lbl(
            "Change the master password used to unlock PGOps on launch.", C_TEXT3, 11
        ))
        btn_chpw = _btn("Change Password", C_SURFACE2, C_BORDER2, C_TEXT2, h=38)
        btn_chpw.clicked.connect(self._on_change_pw)
        pc.addWidget(btn_chpw)
        v.addWidget(pw_card)
        v.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _save(self):
        new_cfg = {
            "username":  self.s_user.text().strip(),
            "password":  self.s_pass.text().strip(),
            "database":  self.s_db.text().strip(),
            "port":      self.s_port.value(),
            "autostart": self.s_auto.isChecked(),
        }
        self._on_save(new_cfg)
        self._on_log("Settings saved. Restart server to apply.")
        QMessageBox.information(self, "Saved", "Settings saved successfully.")
