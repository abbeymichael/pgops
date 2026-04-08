"""
tab_apps.py
Apps Tab — deploy and manage Laravel web applications.
"""

import os
import webbrowser
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDialog, QDialogButtonBox, QFileDialog,
    QRadioButton, QButtonGroup, QFrame, QScrollArea,
    QTextEdit, QProgressBar, QMessageBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QApplication, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

from ui.theme import (
    C_BG, C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_RED, C_AMBER,
    TABLE_STYLE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _btn(text, bg=C_BLUE, hover="#3b7de8", fg="white", h=32):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;padding:0 14px;font-size:12px;font-weight:700;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
    )
    return b


def _lbl(text, color=C_TEXT2, size=12, bold=False):
    l = QLabel(text)
    w = "700" if bold else "400"
    l.setStyleSheet(
        f"color:{color};font-size:{size}px;font-weight:{w};background:transparent;"
    )
    return l


def _inp(placeholder="", val=""):
    f = QLineEdit(val)
    if placeholder:
        f.setPlaceholderText(placeholder)
    f.setFixedHeight(34)
    f.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 11px;color:{C_TEXT};font-size:13px;}}"
        f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
    )
    return f


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


# ── Worker ────────────────────────────────────────────────────────────────────

class _Worker(QThread):
    done      = pyqtSignal(object, str)   # (result, error)
    progress  = pyqtSignal(str, str)      # (step_label, status)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
            self.done.emit(result, "")
        except Exception as exc:
            self.done.emit(None, str(exc))


# ── Deploy Wizard ─────────────────────────────────────────────────────────────

