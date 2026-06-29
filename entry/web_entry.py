"""UCrawl Web UI 入口（薄适配层）。

行业对齐（PyPA 规范）：
- 在 `pyproject.toml` 的 `[project.scripts]` 中注册为 `ucrawl-web` 命令
- 启动 FastAPI + 可选 PyQt6 托盘
- 透传到 `app.web.server.create_app`

历史对应：原 `web_main.py` (227 行)

调用链：
    ucrawl-web (console_script) -> entry.web_entry:main() -> uvicorn + create_app
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- 端口处理 ----

# 顺延查找的最大尝试次数（找不到就报错/弹窗）
_PORT_PROBE_RANGE = 10

def _is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True

def _find_available_port(host: str, start_port: int, max_probe: int = _PORT_PROBE_RANGE) -> int | None:
    """从 start_port 开始顺延查找可用端口，最多尝试 max_probe 次。

    用于 --no-qt 模式（无法弹窗）下的优雅回退：
    用户期望"双击就开"时，被占用的端口不应该让它直接退出。

    Returns:
        可用端口号；若 max_probe 个端口都被占用则返回 None
    """
    for offset in range(max_probe + 1):
        port = start_port + offset
        if port > 65535:
            break
        if not _is_port_in_use(host, port):
            return port
    return None

def _load_app_icon() -> "QIcon | None":
    """加载 Web 应用图标（Web.ico），找不到就回退 favicon.ico。

    关键陷阱：**QIcon 必须在 QApplication 创建之后**才能正常构造，
    否则 PyQt6 在 Windows 上会 STATUS_STACK_BUFFER_OVERRUN 崩溃。
    查找顺序：
    1. 打包后的 _MEIPASS/Web.ico
    2. 仓库根目录的 Web.ico
    3. fallback：favicon.ico
    """
    from PyQt6.QtGui import QIcon

    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "Web.ico")
        candidates.append(Path(meipass) / "favicon.ico")
    candidates.append(Path(__file__).resolve().parent.parent / "Web.ico")
    candidates.append(Path(__file__).resolve().parent.parent / "favicon.ico")

    for path in candidates:
        try:
            if path.is_file():
                icon = QIcon(str(path))
                if not icon.isNull():
                    return icon
        except Exception:
            continue
    return None

def _ensure_app_user_model_id() -> None:
    """Windows 任务栏图标关键修复：设置 Web 模式专属 AppUserModelID。

    任务栏图标 = EXE 资源图标。开发模式下 python.exe 自带图标，
    设置 AppUserModelID 后 Windows 才会用 setWindowIcon 设的图标。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ucrawl.universalcrawlerpro.web"
        )
    except Exception:
        pass

