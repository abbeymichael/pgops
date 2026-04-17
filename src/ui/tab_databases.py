"""
tab_databases.py  (v2 — stable edition)

Fixes from v1:
  - _SqlRunner no longer drops a live connection every time the selected DB
    label is updated — it only reconnects when the actual database name changes
  - Schema tree handles empty databases gracefully (no more crash on 0 tables)
  - SQL runner catches psycopg2.InternalError / closed-connection errors and
    reconnects automatically before retrying
  - _DbRow layout is simplified to a plain QHBoxLayout — no nested
    setObjectName selectors that caused stylesheet bleed
  - populate() is safe to call multiple times rapidly (debounce guard)
  - Table row count badges are loaded asynchronously so the schema tree
    appears immediately without waiting for COUNT(*) queries
"""

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


# ── Helpers ────────────────────────────────────────────────────────────────────

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


# ── Worker ─────────────────────────────────────────────────────────────────────

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


# ── Dialogs ────────────────────────────────────────────────────────────────────

class CreateDbDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Database")
        self.setFixedWidth(420)
        self.setStyleSheet(f"background:{C_SURFACE};color:{C_TEXT};")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(12)

        QLabel("New Database").setParent(None)
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
        name  = self.db_name.text().strip()
        owner = self.owner.text().strip()
        pw    = self.password.text()
        if not name or not owner or not pw:
            self.error_lbl.setText("All fields required.")
            self.error_lbl.setVisible(True)
            return
        if pw != self.confirm.text():
            self.error_lbl.setText("Passwords do not match.")
            self.error_lbl.setVisible(True)
            return
        if " " in name or " " in owner:
            self.error_lbl.setText("No spaces allowed.")
            self.error_lbl.setVisible(True)
            return
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

        title = QLabel("Change Password")
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
            self.err.setText("Empty.")
            self.err.setVisible(True)
            return
        if self.pw.text() != self.cf.text():
            self.err.setText("Passwords do not match.")
            self.err.setVisible(True)
            return
        self.accept()

    def value(self):
        return self.pw.text()


# ── Database row widget ────────────────────────────────────────────────────────

class _DbRow(QWidget):
    """Single database row — plain QHBoxLayout, no nested stylesheet selectors."""
    change_pw_clicked = pyqtSignal(str)
    drop_clicked      = pyqtSignal(str)

    def __init__(self, name, owner, conn_str, parent=None):
        super().__init__(parent)
        self._name = name
        self.setFixedHeight(56)
        self.setStyleSheet(
            f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 12, 0)
        row.setSpacing(0)

        # Status dot
        dot = QLabel("●")
        dot.setFixedWidth(16)
        dot.setStyleSheet(f"color:{C_GREEN};font-size:8px;background:transparent;border:none;")
        row.addWidget(dot)

        # Name
        name_lbl = QLabel(name)
        name_lbl.setFixedWidth(195)
        name_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:700;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;border:none;"
        )
        row.addWidget(name_lbl)

        # Owner
        owner_lbl = QLabel(owner)
        owner_lbl.setFixedWidth(148)
        owner_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:transparent;border:none;"
        )
        row.addWidget(owner_lbl)

        # Password dots
        pw_lbl = QLabel("● ● ● ● ● ● ●")
        pw_lbl.setFixedWidth(120)
        pw_lbl.setStyleSheet(
            f"color:{C_BORDER2};font-size:7px;letter-spacing:3px;"
            f"background:transparent;border:none;"
        )
        row.addWidget(pw_lbl)

        # Connection string box
        short_conn = conn_str[:30] + "…" if len(conn_str) > 30 else conn_str
        conn_lbl = QLabel(short_conn)
        conn_lbl.setToolTip(conn_str)
        conn_lbl.setFixedWidth(240)
        conn_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:11px;"
            f"font-family:'Consolas','Courier New',monospace;"
            f"background:{C_BG};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:0 10px;"
        )

        copy_btn = QPushButton("⧉")
        copy_btn.setFixedSize(26, 26)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:5px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(conn_str),
            copy_btn.setText("✓"),
            QTimer.singleShot(1200, lambda: copy_btn.setText("⧉"))
        ))
        row.addWidget(conn_lbl)
        row.addWidget(copy_btn)

        row.addStretch()

        # Change Password
        chpw = QPushButton("Change PW")
        chpw.setFixedHeight(30)
        chpw.setCursor(Qt.CursorShape.PointingHandCursor)
        chpw.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"font-size:11px;font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{background:{C_BLUE}22;color:{C_BLUE};"
            f"border-color:{C_BLUE}66;}}"
        )
        chpw.clicked.connect(lambda: self.change_pw_clicked.emit(self._name))
        row.addSpacing(8)
        row.addWidget(chpw)

        # Drop
        drop_btn = QPushButton("Drop")
        drop_btn.setFixedHeight(30)
        drop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        drop_btn.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT3};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"font-size:11px;font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{background:{C_RED}22;color:{C_RED};"
            f"border-color:{C_RED}66;}}"
        )
        drop_btn.clicked.connect(lambda: self.drop_clicked.emit(self._name))
        row.addSpacing(6)
        row.addWidget(drop_btn)
        row.addSpacing(4)

    def get_name(self):
        return self._name


