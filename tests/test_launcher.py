"""统一测试启动器（GUI + TUI + CLI 三模自适应）。"""

from __future__ import annotations

import os
import sys
import threading
from collections import defaultdict
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_PROJECT_ROOT = _TESTS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from test_registry import (
    RECOMMENDED_CATEGORY_IDS,
    TEST_ICON_PATH,
    get_category,
    get_enabled_categories,
    get_resolved_files,
    summary,
)
from test_runner import TestResult, format_summary, run_categories, run_category

try:
    from PyQt6.QtCore import QObject, QRect, QSize, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QStatusBar,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    from app.config import cfg
    from app.services.icon_registry import ui_icon_path
    from shared.icon_contract import action_icon_file
    from app.ui.layout.status_bar import StatusDotIndicator
    from app.ui.layout.window_chrome import WindowChromeFrame
    from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
    from app.ui.styles.themes import apply_application_theme, theme_colors
    from app.utils.qt_runtime import load_qt_icon

    _PYQT6_AVAILABLE = True
except ImportError:
    _PYQT6_AVAILABLE = False
    QObject = object
    QMainWindow = object
    QFrame = object
    QApplication = None
    Qt = None
    pyqtSignal = None

BG = "#070B14"
SURFACE = "#0F172A"
SURFACE_2 = "#131D32"
SURFACE_3 = "#1A2740"
SURFACE_4 = "#1E2D4A"
BORDER = "#22304D"
HAIRLINE = "#1A2438"
TEXT = "#E5EEF9"
TEXT_MUTED = "#93A4BF"
TEXT_DIM = "#667892"
ACCENT = "#5B8CFF"
ACCENT_SOFT = "#7C3AED"
ACCENT_MINT = "#18C6B8"
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
DANGER = "#EF4444"
MONO = "'JetBrains Mono','Cascadia Code','Consolas',monospace"
UI_FONT = "'Inter','Segoe UI Variable','Microsoft YaHei UI',sans-serif"

QSS = f"""
QMainWindow {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-family: {UI_FONT};
    font-size: 13px;
}}
QFrame#hero,
QFrame#panel,
QFrame#sectionHeader {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 18px;
}}
QFrame#hero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0E1A33,
        stop:0.48 #0C1730,
        stop:1 #091121);
}}
QWidget#scopeMetrics {{
    background: transparent;
}}
QFrame#scopeMetricDivider {{
    background: {BORDER};
    border: none;
    min-width: 1px;
    max-width: 1px;
}}
QFrame#categoryCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE},
        stop:1 #0B1325);
    border: 1px solid {BORDER};
    border-radius: 18px;
}}
QFrame#categoryCard[state="hover"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #12203A,
        stop:1 #0D182E);
    border: 1px solid #36527F;
}}
QFrame#categoryCard[state="selected"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1B2B47,
        stop:1 #16243B);
    border: 1px solid {ACCENT};
}}
QFrame#categoryCard[state="selected-hover"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #22375A,
        stop:1 #1A2943);
    border: 1px solid #8FB2FF;
}}
QFrame#categoryStrip {{
    background: #162846;
    border-radius: 3px;
}}
QFrame#categoryStrip[state="hover"] {{
    background: #3C5C90;
}}
QFrame#categoryStrip[state="selected"] {{
    background: {ACCENT};
}}
QFrame#categoryStrip[state="selected-hover"] {{
    background: #8FB2FF;
}}
QFrame#panelHeader {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {HAIRLINE};
}}
QFrame#sectionHeader {{
    background: transparent;
    border: none;
    border-top: 1px solid {HAIRLINE};
    border-radius: 0px;
}}
QFrame#sectionMarker {{
    background: {ACCENT_MINT};
    border-radius: 2px;
}}
QWidget#categoryViewport,
QWidget#categoryList {{
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QLabel#heroTitle {{
    font-size: 24px;
    font-weight: 700;
}}
QLabel#heroSub,
QLabel#sectionTitle,
QLabel#metaText,
QLabel#progressHint,
QLabel#emptyText,
QLabel#sectionMeta,
QLabel#categoryMetaLine,
QLabel#selectHint {{
    color: {TEXT_MUTED};
}}
QLabel#sectionLabel {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0px;
}}
QLabel#sectionMeta,
QLabel#categoryMetaLine,
QLabel#selectHint {{
    font-size: 11px;
}}
QLabel#panelTitle {{
    font-size: 15px;
    font-weight: 700;
}}
QLabel#panelSub {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#categoryTitle {{
    font-size: 15px;
    font-weight: 700;
}}
QLabel#categoryDesc {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#avatar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE_3},
        stop:1 #20314F);
    border: 1px solid #30466C;
    border-radius: 18px;
    font-size: 11px;
    font-weight: 700;
    padding: 8px 10px;
}}
QLabel#countPill,
QLabel#badgePill,
QLabel#sectionPill,
QLabel#runStatus,
QLabel#sectionCountPill {{
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#countPill {{
    color: {TEXT};
    background: #13233E;
    border: 1px solid #294168;
}}
QLabel#countPill[state="hover"] {{
    background: #173055;
    border: 1px solid #3B5D8F;
}}
QLabel#countPill[state="selected"] {{
    background: #1C3D72;
    border: 1px solid #6B98FF;
}}
QLabel#countPill[state="selected-hover"] {{
    background: #244B89;
    border: 1px solid #9EC0FF;
}}
QLabel#badgePill {{
    color: {TEXT_MUTED};
    background: #10192B;
    border: 1px solid {BORDER};
}}
QLabel#sectionPill {{
    color: {TEXT_MUTED};
    background: #0E1627;
    border: 1px solid {BORDER};
}}
QLabel#sectionCountPill {{
    color: {TEXT};
    background: #1D2B45;
    border: 1px solid #3B4E72;
}}
QLabel#runStatus {{
    color: {TEXT_MUTED};
    background: #0E1627;
    border: 1px solid {BORDER};
}}
QLabel#statValue {{
    font-size: 22px;
    font-weight: 700;
}}
QLabel#statLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QPushButton#primaryBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT},
        stop:1 #6D63FF);
    border: none;
    border-radius: 12px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 700;
    color: white;
}}
QPushButton#primaryBtn:hover {{
    background: #4A78E0;
}}
QPushButton#dangerBtn {{
    background: {DANGER};
    border: none;
    border-radius: 12px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 700;
    color: white;
}}
QPushButton#dangerBtn:hover {{
    background: #DC2626;
}}
QPushButton#ghostBtn {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    color: {TEXT_MUTED};
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#ghostBtn:hover {{
    color: {TEXT};
    background: {SURFACE_2};
}}
QCheckBox {{
    color: {TEXT_MUTED};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QTextEdit#log {{
    background: transparent;
    border: none;
    padding: 10px;
    color: {TEXT};
    font-size: 12px;
    font-family: {MONO};
    selection-background-color: {ACCENT};
}}
QFrame#logCard {{
    background: #08101E;
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QProgressBar {{
    background: #08101E;
    border: 1px solid {BORDER};
    border-radius: 10px;
    min-height: 22px;
    text-align: center;
    color: {TEXT_MUTED};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT},
        stop:1 {ACCENT_MINT});
    border-radius: 9px;
}}
QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_DIM};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""

def _shared_launcher_theme_is_dark() -> bool:
    try:
        theme = str(cfg.get("common", "theme", "light") or "light").strip().lower()
        if theme in {"light", "dark"}:
            return theme == "dark"
        return bool(cfg.get("common", "dark_theme", False))
    except Exception:
        return False

def _launcher_ui_scale_factor() -> float:
    try:
        raw = str(cfg.get("appearance", "scale", "100%") or "100%").strip()
    except Exception:
        raw = "100%"
    return {"90%": 0.9, "100%": 1.0, "110%": 1.1, "125%": 1.25}.get(raw, 1.0)

def _launcher_scaled_size(width: int, height: int) -> tuple[int, int]:
    scale = max(1.0, _launcher_ui_scale_factor())
    return int(round(width * scale)), int(round(height * scale))

def _launcher_minimum_size() -> tuple[int, int]:
    return _launcher_scaled_size(980, 640)

def _launcher_default_size() -> tuple[int, int]:
    min_width, min_height = _launcher_minimum_size()
    return max(1220, min_width), max(760, min_height)

def _launcher_runtime_colors(is_dark: bool) -> dict[str, str]:
    try:
        c = theme_colors(is_dark)
    except Exception:
        c = {
            "text": TEXT,
            "muted": TEXT_MUTED,
            "accent": ACCENT,
            "success": SUCCESS,
            "danger": DANGER,
            "warning": WARNING,
            "border": BORDER,
        }
    if is_dark:
        return {
            "text": c["text"],
            "muted": c["muted"],
            "dim": TEXT_DIM,
            "accent": c["accent"],
            "success": c["success"],
            "danger": c["danger"],
            "warning": c["warning"],
            "border": c["border"],
            "status_default_bg": "#0E1627",
            "status_running_bg": "#13233E",
            "status_running_border": "#315896",
            "status_success_bg": "#0E1E16",
            "status_success_border": "#1F6D43",
            "status_danger_bg": "#2A1115",
            "status_danger_border": "#7F1D1D",
            "status_warning_bg": "#2B1B07",
            "status_warning_border": "#8A5A12",
        }
    return {
        "text": c["text"],
        "muted": c["muted"],
        "dim": "#94A3B8",
        "accent": c["accent"],
        "success": c["success"],
        "danger": c["danger"],
        "warning": c["warning"],
        "border": c["border"],
        "status_default_bg": c["panel_soft"],
        "status_running_bg": c["accent_soft"],
        "status_running_border": c["accent"],
        "status_success_bg": "#ECFDF5",
        "status_success_border": "#86EFAC",
        "status_danger_bg": "#FEF2F2",
        "status_danger_border": "#FECACA",
        "status_warning_bg": "#FFFBEB",
        "status_warning_border": "#FDE68A",
    }

def _launcher_qss(is_dark: bool) -> str:
    try:
        c = theme_colors(is_dark)
    except Exception:
        return QSS

    bg = c["bg"]
    panel = c["panel"]
    panel_soft = c["panel_soft"]
    input_bg = c["input"]
    accent = c["accent"]
    accent_hover = c["accent_hover"]
    accent_soft = c["accent_soft"]
    row_selected = c["row_selected"]
    text = c["text"] if is_dark else "#020617"
    muted = c["muted"] if is_dark else "#334155"
    ghost_text = muted if is_dark else "#0F172A"
    disabled_text = "#6B7280" if is_dark else "#64748B"
    border = c["border"]
    border_strong = c["border_strong"]
    scrollbar_handle = c["scrollbar_handle"]
    log_bg = c["log_bg"]
    danger = c["danger"]
    return QSS + f"""