class DeployWizard(QDialog):
    """3-step dialog: Source → Details → Progress."""

    deployed = pyqtSignal(dict)   # emitted with completed app dict

    def __init__(self, admin_config: dict, process_manager, caddy_manager, parent=None):
        super().__init__(parent)
        self._cfg   = admin_config
        self._procs = process_manager
        self._caddy = caddy_manager
        self._zip_path = ""
        self._worker: _Worker = None

        self.setWindowTitle("Deploy New App")
        self.setFixedWidth(520)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")

        self._stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._stack.addWidget(self._page_source())    # 0
        self._stack.addWidget(self._page_details())   # 1
        self._stack.addWidget(self._page_progress())  # 2

    # ── Page 0: Source ────────────────────────────────────────────────────────

    def _page_source(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(16)

        v.addWidget(_lbl("Deploy New App", C_TEXT, 16, bold=True))
        v.addWidget(_lbl("Choose your app source.", C_TEXT3, 12))
        v.addWidget(_sep())

        self._rb_zip = QRadioButton("Upload ZIP archive")
        self._rb_git = QRadioButton("Clone from Git repository")
        for rb in (self._rb_zip, self._rb_git):
            rb.setStyleSheet(
                f"QRadioButton{{color:{C_TEXT2};font-size:13px;spacing:8px;}}"
                f"QRadioButton::indicator{{width:15px;height:15px;"
                f"border-radius:8px;border:2px solid {C_BORDER2};}}"
                f"QRadioButton::indicator:checked{{background:{C_BLUE};"
                f"border:2px solid {C_BLUE};}}"
            )
            v.addWidget(rb)
        self._rb_zip.setChecked(True)

        # ZIP picker
        self._zip_widget = QWidget()
        zw = QHBoxLayout(self._zip_widget)
        zw.setContentsMargins(0, 0, 0, 0)
        self._zip_lbl = _inp(placeholder="No file selected")
        self._zip_lbl.setReadOnly(True)
        browse = _btn("Browse...", C_SURFACE2, C_BORDER2, C_TEXT2, h=32)
        browse.clicked.connect(self._pick_zip)
        zw.addWidget(self._zip_lbl)
        zw.addWidget(browse)
        v.addWidget(self._zip_widget)

        # Git fields
        self._git_widget = QWidget()
        gw = QVBoxLayout(self._git_widget)
        gw.setContentsMargins(0, 0, 0, 0)
        gw.setSpacing(8)
        self._git_url    = _inp(placeholder="https://github.com/org/app.git")
        self._git_branch = _inp(placeholder="main", val="main")
        for lbl, fld in [("Git URL", self._git_url), ("Branch", self._git_branch)]:
            gw.addWidget(_lbl(lbl.upper(), C_TEXT3, 10))
            gw.addWidget(fld)
        self._git_widget.setVisible(False)
        v.addWidget(self._git_widget)

        self._rb_zip.toggled.connect(lambda on: (
            self._zip_widget.setVisible(on),
            self._git_widget.setVisible(not on)
        ))

        v.addStretch()

        btns = QHBoxLayout()
        cancel = _btn("Cancel", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        nxt    = _btn("Next →", h=36)
        cancel.clicked.connect(self.reject)
        nxt.clicked.connect(self._go_details)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(nxt)
        v.addLayout(btns)
        return w

    def _pick_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ZIP", "", "ZIP Archives (*.zip)"
        )
        if path:
            self._zip_path = path
            self._zip_lbl.setText(path)

    def _go_details(self):
        if self._rb_zip.isChecked() and not self._zip_path:
            QMessageBox.warning(self, "No File", "Select a ZIP file first.")
            return
        if self._rb_git.isChecked() and not self._git_url.text().strip():
            QMessageBox.warning(self, "No URL", "Enter a Git repository URL.")
            return
        self._stack.setCurrentIndex(1)

    # ── Page 1: Details ───────────────────────────────────────────────────────

    def _page_details(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(14)

        v.addWidget(_lbl("App Details", C_TEXT, 16, bold=True))
        v.addWidget(_lbl("Configure your app's identity.", C_TEXT3, 12))
        v.addWidget(_sep())

        v.addWidget(_lbl("PROJECT SLUG", C_TEXT3, 10))
        self._slug_inp = _inp(placeholder="inventory (lowercase, hyphens ok)")
        v.addWidget(self._slug_inp)

        self._slug_preview = _lbl("", C_BLUE, 11)
        v.addWidget(self._slug_preview)
        self._slug_inp.textChanged.connect(self._update_preview)

        v.addWidget(_lbl("DISPLAY NAME", C_TEXT3, 10))
        self._name_inp = _inp(placeholder="Inventory Manager")
        v.addWidget(self._name_inp)

        self._detail_err = _lbl("", C_RED, 11)
        self._detail_err.setVisible(False)
        v.addWidget(self._detail_err)
        v.addStretch()

        btns = QHBoxLayout()
        back  = _btn("← Back", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        start = _btn("Deploy →", "#166534", "#15803d", "#86efac", h=36)
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        start.clicked.connect(self._start_deploy)
        btns.addStretch()
        btns.addWidget(back)
        btns.addWidget(start)
        v.addLayout(btns)
        return w

    def _update_preview(self, text: str):
        slug = text.strip().lower()
        if slug:
            self._slug_preview.setText(f"→ http://{slug}.pgops.test")
        else:
            self._slug_preview.setText("")

    def _start_deploy(self):
        slug    = self._slug_inp.text().strip().lower()
        display = self._name_inp.text().strip() or slug

        from core.app_manager import validate_slug
        ok, err = validate_slug(slug)
        if not ok:
            self._detail_err.setText(err)
            self._detail_err.setVisible(True)
            return
        self._detail_err.setVisible(False)

        self._deploy_slug    = slug
        self._deploy_display = display
        self._stack.setCurrentIndex(2)
        QTimer.singleShot(200, self._run_deploy)

    # ── Page 2: Progress ──────────────────────────────────────────────────────

    def _page_progress(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(14)

        self._prog_title = _lbl("Deploying…", C_TEXT, 16, bold=True)
        v.addWidget(self._prog_title)
        v.addWidget(_sep())

        self._steps_container = QWidget()
        self._steps_container.setStyleSheet("background:transparent;")
        self._steps_layout = QVBoxLayout(self._steps_container)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(6)
        v.addWidget(self._steps_container)

        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 0)   # indeterminate
        self._prog_bar.setFixedHeight(3)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_BLUE};}}"
        )
        v.addWidget(self._prog_bar)

        self._result_lbl = _lbl("", C_TEXT2, 12)
        self._result_lbl.setWordWrap(True)
        self._result_lbl.setVisible(False)
        v.addWidget(self._result_lbl)

        v.addStretch()

        self._done_btns = QHBoxLayout()
        self._btn_open   = _btn("Open in Browser", C_BLUE, "#3b7de8", h=36)
        self._btn_close2 = _btn("Close", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        self._btn_rollback = _btn("Rollback", "#7f1d1d", "#991b1b", "#fca5a5", h=36)
        self._btn_open.clicked.connect(self._open_app)
        self._btn_close2.clicked.connect(self.accept)
        self._btn_rollback.clicked.connect(self._rollback)
        for b in (self._btn_open, self._btn_close2, self._btn_rollback):
            self._done_btns.addWidget(b)
            b.setVisible(False)
        v.addLayout(self._done_btns)
        return w

    def _add_step_row(self, label: str, status: str) -> QLabel:
        icon_map = {"running": "⏳", "done": "✓", "error": "✗"}
        color_map = {"running": C_AMBER, "done": C_GREEN, "error": C_RED}
        icon  = icon_map.get(status, "·")
        color = color_map.get(status, C_TEXT3)

        row = QHBoxLayout()
        row.setSpacing(8)
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(18)
        icon_lbl.setStyleSheet(f"color:{color};font-size:13px;background:transparent;")
        text_lbl = QLabel(label)
        text_lbl.setStyleSheet(f"color:{C_TEXT2};font-size:12px;background:transparent;")

        row.addWidget(icon_lbl)
        row.addWidget(text_lbl)
        row.addStretch()

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        container.setLayout(row)
        self._steps_layout.addWidget(container)
        return icon_lbl   # caller can update icon_lbl text/color

    def _run_deploy(self):
        self._step_widgets: dict[str, QLabel] = {}

        source_type = "zip" if self._rb_zip.isChecked() else "git"
        source_path = self._zip_path if source_type == "zip" else self._git_url.text().strip()
        git_branch  = self._git_branch.text().strip() or "main"

        def _work(progress_cb):
            from core.app_manager import provision_app

            def _prog(step, status):
                progress_cb(step, status)

            app = provision_app(
                slug=self._deploy_slug,
                display_name=self._deploy_display,
                source_type=source_type,
                source_path=source_path,
                git_branch=git_branch,
                admin_config=self._cfg,
                progress=_prog,
            )
            # Start process
            _prog("Starting app server", "running")
            ok, msg = self._procs.start_app(app)
            if not ok:
                raise RuntimeError(f"App server failed to start: {msg}")
            _prog("Starting app server", "done")

            _prog("Updating Caddy configuration", "running")
            from core.app_manager import load_apps
            self._caddy.update_apps(load_apps())
            _prog("Updating Caddy configuration", "done")

            return app

        self._worker = _Worker(_work)
        self._worker.progress.connect(self._on_step)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_step(self, step: str, status: str):
        if step not in self._step_widgets:
            lbl = self._add_step_row(step, status)
            self._step_widgets[step] = lbl
        else:
            icon_map  = {"running": "⏳", "done": "✓", "error": "✗"}
            color_map = {"running": C_AMBER, "done": C_GREEN, "error": C_RED}
            lbl = self._step_widgets[step]
            lbl.setText(icon_map.get(status, "·"))
            lbl.setStyleSheet(
                f"color:{color_map.get(status, C_TEXT3)};"
                f"font-size:13px;background:transparent;"
            )

    def _on_done(self, app, error: str):
        self._prog_bar.setRange(0, 1)
        self._prog_bar.setValue(1)

        if error:
            self._prog_title.setText("Deployment Failed")
            self._prog_title.setStyleSheet(
                f"color:{C_RED};font-size:16px;font-weight:700;background:transparent;"
            )
            self._result_lbl.setText(error)
            self._result_lbl.setStyleSheet(
                f"color:{C_RED};font-size:12px;background:transparent;"
            )
            self._result_lbl.setVisible(True)
            self._btn_rollback.setVisible(True)
            self._btn_close2.setVisible(True)
            self._deploy_app = None
        else:
            self._deploy_app = app
            self._prog_title.setText("Deployment Complete!")
            self._prog_title.setStyleSheet(
                f"color:{C_GREEN};font-size:16px;font-weight:700;background:transparent;"
            )
            self._result_lbl.setText(
                f"Your app is live at:\nhttp://{app['domain']}"
            )
            self._result_lbl.setStyleSheet(
                f"color:{C_TEXT2};font-size:12px;background:transparent;"
            )
            self._result_lbl.setVisible(True)
            self._btn_open.setVisible(True)
            self._btn_close2.setVisible(True)
            self.deployed.emit(app)

    def _open_app(self):
        if self._deploy_app:
            webbrowser.open(f"http://{self._deploy_app['domain']}")

    def _rollback(self):
        if not hasattr(self, "_deploy_slug"):
            self.reject()
            return
        try:
            from core.app_manager import delete_app
            self._procs.stop_app(self._deploy_slug)
            delete_app(self._deploy_slug, self._cfg)
        except Exception:
            pass
        self.reject()


# ── App Logs Dialog ───────────────────────────────────────────────────────────

class AppLogsDialog(QDialog):
    def __init__(self, app: dict, process_manager, parent=None):
        super().__init__(parent)
        self._app   = app
        self._procs = process_manager
        self.setWindowTitle(f"Logs — {app.get('display_name', app['id'])}")
        self.setFixedSize(700, 460)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setStyleSheet(
            f"background:#0a0f1e;color:{C_GREEN};"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:11px;border:1px solid {C_BORDER};border-radius:6px;padding:8px;"
        )
        v.addWidget(self._log_box)

        row = QHBoxLayout()
        clr = _btn("Clear", C_SURFACE2, C_BORDER2, C_TEXT2, h=28)
        clr.clicked.connect(self._log_box.clear)
        close = _btn("Close", C_SURFACE2, C_BORDER2, C_TEXT2, h=28)
        close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(clr)
        row.addWidget(close)
        v.addLayout(row)

        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _refresh(self):
        lines = self._procs.get_logs(self._app["id"], 200)
        self._log_box.setPlainText("".join(lines))
        sb = self._log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)


