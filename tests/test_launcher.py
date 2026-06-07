"""统一测试启动器（GUI + TUI + CLI 三模自适应）。

设计 v7 — Linear/Spotify 现代深色风格：
- 更深的背景 + 更亮的卡片对比
- 大号标题 + 精致间距
- 选中态用亮色左边框 + 微妙背景变化
- 进度条有实际百分比文字
- 日志区用更深的背景形成层次
- 整体追求「精致工具感」而非「科技炫酷感」

关键修复：
- 不设 QT_QPA_PLATFORM=offscreen
- Qt 类模块级定义（class identity 稳定）
- QSS 只作用在窗口自身
"""

from __future__ import annotations

import os, sys, threading
from pathlib import Path
from typing import Optional

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path: sys.path.insert(0, str(_TESTS_DIR))
_PROJECT_ROOT = _TESTS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(_PROJECT_ROOT))

from test_registry import (TEST_REGISTRY, TEST_ICON_PATH, get_enabled_categories, get_resolved_files, get_category)
from test_runner import (TestResult, run_category, run_categories, format_summary)

try:
    from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
    from PyQt6.QtGui import QIcon, QFont, QColor, QShortcut, QKeySequence, QPixmap, QPainter
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QFrame, QScrollArea, QTextEdit, QProgressBar,
        QStatusBar, QCheckBox, QSizePolicy, QGraphicsDropShadowEffect
    )
    _PYQT6_AVAILABLE = True
except ImportError:
    _PYQT6_AVAILABLE = False
    Qt = None; pyqtSignal = None; QObject = object; QMainWindow = object; QFrame = object; QApplication = None


# ============== 设计令牌 — Linear/Spotify 现代深色 ==============

BG          = "#09090b"    # 极深背景
SURFACE     = "#18181b"    # 卡片/面板
SURFACE_HI  = "#27272a"    # 悬停/选中
BORDER      = "#3f3f46"    # 边框
BORDER_SEL  = "#a1a1aa"    # 选中边框

ACCENT      = "#3b82f6"    # 蓝色强调（Tailwind blue-500）
ACCENT_DIM  = "#1d4ed8"    # 深蓝
GREEN       = "#22c55e"    # 成功（green-500）
RED         = "#ef4444"    # 失败（red-500）
AMBER       = "#f59e0b"    # 警告（amber-500）

TEXT        = "#fafafa"    # 主文字
TEXT_SEC    = "#a1a1aa"    # 次要文字
TEXT_DIM    = "#71717a"    # 最暗文字

FONT_UI   = "'Inter','Segoe UI Variable','Microsoft YaHei UI',system-ui,sans-serif"
FONT_MONO = "'JetBrains Mono','Cascadia Code','Consolas',monospace"

# 类别标记色
_CAT_COLORS = {
    "all": ACCENT, "unit": GREEN, "integration": "#8b5cf6",
    "e2e": "#06b6d4", "ui": "#ec4899", "pipeline": "#14b8a6",
    "packaging": TEXT_DIM, "web_browser": "#6366f1",
    "core": TEXT_DIM, "test_entry": "#f97316",
}

# ============== QSS ==============

