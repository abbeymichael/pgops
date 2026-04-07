from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDialog, QDialogButtonBox, QMessageBox,
    QScrollArea, QFrame, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QApplication, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

import core.db_manager as dbm
from ui.theme import (
    C_BG, C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
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


def _inp(val="", pw=False, placeholder="", mono=False):
    f = QLineEdit(val)
    if pw:
        f.setEchoMode(QLineEdit.EchoMode.Password)
    if placeholder:
        f.setPlaceholderText(placeholder)
    ff = "'Consolas','Courier New',monospace" if mono else "inherit"
    f.setStyleSheet(
        f"QLineEdit{{background:{C_SURFACE};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:7px 11px;color:{C_TEXT};"
        f"font-size:13px;font-family:{ff};}}"
        f"QLineEdit:focus{{border:1px solid {C_BLUE};}}"
    )
    return f


def _lbl(text, color=C_TEXT2, size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;background:transparent;")
    return l


class _Worker(QThread):
    result = pyqtSignal(object, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn(), "")
        except Exception as e:
            self.result.emit(None, str(e))


class CreateDbDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Database")
        self.setFixedWidth(420)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(12)

        title = QLabel("New Database")
        title.setStyleSheet(f"color:{C_TEXT};font-size:16px;font-weight:700;background:transparent;")
        v.addWidget(title)
        sub = QLabel("Create an isolated PostgreSQL database with its own owner credentials.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        v.addWidget(sub)
        v.addSpacing(4)

        for lbl_text, attr, pw in [
            ("Database Name", "db_name", False),
            ("Owner Username", "owner", False),
            ("Owner Password", "password", True),
            ("Confirm Password", "confirm", True),
        ]:
            lbl = QLabel(lbl_text.upper())
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1.2px;background:transparent;"
            )
            v.addWidget(lbl)
            field = _inp(pw=pw)
            setattr(self, attr, field)
            v.addWidget(field)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(f"color:{C_RED};font-size:11px;background:transparent;")
        self.error_lbl.setVisible(False)
        v.addWidget(self.error_lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;padding:6px 18px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};}}"
        )
        v.addWidget(btns)

    def _validate(self):
        name = self.db_name.text().strip()
        owner = self.owner.text().strip()
        pw = self.password.text()
        if not name or not owner or not pw:
            self.error_lbl.setText("All fields required.")
            self.error_lbl.setVisible(True); return
        if pw != self.confirm.text():
            self.error_lbl.setText("Passwords do not match.")
            self.error_lbl.setVisible(True); return
        if " " in name or " " in owner:
            self.error_lbl.setText("No spaces allowed.")
            self.error_lbl.setVisible(True); return
        self.accept()

    def values(self):
        return self.db_name.text().strip(), self.owner.text().strip(), self.password.text()


class ChangePwDialog(QDialog):
    def __init__(self, role, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Change Password — {role}")
        self.setFixedWidth(380)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(10)

        title = QLabel(f"Change Password")
        title.setStyleSheet(f"color:{C_TEXT};font-size:16px;font-weight:700;background:transparent;")
        v.addWidget(title)
        sub = QLabel(f"Set a new password for the role: {role}")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:11px;background:transparent;")
        v.addWidget(sub)
        v.addSpacing(4)

        for lbl_text, attr in [("New Password", "pw"), ("Confirm Password", "cf")]:
            lbl = QLabel(lbl_text.upper())
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1.2px;background:transparent;"
            )
            v.addWidget(lbl)
            field = _inp(pw=True)
            setattr(self, attr, field)
            v.addWidget(field)

        self.err = QLabel("")
        self.err.setStyleSheet(f"color:{C_RED};font-size:11px;background:transparent;")
        self.err.setVisible(False)
        v.addWidget(self.err)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;padding:6px 18px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};}}"
        )
        v.addWidget(btns)

    def _validate(self):
        if not self.pw.text():
            self.err.setText("Empty."); self.err.setVisible(True); return
        if self.pw.text() != self.cf.text():
            self.err.setText("Passwords do not match."); self.err.setVisible(True); return
        self.accept()

    def value(self):
        return self.pw.text()


