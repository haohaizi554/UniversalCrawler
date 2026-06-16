from __future__ import annotations

import sys

from app.debug_logger import debug_logger


class ApplicationLifecycleMixin:
    """Desktop application shutdown and event-loop lifecycle helpers."""

    def _stop_active_spider(self) -> None:
        spider = getattr(self, "current_spider", None)
        if spider and spider.isRunning():
            spider.stop()
            spider.wait(2000)

    def shutdown(self):
        """在应用退出前停止媒体播放、爬虫线程和下载线程。"""
        debug_logger.log(
            component="ApplicationController",
            action="shutdown",
            level="WARN",
            message="应用开始退出清理",
            status_code="APP_SHUTDOWN",
        )
        release_timer = getattr(self, "_media_release_timer", None)
        if release_timer is not None:
            release_timer.stop()
        self._host().cleanup_media()
        self._stop_active_spider()
        self.dl_manager.stop_all()

    def run(self):
        """启动 Qt 事件循环。"""
        sys.exit(self.app.exec())
