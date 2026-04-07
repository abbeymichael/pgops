import platform

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt

from core.service_manager import (
    service_exists, service_running, install_service,
    uninstall_service, start_service, stop_service, is_admin,
)
from core.pg_manager import DATA_DIR, LOG_FILE, _bin
from ui.theme import (
    C_SURFACE, C_BORDER, C_BORDER2, C_SURFACE2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_RED, C_AMBER,
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


class ServiceTab(QWidget):
    """
    Standalone Windows Service page.
    on_log(msg), manager passed in.
    """

    def __init__(self, config, manager, on_log, parent=None):
        super().__init__(parent)
        self.config   = config
        self._manager = manager
        self._on_log  = on_log
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(20)

        title = QLabel("Windows Service")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:22px;font-weight:800;background:transparent;"
        )
        sub = QLabel(
            "Install PostgreSQL as a Windows service so it starts automatically at boot, "
            "before anyone logs in."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        outer.addWidget(title)
        outer.addWidget(sub)

        info_card = self._card("About Service Mode")
        ic = info_card.layout()
        ic.addWidget(_lbl(
            "In service mode PostgreSQL runs as a Windows background service managed by "
            "the Service Control Manager.  Ideal for dedicated VMs and mini PCs that need "
            "to serve the database without a user being logged in.\n\n"
            "Requires running PGOps as Administrator to install or remove the service.",
            C_TEXT2, 12
        ))
        outer.addWidget(info_card)

        ctl_card = self._card("Service Control")
        cc = ctl_card.layout()

        self.svc_status_lbl = QLabel("Checking...")
        self.svc_status_lbl.setStyleSheet(f"color:{C_TEXT2};font-size:13px;background:transparent;")
        cc.addWidget(self.svc_status_lbl)

        btn_row = QHBoxLayout()
        self.btn_install   = _btn("Install Service",  "#166534", "#15803d", "#86efac", h=38)
        self.btn_uninstall = _btn("Remove Service",   "#7f1d1d", "#991b1b", "#fca5a5", h=38)
        self.btn_svc_start = _btn("Start Service",    C_BLUE,    "#3b7de8", "white",   h=38)
        self.btn_svc_stop  = _btn("Stop Service",     C_SURFACE2, C_BORDER2, C_TEXT2,  h=38)

        self.btn_install.clicked.connect(self._install)
        self.btn_uninstall.clicked.connect(self._uninstall)
        self.btn_svc_start.clicked.connect(self._start_svc)
        self.btn_svc_stop.clicked.connect(self._stop_svc)

        for b in (self.btn_install, self.btn_uninstall, self.btn_svc_start, self.btn_svc_stop):
            btn_row.addWidget(b)
        btn_row.addStretch()
        cc.addLayout(btn_row)

        if not is_admin():
            warn = QLabel("Not running as Administrator — service operations require admin rights.")
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"color:{C_AMBER};background:#2a1e0a;padding:10px 14px;"
                f"border-radius:6px;font-size:12px;"
            )
            cc.addWidget(warn)

        outer.addWidget(ctl_card)
        outer.addStretch()

        self.update_status()

    def _card(self, title):
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)
        t = QLabel(title)
        t.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
        v.addWidget(t)
        v.addWidget(_sep())
        return card

    def update_status(self):
        if platform.system() != "Windows":
            self.svc_status_lbl.setText("Service management is Windows-only.")
            self.svc_status_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:13px;background:transparent;")
            return
        if service_exists():
            running = service_running()
            state, color = ("RUNNING", C_GREEN) if running else ("STOPPED", C_RED)
            self.svc_status_lbl.setText(f"Service installed — {state}")
            self.svc_status_lbl.setStyleSheet(f"color:{color};font-size:13px;font-weight:700;background:transparent;")
        else:
            self.svc_status_lbl.setText("Service not installed — app mode")
            self.svc_status_lbl.setStyleSheet(f"color:{C_TEXT3};font-size:13px;background:transparent;")

    def _install(self):
        if not is_admin():
            QMessageBox.warning(self, "Admin Required",
                "Right-click PGOps.exe → Run as Administrator, then try again."); return
        if not self._manager.is_initialized():
            QMessageBox.warning(self, "Not Initialized",
                "Start the server at least once first."); return
        ok, msg = install_service(
            _bin("pg_ctl"), DATA_DIR, LOG_FILE, self.config["port"]
        )
        self._on_log(msg)
        self.update_status()
        if not ok:
            QMessageBox.critical(self, "Error", msg)

    def _uninstall(self):
        if not is_admin():
            QMessageBox.warning(self, "Admin Required",
                "Run as Administrator to remove the service."); return
        ok, msg = uninstall_service()
        self._on_log(msg)
        self.update_status()

    def _start_svc(self):
        ok, msg = start_service()
        self._on_log(msg)
        self.update_status()

    def _stop_svc(self):
        ok, msg = stop_service()
        self._on_log(msg)
        self.update_status()
