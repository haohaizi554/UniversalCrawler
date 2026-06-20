from __future__ import annotations

import sys
import threading

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
            try:
                release_timer.timeout.disconnect()
            except (TypeError, RuntimeError):
                pass
        event_bus = getattr(self, "event_bus", None)
        unsubscribe = getattr(event_bus, "unsubscribe", None)
        if callable(unsubscribe):
            unsubscribe("spider.domain_event", getattr(self, "_dispatch_spider_event", None))
            unsubscribe("download.domain_event", getattr(self, "_dispatch_download_event", None))
        dl_manager = getattr(self, "dl_manager", None)
        if dl_manager is not None:
            for signal_name in ("task_started", "task_progress", "task_finished", "task_error"):
                signal = getattr(dl_manager, signal_name, None)
                disconnect = getattr(signal, "disconnect", None)
                if callable(disconnect):
                    try:
                        disconnect()
                    except (TypeError, RuntimeError):
                        pass
        window = getattr(self, "window", None)
        if window is not None:
            scheduler = getattr(window, "_ui_update_scheduler", None)
            if scheduler is not None:
                scheduler.stop()
        self._host().cleanup_media()
        self._stop_active_spider()
        if dl_manager is not None:
            stop_thread = threading.Thread(target=dl_manager.stop_all, daemon=True, name="download-stop-all")
            stop_thread.start()
            stop_thread.join(timeout=2.0)

    def run(self):
        """启动 Qt 事件循环。"""
        sys.exit(self.app.exec())
