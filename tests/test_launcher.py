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
    from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
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
QFrame#statsCard,
QFrame#selectionSummary,
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
QFrame#statsCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE},
        stop:1 #0C1426);
}}
QFrame#selectionSummary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0E1B34,
        stop:1 #0B1428);
    border-radius: 16px;
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
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0F1930,
        stop:1 #0A1223);
    border-radius: 14px;
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
QLabel#summaryText,
QLabel#sectionMeta,
QLabel#categoryMetaLine,
QLabel#selectHint {{
    color: {TEXT_MUTED};
}}
QLabel#sectionLabel {{
    color: {TEXT};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QLabel#summaryEyebrow {{
    color: {ACCENT_MINT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#summaryValue {{
    font-size: 28px;
    font-weight: 800;
}}
QLabel#summaryText,
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
    background: #13233E;
    border: 1px solid #294168;
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
QLabel#statHint {{
    color: {TEXT_DIM};
    font-size: 11px;
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
    background: #08101E;
    border: 1px solid {BORDER};
    border-radius: 16px;
    padding: 12px;
    color: {TEXT};
    font-size: 12px;
    font-family: {MONO};
    selection-background-color: {ACCENT};
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

    class _SectionHeader(QFrame):
        def __init__(self, section_name: str, count: int):
            super().__init__()
            self.setObjectName("sectionHeader")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(10)

            title_col = QVBoxLayout()
            title_col.setSpacing(2)

            label = QLabel(section_name)
            label.setObjectName("sectionLabel")
            title_col.addWidget(label)

            meta = QLabel("按职责组织，可独立选择或组合运行")
            meta.setObjectName("sectionMeta")
            title_col.addWidget(meta)
            layout.addLayout(title_col, 1)

            pill = QLabel(f"{count} 项")
            pill.setObjectName("sectionCountPill")
            layout.addWidget(pill)
            layout.addStretch(1)

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
            self.resize(1220, 760)
            self.setMinimumSize(980, 640)
            self.setStyleSheet(QSS)

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

            self.signals = _Signals()
            self.signals.event.connect(self._on_event)

            self._build()
            self._refresh_selection_state()
            self._set_run_status("待命中", "default")

        def _build(self):
            root_widget = QWidget()
            self.setCentralWidget(root_widget)
            root = QVBoxLayout(root_widget)
            root.setContentsMargins(18, 18, 18, 12)
            root.setSpacing(14)

            hero = QFrame()
            hero.setObjectName("hero")
            hero_layout = QHBoxLayout(hero)
            hero_layout.setContentsMargins(20, 20, 20, 20)
            hero_layout.setSpacing(18)

            title_col = QVBoxLayout()
            title_col.setSpacing(6)
            hero_title = QLabel("测试套件仪表盘")
            hero_title.setObjectName("heroTitle")
            total_info = summary()
            recommended_count = len(RECOMMENDED_CATEGORY_IDS)
            hero_sub = QLabel(
                f"按职责浏览测试分类，选中后直接运行。当前已收录 {total_info['total_categories']} 个分类、"
                f"{total_info['total_files']} 个测试脚本，推荐组合覆盖 {recommended_count} 条高频回归链路。"
            )
            hero_sub.setObjectName("heroSub")
            hero_sub.setWordWrap(True)
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
            left_header_layout = QVBoxLayout(left_header)
            left_header_layout.setContentsMargins(0, 0, 0, 12)
            left_header_layout.setSpacing(4)
            left_title = QLabel("测试分类")
            left_title.setObjectName("panelTitle")
            left_sub = QLabel("按职责浏览并组合执行范围；卡片数量表示该分类直接包含的脚本数。")
            left_sub.setObjectName("panelSub")
            left_sub.setWordWrap(True)
            left_header_layout.addWidget(left_title)
            left_header_layout.addWidget(left_sub)
            left_layout.addWidget(left_header)

            selection_summary = QFrame()
            selection_summary.setObjectName("selectionSummary")
            selection_layout = QVBoxLayout(selection_summary)
            selection_layout.setContentsMargins(14, 14, 14, 14)
            selection_layout.setSpacing(4)
            summary_eyebrow = QLabel("执行范围")
            summary_eyebrow.setObjectName("summaryEyebrow")
            selection_layout.addWidget(summary_eyebrow)

            summary_row = QHBoxLayout()
            summary_row.setSpacing(8)
            self.left_selected_value = QLabel("0")
            self.left_selected_value.setObjectName("summaryValue")
            summary_row.addWidget(self.left_selected_value)
            self.left_selected_pill = QLabel("未选择")
            self.left_selected_pill.setObjectName("sectionPill")
            summary_row.addWidget(self.left_selected_pill, 0, Qt.AlignmentFlag.AlignBottom)
            summary_row.addStretch(1)
            selection_layout.addLayout(summary_row)

            self.left_selected_text = QLabel("从左侧分类中确定本次执行范围。")
            self.left_selected_text.setObjectName("summaryText")
            self.left_selected_text.setWordWrap(True)
            selection_layout.addWidget(self.left_selected_text)
            left_layout.addWidget(selection_summary)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll_body = QWidget()
            scroll_body.setObjectName("categoryViewport")
            scroll_layout = QVBoxLayout(scroll_body)
            scroll_layout.setContentsMargins(0, 0, 4, 0)
            scroll_layout.setSpacing(10)

            list_container = QWidget()
            list_container.setObjectName("categoryList")
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

            list_layout.addStretch(1)
            scroll_layout.addWidget(list_container)
            scroll_layout.addStretch(1)
            scroll.setWidget(scroll_body)
            left_layout.addWidget(scroll, 1)
            content_row.addWidget(left_panel)

            right_col = QVBoxLayout()
            right_col.setSpacing(14)
            content_row.addLayout(right_col, 1)

            self.detail_panel = QFrame()
            self.detail_panel.setObjectName("panel")
            detail_layout = QVBoxLayout(self.detail_panel)
            detail_layout.setContentsMargins(18, 18, 18, 18)
            detail_layout.setSpacing(10)

            detail_header = QFrame()
            detail_header.setObjectName("panelHeader")
            detail_header_layout = QVBoxLayout(detail_header)
            detail_header_layout.setContentsMargins(0, 0, 0, 12)
            detail_header_layout.setSpacing(6)
            self.detail_title = QLabel("执行范围")
            self.detail_title.setObjectName("heroTitle")
            self.detail_title.setStyleSheet("font-size: 20px; font-weight: 700;")
            detail_header_layout.addWidget(self.detail_title)

            self.detail_desc = QLabel("当前尚未选择测试分类，可使用全部、推荐或自定义组合。")
            self.detail_desc.setObjectName("heroSub")
            self.detail_desc.setWordWrap(True)
            detail_header_layout.addWidget(self.detail_desc)
            detail_layout.addWidget(detail_header)

            self.detail_tags = QLabel("")
            self.detail_tags.setObjectName("metaText")
            detail_layout.addWidget(self.detail_tags)
            right_col.addWidget(self.detail_panel)

            stats_row = QHBoxLayout()
            stats_row.setSpacing(12)
            self.stat_scope = self._make_stats_card(stats_row, "未选", "执行模式", "随选择切换")
            self.stat_files = self._make_stats_card(stats_row, "0", "去重脚本")
            self.stat_total = self._make_stats_card(stats_row, str(total_info["total_categories"]), "总分类数")
            self.stat_misc = self._make_stats_card(stats_row, str(len(get_resolved_files("misc"))), "未归类脚本")
            right_col.addLayout(stats_row)

            control_panel = QFrame()
            control_panel.setObjectName("panel")
            control_layout = QVBoxLayout(control_panel)
            control_layout.setContentsMargins(18, 18, 18, 18)
            control_layout.setSpacing(12)

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
            self.progress_percent = QLabel("0%")
            self.progress_percent.setObjectName("progressHint")
            progress_meta.addWidget(self.progress_detail)
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

            self.log = QTextEdit()
            self.log.setObjectName("log")
            self.log.setReadOnly(True)
            self.log.setPlaceholderText("运行日志会显示在这里。")
            right_col.addWidget(self.log, 1)

            self.sbar = QStatusBar()
            self.setStatusBar(self.sbar)

            QShortcut(QKeySequence("F5"), self, activated=self._run)
            QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self._select_only("all"))
            QShortcut(QKeySequence("Ctrl+R"), self, activated=self._select_recommended)
            QShortcut(QKeySequence("Escape"), self, activated=self._clear_selection)

        def _make_stats_card(self, parent_layout, value, label, hint: str = "实时更新"):
            card = QFrame()
            card.setObjectName("statsCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(4)

            value_label = QLabel(value)
            value_label.setObjectName("statValue")
            text_label = QLabel(label)
            text_label.setObjectName("statLabel")
            hint_label = QLabel(hint)
            hint_label.setObjectName("statHint")
            layout.addWidget(value_label)
            layout.addWidget(text_label)
            layout.addWidget(hint_label)
            parent_layout.addWidget(card, 1)
            return value_label

        def _set_run_status(self, text: str, tone: str):
            color_map = {
                "default": (TEXT_MUTED, "#0E1627", BORDER),
                "running": (TEXT, "#13233E", "#315896"),
                "success": (SUCCESS, "#0E1E16", "#1F6D43"),
                "danger": (DANGER, "#2A1115", "#7F1D1D"),
                "warning": (WARNING, "#2B1B07", "#8A5A12"),
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
                    "count": 0,
                    "mode": "未选",
                    "left_pill": "未选择",
                    "left_text": "从左侧分类中确定本次执行范围。",
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
                    "count": 1,
                    "mode": mode,
                    "left_pill": mode,
                    "left_text": f"已锁定 {category.name}，预计运行 {len(unique_files)} 个去重脚本。",
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
                "count": len(selected_categories),
                "mode": "组合",
                "left_pill": "组合",
                "left_text": f"已组合 {len(selected_categories)} 个分类，预计运行 {len(unique_files)} 个去重脚本。",
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
            self.stat_misc.setText(str(len(get_resolved_files("misc"))))
            self.left_selected_value.setText(str(snapshot["count"]))
            self.left_selected_pill.setText(snapshot["left_pill"])
            self.left_selected_text.setText(snapshot["left_text"])
            self.detail_desc.setText(snapshot["detail_desc"])
            self.detail_tags.setText(snapshot["detail_tags"])

            if not selected_categories:
                self.detail_title.setText("执行范围")
                self.current_hint.setText("待命中")
                self._set_run_status("待命中", "default")
                self.sbar.showMessage(snapshot["status"])
                return

            if len(selected_categories) == 1:
                self.detail_title.setText("执行范围")
            else:
                self.detail_title.setText("执行范围")

            self.sbar.showMessage(snapshot["status"])

        def _append_log(self, html: str):
            self.log.append(html)

        def _run(self):
            if self.worker and self.worker.is_alive():
                return
            if not self.selected_ids:
                self.sbar.showMessage("请先选择测试套件")
                return

            self.log.clear()
            self._done_files = 0
            self._total_files = max(len(self._selected_files()), 1)
            self.progress.setRange(0, self._total_files)
            self.progress.setValue(0)
            self._update_progress_labels()
            self.current_hint.setText("准备运行...")
            self._set_run_status("运行中", "running")
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
                self.sbar.showMessage("正在停止...")

        def _emit(self, kind, category_id, name, payload):
            self.signals.event.emit(kind, category_id, str(name), payload)

        def _on_event(self, kind, category_id, name, payload):
            if kind == "category_start":
                self._append_log(f"<span style='color:{ACCENT}; font-weight:700;'>▶ {name}</span>")
                self.current_hint.setText(f"运行中: {name}")
                self._set_run_status("运行中", "running")
                self.sbar.showMessage(f"运行中: {name}")
                return

            if kind == "file_start":
                path = Path(name).name
                meta = payload or {}
                self._append_log(
                    f"<span style='color:{TEXT_MUTED};'>· {meta.get('index', 0)}/{meta.get('total', 0)} {path}</span>"
                )
                return

            if kind == "file_done":
                if isinstance(payload, TestResult):
                    result = payload
                    color = SUCCESS if result.success else DANGER
                    icon = "PASS" if result.success else "FAIL"
                    self._append_log(
                        f"<span style='color:{color};'>{icon}</span> "
                        f"<span style='color:{TEXT_MUTED};'>P={result.passed} F={result.failed} "
                        f"S={result.skipped} E={result.errors} ({result.duration:.2f}s)</span>"
                    )
                    if result.failed_tests:
                        for failed_name in result.failed_tests[:3]:
                            self._append_log(f"<span style='color:{DANGER};'>  {failed_name}</span>")
                self._done_files += 1
                self.progress.setValue(min(self._done_files, self._total_files))
                self._update_progress_labels()
                return

            if kind == "category_done":
                if isinstance(payload, TestResult):
                    result = payload
                    color = SUCCESS if result.success else DANGER
                    status = "完成" if result.success else "失败"
                    self._append_log(
                        f"<span style='color:{color}; font-weight:700;'>■ {name} {status}</span>"
                        f"<span style='color:{TEXT_MUTED};'>  {result.passed} 通过 / {result.failed} 失败 / "
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

                self._append_log("<hr style='border:0;border-top:1px solid #22304D;'>")
                if failed == 0 and errors == 0:
                    self._set_run_status("全部通过", "success")
                    self._append_log(
                        f"<span style='color:{SUCCESS}; font-weight:700; font-size:14px;'>全部通过</span>"
                        f"<span style='color:{TEXT_MUTED};'>  {passed} 通过 / {skipped} 跳过 / {duration:.2f}s</span>"
                    )
                    self.sbar.showMessage(f"全部通过 · {passed} 通过 · {duration:.2f}s")
                else:
                    self._set_run_status("有失败", "danger")
                    self._append_log(
                        f"<span style='color:{DANGER}; font-weight:700; font-size:14px;'>运行结束，有失败</span>"
                        f"<span style='color:{TEXT_MUTED};'>  {passed} 通过 / {failed} 失败 / {errors} 错误 / {duration:.2f}s</span>"
                    )
                    self.sbar.showMessage(f"运行结束 · {failed} 失败 / {errors} 错误 · {duration:.2f}s")
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
