from __future__ import annotations

from app.controllers.desktop_host import DesktopHostAdapter
from app.debug_logger import debug_logger
from app.exceptions import DebugActionError
from app.models import VideoItem

class ControllerHostMixin:
    """集中管理宿主适配、调试操作和资源日志字段。"""

    def _host(self) -> DesktopHostAdapter:
        host = getattr(self, "host", None)
        if host is None:
            host = DesktopHostAdapter(self.window)
            self.host = host
        return host

    def _item_details(self, item: VideoItem | None) -> dict:
        """提取允许写入控制器日志的少量资源字段。"""
        if not item:
            return {}
        return debug_logger.pick_used(
            {
                "title": item.title,
                "url": item.url,
                "local_path": item.local_path,
                "content_type": item.meta.get("content_type"),
                "media_label": item.meta.get("media_label"),
                "folder_name": item.meta.get("folder_name"),
                "aweme_id": item.meta.get("aweme_id"),
                "audio_url": item.meta.get("audio_url"),
                "download_strategy": item.meta.get("download_strategy"),
                "referer": item.meta.get("referer"),
            },
            "title",
            "url",
            "local_path",
            "content_type",
            "media_label",
            "folder_name",
            "aweme_id",
            "audio_url",
            "download_strategy",
            "referer",
        )

    def _build_download_finished_log_details(self, item: VideoItem) -> dict:
        return self._item_details(item)

    def _build_download_error_log_details(self, item: VideoItem, error: str) -> dict:
        return {**self._item_details(item), "error": error}

    def _report_debug_action_error(self, action: str, exc: Exception):
        """让调试操作失败统一经宿主界面和日志通道上报。"""
        self._host().append_log(f"❌ {action}失败: {exc}")
        debug_logger.log_exception("ApplicationController", action, exc)

    def _run_debug_action(self, success_message: str, action_name: str, func) -> None:
        """封装调试快捷操作，使成功和失败反馈共用同一宿主出口。"""
        try:
            func()
            self._host().append_log(success_message)
        except DebugActionError as exc:
            self._report_debug_action_error(action_name, exc)
