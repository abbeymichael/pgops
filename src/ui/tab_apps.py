import os
import platform
import subprocess
import webbrowser
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDialog, QDialogButtonBox, QFileDialog,
    QRadioButton, QButtonGroup, QFrame, QScrollArea,
    QTextEdit, QProgressBar, QMessageBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QApplication, QSizePolicy, QCheckBox, QGroupBox,
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


# ── PHP Extension Manager Dialog ──────────────────────────────────────────────

class PHPExtensionDialog(QDialog):
    """
    Shows all PHP extensions known to this FrankenPHP build.
    The user can check/uncheck which ones this specific app should load.
    On Save the per-app ini is rebuilt and the registry is updated.
    """

    extensions_saved = pyqtSignal(list)   # emits the new list of extension names

    def __init__(self, app: dict, process_manager, parent=None):
        super().__init__(parent)
        self._app   = app
        self._procs = process_manager
        self._checks: dict[str, QCheckBox] = {}

        self.setWindowTitle(f"PHP Extensions — {app.get('display_name', app['id'])}")
        self.setMinimumWidth(560)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(14)

        v.addWidget(_lbl("PHP Extensions", C_TEXT, 15, bold=True))
        v.addWidget(_lbl(
            "Check the extensions this app should activate. "
            "Extensions marked  ⬤ compiled  are always on. "
            "Extensions marked  ◎ loadable  require a .so file.",
            C_TEXT3, 11,
        ))
        v.addWidget(_sep())

        # Scrollable list of extensions
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background:{C_SURFACE2};border-radius:6px;")
        scroll.setFixedHeight(340)

        inner = QWidget()
        inner.setStyleSheet(f"background:{C_SURFACE2};")
        self._ext_layout = QVBoxLayout(inner)
        self._ext_layout.setContentsMargins(12, 10, 12, 10)
        self._ext_layout.setSpacing(4)
        scroll.setWidget(inner)
        v.addWidget(scroll)

        self._status_lbl = _lbl("", C_TEXT3, 11)
        v.addWidget(self._status_lbl)
        v.addWidget(_sep())

        # Buttons
        row = QHBoxLayout()
        save_btn   = _btn("Save & Rebuild INI", C_BLUE, "#3b7de8", h=36)
        cancel_btn = _btn("Cancel", C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(save_btn)
        v.addLayout(row)

        self._load_extensions()

    def _load_extensions(self):
        # Clear
        while self._ext_layout.count():
            child = self._ext_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._checks.clear()

        currently_enabled = set(self._app.get("php_extensions", []))

        try:
            all_exts = self._procs.list_extensions()
        except Exception as exc:
            self._ext_layout.addWidget(_lbl(f"Could not load extensions: {exc}", C_RED))
            return

        if not all_exts:
            self._ext_layout.addWidget(
                _lbl("No extensions found. Is FrankenPHP installed?", C_AMBER)
            )
            return

        compiled_count = sum(1 for e in all_exts if e["status"] == "active")
        loadable_count = sum(1 for e in all_exts if e["status"] == "loadable")
        self._status_lbl.setText(
            f"{compiled_count} compiled-in  ·  {loadable_count} loadable from .so"
        )

        # Group: compiled-in
        if any(e["status"] == "active" for e in all_exts):
            self._ext_layout.addWidget(
                _lbl("COMPILED-IN  (always active)", C_TEXT3, 9)
            )
            for ext in sorted(all_exts, key=lambda x: x["name"]):
                if ext["status"] != "active":
                    continue
                row = self._make_ext_row(ext, currently_enabled, locked=True)
                self._ext_layout.addWidget(row)
            self._ext_layout.addWidget(_sep())

        # Group: loadable
        if any(e["status"] == "loadable" for e in all_exts):
            self._ext_layout.addWidget(
                _lbl("LOADABLE  (via extension .so)", C_TEXT3, 9)
            )
            for ext in sorted(all_exts, key=lambda x: x["name"]):
                if ext["status"] != "loadable":
                    continue
                row = self._make_ext_row(ext, currently_enabled, locked=False)
                self._ext_layout.addWidget(row)

        self._ext_layout.addStretch()

    def _make_ext_row(self, ext: dict, currently_enabled: set, locked: bool) -> QWidget:
        name   = ext["name"]
        status = ext["status"]
        source = ext.get("source", "")

        row_w = QWidget()
        row_w.setStyleSheet("background:transparent;")
        row   = QHBoxLayout(row_w)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)

        cb = QCheckBox()
        cb.setChecked(name in currently_enabled or locked)
        cb.setEnabled(not locked)
        cb.setStyleSheet(
            f"QCheckBox::indicator{{width:15px;height:15px;"
            f"border-radius:3px;border:2px solid {C_BORDER2};}}"
            f"QCheckBox::indicator:checked{{background:{C_BLUE};"
            f"border:2px solid {C_BLUE};}}"
            f"QCheckBox::indicator:disabled{{background:{C_SURFACE};"
            f"border:2px solid {C_BORDER};}}"
        )
        self._checks[name] = cb
        row.addWidget(cb)

        # Status dot
        dot_color = C_GREEN if status == "active" else C_BLUE
        dot_char  = "⬤" if status == "active" else "◎"
        dot = _lbl(dot_char, dot_color, 10)
        dot.setFixedWidth(16)
        row.addWidget(dot)

        name_lbl = _lbl(name, C_TEXT if not locked else C_TEXT2, 12)
        name_lbl.setMinimumWidth(160)
        row.addWidget(name_lbl)

        if source and source.startswith("so:"):
            path_lbl = _lbl(source[3:], C_TEXT3, 10)
            path_lbl.setWordWrap(False)
            row.addWidget(path_lbl, stretch=1)
        else:
            row.addStretch()

        return row_w

    def _save(self):
        # Collect ticked extensions (compiled always included implicitly by FrankenPHP)
        selected = [name for name, cb in self._checks.items() if cb.isChecked()]

        try:
            from core.frankenphp_manager import (
                ensure_app_php_ini, get_frankenphp_bin
            )
            ini_path, missing = ensure_app_php_ini(
                self._app["id"], set(selected), str(get_frankenphp_bin())
            )
        except Exception as exc:
            QMessageBox.critical(self, "INI Error", f"Failed to rebuild PHP ini:\n{exc}")
            return

        # Persist to registry
        from core.app_manager import set_app_php_extensions
        set_app_php_extensions(self._app["id"], selected)

        if missing:
            QMessageBox.warning(
                self, "Missing Extensions",
                "The following extensions are checked but have no .so file:\n\n"
                + "\n".join(f"  • {e}" for e in sorted(missing))
                + "\n\nThey will be skipped. Place the .so files in the "
                  "FrankenPHP extensions directory and save again."
            )

        self.extensions_saved.emit(selected)
        self.accept()


