"""Web UI 入口：启动 Qt 运行时 + FastAPI 服务器。

用法:
    python web_main.py              # 默认 http://0.0.0.0:8000
    python web_main.py --port 9000  # 自定义端口
    python web_main.py --no-qt      # 无 Qt 模式（仅 API，不支持爬虫）
    python web_main.py --script my.py --script-arg name=alice  # 启动时注入脚本
"""

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


def _is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _resolve_port_with_dialog(default_port: int) -> int:
    """如果默认端口被占用，用 Qt 弹窗让用户输入新端口。"""
    from PyQt6.QtWidgets import QApplication, QInputDialog

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    port = default_port
    while True:
        if not _is_port_in_use("0.0.0.0", port):
            return port

        new_port, ok = QInputDialog.getInt(
            None,
            "端口已被占用",
            f"端口 {port} 已被其他程序占用，请输入新的端口号：",
            value=port + 1,
            min=1,
            max=65535,
            step=1,
        )
        if not ok:
            sys.exit(0)
        port = new_port


def _create_tray_icon(qt_app, url: str, shutdown_event: threading.Event):
    """创建系统托盘图标，提供打开浏览器和退出选项。"""
    from PyQt6.QtGui import QAction, QIcon
    from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        icon_path = Path(sys._MEIPASS).resolve() / "Web.ico"
    else:
        icon_path = Path(__file__).resolve().parent / "Web.ico"

    if icon_path.exists():
        icon = QIcon(str(icon_path))
    else:
        icon = qt_app.style().standardIcon(
            qt_app.style().StandardPixmap.SP_ComputerIcon
        )

    tray = QSystemTrayIcon(icon, qt_app)
    tray.setToolTip(f"CrawlerWebPortal - {url}")

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
        "CrawlerWebPortal 已启动",
        f"服务运行中: {url}\n右键托盘图标可打开或退出",
        QSystemTrayIcon.MessageIcon.Information,
        3000,
    )

    return tray


def main():
    parser = argparse.ArgumentParser(description="Universal Crawler Pro - Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认: 8000)")
    parser.add_argument("--no-qt", action="store_true", help="无 Qt 模式（仅 API，不支持爬虫）")

    parser.add_argument("--script", help="启动后自动调用的脚本 (路径)")
    parser.add_argument(
        "--script-arg",
        action="append",
        default=[],
        help="传递给脚本的 key=value 形式参数 (可多次)",
    )
    parser.add_argument("--script-strict", action="store_true", help="脚本失败时退出 web 服务")
    parser.add_argument("--script-delay", type=float, default=0.0, help="执行脚本前延迟秒数")

    args = parser.parse_args()

    qt_app = None
    tray = None
    shutdown_event = threading.Event()

    if not args.no_qt:
        from PyQt6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)

    if _is_port_in_use(args.host, args.port):
        if args.no_qt:
            print(f"错误: 端口 {args.port} 已被占用，请使用 --port 指定其他端口。", file=sys.stderr)
            sys.exit(1)
        args.port = _resolve_port_with_dialog(args.port)

    from app.web.server import create_app
    from app.web.script_api import parse_kv_args, inject_script_async

    @asynccontextmanager
    async def lifespan(app):
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
    print(f"\n  Universal Crawler Pro - Web UI")
    print(f"  {url}")
    print(f"  保存目录: downloads/")
    if args.script:
        print(f"  启动时注入脚本: {args.script}")
    print()

    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    def _signal_handler(signum, frame):
        print("\n  收到终止信号，正在关闭服务...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    )

    if qt_app:
        # Qt 模式：uvicorn 在后台线程运行，主线程进入 QApplication.exec()
        def _run_server():
            asyncio.run(server.serve())

        server_thread = threading.Thread(target=_run_server, daemon=True)
        server_thread.start()

        # 在主线程创建托盘图标（必须在 exec() 之前）
        tray = _create_tray_icon(qt_app, url, shutdown_event)

        # 使用 QTimer 轮询 shutdown_event，避免阻塞事件循环
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
        timer.start(100)  # 每 100ms 检查一次

        # 进入 Qt 主事件循环
        qt_app.exec()

        # 等待 uvicorn 线程结束
        server_thread.join(timeout=5)
    else:
        server.run()


if __name__ == "__main__":
    main()
