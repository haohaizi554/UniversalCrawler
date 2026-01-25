# app/ui/styles.py

COLOR_BG = "#181818"
COLOR_PANEL = "#1e1e1e"
COLOR_INPUT = "#252526"
COLOR_ACCENT = "#007acc"
COLOR_DANGER = "#C92C2C"
COLOR_TEXT = "#e0e0e0"
COLOR_BORDER = "#333333"

DARK_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}}
/* ================= 顶部工具栏 ================= */
QFrame#TopBar {{
    background-color: {COLOR_PANEL};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    margin: 0px; 
    padding: 0px;
}}
/* ================= 左侧/右侧 面板容器 ================= */
QFrame#ContentPanel {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
}}
/* ================= 列表标题栏 (存放路径) ================= */
QFrame#HeaderBar {{
    background-color: #252526;
    border-bottom: 1px solid {COLOR_BORDER};
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
/* 路径文字高亮 */
QLabel#PathLabel {{
    color: {COLOR_ACCENT};
    font-family: 'Consolas', monospace;
    font-weight: bold;
    padding-left: 5px;
}}
/* ================= 输入组件 ================= */
QLineEdit {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    background-color: {COLOR_INPUT};
    color: #fff;
    padding: 4px;
}}
QLineEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}
QComboBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    background-color: {COLOR_INPUT};
    padding: 4px;
}}
/* ================= 按钮 ================= */
QPushButton {{
    background-color: #2d2d2d;
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    color: #eee;
    padding: 5px 15px; /* 增加左右内边距，防止文字截断 */
}}
QPushButton:hover {{ background-color: #3e3e3e; }}
QPushButton:pressed {{ background-color: #222; }}
QPushButton#PrimaryBtn {{
    background-color: {COLOR_ACCENT};
    border: none;
    font-weight: bold;
}}
QPushButton#PrimaryBtn:hover {{ background-color: #0062a3; }}
QPushButton#DangerBtn {{
    background-color: {COLOR_DANGER};
    border: none;
    font-weight: bold;
}}
QPushButton#DangerBtn:hover {{ background-color: #992222; }}
QPushButton#DangerBtn:disabled {{
    background-color: #2d2d2d;
    color: #555;
    border: 1px solid {COLOR_BORDER};
}}

QPushButton#DirBtn {{
    background-color: {COLOR_INPUT};
    border: 1px dashed #555;
    color: #aaa;
    text-align: left;
}}
QPushButton#DirBtn:hover {{
    border: 1px dashed {COLOR_ACCENT};
    color: #fff;
    background-color: #2d2d2d;
}}

/* ================= 其他 ================= */
QProgressBar {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    background-color: {COLOR_INPUT};
    text-align: center;
    font-size: 11px;
}}
QProgressBar::chunk {{ background-color: {COLOR_ACCENT}; }}
QSplitter::handle {{ background-color: {COLOR_BG}; }}
QSplitter::handle:hover {{ background-color: {COLOR_ACCENT}; }}

/* 滚动条 (亮色滑块) */
QScrollBar:vertical {{ background: #111; width: 12px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: #888; min-height: 20px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: #fff; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ background: #111; height: 12px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: #888; min-width: 20px; border-radius: 4px; }}
QScrollBar::handle:horizontal:hover {{ background: #fff; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0px; }}
"""