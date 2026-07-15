from __future__ import annotations

import uuid
from functools import partial

from app.core.events import (
    DomainEvent,
    DomainEventType,
    build_crawl_state_event,
    build_item_found_event,
    build_items_found_event,
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
    """协调宿主控制器中的爬取会话与状态流转。"""

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

    @staticmethod
    def _tag_spider_session(event: DomainEvent, session_id: str | None) -> DomainEvent:
        if session_id:
            event.payload["session_id"] = session_id
        return event

    def _emit_spider_log_event(self, message: str, session_id: str | None = None) -> None:
        trace_id = getattr(getattr(self, "current_spider", None), "ui_trace_id", None)
        source = getattr(getattr(self, "current_spider", None), "source_id", None) or "Spider"
        event = build_log_event(message, trace_id=trace_id, source=source, level="INFO")
        self._spider_bridge.sig_event.emit(self._tag_spider_session(event, session_id))

    def _emit_spider_item_found_event(self, item: VideoItem, session_id: str | None = None) -> None:
        event = build_item_found_event(item)
        self._spider_bridge.sig_event.emit(self._tag_spider_session(event, session_id))

    def _emit_spider_items_found_event(
        self,
        items: list[VideoItem],
        session_id: str | None = None,
    ) -> None:
        event = build_items_found_event(items)
        self._spider_bridge.sig_event.emit(self._tag_spider_session(event, session_id))

    def _emit_spider_selection_event(self, items: list, session_id: str | None = None) -> None:
        event = build_selection_required_event(items)
        self._spider_bridge.sig_event.emit(self._tag_spider_session(event, session_id))

    def _emit_spider_finished_event(self, session_id: str | None = None) -> None:
        event = build_crawl_state_event(CrawlStatus.FINISHED)
        self._spider_bridge.sig_event.emit(self._tag_spider_session(event, session_id))

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

    def _handle_spider_items_found_event(self, event: DomainEvent) -> None:
        items = self._event_payload(event).get("items")
        if items is not None:
            self._on_spider_items_found(items)

    def _handle_spider_selection_event(self, event: DomainEvent) -> None:
        payload = self._event_payload(event)
        items = payload.get("items")
        if items is not None:
            session_id = payload.get("session_id")
            if session_id is None:
                self._schedule_spider_selection(items)
            else:
                self._schedule_spider_selection(items, session_id)

    def _handle_spider_crawl_state_event(self, event: DomainEvent) -> None:
        if self._event_payload(event).get("status") == CrawlStatus.FINISHED.value:
            self._on_spider_finished()

    def _spider_event_handlers(self) -> dict[DomainEventType, callable]:
        return {
            DomainEventType.LOG: self._handle_spider_log_event,
            DomainEventType.ITEM_FOUND: self._handle_spider_item_found_event,
            DomainEventType.ITEMS_FOUND: self._handle_spider_items_found_event,
            DomainEventType.SELECTION_REQUIRED: self._handle_spider_selection_event,
            DomainEventType.CRAWL_STATE_CHANGED: self._handle_spider_crawl_state_event,
        }

    def _dispatch_spider_event(self, event: DomainEvent) -> None:
        session_id = self._event_payload(event).get("session_id")
        active_session_id = getattr(self, "_active_spider_session_id", None)
        # 旧 worker 可能在新任务启动后才送达收尾事件；会话令牌可防止其改写新任务状态。
        if session_id is not None and session_id != active_session_id:
            return
        handler = self._spider_event_handlers().get(event.event_type)
        if handler:
            handler(event)

    def _schedule_spider_selection(self, items: list, session_id: str | None = None) -> None:
        """将模态选择框延后到 EventBus 发布栈之外，避免同步回调重入。"""
        selected_items = list(items)
        if session_id is None:
            callback = partial(self._on_spider_select_tasks, selected_items)
        else:
            callback = partial(self._on_spider_select_tasks, selected_items, session_id)
        self._host()._queue_on_ui(callback)

    def _create_spider(self, source_id: str, keyword: str, config: dict):
        """通过共享会话运行时创建 Spider，并向宿主呈现创建失败。"""
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

    def _build_spider_session_bindings(self, session_id: str | None = None) -> SpiderSessionBindings:
        """为共享 Spider 运行时构造宿主回调。"""
        if session_id is None:
            return SpiderSessionBindings(
                on_log=self._emit_spider_log_event,
                on_item_found=self._emit_spider_item_found_event,
                on_items_found=self._emit_spider_items_found_event,
                on_select_tasks=self._emit_spider_selection_event,
                on_finished=self._emit_spider_finished_event,
            )
        return SpiderSessionBindings(
            on_log=lambda message: self._emit_spider_log_event(message, session_id),
            on_item_found=lambda item: self._emit_spider_item_found_event(item, session_id),
            on_items_found=lambda items: self._emit_spider_items_found_event(items, session_id),
            on_select_tasks=lambda items: self._emit_spider_selection_event(items, session_id),
            on_finished=lambda: self._emit_spider_finished_event(session_id),
        )

    def _bind_spider_signals(self, spider) -> None:
        """经统一宿主事件桥绑定 Spider 生命周期回调。"""
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
        self._active_spider_session_id = None
        self._host().append_log("⚠️ 上次任务未正常结束，正在清理...")
        self._host().finish_crawl()
        self.current_spider = None

    def on_start_crawl(self, keyword, source_id, config):
        """通过共享 Spider 会话创建、绑定并启动爬取任务。"""
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
            # 每次启动都换用新令牌，使上一会话的迟到回调在分派边界被丢弃。
            self._active_spider_session_id = uuid.uuid4().hex
            self._active_spider_bindings = self._build_spider_session_bindings(
                self._active_spider_session_id
            )
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
            self._active_spider_session_id = None

    def _log_crawl_start(self, plugin_name: str, keyword: str, source_id: str, config: dict) -> None:
        """记录实际生效的爬取输入，供排障和审计使用。"""
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
        """把单个新资源交给统一的批量接收路径。"""
        self._on_spider_items_found([item])

    def _on_spider_items_found(self, items):
        """接收一批资源，并尽量用一次队列唤醒完成下载入队。"""
        accepted_items: list[VideoItem] = []
        for item in list(items or []):
            if self._should_skip_for_video_only(item):
                self._log_video_only_skip(item)
                continue
            self._prepare_pending_item(item)
            accepted_items.append(item)
        if not accepted_items:
            return
        if len(accepted_items) == 1:
            item = accepted_items[0]
            self._store_video_item(item)
            self._host().add_video_row(item)
            self._log_spider_item_found(item)
            self.dl_manager.add_task(item, self._host().current_save_dir)
            return

        store_many = getattr(self, "_store_video_items", None)
        if callable(store_many):
            store_many(accepted_items)
        else:
            for item in accepted_items:
                self._store_video_item(item)

        add_rows = getattr(self._host(), "add_video_rows", None)
        if callable(add_rows):
            add_rows(accepted_items)
        else:
            for item in accepted_items:
                self._host().add_video_row(item)

        save_dir = self._host().current_save_dir
        add_tasks = getattr(self.dl_manager, "add_tasks", None)
        # 批量提交可压低下载队列唤醒和 UI 通知频率；旧实现不支持时才逐项回退。
        if callable(add_tasks):
            add_tasks(accepted_items, save_dir)
        else:
            for item in accepted_items:
                self.dl_manager.add_task(item, save_dir)

        for item in accepted_items:
            self._log_spider_item_found(item)

    def _log_spider_item_found(self, item: VideoItem) -> None:
        debug_logger.log(
            component="ApplicationController",
            action="item_found",
            message="爬虫发现可下载资源",
            status_code="APP_ITEM_FOUND",
            context=self._item_context(item),
            details=self._item_details(item),
            trace_id=self._item_trace_id(item),
        )

    def _on_spider_select_tasks(self, items, session_id: str | None = None):
        """把宿主选择结果回填给暂停中的 Spider。"""
        spider = self.current_spider
        if not spider:
            return
        if session_id is not None and session_id != getattr(self, "_active_spider_session_id", None):
            return
        selected = self._host().show_selection_dialog(items)
        # 模态框期间事件循环仍可能完成停止或启动新任务，回填前必须再次核对会话身份。
        if spider is not self.current_spider:
            return
        if session_id is not None and session_id != getattr(self, "_active_spider_session_id", None):
            return
        if selected is None:
            self._stop_spider_after_selection_cancel(spider)
        # 即使取消已传播 stop，也要释放 Spider 的选择等待点，使 worker 能进入统一收尾。
        spider.resume_from_ui(selected)

    def _stop_spider_after_selection_cancel(self, spider) -> None:
        """把关闭选择框视为显式停止请求，并向 Spider 传播取消。"""
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
        """当前 Spider 会话结束后重置宿主爬取状态。"""
        spider = self.current_spider
        bindings = getattr(self, "_active_spider_bindings", None)
        if spider is not None and bindings is not None:
            SpiderSession.unbind_spider(spider, bindings)
        self._active_spider_bindings = None
        self._active_spider_session_id = None
        self._host().finish_crawl()
        debug_logger.log(
            component="ApplicationController",
            action="crawl_finished",
            message="爬虫任务结束",
            status_code="APP_CRAWL_FINISH",
        )
        self.current_spider = None

    def on_stop_crawl(self):
        """请求停止当前 Spider 会话，并把停止状态同步给宿主。"""
        # 先关闭模态选择框，避免用户停止后界面仍阻塞在旧会话；Spider 的等待点由 stop 负责唤醒。
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
