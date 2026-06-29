"""Qt-only plugin settings widgets and widget-to-run-options adapters."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from app.config import cfg, get_platform_default_values, get_platform_runtime_defaults, proxy_app_options, request_timeout_options
from app.core.plugins.run_options import build_missav_proxy_url
from app.ui.components.combo_popup import ThemedComboBox

class PageLimitSettingsWidget(QWidget):
    """统一的数量下拉控件，固定为少量常用档位。"""

    def __init__(
        self,
        parent=None,
        *,
        label_text: str,
        max_pages: int,
        default_pages: int,
        tooltip: str,
        preset_values: list[int] | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(label_text)
        layout.addWidget(label)

        self.combo_pages = ThemedComboBox(row_height=32)
        self.combo_pages.setToolTip(tooltip)
        self.combo_pages.setMinimumWidth(84)
        self.combo_pages.setMaximumWidth(84)
        self.combo_pages.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._page_values = list(preset_values or [1, 2, 3, 5, max_pages])
        seen_values: set[int] = set()
        for value in self._page_values:
            if value in seen_values:
                continue
            seen_values.add(value)
            text = "max" if value == max_pages else str(value)
            self.combo_pages.addItem(text, value)
        self.set_current_value(default_pages, max_pages)
        layout.addWidget(self.combo_pages)
        layout.setAlignment(self.combo_pages, Qt.AlignmentFlag.AlignVCenter)

    def current_value(self) -> int:
        return int(self.combo_pages.currentData() or 1)

    def set_current_value(self, value: int, max_pages: int) -> None:
        if value >= max_pages:
            index = self.combo_pages.findData(max_pages)
        else:
            index = self.combo_pages.findData(value)
            if index == -1:
                index = self.combo_pages.findData(1)
            if index == -1:
                index = self.combo_pages.findData(20)
        self.combo_pages.setCurrentIndex(max(index, 0))

class MissAVSettingsWidget(QWidget):
    """MissAV Qt 配置控件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.chk_individual = QCheckBox("仅单体")
        self.chk_individual.setChecked(cfg.get("missav", "individual_only", False))
        layout.addWidget(self.chk_individual)

        self.combo_priority = ThemedComboBox(row_height=32)
        self.combo_priority.addItems(["中文字幕优先", "无码流出优先"])
        saved_priority = cfg.get("missav", "priority", "中文字幕优先")
        if saved_priority == "默认排序":
            saved_priority = "中文字幕优先"
        self.combo_priority.setCurrentText(saved_priority)
        layout.addWidget(self.combo_priority)

        layout.addWidget(QLabel("超时:"))
        self.combo_timeout = ThemedComboBox(row_height=32)
        for option in request_timeout_options():
            self.combo_timeout.addItem(str(option.get("label") or option.get("value")), int(option.get("value") or 60))
        timeout_value = int(get_platform_runtime_defaults("missav").get("timeout", 60))
        timeout_index = self.combo_timeout.findData(timeout_value)
        self.combo_timeout.setCurrentIndex(max(timeout_index, 0))
        self.combo_timeout.setMinimumWidth(92)
        layout.addWidget(self.combo_timeout)

        layout.addWidget(QLabel("代理:"))
        self.combo_proxy = ThemedComboBox(row_height=32)
        self.combo_proxy.addItems([str(option.get("label") or option.get("value")) for option in proxy_app_options()])
        self.combo_proxy.setEditable(True)
        self.combo_proxy.setCurrentText(cfg.get("missav", "proxy_app", "Clash (7890)"))
        self.combo_proxy.setMinimumWidth(220)
        layout.addWidget(self.combo_proxy)

def build_bilibili_settings_widget(parent=None) -> PageLimitSettingsWidget:
    defaults = get_platform_runtime_defaults("bilibili")
    return PageLimitSettingsWidget(
        parent,
        label_text="页数:",
        max_pages=9999,
        default_pages=int(defaults.get("max_pages", 1)),
        tooltip="搜索或列表扫描页数，可选 1/2/3/5/max。",
        preset_values=[1, 2, 3, 5, 9999],
    )

def read_bilibili_run_options(widget: QWidget | None) -> dict[str, int]:
    if not isinstance(widget, PageLimitSettingsWidget):
        defaults = get_platform_default_values("bilibili")
        return {"max_pages": int(defaults.get("max_pages", 1)), "max_items": 9999}
    pages = widget.current_value()
    cfg.set("bilibili", "max_pages", pages)
    return {"max_pages": pages, "max_items": 9999}

def build_douyin_settings_widget(parent=None) -> PageLimitSettingsWidget:
    defaults = get_platform_runtime_defaults("douyin")
    return PageLimitSettingsWidget(
        parent,
        label_text="视频数:",
        max_pages=9999,
        default_pages=int(defaults.get("max_items", 20)),
        tooltip="抖音单次最多处理的视频数量，可选 10/20/30/50/max。",
        preset_values=[10, 20, 30, 50, 9999],
    )

def read_douyin_run_options(widget: QWidget | None) -> dict[str, int]:
    if not isinstance(widget, PageLimitSettingsWidget):
        defaults = get_platform_default_values("douyin")
        return {
            "max_items": int(defaults.get("max_items", 20)),
            "timeout": int(defaults.get("timeout", 10)),
        }
    max_items = widget.current_value()
    cfg.set("douyin", "max_items", max_items)
    defaults = get_platform_runtime_defaults("douyin")
    return {"max_items": max_items, "timeout": int(defaults.get("timeout", 10))}

