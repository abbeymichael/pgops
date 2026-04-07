from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QProgressBar, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

import core.db_manager as dbm
from ui.theme import (
    C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, C_AMBER, C_RED,
    TABLE_STYLE,
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


def _group(title):
    from PyQt6.QtWidgets import QGroupBox
    g = QGroupBox(title)
    from PyQt6.QtWidgets import QVBoxLayout as _V
    _V(g).setSpacing(8)
    g.setStyleSheet(
        f"QGroupBox{{border:1px solid {C_BORDER};border-radius:8px;"
        f"margin-top:14px;padding:12px 12px 10px 12px;"
        f"font-size:10px;color:{C_TEXT3};letter-spacing:1px;}}"
        f"QGroupBox::title{{subcontrol-origin:margin;left:12px;"
        f"padding:0 6px;color:{C_TEXT3};font-size:10px;letter-spacing:1.5px;}}"
    )
    return g


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C_BORDER};border:none;")
    return f


class _Worker(QThread):
    done     = pyqtSignal(bool, str)
    progress = pyqtSignal(int)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
            if isinstance(result, tuple):
                ok  = bool(result[0])
                msg = str(result[1]) if len(result) > 1 else ""
            elif result is None:
                ok, msg = True, ""
            else:
                ok, msg = bool(result), ""
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class BackupTab(QWidget):
    """
    Standalone Backup & Restore page.
    Public API:
      populate_dbs(list_of_str)       — called when db list changes
      set_selected_path(Path|None)    — set from outside if needed
    Callbacks passed in:
      on_backup(dbname, dest_dir, prog_cb) -> (bool, str)
      on_restore(path, dbname, prog_cb)   -> (bool, str)
      on_log(msg)
    """

    def __init__(self, config,
                 on_backup, on_restore, on_refresh_dbs, on_log,
                 parent=None):
        super().__init__(parent)
        self.config            = config
        self._on_backup        = on_backup
        self._on_restore       = on_restore
        self._on_refresh_dbs   = on_refresh_dbs
        self._on_log           = on_log
        self._selected_path    = None
        self._workers          = []
        self._build()

    def update_config(self, config):
        self.config = config

    def populate_dbs(self, names):
        self.bk_db_combo.blockSignals(True)
        cur = self.bk_db_combo.currentText()
        self.bk_db_combo.clear()
        for n in names:
            self.bk_db_combo.addItem(n)
        idx = self.bk_db_combo.findText(cur)
        if idx >= 0:
            self.bk_db_combo.setCurrentIndex(idx)
        self.bk_db_combo.blockSignals(False)

    def refresh_backup_list(self):
        self._refresh_backups()

    def _build(self):
        from PyQt6.QtWidgets import QScrollArea
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

        # ── Page header ────────────────────────────────────────────────────────
        title = QLabel("Backup & Restore")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:22px;font-weight:800;background:transparent;"
        )
        sub = QLabel("Create and restore compressed PostgreSQL backups.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        # ── Backup card ────────────────────────────────────────────────────────
        bk_card = QWidget()
        bk_card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        bkv = QVBoxLayout(bk_card)
        bkv.setContentsMargins(22, 20, 22, 20)
        bkv.setSpacing(14)

        bk_title = QLabel("Backup Database")
        bk_title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        bkv.addWidget(bk_title)
        bkv.addWidget(_sep())

        r1 = QHBoxLayout()
        r1.addWidget(_lbl("Database"))
        r1.addSpacing(8)
        self.bk_db_combo = QComboBox()
        self.bk_db_combo.setFixedHeight(34)
        self.bk_db_combo.setStyleSheet(
            f"QComboBox{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:0 10px;color:{C_TEXT};font-size:12px;}}"
            f"QComboBox::drop-down{{border:none;}}"
            f"QComboBox QAbstractItemView{{background:{C_SURFACE2};color:{C_TEXT};"
            f"selection-background-color:{C_BORDER2};}}"
        )
        r1.addWidget(self.bk_db_combo)
        r1.addStretch()
        bkv.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(_lbl("Save to"))
        r2.addSpacing(8)
        self.bk_dir_lbl = QLineEdit(str(dbm.BACKUP_DIR))
        self.bk_dir_lbl.setReadOnly(True)
        self.bk_dir_lbl.setFixedHeight(34)
        self.bk_dir_lbl.setStyleSheet(
            f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:0 11px;color:{C_TEXT2};font-size:12px;}}"
        )
        browse_btn = _btn("Browse...", C_SURFACE2, C_BORDER2, C_TEXT2, h=34)
        browse_btn.clicked.connect(self._browse_dir)
        r2.addWidget(self.bk_dir_lbl)
        r2.addWidget(browse_btn)
        bkv.addLayout(r2)

        self.bk_prog = QProgressBar()
        self.bk_prog.setVisible(False)
        self.bk_prog.setFixedHeight(3)
        self.bk_prog.setTextVisible(False)
        self.bk_prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_GREEN};}}"
        )
        bkv.addWidget(self.bk_prog)

        self.btn_backup = _btn("Backup Now", C_BLUE, "#3b7de8", h=40)
        self.btn_backup.clicked.connect(self._do_backup)
        bkv.addWidget(self.btn_backup)
        v.addWidget(bk_card)

        # ── Restore card ───────────────────────────────────────────────────────
        rs_card = QWidget()
        rs_card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        rsv = QVBoxLayout(rs_card)
        rsv.setContentsMargins(22, 20, 22, 20)
        rsv.setSpacing(14)

        rs_title = QLabel("Restore Database")
        rs_title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        rsv.addWidget(rs_title)
        rsv.addWidget(_sep())

        tb2 = QHBoxLayout()
        self.btn_rs_refresh = _btn("↻  Refresh List", C_SURFACE2, C_BORDER2, C_TEXT2, h=32)
        self.btn_rs_browse  = _btn("Open File...", C_SURFACE2, C_BORDER2, C_TEXT2, h=32)
        self.btn_rs_refresh.clicked.connect(self._refresh_backups)
        self.btn_rs_browse.clicked.connect(self._browse_file)
        tb2.addWidget(self.btn_rs_refresh)
        tb2.addWidget(self.btn_rs_browse)
        tb2.addStretch()
        rsv.addLayout(tb2)

        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["File", "Size (MB)", "Created"])
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setAlternatingRowColors(True)
        self.backup_table.setStyleSheet(TABLE_STYLE)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setMaximumHeight(180)
        self.backup_table.itemSelectionChanged.connect(self._on_selected)
        rsv.addWidget(self.backup_table)

        r3 = QHBoxLayout()
        r3.addWidget(_lbl("Restore into"))
        r3.addSpacing(8)
        self.rs_db_inp = QLineEdit()
        self.rs_db_inp.setPlaceholderText("database name (existing or new)")
        self.rs_db_inp.setFixedHeight(34)
        self.rs_db_inp.setStyleSheet(
            f"QLineEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:0 11px;color:{C_TEXT};font-size:12px;}}"
            f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
        )
        r3.addWidget(self.rs_db_inp)
        rsv.addLayout(r3)

        self.rs_prog = QProgressBar()
        self.rs_prog.setVisible(False)
        self.rs_prog.setFixedHeight(3)
        self.rs_prog.setTextVisible(False)
        self.rs_prog.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;}}"
            f"QProgressBar::chunk{{background:{C_AMBER};}}"
        )
        rsv.addWidget(self.rs_prog)

        self.btn_restore = _btn("Restore Selected Backup", "#6d28d9", "#7c3aed", h=40)
        self.btn_restore.clicked.connect(self._do_restore)
        rsv.addWidget(self.btn_restore)
        v.addWidget(rs_card)
        v.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self._refresh_backups()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Backup Folder", str(dbm.BACKUP_DIR))
        if d:
            self.bk_dir_lbl.setText(d)

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Backup File", str(dbm.BACKUP_DIR),
            "Dump Files (*.dump);;All Files (*)"
        )
        if f:
            self._selected_path = Path(f)
            self.rs_db_inp.setText(Path(f).stem.rsplit("_", 2)[0])
            self._on_log(f"Selected: {f}")

    def _refresh_backups(self):
        backups = dbm.list_backups()
        self.backup_table.setRowCount(0)
        for b in backups:
            row = self.backup_table.rowCount()
            self.backup_table.insertRow(row)
            item = QTableWidgetItem(b["name"])
            item.setData(Qt.ItemDataRole.UserRole, str(b["path"]))
            self.backup_table.setItem(row, 0, item)
            self.backup_table.setItem(row, 1, QTableWidgetItem(str(b["size_mb"])))
            self.backup_table.setItem(row, 2, QTableWidgetItem(b["modified"]))

    def _on_selected(self):
        row = self.backup_table.currentRow()
        if row >= 0:
            item = self.backup_table.item(row, 0)
            if item:
                path_str = item.data(Qt.ItemDataRole.UserRole)
                self._selected_path = Path(path_str) if path_str else None
                if path_str:
                    self.rs_db_inp.setText(Path(path_str).stem.rsplit("_", 2)[0])

    def _do_backup(self):
        dbname = self.bk_db_combo.currentText()
        if not dbname:
            QMessageBox.warning(self, "No Database", "No databases available."); return
        dest = Path(self.bk_dir_lbl.text())
        self.bk_prog.setVisible(True)
        self.bk_prog.setValue(0)
        self.btn_backup.setEnabled(False)
        cfg = self.config

        def fn(prog_cb):
            return dbm.backup_database(
                dbname, cfg["username"], cfg["password"], cfg["port"],
                dest_dir=dest, progress_callback=prog_cb
            )

        def done(ok, msg):
            self.bk_prog.setVisible(False)
            self.btn_backup.setEnabled(True)
            self._on_log(msg)
            self._refresh_backups()
            if not ok:
                QMessageBox.critical(self, "Backup Failed", msg)

        w = _Worker(fn)
        w.done.connect(done)
        w.progress.connect(self.bk_prog.setValue)
        w.start()
        self._workers.append(w)

    def _do_restore(self):
        if not self._selected_path:
            QMessageBox.warning(self, "No Backup", "Select a backup file first."); return
        dbname = self.rs_db_inp.text().strip()
        if not dbname:
            QMessageBox.warning(self, "No Target", "Enter a database name to restore into."); return
        if QMessageBox.question(self, "Restore",
            f"Restore '{self._selected_path.name}' into '{dbname}'?\nExisting data will be replaced.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes: return

        self.rs_prog.setVisible(True)
        self.rs_prog.setValue(0)
        self.btn_restore.setEnabled(False)
        cfg  = self.config
        path = self._selected_path

        def fn(prog_cb):
            return dbm.restore_database(
                path, dbname, cfg["username"], cfg["password"], cfg["port"],
                progress_callback=prog_cb
            )

        def done(ok, msg):
            self.rs_prog.setVisible(False)
            self.btn_restore.setEnabled(True)
            self._on_log(msg)
            self._on_refresh_dbs()
            if not ok:
                QMessageBox.critical(self, "Restore Failed", msg)

        w = _Worker(fn)
        w.done.connect(done)
        w.progress.connect(self.rs_prog.setValue)
        w.start()
        self._workers.append(w)
