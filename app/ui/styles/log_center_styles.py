"""Log center stylesheet generation."""

from __future__ import annotations


# Keep this module free of Qt imports and theme lookups. The caller owns color
# resolution; this module owns only the page-specific QSS contract.
def generate_log_center_stylesheet(c: dict[str, str]) -> str:
    return f"""
QWidget#LogCenterPage {{
    background-color: {c["bg"]};
    color: {c["text"]};
}}
QFrame#LogListPanel,
QFrame#LogInspectorPanel {{
    background-color: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
}}
QWidget#LogTabs {{
    background: transparent;
    border-bottom: 1px solid {c["border"]};
}}
QWidget#LogTabs QPushButton#LogTabButton {{
    min-height: 34px;
    max-height: 34px;
    border: 1px solid transparent;
    border-bottom: 3px solid transparent;
    border-radius: 8px;
    background: transparent;
    color: {c["muted"]};
    font-size: 14px;
    font-weight: 500;
    padding: 0px 12px;
    margin: 0px 3px 4px 0px;
}}
QWidget#LogTabs QPushButton#LogTabButton:hover {{
    background: {c["panel_soft"]};
    color: {c["text"]};
    border-color: {c["border"]};
    border-bottom-color: {c["border"]};
}}
QWidget#LogTabs QPushButton#LogTabButton:checked,
QWidget#LogTabs QPushButton#LogTabButton[active="true"],
QWidget#LogTabs QPushButton#LogTabButton[selected="true"] {{
    color: {c["accent"]};
    background: {c["accent_soft"]};
    border: 1px solid {c["accent"]};
    border-bottom: 3px solid {c["accent"]};
    font-weight: 800;
}}
QWidget#LogTabs QPushButton#LogTabButton:checked:hover,
QWidget#LogTabs QPushButton#LogTabButton[active="true"]:hover,
QWidget#LogTabs QPushButton#LogTabButton[selected="true"]:hover {{
    color: {c["accent"]};
    background: {c["accent_soft"]};
    border-color: {c["accent"]};
    border-bottom-color: {c["accent"]};
}}
QFrame#LogFilterBar {{
    background-color: {c["panel_soft"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QLabel#LogFilterLabel {{
    color: {c["muted"]};
    font-size: 12px;
}}
QComboBox#LogFilterControl,
QLineEdit#LogFilterControl,
QLineEdit#LogFilterTextInput {{
    background: {c["input"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    min-height: 32px;
    max-height: 32px;
    padding: 2px 10px;
    font-size: 13px;
    color: {c["text"]};
}}
QLineEdit#LogFilterControl:focus,
QLineEdit#LogFilterControl[focused="true"],
QLineEdit#LogFilterTextInput:focus,
QLineEdit#LogFilterTextInput[focused="true"] {{
    background: {c["input"]};
    border: 2px solid {c["accent"]};
    padding: 1px 9px;
}}
QComboBox#LogFilterControl QAbstractItemView {{
    background: {c["panel"]};
    color: {c["text"]};
    border: 2px solid {c["accent"]};
    border-radius: 8px;
    padding: 0px;
    selection-background-color: {c["accent"]};
    selection-color: #ffffff;
}}
QComboBox#LogFilterControl QAbstractItemView::item {{
    min-height: 34px;
    padding: 4px 10px;
}}
QComboBox#LogFilterControl QAbstractItemView::item:selected,
QComboBox#LogFilterControl QAbstractItemView::item:selected:hover,
QComboBox#LogFilterControl QAbstractItemView::item:hover {{
    background: transparent;
}}
QPushButton#LogPrimaryActionButton,
QPushButton#LogDangerActionButton,
QPushButton#LogActionButton {{
    font-size: 12px;
    font-weight: 600;
    padding: 2px 8px;
    min-height: 30px;
    max-height: 30px;
    border-radius: 8px;
}}
QPushButton#LogPrimaryActionButton {{
    background-color: {c["panel"]};
    border: 1px solid {c["accent"]};
    color: {c["accent"]};
}}
QPushButton#LogPrimaryActionButton:hover {{
    background-color: {c["accent_soft"]};
    border-color: {c["accent_hover"]};
}}
QPushButton#LogDangerActionButton {{
    background-color: {c["panel"]};
    border: 1px solid {c["danger"]};
    color: {c["danger"]};
}}
QPushButton#LogDangerActionButton:hover {{
    background-color: {c["panel_soft"]};
    border-color: {c["danger_hover"]};
}}
QPushButton#LogActionButton {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    color: {c["text"]};
}}
QPushButton#LogActionButton:hover {{
    background-color: {c["panel_soft"]};
    border-color: {c["accent"]};
    color: {c["accent"]};
}}
QFrame#LogTableContainer {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QTableView#LogItemsTable {{
    background: {c["panel"]};
    border: none;
    gridline-color: {c["border"]};
    selection-background-color: {c["row_selected"]};
    color: {c["text"]};
}}
QTableView#LogItemsTable::item {{
    padding-left: 10px;
    padding-right: 10px;
    font-size: 13px;
    font-weight: 400;
    color: {c["text"]};
}}
QTableView#LogItemsTable::item:hover {{
    background: {c["panel_soft"]};
}}
QTableView#LogItemsTable::item:selected,
QTableView#LogItemsTable::item:selected:active {{
    background: {c["row_selected"]};
    color: {c["text"]};
}}
QTableView#LogItemsTable QHeaderView::section {{
    background: {c["panel_soft"]};
    border: none;
    border-bottom: 1px solid {c["border"]};
    border-right: 1px solid {c["border"]};
    min-height: 32px;
    max-height: 32px;
    font-weight: 600;
    font-size: 12px;
    color: {c["text"]};
}}
QWidget#LogTableFooter {{
    background: {c["panel"]};
    border-top: 1px solid {c["border"]};
}}
QLabel#LogFooterStats,
QLabel#LogPageIndicator {{
    color: {c["muted"]};
    font-size: 12px;
}}
QComboBox#LogFooterPageSize {{
    background: {c["input"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 0px 8px;
    color: {c["text"]};
    font-size: 12px;
}}
QComboBox#LogFooterPageSize QAbstractItemView {{
    background: {c["panel"]};
    color: {c["text"]};
    border: 2px solid {c["accent"]};
    border-radius: 8px;
    padding: 0px;
    selection-background-color: {c["accent"]};
    selection-color: #ffffff;
}}
QComboBox#LogFooterPageSize QAbstractItemView::item {{
    min-height: 32px;
    padding: 4px 10px;
}}
QComboBox#LogFooterPageSize QAbstractItemView::item:selected,
QComboBox#LogFooterPageSize QAbstractItemView::item:selected:hover,
QComboBox#LogFooterPageSize QAbstractItemView::item:hover {{
    background: transparent;
}}
QPushButton#LogFooterPageButton {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    color: {c["text"]};
    font-size: 12px;
    padding: 0px 10px;
}}
QPushButton#LogFooterPageButton:hover {{
    border-color: {c["accent"]};
    color: {c["accent"]};
    background: {c["panel_soft"]};
}}
QPushButton#LogFooterPageButton:disabled {{
    color: {c["muted"]};
    background: {c["panel_soft"]};
    border-color: {c["border"]};
}}
QWidget#LogInspectorHeader {{
    background: {c["panel"]};
    border-bottom: 1px solid {c["border"]};
}}
QLabel#LogInspectorTitle {{
    color: {c["text"]};
    font-size: 16px;
    font-weight: 700;
}}
QPushButton#LogInspectorActionButton {{
    min-height: 26px;
    max-height: 26px;
    min-width: 52px;
    padding: 2px 8px;
    border-radius: 6px;
    color: {c["text"]};
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#LogInspectorActionButton:hover {{
    color: {c["accent"]};
    border-color: {c["accent"]};
    background: {c["panel_soft"]};
}}
QPushButton#LogInspectorActionButton:disabled {{
    color: {c["muted"]};
    background: {c["panel_soft"]};
    border-color: {c["border"]};
}}
QFrame#LogDetailSummarySection,
QFrame#LogJsonSection,
QFrame#LogStackSection {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QLabel#LogSectionTitle {{
    color: {c["text"]};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#LogDetailKey {{
    color: {c["muted"]};
    font-size: 12px;
    min-width: 56px;
    max-width: 56px;
}}
QLabel#LogDetailValue {{
    color: {c["text"]};
    font-size: 13px;
    font-weight: 500;
}}
QWidget#LogKvRow {{
    background: transparent;
}}
QLabel#LogLevelBadgeInfo {{
    color: {c["accent"]};
    background-color: {c["accent_soft"]};
    border: 1px solid {c["accent"]};
    border-radius: 11px;
    padding: 0px 8px;
    font-weight: 700;
    font-size: 12px;
    min-width: 46px;
    max-width: 76px;
}}
QLabel#LogLevelBadgeSuccess {{
    color: {c["success"]};
    background-color: {c["panel_soft"]};
    border: 1px solid {c["success"]};
    border-radius: 11px;
    padding: 0px 8px;
    font-weight: 700;
    font-size: 12px;
    min-width: 64px;
    max-width: 92px;
}}
QLabel#LogLevelBadgeWarn {{
    color: {c["warning"]};
    background-color: {c["panel_soft"]};
    border: 1px solid {c["warning"]};
    border-radius: 11px;
    padding: 0px 8px;
    font-weight: 700;
    font-size: 12px;
    min-width: 50px;
    max-width: 76px;
}}
QLabel#LogLevelBadgeError {{
    color: {c["danger"]};
    background-color: {c["panel_soft"]};
    border: 1px solid {c["danger"]};
    border-radius: 11px;
    padding: 0px 8px;
    font-weight: 700;
    font-size: 12px;
    min-width: 54px;
    max-width: 80px;
}}
QLabel#LogLevelBadgeCommand {{
    color: {c["accent"]};
    background-color: {c["panel_soft"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 11px;
    padding: 0px 8px;
    font-weight: 700;
    font-size: 12px;
    min-width: 46px;
    max-width: 76px;
}}
QWidget#LogJsonSectionHeader {{
    min-height: 30px;
    max-height: 32px;
}}
QLabel#LogMessageTitle {{
    color: {c["muted"]};
    font-size: 12px;
    font-weight: 600;
    margin-top: 4px;
}}
QLabel#LogMessageBox,
QTextBrowser#LogMessageBox {{
    color: {c["text"]};
    font-size: 13px;
    font-weight: 400;
    background-color: {c["panel_soft"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 10px 12px;
    min-height: 42px;
    max-height: 180px;
}}
QTextBrowser#LogMessageBox QScrollBar:vertical {{
    width: 8px;
    background: transparent;
    margin: 2px;
}}
QTextBrowser#LogMessageBox QScrollBar::handle:vertical {{
    background: {c["scrollbar_handle"]};
    border-radius: 4px;
    min-height: 24px;
}}
QTextBrowser#LogMessageBox QScrollBar::add-line:vertical,
QTextBrowser#LogMessageBox QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QTextBrowser#LogJsonViewer {{
    background-color: {c["panel_soft"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 10px;
    color: {c["text"]};
}}
QTextBrowser#LogJsonViewer QScrollBar:vertical {{
    width: 8px;
    background: transparent;
    margin: 2px;
}}
QTextBrowser#LogJsonViewer QScrollBar::handle:vertical {{
    background: {c["scrollbar_handle"]};
    border-radius: 4px;
    min-height: 24px;
}}
QTextBrowser#LogJsonViewer QScrollBar::add-line:vertical,
QTextBrowser#LogJsonViewer QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QPlainTextEdit#LogStackText {{
    background: {c["panel_soft"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    color: {c["text"]};
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 10px;
}}
QScrollArea#LogInspectorScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#LogInspectorScroll > QWidget {{
    background: transparent;
}}
QScrollArea#LogInspectorScroll QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollArea#LogInspectorScroll QScrollBar::handle:vertical {{
    background: {c["scrollbar_handle"]};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollArea#LogInspectorScroll QScrollBar::add-line:vertical,
QScrollArea#LogInspectorScroll QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
