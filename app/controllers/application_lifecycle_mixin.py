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
            for topic, handler_name in (
                ("spider.domain_event", "_spider_domain_event_handler"),
                ("download.domain_event", "_download_domain_event_handler"),
            ):
                handler = getattr(self, handler_name, None)
                if handler is not None:
                    unsubscribe(topic, handler)
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
        short_runner = getattr(self, "_short_task_runner", None)
        if short_runner is not None:
            short_runner.cancel_all(timeout_ms=1000)
        frontend_state_service = getattr(self, "frontend_state_service", None)
        destroy_frontend_state = getattr(frontend_state_service, "destroy", None)
        if callable(destroy_frontend_state):
            try:
                destroy_frontend_state()
            except Exception as exc:
                debug_logger.log_exception(
                    "ApplicationController",
                    "shutdown_frontend_state_service",
                    exc,
                )
        app_state = getattr(self, "app_state", None)
        shutdown_app_state = getattr(app_state, "shutdown", None)
        if callable(shutdown_app_state):
            try:
                shutdown_app_state()
            except Exception as exc:
                debug_logger.log_exception(
                    "ApplicationController",
                    "shutdown_app_state",
                    exc,
                )
        cache_service = getattr(self, "cache_service", None)
        close_cache = getattr(cache_service, "close", None)
        if callable(close_cache):
            try:
                close_cache()
            except Exception as exc:
                debug_logger.log_exception(
                    "ApplicationController",
                    "shutdown_cache_service",
                    exc,
                )
        event_bus = getattr(self, "event_bus", None)
        shutdown_event_bus = getattr(event_bus, "shutdown", None)
        if callable(shutdown_event_bus):
            try:
                shutdown_event_bus()
            except Exception as exc:
                debug_logger.log_exception(
                    "ApplicationController",
                    "shutdown_event_bus",
                    exc,
                )
        self._host().cleanup_media()
        self._stop_active_spider()
        if dl_manager is not None:
            stop_thread = threading.Thread(target=dl_manager.stop_all, daemon=True, name="download-stop-all")
            stop_thread.start()
            stop_thread.join(timeout=2.0)

    def run(self):
        """启动 Qt 事件循环。"""
        sys.exit(self.app.exec())
