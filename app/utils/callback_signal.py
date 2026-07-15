"""为非 Qt 运行路径提供轻量回调信号。"""

from __future__ import annotations

import threading
import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from PyQt6.QtWidgets import QWidget
except Exception:  # pragma: no cover - 部分入口允许未安装 PyQt
    QWidget = None

class CallbackSignal:
    """提供近似 Qt API 的线程安全回调信号。"""

    SLOW_CALLBACK_SECONDS = 0.05

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., Any]] = []
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def connect(self, callback: Callable[..., Any], *_args: Any) -> Callable[..., Any]:
        """注册回调。

        忽略额外位置参数，使既有 `.connect(cb, Qt.ConnectionType...)` 调用在非 Qt
        信号上仍能复用同一绑定代码。
        """
        bound_self = getattr(callback, "__self__", None)
        if QWidget is not None and isinstance(bound_self, QWidget):
            raise TypeError("worker signals must not connect directly to QWidget methods; route through EventBus/bridge")
        with self._lock:
            self._callbacks.append(callback)
        return callback

    def disconnect(self, callback: Callable[..., Any] | None = None) -> None:
        """移除指定回调；未指定时清空全部订阅者。"""
        with self._lock:
            if callback is None:
                self._callbacks.clear()
                return
            self._callbacks = [registered for registered in self._callbacks if registered != callback]

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """调用当前已注册的全部回调。

        worker 信号必须隔离订阅者异常：单个观察者失败不能中断下载/采集线程，
        也不能阻止后续观察者收到同一事件。
        """
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            started = time.perf_counter()
            try:
                callback(*args, **kwargs)
            except Exception:  # pragma: no cover - 防御性日志分支
                self._logger.exception("CallbackSignal subscriber failed: %r", callback)
                continue
            elapsed = time.perf_counter() - started
            if elapsed >= self.SLOW_CALLBACK_SECONDS:
                self._logger.warning(
                    "CallbackSignal subscriber was slow: callback=%r elapsed_ms=%.2f",
                    callback,
                    elapsed * 1000,
                )
