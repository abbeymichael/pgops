C_BG          = "#141518"
C_SURFACE     = "#1e2128"
C_SURFACE2    = "#252830"
C_BORDER      = "#2a2d35"
C_BORDER2     = "#32363f"
C_TEXT        = "#e8eaf0"
C_TEXT2       = "#9499a8"
C_TEXT3       = "#555b6e"
C_BLUE        = "#4f8ef7"
C_GREEN       = "#2ecc71"
C_RED         = "#e74c3c"
C_AMBER       = "#f39c12"
C_PURPLE      = "#8b5cf6"

SIDEBAR_W = 230

APP_STYLE = f"""
* {{ font-family: 'Segoe UI', -apple-system, sans-serif; }}
QMainWindow, QWidget {{ background: {C_BG}; color: {C_TEXT}; }}
QDialog {{ background: {C_SURFACE}; color: {C_TEXT}; }}
QMessageBox {{ background: {C_SURFACE}; color: {C_TEXT}; }}
QScrollBar:vertical {{
    background: {C_BG}; width: 5px; border-radius: 3px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER2}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C_BG}; height: 5px; border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {C_BORDER2}; border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollArea {{ background: transparent; border: none; }}
QGroupBox {{
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px 14px 12px 14px;
    font-size: 11px;
    color: {C_TEXT3};
    letter-spacing: 1px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {C_TEXT3};
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}}
QComboBox {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    color: {C_TEXT};
    font-size: 12px;
    min-width: 100px;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {C_SURFACE2};
    color: {C_TEXT};
    selection-background-color: {C_BORDER2};
    border: 1px solid {C_BORDER};
}}
QSpinBox, QTimeEdit {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    color: {C_TEXT};
    font-size: 12px;
}}
QCheckBox {{ color: {C_TEXT2}; font-size: 12px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 1px solid {C_BORDER2};
    background: {C_SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {C_BLUE};
    border: 1px solid {C_BLUE};
}}
QToolTip {{
    background: {C_SURFACE2};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 11px;
}}
"""

TABLE_STYLE = f"""
QTableWidget {{
    background: {C_SURFACE};
    color: {C_TEXT};
    border: none;
    gridline-color: {C_BORDER};
    font-size: 12px;
    outline: none;
}}
QTableWidget::item {{ padding: 0 12px; border: none; }}
QTableWidget::item:selected {{ background: {C_SURFACE2}; color: {C_TEXT}; }}
QTableWidget::item:hover {{ background: {C_SURFACE2}; }}
QHeaderView {{ background: {C_SURFACE}; border: none; }}
QHeaderView::section {{
    background: {C_SURFACE};
    color: {C_TEXT3};
    padding: 0 12px;
    height: 36px;
    border: none;
    border-bottom: 1px solid {C_BORDER};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}}
"""