class _DbRow(QWidget):
    """
    A single database row matching the mockup:
    [● name] [owner] [••• password] [conn string box + copy] [Change Password] [Drop]
    """
    change_pw_clicked = pyqtSignal(str)
    drop_clicked      = pyqtSignal(str)

    def __init__(self, name, owner, conn_str, parent=None):
        super().__init__(parent)
        self._name = name
        self.setStyleSheet(
            f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 16, 0)
        row.setSpacing(0)

        # ● name
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{C_GREEN};font-size:10px;background:transparent;margin-right:8px;")
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"color:{C_BLUE};font-size:13px;font-weight:700;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        name_lbl.setFixedWidth(200)
        row.addWidget(dot)
        row.addWidget(name_lbl)

        # owner
        owner_lbl = QLabel(owner)
        owner_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;background:transparent;"
        )
        owner_lbl.setFixedWidth(150)
        row.addWidget(owner_lbl)

        # password dots
        pw_lbl = QLabel("• " * 10)
        pw_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;letter-spacing:2px;background:transparent;"
        )
        pw_lbl.setFixedWidth(160)
        row.addWidget(pw_lbl)

        # connection string box with copy
        conn_box = QWidget()
        conn_box.setFixedWidth(260)
        conn_box.setStyleSheet(
            f"background:{C_SURFACE2};border:1px solid {C_BORDER};"
            f"border-radius:6px;"
        )
        cb = QHBoxLayout(conn_box)
        cb.setContentsMargins(10, 0, 4, 0)
        cb.setSpacing(4)
        short_conn = conn_str[:28] + "..." if len(conn_str) > 28 else conn_str
        conn_lbl = QLabel(short_conn)
        conn_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:11px;"
            f"font-family:'Consolas','Courier New',monospace;background:transparent;"
        )
        copy_btn = QPushButton("⧉")
        copy_btn.setFixedSize(24, 24)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT3};"
            f"border:none;font-size:13px;}}"
            f"QPushButton:hover{{color:{C_TEXT};}}"
        )
        copy_btn.setToolTip(conn_str)
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(conn_str),
            copy_btn.setText("✓"),
            QTimer.singleShot(1200, lambda: copy_btn.setText("⧉"))
        ))
        cb.addWidget(conn_lbl)
        cb.addStretch()
        cb.addWidget(copy_btn)
        row.addWidget(conn_box)

        row.addStretch()

        # Change Password button
        chpw = QPushButton("Change\nPassword")
        chpw.setFixedSize(80, 44)
        chpw.setCursor(Qt.CursorShape.PointingHandCursor)
        chpw.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_BLUE};"
            f"border:none;font-size:11px;font-weight:600;text-align:center;}}"
            f"QPushButton:hover{{color:#93c5fd;}}"
        )
        chpw.clicked.connect(lambda: self.change_pw_clicked.emit(self._name))
        row.addWidget(chpw)

        # Drop button
        drop = QPushButton("Drop")
        drop.setFixedSize(50, 44)
        drop.setCursor(Qt.CursorShape.PointingHandCursor)
        drop.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_RED};"
            f"border:none;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{color:#f87171;}}"
        )
        drop.clicked.connect(lambda: self.drop_clicked.emit(self._name))
        row.addWidget(drop)

    def get_name(self):
        return self._name


