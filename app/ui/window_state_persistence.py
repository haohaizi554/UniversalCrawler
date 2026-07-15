"""在不阻塞 Qt 的前提下捕获、恢复并持久化主窗口状态。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import QByteArray

from app.debug_logger import debug_logger


@dataclass(frozen=True)
class UiStateSnapshot:
    geometry: bytes
    state: bytes
    main_splitter: bytes = b""
    right_splitter: bytes = b""
    is_fs: bool = False


def initialize_window_state_persistence(owner: Any) -> None:
    owner._ui_state_save_thread = None
    owner._ui_state_save_done = threading.Event()
    owner._ui_state_save_done.set()
    owner._ui_state_save_error = None


def capture_window_state(window: Any) -> UiStateSnapshot:
    """在窗口仍存活时复制 Qt QByteArray，后台线程只接触独立 bytes。"""
    return UiStateSnapshot(
        geometry=bytes(window.saveGeometry()),
        state=bytes(window.saveState()),
    )


def restore_window_state(window: Any, config: Any) -> None:
    """先恢复 Qt geometry 真值并约束到当前屏幕，再恢复窗口附加状态。

    屏幕拓扑或 DPI 变化后，历史 geometry 可能落到不可见区域，因此恢复成功也要校正。
    """
    geometry_hex = config.get("ui", "geometry")
    geometry_restored = False
    if geometry_hex:
        try:
            geometry_restored = bool(window.restoreGeometry(QByteArray.fromHex(geometry_hex.encode())))
        except (RuntimeError, ValueError) as exc:
            debug_logger.log_exception("MainWindow", "restore_geometry", exc)
    if geometry_restored:
        window._constrain_window_geometry_to_screen()
    else:
        window._apply_default_window_geometry()

    state_hex = config.get("ui", "window_state")
    if state_hex:
        window.restoreState(QByteArray.fromHex(state_hex.encode()))


def start_window_state_persistence(
    owner: Any,
    snapshot: UiStateSnapshot,
    save_ui_state: Callable[..., None],
) -> None:
    """在受跟踪的非 `daemon` 线程中持久化脱离 Qt 对象的状态快照。"""
    done = threading.Event()
    owner._ui_state_save_done = done
    owner._ui_state_save_error = None

    def persist() -> None:
        try:
            save_ui_state(
                geometry=snapshot.geometry,
                state=snapshot.state,
                main_splitter=snapshot.main_splitter,
                right_splitter=snapshot.right_splitter,
                is_fs=snapshot.is_fs,
            )
        except Exception as exc:
            owner._ui_state_save_error = exc
            debug_logger.log_exception("MainWindow", "persist_ui_state", exc)
        finally:
            done.set()

    worker = threading.Thread(target=persist, name="ui-state-save-worker", daemon=False)
    owner._ui_state_save_thread = worker
    try:
        worker.start()
    except Exception as exc:
        owner._ui_state_save_error = exc
        done.set()
        debug_logger.log_exception("MainWindow", "persist_ui_state", exc)
