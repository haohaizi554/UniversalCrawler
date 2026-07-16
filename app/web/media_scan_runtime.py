"""Web 会话的目录变化监听与本地媒体增量扫描。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.debug_logger import debug_logger
from app.exceptions import MediaScanError
from app.services.media_directory_monitor import media_directory_monitor


class WebMediaScanRuntimeMixin:
    """把文件 I/O 留在线程池，并把一次扫描收敛成一个前端增量事件。"""

    def _start_media_directory_watch(self) -> None:
        if getattr(self, "_media_directory_watch_handle", None) is not None:
            return

        def on_directory_changed(path: str) -> None:
            loop = self._loop
            if loop is None or loop.is_closed() or not loop.is_running():
                return
            loop.call_soon_threadsafe(self._queue_external_media_rescan, path)

        self._media_directory_watch_handle = media_directory_monitor.watch(
            self._media_watch_directories(self.current_save_dir),
            on_directory_changed,
        )

    def _stop_media_directory_watch(self) -> None:
        self._media_directory_watch_closed = True
        handle = getattr(self, "_media_directory_watch_handle", None)
        self._media_directory_watch_handle = None
        close = getattr(handle, "close", None)
        if callable(close):
            close()
        task = self._external_media_scan_task
        self._external_media_scan_task = None
        if task is not None and not task.done():
            task.cancel()

    def _queue_external_media_rescan(self, _changed_directory: str) -> None:
        if self._media_directory_watch_closed or self._is_shutting_down:
            return
        task = self._external_media_scan_task
        if task is not None and not task.done():
            self._external_media_rescan_pending = True
            return
        self._external_media_rescan_pending = False
        task = self._loop.create_task(
            self.async_scan_local_dir(announce=False, require_current=True)
        )
        self._external_media_scan_task = task
        task.add_done_callback(self._finish_external_media_rescan)

    def _finish_external_media_rescan(self, task: asyncio.Task) -> None:
        if self._external_media_scan_task is task:
            self._external_media_scan_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            debug_logger.log_exception("WebController", "external_media_rescan", exc)
        if self._external_media_rescan_pending and not self._media_directory_watch_closed:
            self._external_media_rescan_pending = False
            self._queue_external_media_rescan(self.current_save_dir)

    @staticmethod
    def _media_reconcile_payload(outcome) -> dict[str, Any]:
        removed_ids = list(getattr(outcome, "removed_ids", ()))
        added_ids = list(getattr(outcome, "added_ids", ()))
        return {
            "added_ids": added_ids,
            "removed_ids": removed_ids,
            "video_ids": removed_ids,
            "added_count": len(added_ids),
            "removed_count": len(removed_ids),
        }

    async def _build_media_scan_snapshot(self, directory: str, scan_limit: int | None):
        """串行执行目录遍历，避免过期刷新同时占用线程池。"""

        async with self._media_scan_lock:
            return await asyncio.get_running_loop().run_in_executor(
                None,
                self._scan_media_directory_with_missing,
                directory,
                scan_limit,
            )

    def scan_local_dir(
        self,
        directory: str | None = None,
        scan_limit: int | None = None,
        *,
        announce: bool = True,
    ):
        """兼容仍需同步扫描的调用方；界面主路径使用异步版本。"""

        directory = directory or self.current_save_dir
        if announce:
            self.bridge.emit("log", {"message": f"📂 正在扫描目录: {directory}"})
        debug_logger.log(
            component="WebController",
            action="scan_local_dir",
            message="Web 端开始扫描本地媒体目录",
            status_code="WEB_SCAN_START",
            details={"directory": directory},
        )
        try:
            result, missing_items = self._scan_media_directory_with_missing(directory, scan_limit)
            outcome = self._reconcile_scanned_items(
                result,
                directory,
                missing_items=missing_items,
            )
            self._refresh_media_directory_watch_paths(directory)
            if outcome.changed:
                self.bridge.emit("videos.reconcile", self._media_reconcile_payload(outcome))
            if announce:
                for message in self._build_scan_messages(result):
                    self.bridge.emit("log", {"message": message})
                self.bridge.emit("scan_result", self._scan_result_payload(result))
            return result, outcome
        except MediaScanError as exc:
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
            debug_logger.log_exception(
                "WebController",
                "scan_local_dir",
                exc,
                context={"directory": directory},
            )
        except Exception as exc:
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
            debug_logger.log_exception(
                "WebController",
                "scan_local_dir",
                exc,
                context={"directory": directory},
            )
        return None

    async def async_scan_local_dir(
        self,
        directory: str | None = None,
        scan_limit: int | None = None,
        *,
        announce: bool = True,
        require_current: bool = False,
    ):
        """在线程池扫描，并原子发布真实发生的新增与移除。"""

        requested_current_directory = directory is None
        directory = directory or self.current_save_dir
        require_current = require_current or requested_current_directory
        if (
            self._media_directory_watch_handle is None
            and not self._media_directory_watch_closed
            and self._loop is not None
            and self._loop.is_running()
        ):
            self._start_media_directory_watch()

        if announce:
            await self._send_recorded_frontend_event(
                "log",
                {"message": f"📂 正在扫描目录: {directory}"},
            )
        debug_logger.log(
            component="WebController",
            action="async_scan_local_dir",
            message="Web 端开始扫描本地媒体目录（异步）",
            status_code="WEB_SCAN_START",
            details={"directory": directory},
        )
        try:
            result, missing_items = await self._build_media_scan_snapshot(directory, scan_limit)
        except MediaScanError as exc:
            await self._send_recorded_frontend_event(
                "log",
                {"message": f"❌ 扫描目录出错: {exc}"},
            )
            debug_logger.log_exception(
                "WebController",
                "async_scan_local_dir",
                exc,
                context={"directory": directory},
            )
            return None
        except Exception as exc:
            await self._send_recorded_frontend_event(
                "log",
                {"message": f"❌ 扫描目录出错: {exc}"},
            )
            debug_logger.log_exception(
                "WebController",
                "async_scan_local_dir",
                exc,
                context={"directory": directory},
            )
            return None

        if (
            require_current
            and self._normalize_library_path(directory)
            != self._normalize_library_path(self.current_save_dir)
        ):
            return None

        outcome = self._reconcile_scanned_items(
            result,
            directory,
            missing_items=missing_items,
        )
        self._refresh_media_directory_watch_paths(self.current_save_dir)
        if outcome.changed:
            await self._send_recorded_frontend_event(
                "videos.reconcile",
                self._media_reconcile_payload(outcome),
            )
        if announce:
            for message in self._build_scan_messages(result):
                await self._send_recorded_frontend_event("log", {"message": message})
            await self._send_recorded_frontend_event(
                "scan_result",
                self._scan_result_payload(result),
            )
        return result, outcome

    @staticmethod
    def _scan_result_payload(result) -> dict[str, Any]:
        return {
            "total_count": result.total_count,
            "video_count": result.video_count,
            "image_count": result.image_count,
            "truncated": result.truncated,
            "original_count": result.original_count,
        }
