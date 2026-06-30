from __future__ import annotations

from app.core.events import (
    DomainEvent,
    DomainEventType,
    build_crawl_state_event,
    build_item_found_event,
    build_log_event,
    build_selection_required_event,
)
from app.config import cfg
from app.core.media_filter import should_skip_for_video_only
from app.core.plugin_registry import registry
from app.core.state import CrawlStatus
from app.debug_logger import debug_logger
from app.models import VideoItem
from shared.spider_session_runtime import SpiderSession, SpiderSessionBindings

class CrawlControllerMixin:
    """Shared crawl-session orchestration for host-backed controllers."""

    def _video_only_mode_enabled(self) -> bool:
        manager_value = getattr(getattr(self, "dl_manager", None), "video_only", None)
        if isinstance(manager_value, bool):
            return manager_value
        return bool(cfg.get("download", "video_only", False))

    def _should_skip_for_video_only(self, item: VideoItem) -> bool:
        return self._video_only_mode_enabled() and should_skip_for_video_only(item)

    def _log_video_only_skip(self, item: VideoItem) -> None:
        title = getattr(item, "title", "") or getattr(item, "url", "")
        self._host().append_log(
            f"Video-only mode skipped non-video resource: {title}",
            trace_id=self._item_trace_id(item),
            source="Downloader",
            level="INFO",
        )
        debug_logger.log(
            component="ApplicationController",
            action="skip_non_video_resource",
            message="Video-only mode skipped a non-video resource",
            status_code="APP_SKIP_VIDEO_ONLY",
            context=self._item_context(item),
            details=self._item_details(item),
            trace_id=self._item_trace_id(item),
        )

    def _emit_spider_log_event(self, message: str) -> None:
        trace_id = getattr(getattr(self, "current_spider", None), "ui_trace_id", None)
        source = getattr(getattr(self, "current_spider", None), "source_id", None) or "Spider"
        self._spider_bridge.sig_event.emit(
            build_log_event(message, trace_id=trace_id, source=source, level="INFO")
        )

    def _emit_spider_item_found_event(self, item: VideoItem) -> None:
        self._spider_bridge.sig_event.emit(build_item_found_event(item))

    def _emit_spider_selection_event(self, items: list) -> None:
        self._spider_bridge.sig_event.emit(build_selection_required_event(items))

    def _emit_spider_finished_event(self) -> None:
        self._spider_bridge.sig_event.emit(build_crawl_state_event(CrawlStatus.FINISHED))

    def _handle_spider_log_event(self, event: DomainEvent) -> None:
        payload = self._event_payload(event)
        self._host().append_log(
            payload.get("message", ""),
            trace_id=payload.get("trace_id") or event.trace_id,
            source=payload.get("source") or "Spider",
            level=payload.get("level") or "INFO",
        )

    def _handle_spider_item_found_event(self, event: DomainEvent) -> None:
        item = self._event_payload(event).get("item")
        if item is not None:
            self._on_spider_item_found(item)

    def _handle_spider_selection_event(self, event: DomainEvent) -> None:
        items = self._event_payload(event).get("items")
        if items is not None:
            self._on_spider_select_tasks(items)

    def _handle_spider_crawl_state_event(self, event: DomainEvent) -> None:
        if self._event_payload(event).get("status") == CrawlStatus.FINISHED.value:
            self._on_spider_finished()

    def _spider_event_handlers(self) -> dict[DomainEventType, callable]:
        return {
            DomainEventType.LOG: self._handle_spider_log_event,
            DomainEventType.ITEM_FOUND: self._handle_spider_item_found_event,
            DomainEventType.SELECTION_REQUIRED: self._handle_spider_selection_event,
            DomainEventType.CRAWL_STATE_CHANGED: self._handle_spider_crawl_state_event,
        }

    def _dispatch_spider_event(self, event: DomainEvent) -> None:
        handler = self._spider_event_handlers().get(event.event_type)
        if handler:
            handler(event)

    def _create_spider(self, source_id: str, keyword: str, config: dict):
        """Create a spider via shared session runtime and surface host-visible failures."""
        spider_session = getattr(self, "spider_session", SpiderSession(registry))
        try:
            return spider_session.create_spider(source_id, keyword, config)
        except ValueError:
            self._host().notify_unknown_source()
            return None, None
        except Exception as exc:
            self._host().notify_spider_create_failed(exc)
            debug_logger.log_exception(
                "ApplicationController",
                "create_spider",
                exc,
                context={"source_id": source_id, "keyword": keyword},
            )
            plugin = registry.get_plugin(source_id)
            return plugin, None

    def _build_spider_session_bindings(self) -> SpiderSessionBindings:
        """Build host callbacks for the shared spider runtime."""
        return SpiderSessionBindings(
            on_log=self._emit_spider_log_event,
            on_item_found=self._emit_spider_item_found_event,
            on_select_tasks=self._emit_spider_selection_event,
            on_finished=self._emit_spider_finished_event,
        )

    def _bind_spider_signals(self, spider) -> None:
        """Bind spider lifecycle callbacks through the unified host event bridge."""
        spider_session = getattr(self, "spider_session", SpiderSession(registry))
        spider_session.bind_spider(spider, self._build_spider_session_bindings())

    def _cleanup_dead_spider(self) -> None:
        spider = getattr(self, "current_spider", None)
        if spider is None or spider.isRunning():
            return
        bindings = getattr(self, "_active_spider_bindings", None)
        if bindings is not None:
            SpiderSession.unbind_spider(spider, bindings)
        self._active_spider_bindings = None
        self._host().append_log("⚠️ 上次任务未正常结束，正在清理...")
        self._host().finish_crawl()
        self.current_spider = None

    def on_start_crawl(self, keyword, source_id, config):
        """Create, bind and start a crawl task through the shared spider session."""
        self._cleanup_dead_spider()
        if self._has_active_spider():
            self._host().notify_crawl_already_running()
            return
        plugin, spider = self._create_spider(source_id, keyword, config)
        if not plugin or not spider:
            return
        self._host().begin_crawl(plugin.name)
        self._log_crawl_start(plugin.name, keyword, source_id, config)

        try:
            spider.ui_trace_id = debug_logger.new_trace_id(f"{source_id}-crawl")
            spider.source_id = source_id
            self.current_spider = spider
            self._active_spider_bindings = self._build_spider_session_bindings()
            spider_session = getattr(self, "spider_session", SpiderSession(registry))
            spider_session.activate_spider(
                self.current_spider,
                self._active_spider_bindings,
            )
        except Exception as exc:
            self._host().fail_crawl_start(exc)
            debug_logger.log_exception(
                "ApplicationController",
                "start_crawl",
                exc,
                context={"source_id": source_id, "keyword": keyword},
            )
            self.current_spider = None

    def _log_crawl_start(self, plugin_name: str, keyword: str, source_id: str, config: dict) -> None:
        """Record the effective crawl input for later debugging and audit."""
        debug_logger.log(
            component="ApplicationController",
            action="start_crawl",
            message="用户启动爬虫任务",
            status_code="APP_CRAWL_START",
            details={
                "keyword": keyword,
                "source_id": source_id,
                "plugin_name": plugin_name,
                "active_config": self._summarize_active_config(config),
            },
        )

    def _on_spider_item_found(self, item):
        """Append a newly discovered item into the host and queue it for download."""
        if self._should_skip_for_video_only(item):
            self._log_video_only_skip(item)
            return
        self._prepare_pending_item(item)
        self._store_video_item(item)
        self._host().add_video_row(item)
        debug_logger.log(
            component="ApplicationController",
            action="item_found",
            message="爬虫发现可下载资源",
            status_code="APP_ITEM_FOUND",
            context=self._item_context(item),
            details=self._item_details(item),
            trace_id=self._item_trace_id(item),
        )
        self.dl_manager.add_task(item, self._host().current_save_dir)

    def _on_spider_select_tasks(self, items):
        """Resume spider processing using the host-provided selection result."""
        selected = self._host().show_selection_dialog(items)
        spider = self.current_spider
        if not spider:
            return
        if selected is None:
            self._stop_spider_after_selection_cancel(spider)
        spider.resume_from_ui(selected)

    def _stop_spider_after_selection_cancel(self, spider) -> None:
        """Treat dialog cancellation as an explicit crawl stop request."""
        if getattr(spider, "interrupt_requested", False):
            return
        spider_session = getattr(self, "spider_session", SpiderSession(registry))
        bindings = getattr(self, "_active_spider_bindings", None)
        spider_session.stop_session(spider, bindings)
        self._host().notify_crawl_stop_requested()
        debug_logger.log(
            component="ApplicationController",
            action="selection_cancel_stop_crawl",
            level="WARN",
            message="用户取消任务选择，停止爬虫任务",
            status_code="APP_CRAWL_SELECTION_CANCEL",
        )

    def _on_spider_finished(self):
        """Reset host crawl state when the current spider session ends."""
        spider = self.current_spider
        bindings = getattr(self, "_active_spider_bindings", None)
        if spider is not None and bindings is not None:
            SpiderSession.unbind_spider(spider, bindings)
        self._active_spider_bindings = None
        self._host().finish_crawl()
        debug_logger.log(
            component="ApplicationController",
            action="crawl_finished",
            message="爬虫任务结束",
            status_code="APP_CRAWL_FINISH",
        )
        self.current_spider = None

    def on_stop_crawl(self):
        """Request the active spider session to stop and report that to the host."""
        dismiss = getattr(self._host(), "dismiss_selection_dialog", None)
        if callable(dismiss):
            dismiss()
        if self.current_spider:
            spider_session = getattr(self, "spider_session", SpiderSession(registry))
            bindings = getattr(self, "_active_spider_bindings", None)
            spider_session.stop_session(self.current_spider, bindings)
            self._host().notify_crawl_stop_requested()
            debug_logger.log(
                component="ApplicationController",
                action="stop_crawl",
                level="WARN",
                message="用户请求停止爬虫任务",
                status_code="APP_CRAWL_STOP",
            )
