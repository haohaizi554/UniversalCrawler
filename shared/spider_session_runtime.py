"""Host-neutral spider session runtime shared by GUI / CLI / Web."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

@dataclass(slots=True)
class SpiderSessionBindings:
    """Host callbacks used to bind a spider to its runtime adapter."""

    on_log: Callable[[str], None]
    on_item_found: Callable[[Any], None]
    on_select_tasks: Callable[[Any], None]
    on_finished: Callable[[], None]
    on_items_found: Callable[[list[Any]], None] | None = None
    patch_spider: Callable[[Any], None] | None = None

@dataclass(slots=True)
class SpiderLaunchRequest:
    """显式描述一次 spider 启动请求。"""

    source_id: str
    keyword: str
    config: dict
    save_dir: str | None = None
    selection_strategy: Any | None = None

class SpiderSession:
    """Small orchestration layer for spider create/bind/start/stop."""

    def __init__(self, plugin_registry=None) -> None:
        self.plugin_registry = plugin_registry or self._resolve_default_registry()

    @staticmethod
    def _resolve_default_registry():
        from app.core.plugin_registry import registry as default_registry

        return default_registry

    def create_spider(self, source_id: str, keyword: str, config: dict):
        plugin = self.plugin_registry.get_plugin(source_id)
        if not plugin:
            raise ValueError("未知的爬虫源")
        spider_cls = plugin.get_spider_class()
        return plugin, spider_cls(keyword=keyword, config=config)

    @staticmethod
    def bind_spider(spider, bindings: SpiderSessionBindings) -> None:
        if bindings.patch_spider:
            bindings.patch_spider(spider)
        spider.sig_log.connect(bindings.on_log)
        spider.sig_item_found.connect(bindings.on_item_found)
        batch_signal = getattr(spider, "sig_items_found", None)
        if bindings.on_items_found is not None and batch_signal is not None:
            batch_signal.connect(bindings.on_items_found)
        spider.sig_select_tasks.connect(bindings.on_select_tasks)
        spider.sig_finished.connect(bindings.on_finished)

    @staticmethod
    def unbind_spider(spider, bindings: SpiderSessionBindings) -> None:
        for signal, callback in (
            (spider.sig_log, bindings.on_log),
            (spider.sig_item_found, bindings.on_item_found),
            (getattr(spider, "sig_items_found", None), bindings.on_items_found),
            (spider.sig_select_tasks, bindings.on_select_tasks),
            (spider.sig_finished, bindings.on_finished),
        ):
            if signal is None or callback is None:
                continue
            try:
                signal.disconnect(callback)
            except (TypeError, ValueError):
                pass

    @classmethod
    def activate_spider(cls, spider, bindings: SpiderSessionBindings):
        cls.bind_spider(spider, bindings)
        spider.start()
        return spider

    def start_session(self, source_id: str, keyword: str, config: dict, bindings: SpiderSessionBindings):
        plugin, spider = self.create_spider(source_id, keyword, config)
        self.activate_spider(spider, bindings)
        return plugin, spider

    @staticmethod
    def stop_session(spider, bindings: SpiderSessionBindings | None = None) -> None:
        """Request spider shutdown; keep signal bindings until sig_finished fires."""
        if spider:
            spider.stop()
