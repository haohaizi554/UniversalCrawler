# app/ui/styles.py

# ================= 深色主题配色 (VS Code Dark+) =================
DARK_BG = "#1e1e1e"
DARK_PANEL = "#252526"
DARK_INPUT = "#3c3c3c"
DARK_ACCENT = "#0078d4"
DARK_DANGER = "#f14c4c"
DARK_TEXT = "#cccccc"
DARK_BORDER = "#3c3c3c"

# ================= 浅色主题配色 (VS Code Light+ / Notion 风格) =================
LIGHT_BG = "#f3f3f3"          # 主背景 - 柔和灰
LIGHT_PANEL = "#ffffff"        # 面板 - 纯白
LIGHT_INPUT = "#ffffff"        # 输入框
LIGHT_ACCENT = "#0078d4"       # 强调色 - 蓝色
LIGHT_DANGER = "#d13438"       # 危险色
LIGHT_TEXT = "#3b3b3b"         # 文字 - 深灰
LIGHT_BORDER = "#e0e0e0"       # 边框
LIGHT_SIDEBAR = "#f8f8f8"      # 侧边栏 - 更浅的灰


def generate_stylesheet(is_dark=True):
    """根据主题生成样式表"""
    if is_dark:
        bg = DARK_BG
        panel = DARK_PANEL
        inp = DARK_INPUT
        accent = DARK_ACCENT
        danger = DARK_DANGER
        text = DARK_TEXT
        border = DARK_BORDER
        btn_bg = "#2d2d2d"
        btn_hover = "#3e3e3e"
        btn_pressed = "#222"
        input_text = "#fff"
        scrollbar_bg = "#111"
        scrollbar_handle = "#888"
        video_bg = "#0a0a0a"  # 视频区域背景
        log_bg = "#1a1a1a"    # 日志区域背景
        muted_text = "#888"  # 次要文字颜色
    else:
        bg = LIGHT_BG
        panel = LIGHT_PANEL
        inp = LIGHT_INPUT
        accent = LIGHT_ACCENT
        danger = LIGHT_DANGER
        text = LIGHT_TEXT
        border = LIGHT_BORDER
        btn_bg = "#f0f0f0"
        btn_hover = "#e5e5e5"
        btn_pressed = "#d5d5d5"
        input_text = LIGHT_TEXT
        scrollbar_bg = "#e0e0e0"
        scrollbar_handle = "#c0c0c0"
        video_bg = "#e8e8e8"  # 视频区域背景 - 浅灰
        log_bg = "#f0f0f0"    # 日志区域背景
        muted_text = "#666"  # 次要文字颜色

    return f"""
QMainWindow, QWidget {{
    background-color: {bg};
    color: {text};
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}}

/* ================= 顶部工具栏 ================= */
QFrame#TopBar {{
    background-color: {panel};
    border: none;
    border-bottom: 1px solid {border};
    margin: 0px;
    padding: 0px;
}}

/* ================= 左侧/右侧 面板容器 ================= */
QFrame#ContentPanel {{
    background-color: {panel};
    border: 1px solid {border};
    border-radius: 4px;
}}

/* ================= 视频播放器区域 ================= */
QVideoWidget {{
    background-color: {video_bg};
}}

/* ================= 图片显示区域 ================= */
QLabel#ImageLabel {{
    background-color: {video_bg};
}}

/* ================= 列表标题栏 (存放路径) ================= */
QFrame#HeaderBar {{
    background-color: {inp};
    border-bottom: 1px solid {border};
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}

/* 路径文字高亮 */
QLabel#PathLabel {{
    color: {accent};
    font-family: 'Consolas', monospace;
    font-weight: bold;
    padding-left: 5px;
}}

/* ================= 输入组件 ================= */
QLineEdit {{
    border: 1px solid {border};
    border-radius: 4px;
    background-color: {inp};
    color: {input_text};
    padding: 4px;
}}
QLineEdit:focus {{ border: 1px solid {accent}; }}

QComboBox {{
    border: 1px solid {border};
    border-radius: 4px;
    background-color: {inp};
    padding: 4px;
}}

/* ================= 按钮 ================= */
QPushButton {{
    background-color: {btn_bg};
    border: 1px solid {border};
    border-radius: 4px;
    color: {text};
    padding: 5px 15px;
}}
QPushButton:hover {{ background-color: {btn_hover}; }}
QPushButton:pressed {{ background-color: {btn_pressed}; }}

QPushButton#PrimaryBtn {{
    background-color: {accent};
    border: none;
    font-weight: bold;
    color: white;
}}
QPushButton#PrimaryBtn:hover {{ background-color: {'#0062a3' if is_dark else '#005a9e'}; }}

QPushButton#DangerBtn {{
    background-color: {danger};
    border: none;
    font-weight: bold;
    color: white;
}}
QPushButton#DangerBtn:hover {{ background-color: {'#992222' if is_dark else '#a12d32'}; }}
QPushButton#DangerBtn:disabled {{
    background-color: {btn_bg};
    color: {'#555' if is_dark else '#999'};
    border: 1px solid {border};
}}

QPushButton#DirBtn {{
    background-color: {inp};
    border: 1px dashed {'#555' if is_dark else '#aaa'};
    color: {'#aaa' if is_dark else '#666'};
    text-align: left;
}}
QPushButton#DirBtn:hover {{
    border: 1px dashed {accent};
    color: {text};
    background-color: {btn_hover};
}}

QPushButton#ThemeBtn {{
    background-color: {accent};
    border: none;
    border-radius: 15px;
    color: white;
    font-weight: bold;
    padding: 5px 12px;
    min-width: 60px;
}}
QPushButton#ThemeBtn:hover {{ background-color: {'#0062a3' if is_dark else '#005a9e'}; }}

/* ================= 表格 ================= */
QTableWidget {{
    background-color: {panel};
    border: none;
    gridline-color: {border};
    selection-background-color: {accent};
    selection-color: white;
}}
QTableWidget::item {{
    padding: 5px;
    border-bottom: 1px solid {border};
}}
QTableWidget::item:selected {{
    background-color: {accent};
}}
QHeaderView::section {{
    background-color: {inp};
    color: {text};
    padding: 5px;
    border: none;
    border-bottom: 1px solid {border};
    font-weight: bold;
}}

/* ================= 其他 ================= */
QProgressBar {{
    border: 1px solid {border};
    border-radius: 3px;
    background-color: {inp};
    text-align: center;
    font-size: 11px;
}}
QProgressBar::chunk {{ background-color: {accent}; }}

QSplitter::handle {{ background-color: {bg}; }}
QSplitter::handle:hover {{ background-color: {accent}; }}

/* 滚动条 */
QScrollBar:vertical {{ background: {scrollbar_bg}; width: 12px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {scrollbar_handle}; min-height: 20px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: {'#fff' if is_dark else '#666'}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

QScrollBar:horizontal {{ background: {scrollbar_bg}; height: 12px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: {scrollbar_handle}; min-width: 20px; border-radius: 4px; }}
QScrollBar::handle:horizontal:hover {{ background: {'#fff' if is_dark else '#666'}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0px; }}

/* 日志文本 */
QPlainTextEdit {{
    background-color: {log_bg};
    color: {text};
    border: 1px solid {border};
}}

/* 控制面板 */
QFrame#ControlPanel {{
    background-color: {panel};
    border-top: 1px solid {border};
}}

/* 播放按钮 */
QPushButton#PlayBtn {{
    border-radius: 16px;
    background-color: {btn_bg};
    border: 1px solid {border};
}}
QPushButton#PlayBtn:hover {{ background-color: {btn_hover}; }}

/* 时间标签 */
QLabel#TimeLabel {{
    color: {muted_text};
    font-family: 'Consolas', monospace;
    font-size: 12px;
}}

/* 全屏按钮 */
QPushButton#FullscreenBtn {{
    border-radius: 4px;
    background-color: {btn_bg};
    border: 1px solid {border};
    color: {text};
    font-size: 12px;
    padding: 0px 10px;
}}
QPushButton#FullscreenBtn:hover {{ background-color: {btn_hover}; }}

/* 日志区域 */
QPlainTextEdit#LogText {{
    background-color: {log_bg};
    color: {text};
    border: 1px solid {border};
    border-top: 1px solid {border};
}}
"""


# 兼容旧代码
DARK_STYLESHEET = generate_stylesheet(is_dark=True)
LIGHT_STYLESHEET = generate_stylesheet(is_dark=False)