def _resolve_port_with_dialog(default_port: int) -> int:
    """端口被占用时，弹自定义 Qt 弹窗让用户选新端口。

    现代化设计（v2 升级）：
    - 600x340 居中
    - 顶部 4px 蓝色装饰条
    - 64x64 圆形图标背景 + 大标题
    - 状态卡：左红/左绿边条 + 徽章（被占用 / 建议）
    - 大输入框 + focus 蓝色 ring
    - QGraphicsDropShadowEffect 阴影
    - 蓝色主按钮 / 灰色次按钮
    - 任务栏图标：app.setWindowIcon(icon) + dialog.setWindowIcon(icon)
    """
    from PyQt6.QtCore import QSize, Qt
    from PyQt6.QtGui import QFont, QIcon, QKeySequence, QShortcut
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QVBoxLayout,
    )

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    _ensure_app_user_model_id()

    # ---- 配色（与 dispatcher 弹窗统一）----
    ACCENT = "#3b82f6"          # 蓝（主品牌色）
    ACCENT_HOVER = "#2563eb"
    ACCENT_LIGHT = "#dbeafe"    # 淡蓝背景
    DANGER = "#ef4444"          # 红
    DANGER_LIGHT = "#fee2e2"    # 淡红背景
    SUCCESS = "#10b981"         # 绿
    SUCCESS_LIGHT = "#d1fae5"   # 淡绿背景
    TEXT_PRIMARY = "#111827"
    TEXT_SECONDARY = "#6b7280"
    BG_SOFT = "#f9fafb"         # 卡片底色

    port = default_port
    while True:
        if not _is_port_in_use("0.0.0.0", port):
            return port

        # ---- QDialog ----
        dlg = QDialog()
        dlg.setWindowTitle("端口已被占用 · UCrawl")
        dlg.setModal(True)
        dlg.setMinimumSize(QSize(600, 340))
        dlg.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if icon is not None:
            dlg.setWindowIcon(icon)
        # 阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setColor(Qt.GlobalColor.gray)
        shadow.setOffset(0, 4)
        dlg.setGraphicsEffect(shadow)

        dlg.setStyleSheet(f"""
            QDialog {{ background: #ffffff; }}
            QLabel#title {{
                color: {TEXT_PRIMARY};
                font-size: 20px;
                font-weight: 700;
                letter-spacing: 0.2px;
            }}
            QLabel#subtitle {{
                color: {TEXT_SECONDARY};
                font-size: 12px;
                margin-top: 2px;
            }}
            QLabel#labelText {{
                color: {TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#labelValue {{
                color: {TEXT_PRIMARY};
                font-size: 15px;
                font-weight: 700;
                font-family: 'Cascadia Code', 'Consolas', monospace;
            }}
            QLabel#badge {{
                color: white;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 10px;
                border-radius: 10px;
            }}
            QLabel#badgeDanger {{ background: {DANGER}; }}
            QLabel#badgeSuccess {{ background: {SUCCESS}; }}
            QFrame#statusCard {{
                background: {BG_SOFT};
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }}
            QLabel#statusStripeDanger {{
                background: {DANGER};
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }}
            QLabel#statusStripeSuccess {{
                background: {SUCCESS};
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }}
            QLabel#statusStripeWarn {{
                background: #f59e0b;
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }}
            QLabel#inputLabel {{
                color: {TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 600;
                margin-bottom: 6px;
            }}
            QLabel#hint {{
                color: {TEXT_SECONDARY};
                font-size: 11px;
                margin-top: 6px;
            }}
            QSpinBox {{
                padding: 10px 14px;
                border: 1.5px solid #d1d5db;
                border-radius: 10px;
                font-size: 15px;
                font-weight: 600;
                min-height: 28px;
                background: #ffffff;
                selection-background-color: {ACCENT_LIGHT};
            }}
            QSpinBox:hover {{
                border: 1.5px solid #9ca3af;
            }}
            QSpinBox:focus {{
                border: 2px solid {ACCENT};
                background: #f0f7ff;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 24px;
                border: none;
                background: transparent;
            }}
            QPushButton {{
                border-radius: 10px;
                padding: 9px 24px;
                font-size: 13px;
                font-weight: 600;
                min-width: 96px;
                min-height: 36px;
            }}
            QPushButton#okBtn {{
                background: {ACCENT};
                color: white;
                border: none;
            }}
            QPushButton#okBtn:hover {{
                background: {ACCENT_HOVER};
            }}
            QPushButton#okBtn:pressed {{
                background: #1d4ed8;
            }}
            QPushButton#cancelBtn {{
                background: transparent;
                color: {TEXT_SECONDARY};
                border: 1px solid #d1d5db;
            }}
            QPushButton#cancelBtn:hover {{
                background: #f3f4f6;
                color: #374151;
                border: 1px solid #9ca3af;
            }}
        """)

        # ---- 根布局 ----
        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部 4px 蓝色装饰条
        top_stripe = QFrame()
        top_stripe.setFixedHeight(4)
        top_stripe.setStyleSheet(f"background: {ACCENT}; border: none;")
        root.addWidget(top_stripe)

        # 主内容容器
        body = QVBoxLayout()
        body.setContentsMargins(32, 24, 32, 22)
        body.setSpacing(0)
        root.addLayout(body)

        # ---- Header：圆形图标 + 标题 ----
        header = QHBoxLayout()
        header.setSpacing(14)

        # 64x64 圆形图标背景（淡蓝）
        icon_circle = QFrame()
        icon_circle.setFixedSize(QSize(56, 56))
        icon_circle.setStyleSheet(f"""
            QFrame {{
                background: {ACCENT_LIGHT};
                border-radius: 28px;
                border: none;
            }}
        """)
        icon_layout = QVBoxLayout(icon_circle)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        if icon is not None:
            pixmap = icon.pixmap(QSize(36, 36))
            if not pixmap.isNull():
                il = QLabel()
                il.setPixmap(pixmap)
                il.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon_layout.addWidget(il)
        header.addWidget(icon_circle, 0, Qt.AlignmentFlag.AlignVCenter)

        # 标题 + 副标题
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("端口已被占用")
        title_label.setObjectName("title")
        title_box.addWidget(title_label)
        subtitle = QLabel("Web 服务需要切换到其他端口才能启动")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        body.addLayout(header)

        body.addSpacing(18)

        # ---- 状态卡（左红/左绿边条）----
        def make_status_card(stripe_obj: str, value: str, badge_text: str,
                             badge_color: str, label_text: str) -> QFrame:
            """构造状态卡。

            Args:
                stripe_obj: 左侧边条的 objectName（用于 QSS）
                value: 显示的端口号（或"—"表示无建议）
                badge_text: 徽章文字
                badge_color: 徽章背景色（hex）
                label_text: 标签文字
            """
            card = QFrame()
            card.setObjectName("statusCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)
            # 左侧 4px 边条
            stripe = QLabel()
            stripe.setObjectName(stripe_obj)
            stripe.setFixedSize(QSize(4, 48))
            card_layout.addWidget(stripe, 0, Qt.AlignmentFlag.AlignVCenter)
            # 文本
            text_box = QHBoxLayout()
            text_box.setContentsMargins(14, 10, 14, 10)
            text_box.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("labelText")
            text_box.addWidget(label)
            value_lbl = QLabel(value)
            value_lbl.setObjectName("labelValue")
            text_box.addWidget(value_lbl)
            text_box.addStretch(1)
            # 徽章（用 inline style 强制设置背景色，PyQt6 [class=...] 不可靠）
            badge = QLabel(badge_text)
            badge.setObjectName("badge")
            badge.setStyleSheet(f"""
                QLabel {{
                    background: {badge_color};
                    color: white;
                    font-size: 11px;
                    font-weight: 700;
                    padding: 3px 10px;
                    border-radius: 10px;
                }}
            """)
            text_box.addWidget(badge)
            text_wrap = QFrame()
            text_wrap.setLayout(text_box)
            text_wrap.setStyleSheet("background: transparent; border: none;")
            card_layout.addWidget(text_wrap, 1)
            return card

        # 请求端口（被占用）
        port_card = make_status_card(
            stripe_obj="statusStripeDanger",
            value=str(port),
            badge_text="✗  被占用",
            badge_color=DANGER,
            label_text="请求端口：",
        )
        body.addWidget(port_card)

        body.addSpacing(8)

        # ---- 建议端口：真实验证可用性（不是"面子工程"）----
        # 逐个尝试 bind，找到第一个可用的；找不到就明确告诉用户
        suggested: int | None = None
        attempted = 0
        for offset in range(1, _PORT_PROBE_RANGE + 1):
            cand = port + offset
            if cand > 65535:
                break
            attempted += 1
            if not _is_port_in_use("0.0.0.0", cand):
                suggested = cand
                break

        if suggested is not None:
            suggest_value = str(suggested)
            suggest_badge = f"✓  已验证可用 (尝试 {attempted} 个)"
            suggest_badge_color = SUCCESS
            suggest_stripe = "statusStripeSuccess"
            suggest_label = "建议端口："
        else:
            # 找不到可用端口 —— 不做"面子工程"，明确告诉用户
            suggest_value = "—"
            suggest_badge = "⚠  需手动指定"
            suggest_badge_color = "#f59e0b"  # 橙（警告色，非红非绿）
            suggest_stripe = "statusStripeWarn"
            suggest_label = "建议端口："
        suggest_card = make_status_card(
            stripe_obj=suggest_stripe,
            value=suggest_value,
            badge_text=suggest_badge,
            badge_color=suggest_badge_color,
            label_text=suggest_label,
        )
        body.addWidget(suggest_card)

        body.addSpacing(20)

        # ---- 输入区 ----
        input_label = QLabel("新端口号")
        input_label.setObjectName("inputLabel")
        body.addWidget(input_label)

        spin = QSpinBox()
        spin.setRange(1, 65535)
        # suggested 为 None 时 fallback 到 port+1（QSpinBox 不接受 None）
        spin.setValue(suggested if suggested is not None else port + 1)
        spin.setSingleStep(1)
        spin.selectAll()
        body.addWidget(spin)

        if suggested is not None:
            hint = QLabel(
                f"提示：建议端口 {suggested} 已验证可用。"
                f"如需更换，范围 1 - 65535，建议使用 1024 以上的端口"
            )
        else:
            hint = QLabel(
                f"提示：自动搜索 {_PORT_PROBE_RANGE} 个端口都不可用，"
                f"请手动指定一个端口（范围 1 - 65535）"
            )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        body.addWidget(hint)

        body.addStretch(1)

        # ---- 底部按钮 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bottom.addWidget(cancel_btn)

        ok_btn = QPushButton("使用此端口")
        ok_btn.setObjectName("okBtn")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setDefault(True)
        bottom.addWidget(ok_btn)
        body.addLayout(bottom)

        # ---- 居中显示 ----
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geo = screen.availableGeometry()
            dlg_geo = dlg.frameGeometry()
            x = (screen_geo.width() - dlg_geo.width()) // 2 + screen_geo.left()
            y = (screen_geo.height() - dlg_geo.height()) // 2 + screen_geo.top()
            dlg.move(max(0, x), max(0, y))

        # ---- 事件 ----
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), dlg, activated=dlg.reject)
        QShortcut(QKeySequence(Qt.Key.Key_Return), dlg, activated=dlg.accept)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        port = spin.value()

