from __future__ import annotations


class DebugControllerMixin:
    """Debug artifact actions for host-backed desktop controllers."""

    def open_latest_log(self):
        """打开最新的脱敏调试日志文件。"""
        self._run_debug_action("📄 已打开最新调试日志", "打开最新日志", self.debug_service.open_latest_log)

    def open_latest_error_summary(self):
        """打开最近一次异常生成的错误摘要文档。"""
        self._run_debug_action("🚨 已打开最近错误摘要", "打开错误摘要", self.debug_service.open_latest_error_summary)

    def copy_trace_id_for_video(self, video_id: str):
        """把指定资源的 trace_id 复制到剪贴板，便于快速排障。"""
        item = self.videos.get(video_id)
        trace_id = self._item_trace_id(item)
        self._run_debug_action(
            f"📋 已复制 trace_id: {trace_id}",
            "复制 trace_id",
            lambda: self.debug_service.copy_trace_id(self.app.clipboard(), trace_id),
        )