# ── Deploy Wizard ─────────────────────────────────────────────────────────────

class DeployWizard(QDialog):
    """3-step dialog: Source → Details → Progress."""

    deployed = pyqtSignal(dict)

    def __init__(self, admin_config: dict, process_manager, caddy_manager, parent=None):
        super().__init__(parent)
        self._cfg      = admin_config
        self._procs    = process_manager
        self._caddy    = caddy_manager
        self._zip_path = ""
        self._worker: _Worker = None
        self._deploy_app = None

        self.setWindowTitle("Deploy New App")
        self.setFixedWidth(520)
        # Prevent the wizard from growing taller than the available screen area,
        # which causes Qt geometry warnings on smaller / high-DPI displays.
        screen = QApplication.primaryScreen()
        if screen:
            available_h = screen.availableGeometry().height()
            self.setMaximumHeight(min(available_h - 80, 900))
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

        # ── Stack type ────────────────────────────────────────────────────────
        v.addWidget(_lbl("STACK TYPE", C_TEXT3, 10))

        # Explicit button group keeps stack radios isolated from source radios
        self._stack_group = QButtonGroup(w)

        stack_row = QHBoxLayout()
        stack_row.setSpacing(10)
        self._rb_stack_laravel = QRadioButton("Laravel (PHP)")
        self._rb_stack_static  = QRadioButton("Static HTML")
        self._rb_stack_other   = QRadioButton("Other")
        self._rb_stack_laravel.setChecked(True)

        _stack_rb_style = (
            f"QRadioButton{{color:{C_TEXT2};font-size:13px;spacing:8px;}}"
            f"QRadioButton::indicator{{width:15px;height:15px;"
            f"border-radius:8px;border:2px solid {C_BORDER2};}}"
            f"QRadioButton::indicator:checked{{background:{C_BLUE};"
            f"border:2px solid {C_BLUE};}}"
        )
        for rb in (self._rb_stack_laravel, self._rb_stack_static, self._rb_stack_other):
            rb.setStyleSheet(_stack_rb_style)
            self._stack_group.addButton(rb)
            stack_row.addWidget(rb)
        stack_row.addStretch()
        v.addLayout(stack_row)

        # Hint label that updates with stack selection
        self._stack_hint = _lbl(
            "Provisions PostgreSQL database, SeaweedFS S3 bucket, and PHP environment.",
            C_TEXT3, 11,
        )
        self._stack_hint.setWordWrap(True)
        v.addWidget(self._stack_hint)

        def _update_stack_hint():
            if self._rb_stack_laravel.isChecked():
                self._stack_hint.setText(
                    "Provisions PostgreSQL database, SeaweedFS S3 bucket, and PHP environment."
                )
            elif self._rb_stack_static.isChecked():
                self._stack_hint.setText(
                    "Serves static files only — no database, bucket, or PHP runtime."
                )
            else:
                self._stack_hint.setText(
                    "Generic deployment — files only. No database or bucket provisioned."
                )

        self._rb_stack_laravel.toggled.connect(lambda _: _update_stack_hint())
        self._rb_stack_static.toggled.connect(lambda _: _update_stack_hint())
        self._rb_stack_other.toggled.connect(lambda _: _update_stack_hint())

        v.addWidget(_sep())

        # ── Source ────────────────────────────────────────────────────────────
        v.addWidget(_lbl("SOURCE", C_TEXT3, 10))

        # Explicit button group keeps source radios isolated from stack radios
        self._source_group = QButtonGroup(w)

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
            self._source_group.addButton(rb)
            v.addWidget(rb)
        self._rb_zip.setChecked(True)

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

        self._git_widget = QWidget()
        gw = QVBoxLayout(self._git_widget)
        gw.setContentsMargins(0, 0, 0, 0)
        gw.setSpacing(8)
        self._git_url    = _inp(placeholder="https://github.com/org/app.git")
        self._git_branch = _inp(placeholder="main", val="main")
        for lbl_text, fld in [("Git URL", self._git_url), ("Branch", self._git_branch)]:
            gw.addWidget(_lbl(lbl_text.upper(), C_TEXT3, 10))
            gw.addWidget(fld)
        self._git_widget.setVisible(False)
        v.addWidget(self._git_widget)

        self._rb_zip.toggled.connect(lambda on: (
            self._zip_widget.setVisible(on),
            self._git_widget.setVisible(not on),
        ))

        v.addStretch()
        btns   = QHBoxLayout()
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

        btns  = QHBoxLayout()
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
        self._slug_preview.setText(f"→ http://{slug}.pgops.local" if slug else "")

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
        self._steps_layout.addStretch()

        steps_scroll = QScrollArea()
        steps_scroll.setWidgetResizable(True)
        steps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        steps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        steps_scroll.setStyleSheet("background:transparent;border:none;")
        steps_scroll.setMaximumHeight(300)
        steps_scroll.setWidget(self._steps_container)
        v.addWidget(steps_scroll)

        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 0)
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

        self._done_btns  = QHBoxLayout()
        self._btn_open   = _btn("Open in Browser", C_BLUE,    "#3b7de8",          h=36)
        self._btn_close2 = _btn("Close",           C_SURFACE2, C_BORDER2, C_TEXT2, h=36)
        self._btn_rollback = _btn("Rollback & Delete", "#7f1d1d", "#991b1b", "#fca5a5", h=36)
        self._btn_open.clicked.connect(self._open_app)
        self._btn_close2.clicked.connect(self.accept)
        self._btn_rollback.clicked.connect(self._rollback)
        for b in (self._btn_open, self._btn_close2, self._btn_rollback):
            self._done_btns.addWidget(b)
            b.setVisible(False)
        v.addLayout(self._done_btns)
        return w

    def _add_step_row(self, label: str, status: str) -> QLabel:
        icon_map  = {"running": "⏳", "done": "✓", "error": "✗"}
        color_map = {"running": C_AMBER, "done": C_GREEN, "error": C_RED}

        row    = QHBoxLayout()
        row.setSpacing(8)
        icon_lbl = QLabel(icon_map.get(status, "·"))
        icon_lbl.setFixedWidth(18)
        icon_lbl.setStyleSheet(
            f"color:{color_map.get(status, C_TEXT3)};font-size:13px;background:transparent;"
        )
        text_lbl = QLabel(label)
        text_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;background:transparent;"
        )
        row.addWidget(icon_lbl)
        row.addWidget(text_lbl)
        row.addStretch()

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        container.setLayout(row)
        # Insert before the trailing stretch so rows stack top-to-bottom
        insert_pos = max(0, self._steps_layout.count() - 1)
        self._steps_layout.insertWidget(insert_pos, container)
        return icon_lbl

    def _run_deploy(self):
        self._step_widgets: dict[str, QLabel] = {}

        source_type = "zip" if self._rb_zip.isChecked() else "git"
        source_path = self._zip_path if source_type == "zip" else self._git_url.text().strip()
        git_branch  = self._git_branch.text().strip() or "main"

        if self._rb_stack_laravel.isChecked():
            stack_type = "laravel"
        elif self._rb_stack_static.isChecked():
            stack_type = "static"
        else:
            stack_type = "other"

        def _work(progress_cb):
            from core.app_manager import provision_app

            app = provision_app(
                slug=self._deploy_slug,
                display_name=self._deploy_display,
                source_type=source_type,
                source_path=source_path,
                git_branch=git_branch,
                admin_config=self._cfg,
                progress=progress_cb,
                stack_type=stack_type,
            )

            # Start process — use the saved php_extensions from the app record
            progress_cb("Starting app server", "running")
            required = set(app.get("php_extensions", []))
            ok, msg  = self._procs.start_app(app, required_extensions=required or None)
            if not ok:
                raise RuntimeError(f"App server failed to start: {msg}")
            progress_cb("Starting app server", "done")

            progress_cb("Updating Caddy configuration", "running")
            from core.app_manager import load_apps, set_app_status
            set_app_status(app["id"], "running")
            self._caddy.update_apps(load_apps())
            progress_cb("Updating Caddy configuration", "done")

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
            # provision_app already rolled back internally; show rollback btn for
            # any manual cleanup that may still be needed.
            self._btn_rollback.setVisible(True)
            self._btn_close2.setVisible(True)
            self._deploy_app = None
        else:
            self._deploy_app = app
            self._prog_title.setText("Deployment Complete!")
            self._prog_title.setStyleSheet(
                f"color:{C_GREEN};font-size:16px;font-weight:700;background:transparent;"
            )
            self._result_lbl.setText(f"Your app is live at:\nhttp://{app['domain']}")
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
        """Manual rollback — calls delete_app which cleans files, DB, bucket, ini."""
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