def _create_tray_icon(qt_app, url: str, shutdown_event: threading.Event):
    """创建系统托盘图标（Windows 上增强体验）。"""
    from PyQt6.QtGui import QAction, QIcon
    from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        icon_path = Path(sys._MEIPASS).resolve() / "Web.ico"
    else:
        icon_path = Path(__file__).resolve().parent.parent / "Web.ico"

    if icon_path.exists():
        icon = QIcon(str(icon_path))
    else:
        icon = qt_app.style().standardIcon(qt_app.style().StandardPixmap.SP_ComputerIcon)

    tray = QSystemTrayIcon(icon, qt_app)
    tray.setToolTip(f"UCrawl Web - {url}")

    menu = QMenu()
    open_action = QAction("打开浏览器", menu)
    open_action.triggered.connect(lambda: webbrowser.open(url))
    menu.addAction(open_action)
    menu.addSeparator()
    quit_action = QAction("退出", menu)
    quit_action.triggered.connect(lambda: shutdown_event.set())
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: webbrowser.open(url)
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick
        else None
    )
    tray.show()
    tray.showMessage(
        "UCrawl Web 已启动",
        f"服务运行中: {url}\n右键托盘图标可打开或退出",
        QSystemTrayIcon.MessageIcon.Information,
        3000,
    )
    return tray

