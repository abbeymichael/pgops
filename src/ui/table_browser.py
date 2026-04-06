"""
table_browser.py
Browse PostgreSQL databases: schema tree, table preview, pagination, SQL runner.
TableBrowser(config) — config is the admin config dict.
"""

import platform
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget,
    QTreeWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit, QLabel, QComboBox, QAbstractItemView,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont


# ─── Worker ───────────────────────────────────────────────────────────────────
class DBWorker(QThread):
    result = pyqtSignal(object, str)   # data, error_msg

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn(), "")
        except Exception as e:
            self.result.emit(None, str(e))


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _btn(text, bg="#1d4ed8", hover="#1e40af", fg="white", h=30):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:5px;padding:0 12px;font-size:12px;font-weight:600;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:#1e293b;color:#475569;}}"
    )
    return b


def _lbl(text, color="#94a3b8", size=12):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;")
    return l


def _get_conn(host, port, user, password, dbname):
    try:
        import psycopg2
        return psycopg2.connect(
            host=host, port=port, user=user,
            password=password, dbname=dbname,
            connect_timeout=5
        )
    except ImportError:
        raise RuntimeError(
            "psycopg2 not installed.\n"
            "Run: pip install psycopg2-binary"
        )


# ─── TableBrowser widget ──────────────────────────────────────────────────────
class TableBrowser(QWidget):
    """
    Instantiate with: TableBrowser(config)
    where config = {"username":..., "password":..., "port":..., ...}
    """

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._conn = None
        self._workers = []
        self._current_table = None
        self._offset = 0
        self._page_size = 100

        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────────────

    def update_config(self, config: dict):
        """Called when admin settings change."""
        self.config = config

    def refresh_databases(self, db_list: list):
        """
        Called from main window after the DB list updates.
        db_list: list of dicts with at least {"name": str}
        """
        current = self.db_combo.currentText()
        self.db_combo.blockSignals(True)
        self.db_combo.clear()
        for db in db_list:
            name = db["name"] if isinstance(db, dict) else db
            self.db_combo.addItem(name)
        idx = self.db_combo.findText(current)
        if idx >= 0:
            self.db_combo.setCurrentIndex(idx)
        self.db_combo.blockSignals(False)

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background:#080f1e;border-bottom:1px solid #1e293b;")
        toolbar.setFixedHeight(44)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(12, 0, 12, 0)
        tb.setSpacing(8)

        tb.addWidget(_lbl("Database:"))
        self.db_combo = QComboBox()
        self.db_combo.setStyleSheet(
            "background:#1e293b;border:1px solid #334155;border-radius:5px;"
            "padding:4px 8px;color:#e2e8f0;font-size:12px;min-width:140px;"
        )
        self.db_combo.currentTextChanged.connect(self._on_db_changed)
        tb.addWidget(self.db_combo)

        self.btn_connect = _btn("Connect", "#1d4ed8", "#1e40af", h=28)
        self.btn_connect.clicked.connect(self._connect)
        tb.addWidget(self.btn_connect)

        tb.addSpacing(12)
        self.status_lbl = _lbl("Not connected", "#475569")
        tb.addWidget(self.status_lbl)
        tb.addStretch()

        self.btn_refresh_schema = _btn("Refresh Schema", "#1e293b", "#334155", "#94a3b8", h=28)
        self.btn_refresh_schema.clicked.connect(self._load_schema)
        self.btn_refresh_schema.setEnabled(False)
        tb.addWidget(self.btn_refresh_schema)

        root.addWidget(toolbar)

        # SQL bar
        sql_bar = QWidget()
        sql_bar.setStyleSheet("background:#080f1e;border-bottom:1px solid #1e293b;")
        sql_bar.setFixedHeight(38)
        sb = QHBoxLayout(sql_bar)
        sb.setContentsMargins(8, 0, 8, 0)
        sb.setSpacing(6)

        self.sql_input = QLineEdit()
        self.sql_input.setPlaceholderText("SQL — press Enter or Run")
        self.sql_input.setStyleSheet(
            "background:#0a1020;border:1px solid #1e293b;border-radius:4px;"
            "padding:4px 8px;color:#e2e8f0;font-family:monospace;font-size:12px;"
        )
        self.sql_input.returnPressed.connect(self._run_sql)
        sb.addWidget(self.sql_input)

        self.btn_run = _btn("Run", "#065f46", "#047857", h=26)
        self.btn_run.clicked.connect(self._run_sql)
        self.btn_run.setEnabled(False)
        sb.addWidget(self.btn_run)

        self.btn_clear = _btn("Clear", "#1e293b", "#334155", "#94a3b8", h=26)
        self.btn_clear.clicked.connect(self.sql_input.clear)
        sb.addWidget(self.btn_clear)

        root.addWidget(sql_bar)

        # Main split: tree | data
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle{background:#1e293b;width:2px;}")

        # Left: schema tree
        left = QWidget()
        left.setStyleSheet("background:#080f1e;")
        left.setMinimumWidth(180)
        left.setMaximumWidth(260)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        schema_hdr = QLabel("  Schema")
        schema_hdr.setFixedHeight(28)
        schema_hdr.setStyleSheet(
            "background:#0a1020;color:#475569;font-size:11px;"
            "font-weight:bold;border-bottom:1px solid #1e293b;"
        )
        lv.addWidget(schema_hdr)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(
            "QTreeWidget{background:#080f1e;color:#cbd5e1;border:none;font-size:12px;}"
            "QTreeWidget::item{padding:3px 4px;}"
            "QTreeWidget::item:selected{background:#1e293b;color:#fff;}"
            "QTreeWidget::item:hover{background:#0f172a;}"
            "QTreeWidget::branch{background:#080f1e;}"
        )
        self.tree.itemClicked.connect(self._on_tree_click)
        lv.addWidget(self.tree)
        splitter.addWidget(left)

        # Right: data table + pagination
        right = QWidget()
        right.setStyleSheet("background:#0f172a;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.data_table = QTableWidget(0, 0)
        self.data_table.setStyleSheet(
            "QTableWidget{background:#0a1020;color:#e2e8f0;border:none;"
            "gridline-color:#1e293b;font-size:12px;font-family:monospace;}"
            "QTableWidget::item{padding:4px 8px;}"
            "QTableWidget::item:selected{background:#1e293b;}"
            "QHeaderView::section{background:#0f172a;color:#64748b;"
            "padding:5px 8px;border:none;border-right:1px solid #1e293b;"
            "font-size:11px;font-weight:bold;}"
        )
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.data_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.data_table.horizontalHeader().setStretchLastSection(True)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.verticalHeader().setDefaultSectionSize(24)
        rv.addWidget(self.data_table)

        # Pagination bar
        pag = QWidget()
        pag.setFixedHeight(32)
        pag.setStyleSheet("background:#080f1e;border-top:1px solid #1e293b;")
        pg = QHBoxLayout(pag)
        pg.setContentsMargins(10, 0, 10, 0)
        pg.setSpacing(8)

        self.row_info = _lbl("", "#475569", 11)
        self.btn_prev = _btn("Prev", "#1e293b", "#334155", "#94a3b8", h=24)
        self.btn_next = _btn("Next", "#1e293b", "#334155", "#94a3b8", h=24)
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

        pg.addWidget(self.row_info)
        pg.addStretch()
        pg.addWidget(self.btn_prev)
        pg.addWidget(self.btn_next)
        rv.addWidget(pag)

        splitter.addWidget(right)
        splitter.setSizes([200, 600])
        root.addWidget(splitter)

    # ── Connection ────────────────────────────────────────────────────────────

    def _on_db_changed(self, dbname):
        self._disconnect()

    def _connect(self):
        dbname = self.db_combo.currentText()
        if not dbname:
            return
        self._set_status("Connecting...", "#f59e0b")
        self.btn_connect.setEnabled(False)
        c = self.config

        def fn():
            return _get_conn("127.0.0.1", c["port"], c["username"], c["password"], dbname)

        w = DBWorker(fn)
        w.result.connect(self._on_connected)
        w.start()
        self._workers.append(w)

    def _on_connected(self, conn, error):
        self.btn_connect.setEnabled(True)
        if error:
            self._set_status(f"Error: {error[:60]}", "#ef4444")
            return
        self._conn = conn
        self._set_status(f"Connected: {self.db_combo.currentText()}", "#22c55e")
        self.btn_refresh_schema.setEnabled(True)
        self.btn_run.setEnabled(True)
        self._load_schema()

    def _disconnect(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self.tree.clear()
        self._clear_data()
        self.btn_refresh_schema.setEnabled(False)
        self.btn_run.setEnabled(False)
        self._set_status("Not connected", "#475569")

    def _set_status(self, text, color):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color:{color};font-size:12px;")

    # ── Schema ────────────────────────────────────────────────────────────────

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
            return cur.fetchall()

        w = DBWorker(fn)
        w.result.connect(self._on_schema)
        w.start()
        self._workers.append(w)

    def _on_schema(self, rows, error):
        if error:
            self._show_error(error)
            return
        self.tree.clear()
        schemas = {}
        for schema, table, ttype in (rows or []):
            schemas.setdefault(schema, {"tables": [], "views": []})
            if ttype == "BASE TABLE":
                schemas[schema]["tables"].append(table)
            else:
                schemas[schema]["views"].append(table)

        for schema, groups in schemas.items():
            si = QTreeWidgetItem(self.tree, [f"  {schema}"])
            si.setForeground(0, QColor("#64748b"))
            si.setExpanded(True)

            if groups["tables"]:
                ti = QTreeWidgetItem(si, ["  Tables"])
                ti.setForeground(0, QColor("#475569"))
                ti.setExpanded(True)
                for t in groups["tables"]:
                    item = QTreeWidgetItem(ti, [f"    {t}"])
                    item.setData(0, Qt.ItemDataRole.UserRole, (schema, t))
                    item.setForeground(0, QColor("#94a3b8"))

            if groups["views"]:
                vi = QTreeWidgetItem(si, ["  Views"])
                vi.setForeground(0, QColor("#475569"))
                vi.setExpanded(True)
                for v in groups["views"]:
                    item = QTreeWidgetItem(vi, [f"    {v}"])
                    item.setData(0, Qt.ItemDataRole.UserRole, (schema, v))
                    item.setForeground(0, QColor("#94a3b8"))

    def _on_tree_click(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        schema, name = data
        self._current_table = f'"{schema}"."{name}"'
        self._offset = 0
        self.sql_input.setText(f"SELECT * FROM {self._current_table}")
        self._load_data()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_data(self):
        if not self._conn or not self._current_table:
            return
        tbl = self._current_table
        offset = self._offset
        limit = self._page_size

        def fn():
            cur = self._conn.cursor()
            cur.execute(f"SELECT * FROM {tbl} LIMIT {limit} OFFSET {offset}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                total = cur.fetchone()[0]
            except Exception:
                total = "?"
            return cols, rows, total

        w = DBWorker(fn)
        w.result.connect(self._on_data)
        w.start()
        self._workers.append(w)

    def _on_data(self, data, error):
        if error:
            self._show_error(error)
            return
        cols, rows, total = data
        self._populate(cols, rows)
        shown_end = self._offset + len(rows)
        self.row_info.setText(
            f"Rows {self._offset + 1}–{shown_end} of {total}" if rows else "No rows"
        )
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(isinstance(total, int) and shown_end < total)

    def _populate(self, cols, rows):
        self.data_table.clear()
        self.data_table.setColumnCount(len(cols))
        self.data_table.setRowCount(len(rows))
        self.data_table.setHorizontalHeaderLabels(cols)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                text = "NULL" if val is None else str(val)
                cell = QTableWidgetItem(text)
                if val is None:
                    cell.setForeground(QColor("#475569"))
                self.data_table.setItem(r, c, cell)
        self.data_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.data_table.horizontalHeader().setStretchLastSection(True)

    def _clear_data(self):
        self.data_table.clear()
        self.data_table.setColumnCount(0)
        self.data_table.setRowCount(0)

    def _prev_page(self):
        self._offset = max(0, self._offset - self._page_size)
        self._load_data()

    def _next_page(self):
        self._offset += self._page_size
        self._load_data()

    # ── SQL runner ────────────────────────────────────────────────────────────

    def _run_sql(self):
        sql = self.sql_input.text().strip()
        if not sql or not self._conn:
            return
        self.btn_run.setEnabled(False)
        self._set_status("Running...", "#f59e0b")

        def fn():
            cur = self._conn.cursor()
            cur.execute(sql)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(500)
                return "select", cols, rows
            else:
                self._conn.commit()
                return "exec", cur.rowcount, []

        w = DBWorker(fn)
        w.result.connect(self._on_sql_done)
        w.start()
        self._workers.append(w)

    def _on_sql_done(self, data, error):
        self.btn_run.setEnabled(True)
        if error:
            self._show_error(error)
            return
        if data[0] == "select":
            _, cols, rows = data
            self._populate(cols, rows)
            self.row_info.setText(f"{len(rows)} rows returned")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self._set_status(f"Connected: {self.db_combo.currentText()}", "#22c55e")
        else:
            _, count, _ = data
            self._clear_data()
            self._set_status(f"OK — {count} row(s) affected", "#22c55e")

    def _show_error(self, error: str):
        self._set_status("Error", "#ef4444")
        self.data_table.clear()
        self.data_table.setColumnCount(1)
        self.data_table.setRowCount(1)
        self.data_table.setHorizontalHeaderLabels(["Error"])
        cell = QTableWidgetItem(error)
        cell.setForeground(QColor("#ef4444"))
        self.data_table.setItem(0, 0, cell)
        self.data_table.horizontalHeader().setStretchLastSection(True)