QSS = f"""
QMainWindow {{ background: {BG}; }}

QWidget {{ color: {TEXT}; font-family: {FONT_UI}; font-size: 13px; }}

/* ---- 卡片 ---- */
QFrame#tc {{
    background: {SURFACE}; border: 1px solid transparent; border-radius: 8px;
}}
QFrame#tc:hover {{
    background: {SURFACE_HI}; border-color: {BORDER};
}}
QFrame#tcSel {{
    background: {SURFACE_HI}; border-left: 3px solid {ACCENT}; border-top: 1px solid transparent;
    border-right: 1px solid transparent; border-bottom: 1px solid transparent; border-radius: 8px;
}}

QLabel#tcName {{ color: {TEXT}; font-size: 13px; font-weight: 600; background: transparent; border: none; }}
QLabel#tcDesc {{ color: {TEXT_DIM}; font-size: 11px; background: transparent; border: none; padding-top: 2px; }}
QLabel#tcIdx  {{ color: {TEXT_DIM}; font-size: 13px; font-weight: 500; background: transparent; border: none; }}

/* ---- 按钮 ---- */
QPushButton#runBtn {{
    background: {ACCENT}; border: none; border-radius: 6px;
    padding: 8px 24px; font-size: 13px; font-weight: 600; color: white;
}}
QPushButton#runBtn:hover {{ background: #2563eb; }}
QPushButton#runBtn:disabled {{ background: {SURFACE_HI}; color: {TEXT_DIM}; }}

QPushButton#stopBtn {{
    background: {RED}; border: none; border-radius: 6px;
    padding: 8px 24px; font-size: 13px; font-weight: 600; color: white;
}}
QPushButton#stopBtn:hover {{ background: #dc2626; }}

QPushButton#ghost {{
    background: transparent; color: {TEXT_SEC}; border: none;
    border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 500;
}}
QPushButton#ghost:hover {{ color: {TEXT}; background: {SURFACE_HI}; }}

/* ---- 日志 ---- */
QTextEdit#log {{
    background: #0c0c0e; color: {TEXT_SEC}; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: {FONT_MONO}; font-size: 11px; padding: 10px;
    selection-background-color: {ACCENT};
}}

/* ---- 进度条 ---- */
QProgressBar {{
    background: {SURFACE}; border: none; border-radius: 6px;
    text-align: center; font-size: 11px; color: {TEXT_SEC};
    min-height: 24px; max-height: 24px;
}}
QProgressBar::chunk {{
    background: {ACCENT}; border-radius: 5px;
}}

/* ---- 状态栏 ---- */
QStatusBar {{
    background: {SURFACE}; color: {TEXT_DIM}; border-top: 1px solid {BORDER};
    font-size: 11px; padding: 4px 12px;
}}

/* ---- 复选框 ---- */
QCheckBox {{ color: {TEXT_SEC}; font-size: 12px; spacing: 6px; background: transparent; border: none; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1.5px solid {BORDER}; background: {SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}

/* ---- 滚动条 ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


# ============== 后台线程 ==============

class TestRunnerWorker(threading.Thread):
    def __init__(self, category_ids, callback, no_failfast=True):
        super().__init__(daemon=True)
        self.category_ids = category_ids; self.callback = callback
        self.no_failfast = no_failfast; self.results = []; self._stop = False

    def run(self):
        for cid in self.category_ids:
            if self._stop: break
            cat = get_category(cid); files = get_resolved_files(cid)
            try: self.callback("cs", cid, cat.name, len(files))
            except Exception: pass
            for idx, f in enumerate(files):
                if self._stop: break
                try: self.callback("fs", cid, f, idx)
                except Exception: pass
                from test_runner import run_category as _rc
                res = _rc(category_id=cid, category_name=cat.name, files=[f], no_failfast=self.no_failfast)
                if self.results and self.results[-1].category_id == cid:
                    r = self.results[-1]; r.passed += res.passed; r.failed += res.failed
                    r.skipped += res.skipped; r.errors += res.errors; r.duration += res.duration
                    r.output += res.output; r.failed_tests.extend(res.failed_tests)
                else: self.results.append(res)
                try: self.callback("fd", cid, f, res)
                except Exception: pass
            try: self.callback("cd", cid, cat.name, None)
            except Exception: pass
        try: self.callback("ad", "", "", self.results)
        except Exception: pass

    def stop(self): self._stop = True


# ============== Qt 类（模块级） ==============

if _PYQT6_AVAILABLE:

    class _Signals(QObject):
        event = pyqtSignal(str, str, object, object)

    class _CatCard(QFrame):
        """类别卡片 — Linear 风格：左边框选中态 + 简洁排版。"""

        def __init__(self, cat, idx, on_click):
            super().__init__()
            self.cat = cat; self.on_click = on_click; self.selected = False
            self.setObjectName("tc")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFixedHeight(56)
            self._color = _CAT_COLORS.get(cat.id, ACCENT)

            lay = QHBoxLayout(self)
            lay.setContentsMargins(14, 0, 14, 0); lay.setSpacing(10)

            # 序号
            num = QLabel(str(idx)); num.setObjectName("tcIdx")
            num.setFixedWidth(20); num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(num)

            # 色点
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {self._color}; font-size: 8px; background: transparent; border: none;"
            )
            dot.setFixedWidth(10); dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(dot)

            # 文本
            col = QVBoxLayout(); col.setContentsMargins(0, 8, 0, 8); col.setSpacing(0)
            row = QHBoxLayout(); row.setSpacing(8)
            name = QLabel(cat.name); name.setObjectName("tcName"); row.addWidget(name)

            count = QLabel(f"{cat.file_count()}")
            count.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 11px; background: transparent; border: none;"
            )
            row.addWidget(count)

            row.addStretch(); col.addLayout(row)

            desc = QLabel(cat.description[:48] + ("…" if len(cat.description) > 48 else ""))
            desc.setObjectName("tcDesc"); col.addWidget(desc)
            lay.addLayout(col, 1)

            # 勾选指示
            self.chk = QLabel(); self.chk.setFixedSize(18, 18)
            self.chk.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._paint_chk(); lay.addWidget(self.chk)

        def _paint_chk(self):
            if self.selected:
                self.chk.setText("✓")
                self.chk.setStyleSheet(
                    f"color: white; font-size: 10px; font-weight: bold; "
                    f"background: {ACCENT}; border-radius: 4px; border: none;"
                )
            else:
                self.chk.setText("")
                self.chk.setStyleSheet(
                    f"background: transparent; border: 1.5px solid {BORDER}; border-radius: 4px;"
                )

        def mousePressEvent(self, ev):
            if ev.button() == Qt.MouseButton.LeftButton: self.on_click(self.cat)
            super().mousePressEvent(ev)

        def set_selected(self, on):
            self.selected = on
            self.setObjectName("tcSel" if on else "tc")
            self.style().unpolish(self); self.style().polish(self)
            self._paint_chk()

    class LauncherWindow(QMainWindow):
        """测试启动器 — Linear/Spotify 现代深色风格。"""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("UCrawl 测试套件")
            self.resize(780, 560); self.setMinimumSize(600, 400)
            self.setStyleSheet(QSS)

            icon = _load_test_icon()
            if icon: self.setWindowIcon(icon)
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ucrawl.test")
            except Exception: pass

            self.cards = {}; self.selected_ids = []; self.worker = None
            self.signals = _Signals(); self.signals.event.connect(self._on_event)
            self._total = 0; self._done = 0
            self._build()

        def _build(self):
            c = QWidget(); self.setCentralWidget(c)
            root = QVBoxLayout(c)
            root.setContentsMargins(20, 16, 20, 10); root.setSpacing(12)

            # ---- 头部 ----
            hdr = QHBoxLayout(); hdr.setSpacing(10)

            tcol = QVBoxLayout(); tcol.setSpacing(2)
            title = QLabel("测试套件")
            title.setStyleSheet(
                f"color: {TEXT}; font-size: 20px; font-weight: 700; "
                f"background: transparent; border: none; letter-spacing: -0.3px;"
            )
            sub = QLabel("选择类别 · 运行测试 · 查看结果")
            sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px; background: transparent; border: none;")
            tcol.addWidget(title); tcol.addWidget(sub)
            hdr.addLayout(tcol, 1)

            # 快捷按钮
            for text, tip, fn in [
                ("全选", None, lambda: self._sel_all(True)),
                ("清除", None, lambda: self._sel_all(False)),
                ("推荐", "unit + integration + e2e + pipeline", self._sel_rec),
            ]:
                b = QPushButton(text); b.setObjectName("ghost")
                if tip: b.setToolTip(tip)
                b.setFixedHeight(28); b.clicked.connect(fn); hdr.addWidget(b)
            root.addLayout(hdr)

            # ---- 分隔 ----
            sep = QFrame(); sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {BORDER}; border: none;")
            root.addWidget(sep)

            # ---- 卡片列表 ----
            sa = QScrollArea(); sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sw = QWidget(); sw.setStyleSheet("background: transparent;")
            sl = QVBoxLayout(sw); sl.setContentsMargins(0, 2, 0, 2); sl.setSpacing(4)
            for i, cat in enumerate(get_enabled_categories(), 1):
                card = _CatCard(cat, i, self._on_click)
                self.cards[cat.id] = card; sl.addWidget(card)
            sl.addStretch(); sa.setWidget(sw)
            root.addWidget(sa, 1)

            # ---- 底部 ----
            bot = QVBoxLayout(); bot.setSpacing(8)

            # 选项行
            opt_row = QHBoxLayout(); opt_row.setSpacing(16)
            self.chk_ff = QCheckBox("遇失败停止")
            self.chk_vb = QCheckBox("详细输出")
            opt_row.addWidget(self.chk_ff); opt_row.addWidget(self.chk_vb)
            opt_row.addStretch(); bot.addLayout(opt_row)

            # 日志
            self.log = QTextEdit(); self.log.setObjectName("log")
            self.log.setReadOnly(True); self.log.setFixedHeight(120)
            self.log.setPlaceholderText("等待运行…")
            bot.addWidget(self.log)

            # 进度 + 按钮
            prow = QHBoxLayout(); prow.setSpacing(10)
            self.pbar = QProgressBar(); self.pbar.setValue(0)
            prow.addWidget(self.pbar, 1)

            self.btn_run = QPushButton("运行测试"); self.btn_run.setObjectName("runBtn")
            self.btn_run.setFixedSize(110, 32); self.btn_run.clicked.connect(self._run)
            prow.addWidget(self.btn_run)

            self.btn_stop = QPushButton("停止"); self.btn_stop.setObjectName("stopBtn")
            self.btn_stop.setFixedSize(80, 32); self.btn_stop.clicked.connect(self._stop)
            self.btn_stop.hide(); prow.addWidget(self.btn_stop)

            bot.addLayout(prow)
            root.addLayout(bot)

            # 状态栏
            self.sbar = QStatusBar(); self.setStatusBar(self.sbar)
            self.sbar.showMessage("就绪")

            # 快捷键
            QShortcut(QKeySequence("F5"), self, activated=self._run)
            QShortcut(QKeySequence("Ctrl+A"), self, activated=lambda: self._sel_all(True))
            QShortcut(QKeySequence("Escape"), self, activated=lambda: self._sel_all(False))

        # ---- 交互 ----

        def _on_click(self, cat):
            if cat.id in self.selected_ids:
                self.selected_ids.remove(cat.id); self.cards[cat.id].set_selected(False)
            else:
                self.selected_ids.append(cat.id); self.cards[cat.id].set_selected(True)
            self._upd()

        def _sel_all(self, on):
            self.selected_ids.clear()
            for cid, card in self.cards.items():
                if cid == "all": continue
                if on: self.selected_ids.append(cid)
                card.set_selected(on and cid != "all")
            self._upd()

        def _sel_rec(self):
            self.selected_ids.clear()
            for cid, card in self.cards.items(): card.set_selected(False)
            for cid in ("unit", "integration", "e2e", "pipeline"):
                if cid in self.cards:
                    self.selected_ids.append(cid); self.cards[cid].set_selected(True)
            self._upd()

        def _upd(self):
            n = len(self.selected_ids)
            if n == 0: self.sbar.showMessage("就绪"); return
            nf = sum(get_category(c).file_count() for c in self.selected_ids)
            names = ", ".join(self.cards[c].cat.name for c in self.selected_ids)
            self.sbar.showMessage(f"{n} 类别 · {nf} 文件 — {names}")

        def _run(self):
            if self.worker and self.worker.is_alive(): return
            if not self.selected_ids: self.sbar.showMessage("请先选择测试类别"); return
            self.log.clear()
            self._total = sum(len(get_resolved_files(c)) for c in self.selected_ids)
            self._done = 0
            self.pbar.setMaximum(self._total or 1); self.pbar.setValue(0)
            self.btn_run.hide(); self.btn_stop.show()
            self.worker = TestRunnerWorker(self.selected_ids, self._emit, not self.chk_ff.isChecked())
            self.worker.start()
            self._timer = QTimer(self); self._timer.timeout.connect(self._poll); self._timer.start(150)

        def _stop(self):
            if self.worker and self.worker.is_alive(): self.worker.stop(); self.sbar.showMessage("正在停止…")

        def _emit(self, kind, cid, name, payload):
            self.signals.event.emit(kind, cid, str(name), payload)

        def _on_event(self, kind, cid, name, payload):
            if kind == "cs":
                self.log.append(f"<span style='color:{ACCENT};font-weight:600'>▶ {name}</span>")
                self.sbar.showMessage(f"运行: {name}")
            elif kind == "fs":
                short = Path(str(name)).name if ("/" in str(name) or "\\" in str(name)) else str(name)
                self.log.append(f"  <span style='color:{TEXT_DIM}'>· {short}</span>")
            elif kind == "fd":
                if isinstance(payload, TestResult):
                    r = payload
                    ic = "✓" if r.success else "✗"
                    co = GREEN if r.success else RED
                    self.log.append(
                        f"    <span style='color:{co}'>{ic} P={r.passed} F={r.failed} S={r.skipped} ({r.duration:.1f}s)</span>"
                    )
                    if r.failed > 0 and r.failed_tests:
                        for ft in r.failed_tests[:3]:
                            self.log.append(f"      <span style='color:{RED}'>{ft}</span>")
                self._done += 1
                pct = int(self._done / max(self._total, 1) * 100)
                self.pbar.setValue(self._done)
            elif kind == "cd":
                self.log.append(f"<span style='color:{TEXT_DIM}'>── {name} ──</span>")
            elif kind == "ad":
                results = payload
                self.btn_run.show(); self.btn_stop.hide()
                self.pbar.setValue(self.pbar.maximum())
                p = sum(r.passed for r in results); f = sum(r.failed for r in results)
                s = sum(r.skipped for r in results); d = sum(r.duration for r in results)
                self.log.append("")
                if f == 0:
                    self.log.append(
                        f"<span style='color:{GREEN};font-weight:700;font-size:14px'>全部通过 ✓</span>"
                        f"  <span style='color:{TEXT_DIM}'>{p} passed · {s} skipped · {d:.1f}s</span>"
                    )
                    self.sbar.showMessage(f"全部通过 · {p} tests · {d:.1f}s")
                else:
                    self.log.append(
                        f"<span style='color:{RED};font-weight:700;font-size:14px'>{f} 失败 ✗</span>"
                        f"  <span style='color:{TEXT_DIM}'>{p} passed · {s} skipped · {d:.1f}s</span>"
                    )
                    self.sbar.showMessage(f"{f} 失败 · {p} 通过 · {d:.1f}s")
                if hasattr(self, "_timer"): self._timer.stop()

        def _poll(self):
            if self.worker and not self.worker.is_alive(): self._timer.stop()

else:
    class _Signals: pass  # type: ignore
    class _CatCard: pass  # type: ignore
    class LauncherWindow:  # type: ignore
        def __init__(self, *a, **kw): raise RuntimeError("PyQt6 不可用")


# ============== 图标加载 ==============

def _pyqt6_available(): return _PYQT6_AVAILABLE

def _load_test_icon():
    """加载并优化 test.ico 图标（窗口图标 + 任务栏图标）。"""
    if not _PYQT6_AVAILABLE: return None

    # 搜索图标文件
    icon_paths = [
        _PROJECT_ROOT / "test.ico",       # 项目根目录（用户放置的位置）
        TEST_ICON_PATH,                     # tests/ 目录
        _TESTS_DIR / "test.ico",           # tests/ 目录备选
    ]

    for p in icon_paths:
        if p.exists():
            try:
                icon = QIcon(str(p))
                if icon.isNull():
                    continue

                # 确保图标包含常用尺寸（Windows 任务栏需要 32x32+）
                # QIcon 会自动从 ICO 文件中提取所有帧
                # 但如果 ICO 只有小尺寸，需要手动缩放补充
                sizes = icon.availableSizes()
                has_large = any(s.width() >= 32 for s in sizes)

                if not has_large and sizes:
                    # 从最大的帧缩放出 32x32 和 48x48
                    largest = max(sizes, key=lambda s: s.width() * s.height())
                    pm32 = icon.pixmap(largest).scaled(
                        32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    pm48 = icon.pixmap(largest).scaled(
                        48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    icon.addPixmap(pm32)
                    icon.addPixmap(pm48)

                return icon
            except Exception:
                continue
    return None


# ============== 工厂 ==============

_APP_REF = []; _LAST_WIN = []

def _ensure_qapp():
    app = QApplication.instance()
    if app is None: app = QApplication(sys.argv); _APP_REF.append(app)
    return app

def _build_gui():
    if not _PYQT6_AVAILABLE: raise RuntimeError("PyQt6 不可用")
    _ensure_qapp()
    w = LauncherWindow(); _LAST_WIN.append(w); return w

def _embed_gui(parent=None):
    w = _build_gui()
    if parent is not None:
        try:
            g = parent.frameGeometry()
            w.move(max(0, g.x() + 50), max(0, g.y() + 50))
        except Exception: pass
    w.show(); w.raise_(); w.activateWindow()
    _embed_gui._w = w  # type: ignore
    return 0


# ============== TUI ==============

def _run_tui():
    import shutil
    B, R, C, G, Y, D = "\033[1m", "\033[0m", "\033[96m", "\033[92m", "\033[93m", "\033[2m"
    cols = shutil.get_terminal_size((80, 20)).columns
    def clear(): os.system("cls" if os.name == "nt" else "clear")
    cats = get_enabled_categories()
    while True:
        clear()
        print("=" * min(cols, 70))
        print(f"{B}UCrawl 测试套件 (TUI){R}")
        print("=" * min(cols, 70))
        for i, c in enumerate(cats, 1):
            m = "★" if c.id == "all" else " "
            print(f"  {Y}{i}{R}. {m} {B}{c.name}{R}  {D}({c.file_count()} 文件){R}")
        print(f"  {Y}q{R}. 退出\n")
        try: ch = input(f"{C}选择 (1-{len(cats)}, q): {R}").strip()
        except (EOFError, KeyboardInterrupt): print("\n再见！"); return
        if ch == "q": return
        try:
            idx = int(ch) - 1
            if 0 <= idx < len(cats):
                sel = cats[idx]
                ids = [c.id for c in cats if c.id != "all"] if sel.id == "all" else [sel.id]
                print(f"\n{G}▶ {sel.name}{R}\n")
                print(format_summary(run_categories(ids)))
                input("\n回车继续…")
        except ValueError: pass


# ============== CLI ==============

def _list_cats():
    cats = get_enabled_categories()
    print(f"{'ID':<14} {'名称':<14} {'文件':<6} 描述")
    print("-" * 80)
    for c in cats: print(f"{c.id:<14} {c.name:<14} {c.file_count():<6} {c.description}")

def _run_cli(args):
    import argparse
    p = argparse.ArgumentParser(description="UCrawl 测试套件")
    p.add_argument("--category","-c", choices=[c.id for c in get_enabled_categories()])
    p.add_argument("--tui", action="store_true")
    p.add_argument("--list","-l", action="store_true")
    p.add_argument("--verbose","-v", action="store_true")
    p.add_argument("--no-failfast", action="store_true")
    p.add_argument("--gui", action="store_true")
    a = p.parse_args(args)
    if a.list: _list_cats(); return 0
    if not a.category and not a.tui and not a.gui:
        if _pyqt6_available() and (os.environ.get("DISPLAY") or os.name == "nt"):
            try:
                w = _build_gui(); w.show()
                return (QApplication.instance() or QApplication(sys.argv)).exec()
            except Exception as e: print(f"[GUI 失败: {e}]")
        return _run_tui() or 0
    if a.tui: return _run_tui() or 0
    if a.gui:
        w = _build_gui(); w.show()
        return (QApplication.instance() or QApplication(sys.argv)).exec()
    if a.category:
        r = run_categories([a.category], verbose=a.verbose, no_failfast=a.no_failfast)
        print(format_summary(r)); return 0 if all(x.success for x in r) else 1
    return 0

def main(): return _run_cli(sys.argv[1:])
if __name__ == "__main__": sys.exit(main())