def _build_argparser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="ucrawl-web",
        description="UCrawl Web UI - FastAPI + 浏览器",
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认: 8000)")
    parser.add_argument("--no-qt", action="store_true", help="无 Qt 模式（适合服务器 / 容器部署）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    # 启动时脚本注入参数
    parser.add_argument("--script", help="启动后自动调用的脚本 (路径)")
    parser.add_argument(
        "--script-arg",
        action="append",
        default=[],
        help="传递给脚本的 key=value 形式参数 (可多次)",
    )
    parser.add_argument("--script-strict", action="store_true", help="脚本失败时退出 web 服务")
    parser.add_argument("--script-delay", type=float, default=0.0, help="执行脚本前延迟秒数")
    return parser

def main(argv: list[str] | None = None) -> int:
    """Web UI 入口。"""
    parser = _build_argparser()
    args = parser.parse_args(argv)

    qt_app = None
    tray = None
    shutdown_event = threading.Event()

    if not args.no_qt:
        from PyQt6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)

    if _is_port_in_use(args.host, args.port):
        if args.no_qt:
            # 无 Qt 模式：自动顺延找可用端口（静默），找不到再报错
            # 修复：之前直接报错退出太粗暴，违反"双击就开"的预期
            new_port = _find_available_port(args.host, args.port)
            if new_port is None:
                sys.stderr.write(
                    f"错误: 端口 {args.port} 及后续 {_PORT_PROBE_RANGE} 个端口都被占用，\n"
                    f"      请使用 --port 指定其他端口后再启动。\n"
                )
                return 1
            sys.stderr.write(
                f"⚠️  端口 {args.port} 已被占用，自动改用端口 {new_port}\n"
            )
            args.port = new_port
        else:
            # 默认 / Qt 模式：弹 Qt 输入框让用户选（保持与源码一致）
            args.port = _resolve_port_with_dialog(args.port)

    from app.web.server import create_app
    from app.web.script_api import parse_kv_args, inject_script_async

    @asynccontextmanager
    async def lifespan(app):
        # 启动时执行注入脚本
        if args.script:
            from app.web.server import controller as web_controller
            script_kwargs = parse_kv_args(args.script_arg)
            inject_script_async(
                args.script,
                web_controller,
                strict=args.script_strict,
                delay=args.script_delay,
                **script_kwargs,
            )
        yield
        from app.web.server import controller
        if controller:
            controller.shutdown()

    app = create_app(lifespan=lifespan)

    url = f"http://localhost:{args.port}"
    sys.stderr.write("\n  UCrawl Web UI\n")
    sys.stderr.write(f"  {url}\n")
    sys.stderr.write(f"  保存目录: downloads/\n")
    if args.script:
        sys.stderr.write(f"  启动时注入脚本: {args.script}\n")
    sys.stderr.write("\n")
    sys.stderr.flush()

    if not args.no_browser:
        def _open_browser():
            import time
            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    def _signal_handler(signum, frame):
        sys.stderr.write("\n  收到终止信号，正在关闭服务...\n")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    import uvicorn
    server = uvicorn.Server(
        uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    )

    # 抑制 asyncio ProactorEventLoop 在 Windows 上的连接重置噪音
    # 根因：远程服务器关闭连接后，asyncio 回调中调用 socket.shutdown()，
    # 此时连接已关闭，抛出 ConnectionResetError(10054)。不影响功能，仅刷屏。
    # 参考：https://github.com/encode/uvicorn/issues/1580
    def _patch_proactor_exc_handler(loop: asyncio.AbstractEventLoop):
        orig_handler = loop.get_exception_handler()

        def _filtered_handler(loop_ctx, context):
            exc = context.get("exception")
            msg = context.get("message", "")
            if exc is not None:
                exc_msg = str(exc)
                if isinstance(exc, ConnectionResetError) and "10054" in exc_msg:
                    return  # 抑制 Windows ProactorEventLoop 的连接重置噪音
                if isinstance(exc, ConnectionResetError):
                    return
            if msg and "connection_lost" in str(msg).lower():
                return
            if orig_handler:
                orig_handler(loop_ctx, context)
            else:
                loop.default_exception_handler(context)

        loop.set_exception_handler(_filtered_handler)

    async def _serve_with_patch():
        loop = asyncio.get_running_loop()
        _patch_proactor_exc_handler(loop)
        await server.serve()

    if qt_app:
        # Qt 模式：uvicorn 在后台线程，主线程跑 QApplication.exec()
        def _run_server():
            asyncio.run(_serve_with_patch())

        server_thread = threading.Thread(target=_run_server, daemon=True)
        server_thread.start()

        tray = _create_tray_icon(qt_app, url, shutdown_event)

        from PyQt6.QtCore import QTimer

        def _check_shutdown():
            if shutdown_event.is_set():
                timer.stop()
                server.should_exit = True
                if tray:
                    tray.hide()
                qt_app.quit()

        timer = QTimer()
        timer.timeout.connect(_check_shutdown)
        timer.start(100)
        qt_app.exec()
        server_thread.join(timeout=5)
    else:
        # 无 Qt 模式：主线程直接跑 asyncio（同样应用连接重置异常抑制）
        asyncio.run(_serve_with_patch())

    return 0

if __name__ == "__main__":
    sys.exit(main())