# ── Artisan Dialog ────────────────────────────────────────────────────────────

class _ArtisanWorker(QThread):
    """
    Runs one artisan command via subprocess.Popen and streams output
    line-by-line back to the UI thread so the terminal feels live.
    """
    line_ready  = pyqtSignal(str)   # each output line as it arrives
    finished_ok = pyqtSignal(int)   # exit code when process ends

    def __init__(self, cmd: list[str], cwd: str, env: dict):
        super().__init__()
        self._cmd  = cmd
        self._cwd  = cwd
        self._env  = env
        self._proc = None

    def run(self):
        try:
            kwargs = {}
            if platform.system() == "Windows":
                import subprocess as sp
                kwargs["creationflags"] = sp.CREATE_NO_WINDOW

            self._proc = subprocess.Popen(
                self._cmd,
                cwd=self._cwd,
                env=self._env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs,
            )
            for line in self._proc.stdout:
                self.line_ready.emit(line.rstrip("\n"))
            self._proc.wait()
            self.finished_ok.emit(self._proc.returncode)
        except Exception as exc:
            self.line_ready.emit(f"[ERROR] Could not launch artisan: {exc}")
            self.finished_ok.emit(-1)

    def kill(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass


class ArtisanDialog(QDialog):
    """
    Modal artisan command runner with live streaming output terminal.

    Organised into command groups:
      Keys        — key:generate
      Migrations  — migrate, migrate:fresh, migrate:rollback, migrate:status
      Seeding     — db:seed, migrate:fresh --seed
      Caches      — config:cache, route:cache, view:cache, cache:clear,
                    config:clear, route:clear, view:clear
      Queue       — queue:work (runs until stopped), queue:restart
      Custom      — free-text input for any artisan command
    """

    # (button_label, args_list, confirm_msg_or_None, is_destructive)
    _COMMANDS: list[tuple] = [
        # ── Keys ──────────────────────────────────────────────────────────────
        ("key:generate",
         ["key:generate"],
         None, False),

        # ── Migrations ────────────────────────────────────────────────────────
        ("migrate",
         ["migrate", "--force"],
         None, False),

        ("migrate:fresh",
         ["migrate:fresh", "--force"],
         "⚠  This will DROP all tables and re-run every migration.\n"
         "All data in the database will be lost.\n\nContinue?",
         True),

        ("migrate:fresh --seed",
         ["migrate:fresh", "--seed", "--force"],
         "⚠  This will DROP all tables, re-run every migration, "
         "and re-seed the database.\nAll data will be lost.\n\nContinue?",
         True),

        ("migrate:rollback",
         ["migrate:rollback", "--force"],
         "Roll back the last batch of migrations?",
         True),

        ("migrate:rollback --step=1",
         ["migrate:rollback", "--step=1", "--force"],
         None, False),

        ("migrate:status",
         ["migrate:status"],
         None, False),

        # ── Seeding ───────────────────────────────────────────────────────────
        ("db:seed",
         ["db:seed", "--force"],
         None, False),

        # ── Caches ────────────────────────────────────────────────────────────
        ("config:cache",   ["config:cache"],   None, False),
        ("route:cache",    ["route:cache"],    None, False),
        ("view:cache",     ["view:cache"],     None, False),
        ("cache:clear",    ["cache:clear"],    None, False),
        ("config:clear",   ["config:clear"],   None, False),
        ("route:clear",    ["route:clear"],    None, False),
        ("view:clear",     ["view:clear"],     None, False),
        ("optimize",       ["optimize"],       None, False),
        ("optimize:clear", ["optimize:clear"], None, False),

        # ── Queue ─────────────────────────────────────────────────────────────
        ("queue:restart",
         ["queue:restart"],
         None, False),

        # ── Storage / links ───────────────────────────────────────────────────
        ("storage:link",
         ["storage:link"],
         None, False),
    ]

    # Groups: (heading, list of command labels that belong to it)
    _GROUPS = [
        ("Keys",      ["key:generate"]),
        ("Migrations",["migrate", "migrate:fresh", "migrate:fresh --seed",
                       "migrate:rollback", "migrate:rollback --step=1",
                       "migrate:status"]),
        ("Seeding",   ["db:seed"]),
        ("Caches",    ["config:cache", "route:cache", "view:cache",
                       "cache:clear", "config:clear", "route:clear",
                       "view:clear", "optimize", "optimize:clear"]),
        ("Queue",     ["queue:restart"]),
        ("Storage",   ["storage:link"]),
    ]

    def __init__(self, app: dict, parent=None):
        super().__init__(parent)
        self._app    = app
        self._worker: _ArtisanWorker = None

        title = app.get("display_name", app["id"])
        self.setWindowTitle(f"Artisan — {title}")
        self.setMinimumSize(860, 620)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left sidebar: command buttons ────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(230)
        sidebar.setStyleSheet(
            f"background:{C_BG};border-right:1px solid {C_BORDER};"
        )
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        # Sidebar header
        hdr = QWidget()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{C_BG};border-bottom:1px solid {C_BORDER};")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(16, 0, 16, 0)
        icon_lbl = QLabel("⚡")
        icon_lbl.setStyleSheet(f"color:{C_AMBER};font-size:16px;background:transparent;")
        name_lbl = QLabel("Artisan")
        name_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent;"
        )
        hh.addWidget(icon_lbl)
        hh.addSpacing(6)
        hh.addWidget(name_lbl)
        hh.addStretch()
        sv.addWidget(hdr)

        # Scrollable button list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"background:{C_BG};border:none;")

        cmd_lookup = {row[0]: row for row in self._COMMANDS}

        inner = QWidget()
        inner.setStyleSheet(f"background:{C_BG};")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 8, 0, 8)
        iv.setSpacing(0)

        for group_name, cmd_labels in self._GROUPS:
            grp_lbl = QLabel(f"  {group_name.upper()}")
            grp_lbl.setFixedHeight(28)
            grp_lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:9px;font-weight:700;"
                f"letter-spacing:1.4px;background:transparent;"
                f"padding-left:16px;"
            )
            iv.addWidget(grp_lbl)

            for label in cmd_labels:
                if label not in cmd_lookup:
                    continue
                _, args, confirm, destructive = cmd_lookup[label]
                fg = C_RED if destructive else C_TEXT2
                btn = QPushButton(f"  {label}")
                btn.setFixedHeight(34)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{fg};"
                    f"border:none;font-size:12px;font-family:'Consolas','Courier New',monospace;"
                    f"text-align:left;padding-left:20px;}}"
                    f"QPushButton:hover{{background:{C_SURFACE};color:{C_TEXT};}}"
                    f"QPushButton:disabled{{color:{C_TEXT3};}}"
                )
                btn.clicked.connect(
                    lambda _=False, a=args, c=confirm, lb=label:
                        self._run_command(a, c, lb)
                )
                iv.addWidget(btn)

            iv.addSpacing(4)

        iv.addStretch()

        # ── Custom command row ────────────────────────────────────────────────
        custom_sep = QFrame()
        custom_sep.setFrameShape(QFrame.Shape.HLine)
        custom_sep.setFixedHeight(1)
        custom_sep.setStyleSheet(f"background:{C_BORDER};border:none;")
        iv.addWidget(custom_sep)

        custom_lbl = QLabel("  CUSTOM")
        custom_lbl.setFixedHeight(28)
        custom_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:9px;font-weight:700;"
            f"letter-spacing:1.4px;background:transparent;padding-left:16px;"
        )
        iv.addWidget(custom_lbl)

        self._custom_inp = QLineEdit()
        self._custom_inp.setPlaceholderText("e.g. make:model Post -m")
        self._custom_inp.setFixedHeight(30)
        self._custom_inp.setStyleSheet(
            f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:5px;padding:0 8px;color:{C_TEXT};"
            f"font-family:'Consolas','Courier New',monospace;font-size:12px;"
            f"margin:0 8px;}}"
            f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
        )
        self._custom_inp.returnPressed.connect(self._run_custom)
        iv.addWidget(self._custom_inp)
        iv.addSpacing(4)

        run_custom_btn = QPushButton("▶  Run Custom")
        run_custom_btn.setFixedHeight(30)
        run_custom_btn.setFixedWidth(198)
        run_custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        run_custom_btn.setStyleSheet(
            f"QPushButton{{background:{C_BLUE};color:white;border:none;"
            f"border-radius:5px;font-size:12px;font-weight:700;"
            f"margin:0 16px;}}"
            f"QPushButton:hover{{background:#3b7de8;}}"
        )
        run_custom_btn.clicked.connect(self._run_custom)

        custom_btn_row = QHBoxLayout()
        custom_btn_row.setContentsMargins(16, 0, 16, 0)
        custom_btn_row.addWidget(run_custom_btn)
        custom_btn_row.addStretch()
        iv.addLayout(custom_btn_row)
        iv.addSpacing(8)

        scroll.setWidget(inner)
        sv.addWidget(scroll)
        root.addWidget(sidebar)

        # ── Right panel: terminal output ─────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{C_SURFACE};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        # Terminal header
        term_hdr = QWidget()
        term_hdr.setFixedHeight(52)
        term_hdr.setStyleSheet(
            f"background:{C_BG};border-bottom:1px solid {C_BORDER};"
        )
        thh = QHBoxLayout(term_hdr)
        thh.setContentsMargins(16, 0, 16, 0)
        thh.setSpacing(10)

        self._cmd_badge = QLabel("No command run yet")
        self._cmd_badge.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;"
        )
        thh.addWidget(self._cmd_badge)
        thh.addStretch()

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;background:transparent;"
        )
        self._status_lbl = QLabel("idle")
        self._status_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        thh.addWidget(self._status_dot)
        thh.addWidget(self._status_lbl)

        self._kill_btn = _btn("■ Stop", "#7f1d1d", "#991b1b", "#fca5a5", h=28)
        self._kill_btn.setFixedWidth(64)
        self._kill_btn.setVisible(False)
        self._kill_btn.clicked.connect(self._kill_worker)
        thh.addWidget(self._kill_btn)

        clear_btn = _btn("Clear", C_SURFACE2, C_BORDER2, C_TEXT2, h=28)
        clear_btn.setFixedWidth(52)
        clear_btn.clicked.connect(self._clear_terminal)
        thh.addWidget(clear_btn)
        rv.addWidget(term_hdr)

        # Terminal body
        self._terminal = QTextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setStyleSheet(
            f"QTextEdit{{background:#0a0f1e;color:#e2e8f0;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;border:none;padding:12px;"
            f"selection-background-color:{C_BLUE}44;}}"
        )
        self._terminal.setPlaceholderText(
            "Select a command from the left panel to run it here.\n"
            "Output streams live as the command executes."
        )
        rv.addWidget(self._terminal)

        # Bottom bar
        bot = QWidget()
        bot.setFixedHeight(44)
        bot.setStyleSheet(
            f"background:{C_BG};border-top:1px solid {C_BORDER};"
        )
        bh = QHBoxLayout(bot)
        bh.setContentsMargins(16, 0, 16, 0)
        bh.setSpacing(10)

        self._exit_lbl = QLabel("")
        self._exit_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;"
        )
        bh.addWidget(self._exit_lbl)
        bh.addStretch()

        close_btn = _btn("Close", C_SURFACE2, C_BORDER2, C_TEXT2, h=30)
        close_btn.setFixedWidth(70)
        close_btn.clicked.connect(self._safe_close)
        bh.addWidget(close_btn)
        rv.addWidget(bot)

        root.addWidget(right)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_artisan_env(self) -> dict:
        """Build the subprocess environment for artisan, honouring the per-app ini."""
        env = {**os.environ, "APP_ENV": "production"}
        try:
            from core.frankenphp_manager import get_app_php_ini_path
            p = get_app_php_ini_path(self._app["id"])
            if p.exists():
                env["PHP_INI_SCAN_DIR"] = str(p.parent)
        except Exception:
            pass
        return env

    def _get_php_bin(self) -> str:
        from core.frankenphp_manager import get_frankenphp_bin
        return str(get_frankenphp_bin())

    def _set_status(self, text: str, color: str):
        self._status_dot.setStyleSheet(
            f"color:{color};font-size:10px;background:transparent;"
        )
        self._status_lbl.setStyleSheet(
            f"color:{color};font-size:11px;background:transparent;"
        )
        self._status_lbl.setText(text)

    def _append(self, line: str):
        """Append one line to the terminal, auto-coloring known prefixes."""
        lo = line.lower()
        if any(k in lo for k in ("error", "fail", "exception", "fatal")):
            color = "#f87171"   # red
        elif any(k in lo for k in ("warning", "warn", "deprecated")):
            color = "#fbbf24"   # amber
        elif any(k in lo for k in ("migrat", "done", "success", "generated",
                                    "seeded", "cached", "cleared", "created",
                                    "linked", "restarted")):
            color = "#4ade80"   # green
        elif line.startswith("  ") or line.startswith("INFO"):
            color = "#93c5fd"   # blue
        else:
            color = "#e2e8f0"   # default

        # Escape HTML special chars so the rich text engine doesn't choke
        safe = (line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
        self._terminal.append(
            f'<span style="color:{color};white-space:pre;">{safe}</span>'
        )
        sb = self._terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_terminal(self):
        self._terminal.clear()
        self._exit_lbl.setText("")

    def _kill_worker(self):
        if self._worker:
            self._worker.kill()

    def _safe_close(self):
        self._kill_worker()
        self.accept()

    # ── Command dispatch ──────────────────────────────────────────────────────

    def _run_command(self, args: list[str], confirm_msg: str | None, label: str):
        """Validate, optionally confirm, then launch the artisan worker."""
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(
                self, "Busy",
                "A command is already running.\nStop it first or wait for it to finish."
            )
            return

        if confirm_msg:
            reply = QMessageBox.question(
                self, "Confirm", confirm_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        app_folder = self._app.get("folder", "")
        if not app_folder or not Path(app_folder).exists():
            QMessageBox.critical(
                self, "Error",
                f"App folder not found:\n{app_folder}\n\nIs the app still deployed?"
            )
            return

        try:
            php_bin = self._get_php_bin()
        except Exception as exc:
            QMessageBox.critical(self, "FrankenPHP not found", str(exc))
            return

        cmd = [php_bin, "php-cli", "artisan"] + args
        env = self._get_artisan_env()

        # Header separator
        self._append(f"\n{'─' * 60}")
        self._append(f"$ php artisan {' '.join(args)}")
        self._append(f"{'─' * 60}")

        self._cmd_badge.setText(f"php artisan {' '.join(args)}")
        self._exit_lbl.setText("")
        self._set_status("running", C_AMBER)
        self._kill_btn.setVisible(True)

        self._worker = _ArtisanWorker(cmd, app_folder, env)
        self._worker.line_ready.connect(self._append)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.start()

    def _run_custom(self):
        raw = self._custom_inp.text().strip()
        if not raw:
            return
        # Split safely — don't use shell=True; just naive split is fine for
        # artisan args which don't use shell quoting in practice.
        parts = raw.split()
        # Strip leading "artisan", "php artisan", or "php-cli artisan" if typed
        if parts and parts[0] == "artisan":
            parts = parts[1:]
        elif len(parts) >= 2 and parts[0] in ("php", "php-cli") and parts[1] == "artisan":
            parts = parts[2:]
        elif len(parts) >= 3 and parts[0] in ("php", "php-cli") and parts[1] == "artisan":
            parts = parts[2:]
        if not parts:
            return
        self._run_command(parts, None, raw)

    def _on_finished(self, exit_code: int):
        self._kill_btn.setVisible(False)
        if exit_code == 0:
            self._set_status("done", C_GREEN)
            self._exit_lbl.setText(f"exit 0  ✓")
            self._exit_lbl.setStyleSheet(
                f"color:{C_GREEN};font-size:11px;"
                f"font-family:'Consolas','Courier New',monospace;"
                f"background:transparent;"
            )
        else:
            self._set_status(f"exit {exit_code}", C_RED)
            self._exit_lbl.setText(f"exit {exit_code}  ✗")
            self._exit_lbl.setStyleSheet(
                f"color:{C_RED};font-size:11px;"
                f"font-family:'Consolas','Courier New',monospace;"
                f"background:transparent;"
            )
        self._append(f"\n[Process exited with code {exit_code}]")

    def closeEvent(self, e):
        self._kill_worker()
        super().closeEvent(e)


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

        row   = QHBoxLayout()
        clr   = _btn("Clear",  C_SURFACE2, C_BORDER2, C_TEXT2, h=28)
        close = _btn("Close",  C_SURFACE2, C_BORDER2, C_TEXT2, h=28)
        clr.clicked.connect(self._log_box.clear)
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
        self._cfg     = config
        self._procs   = process_manager
        self._caddy   = caddy_manager
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
            C_TEXT3, 12,
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
            ("APP NAME", 200), ("DOMAIN", 220),
            ("STATUS", 80), ("DATABASE", 140), ("ACTIONS", 0),
        ]:
            lbl = QLabel(col)
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1.2px;background:transparent;"
            )
            if width:
                lbl.setFixedWidth(width)
            else:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            thh.addWidget(lbl)
        cv.addWidget(th)

        self._empty_lbl = QLabel(
            "No apps deployed yet. Click  +  Deploy New App  to get started."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;padding:40px;background:transparent;"
        )
        cv.addWidget(self._empty_lbl)

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
        apps       = load_apps()
        status_map = self._procs.status_map()

        for app in apps:
            live = status_map.get(app["id"])
            if live:
                app["status"] = live

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
        name_lbl.setFixedWidth(200)
        name_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:700;background:transparent;"
        )
        row.addWidget(name_lbl)

        # Domain (clickable)
        domain  = app.get("domain", "")
        dom_btn = QPushButton(domain)
        dom_btn.setFixedWidth(220)
        dom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dom_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_BLUE};"
            f"border:none;font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;text-align:left;}}"
            f"QPushButton:hover{{color:#93c5fd;}}"
        )
        dom_btn.clicked.connect(lambda _=False, d=domain: webbrowser.open(f"http://{d}"))
        row.addWidget(dom_btn)

        # Stack badge
        stack_type = app.get("stack_type", "laravel")
        stack_labels = {"laravel": "PHP", "static": "HTML", "other": "OTHER"}
        stack_colors = {"laravel": C_BLUE, "static": C_GREEN, "other": C_AMBER}
        stack_text  = stack_labels.get(stack_type, stack_type.upper())
        stack_color = stack_colors.get(stack_type, C_TEXT3)
        sk_lbl = QLabel(stack_text)
        sk_lbl.setFixedWidth(46)
        sk_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sk_lbl.setStyleSheet(
            f"color:{stack_color};background:{stack_color}22;"
            f"border:1px solid {stack_color}55;"
            f"border-radius:4px;font-size:9px;font-weight:800;"
            f"letter-spacing:0.8px;padding:2px 4px;"
        )
        row.addWidget(sk_lbl)

        # Status badge
        status = app.get("status", "stopped")
        color  = C_GREEN if status == "running" else C_RED if status == "error" else C_TEXT3
        bg     = "#0a2016" if status == "running" else "#2a0d0d" if status == "error" else C_SURFACE2
        st_lbl = QLabel(status.upper())
        st_lbl.setFixedWidth(80)
        st_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        st_lbl.setStyleSheet(
            f"color:{color};background:{bg};border:1px solid {color}44;"
            f"border-radius:4px;font-size:9px;font-weight:800;"
            f"letter-spacing:0.8px;padding:2px 6px;"
        )
        row.addWidget(st_lbl)

        # DB name — only meaningful for Laravel apps
        db_text = app.get("database", "—") if stack_type == "laravel" else "—"
        db_lbl = QLabel(db_text)
        db_lbl.setFixedWidth(140)
        db_lbl.setStyleSheet(
            f"color:{C_TEXT2 if stack_type == 'laravel' else C_TEXT3};font-size:12px;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        row.addWidget(db_lbl)
        row.addStretch()

        # Action buttons
        is_running = status == "running"

        btn_defs = [
            ("Start",   lambda _=False, a=app: self._start(a),
             "#166534", "#15803d", "#86efac"),
            ("Stop",    lambda _=False, a=app: self._stop(a),
             "#7f1d1d", "#991b1b", "#fca5a5"),
            ("Restart", lambda _=False, a=app: self._restart(a),
             C_SURFACE2, C_BORDER2, C_TEXT2),
            ("PHP",     lambda _=False, a=app: self._php_extensions(a),
             C_SURFACE2, C_BORDER2, C_AMBER),
            ("Artisan", lambda _=False, a=app: self._artisan(a),
             C_SURFACE2, C_BORDER2, "#a78bfa"),   # soft purple — distinct from other btns
            ("Logs",    lambda _=False, a=app: self._show_logs(a),
             C_SURFACE2, C_BORDER2, C_TEXT2),
            ("Pull",    lambda _=False, a=app: self._pull(a),
             C_SURFACE2, C_BORDER2, C_TEXT2),
            ("Delete",  lambda _=False, a=app: self._delete(a),
             C_SURFACE2, C_BORDER2, C_RED),
        ]

        for text, fn, btn_bg, btn_hov, btn_fg in btn_defs:
            b = _btn(text, btn_bg, btn_hov, btn_fg, h=28)
            b.setFixedWidth(58)
            if text == "Start":
                b.setEnabled(not is_running)
            elif text == "Stop":
                b.setEnabled(is_running)
            # PHP ext manager and Artisan are Laravel-only
            elif text in ("PHP", "Artisan") and stack_type != "laravel":
                b.setVisible(False)
            b.clicked.connect(fn)
            row.addWidget(b)

        return row_w

    # ── Actions ───────────────────────────────────────────────────────────────

    def _deploy(self):
        dlg = DeployWizard(self._cfg, self._procs, self._caddy, self)
        dlg.deployed.connect(lambda _: self.refresh())
        dlg.exec()

    def _start(self, app: dict):
        """Start a stopped app — rebuild its ini then launch the process."""
        from core.app_manager import set_app_status, load_apps, get_app_by_id
        # Reload app from registry to get latest php_extensions
        fresh = get_app_by_id(app["id"]) or app
        required = set(fresh.get("php_extensions", []))
        ok, msg  = self._procs.start_app(fresh, required_extensions=required or None)
        if ok:
            set_app_status(fresh["id"], "running")
            self._caddy.update_apps(load_apps())
        else:
            QMessageBox.warning(self, "Start Failed", msg)
        self.refresh()

    def _stop(self, app: dict):
        from core.app_manager import set_app_status, load_apps
        self._procs.stop_app(app["id"])
        set_app_status(app["id"], "stopped")
        self._caddy.update_apps(load_apps())
        self.refresh()

    def _restart(self, app: dict):
        """Stop then start, honouring the saved php_extensions."""
        from core.app_manager import set_app_status, load_apps, get_app_by_id
        fresh    = get_app_by_id(app["id"]) or app
        required = set(fresh.get("php_extensions", []))
        ok, msg  = self._procs.restart_app(
            fresh["id"], fresh,
            required_extensions=required or None,
        )
        if ok:
            set_app_status(fresh["id"], "running")
            self._caddy.update_apps(load_apps())
        else:
            QMessageBox.warning(self, "Restart Failed", msg)
        self.refresh()

    def _php_extensions(self, app: dict):
        """Open the PHP extension manager popup for this app."""
        from core.app_manager import get_app_by_id, load_apps, set_app_status

        fresh = get_app_by_id(app["id"]) or app
        dlg   = PHPExtensionDialog(fresh, self._procs, self)

        def _on_saved(new_exts: list):
            # Offer to restart if app is currently running
            if fresh.get("status") == "running" or self._procs.is_running(fresh["id"]):
                reply = QMessageBox.question(
                    self,
                    "Restart Required",
                    "PHP extension settings have changed.\n"
                    "Restart the app now to apply them?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._restart(fresh)

        dlg.extensions_saved.connect(_on_saved)
        dlg.exec()
        self.refresh()

    def _artisan(self, app: dict):
        """Open the Artisan command runner modal for this app."""
        from core.app_manager import get_app_by_id
        fresh = get_app_by_id(app["id"]) or app
        dlg = ArtisanDialog(fresh, self)
        dlg.exec()

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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def work(progress_cb):
            from core.app_manager import pull_app, load_apps, get_app_by_id
            a = pull_app(app["id"], progress=progress_cb)
            fresh    = get_app_by_id(app["id"]) or a
            required = set(fresh.get("php_extensions", []))
            self._procs.restart_app(app["id"], fresh, required_extensions=required or None)
            self._caddy.update_apps(load_apps())
            return True

        w = _Worker(work)
        w.done.connect(lambda ok, err: (
            QMessageBox.critical(self, "Pull Failed", err) if err else None,
            self.refresh(),
        ))
        w.start()
        self._workers.append(w)

    def _delete(self, app: dict):
        stack_type = app.get("stack_type", "laravel")
        is_laravel = stack_type == "laravel"

        extra_lines = ""
        if is_laravel:
            extra_lines = (
                f"  • Drop database '{app.get('database','')}' and its user\n"
                f"  • Drop SeaweedFS bucket '{app.get('bucket','')}'\n"
                f"  • Remove the PHP ini configuration\n"
            )

        reply = QMessageBox.question(
            self, "Delete App",
            f"Permanently delete '{app.get('display_name', app['id'])}'?\n\n"
            "This will:\n"
            f"  • Delete all app files in {app.get('folder','')}\n"
            + extra_lines +
            "\nThis CANNOT be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def work(_prog):
            from core.app_manager import delete_app, load_apps
            self._procs.stop_app(app["id"])
            delete_app(app["id"], self._cfg, progress=_prog)
            self._caddy.update_apps(load_apps())
            return True

        w = _Worker(work)
        w.done.connect(lambda ok, err: (
            QMessageBox.critical(self, "Error", err) if err else None,
            self.refresh(),
        ))
        w.start()
        self._workers.append(w)