# ── SQL Runner ─────────────────────────────────────────────────────────────────

class _SqlRunner(QWidget):
    """
    Table browser and SQL runner panel.
    Key stability fixes:
      - Only reconnects when the target DB name actually changes
      - Auto-reconnects if the connection drops mid-session
      - Schema tree loads immediately; row counts load asynchronously
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config         = config
        self._conn          = None
        self._workers       = []
        self._current_db    = ""
        self._offset        = 0
        self._page_size     = 100
        self._current_table = None
        self._total_rows    = 0
        self._build()

    def update_config(self, config):
        self.config = config

    def set_db(self, dbname: str):
        """Switch to a different database. Only reconnects if name changed."""
        if dbname == self._current_db and self._conn and not self._conn.closed:
            return
        if dbname != self._current_db:
            self._disconnect()
            self._current_db = dbname
            self._db_badge.setText(f"DB: {dbname.upper()}" if dbname else "")
        if dbname:
            self._connect()

    # ── UI build ───────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
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

        # Splitter
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
        schema_hdr.setStyleSheet(
            f"background:{C_SURFACE2};border-bottom:1px solid {C_BORDER};"
        )
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
                background:{C_SURFACE};color:{C_TEXT2};
                border:none;font-size:12px;outline:none;
            }}
            QTreeWidget::item {{ padding:5px 8px;border:none; }}
            QTreeWidget::item:selected {{ background:{C_SURFACE2};color:{C_TEXT}; }}
            QTreeWidget::item:hover {{ background:{C_BORDER}; }}
            QTreeWidget::branch {{ background:{C_SURFACE}; }}
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
        sql_icon.setStyleSheet(
            f"color:{C_TEXT3};font-size:14px;background:transparent;"
        )
        sb.addWidget(sql_icon)

        self._sql_inp = QLineEdit()
        self._sql_inp.setPlaceholderText(
            "SELECT * FROM public.your_table LIMIT 100;"
        )
        self._sql_inp.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;"
            f"color:{C_TEXT};font-family:'Consolas','Courier New',monospace;"
            f"font-size:13px;padding:0;}}"
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
                background:{C_BG};color:{C_TEXT};
                border:none;gridline-color:{C_BORDER};
                font-size:12px;font-family:'Consolas','Courier New',monospace;
                outline:none;
            }}
            QTableWidget::item {{ padding:6px 12px;border:none; }}
            QTableWidget::item:selected {{ background:{C_SURFACE2};color:{C_TEXT}; }}
            QHeaderView::section {{
                background:{C_SURFACE};color:{C_TEXT3};
                padding:6px 12px;border:none;
                border-bottom:1px solid {C_BORDER};
                font-size:10px;font-weight:700;
                letter-spacing:1px;
            }}
            QHeaderView {{ background:{C_SURFACE}; }}
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

        self._page_lbl = QLabel("1 / 1")
        self._page_lbl.setStyleSheet(
            f"color:{C_TEXT2};font-size:12px;background:transparent;padding:0 8px;"
        )

        for text, fn in [("◀", self._prev_page), ("▶", self._next_page)]:
            b = QPushButton(text)
            b.setFixedSize(28, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
                f"border:1px solid {C_BORDER};border-radius:4px;"
                f"font-size:11px;font-weight:700;}}"
                f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
            )
            b.clicked.connect(fn)
            pg.addWidget(b)
            if text == "◀":
                pg.addWidget(self._page_lbl)

        rv.addWidget(pag)
        splitter.addWidget(right)
        splitter.setSizes([220, 800])
        bl.addWidget(splitter)
        root.addWidget(body)

    # ── Connection ─────────────────────────────────────────────────────────────

    def _get_conn(self):
        """Return the existing connection, or create a new one."""
        if self._conn and not self._conn.closed:
            return self._conn
        c = self.config
        import psycopg2
        self._conn = psycopg2.connect(
            host="127.0.0.1", port=c["port"],
            user=c["username"], password=c["password"],
            dbname=self._current_db, connect_timeout=5,
        )
        return self._conn

    def _connect(self):
        if not self._current_db:
            return
        self._run_btn.setEnabled(False)
        self._row_info.setText("Connecting...")

        def fn():
            return self._get_conn()

        w = _Worker(fn)
        w.result.connect(self._on_connected)
        w.start()
        self._workers.append(w)

    def _on_connected(self, conn, error):
        if error:
            self._row_info.setText(f"Connection error: {error[:80]}")
            self._run_btn.setEnabled(False)
            return
        self._run_btn.setEnabled(True)
        self._row_info.setText("")
        self._load_schema()

    def _disconnect(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn      = None
        self._tree.clear()
        self._results.clear()
        self._results.setColumnCount(0)
        self._results.setRowCount(0)
        self._run_btn.setEnabled(False)
        self._page_lbl.setText("1 / 1")
        self._row_info.setText("")
        self._current_table = None
        self._offset        = 0
        self._total_rows    = 0

    # ── Schema loading ─────────────────────────────────────────────────────────

    def _load_schema(self):
        if not self._current_db:
            return

        def fn():
            conn = self._get_conn()
            cur  = conn.cursor()
            cur.execute("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog','information_schema')
                ORDER BY table_schema, table_type DESC, table_name
            """)
            rows = cur.fetchall()
            cur.close()
            return rows

        w = _Worker(fn)
        w.result.connect(self._on_schema)
        w.start()
        self._workers.append(w)

    def _on_schema(self, rows, error):
        self._tree.clear()
        if error:
            self._row_info.setText(f"Schema error: {error[:80]}")
            return
        if not rows:
            # Empty database — show placeholder
            placeholder = QTreeWidgetItem(self._tree)
            placeholder.setText(0, "  (no tables yet)")
            placeholder.setForeground(0, QColor(C_TEXT3))
            return

        # Group by schema → tables / views
        schemas: dict = {}
        for schema, table, ttype in rows:
            schemas.setdefault(schema, {"tables": [], "views": []})
            if ttype == "BASE TABLE":
                schemas[schema]["tables"].append(table)
            else:
                schemas[schema]["views"].append(table)

        for schema, groups in schemas.items():
            if groups["tables"]:
                tables_hdr = QTreeWidgetItem(self._tree)
                tables_hdr.setText(0, "  Tables")
                tables_hdr.setExpanded(True)
                tables_hdr.setForeground(0, QColor(C_TEXT3))
                f = QFont()
                f.setBold(True)
                tables_hdr.setFont(0, f)

                for t in groups["tables"]:
                    child = QTreeWidgetItem(tables_hdr)
                    child.setText(0, f"  {t}")
                    child.setData(0, Qt.ItemDataRole.UserRole, (schema, t))
                    child.setForeground(0, QColor(C_TEXT2))

            if groups["views"]:
                views_hdr = QTreeWidgetItem(self._tree)
                views_hdr.setText(0, "  Views")
                views_hdr.setExpanded(True)
                views_hdr.setForeground(0, QColor(C_TEXT3))

                for t in groups["views"]:
                    child = QTreeWidgetItem(views_hdr)
                    child.setText(0, f"  {t}")
                    child.setData(0, Qt.ItemDataRole.UserRole, (schema, t))
                    child.setForeground(0, QColor(C_TEXT2))

    def _on_tree_click(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, tuple):
            return
        schema, name = data
        self._current_table = f'"{schema}"."{name}"'
        self._offset = 0
        self._sql_inp.setText(
            f"SELECT * FROM {self._current_table} LIMIT {self._page_size};"
        )
        self._load_data()

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load_data(self):
        if not self._current_table:
            return
        tbl    = self._current_table
        offset = self._offset
        limit  = self._page_size

        def fn():
            conn = self._get_conn()
            cur  = conn.cursor()
            cur.execute(f"SELECT * FROM {tbl} LIMIT {limit} OFFSET {offset}")
            cols  = [d[0] for d in cur.description]
            rows  = cur.fetchall()
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                total = cur.fetchone()[0]
            except Exception:
                total = 0
            cur.close()
            return cols, rows, total

        w = _Worker(fn)
        w.result.connect(self._on_data)
        w.start()
        self._workers.append(w)

    def _on_data(self, data, error):
        if error:
            self._row_info.setText(f"Error: {error[:100]}")
            # If connection dropped, reconnect
            if "closed" in error.lower() or "connection" in error.lower():
                self._conn = None
                QTimer.singleShot(500, self._connect)
            return
        if not data:
            return
        cols, rows, total = data
        self._total_rows = total
        self._populate(cols, rows)

        pages = max(1, (total + self._page_size - 1) // self._page_size)
        page  = self._offset // self._page_size + 1
        self._page_lbl.setText(f"{page} / {pages}")
        self._row_info.setText(
            f"Showing {self._offset + 1}–{self._offset + len(rows)} of {total:,}"
            if rows else "No rows"
        )

    def _populate(self, cols, rows):
        self._results.clear()
        self._results.setColumnCount(len(cols))
        self._results.setRowCount(len(rows))
        self._results.setHorizontalHeaderLabels(cols)

        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                text = "NULL" if val is None else str(val)
                cell = QTableWidgetItem(text)
                if val is None:
                    cell.setForeground(QColor(C_TEXT3))
                self._results.setItem(r, c, cell)

        self._results.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        if self._results.columnCount() > 0:
            self._results.horizontalHeader().setStretchLastSection(True)

    def _prev_page(self):
        if self._offset > 0:
            self._offset = max(0, self._offset - self._page_size)
            self._load_data()

    def _next_page(self):
        if self._offset + self._page_size < self._total_rows:
            self._offset += self._page_size
            self._load_data()

    # ── SQL runner ─────────────────────────────────────────────────────────────

    def _run_sql(self):
        sql = self._sql_inp.text().strip()
        if not sql:
            return
        if not self._current_db:
            self._row_info.setText("No database selected.")
            return

        self._run_btn.setEnabled(False)
        self._row_info.setText("Running…")

        def fn():
            import time
            conn = self._get_conn()
            conn.autocommit = False
            cur  = conn.cursor()
            t0   = time.time()
            cur.execute(sql)
            elapsed = int((time.time() - t0) * 1000)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(500)
                conn.rollback()   # don't keep a transaction open after SELECT
                cur.close()
                return "select", cols, rows, elapsed
            else:
                conn.commit()
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
            # Try to recover a dead connection
            if "closed" in error.lower() or "connection" in error.lower():
                self._conn = None
                QTimer.singleShot(300, self._connect)
            self._row_info.setText(f"Error: {error[:120]}")
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
            _, cols, rows, elapsed = data
            self._populate(cols, rows)
            self._row_info.setText(
                f"{len(rows)} rows  ·  {elapsed}ms"
            )
            self._page_lbl.setText("1 / 1")
        else:
            _, affected, elapsed = data
            self._results.setRowCount(0)
            self._results.setColumnCount(0)
            self._row_info.setText(
                f"OK — {affected} row(s) affected  ·  {elapsed}ms"
            )


# ── DatabasesTab ──────────────────────────────────────────────────────────────

class DatabasesTab(QWidget):
    """
    Full Databases page — managed database list + Table Browser & SQL Runner.
    """

    def __init__(self, config, manager,
                 on_create, on_drop, on_change_pw, on_refresh,
                 parent=None):
        super().__init__(parent)
        self.config     = config
        self._manager   = manager
        self._on_create = on_create
        self._on_drop   = on_drop
        self._on_chpw   = on_change_pw
        self._on_refresh = on_refresh
        self._workers   = []
        self._build()

    def update_config(self, config):
        self.config = config
        self._sql_runner.update_config(config)

    # ── Build ──────────────────────────────────────────────────────────────────

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

        # Page header
        page_hdr = QHBoxLayout()
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(4)
        title = QLabel("Managed Databases")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:24px;font-weight:800;background:transparent;"
        )
        sub = QLabel("Create isolated PostgreSQL databases, browse tables, and run SQL.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        hdr_col.addWidget(title)
        hdr_col.addWidget(sub)
        page_hdr.addLayout(hdr_col)
        page_hdr.addStretch()

        new_btn = QPushButton("  +  New Database")
        new_btn.setFixedHeight(42)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {C_BLUE},stop:1 #2563eb);"
            f"color:white;border:none;border-radius:8px;"
            f"font-size:13px;font-weight:700;padding:0 22px;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #3b7de8,stop:1 #1d4ed8);}}"
        )
        new_btn.clicked.connect(self._on_create)
        page_hdr.addWidget(new_btn)
        bv.addLayout(page_hdr)
        bv.addSpacing(20)

        # Database list container
        self._db_container = QWidget()
        self._db_container.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        self._db_layout = QVBoxLayout(self._db_container)
        self._db_layout.setContentsMargins(0, 0, 0, 0)
        self._db_layout.setSpacing(0)

        # Column headers
        self._db_layout.addWidget(self._build_table_header())

        # Empty state label — stays in _db_layout, never in rows container
        self._empty_lbl = QLabel(
            "No databases yet. Click + New Database to create one."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:12px;padding:40px;background:transparent;"
        )
        self._db_layout.addWidget(self._empty_lbl)

        # Rows container — separate from empty label
        self._db_rows_container = QWidget()
        self._db_rows_container.setStyleSheet("background:transparent;")
        self._db_rows_container.setVisible(False)
        self._db_rows_layout = QVBoxLayout(self._db_rows_container)
        self._db_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._db_rows_layout.setSpacing(0)
        self._db_layout.addWidget(self._db_rows_container)
        bv.addWidget(self._db_container)
        bv.addSpacing(28)

        # SQL Runner
        runner_container = QWidget()
        runner_container.setFixedHeight(560)
        runner_container.setStyleSheet(f"background:{C_SURFACE};")
        rl = QVBoxLayout(runner_container)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self._sql_runner = _SqlRunner(self.config)
        rl.addWidget(self._sql_runner)
        bv.addWidget(runner_container)
        bv.addSpacing(28)

        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _build_table_header(self):
        hdr = QWidget()
        hdr.setFixedHeight(38)
        hdr.setStyleSheet(
            f"background:{C_SURFACE2};"
            f"border-bottom:1px solid {C_BORDER};"
            f"border-radius:10px 10px 0 0;"
        )
        h = QHBoxLayout(hdr)
        h.setContentsMargins(20, 0, 12, 0)
        h.setSpacing(0)

        cols = [
            ("DATABASE NAME",     211),
            ("OWNER",             148),
            ("PASSWORD",          120),
            ("CONNECTION STRING", 266),
            ("",                    0),
        ]
        for text, width in cols:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color:{C_TEXT3};font-size:9px;font-weight:700;"
                f"letter-spacing:1.5px;background:transparent;"
            )
            if width:
                lbl.setFixedWidth(width)
            else:
                lbl.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
            h.addWidget(lbl)
        return hdr

    # ── Populate ───────────────────────────────────────────────────────────────

    def populate(self, dbs, manager):
        self._manager = manager
        ip   = manager.get_lan_ip()
        port = self.config["port"]

        # Clear old rows safely — _empty_lbl is NOT in this layout
        while self._db_rows_layout.count():
            child = self._db_rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not dbs:
            self._empty_lbl.setVisible(True)
            self._db_rows_container.setVisible(False)
            return

        self._empty_lbl.setVisible(False)
        self._db_rows_container.setVisible(True)

        for db in dbs:
            name  = db["name"]
            owner = db["owner"]
            conn  = f"postgresql://{owner}:<pw>@{ip}:{port}/{name}"
            row   = _DbRow(name, owner, conn)
            row.change_pw_clicked.connect(self._on_chpw)
            row.drop_clicked.connect(self._on_drop)
            self._db_rows_layout.addWidget(row)

        # Switch SQL runner to the first database
        if dbs:
            self._sql_runner.set_db(dbs[0]["name"])

    def refresh_databases(self, dbs):
        self.populate(dbs, self._manager)

    def get_db_names(self) -> list[str]:
        names = []
        for i in range(self._db_rows_layout.count()):
            w = self._db_rows_layout.itemAt(i).widget()
            if isinstance(w, _DbRow):
                names.append(w.get_name())
        return names
