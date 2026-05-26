from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from app.spiders.base import BaseSpider


class BasePlugin:
    id = "base"
    name = "Base Plugin"

    def get_search_placeholder(self) -> str:
        return "请输入关键词..."

    def get_settings_widget(self, parent=None) -> QWidget | None:
        return None

    def get_spider_class(self) -> type[BaseSpider]:
        raise NotImplementedError

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        return {}
