"""Web 入口托盘 UI 组件。"""

from __future__ import annotations

import webbrowser
from typing import Any

from entry.qt_entry_utils import resolve_icon_path


def create_tray_icon(qt_app: Any, url: str, shutdown_event: Any):
    """创建系统托盘图标。"""
    from PyQt6.QtGui import QAction, QIcon
    from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

    icon_path = resolve_icon_path(["Web.ico"], fallback_names=["favicon.ico"])
    if icon_path and icon_path.exists():
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
