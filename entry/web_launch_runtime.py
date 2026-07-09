"""Web 入口启动期辅助逻辑。"""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
import time
import webbrowser
from typing import Any, Awaitable, Callable

def try_reuse_existing_instance(
    *,
    host: str,
    port: int,
    open_browser: bool,
    resolve_existing_url: Callable[[str, int], str | None],
    browser_opener: Callable[[str], Any] = webbrowser.open,
    stderr=None,
) -> bool:
    """检测并复用已运行的 Web 实例。

    启动入口先做端口复用判断，能避免用户双击多次后同时启动多个 Web
    服务和后台下载管理器。
    """
    stderr = stderr or sys.stderr
    existing_url = resolve_existing_url(host, port)
    if not existing_url:
        return False
    stderr.write(f"⚠️  检测到 UCrawl Web 已在运行，直接复用现有实例：{existing_url}\n")
    stderr.flush()
    if open_browser:
        browser_opener(existing_url)
    return True

def print_startup_banner(url: str, *, script: str | None = None, stderr=None) -> None:
    """输出 Web 启动横幅。"""
    stderr = stderr or sys.stderr
    stderr.write("\n  UCrawl Web UI\n")
    stderr.write(f"  {url}\n")
    stderr.write("  保存目录: downloads/\n")
    if script:
        stderr.write(f"  启动时注入脚本: {script}\n")
    stderr.write("\n")
    stderr.flush()

def start_browser_open_thread(
    url: str,
    *,
    delay: float = 1.5,
    browser_opener: Callable[[str], Any] = webbrowser.open,
) -> threading.Thread:
    """后台延迟打开浏览器，避免服务未就绪时抢跑。"""

    def _open_browser() -> None:
        time.sleep(delay)
        browser_opener(url)

    thread = threading.Thread(target=_open_browser, daemon=True)
    thread.start()
    return thread

def install_shutdown_signal_handlers(
    shutdown_event: threading.Event,
    *,
    signal_module=signal,
    stderr=None,
) -> Callable[[int, object], None]:
    """安装 SIGINT/SIGTERM 处理器，统一走 shutdown_event。

    Web 服务、Qt 托盘和浏览器打开线程都观察同一个事件，退出路径就不会
    因入口模式不同而遗漏清理。
    """
    stderr = stderr or sys.stderr

    def _signal_handler(signum, frame) -> None:
        stderr.write("\n  收到终止信号，正在关闭服务...\n")
        shutdown_event.set()

    signal_module.signal(signal_module.SIGINT, _signal_handler)
    signal_module.signal(signal_module.SIGTERM, _signal_handler)
    return _signal_handler

def run_server_with_qt(
    qt_app: Any,
    *,
    url: str,
    shutdown_event: threading.Event,
    serve_async: Callable[[], Awaitable[None]],
    create_tray_icon: Callable[[Any, str, threading.Event], Any],
    request_shutdown: Callable[[], None],
) -> None:
    """Qt 模式下：后台线程跑 Web，主线程跑 Qt 事件循环。

    Qt 要占主线程，FastAPI/uvicorn 只能放到后台线程；QTimer 轮询
    shutdown_event 是为了把信号处理安全切回 Qt 事件循环。
    """

    def _run_server() -> None:
        asyncio.run(serve_async())

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    tray = create_tray_icon(qt_app, url, shutdown_event)

    from PyQt6.QtCore import QTimer

    def _check_shutdown() -> None:
        if shutdown_event.is_set():
            timer.stop()
            request_shutdown()
            if tray:
                tray.hide()
            qt_app.quit()

    timer = QTimer()
    timer.timeout.connect(_check_shutdown)
    timer.start(100)
    qt_app.exec()
    server_thread.join(timeout=5)

def run_server_without_qt(*, serve_async: Callable[[], Awaitable[None]]) -> None:
    """无 Qt 模式下直接在主线程运行 asyncio。"""
    asyncio.run(serve_async())