class _SqlRunner(QWidget):
    """Table Browser & SQL Runner panel — bottom half of databases page."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._conn  = None
        self._workers = []
        self._current_db = ""
        self._offset = 0
        self._page_size = 100
        self._current_table = None
        self._build()

    def update_config(self, config):
        self.config = config

    def set_db(self, dbname):
        if dbname == self._current_db and self._conn:
            return
        self._disconnect()
        self._current_db = dbname
        self._db_badge.setText(f"DB: {dbname.upper()}")
        self._connect()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(f"background:{C_BG};")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(20, 0, 20, 0)
        hh.setSpacing(10)

        icon = QLabel("▣")
        icon.setStyleSheet(f"color:{C_TEXT2};font-size:16px;background:transparent;")
        title = QLabel("Table Browser & SQL Runner")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        hh.addWidget(icon)
        hh.addWidget(title)
        hh.addStretch()

        self._db_badge = QLabel("")
        self._db_badge.setStyleSheet(
            f"color:{C_TEXT2};background:{C_SURFACE};border:1px solid {C_BORDER};"
            f"border-radius:5px;font-size:11px;font-weight:700;"
            f"letter-spacing:0.8px;padding:4px 12px;"
        )
        hh.addWidget(self._db_badge)
        root.addWidget(hdr)

        # ── Body splitter ──────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background:{C_BG};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            f"QSplitter::handle{{background:{C_BORDER};width:1px;}}"
        )

        # ── Left: schema tree ──────────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(200)
        left.setMaximumWidth(280)
        left.setStyleSheet(f"background:{C_SURFACE};border-right:1px solid {C_BORDER};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        schema_hdr = QWidget()
        schema_hdr.setFixedHeight(34)
        schema_hdr.setStyleSheet(f"background:{C_SURFACE2};border-bottom:1px solid {C_BORDER};")
        sh = QHBoxLayout(schema_hdr)
        sh.setContentsMargins(14, 0, 14, 0)
        schema_lbl = QLabel("SCHEMA: PUBLIC")
        schema_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;"
        )
        sh.addWidget(schema_lbl)
        lv.addWidget(schema_hdr)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background:{C_SURFACE};
                color:{C_TEXT2};
                border:none;
                font-size:12px;
                outline:none;
            }}
            QTreeWidget::item {{
                padding:5px 8px;
                border:none;
            }}
            QTreeWidget::item:selected {{
                background:{C_SURFACE2};
                color:{C_TEXT};
            }}
            QTreeWidget::item:hover {{
                background:{C_BORDER};
            }}
            QTreeWidget::branch {{
                background:{C_SURFACE};
            }}
        """)
        self._tree.itemClicked.connect(self._on_tree_click)
        lv.addWidget(self._tree)
        splitter.addWidget(left)

        # ── Right: SQL + results ───────────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{C_BG};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        # SQL bar
        sql_bar = QWidget()
        sql_bar.setFixedHeight(52)
        sql_bar.setStyleSheet(
            f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};"
        )
        sb = QHBoxLayout(sql_bar)
        sb.setContentsMargins(12, 0, 12, 0)
        sb.setSpacing(8)

        sql_icon = QLabel("▢")
        sql_icon.setStyleSheet(f"color:{C_TEXT3};font-size:14px;background:transparent;")
        sb.addWidget(sql_icon)

        self._sql_inp = QLineEdit()
        self._sql_inp.setPlaceholderText("SELECT * FROM public.users LIMIT 100;")
        self._sql_inp.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;"
            f"color:{C_TEXT};font-family:'Consolas','Courier New',monospace;"
            f"font-size:13px;padding:0;}}"
            f"QLineEdit:focus{{border:none;outline:none;}}"
        )
        self._sql_inp.returnPressed.connect(self._run_sql)
        sb.addWidget(self._sql_inp)

        self._run_btn = QPushButton("▶  Run")
        self._run_btn.setFixedSize(88, 36)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setStyleSheet(
            f"QPushButton{{background:{C_BLUE};color:white;border:none;"
            f"border-radius:6px;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:#3b7de8;}}"
            f"QPushButton:disabled{{background:{C_BORDER};color:{C_TEXT3};}}"
        )
        self._run_btn.clicked.connect(self._run_sql)
        self._run_btn.setEnabled(False)
        sb.addWidget(self._run_btn)
        rv.addWidget(sql_bar)

        # Results table
        self._results = QTableWidget(0, 0)
        self._results.setStyleSheet(f"""
            QTableWidget {{
                background:{C_BG};
                color:{C_TEXT};
                border:none;
                gridline-color:{C_BORDER};
                font-size:12px;
                font-family:'Consolas','Courier New',monospace;
                outline:none;
            }}
            QTableWidget::item {{
                padding:6px 12px;
                border:none;
            }}
            QTableWidget::item:selected {{
                background:{C_SURFACE2};
                color:{C_TEXT};
            }}
            QHeaderView::section {{
                background:{C_SURFACE};
                color:{C_TEXT3};
                padding:6px 12px;
                border:none;
                border-bottom:1px solid {C_BORDER};
                border-right:1px solid {C_BORDER};
                font-size:10px;
                font-weight:700;
                letter-spacing:1px;
                text-transform:uppercase;
            }}
            QHeaderView {{
                background:{C_SURFACE};
            }}
        """)
        self._results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results.verticalHeader().setVisible(False)
        self._results.verticalHeader().setDefaultSectionSize(40)
        self._results.setShowGrid(True)
        rv.addWidget(self._results)

        # Pagination bar
        pag = QWidget()
        pag.setFixedHeight(40)
        pag.setStyleSheet(
            f"background:{C_SURFACE};border-top:1px solid {C_BORDER};"
        )
        pg = QHBoxLayout(pag)
        pg.setContentsMargins(16, 0, 16, 0)
        pg.setSpacing(8)

        self._row_info = QLabel("")
        self._row_info.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;background:transparent;"
        )
        pg.addWidget(self._row_info)
        pg.addStretch()

        # Pagination buttons matching mockup |< < N/T > >|
        for text, fn in [
            ("|◀", self._first_page), ("◀", self._prev_page),
        ]:
            b = self._pag_btn(text)
            b.clicked.connect(fn)
            pg.addWidget(b)

        self._page_lbl = QLabel("1 / 1")
        self._page_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;background:transparent;padding:0 8px;"
        )
        pg.addWidget(self._page_lbl)

        for text, fn in [
            ("▶", self._next_page), ("▶|", self._last_page),
        ]:
            b = self._pag_btn(text)
            b.clicked.connect(fn)
            pg.addWidget(b)

        rv.addWidget(pag)
        splitter.addWidget(right)
        splitter.setSizes([220, 800])
        bl.addWidget(splitter)
        root.addWidget(body)

    def _pag_btn(self, text):
        b = QPushButton(text)
        b.setFixedSize(28, 26)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER};border-radius:4px;"
            f"font-size:11px;font-weight:700;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
            f"QPushButton:disabled{{color:{C_TEXT3};}}"
        )
        return b

    def _connect(self):
        if not self._current_db:
            return
        c = self.config
        try:
            import psycopg2
            self._conn = psycopg2.connect(
                host="127.0.0.1", port=c["port"],
                user=c["username"], password=c["password"],
                dbname=self._current_db, connect_timeout=5
            )
            self._run_btn.setEnabled(True)
            self._load_schema()
        except Exception as e:
            self._row_info.setText(f"Connection error: {e}")

    def _disconnect(self):
        if self._conn:
            try: self._conn.close()
            except Exception: pass
        self._conn = None
        self._tree.clear()
        self._results.clear()
        self._results.setColumnCount(0)
        self._results.setRowCount(0)
        self._run_btn.setEnabled(False)
        self._page_lbl.setText("1 / 1")
        self._row_info.setText("")

    def _load_schema(self):
        if not self._conn:
            return
        def fn():
            cur = self._conn.cursor()
            cur.execute("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog','information_schema')
                ORDER BY table_schema, table_type DESC, table_name
            """)
            rows = cur.fetchall()
            cur.execute("""
                SELECT schemaname, tablename, n_live_tup
                FROM pg_stat_user_tables
                ORDER BY n_live_tup DESC
            """)
            stats = {(r[0], r[1]): r[2] for r in cur.fetchall()}
            cur.close()
            return rows, stats

        w = _Worker(fn)
        w.result.connect(self._on_schema)
        w.start()
        self._workers.append(w)

    def _on_schema(self, data, error):
        if error or not data:
            return
        rows, stats = data
        self._tree.clear()

        schemas = {}
        for schema, table, ttype in rows:
            schemas.setdefault(schema, {"tables": [], "views": []})
            if ttype == "BASE TABLE":
                schemas[schema]["tables"].append(table)
            else:
                schemas[schema]["views"].append(table)

        for schema, groups in schemas.items():
            if groups["tables"]:
                tables_item = QTreeWidgetItem(self._tree)
                tables_item.setText(0, "  Tables")
                tables_item.setExpanded(True)
                tables_item.setForeground(0, QColor(C_TEXT3))
                f = QFont(); f.setWeight(QFont.Weight.Bold)
                tables_item.setFont(0, f)

                for t in groups["tables"]:
                    child = QTreeWidgetItem(tables_item)
                    count = stats.get((schema, t))
                    label = f"  {t}"
                    child.setText(0, label)
                    if count is not None:
                        count_str = f"{count/1000:.1f}k" if count >= 1000 else str(count)
                        child.setText(0, f"  {t}")
                        child.setData(0, Qt.ItemDataRole.UserRole + 1, count_str)
                    child.setData(0, Qt.ItemDataRole.UserRole, (schema, t))
                    child.setForeground(0, QColor(C_TEXT2))

            if groups["views"]:
                views_item = QTreeWidgetItem(self._tree)
                views_item.setText(0, "  Views")
                views_item.setExpanded(True)
                views_item.setForeground(0, QColor(C_TEXT3))

                for t in groups["views"]:
                    child = QTreeWidgetItem(views_item)
                    child.setText(0, f"  {t}")
                    child.setData(0, Qt.ItemDataRole.UserRole, (schema, t))
                    child.setForeground(0, QColor(C_TEXT2))

        if groups.get("tables") or groups.get("views"):
            fn_item = QTreeWidgetItem()
            fn_item.setText(0, "  Functions")
            fn_item.setForeground(0, QColor(C_TEXT3))
            self._tree.insertTopLevelItem(0, fn_item)

            pol_item = QTreeWidgetItem(self._tree)
            pol_item.setText(0, "  Policies")
            pol_item.setForeground(0, QColor(C_TEXT3))

    def _on_tree_click(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, tuple):
            return
        schema, name = data
        self._current_table = f'"{schema}"."{name}"'
        self._offset = 0
        self._sql_inp.setText(f"SELECT * FROM {self._current_table} LIMIT {self._page_size};")
        self._load_data()

    def _load_data(self):
        if not self._conn or not self._current_table:
            return
        tbl = self._current_table
        offset = self._offset
        limit  = self._page_size

        def fn():
            cur = self._conn.cursor()
            cur.execute(f"SELECT * FROM {tbl} LIMIT {limit} OFFSET {offset}")
            cols = [d[0] for d in cur.description]
            col_types = [d[1] for d in cur.description]
            rows = cur.fetchall()
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                total = cur.fetchone()[0]
            except Exception:
                total = 0
            cur.close()
            return cols, col_types, rows, total

        w = _Worker(fn)
        w.result.connect(self._on_data)
        w.start()
        self._workers.append(w)

    def _on_data(self, data, error):
        if error:
            self._row_info.setText(f"Error: {error[:80]}")
            return
        if not data:
            return
        cols, col_types, rows, total = data
        self._populate(cols, col_types, rows)

        total_pages = max(1, (total + self._page_size - 1) // self._page_size)
        current_page = self._offset // self._page_size + 1
        end_row = min(self._offset + self._page_size, total)
        self._page_lbl.setText(f"{current_page} / {total_pages}")
        self._row_info.setText(
            f"SHOWING {min(len(rows), self._page_size)} OF {total:,} ROWS  ·  TIME: —"
        )

    def _populate(self, cols, col_types, rows):
        import psycopg2
        TYPE_LABELS = {}
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT oid, typname FROM pg_type")
            for oid, typname in cur.fetchall():
                TYPE_LABELS[oid] = typname.upper()
            cur.close()
        except Exception:
            pass

        self._results.clear()
        self._results.setColumnCount(len(cols))
        self._results.setRowCount(len(rows))

        headers = []
        for i, (col, oid) in enumerate(zip(cols, col_types)):
            type_label = TYPE_LABELS.get(oid, "")
            header = QTableWidgetItem(col)
            header.setData(Qt.ItemDataRole.UserRole, type_label)
            headers.append(col)

        self._results.setHorizontalHeaderLabels(headers)

        for i, (col, oid) in enumerate(zip(cols, col_types)):
            type_label = TYPE_LABELS.get(oid, "")
            if type_label:
                hi = self._results.horizontalHeaderItem(i)
                if hi:
                    hi.setText(f"{col}")
                    full = f"{col}  {type_label}"
                    w2 = QTableWidgetItem(full)
                    w2.setForeground(QColor(C_TEXT3))
                    self._results.setHorizontalHeaderItem(i, w2)

        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                text = "NULL" if val is None else str(val)
                cell = QTableWidgetItem(text)
                if val is None:
                    cell.setForeground(QColor(C_TEXT3))
                    cell.setFont(QFont("italic"))
                self._results.setItem(r, c, cell)

        self._results.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        if self._results.columnCount() > 0:
            self._results.horizontalHeader().setStretchLastSection(True)

    def _run_sql(self):
        sql = self._sql_inp.text().strip()
        if not sql or not self._conn:
            return
        self._run_btn.setEnabled(False)
        self._row_info.setText("Running...")

        def fn():
            cur = self._conn.cursor()
            import time
            t0 = time.time()
            cur.execute(sql)
            elapsed = int((time.time() - t0) * 1000)
            if cur.description:
                cols = [d[0] for d in cur.description]
                col_types = [d[1] for d in cur.description]
                rows = cur.fetchmany(500)
                cur.close()
                return "select", cols, col_types, rows, elapsed
            else:
                self._conn.commit()
                affected = cur.rowcount
                cur.close()
                return "exec", affected, elapsed

        w = _Worker(fn)
        w.result.connect(self._on_sql_done)
        w.start()
        self._workers.append(w)

    def _on_sql_done(self, data, error):
        self._run_btn.setEnabled(True)
        if error:
            self._row_info.setText(f"Error: {error[:100]}")
            self._results.setRowCount(0)
            self._results.setColumnCount(1)
            self._results.setHorizontalHeaderLabels(["Error"])
            item = QTableWidgetItem(error)
            item.setForeground(QColor(C_RED))
            self._results.setItem(0, 0, item)
            return
        if not data:
            return
        if data[0] == "select":
            _, cols, col_types, rows, elapsed = data
            self._populate(cols, col_types, rows)
            self._row_info.setText(
                f"SHOWING {len(rows)} OF {len(rows)} ROWS  ·  TIME: {elapsed}ms"
            )
            self._page_lbl.setText("1 / 1")
        else:
            _, affected, elapsed = data
            self._results.setRowCount(0)
            self._results.setColumnCount(0)
            self._row_info.setText(
                f"OK — {affected} row(s) affected  ·  TIME: {elapsed}ms"
            )

    def _first_page(self):
        self._offset = 0
        self._load_data()

    def _prev_page(self):
        self._offset = max(0, self._offset - self._page_size)
        self._load_data()

    def _next_page(self):
        self._offset += self._page_size
        self._load_data()

    def _last_page(self):
        pass


class DatabasesTab(QWidget):
    """
    Full Databases page — Managed Databases list + Table Browser & SQL Runner.
    Callbacks are passed in from main_window to keep all logic there.
    """

    def __init__(self, config, manager,
                 on_create, on_drop, on_change_pw, on_refresh,
                 parent=None):
        super().__init__(parent)
        self.config      = config
        self._manager    = manager
        self._on_create  = on_create
        self._on_drop    = on_drop
        self._on_chpw    = on_change_pw
        self._on_refresh = on_refresh
        self._db_rows    = []
        self._workers    = []
        self._build()

    def update_config(self, config):
        self.config = config
        self._sql_runner.update_config(config)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:#1a1d23;border:none;")

        body = QWidget()
        body.setStyleSheet("background:#1a1d23;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(28, 28, 28, 0)
        bv.setSpacing(0)

        # ── Page header ────────────────────────────────────────────────────────
        page_hdr = QHBoxLayout()
        page_hdr.setSpacing(0)

        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(4)
        title = QLabel("Managed Databases")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:24px;font-weight:800;background:transparent;"
        )
        sub = QLabel("Orchestrate and monitor your PostgreSQL isolated instances.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        hdr_col.addWidget(title)
        hdr_col.addWidget(sub)

        page_hdr.addLayout(hdr_col)
        page_hdr.addStretch()

        new_btn = QPushButton("  +  New Database")
        new_btn.setFixedHeight(42)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C_BLUE}, stop:1 #2563eb);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 700;
                padding: 0 22px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #3b7de8, stop:1 #1d4ed8);
            }}
        """)
        new_btn.clicked.connect(self._on_create)
        page_hdr.addWidget(new_btn)

        bv.addLayout(page_hdr)
        bv.addSpacing(20)

        # ── Databases table ────────────────────────────────────────────────────
        self._db_container = QWidget()
        self._db_container.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};"
            f"border-radius:10px;"
        )
        self._db_layout = QVBoxLayout(self._db_container)
        self._db_layout.setContentsMargins(0, 0, 0, 0)
        self._db_layout.setSpacing(0)

        self._db_header = self._build_table_header()
        self._db_layout.addWidget(self._db_header)

        self._db_rows_container = QWidget()
        self._db_rows_container.setStyleSheet("background:transparent;")
        self._db_rows_layout = QVBoxLayout(self._db_rows_container)
        self._db_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._db_rows_layout.setSpacing(0)

        self._empty_lbl = QLabel("No databases yet. Click + New Database to create one.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;padding:32px;background:transparent;"
        )
        self._db_rows_layout.addWidget(self._empty_lbl)
        self._db_layout.addWidget(self._db_rows_container)
        bv.addWidget(self._db_container)
        bv.addSpacing(28)

        # ── Table Browser & SQL Runner ─────────────────────────────────────────
        runner_container = QWidget()
        runner_container.setFixedHeight(560)
        runner_container.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};"
            f"border-radius:10px;overflow:hidden;"
        )
        rl = QVBoxLayout(runner_container)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        self._sql_runner = _SqlRunner(self.config)
        rl.addWidget(self._sql_runner)
        bv.addWidget(runner_container)
        bv.addSpacing(28)

        scroll.setWidget(body)
        root.addLayout(QVBoxLayout())
        root2 = self.layout()
        root2.addWidget(scroll)

    def _build_table_header(self):
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(
            f"background:{C_SURFACE2};border-bottom:1px solid {C_BORDER};"
            f"border-radius:10px 10px 0 0;"
        )
        h = QHBoxLayout(hdr)
        h.setContentsMargins(20, 0, 16, 0)
        h.setSpacing(0)

        for text, width in [
            ("DATABASE NAME", 210),
            ("OWNER\nUSERNAME", 150),
            ("PASSWORD", 160),
            ("CONNECTION STRING", 270),
            ("", 0),
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1.2px;background:transparent;"
            )
            if width:
                lbl.setFixedWidth(width)
            else:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            h.addWidget(lbl)

        return hdr

    def populate(self, dbs, manager):
        self._manager = manager
        ip   = manager.get_lan_ip()
        port = self.config["port"]

        while self._db_rows_layout.count():
            child = self._db_rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not dbs:
            self._db_rows_layout.addWidget(self._empty_lbl)
            self._empty_lbl.setVisible(True)
            return

        self._empty_lbl.setVisible(False)
        for db in dbs:
            name  = db["name"]
            owner = db["owner"]
            conn  = f"postgresql://{owner}:<pw>@{ip}:{port}/{name}"
            row   = _DbRow(name, owner, conn)
            row.change_pw_clicked.connect(self._on_chpw)
            row.drop_clicked.connect(self._on_drop)
            row.setFixedHeight(54)
            self._db_rows_layout.addWidget(row)

        if dbs:
            self._sql_runner.set_db(dbs[0]["name"])

    def refresh_databases(self, dbs):
        self.populate(dbs, self._manager)

    def get_db_names(self):
        names = []
        for i in range(self._db_rows_layout.count()):
            w = self._db_rows_layout.itemAt(i).widget()
            if isinstance(w, _DbRow):
                names.append(w.get_name())
        return names
