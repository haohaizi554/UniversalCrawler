"""WebController：桥接 Qt 信号到 WebSocket，复用现有 Spider/DownloadManager 逻辑。"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

from app.config import cfg
from app.core.download_manager import DownloadManager
from app.core.plugin_registry import registry
from app.debug_logger import debug_logger
from app.exceptions import DebugActionError, FileOperationError, MediaScanError
from app.models import VideoItem
from app.services.file_service import MediaLibraryService

# 检测 Qt 是否可用且 QApplication 是否存在
_QT_AVAILABLE = False
try:
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    _QT_AVAILABLE = QApplication.instance() is not None
except ImportError:
    QObject = object
    pyqtSignal = None


if _QT_AVAILABLE:
    class WebSocketBridge(QObject):
        """Qt 模式：桥接 Qt 信号到 asyncio 事件循环。

        两种调度路径：
        1. emit() → 直接调度到 asyncio 事件循环（最快路径，不经过 Qt 信号）
        2. call_in_main_thread() → 通过 Qt 信号调度到 Qt 主线程（仅用于 spider 创建/停止）
        """

        sig_call_in_main_thread = pyqtSignal(object)

        def __init__(self, loop: asyncio.AbstractEventLoop, send_func: Callable):
            super().__init__()
            self._loop = loop
            self._send_func = send_func
            self.sig_call_in_main_thread.connect(self._on_call_in_main_thread)

        def _on_call_in_main_thread(self, callback):
            """在 Qt 主线程中执行回调（由 sig_call_in_main_thread 触发）。"""
            try:
                callback()
            except Exception as exc:
                import logging
                logging.error(f"WebSocketBridge._on_call_in_main_thread: 回调执行失败: {exc}", exc_info=True)

        def call_in_main_thread(self, callback: Callable):
            """从任意线程安全地将回调调度到 Qt 主线程执行。

            修复 BUG: QTimer.singleShot 从非 Qt 线程调用时回调不会被执行，
            因为 QTimer 的事件循环亲和性——它只在调用线程的 Qt 事件循环中触发。
            而 uvicorn 线程运行 asyncio 事件循环，不是 Qt 事件循环。

            使用 pyqtSignal 的跨线程机制（AutoConnection → QueuedConnection）
            替代 QTimer.singleShot，确保回调在 Qt 主线程中执行。
            """
            self.sig_call_in_main_thread.emit(callback)

        def emit(self, event_type: str, data: Any = None):
            """从任意线程安全地广播事件。直接调度到 asyncio 事件循环，不经过 Qt 信号。

            性能优化：之前的实现通过 sig_broadcast → Qt 主线程 → asyncio.run_coroutine_threadsafe，
            每次广播需要 3 次线程跳转（spider线程 → Qt主线程 → uvicorn线程）。
            现在直接调度到 asyncio 事件循环，只有 1 次线程跳转（spider线程 → uvicorn线程），
            通信延迟大幅降低。
            """
            loop = self._loop
            if loop is None or loop.is_closed():
                return
            coro = self._send_func(event_type, data)
            if not asyncio.iscoroutine(coro):
                return
            # 最快路径：当前就在目标事件循环中
            try:
                current_loop = asyncio.get_running_loop()
                if current_loop is loop:
                    current_loop.create_task(coro)
                    return
            except RuntimeError:
                pass
            # 跨线程调度：直接到 uvicorn 事件循环
            asyncio.run_coroutine_threadsafe(coro, loop)
else:
    class WebSocketBridge:
        """无 Qt 模式：直接调度到 asyncio 事件循环，不依赖 pyqtSignal。"""

        def __init__(self, loop: asyncio.AbstractEventLoop | None, send_func: Callable):
            self._loop = loop
            self._send_func = send_func

        def _get_loop(self) -> asyncio.AbstractEventLoop:
            """获取事件循环，延迟获取以确保是 uvicorn 运行时的事件循环。
            修复 BUG-152: 必须兼容跨线程调用（spider 在子线程中 emit）。
            """
            if self._loop is None or self._loop.is_closed():
                # 尝试在当前线程中获取
                try:
                    self._loop = asyncio.get_running_loop()
                except RuntimeError:
                    # 不在事件循环线程，尝试从主线程获取
                    try:
                        self._loop = asyncio.get_event_loop_policy().get_event_loop()
                    except RuntimeError:
                        self._loop = asyncio.new_event_loop()
            return self._loop

        def set_loop(self, loop: asyncio.AbstractEventLoop):
            """显式设置事件循环（在 WebSocket 连接时由主线程调用）。"""
            self._loop = loop

        def emit(self, event_type: str, data: Any = None):
            """从任意线程安全地广播事件。

            修复 BUG-159: 不管 emit 从哪个线程调用，都用统一的"调度到目标 loop"策略：
            - 当前线程在事件循环中：用 loop.call_soon 调度同步执行 send_func
            - 当前线程不在事件循环中：用 run_coroutine_threadsafe 跨线程调度

            注意: send_func 必须在目标 loop 线程中执行（因为它会 await WebSocket）
            """
            # 优先: 在当前事件循环线程中调度（避免跨线程）
            try:
                current_loop = asyncio.get_running_loop()
                # 当前就在事件循环中，用 call_soon 把 broadcast 排入下次迭代
                # 不在 HTTP 协程中 await，让 HTTP 立即返回
                def _schedule():
                    coro = self._send_func(event_type, data)
                    if asyncio.iscoroutine(coro):
                        current_loop.create_task(coro)
                current_loop.call_soon(_schedule)
                return
            except RuntimeError:
                # 当前线程不在事件循环中 (如 spider 线程)
                pass

            # fallback: 跨线程调度
            target_loop = self._get_loop()
            if target_loop and target_loop.is_running():
                coro = self._send_func(event_type, data)
                if asyncio.iscoroutine(coro):
                    asyncio.run_coroutine_threadsafe(coro, target_loop)
            else:
                import logging
                logging.warning(f"WebSocketBridge: 事件循环未运行，丢弃事件 {event_type}")


class WebController:
    """Web 端核心控制器，逻辑与 ApplicationController 对称，但输出到 WebSocket。"""

    VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts")
    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    def __init__(self, loop: asyncio.AbstractEventLoop, send_func: Callable):
        self._loop = loop
        self._send_func = send_func
        self.bridge = WebSocketBridge(loop, send_func)

        self.file_service = MediaLibraryService(self.VIDEO_EXTENSIONS, self.IMAGE_EXTENSIONS)
        self.dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))

        self.videos: dict[str, VideoItem] = {}
        self.current_spider = None
        self.current_save_dir: str = cfg.get("common", "save_directory", "downloads")
        self._pending_selection_strategy = None  # 由 /api/crawl/start 设置，供 _bind_spider_signals 使用

        self._connect_download_signals()

    def _connect_download_signals(self):
        self.dl_manager.task_started.connect(self._on_task_started)
        self.dl_manager.task_progress.connect(self._on_task_progress)
        self.dl_manager.task_finished.connect(self._on_task_finished)
        self.dl_manager.task_error.connect(self._on_task_error)

    # ---- 下载信号处理 ----

    def _on_task_started(self, video_id: str):
        item = self._apply_video_state(video_id, status="⏳ 下载中...", progress=0)
        # 与 CLI CLIRunner._on_task_finished 对齐：local_path 使用 or "" 防御 None
        local_path = (item.local_path or "") if item else ""
        # 与 task_finished 事件对齐：task_started 也包含 title/content_type，
        # 让 WebSocket 客户端在下载开始时即可显示完整信息
        title = item.title if item else ""
        content_type = (item.meta.get("content_type", "") if item.meta else "") if item else ""
        self.bridge.emit("task_started", {
            "video_id": video_id,
            "local_path": local_path,
            "title": title,
            "content_type": content_type,
        })

    def _on_task_progress(self, video_id: str, progress: int):
        self._apply_video_state(video_id, progress=progress)
        self.bridge.emit("task_progress", {"video_id": video_id, "progress": progress})

    def _on_task_finished(self, video_id: str):
        item = self._apply_video_state(video_id, status="✅ 完成", progress=100)
        # 与 CLI CLIRunner._on_task_finished 对齐：local_path 使用 or "" 防御 None
        local_path = (item.local_path or "") if item else ""
        # 与 REST API/WebSocket download 对齐：task_finished 包含完整信息
        # （content_type 和 title 让 WebSocket 客户端无需额外请求即可获取完整下载结果）
        content_type = ""
        title = ""
        if item:
            content_type = item.meta.get("content_type", "") if item.meta else ""
            title = item.title
        self.bridge.emit("task_finished", {
            "video_id": video_id,
            "local_path": local_path,
            "content_type": content_type,
            "title": title,
        })
        if item:
            self.bridge.emit("log", {"message": f"✅ 下载完成: {item.title}"})
            # 与 GUI _on_download_finished 对齐：记录下载完成日志（含 context 和 trace_id）
            debug_logger.log(
                component="WebController",
                action="download_finished",
                message="Web 端下载任务完成",
                status_code="WEB_DL_FINISH",
                context=self._item_context(item),
                details={"video_id": video_id, "title": item.title, "local_path": local_path},
                trace_id=self._item_trace_id(item),
            )

    def _on_task_error(self, video_id: str, error: str):
        # 与 REST API /api/download 错误路径对齐：失败时 progress=0
        item = self._apply_video_state(video_id, status="❌ 失败", progress=0)
        # 与 CLI CLIRunner._on_task_error 对齐：存储错误原因到 meta
        if item:
            item.meta["download_error"] = error
        # 与 task_finished 事件对齐：task_error 也包含 local_path/content_type/title，
        # 让 WebSocket 客户端无需额外请求即可获取完整错误信息
        local_path = (item.local_path or "") if item else ""
        content_type = (item.meta.get("content_type", "") if item.meta else "") if item else ""
        title = item.title if item else ""
        self.bridge.emit("task_error", {
            "video_id": video_id,
            "error": error,
            "local_path": local_path,
            "content_type": content_type,
            "title": title,
        })
        if item:
            self.bridge.emit("log", {"message": f"❌ 下载失败 [{item.title}]: {error}"})
            # 与 GUI _on_download_error 对齐：记录下载失败日志（含 context 和 trace_id）
            debug_logger.log(
                component="WebController",
                action="download_error",
                level="ERROR",
                message="Web 端下载任务失败",
                status_code="WEB_DL_ERROR",
                context=self._item_context(item),
                details={"video_id": video_id, "title": item.title, "error": error},
                trace_id=self._item_trace_id(item),
            )

    def _apply_video_state(self, vid: str, *, status: str | None = None, progress: int | None = None) -> VideoItem | None:
        item = self.videos.get(vid)
        if not item:
            return None
        if status is not None:
            item.status = status
        if progress is not None:
            item.progress = progress
        # 与 REST API/WebSocket download 对齐：video_state_changed 包含完整信息
        # （完成/失败状态时增补 local_path 和 content_type，让 WebSocket 客户端可更新本地缓存）
        event_data = {
            "video_id": vid,
            "status": item.status,
            "progress": item.progress if progress is not None else None,
        }
        if status in ("✅ 完成", "❌ 失败", "❌ 超时"):
            event_data["local_path"] = item.local_path or ""
            event_data["content_type"] = (item.meta.get("content_type", "") if item.meta else "")
        self.bridge.emit("video_state_changed", event_data)
        return item

    # ---- 爬虫控制 ----

    def _cleanup_dead_spider(self):
        """清理已退出但未被 _on_spider_finished 处理的 spider。

        场景：spider 因 Playwright 崩溃等异常退出，sig_finished 未被 emit，
        导致 current_spider 残留、isRunning() 返回 False 但引用未清空。
        """
        if self.current_spider and not self.current_spider.isRunning():
            self.bridge.emit("log", {"message": "⚠️ 上次任务未正常结束，正在清理..."})
            self.current_spider = None
            self._pending_selection_strategy = None
            self.bridge.emit("crawl_state", {"is_running": False})

    def start_crawl(self, source_id: str, keyword: str, config: dict):
        # 清理已退出但残留的 spider 引用
        self._cleanup_dead_spider()

        if self.current_spider and self.current_spider.isRunning():
            self.bridge.emit("log", {"message": "⚠️ 当前已有任务在运行，请先停止或等待结束"})
            # 与 GUI 一致：启动失败时恢复 UI 状态
            self.bridge.emit("crawl_state", {"is_running": False})
            # 清理预置的选择策略，避免跨请求污染
            self._pending_selection_strategy = None
            return

        plugin = registry.get_plugin(source_id)
        if not plugin:
            self.bridge.emit("log", {"message": "❌ 未知的爬虫源"})
            self.bridge.emit("crawl_state", {"is_running": False})
            # 清理预置的选择策略，避免跨请求污染
            self._pending_selection_strategy = None
            return

        # 关键修复：将 spider 创建、信号绑定和启动调度到 Qt 主线程
        # 原因：spider 是 QThread，其信号回调需要在 Qt 主线程中处理
        # 如果在 uvicorn 线程中创建 spider 并连接信号，Qt 的 AutoConnection
        # 会将回调 marshal 到 uvicorn 线程，但 uvicorn 不运行 Qt 事件循环，
        # 导致回调永远不会被执行 → 日志丢失、二次选择死锁、停止无响应
        #
        # 修复 BUG: QTimer.singleShot 从非 Qt 线程调用时回调不会被执行，
        # 因为 QTimer 的事件循环亲和性——它只在调用线程的 Qt 事件循环中触发。
        # 而 uvicorn 线程运行 asyncio 事件循环，不是 Qt 事件循环。
        # 使用 bridge.call_in_main_thread（基于 pyqtSignal 的跨线程机制）替代。
        if _QT_AVAILABLE:
            self.bridge.call_in_main_thread(lambda: self._do_start_crawl(plugin, source_id, keyword, config))
        else:
            # 无 Qt 模式：直接在当前线程执行
            self._do_start_crawl(plugin, source_id, keyword, config)

    def _do_start_crawl(self, plugin, source_id: str, keyword: str, config: dict):
        """在 Qt 主线程中创建和启动 spider（与 GUI on_start_crawl 对齐）。"""
        try:
            spider_cls = plugin.get_spider_class()
            spider = spider_cls(keyword=keyword, config=config)
        except Exception as exc:
            self.bridge.emit("log", {"message": f"❌ 创建爬虫失败: {exc}"})
            self.bridge.emit("crawl_state", {"is_running": False})
            self._pending_selection_strategy = None
            return

        self.bridge.emit("log", {"message": f"🟢 启动任务 | 模式: {plugin.name} | 关键词: {keyword}"})
        self.bridge.emit("crawl_state", {"is_running": True, "source": source_id})

        # 与 GUI _log_crawl_start 对齐：记录爬虫启动日志
        debug_logger.log(
            component="WebController",
            action="start_crawl",
            message="Web 端启动爬虫任务",
            status_code="WEB_CRAWL_START",
            details={
                "keyword": keyword,
                "source_id": source_id,
                "plugin_name": plugin.name,
                "active_config": {k: v for k, v in config.items() if v not in (None, "", [], {})},
            },
        )

        self.current_spider = spider
        self._bind_spider_signals(spider)
        spider.start()

    def _bind_spider_signals(self, spider):
        # 如果有预置的 selection 策略，monkey-patch ask_user_selection（与 CLI CLIRunner 对齐）
        if self._pending_selection_strategy is not None:
            from types import MethodType
            strategy = self._pending_selection_strategy
            self._pending_selection_strategy = None  # 用完即清
            call_count = [0]

            def ask_user_selection_sync(spider_self, items):
                """同步版 ask_user_selection：直接调 selection_strategy，不走 Qt 信号。
                与 CLI CLIRunner._make_ask_user_selection 完全对齐。"""
                call_count[0] += 1
                try:
                    indices = strategy.select(items, prompt=f"二次选择 #{call_count[0]}: {len(items)} 个候选")
                except Exception:
                    indices = list(range(len(items)))
                if indices is None:
                    indices = []
                return indices

            spider.ask_user_selection = MethodType(ask_user_selection_sync, spider)

        # 信号连接：由于 _do_start_crawl 在 Qt 主线程中执行，
        # AutoConnection 会自动将 spider 线程的回调 marshal 到 Qt 主线程
        # （与 GUI _bind_spider_signals 完全一致）
        spider.sig_log.connect(lambda msg: self.bridge.emit("log", {"message": msg}))
        spider.sig_item_found.connect(self._on_spider_item_found)
        spider.sig_select_tasks.connect(self._on_spider_select_tasks)
        spider.sig_finished.connect(self._on_spider_finished)

    def _on_spider_item_found(self, item: VideoItem):
        item.status = "⏳ 等待中"
        item.progress = 0
        self.videos[item.id] = item
        self.bridge.emit("item_found", self._video_item_to_dict(item))
        self.dl_manager.add_task(item, self.current_save_dir)
        # 与 GUI _on_spider_item_found 对齐：记录 item 发现日志（含 context 和 trace_id）
        debug_logger.log(
            component="WebController",
            action="item_found",
            message="Web 端发现可下载资源",
            status_code="WEB_ITEM_FOUND",
            context=self._item_context(item),
            details={"video_id": item.id, "title": item.title, "source": item.source},
            trace_id=self._item_trace_id(item),
        )

    def _on_spider_select_tasks(self, items: list):
        """二次选择回调：将候选列表推送给前端。

        与 GUI SelectionDialog 对齐：序列化完整信息，不只是 title/index。
        VideoItem 对象使用 to_dict() 序列化，dict 对象提取关键字段。
        """
        serialized = []
        for i, it in enumerate(items):
            if isinstance(it, VideoItem):
                # 与 GUI 一致：使用 to_dict() 完整序列化
                serialized.append(it.to_dict())
            elif isinstance(it, dict):
                # 兼容 dict 格式：提取关键字段，补全 index
                entry = {"index": it.get("index", i)}
                for key in ("id", "title", "url", "source", "status", "progress",
                            "local_path", "content_type", "meta"):
                    if key in it:
                        entry[key] = it[key]
                if "title" not in entry:
                    entry["title"] = ""
                serialized.append(entry)
            elif hasattr(it, "title"):
                # 其他有 title 属性的对象
                serialized.append({
                    "index": i,
                    "title": getattr(it, "title", ""),
                    "url": getattr(it, "url", ""),
                    "source": getattr(it, "source", ""),
                })
            else:
                serialized.append({"title": str(it), "index": i})
        self.bridge.emit("select_tasks", {"items": serialized})

    def _on_spider_finished(self):
        import threading
        debug_logger.log(
            component="WebController",
            action="_on_spider_finished_enter",
            message="_on_spider_finished 被调用",
            status_code="WEB_SPIDER_FINISH_ENTER",
            details={
                "thread": threading.current_thread().name,
                "has_spider": self.current_spider is not None,
                "spider_running": self.current_spider.isRunning() if self.current_spider else None,
            },
        )
        self.bridge.emit("log", {"message": "✅ 爬虫任务结束"})
        self.bridge.emit("crawl_state", {"is_running": False})
        # 与 GUI _on_spider_finished 对齐：记录完成日志
        debug_logger.log(
            component="WebController",
            action="crawl_finished",
            message="Web 端爬虫任务结束",
            status_code="WEB_CRAWL_FINISH",
        )
        self.current_spider = None
        # 防御性清理：确保 _pending_selection_strategy 不残留
        # （正常流程中 _bind_spider_signals 已消费，但 spider 异常退出时可能未消费）
        self._pending_selection_strategy = None

    def stop_crawl(self):
        if not self.current_spider:
            return
        # 防抖：如果已经在停止等待中，忽略重复请求
        if getattr(self, '_stop_wait_spider', None) is not None:
            return
        # 关键修复：将 stop 操作调度到 Qt 主线程
        # 原因：spider.stop() 设置 is_running=False，但 spider 可能正在
        # ask_user_selection 中等待 _resume_event。stop() 会 _resume_event.set()，
        # 但如果 Qt 事件循环被阻塞（如在 uvicorn 线程中调用 spider.wait()），
        # 信号无法被处理，形成死锁。
        # 修复 BUG: 使用 bridge.call_in_main_thread 替代 QTimer.singleShot，
        # 因为 QTimer.singleShot 从非 Qt 线程调用时回调不会被执行。
        if _QT_AVAILABLE:
            self.bridge.call_in_main_thread(self._do_stop_crawl)
        else:
            self._do_stop_crawl()

    def _do_stop_crawl(self):
        """在 Qt 主线程中执行停止操作（与 GUI on_stop_crawl 对齐）。"""
        spider = self.current_spider
        if not spider:
            return
        spider.stop()
        self.bridge.emit("log", {"message": "🛑 正在停止任务..."})
        debug_logger.log(
            component="WebController",
            action="stop_crawl",
            level="WARN",
            message="Web 端用户请求停止爬虫任务",
            status_code="WEB_CRAWL_STOP",
        )
        # 异步等待 spider 退出（避免阻塞 Qt 事件循环）
        self._stop_wait_count = 0
        self._stop_wait_spider = spider
        self._schedule_stop_wait()

    def _schedule_stop_wait(self):
        """异步等待 spider 线程退出（避免阻塞 Qt 事件循环）。"""
        spider = getattr(self, '_stop_wait_spider', None)
        if spider is None:
            return

        self._stop_wait_count += 1

        if not spider.isRunning():
            # spider 已退出
            self._finish_stop(spider, forced=False)
            return

        if self._stop_wait_count >= 10:  # 1 秒超时（10 * 100ms）
            # spider 仍在运行（Playwright 阻塞），强制清理
            self._finish_stop(spider, forced=True)
            return

        # 继续等待
        if _QT_AVAILABLE:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._schedule_stop_wait)
        else:
            # 无 Qt 模式：直接在当前线程等待
            spider.wait(2000)
            self._finish_stop(spider, forced=spider.isRunning())

    def _finish_stop(self, spider, forced: bool = False):
        """完成停止操作的清理。"""
        # 强制释放时断开 spider 信号，防止幽灵 spider 继续发消息到前端
        if forced:
            try:
                spider.sig_log.disconnect()
                spider.sig_item_found.disconnect()
                spider.sig_select_tasks.disconnect()
                spider.sig_finished.disconnect()
            except Exception:
                pass
            self.bridge.emit("log", {"message": "⚠️ 爬虫线程未能在 1 秒内退出，已强制释放"})
        else:
            self.bridge.emit("log", {"message": "✅ 任务已停止"})
        # 清理 spider 引用（与 GUI _on_spider_finished 对齐）
        if self.current_spider is spider:
            self.current_spider = None
        self._pending_selection_strategy = None
        self._stop_wait_spider = None
        self._stop_wait_count = 0
        self.bridge.emit("crawl_state", {"is_running": False})

    def resume_spider_selection(self, selected_indices: list[int] | None):
        if self.current_spider:
            self.current_spider.resume_from_ui(selected_indices)

    # ---- 目录扫描 ----

    def scan_local_dir(self, directory: str | None = None, scan_limit: int | None = None):
        """同步版目录扫描（向后兼容）。

        与 GUI 对齐：扫描不改变 current_save_dir（只有 change_dir 才改变）。

        Args:
            directory: 要扫描的目录（默认使用 current_save_dir）
            scan_limit: 最多扫描文件数（None=从配置读取，与 REST API /api/scan 对齐）
        """
        directory = directory or self.current_save_dir
        # 与 REST API /api/scan 对齐：scan_limit 支持请求体指定
        if scan_limit is None:
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
        self.bridge.emit("log", {"message": f"📂 正在扫描目录: {directory}"})
        # 与 GUI scan_local_dir 对齐：记录扫描开始日志
        debug_logger.log(
            component="WebController",
            action="scan_local_dir",
            message="Web 端开始扫描本地媒体目录",
            status_code="WEB_SCAN_START",
            details={"directory": directory},
        )

        self.videos.clear()
        self.bridge.emit("clear_videos", {"directory": directory})

        try:
            result = self.file_service.scan_directory(
                directory,
                max_scan_count=scan_limit,
            )
            for item in result.items:
                # 与 SDK scan_directory 一致：本地文件标记为"✅ 本地"，进度 100%
                item.status = "✅ 本地"
                item.progress = 100
                self.videos[item.id] = item
                self.bridge.emit("item_found", self._video_item_to_dict(item))

            msg = f"✅ 已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
            if result.truncated:
                msg = f"⚠️ 文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
            elif result.total_count == 0:
                msg = "ℹ️ 该目录下没有找到视频或图片"
            self.bridge.emit("log", {"message": msg})
            self.bridge.emit("scan_result", {
                "total_count": result.total_count,
                "video_count": result.video_count,
                "image_count": result.image_count,
                # 与 REST API /api/scan 和 /api/dir/change 对齐：包含 truncated 和 original_count
                "truncated": result.truncated,
                "original_count": result.original_count,
            })
        except MediaScanError as exc:
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "scan_local_dir", exc, context={"directory": directory})
        except Exception as exc:
            # BUG-180: 捕获所有异常，避免未处理异常导致 WebSocket 断连
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "scan_local_dir", exc, context={"directory": directory})

    async def async_scan_local_dir(self, directory: str | None = None, scan_limit: int | None = None):
        """异步版目录扫描：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。

        修复 BUG-180: change_dir 不再使用 run_in_executor 包裹整个方法，
        而是只将文件 I/O 部分放到线程池，WebSocket 消息直接 await 发送，
        避免 bridge.emit 的 call_soon + create_task 调度可能导致的静默失败。
        修复 BUG-182: 直接 await self._send_func 而不是通过 bridge.emit 间接调度，
        确保消息在当前协程中立即发送，不会因为调度时序问题丢失。

        Args:
            directory: 要扫描的目录（默认使用 current_save_dir）
            scan_limit: 最多扫描文件数（None=从配置读取，与 REST API /api/scan 对齐）
        """
        import asyncio
        directory = directory or self.current_save_dir
        # 与 REST API /api/scan 对齐：scan_limit 支持请求体指定
        if scan_limit is None:
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
        # 与 GUI 对齐：扫描不改变 current_save_dir（只有 async_change_dir 才改变）

        # 1. 直接 await 发送初始事件（确保消息立即发送到浏览器）
        await self._send_func("log", {"message": f"📂 正在扫描目录: {directory}"})
        # 与 GUI scan_local_dir 对齐：记录扫描开始日志
        debug_logger.log(
            component="WebController",
            action="async_scan_local_dir",
            message="Web 端开始扫描本地媒体目录（异步）",
            status_code="WEB_SCAN_START",
            details={"directory": directory},
        )
        self.videos.clear()
        await self._send_func("clear_videos", {"directory": directory})

        # 2. 文件 I/O 在线程池中执行（不阻塞事件循环）
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                self.file_service.scan_directory,
                directory,
                scan_limit,
            )
        except MediaScanError as exc:
            await self._send_func("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "async_scan_local_dir", exc, context={"directory": directory})
            return
        except Exception as exc:
            await self._send_func("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "async_scan_local_dir", exc, context={"directory": directory})
            return

        # 3. 直接 await 发送结果事件（确保消息立即发送到浏览器）
        for item in result.items:
            # 与 SDK scan_directory 一致：本地文件标记为"✅ 本地"，进度 100%
            item.status = "✅ 本地"
            item.progress = 100
            self.videos[item.id] = item
            await self._send_func("item_found", self._video_item_to_dict(item))

        msg = f"✅ 已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
        if result.truncated:
            msg = f"⚠️ 文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
        elif result.total_count == 0:
            msg = "ℹ️ 该目录下没有找到视频或图片"
        await self._send_func("log", {"message": msg})
        await self._send_func("scan_result", {
            "total_count": result.total_count,
            "video_count": result.video_count,
            "image_count": result.image_count,
            # 与 REST API /api/scan 和 /api/dir/change 对齐：包含 truncated 和 original_count
            "truncated": result.truncated,
            "original_count": result.original_count,
        })

    def change_dir(self, directory: str):
        self.current_save_dir = directory
        cfg.set("common", "save_directory", directory)
        # 与 GUI on_dir_changed 对齐：记录目录变更日志
        debug_logger.log(
            component="WebController",
            action="change_save_dir",
            message="Web 端保存目录已变更",
            status_code="WEB_DIR_CHANGED",
            details={"save_dir": directory},
        )
        self.bridge.emit("log", {"message": f"📂 目录已变更: {directory}"})
        self.scan_local_dir(directory)

    async def async_change_dir(self, directory: str):
        """异步版更改目录：使用 async_scan_local_dir，WebSocket 消息直接 await 发送。

        与 REST API /api/dir/change 对齐：cfg.set 在线程池中执行，避免文件 I/O 阻塞事件循环。
        """
        self.current_save_dir = directory
        # 与 REST API /api/dir/change 对齐：cfg.set 在线程池中执行
        import asyncio
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, cfg.set, "common", "save_directory", directory
            )
        except Exception:
            pass  # cfg.set 失败不影响内存状态
        # 与 GUI on_dir_changed 对齐：记录目录变更日志
        debug_logger.log(
            component="WebController",
            action="change_save_dir",
            message="Web 端保存目录已变更",
            status_code="WEB_DIR_CHANGED",
            details={"save_dir": directory},
        )
        await self._send_func("log", {"message": f"📂 目录已变更: {directory}"})
        await self.async_scan_local_dir(directory)

    # ---- 文件操作 ----

    def delete_video(self, video_id: str):
        if video_id not in self.videos:
            return
        video = self.videos[video_id]
        cancel_result = self.dl_manager.cancel_task(video_id)
        try:
            deleted = self.file_service.delete_media(video)
            if deleted:
                self.bridge.emit("log", {"message": f"🗑️ 已删除: {os.path.basename(video.local_path)}"})
            else:
                self.bridge.emit("log", {"message": f"ℹ️ 文件不存在，仅从列表移除: {video.title}"})
        except FileOperationError as exc:
            self.bridge.emit("log", {"message": f"❌ 删除文件失败: {exc}"})
            return
        if cancel_result == "queued":
            self.bridge.emit("log", {"message": f"🛑 已取消队列任务: {video.title}"})
        elif cancel_result == "running":
            self.bridge.emit("log", {"message": f"🛑 已请求停止下载: {video.title}"})
        del self.videos[video_id]
        self.bridge.emit("video_removed", {"video_id": video_id})

    async def async_delete_video(self, video_id: str):
        """异步版删除视频：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。"""
        import asyncio
        if video_id not in self.videos:
            return
        video = self.videos[video_id]
        cancel_result = self.dl_manager.cancel_task(video_id)
        # 文件删除在线程池中执行
        try:
            deleted = await asyncio.get_running_loop().run_in_executor(
                None, self.file_service.delete_media, video
            )
            if deleted:
                await self._send_func("log", {"message": f"🗑️ 已删除: {os.path.basename(video.local_path)}"})
            else:
                await self._send_func("log", {"message": f"ℹ️ 文件不存在，仅从列表移除: {video.title}"})
        except FileOperationError as exc:
            await self._send_func("log", {"message": f"❌ 删除文件失败: {exc}"})
            return
        if cancel_result == "queued":
            await self._send_func("log", {"message": f"🛑 已取消队列任务: {video.title}"})
        elif cancel_result == "running":
            await self._send_func("log", {"message": f"🛑 已请求停止下载: {video.title}"})
        del self.videos[video_id]
        await self._send_func("video_removed", {"video_id": video_id})

    # ---- 重命名 ----

    def rename_video(self, video_id: str, new_title: str) -> dict:
        if video_id not in self.videos:
            return {"status": "error", "message": "视频不存在"}
        video = self.videos[video_id]
        if not new_title.strip():
            return {"status": "error", "message": "标题不能为空"}
        if not video.local_path or not os.path.exists(video.local_path):
            return {"status": "error", "message": "文件不存在，无法重命名"}
        try:
            old_path, new_path = self.file_service.rename_media(video, new_title.strip(), self.current_save_dir)
            video.title = new_title.strip()
            video.local_path = new_path
            self.bridge.emit("log", {"message": f"📝 重命名: {os.path.basename(old_path)} -> {os.path.basename(new_path)}"})
            self.bridge.emit("video_renamed", {"video_id": video_id, "new_title": video.title, "new_path": new_path})
            return {"status": "ok"}
        except FileOperationError as exc:
            self.bridge.emit("log", {"message": f"❌ 重命名失败: {exc}"})
            return {"status": "error", "message": str(exc)}

    async def async_rename_video(self, video_id: str, new_title: str) -> dict:
        """异步版重命名：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。"""
        import asyncio
        if video_id not in self.videos:
            return {"status": "error", "message": "视频不存在"}
        video = self.videos[video_id]
        if not new_title.strip():
            return {"status": "error", "message": "标题不能为空"}
        if not video.local_path or not os.path.exists(video.local_path):
            return {"status": "error", "message": "文件不存在，无法重命名"}
        try:
            old_path, new_path = await asyncio.get_running_loop().run_in_executor(
                None, self.file_service.rename_media, video, new_title.strip(), self.current_save_dir
            )
            video.title = new_title.strip()
            video.local_path = new_path
            await self._send_func("log", {"message": f"📝 重命名: {os.path.basename(old_path)} -> {os.path.basename(new_path)}"})
            await self._send_func("video_renamed", {"video_id": video_id, "new_title": video.title, "new_path": new_path})
            return {"status": "ok"}
        except FileOperationError as exc:
            await self._send_func("log", {"message": f"❌ 重命名失败: {exc}"})
            return {"status": "error", "message": str(exc)}

    # ---- 配置 ----

    def get_config(self) -> dict:
        return cfg.settings.to_dict()

    def update_config(self, updates: dict):
        for section, values in updates.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                try:
                    cfg.set(section, key, value)
                except Exception:
                    pass

    # ---- 平台信息 ----

    def get_platforms(self) -> list[dict]:
        """返回平台列表（与 SDK list_platforms 字段对齐）。"""
        platforms = []
        for plugin in registry.get_all_plugins():
            info = {
                "id": plugin.id,
                "name": plugin.name,
                "search_placeholder": plugin.get_search_placeholder(),
            }
            # 与 SDK list_platforms 一致：包含 description 和 settings
            if hasattr(plugin, "description") and plugin.description:
                info["description"] = plugin.description
            if hasattr(plugin, "settings_builder") and plugin.settings_builder is not None:
                try:
                    info["settings"] = plugin.settings_builder.field_defs
                except (AttributeError, TypeError):
                    pass
            platforms.append(info)
        return platforms

    # ---- 状态快照 ----

    def get_state(self) -> dict:
        return {
            "current_save_dir": self.current_save_dir,
            "is_crawling": bool(self.current_spider and self.current_spider.isRunning()),
            # 与 GUI 状态栏对齐：返回当前已加载的视频数量
            "video_count": len(self.videos),
        }

    # ---- 媒体路径 ----

    def get_media_path(self, video_id: str) -> str | None:
        item = self.videos.get(video_id)
        if item and item.local_path and os.path.exists(item.local_path):
            return item.local_path
        return None

    # ---- 辅助 ----

    @staticmethod
    def _item_trace_id(item: VideoItem | None) -> str | None:
        """从条目元数据中提取 trace_id（与 GUI ApplicationController._item_trace_id 对齐）。"""
        return item.meta.get("trace_id") if item else None

    @staticmethod
    def _item_context(item: VideoItem | None) -> dict:
        """构建日志上下文字段（与 GUI ApplicationController._item_context 对齐）。"""
        if not item:
            return {}
        return {
            "trace_id": WebController._item_trace_id(item),
            "video_id": item.id,
            "source": item.source,
        }

    @staticmethod
    def _video_item_to_dict(item: VideoItem) -> dict:
        """统一序列化：委托给 VideoItem.to_dict()，确保 CLI/SDK/Web/Skill 四层一致。"""
        return item.to_dict()

    def shutdown(self):
        if self.current_spider and self.current_spider.isRunning():
            self.current_spider.stop()
            self.current_spider.wait(2000)
        self.dl_manager.stop_all()