# ── Apps Tab ──────────────────────────────────────────────────────────────────

class AppsTab(QWidget):
    """
    Main Apps tab widget.
    Instantiate with AppsTab(config, process_manager, caddy_manager)
    """

    def __init__(self, config: dict, process_manager, caddy_manager, parent=None):
        super().__init__(parent)
        self._cfg   = config
        self._procs = process_manager
        self._caddy = caddy_manager
        self._workers = []
        self._build()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(5000)
        QTimer.singleShot(600, self.refresh)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header_bar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:#1a1d23;border:none;")

        body = QWidget()
        body.setStyleSheet("background:#1a1d23;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(28, 24, 28, 28)
        bv.setSpacing(18)

        page_title = _lbl("Web Applications", C_TEXT, 22, bold=True)
        page_sub   = _lbl(
            "Deploy and manage Laravel apps. Each app gets its own database, bucket, and subdomain.",
            C_TEXT3, 12
        )
        bv.addWidget(page_title)
        bv.addWidget(page_sub)

        # App table card
        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        # Table header row
        th = QWidget()
        th.setFixedHeight(44)
        th.setStyleSheet(
            f"background:{C_SURFACE2};border-bottom:1px solid {C_BORDER};"
            f"border-radius:10px 10px 0 0;"
        )
        thh = QHBoxLayout(th)
        thh.setContentsMargins(20, 0, 16, 0)
        thh.setSpacing(0)
        for col, width in [
            ("APP NAME", 220), ("DOMAIN", 240),
            ("STATUS", 90), ("DATABASE", 150), ("ACTIONS", 0),
        ]:
            lbl = QLabel(col)
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1.2px;background:transparent;"
            )
            if width:
                lbl.setFixedWidth(width)
            else:
                lbl.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
            thh.addWidget(lbl)
        cv.addWidget(th)

        # ── FIX: empty label lives directly in the card layout, NOT in rows_layout ──
        self._empty_lbl = QLabel(
            "No apps deployed yet. Click  +  Deploy New App  to get started."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;padding:40px;background:transparent;"
        )
        cv.addWidget(self._empty_lbl)

        # Rows container is a separate sibling — shown/hidden independently
        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background:transparent;")
        self._rows_container.setVisible(False)
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        cv.addWidget(self._rows_container)

        bv.addWidget(card)
        bv.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll)

    def _header_bar(self):
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet(f"background:{C_BG};border-bottom:1px solid {C_BORDER};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 0, 24, 0)
        h.setSpacing(12)

        self._summary_lbl = _lbl("", C_TEXT3, 12)
        h.addWidget(self._summary_lbl)
        h.addStretch()

        refresh_btn = _btn("↻  Refresh", C_SURFACE2, C_BORDER2, C_TEXT2, h=30)
        refresh_btn.clicked.connect(self.refresh)
        h.addWidget(refresh_btn)

        deploy_btn = QPushButton("  +  Deploy New App")
        deploy_btn.setFixedHeight(34)
        deploy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        deploy_btn.setStyleSheet(
            "QPushButton{"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #4f8ef7, stop:1 #2563eb);"
            "  color:white;border:none;border-radius:7px;"
            "  font-size:13px;font-weight:700;padding:0 18px;"
            "}"
            "QPushButton:hover{"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #3b7de8, stop:1 #1d4ed8);"
            "}"
        )
        deploy_btn.clicked.connect(self._deploy)
        h.addWidget(deploy_btn)
        return bar

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        from core.app_manager import load_apps
        apps = load_apps()
        status_map = self._procs.status_map()

        # Sync live status
        for app in apps:
            live = status_map.get(app["id"])
            if live:
                app["status"] = live

        # Clear existing rows safely — _empty_lbl is NOT in this layout
        while self._rows_layout.count():
            child = self._rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        running = sum(1 for a in apps if a.get("status") == "running")
        self._summary_lbl.setText(
            f"{len(apps)} apps  ·  {running} running" if apps else "No apps deployed"
        )

        if not apps:
            self._empty_lbl.setVisible(True)
            self._rows_container.setVisible(False)
            return

        self._empty_lbl.setVisible(False)
        self._rows_container.setVisible(True)
        for app in apps:
            self._rows_layout.addWidget(self._make_row(app))

    def _make_row(self, app: dict):
        row_w = QWidget()
        row_w.setFixedHeight(56)
        row_w.setStyleSheet(
            f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};"
        )
        row = QHBoxLayout(row_w)
        row.setContentsMargins(20, 0, 16, 0)
        row.setSpacing(0)

        # Name
        name_lbl = QLabel(app.get("display_name", app["id"]))
        name_lbl.setFixedWidth(220)
        name_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:700;background:transparent;"
        )
        row.addWidget(name_lbl)

        # Domain (clickable)
        domain   = app.get("domain", "")
        dom_btn  = QPushButton(domain)
        dom_btn.setFixedWidth(240)
        dom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dom_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_BLUE};"
            f"border:none;font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;text-align:left;}}"
            f"QPushButton:hover{{color:#93c5fd;}}"
        )
        dom_btn.clicked.connect(lambda _=False, d=domain: webbrowser.open(f"http://{d}"))
        row.addWidget(dom_btn)

        # Status badge
        status = app.get("status", "stopped")
        color  = C_GREEN if status == "running" else C_RED if status == "error" else C_TEXT3
        bg     = "#0a2016" if status == "running" else "#2a0d0d" if status == "error" else C_SURFACE2
        st_lbl = QLabel(status.upper())
        st_lbl.setFixedWidth(90)
        st_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        st_lbl.setStyleSheet(
            f"color:{color};background:{bg};border:1px solid {color}44;"
            f"border-radius:4px;font-size:9px;font-weight:800;"
            f"letter-spacing:0.8px;padding:2px 6px;"
        )
        row.addWidget(st_lbl)

        # DB name
        db_lbl = QLabel(app.get("database", "—"))
        db_lbl.setFixedWidth(150)
        db_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        row.addWidget(db_lbl)

        row.addStretch()

        # Action buttons
        app_id = app["id"]
        is_running = status == "running"

        for text, fn, btn_bg, btn_hov, btn_fg in [
            ("Start",   lambda _=False, a=app: self._start(a),
             "#166534", "#15803d", "#86efac"),
            ("Stop",    lambda _=False, a=app: self._stop(a),
             "#7f1d1d", "#991b1b", "#fca5a5"),
            ("Restart", lambda _=False, a=app: self._restart(a),
             C_SURFACE2, C_BORDER2, C_TEXT2),
            ("Logs",    lambda _=False, a=app: self._show_logs(a),
             C_SURFACE2, C_BORDER2, C_TEXT2),
            ("Pull",    lambda _=False, a=app: self._pull(a),
             C_SURFACE2, C_BORDER2, C_TEXT2),
            ("Delete",  lambda _=False, a=app: self._delete(a),
             C_SURFACE2, C_BORDER2, C_RED),
        ]:
            b = _btn(text, btn_bg, btn_hov, btn_fg, h=28)
            b.setFixedWidth(56)
            if text == "Start":
                b.setEnabled(not is_running)
            elif text == "Stop":
                b.setEnabled(is_running)
            b.clicked.connect(fn)
            row.addWidget(b)

        return row_w

    # ── Actions ───────────────────────────────────────────────────────────────

    def _deploy(self):
        dlg = DeployWizard(self._cfg, self._procs, self._caddy, self)
        dlg.deployed.connect(lambda _: self.refresh())
        dlg.exec()

    def _start(self, app: dict):
        from core.app_manager import set_app_status, load_apps
        ok, msg = self._procs.start_app(app)
        if ok:
            set_app_status(app["id"], "running")
            self._caddy.update_apps(load_apps())
        self.refresh()

    def _stop(self, app: dict):
        from core.app_manager import set_app_status, load_apps
        self._procs.stop_app(app["id"])
        set_app_status(app["id"], "stopped")
        self._caddy.update_apps(load_apps())
        self.refresh()

    def _restart(self, app: dict):
        ok, msg = self._procs.restart_app(app["id"], app)
        self.refresh()

    def _show_logs(self, app: dict):
        dlg = AppLogsDialog(app, self._procs, self)
        dlg.exec()

    def _pull(self, app: dict):
        if not app.get("git_remote"):
            QMessageBox.information(
                self, "No Git Remote",
                "This app was deployed from a ZIP and has no git remote configured."
            )
            return

        reply = QMessageBox.question(
            self, "Pull Latest",
            f"Pull latest from {app['git_remote']} ({app.get('git_branch','main')})?\n"
            "This will run migrations and restart the app.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def work(_prog):
            from core.app_manager import pull_app, load_apps
            def _p(step, status): _prog(step, status)
            a = pull_app(app["id"], progress=_p)
            self._procs.restart_app(app["id"], a)
            self._caddy.update_apps(load_apps())
            return True

        w = _Worker(work)
        w.done.connect(lambda ok, err: (
            QMessageBox.critical(self, "Pull Failed", err) if err else None,
            self.refresh()
        ))
        w.start()
        self._workers.append(w)

    def _delete(self, app: dict):
        reply = QMessageBox.question(
            self, "Delete App",
            f"Permanently delete '{app.get('display_name', app['id'])}'?\n\n"
            "This will:\n"
            f"  • Delete all app files in {app.get('folder','')}\n"
            f"  • Drop database '{app.get('database','')}'\n"
            f"  • Drop MinIO bucket '{app.get('bucket','')}'\n\n"
            "This CANNOT be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def work(_prog):
            from core.app_manager import delete_app, load_apps
            self._procs.stop_app(app["id"])
            delete_app(app["id"], self._cfg)
            self._caddy.update_apps(load_apps())
            return True

        w = _Worker(work)
        w.done.connect(lambda ok, err: (
            QMessageBox.critical(self, "Error", err) if err else None,
            self.refresh()
        ))
        w.start()
        self._workers.append(w)