QMainWindow {{
    background: {bg};
}}
QWidget {{
    color: {text};
}}
QFrame#hero,
QFrame#panel,
QFrame#sectionHeader {{
    background: {panel};
    border: 1px solid {border};
}}
QFrame#hero {{
    background: {panel};
}}
QFrame#sectionHeader {{
    background: transparent;
    border: none;
    border-top: 1px solid {border};
    border-radius: 0px;
}}
QFrame#sectionMarker {{
    background: {accent};
    border-radius: 2px;
}}
QFrame#categoryCard {{
    background: {panel};
    border: 1px solid {border};
}}
QFrame#categoryCard[state="hover"] {{
    background: {panel_soft};
    border: 1px solid {border_strong};
}}
QFrame#categoryCard[state="selected"] {{
    background: {accent_soft};
    border: 1px solid {accent};
}}
QFrame#categoryCard[state="selected-hover"] {{
    background: {row_selected};
    border: 1px solid {accent_hover};
}}
QFrame#categoryStrip {{
    background: {border_strong};
}}
QFrame#categoryStrip[state="hover"],
QFrame#categoryStrip[state="selected"],
QFrame#categoryStrip[state="selected-hover"] {{
    background: {accent};
}}
QFrame#panelHeader {{
    border-bottom: 1px solid {border};
}}
QFrame#scopeMetricDivider {{
    background: {border};
}}
QWidget#contentBody,
QWidget#categoryViewport,
QWidget#categoryList {{
    background: transparent;
}}
QLabel#heroSub,
QLabel#sectionTitle,
QLabel#metaText,
QLabel#progressHint,
QLabel#emptyText,
QLabel#sectionMeta,
QLabel#categoryMetaLine,
QLabel#selectHint,
QLabel#panelSub,
QLabel#categoryDesc,
QLabel#statLabel {{
    color: {muted};
}}
QLabel#heroTitle,
QLabel#sectionLabel,
QLabel#panelTitle,
QLabel#categoryTitle,
QLabel#statValue {{
    color: {text};
}}
QLabel#avatar {{
    background: {panel_soft};
    border: 1px solid {border_strong};
}}
QLabel#countPill,
QLabel#sectionCountPill {{
    color: {text};
    background: {accent_soft};
    border: 1px solid {border_strong};
}}
QLabel#countPill[state="hover"],
QLabel#countPill[state="selected"],
QLabel#countPill[state="selected-hover"] {{
    background: {row_selected};
    border: 1px solid {accent};
}}
QLabel#badgePill,
QLabel#sectionPill,
QLabel#runStatus {{
    color: {muted};
    background: {panel_soft};
    border: 1px solid {border};
}}
QPushButton#primaryBtn {{
    background: {accent};
    color: white;
}}
QPushButton#primaryBtn:hover {{
    background: {accent_hover};
}}
QPushButton#dangerBtn {{
    background: {danger};
    color: white;
}}
QPushButton#ghostBtn {{
    background: transparent;
    border: 1px solid {border};
    color: {ghost_text};
}}
QPushButton#ghostBtn:hover {{
    color: {text};
    background: {panel_soft};
}}
QPushButton#ghostBtn:disabled,
QPushButton#primaryBtn:disabled,
QPushButton#dangerBtn:disabled {{
    color: {disabled_text};
    background: {panel_soft};
    border: 1px solid {border};
}}
QPushButton#ThemeBtn {{
    min-width: 48px;
    min-height: 36px;
    max-width: 48px;
    max-height: 36px;
    background: {panel};
    border: 1px solid {border};
    border-radius: 18px;
    padding: 0px;
}}
QPushButton#ThemeBtn:hover {{
    background: {panel_soft};
    border-color: {border_strong};
}}
QCheckBox {{
    color: {muted};
}}
QCheckBox::indicator {{
    border: 1px solid {border};
    background: {input_bg};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QTextEdit#log {{
    background: transparent;
    border: none;
    color: {text};
    selection-background-color: {accent};
}}
QFrame#logCard {{
    background: {log_bg};
    border: 1px solid {border};
}}
QProgressBar {{
    background: {input_bg};
    border: 1px solid {border};
    color: {muted};
}}
QProgressBar::chunk {{
    background: {accent};
}}
QStatusBar {{
    background: {panel};
    border-top: 1px solid {border};
    color: {muted};
}}
QScrollBar::handle:vertical {{
    background: {scrollbar_handle};
}}
QScrollBar::handle:vertical:hover {{
    background: {border_strong};
}}
"""

def _merge_results(current: TestResult | None, update: TestResult) -> TestResult:
    if current is None:
        return TestResult(
            category_id=update.category_id,
            category_name=update.category_name,
            file_count=update.file_count,
            passed=update.passed,
            failed=update.failed,
            skipped=update.skipped,
            errors=update.errors,
            duration=update.duration,
            returncode=update.returncode,
            output=update.output,
            success=update.success,
            started_at=update.started_at,
            finished_at=update.finished_at,
            failed_tests=list(update.failed_tests),
        )
    current.passed += update.passed
    current.failed += update.failed
    current.skipped += update.skipped
    current.errors += update.errors
    current.duration += update.duration
    current.output += update.output
    current.failed_tests.extend(update.failed_tests)
    current.returncode = 0 if current.failed == 0 and current.errors == 0 else 1
    current.success = current.returncode == 0
    current.finished_at = update.finished_at
    return current

class TestRunnerWorker(threading.Thread):
    __test__ = False

    def __init__(self, category_ids, callback, *, no_failfast=True, verbose=False):
        super().__init__(daemon=True)
        self.category_ids = list(category_ids)
        self.callback = callback
        self.no_failfast = no_failfast
        self.verbose = verbose
        self.results: list[TestResult] = []
        self._stop = False

    def stop(self):
        self._stop = True

    def _emit(self, event, category_id, name, payload):
        try:
            self.callback(event, category_id, name, payload)
        except Exception:
            pass

    def run(self):
        for category_id in self.category_ids:
            if self._stop:
                break

            category = get_category(category_id)
            files = get_resolved_files(category_id)
            self._emit("category_start", category_id, category.name, len(files))

            aggregated: TestResult | None = None
            for index, file_path in enumerate(files, 1):
                if self._stop:
                    break
                self._emit("file_start", category_id, file_path, {"index": index, "total": len(files)})
                result = run_category(
                    category_id=category_id,
                    category_name=category.name,
                    files=[file_path],
                    verbose=self.verbose,
                    no_failfast=self.no_failfast,
                )
                aggregated = _merge_results(aggregated, result)
                self._emit("file_done", category_id, file_path, result)
                if not self.no_failfast and not result.success:
                    break

            if aggregated is None:
                aggregated = TestResult(
                    category_id=category_id,
                    category_name=category.name,
                    file_count=0,
                    success=True,
                )

            self.results.append(aggregated)
            self._emit("category_done", category_id, category.name, aggregated)
            if self._stop or (not self.no_failfast and not aggregated.success):
                break

        self._emit("all_done", "", "", self.results)

if _PYQT6_AVAILABLE:

    class _Signals(QObject):
        event = pyqtSignal(str, str, object, object)

    class _LogCard(QFrame):
        """Rounded log surface with a compact preferred height for the minimum window."""

        _PREFERRED_HEIGHT = 140

        def sizeHint(self):
            hint = super().sizeHint()
            return QSize(hint.width(), max(self.minimumHeight(), min(hint.height(), self._PREFERRED_HEIGHT)))

    class _SectionHeader(QFrame):
        def __init__(self, section_name: str, count: int):
            super().__init__()
            self.setObjectName("sectionHeader")
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4, 10, 4, 8)
            layout.setSpacing(10)

            marker = QFrame()
            marker.setObjectName("sectionMarker")
            marker.setFixedSize(4, 34)
            layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)

            title_col = QVBoxLayout()
            title_col.setSpacing(4)

            title_row = QHBoxLayout()
            title_row.setSpacing(8)

            label = QLabel(section_name)
            label.setObjectName("sectionLabel")
            title_row.addWidget(label)

            pill = QLabel(f"{count} 项")
            pill.setObjectName("sectionCountPill")
            title_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)
            title_row.addStretch(1)
            title_col.addLayout(title_row)

            meta = QLabel("按职责组织，可独立选择或组合运行")
            meta.setObjectName("sectionMeta")
            meta.setWordWrap(True)
            title_col.addWidget(meta)
            layout.addLayout(title_col, 1)

    class _CategoryCard(QFrame):
        def __init__(self, category, on_click):
            super().__init__()
            self.category = category
            self.on_click = on_click
            self._selected = False
            self._hovered = False
            self.setObjectName("categoryCard")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setProperty("selected", False)
            self.setProperty("state", "default")
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.strip = QFrame()
            self.strip.setObjectName("categoryStrip")
            self.strip.setProperty("state", "default")
            self.strip.setFixedWidth(6)
            layout.addWidget(self.strip)

            inner = QWidget()
            body = QHBoxLayout(inner)
            body.setContentsMargins(16, 16, 16, 16)
            body.setSpacing(14)
            layout.addWidget(inner, 1)

            self.avatar = QLabel(category.icon_letter[:4])
            self.avatar.setObjectName("avatar")
            self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.avatar.setFixedSize(60, 60)
            self._avatar_bg = category.icon_color
            body.addWidget(self.avatar)

            text_col = QVBoxLayout()
            text_col.setSpacing(7)

            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            self.title = QLabel(category.name)
            self.title.setObjectName("categoryTitle")
            title_row.addWidget(self.title)

            self.count_pill = QLabel(f"{category.file_count()} 脚本")
            self.count_pill.setObjectName("countPill")
            self.count_pill.setProperty("state", "default")
            title_row.addWidget(self.count_pill)
            title_row.addStretch(1)
            text_col.addLayout(title_row)

            self.desc = QLabel(category.description)
            self.desc.setObjectName("categoryDesc")
            self.desc.setWordWrap(True)
            text_col.addWidget(self.desc)

            source_map = {
                "builtin": "内置",
                "rule": "规则收录",
                "manual": "手工收录",
                "plugin": "插件扩展",
            }
            meta = QLabel(f"{category.section} · {source_map.get(category.source, category.source)}")
            meta.setObjectName("categoryMetaLine")
            text_col.addWidget(meta)

            badges = list(category.badges)
            if category.requires_gui:
                badges.append("GUI")
            if category.requires_network:
                badges.append("网络")
            badge_row = QHBoxLayout()
            badge_row.setSpacing(6)
            if not badges:
                badges = [category.section]
            for badge in badges[:3]:
                pill = QLabel(f"#{badge}")
                pill.setObjectName("badgePill")
                badge_row.addWidget(pill)
            badge_row.addStretch(1)
            text_col.addLayout(badge_row)

            body.addLayout(text_col, 1)
            self._apply_visual_state()

        def _visual_state(self) -> str:
            if self._selected and self._hovered:
                return "selected-hover"
            if self._selected:
                return "selected"
            if self._hovered:
                return "hover"
            return "default"

        def _repolish(self, widget):
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
            widget.update()

        def _apply_visual_state(self):
            state = self._visual_state()
            self.setProperty("selected", self._selected)
            self.setProperty("state", state)
            self.strip.setProperty("state", state)
            self.count_pill.setProperty("state", state)

            border_map = {
                "default": "none",
                "hover": "1px solid #8FB2FF",
                "selected": "2px solid #D5E4FF",
                "selected-hover": "2px solid white",
            }
            self.avatar.setStyleSheet(
                f"color: white; background: {self._avatar_bg}; "
                f"border: {border_map[state]}; border-radius: 18px;"
            )
            for widget in (self, self.strip, self.count_pill):
                self._repolish(widget)

        def _set_hovered(self, hovered: bool):
            hovered = bool(hovered)
            if self._hovered == hovered:
                return
            self._hovered = hovered
            self._apply_visual_state()

        def enterEvent(self, event):
            self._set_hovered(True)
            super().enterEvent(event)

        def leaveEvent(self, event):
            self._set_hovered(False)
            super().leaveEvent(event)

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self.on_click(self.category)
            super().mousePressEvent(event)

        def set_selected(self, selected: bool):
            selected = bool(selected)
            if self._selected == selected:
                return
            self._selected = selected
            self._apply_visual_state()

    class LauncherWindow(QMainWindow):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("UCrawl 测试套件")
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            self.is_dark_theme = _shared_launcher_theme_is_dark()
            self._theme_colors = _launcher_runtime_colors(self.is_dark_theme)
            self._run_status_text = "待命中"
            self._run_status_tone = "default"
            apply_application_theme(self.is_dark_theme)
            self.setStyleSheet(_launcher_qss(self.is_dark_theme))
            self._apply_window_size_floor()
            self.resize(*_launcher_default_size())

            icon = _load_test_icon()
            if icon:
                self.setWindowIcon(icon)
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ucrawl.test.launcher")
            except Exception:
                pass

            self.cards: dict[str, _CategoryCard] = {}
            self.selected_ids: list[str] = []
            self.worker: TestRunnerWorker | None = None
            self._timer: QTimer | None = None
            self._total_files = 0
            self._done_files = 0
            self._passed_tests = 0
            self._failed_tests = 0
            self._skipped_tests = 0
            self._error_tests = 0
            self._elapsed_seconds = 0.0

            self.signals = _Signals()
            self.signals.event.connect(self._on_event)

            self._build()
            self._refresh_selection_state()
            self._set_run_status("待命中", "default")

        def _build(self):
            self.window_chrome = WindowChromeFrame(
                title=self.windowTitle(),
                icon=self.windowIcon(),
                is_dark_theme=self.is_dark_theme,
            )
            self.window_title_bar = self.window_chrome.title_bar
            self.window_title_bar.minimize_requested.connect(self.showMinimized)
            self.window_title_bar.maximize_restore_requested.connect(self._toggle_maximized)
            self.window_title_bar.close_requested.connect(self.close)
            self._window_chrome_controller = FramelessWindowChromeController(
                self,
                title_bar_getter=lambda: self.window_title_bar,
                resizable=True,
                minimizable=True,
                maximizable=True,
            )
            self._window_chrome_controller.set_window_flags()
            self.setCentralWidget(self.window_chrome)
            root = self.window_chrome.body_layout
            root.setContentsMargins(18, 18, 18, 12)
            root.setSpacing(14)

            hero = QFrame()
            hero.setObjectName("hero")
            hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.hero_panel = hero
            hero_layout = QHBoxLayout(hero)
            hero_layout.setContentsMargins(20, 20, 20, 20)
            hero_layout.setSpacing(18)

            title_col = QVBoxLayout()
            title_col.setSpacing(6)
            hero_title = QLabel("测试套件仪表盘")
            hero_title.setObjectName("heroTitle")
            total_info = summary()
            recommended_count = len(RECOMMENDED_CATEGORY_IDS)
            self.hero_sub = QLabel(
                f"按职责浏览并运行。{total_info['total_categories']} 类 / "
                f"{total_info['total_files']} 脚本，推荐覆盖 {recommended_count} 条高频链路。"
            )
            hero_sub = self.hero_sub
            hero_sub.setObjectName("heroSub")
            hero_sub.setWordWrap(False)
            title_col.addWidget(hero_title)
            title_col.addWidget(hero_sub)
            hero_layout.addLayout(title_col, 1)

            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            for text, tip, handler in [
                ("全部", "运行当前目录下全部可执行测试", lambda: self._select_only("all")),
                ("推荐", "选择核心高频回归组合", self._select_recommended),
                ("清空", "清空当前选择", self._clear_selection),
            ]:
                button = QPushButton(text)
                button.setObjectName("ghostBtn")
                button.setToolTip(tip)
                button.clicked.connect(handler)
                action_row.addWidget(button)
            self.btn_theme = QPushButton()
            self.btn_theme.setObjectName("ThemeBtn")
            self.btn_theme.setFixedSize(48, 36)
            self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_theme.setToolTip("切换主题")
            self.btn_theme.clicked.connect(self._toggle_theme)
            action_row.addWidget(self.btn_theme)
            hero_layout.addLayout(action_row)
            root.addWidget(hero)

            content_row = QHBoxLayout()
            content_row.setSpacing(14)
            root.addLayout(content_row, 1)

            left_panel = QFrame()
            left_panel.setObjectName("panel")
            left_panel.setMinimumWidth(360)
            left_panel.setMaximumWidth(420)
            left_layout = QVBoxLayout(left_panel)
            left_layout.setContentsMargins(16, 16, 16, 16)
            left_layout.setSpacing(12)

            left_header = QFrame()
            left_header.setObjectName("panelHeader")
            left_header_layout = QHBoxLayout(left_header)
            left_header_layout.setContentsMargins(0, 0, 0, 12)
            left_header_layout.setSpacing(10)
            left_title = QLabel("测试分类")
            left_title.setObjectName("panelTitle")
            left_sub = QLabel("按职责组合执行范围。")
            left_sub.setObjectName("panelSub")
            left_sub.setWordWrap(False)
            left_header_layout.addWidget(left_title, 0, Qt.AlignmentFlag.AlignVCenter)
            left_header_layout.addWidget(left_sub, 1, Qt.AlignmentFlag.AlignVCenter)
            left_layout.addWidget(left_header)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setMinimumHeight(150)
            scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
            scroll_body = QWidget()
            scroll_body.setObjectName("categoryViewport")
            scroll_layout = QVBoxLayout(scroll_body)
            scroll_layout.setContentsMargins(0, 0, 4, 0)
            scroll_layout.setSpacing(10)

            list_container = QWidget()
            list_container.setObjectName("categoryList")
            list_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            list_layout = QVBoxLayout(list_container)
            list_layout.setContentsMargins(0, 0, 0, 0)
            list_layout.setSpacing(10)

            grouped = defaultdict(list)
            for category in get_enabled_categories():
                grouped[category.section].append(category)

            for section_name, categories in grouped.items():
                list_layout.addWidget(_SectionHeader(section_name, len(categories)))
                for category in categories:
                    card = _CategoryCard(category, self._toggle_category)
                    self.cards[category.id] = card
                    list_layout.addWidget(card)

            scroll_layout.addWidget(list_container)
            scroll.setWidget(scroll_body)
            left_layout.addWidget(scroll, 1)
            content_row.addWidget(left_panel)

            right_col = QVBoxLayout()
            right_col.setSpacing(10)
            content_row.addLayout(right_col, 1)

            self.detail_panel = QFrame()
            self.detail_panel.setObjectName("panel")
            self.detail_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            detail_layout = QVBoxLayout(self.detail_panel)
            detail_layout.setContentsMargins(18, 18, 18, 18)
            detail_layout.setSpacing(10)

            detail_header = QFrame()
            detail_header.setObjectName("panelHeader")
            detail_header_layout = QHBoxLayout(detail_header)
            detail_header_layout.setContentsMargins(0, 0, 0, 12)
            detail_header_layout.setSpacing(12)
            self.detail_title = QLabel("执行范围")
            self.detail_title.setObjectName("heroTitle")
            self.detail_title.setStyleSheet("font-size: 20px; font-weight: 700;")
            detail_header_layout.addWidget(self.detail_title, 0, Qt.AlignmentFlag.AlignVCenter)

            self.detail_desc = QLabel("当前尚未选择测试分类，可使用全部、推荐或自定义组合。")
            self.detail_desc.setObjectName("heroSub")
            self.detail_desc.setWordWrap(False)
            detail_header_layout.addWidget(self.detail_desc, 1, Qt.AlignmentFlag.AlignVCenter)
            detail_layout.addWidget(detail_header)

            self.detail_tags = QLabel("")
            self.detail_tags.setObjectName("metaText")
            self.detail_tags.setWordWrap(True)
            detail_layout.addWidget(self.detail_tags)

            scope_metrics = QWidget()
            scope_metrics.setObjectName("scopeMetrics")
            scope_metrics_layout = QHBoxLayout(scope_metrics)
            scope_metrics_layout.setContentsMargins(0, 8, 0, 0)
            scope_metrics_layout.setSpacing(14)
            self.stat_scope = self._make_scope_metric(scope_metrics_layout, "未选", "执行模式")
            self.stat_files = self._make_scope_metric(scope_metrics_layout, "0", "去重脚本")
            self.stat_selected = self._make_scope_metric(scope_metrics_layout, "0", "已选分类")
            self.stat_misc = self._make_scope_metric(
                scope_metrics_layout,
                str(len(get_resolved_files("misc"))),
                "未归类脚本",
            )
            detail_layout.addWidget(scope_metrics)
            right_col.addWidget(self.detail_panel)

            control_panel = QFrame()
            control_panel.setObjectName("panel")
            control_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.control_panel = control_panel
            control_layout = QVBoxLayout(control_panel)
            control_layout.setContentsMargins(18, 16, 18, 12)
            control_layout.setSpacing(10)

            control_header = QFrame()
            control_header.setObjectName("panelHeader")
            control_header_layout = QHBoxLayout(control_header)
            control_header_layout.setContentsMargins(0, 0, 0, 12)
            control_header_layout.setSpacing(10)
            control_title_col = QVBoxLayout()
            control_title_col.setSpacing(4)
            control_title = QLabel("执行面板")
            control_title.setObjectName("panelTitle")
            control_sub = QLabel("运行中会按文件推进进度，并在日志区显示套件摘要。")
            control_sub.setObjectName("panelSub")
            control_sub.setWordWrap(True)
            control_title_col.addWidget(control_title)
            control_title_col.addWidget(control_sub)
            control_header_layout.addLayout(control_title_col, 1)
            self.run_status = QLabel("待命中")
            self.run_status.setObjectName("runStatus")
            control_header_layout.addWidget(self.run_status)
            control_layout.addWidget(control_header)

            options_row = QHBoxLayout()
            options_row.setSpacing(18)
            self.chk_failfast = QCheckBox("失败即停")
            self.chk_verbose = QCheckBox("详细输出")
            options_row.addWidget(self.chk_failfast)
            options_row.addWidget(self.chk_verbose)
            options_row.addStretch(1)
            self.current_hint = QLabel("待命中")
            self.current_hint.setObjectName("progressHint")
            self.current_hint.setWordWrap(True)
            options_row.addWidget(self.current_hint)
            control_layout.addLayout(options_row)

            self.progress = QProgressBar()
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            control_layout.addWidget(self.progress)

            progress_meta = QHBoxLayout()
            progress_meta.setSpacing(10)
            self.progress_detail = QLabel("尚未开始")
            self.progress_detail.setObjectName("progressHint")
            self.progress_detail.setWordWrap(False)
            self.progress_detail.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self.progress_detail.setMinimumWidth(self.progress_detail.fontMetrics().horizontalAdvance("已完成 000/000 个脚本") + 12)
            self.progress_percent = QLabel("0%")
            self.progress_percent.setObjectName("progressHint")
            progress_meta.addWidget(self.progress_detail, 0)
            progress_meta.addStretch(1)
            progress_meta.addWidget(self.progress_percent)
            control_layout.addLayout(progress_meta)

            action_row_2 = QHBoxLayout()
            action_row_2.setSpacing(10)
            self.btn_run = QPushButton("运行测试")
            self.btn_run.setObjectName("primaryBtn")
            self.btn_run.clicked.connect(self._run)
            action_row_2.addWidget(self.btn_run)

            self.btn_stop = QPushButton("停止")
            self.btn_stop.setObjectName("dangerBtn")
            self.btn_stop.clicked.connect(self._stop)
            self.btn_stop.hide()
            action_row_2.addWidget(self.btn_stop)
            action_row_2.addStretch(1)
            control_layout.addLayout(action_row_2)
            right_col.addWidget(control_panel)

            self.log_card = _LogCard()
            self.log_card.setObjectName("logCard")
            self.log_card.setMinimumHeight(112)
            self.log_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            log_card_layout = QVBoxLayout(self.log_card)
            log_card_layout.setContentsMargins(8, 8, 8, 8)
            log_card_layout.setSpacing(0)

            self.log = QTextEdit()
            self.log.setObjectName("log")
            self.log.setReadOnly(True)
            self.log.setFrameShape(QFrame.Shape.NoFrame)
            self.log.setPlaceholderText("运行日志会显示在这里。")
            self.log.setMinimumHeight(82)
            self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            log_card_layout.addWidget(self.log)
            right_col.addWidget(self.log_card, 1)

            self.sbar = QStatusBar()
            self.sbar.setObjectName("LauncherStatusBar")
            self._build_status_bar()
            self.setStatusBar(self.sbar)

            QShortcut(QKeySequence("F5"), self, activated=self._run)
            QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self._select_only("all"))
            QShortcut(QKeySequence("Ctrl+R"), self, activated=self._select_recommended)
            QShortcut(QKeySequence("Escape"), self, activated=self._clear_selection)
            self._set_theme(self.is_dark_theme, persist=False)

        def _build_status_bar(self):
            self.footer_status_host = QWidget()
            self.footer_status_host.setObjectName("launcherStatusStrip")
            self.footer_status_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            footer_layout = QHBoxLayout(self.footer_status_host)
            footer_layout.setContentsMargins(8, 0, 8, 0)
            footer_layout.setSpacing(10)

            self.footer_status_dot = StatusDotIndicator(self.footer_status_host, is_dark=self.is_dark_theme)
            footer_layout.addWidget(self.footer_status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

            self.footer_status_state = QLabel("就绪")
            self.footer_status_state.setObjectName("launcherFooterState")
            footer_layout.addWidget(self.footer_status_state, 0, Qt.AlignmentFlag.AlignVCenter)

            self.footer_status_detail = QLabel("等待选择测试范围")
            self.footer_status_detail.setObjectName("launcherFooterDetail")
            self.footer_status_detail.setMinimumWidth(160)
            self.footer_status_detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            footer_layout.addWidget(self.footer_status_detail, 1, Qt.AlignmentFlag.AlignVCenter)

            self.footer_status_metrics: dict[str, QLabel] = {}
            for key, text in (
                ("scripts", "脚本 0/0"),
                ("passed", "通过 0"),
                ("skipped", "跳过 0"),
                ("failed", "失败 0"),
                ("errors", "错误 0"),
                ("duration", "耗时 0.00s"),
            ):
                label = QLabel(text)
                label.setObjectName("launcherFooterMetric")
                label.setProperty("metric", key)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.footer_status_metrics[key] = label
                footer_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

            self.sbar.addPermanentWidget(self.footer_status_host, 1)
            self._set_footer_status("default", "就绪", "等待选择测试范围")

        def _style_status_bar(self, tone: str = "default"):
            if not hasattr(self, "footer_status_state"):
                return
            tone_colors = {
                "default": self._theme_color("muted"),
                "running": self._theme_color("success"),
                "success": self._theme_color("success"),
                "danger": self._theme_color("danger"),
                "warning": self._theme_color("warning"),
            }
            state_color = tone_colors.get(tone, tone_colors["default"])
            text = self._theme_color("text")
            muted = self._theme_color("muted")
            border = self._theme_color("border")
            panel = self._theme_color("status_default_bg")
            danger = self._theme_color("danger")
            warning = self._theme_color("warning")

            self.footer_status_state.setStyleSheet(f"color:{state_color}; font-weight:700;")
            self.footer_status_detail.setStyleSheet(f"color:{muted};")
            for key, label in self.footer_status_metrics.items():
                color = text
                if key in {"failed", "errors"} and not label.text().endswith(" 0"):
                    color = danger
                elif key == "skipped" and not label.text().endswith(" 0"):
                    color = warning
                label.setStyleSheet(
                    f"color:{color}; background:{panel}; border:1px solid {border}; "
                    "border-radius:9px; padding:2px 8px; font-weight:600;"
                )

        def _set_footer_status(
            self,
            tone: str,
            state: str,
            detail: str = "",
            *,
            scripts_done: int | None = None,
            scripts_total: int | None = None,
            passed: int | None = None,
            skipped: int | None = None,
            failed: int | None = None,
            errors: int | None = None,
            duration: float | None = None,
        ):
            if not hasattr(self, "footer_status_state"):
                return
            self._footer_status_tone = tone
            dot_state = {
                "running": "running",
                "success": "running",
                "danger": "error",
                "warning": "error",
            }.get(tone, "idle")
            self.footer_status_dot.set_state(dot_state)
            self.footer_status_state.setText(state)
            self.footer_status_detail.setText(detail or " ")
            self.footer_status_metrics["scripts"].setText(
                f"脚本 {int(scripts_done or 0)}/{int(scripts_total or 0)}"
                if scripts_total is not None
                else "脚本 0/0"
            )
            self.footer_status_metrics["passed"].setText(f"通过 {int(passed or 0)}")
            self.footer_status_metrics["skipped"].setText(f"跳过 {int(skipped or 0)}")
            self.footer_status_metrics["failed"].setText(f"失败 {int(failed or 0)}")
            self.footer_status_metrics["errors"].setText(f"错误 {int(errors or 0)}")
            self.footer_status_metrics["duration"].setText(f"耗时 {float(duration or 0.0):.2f}s")
            self.footer_status_host.setToolTip(
                " · ".join(
                    part
                    for part in (
                        state,
                        detail,
                        self.footer_status_metrics["scripts"].text(),
                        self.footer_status_metrics["passed"].text(),
                        self.footer_status_metrics["skipped"].text(),
                        self.footer_status_metrics["failed"].text(),
                        self.footer_status_metrics["errors"].text(),
                        self.footer_status_metrics["duration"].text(),
                    )
                    if part
                )
            )
            self.sbar.clearMessage()
            self._style_status_bar(tone)

        def _apply_window_size_floor(self):
            min_width, min_height = _launcher_minimum_size()
            central = self.centralWidget()
            if central is not None:
                for hint in (central.minimumSizeHint(), central.sizeHint()):
                    if hint.isValid():
                        min_width = max(min_width, hint.width())
                        min_height = max(min_height, hint.height())
            needs_resize = self.width() < min_width or self.height() < min_height
            self.setMinimumSize(min_width, min_height)
            target_width = max(self.width(), min_width)
            target_height = max(self.height(), min_height)
            if needs_resize:
                self.resize(target_width, target_height)
                QTimer.singleShot(0, self._apply_window_size_floor)

        def _refresh_text_minimums(self):
            tracked_names = {
                "heroTitle",
                "heroSub",
                "sectionLabel",
                "sectionMeta",
                "panelTitle",
                "panelSub",
                "categoryTitle",
                "categoryDesc",
                "categoryMetaLine",
                "metaText",
                "progressHint",
                "statValue",
                "statLabel",
                "runStatus",
                "sectionPill",
                "sectionCountPill",
                "countPill",
                "badgePill",
            }
            changed = False
            for label in self.findChildren(QLabel):
                if not label.text().strip():
                    continue
                name = label.objectName()
                if name not in tracked_names and not label.wordWrap():
                    continue
                label.ensurePolished()
                needed = self._label_minimum_text_height(label)
                if label.minimumHeight() != needed:
                    label.setMinimumHeight(needed)
                    label.updateGeometry()
                    changed = True
            for panel in (getattr(self, "detail_panel", None), getattr(self, "control_panel", None)):
                if panel is None:
                    continue
                panel.ensurePolished()
                needed = max(panel.sizeHint().height(), panel.minimumSizeHint().height(), 0)
                if needed > 0 and panel.minimumHeight() != needed:
                    panel.setMinimumHeight(needed)
                    panel.updateGeometry()
                    changed = True
            central = self.centralWidget()
            needs_floor_sync = False
            if central is not None:
                for hint in (central.minimumSizeHint(), central.sizeHint()):
                    needs_floor_sync = hint.isValid() and (
                        hint.width() > self.minimumWidth() or hint.height() > self.minimumHeight()
                    )
                    if needs_floor_sync:
                        break
            if changed or needs_floor_sync:
                self._apply_window_size_floor()
                QTimer.singleShot(0, self._apply_window_size_floor)

        @staticmethod
        def _label_minimum_text_height(label: QLabel) -> int:
            metrics = label.fontMetrics()
            line_height = max(metrics.lineSpacing(), metrics.height(), 1)
            name = label.objectName()
            vertical_padding = 10 if name in {
                "runStatus",
                "sectionPill",
                "sectionCountPill",
                "countPill",
                "badgePill",
            } else 6
            if label.wordWrap():
                width = max(label.width(), 80)
                rect = metrics.boundingRect(
                    QRect(0, 0, width, 10000),
                    int(Qt.TextFlag.TextWordWrap),
                    label.text(),
                )
                content_height = max(rect.height(), line_height)
            else:
                content_height = line_height
            return content_height + vertical_padding

        def _toggle_theme(self):
            self._set_theme(not self.is_dark_theme, persist=True)

        def _set_theme(self, is_dark: bool, *, persist: bool):
            self.is_dark_theme = bool(is_dark)
            self._theme_colors = _launcher_runtime_colors(self.is_dark_theme)
            if persist:
                try:
                    cfg.set_many(
                        "common",
                        {
                            "theme": "dark" if self.is_dark_theme else "light",
                            "dark_theme": self.is_dark_theme,
                        },
                    )
                except Exception:
                    pass
            apply_application_theme(self.is_dark_theme)
            self.setStyleSheet(_launcher_qss(self.is_dark_theme))
            if hasattr(self, "window_chrome"):
                self.window_chrome.apply_theme(self.is_dark_theme)
            if hasattr(self, "btn_theme"):
                self._set_theme_button_icon()
            if hasattr(self, "run_status"):
                self._set_run_status(self._run_status_text, self._run_status_tone)
            if hasattr(self, "footer_status_dot"):
                self.footer_status_dot.set_theme(self.is_dark_theme)
                self._style_status_bar(getattr(self, "_footer_status_tone", "default"))
            if hasattr(self, "window_chrome"):
                QTimer.singleShot(0, self._refresh_text_minimums)
            self._apply_window_size_floor()

        def _set_theme_button_icon(self):
            self.btn_theme.setText("")
            self.btn_theme.setToolTip("切换主题")
            icon_name = action_icon_file("theme_dark" if self.is_dark_theme else "theme_light")
            icon = load_qt_icon([ui_icon_path(icon_name)])
            if icon is not None:
                self.btn_theme.setIcon(icon)
                self.btn_theme.setIconSize(QSize(18, 18))

        def _theme_color(self, key: str) -> str:
            return self._theme_colors.get(key, _launcher_runtime_colors(self.is_dark_theme).get(key, TEXT))

        def _toggle_maximized(self):
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            self._window_chrome_controller.sync_title_bar_state()

        def showEvent(self, event):
            super().showEvent(event)
            self._window_chrome_controller.install()
            self._window_chrome_controller.on_show_event()
            QTimer.singleShot(0, self._refresh_text_minimums)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if hasattr(self, "window_chrome"):
                QTimer.singleShot(0, self._refresh_text_minimums)

        def closeEvent(self, event):
            self._window_chrome_controller.uninstall()
            super().closeEvent(event)

        def nativeEvent(self, event_type, message):
            hit_test = self._window_chrome_controller.handle_native_event(event_type, message)
            if hit_test is not None:
                return True, hit_test
            return False, 0

        def mousePressEvent(self, event):
            if self._window_chrome_controller.mouse_press_event(event):
                return
            super().mousePressEvent(event)

        def eventFilter(self, watched, event):
            if self._window_chrome_controller.event_filter(watched, event):
                return True
            return super().eventFilter(watched, event)

        def _make_scope_metric(self, parent_layout, value, label):
            if parent_layout.count() > 0:
                divider = QFrame()
                divider.setObjectName("scopeMetricDivider")
                divider.setFixedWidth(1)
                divider.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
                parent_layout.addWidget(divider)

            metric = QWidget()
            metric.setObjectName("scopeMetric")
            metric.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)
            line.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            metric.setLayout(line)

            value_label = QLabel(value)
            value_label.setObjectName("statValue")
            value_label.setWordWrap(False)
            text_label = QLabel(label)
            text_label.setObjectName("statLabel")
            text_label.setWordWrap(False)
            line.addWidget(value_label, 0, Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(text_label, 0, Qt.AlignmentFlag.AlignVCenter)
            line.addStretch(1)
            parent_layout.addWidget(metric, 1)
            return value_label

        def _set_run_status(self, text: str, tone: str):
            self._run_status_text = text
            self._run_status_tone = tone
            color_map = {
                "default": (
                    self._theme_color("muted"),
                    self._theme_color("status_default_bg"),
                    self._theme_color("border"),
                ),
                "running": (
                    self._theme_color("text"),
                    self._theme_color("status_running_bg"),
                    self._theme_color("status_running_border"),
                ),
                "success": (
                    self._theme_color("success"),
                    self._theme_color("status_success_bg"),
                    self._theme_color("status_success_border"),
                ),
                "danger": (
                    self._theme_color("danger"),
                    self._theme_color("status_danger_bg"),
                    self._theme_color("status_danger_border"),
                ),
                "warning": (
                    self._theme_color("warning"),
                    self._theme_color("status_warning_bg"),
                    self._theme_color("status_warning_border"),
                ),
            }
            fg, bg, border = color_map.get(tone, color_map["default"])
            self.run_status.setText(text)
            self.run_status.setStyleSheet(
                f"color:{fg}; background:{bg}; border:1px solid {border}; border-radius:10px; padding:4px 10px; font-size:11px; font-weight:700;"
            )

        def _update_progress_labels(self):
            total = max(self._total_files, 1)
            percent = int(min(self._done_files / total, 1) * 100)
            self.progress_percent.setText(f"{percent}%")
            self.progress_detail.setText(f"已完成 {self._done_files}/{self._total_files} 个脚本")
            self.progress_detail.setMinimumWidth(
                max(
                    self.progress_detail.minimumWidth(),
                    self.progress_detail.fontMetrics().horizontalAdvance(self.progress_detail.text()) + 12,
                )
            )

        def _selected_files(self) -> list[str]:
            files: list[str] = []
            for category_id in self.selected_ids:
                for file_path in get_resolved_files(category_id):
                    if file_path not in files:
                        files.append(file_path)
            return files

        def _build_selection_snapshot(self) -> dict:
            selected_categories = [get_category(cid) for cid in self.selected_ids if cid in self.cards]
            unique_files = self._selected_files()

            if not selected_categories:
                return {
                    "categories": selected_categories,
                    "unique_files": unique_files,
                    "mode": "未选",
                    "detail_desc": "当前尚未选择测试分类，可使用全部、推荐或自定义组合。",
                    "detail_tags": "快捷键: F5 运行  ·  Ctrl+R 推荐  ·  Ctrl+1 全部  ·  Esc 清空",
                    "status": "就绪",
                }

            if len(selected_categories) == 1:
                category = selected_categories[0]
                mode = "全量" if category.id == "all" else "单项"
                tags = [category.name, category.section, f"{len(unique_files)} 个去重脚本"]
                if category.badges:
                    tags.extend(category.badges[:3])
                if category.requires_gui:
                    tags.append("需要 GUI")
                if category.requires_network:
                    tags.append("涉及网络")
                return {
                    "categories": selected_categories,
                    "unique_files": unique_files,
                    "mode": mode,
                    "detail_desc": f"当前执行范围为 {category.name}。",
                    "detail_tags": "  ·  ".join(tags),
                    "status": f"执行范围：{mode} / {len(unique_files)} 个脚本",
                }

            names = " / ".join(category.name for category in selected_categories[:4])
            if len(selected_categories) > 4:
                names += " / ..."
            return {
                "categories": selected_categories,
                "unique_files": unique_files,
                "mode": "组合",
                "detail_desc": "当前执行范围为多分类组合，运行时按所选顺序依次执行。",
                "detail_tags": f"{names}  ·  共 {len(unique_files)} 个去重脚本",
                "status": f"执行范围：组合 / {len(selected_categories)} 个分类 / {len(unique_files)} 个脚本",
            }

        def _clear_selection(self):
            self.selected_ids.clear()
            self._refresh_selection_state()

        def _select_only(self, category_id: str):
            self.selected_ids = [category_id]
            self._refresh_selection_state()

        def _select_recommended(self):
            self.selected_ids = [cid for cid in RECOMMENDED_CATEGORY_IDS if cid in self.cards]
            self._refresh_selection_state()

        def _toggle_category(self, category):
            category_id = category.id
            if category_id == "all":
                self._select_only("all")
                return
            if "all" in self.selected_ids:
                self.selected_ids.remove("all")
            if category_id in self.selected_ids:
                self.selected_ids.remove(category_id)
            else:
                self.selected_ids.append(category_id)
            self._refresh_selection_state()

        def _refresh_selection_state(self):
            for category_id, card in self.cards.items():
                card.set_selected(category_id in self.selected_ids)

            snapshot = self._build_selection_snapshot()
            selected_categories = snapshot["categories"]
            unique_files = snapshot["unique_files"]

            self.stat_scope.setText(snapshot["mode"])
            self.stat_files.setText(str(len(unique_files)))
            self.stat_selected.setText(str(len(selected_categories)))
            self.stat_misc.setText(str(len(get_resolved_files("misc"))))
            self.detail_desc.setText(snapshot["detail_desc"])
            self.detail_tags.setText(snapshot["detail_tags"])
            QTimer.singleShot(0, self._refresh_text_minimums)

            if not selected_categories:
                self.detail_title.setText("执行范围")
                self.current_hint.setText("待命中")
                self._set_run_status("待命中", "default")
                self._set_footer_status("default", "就绪", snapshot["status"], scripts_done=0, scripts_total=0)
                return

            if len(selected_categories) == 1:
                self.detail_title.setText("执行范围")
            else:
                self.detail_title.setText("执行范围")

            self._set_footer_status(
                "default",
                "就绪",
                snapshot["status"],
                scripts_done=0,
                scripts_total=len(unique_files),
            )

        def _append_log(self, html: str):
            self.log.append(html)

        def _run(self):
            if self.worker and self.worker.is_alive():
                return
            if not self.selected_ids:
                self._set_footer_status("warning", "未选择", "请先选择测试套件", scripts_done=0, scripts_total=0)
                return

            self.log.clear()
            self._done_files = 0
            self._total_files = max(len(self._selected_files()), 1)
            self._passed_tests = 0
            self._failed_tests = 0
            self._skipped_tests = 0
            self._error_tests = 0
            self._elapsed_seconds = 0.0
            self.progress.setRange(0, self._total_files)
            self.progress.setValue(0)
            self._update_progress_labels()
            self.current_hint.setText("准备运行...")
            self._set_run_status("运行中", "running")
            self._set_footer_status(
                "running",
                "运行中",
                "准备执行测试脚本",
                scripts_done=0,
                scripts_total=self._total_files,
            )
            self.btn_run.hide()
            self.btn_stop.show()

            self.worker = TestRunnerWorker(
                self.selected_ids,
                self._emit,
                no_failfast=not self.chk_failfast.isChecked(),
                verbose=self.chk_verbose.isChecked(),
            )
            self.worker.start()

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll_worker)
            self._timer.start(150)

        def _stop(self):
            if self.worker and self.worker.is_alive():
                self.worker.stop()
                self.current_hint.setText("等待当前脚本收尾后停止...")
                self._set_run_status("停止中", "warning")
                self._set_footer_status(
                    "warning",
                    "停止中",
                    "等待当前脚本收尾",
                    scripts_done=self._done_files,
                    scripts_total=self._total_files,
                    passed=self._passed_tests,
                    skipped=self._skipped_tests,
                    failed=self._failed_tests,
                    errors=self._error_tests,
                    duration=self._elapsed_seconds,
                )

        def _emit(self, kind, category_id, name, payload):
            self.signals.event.emit(kind, category_id, str(name), payload)

        def _on_event(self, kind, category_id, name, payload):
            accent = self._theme_color("accent")
            muted = self._theme_color("muted")
            success = self._theme_color("success")
            danger = self._theme_color("danger")
            border = self._theme_color("border")

            if kind == "category_start":
                self._append_log(f"<span style='color:{accent}; font-weight:700;'>▶ {name}</span>")
                self.current_hint.setText(f"运行中: {name}")
                self._set_run_status("运行中", "running")
                self._set_footer_status(
                    "running",
                    "运行中",
                    f"当前分类：{name}",
                    scripts_done=self._done_files,
                    scripts_total=self._total_files,
                    passed=self._passed_tests,
                    skipped=self._skipped_tests,
                    failed=self._failed_tests,
                    errors=self._error_tests,
                    duration=self._elapsed_seconds,
                )
                return

            if kind == "file_start":
                path = Path(name).name
                meta = payload or {}
                self._append_log(
                    f"<span style='color:{muted};'>· {meta.get('index', 0)}/{meta.get('total', 0)} {path}</span>"
                )
                return

            if kind == "file_done":
                if isinstance(payload, TestResult):
                    result = payload
                    self._passed_tests += result.passed
                    self._failed_tests += result.failed
                    self._skipped_tests += result.skipped
                    self._error_tests += result.errors
                    self._elapsed_seconds += result.duration
                    color = success if result.success else danger
                    icon = "PASS" if result.success else "FAIL"
                    self._append_log(
                        f"<span style='color:{color};'>{icon}</span> "
                        f"<span style='color:{muted};'>P={result.passed} F={result.failed} "
                        f"S={result.skipped} E={result.errors} ({result.duration:.2f}s)</span>"
                    )
                    if result.failed_tests:
                        for failed_name in result.failed_tests[:3]:
                            self._append_log(f"<span style='color:{danger};'>  {failed_name}</span>")
                self._done_files += 1
                self.progress.setValue(min(self._done_files, self._total_files))
                self._update_progress_labels()
                tone = "danger" if self._failed_tests or self._error_tests else "running"
                self._set_footer_status(
                    tone,
                    "运行中",
                    f"已完成 {self._done_files}/{self._total_files} 个脚本",
                    scripts_done=self._done_files,
                    scripts_total=self._total_files,
                    passed=self._passed_tests,
                    skipped=self._skipped_tests,
                    failed=self._failed_tests,
                    errors=self._error_tests,
                    duration=self._elapsed_seconds,
                )
                return

            if kind == "category_done":
                if isinstance(payload, TestResult):
                    result = payload
                    color = success if result.success else danger
                    status = "完成" if result.success else "失败"
                    self._append_log(
                        f"<span style='color:{color}; font-weight:700;'>■ {name} {status}</span>"
                        f"<span style='color:{muted};'>  {result.passed} 通过 / {result.failed} 失败 / "
                        f"{result.errors} 错误 / {result.duration:.2f}s</span>"
                    )
                self._append_log("")
                return

            if kind == "all_done":
                results = payload or []
                self.btn_stop.hide()
                self.btn_run.show()
                self.progress.setValue(self.progress.maximum())
                self.current_hint.setText("已完成")
                self._done_files = self._total_files
                self._update_progress_labels()
                if self._timer is not None:
                    self._timer.stop()

                passed = sum(item.passed for item in results)
                failed = sum(item.failed for item in results)
                skipped = sum(item.skipped for item in results)
                errors = sum(item.errors for item in results)
                duration = sum(item.duration for item in results)
                self._passed_tests = passed
                self._failed_tests = failed
                self._skipped_tests = skipped
                self._error_tests = errors
                self._elapsed_seconds = duration

                self._append_log(f"<hr style='border:0;border-top:1px solid {border};'>")
                if failed == 0 and errors == 0:
                    self._set_run_status("全部通过", "success")
                    self._append_log(
                        f"<span style='color:{success}; font-weight:700; font-size:14px;'>全部通过</span>"
                        f"<span style='color:{muted};'>  {passed} 通过 / {skipped} 跳过 / {duration:.2f}s</span>"
                    )
                    self._set_footer_status(
                        "success",
                        "全部通过",
                        "测试套件运行完成",
                        scripts_done=self._done_files,
                        scripts_total=self._total_files,
                        passed=passed,
                        skipped=skipped,
                        failed=failed,
                        errors=errors,
                        duration=duration,
                    )
                else:
                    self._set_run_status("有失败", "danger")
                    self._append_log(
                        f"<span style='color:{danger}; font-weight:700; font-size:14px;'>运行结束，有失败</span>"
                        f"<span style='color:{muted};'>  {passed} 通过 / {failed} 失败 / {errors} 错误 / {duration:.2f}s</span>"
                    )
                    self._set_footer_status(
                        "danger",
                        "有失败",
                        "测试套件运行完成",
                        scripts_done=self._done_files,
                        scripts_total=self._total_files,
                        passed=passed,
                        skipped=skipped,
                        failed=failed,
                        errors=errors,
                        duration=duration,
                    )
                return

        def _poll_worker(self):
            if self.worker and not self.worker.is_alive() and self._timer is not None:
                self._timer.stop()

else:

    class _Signals:  # type: ignore
        pass

    class _CategoryCard:  # type: ignore
        pass

    class LauncherWindow:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 不可用")

def _pyqt6_available():
    return _PYQT6_AVAILABLE

def _load_test_icon():
    if not _PYQT6_AVAILABLE:
        return None
    for icon_path in (_PROJECT_ROOT / "test.ico", TEST_ICON_PATH, _TESTS_DIR / "test.ico"):
        if not icon_path.exists():
            continue
        try:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
        except Exception:
            continue
    return None

_APP_REF = []
_LAST_WIN = []

def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        _APP_REF.append(app)
    return app

def _build_gui():
    if not _PYQT6_AVAILABLE:
        raise RuntimeError("PyQt6 不可用")
    _ensure_qapp()
    window = LauncherWindow()
    _LAST_WIN.append(window)
    return window

def _embed_gui(parent=None):
    window = _build_gui()
    if parent is not None:
        try:
            geometry = parent.frameGeometry()
            window.move(max(0, geometry.x() + 50), max(0, geometry.y() + 50))
        except Exception:
            pass
    window.show()
    window.raise_()
    window.activateWindow()
    _embed_gui._window = window  # type: ignore[attr-defined]
    return 0

def _list_categories():
    print(f"{'ID':<16} {'名称':<14} {'文件':<6} {'分组':<10} 描述")
    print("-" * 100)
    for category in get_enabled_categories():
        print(
            f"{category.id:<16} {category.name:<14} {category.file_count():<6} "
            f"{category.section:<10} {category.description}"
        )

def _run_tui():
    import shutil

    bold, reset, cyan, green, yellow, dim = "\033[1m", "\033[0m", "\033[96m", "\033[92m", "\033[93m", "\033[2m"
    width = shutil.get_terminal_size((100, 24)).columns
    categories = get_enabled_categories()

    def clear():
        os.system("cls" if os.name == "nt" else "clear")

    while True:
        clear()
        print("=" * min(width, 88))
        print(f"{bold}UCrawl 测试套件 (TUI){reset}")
        print("=" * min(width, 88))
        for index, category in enumerate(categories, 1):
            marker = "★" if category.id == "all" else " "
            print(
                f"  {yellow}{index:>2}{reset}. {marker} {bold}{category.name}{reset}  "
                f"{dim}({category.file_count()} 脚本 · {category.section}){reset}"
            )
        print()
        print(f"  {yellow}a{reset}. 全部测试")
        print(f"  {yellow}r{reset}. 推荐组合")
        print(f"  {yellow}l{reset}. 列表")
        print(f"  {yellow}q{reset}. 退出")
        print()
        try:
            raw = input(f"{cyan}选择 (1-{len(categories)} / a / r / l / q): {reset}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            return 0

        if raw in {"q", "quit", "exit"}:
            return 0
        if raw == "l":
            print()
            _list_categories()
            input("\n回车继续...")
            continue
        if raw == "a":
            target_ids = ["all"]
        elif raw == "r":
            target_ids = list(RECOMMENDED_CATEGORY_IDS)
        else:
            try:
                target_ids = [categories[int(raw) - 1].id]
            except Exception:
                continue

        print(f"\n{green}▶ 运行: {', '.join(target_ids)}{reset}\n")
        results = run_categories(target_ids)
        print(format_summary(results))
        input("\n回车继续...")

def _run_cli(args):
    import argparse

    parser = argparse.ArgumentParser(description="UCrawl 测试套件")
    parser.add_argument("--category", "-c", choices=[category.id for category in get_enabled_categories()])
    parser.add_argument("--tui", action="store_true")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--list", "-l", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-failfast", action="store_true")
    parsed = parser.parse_args(args)

    if parsed.list:
        _list_categories()
        return 0
    if parsed.tui:
        return _run_tui()
    if parsed.gui:
        window = _build_gui()
        window.show()
        return (QApplication.instance() or QApplication(sys.argv)).exec()
    if parsed.category:
        results = run_categories(
            [parsed.category],
            verbose=parsed.verbose,
            no_failfast=parsed.no_failfast,
        )
        print(format_summary(results))
        return 0 if all(result.success for result in results) else 1

    if _pyqt6_available() and (os.environ.get("DISPLAY") or os.name == "nt"):
        try:
            window = _build_gui()
            window.show()
            return (QApplication.instance() or QApplication(sys.argv)).exec()
        except Exception as exc:
            print(f"[GUI 失败: {exc}]")
    return _run_tui()

def main():
    return _run_cli(sys.argv[1:])

if __name__ == "__main__":
    sys.exit(main())