def build_xiaohongshu_settings_widget(parent=None) -> PageLimitSettingsWidget:
    defaults = get_platform_runtime_defaults("xiaohongshu")
    return PageLimitSettingsWidget(
        parent,
        label_text="笔记数:",
        max_pages=9999,
        default_pages=int(defaults.get("max_items", 20)),
        tooltip="小红书单次最多处理的笔记数量，可选 10/20/30/50/max。",
        preset_values=[10, 20, 30, 50, 9999],
    )

def read_xiaohongshu_run_options(widget: QWidget | None) -> dict[str, int | float]:
    defaults = get_platform_runtime_defaults("xiaohongshu")
    if not isinstance(widget, PageLimitSettingsWidget):
        defaults = get_platform_default_values("xiaohongshu")
        return {
            "max_items": int(defaults.get("max_items", 20)),
            "search_max_pages": int(defaults.get("search_max_pages", 5)),
            "timeout": int(defaults.get("timeout", 30)),
            "request_interval": float(defaults.get("request_interval", 1.5)),
            "detail_request_interval": float(defaults.get("detail_request_interval", 0.5)),
        }
    max_items = widget.current_value()
    cfg.set("xiaohongshu", "max_items", max_items)
    return {
        "max_items": max_items,
        "search_max_pages": int(defaults.get("search_max_pages", 5)),
        "timeout": int(defaults.get("timeout", 30)),
        "request_interval": float(defaults.get("request_interval", 1.5)),
        "detail_request_interval": float(defaults.get("detail_request_interval", 0.5)),
    }

def build_kuaishou_settings_widget(parent=None) -> PageLimitSettingsWidget:
    defaults = get_platform_runtime_defaults("kuaishou")
    return PageLimitSettingsWidget(
        parent,
        label_text="视频数:",
        max_pages=9999,
        default_pages=int(defaults.get("max_items", 20)),
        tooltip="快手单次最多扫描的视频数量，可选 10/20/30/50/max。",
        preset_values=[10, 20, 30, 50, 9999],
    )

def read_kuaishou_run_options(widget: QWidget | None) -> dict[str, int]:
    if not isinstance(widget, PageLimitSettingsWidget):
        defaults = get_platform_default_values("kuaishou")
        return {
            "max_items": int(defaults.get("max_items", 20)),
            "timeout": int(defaults.get("timeout", 10)),
        }
    max_items = widget.current_value()
    cfg.set("kuaishou", "max_items", max_items)
    defaults = get_platform_runtime_defaults("kuaishou")
    return {"max_items": max_items, "timeout": int(defaults.get("timeout", 10))}

def build_missav_settings_widget(parent=None) -> MissAVSettingsWidget:
    return MissAVSettingsWidget(parent)

def read_missav_run_options(widget: QWidget | None) -> dict[str, str | bool | int]:
    if not isinstance(widget, MissAVSettingsWidget):
        defaults = get_platform_default_values("missav")
        return {
            "individual_only": bool(defaults.get("individual_only", False)),
            "priority": str(defaults.get("priority", "中文字幕优先")),
            "timeout": int(defaults.get("timeout", 60)),
            "proxy": str(defaults.get("proxy", "http://127.0.0.1:7890")),
        }

    is_individual = widget.chk_individual.isChecked()
    priority = widget.combo_priority.currentText()
    timeout = int(widget.combo_timeout.currentData() or 60)
    proxy_str = widget.combo_proxy.currentText()
    proxy_url = build_missav_proxy_url(proxy_str)

    cfg.set("missav", "individual_only", is_individual)
    cfg.set("missav", "priority", priority)
    cfg.set("missav", "timeout", timeout)
    cfg.update_missav_proxy(proxy_str, proxy_url)

    return {
        "individual_only": is_individual,
        "priority": priority,
        "timeout": timeout,
        "proxy": proxy_url,
    }

def _iter_plugin_settings_functions():
    """Yield (plugin_id, builder_fn, reader_fn) for every plugin in the registry.

    Uses naming convention ``build_<id>_settings_widget`` /
    ``read_<id>_run_options`` within this module to auto-discover functions,
    eliminating the need for a manual registry dict.

    A plugin without a settings builder simply yields ``(builder=None, reader=None)``.
    """
    from app.core.plugin_registry import registry

    module = sys.modules[__name__]
    for p in registry.get_all_plugins():
        pid = p.id
        builder = getattr(module, f"build_{pid}_settings_widget", None)
        reader = getattr(module, f"read_{pid}_run_options", None)
        yield pid, builder, reader

def build_plugin_settings_widget(plugin_id: str, parent=None) -> QWidget | None:
    """Build the settings widget for *plugin_id*, or return ``None``."""
    for pid, builder, _reader in _iter_plugin_settings_functions():
        if pid == plugin_id and builder is not None:
            return builder(parent)
    return None

def read_plugin_run_options(plugin_id: str, widget: QWidget | None) -> dict:
    """Read run options from the widget for *plugin_id*."""
    for pid, _builder, reader in _iter_plugin_settings_functions():
        if pid == plugin_id and reader is not None:
            return reader(widget)
    return {}
