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
        """Qt 模式：将 Qt 信号转换为 asyncio 协程调用，桥接到 WebSocket。"""

        sig_broadcast = pyqtSignal(str, object)

        def __init__(self, loop: asyncio.AbstractEventLoop, send_func: Callable):
            super().__init__()
            self._loop = loop
            self._send_func = send_func
            self.sig_broadcast.connect(self._on_broadcast)

        def _on_broadcast(self, event_type: str, data: Any):
            """在 Qt 线程中接收信号，调度到 asyncio 事件循环发送。"""
            coro = self._send_func(event_type, data)
            if not asyncio.iscoroutine(coro):
                import logging
                logging.error(f"WebSocketBridge._on_broadcast: _send_func({event_type}) 没有返回 coroutine, got: {type(coro)}")
                return
            asyncio.run_coroutine_threadsafe(coro, self._loop)

        def emit(self, event_type: str, data: Any = None):
            """从任意线程安全地广播事件。"""
            self.sig_broadcast.emit(event_type, data)
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

    VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm")
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
        # 携带 local_path 给 Web 端 (修复 BUG-139: Web 端依赖 local_path 播放视频)
        local_path = item.local_path if item else ""
        self.bridge.emit("task_started", {"video_id": video_id, "local_path": local_path})

    def _on_task_progress(self, video_id: str, progress: int):
        self._apply_video_state(video_id, progress=progress)
        self.bridge.emit("task_progress", {"video_id": video_id, "progress": progress})

    def _on_task_finished(self, video_id: str):
        item = self._apply_video_state(video_id, status="✅ 完成", progress=100)
        self.bridge.emit("task_finished", {"video_id": video_id})
        if item:
            self.bridge.emit("log", {"message": f"✅ 下载完成: {item.title}"})

    def _on_task_error(self, video_id: str, error: str):
        item = self._apply_video_state(video_id, status="❌ 失败")
        self.bridge.emit("task_error", {"video_id": video_id, "error": error})
        if item:
            self.bridge.emit("log", {"message": f"❌ 下载失败 [{item.title}]: {error}"})

    def _apply_video_state(self, vid: str, *, status: str | None = None, progress: int | None = None) -> VideoItem | None:
        item = self.videos.get(vid)
        if not item:
            return None
        if status is not None:
            item.status = status
        if progress is not None:
            item.progress = progress
        self.bridge.emit("video_state_changed", {
            "video_id": vid,
            "status": item.status,
            "progress": item.progress if progress is not None else None,
        })
        return item

    # ---- 爬虫控制 ----

    def start_crawl(self, source_id: str, keyword: str, config: dict):
        if self.current_spider and self.current_spider.isRunning():
            self.bridge.emit("log", {"message": "⚠️ 当前已有任务在运行，请先停止或等待结束"})
            # 与 GUI 一致：启动失败时恢复 UI 状态
            self.bridge.emit("crawl_state", {"is_running": False})
            return

        plugin = registry.get_plugin(source_id)
        if not plugin:
            self.bridge.emit("log", {"message": "❌ 未知的爬虫源"})
            self.bridge.emit("crawl_state", {"is_running": False})
            return

        spider_cls = plugin.get_spider_class()
        spider = spider_cls(keyword=keyword, config=config)

        self.bridge.emit("log", {"message": f"🟢 启动任务 | 模式: {plugin.name}"})
        self.bridge.emit("crawl_state", {"is_running": True, "source": source_id})

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

    def _on_spider_select_tasks(self, items: list):
        self.bridge.emit("select_tasks", {
            "items": [
                {"title": it.get("title", ""), "index": it.get("index", i)}
                for i, it in enumerate(items)
            ]
        })

    def _on_spider_finished(self):
        self.bridge.emit("log", {"message": "✅ 爬虫任务结束"})
        self.bridge.emit("crawl_state", {"is_running": False})
        self.current_spider = None

    def stop_crawl(self):
        # 修复 BUG-170: 不在 controller 层发 log，避免和 spider.stop() 内部 sig_log 重复
        # GUI 端 on_stop_crawl 也是只发一次"🛑 正在停止任务..."，spider.stop() 内部负责
        if self.current_spider:
            self.current_spider.stop()

    def resume_spider_selection(self, selected_indices: list[int]):
        if self.current_spider:
            self.current_spider.resume_from_ui(selected_indices)

    # ---- 目录扫描 ----

    def scan_local_dir(self, directory: str | None = None):
        """同步版目录扫描（向后兼容）。"""
        directory = directory or self.current_save_dir
        self.current_save_dir = directory
        self.bridge.emit("log", {"message": f"📂 正在扫描目录: {directory}"})

        self.videos.clear()
        self.bridge.emit("clear_videos", {"directory": directory})

        try:
            result = self.file_service.scan_directory(
                directory,
                max_scan_count=cfg.get("download", "local_scan_limit", 1000),
            )
            for item in result.items:
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
            })
        except MediaScanError as exc:
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
        except Exception as exc:
            # BUG-180: 捕获所有异常，避免未处理异常导致 WebSocket 断连
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})

    async def async_scan_local_dir(self, directory: str | None = None):
        """异步版目录扫描：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。

        修复 BUG-180: change_dir 不再使用 run_in_executor 包裹整个方法，
        而是只将文件 I/O 部分放到线程池，WebSocket 消息直接 await 发送，
        避免 bridge.emit 的 call_soon + create_task 调度可能导致的静默失败。
        修复 BUG-182: 直接 await self._send_func 而不是通过 bridge.emit 间接调度，
        确保消息在当前协程中立即发送，不会因为调度时序问题丢失。
        """
        import asyncio
        directory = directory or self.current_save_dir
        self.current_save_dir = directory

        # 1. 直接 await 发送初始事件（确保消息立即发送到浏览器）
        await self._send_func("log", {"message": f"📂 正在扫描目录: {directory}"})
        self.videos.clear()
        await self._send_func("clear_videos", {"directory": directory})

        # 2. 文件 I/O 在线程池中执行（不阻塞事件循环）
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                self.file_service.scan_directory,
                directory,
                cfg.get("download", "local_scan_limit", 1000),
            )
        except MediaScanError as exc:
            await self._send_func("log", {"message": f"❌ 扫描目录出错: {exc}"})
            return
        except Exception as exc:
            await self._send_func("log", {"message": f"❌ 扫描目录出错: {exc}"})
            return

        # 3. 直接 await 发送结果事件（确保消息立即发送到浏览器）
        for item in result.items:
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
        })

    def change_dir(self, directory: str):
        self.current_save_dir = directory
        cfg.set("common", "save_directory", directory)
        self.bridge.emit("log", {"message": f"📂 目录已变更: {directory}"})
        self.scan_local_dir(directory)

    async def async_change_dir(self, directory: str):
        """异步版更改目录：使用 async_scan_local_dir，WebSocket 消息直接 await 发送。"""
        self.current_save_dir = directory
        cfg.set("common", "save_directory", directory)
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
        platforms = []
        for plugin in registry.get_all_plugins():
            platforms.append({
                "id": plugin.id,
                "name": plugin.name,
                "search_placeholder": plugin.get_search_placeholder(),
            })
        return platforms

    # ---- 状态快照 ----

    def get_state(self) -> dict:
        return {
            "current_save_dir": self.current_save_dir,
            "is_crawling": bool(self.current_spider and self.current_spider.isRunning()),
        }

    # ---- 媒体路径 ----

    def get_media_path(self, video_id: str) -> str | None:
        item = self.videos.get(video_id)
        if item and item.local_path and os.path.exists(item.local_path):
            return item.local_path
        return None

    # ---- 辅助 ----

    @staticmethod
    def _video_item_to_dict(item: VideoItem) -> dict:
        """统一序列化：委托给 VideoItem.to_dict()，确保 CLI/SDK/Web/Skill 四层一致。"""
        return item.to_dict()

    def shutdown(self):
        if self.current_spider and self.current_spider.isRunning():
            self.current_spider.stop()
            self.current_spider.wait(2000)
        self.dl_manager.stop_all()
