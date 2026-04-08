from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QSpinBox, QComboBox, QTimeEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame,
)
from PyQt6.QtCore import Qt, QTime

from ui.theme import (
    C_SURFACE, C_SURFACE2, C_BORDER, C_BORDER2,
    C_TEXT, C_TEXT2, C_TEXT3, C_BLUE, C_GREEN, TABLE_STYLE,
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


def _styled_combo(items, current=""):
    c = QComboBox()
    c.setFixedHeight(34)
    c.addItems(items)
    if current:
        c.setCurrentText(current)
    c.setStyleSheet(
        f"QComboBox{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 10px;color:{C_TEXT};font-size:12px;}}"
        f"QComboBox::drop-down{{border:none;}}"
        f"QComboBox QAbstractItemView{{background:{C_SURFACE2};color:{C_TEXT};"
        f"selection-background-color:{C_BORDER2};}}"
    )
    return c


def _styled_spin(lo, hi, val):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setFixedHeight(34)
    s.setStyleSheet(
        f"QSpinBox{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 10px;color:{C_TEXT};font-size:12px;}}"
    )
    return s


def _styled_time(h, m):
    t = QTimeEdit()
    t.setTime(QTime(h, m))
    t.setFixedHeight(34)
    t.setStyleSheet(
        f"QTimeEdit{{background:{C_SURFACE2};border:1px solid {C_BORDER};"
        f"border-radius:6px;padding:0 10px;color:{C_TEXT};font-size:12px;}}"
    )
    return t


class ScheduleTab(QWidget):
    """
    Standalone Schedule page.
    Public API:
      populate_dbs(list_of_str)         — refresh database checkboxes
      get_schedule() -> dict            — current settings as dict
    Callback passed in:
      on_save(schedule_dict)
      on_log(msg)
    """

    def __init__(self, scheduler, on_save, on_log, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._on_save   = on_save
        self._on_log    = on_log
        self._build()

    def populate_dbs(self, names):
        enabled = set(self._scheduler.schedule.get("databases", []))
        self.sched_db_list.setRowCount(0)
        for name in names:
            row = self.sched_db_list.rowCount()
            self.sched_db_list.insertRow(row)
            chk = QTableWidgetItem()
            chk.setCheckState(
                Qt.CheckState.Checked if name in enabled else Qt.CheckState.Unchecked
            )
            self.sched_db_list.setItem(row, 0, chk)
            self.sched_db_list.setItem(row, 1, QTableWidgetItem(name))

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

        title = QLabel("Backup Schedule")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:22px;font-weight:800;background:transparent;"
        )
        sub = QLabel("Configure automatic backups to run unattended in the background.")
        sub.setStyleSheet(f"color:{C_TEXT3};font-size:12px;background:transparent;")
        v.addWidget(title)
        v.addWidget(sub)

        sch = self._scheduler.schedule

        card = QWidget()
        card.setStyleSheet(
            f"background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:10px;"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(22, 20, 22, 20)
        cv.setSpacing(14)

        card_title = QLabel("Automatic Backup Schedule")
        card_title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:700;background:transparent;"
        )
        cv.addWidget(card_title)
        cv.addWidget(_sep())

        self.sched_enabled = QCheckBox("Enable scheduled backups")
        self.sched_enabled.setChecked(sch.get("enabled", False))
        self.sched_enabled.setStyleSheet(
            f"QCheckBox{{color:{C_TEXT2};font-size:13px;}}"
            f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
            f"border:1px solid {C_BORDER2};background:{C_SURFACE2};}}"
            f"QCheckBox::indicator:checked{{background:{C_BLUE};border:1px solid {C_BLUE};}}"
        )
        cv.addWidget(self.sched_enabled)

        FIELD_W = 140
        for label, widget_attr in [
            ("Frequency",       "sched_freq"),
            ("At time",         "sched_time"),
            ("Day (weekly)",    "sched_dow"),
            ("Keep last N",     "sched_keep"),
        ]:
            r = QHBoxLayout()
            l = _lbl(label.upper(), C_TEXT3, 10)
            l.setStyleSheet(
                f"color:{C_TEXT3};font-size:10px;font-weight:700;"
                f"letter-spacing:1px;background:transparent;"
            )
            l.setFixedWidth(FIELD_W)
            r.addWidget(l)

            if label == "Frequency":
                self.sched_freq = _styled_combo(
                    ["hourly", "daily", "weekly"], sch.get("frequency", "daily")
                )
                self.sched_freq.setFixedWidth(180)
                r.addWidget(self.sched_freq)
            elif label == "At time":
                parts = sch.get("time", "02:00").split(":")
                self.sched_time = _styled_time(int(parts[0]), int(parts[1]))
                self.sched_time.setFixedWidth(120)
                r.addWidget(self.sched_time)
            elif label == "Day (weekly)":
                self.sched_dow = _styled_combo(
                    ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
                )
                self.sched_dow.setCurrentIndex(sch.get("day_of_week", 0))
                self.sched_dow.setFixedWidth(180)
                r.addWidget(self.sched_dow)
            elif label == "Keep last N":
                self.sched_keep = _styled_spin(1, 365, sch.get("keep_count", 7))
                self.sched_keep.setFixedWidth(100)
                r.addWidget(self.sched_keep)

            r.addStretch()
            cv.addLayout(r)

        cv.addWidget(_sep())

        db_lbl = _lbl("DATABASES TO INCLUDE", C_TEXT3, 10)
        db_lbl.setStyleSheet(
            f"color:{C_TEXT3};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;"
        )
        cv.addWidget(db_lbl)

        self.sched_db_list = QTableWidget(0, 2)
        self.sched_db_list.setHorizontalHeaderLabels(["", "Database"])
        self.sched_db_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sched_db_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sched_db_list.setStyleSheet(TABLE_STYLE)
        self.sched_db_list.verticalHeader().setVisible(False)
        self.sched_db_list.setMaximumHeight(140)
        self.sched_db_list.setEditTriggers(self.sched_db_list.EditTrigger.NoEditTriggers)
        cv.addWidget(self.sched_db_list)

        self.next_run_lbl = _lbl("", C_TEXT3, 11)
        cv.addWidget(self.next_run_lbl)
        v.addWidget(card)

        save_btn = _btn("Save Schedule", C_BLUE, "#3b7de8", h=42)
        save_btn.clicked.connect(self._save)
        v.addWidget(save_btn)

        self.status_lbl = _lbl("", C_GREEN, 12)
        v.addWidget(self.status_lbl)
        v.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _save(self):
        selected = []
        for row in range(self.sched_db_list.rowCount()):
            chk  = self.sched_db_list.item(row, 0)
            name = self.sched_db_list.item(row, 1)
            if chk and name and chk.checkState() == Qt.CheckState.Checked:
                selected.append(name.text())
        t = self.sched_time.time()
        schedule = {
            "enabled":     self.sched_enabled.isChecked(),
            "frequency":   self.sched_freq.currentText(),
            "time":        f"{t.hour():02d}:{t.minute():02d}",
            "day_of_week": self.sched_dow.currentIndex(),
            "keep_count":  self.sched_keep.value(),
            "databases":   selected,
        }
        self._on_save(schedule)
        self.status_lbl.setText(
            "Scheduler running." if schedule["enabled"] else "Scheduler disabled."
        )
        self.next_run_lbl.setText(f"Next run: {self._scheduler.next_run_str()}")

    def refresh_next_run(self):
        self.next_run_lbl.setText(f"Next run: {self._scheduler.next_run_str()}")
