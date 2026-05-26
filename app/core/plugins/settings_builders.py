from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from app.config import cfg


class PageLimitSettingsWidget(QWidget):
    """统一的页数下拉控件，固定为少量常用档位。"""

    def __init__(
        self,
        parent=None,
        *,
        label_text: str,
        max_pages: int,
        default_pages: int,
        tooltip: str,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(label_text)
        layout.addWidget(label)

        # 固定选项避免用户在不同平台输入过大页数后带来误解。
        self.combo_pages = QComboBox()
        self.combo_pages.setToolTip(tooltip)
        self.combo_pages.setMinimumWidth(84)
        self.combo_pages.setMaximumWidth(84)
        self.combo_pages.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._page_values = [1, 2, 5, 10, max_pages]
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
        self.combo_pages.setCurrentIndex(max(index, 0))


class MissAVSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.chk_individual = QCheckBox("仅单体")
        self.chk_individual.setChecked(cfg.get("missav", "individual_only", False))
        layout.addWidget(self.chk_individual)

        self.combo_priority = QComboBox()
        self.combo_priority.addItems(["中文字幕优先", "无码流出优先"])
        saved_priority = cfg.get("missav", "priority", "中文字幕优先")
        if saved_priority == "默认排序":
            saved_priority = "中文字幕优先"
        self.combo_priority.setCurrentText(saved_priority)
        layout.addWidget(self.combo_priority)

        layout.addWidget(QLabel("代理:"))
        self.combo_proxy = QComboBox()
        self.combo_proxy.addItems(["Clash (7890)", "v2rayN (10809)", "自定义"])
        self.combo_proxy.setEditable(True)
        self.combo_proxy.setCurrentText(cfg.get("missav", "proxy_app", "Clash (7890)"))
        self.combo_proxy.setMinimumWidth(110)
        layout.addWidget(self.combo_proxy)


def build_bilibili_settings_widget(parent=None) -> PageLimitSettingsWidget:
    return PageLimitSettingsWidget(
        parent,
        label_text="页数:",
        max_pages=500,
        default_pages=cfg.get("bilibili", "max_pages", 1),
        tooltip="搜索或列表扫描页数，可选 1/2/5/10/max；空间主页仍按全量扫描。",
    )


def read_bilibili_run_options(widget: QWidget | None) -> dict[str, int]:
    if not isinstance(widget, PageLimitSettingsWidget):
        return {"max_pages": 1}
    pages = widget.current_value()
    cfg.set("bilibili", "max_pages", pages)
    return {"max_pages": pages}


def build_douyin_settings_widget(parent=None) -> PageLimitSettingsWidget:
    return PageLimitSettingsWidget(
        parent,
        label_text="页数:",
        max_pages=100,
        default_pages=cfg.get("douyin", "search_max_pages", 1),
        tooltip="仅对关键词搜索生效，可选 1/2/5/10/max；链接和主页模式仍按实际流程处理。",
    )


def read_douyin_run_options(widget: QWidget | None) -> dict[str, int]:
    if not isinstance(widget, PageLimitSettingsWidget):
        return {"search_max_pages": 1, "timeout": 10}
    pages = widget.current_value()
    cfg.set("douyin", "search_max_pages", pages)
    return {"search_max_pages": pages, "timeout": 10}


def build_missav_proxy_url(proxy_str: str) -> str:
    normalized = proxy_str.strip()
    if normalized == "Clash (7890)":
        return "http://127.0.0.1:7890"
    if normalized == "v2rayN (10809)":
        return "http://127.0.0.1:10809"
    if ":" in normalized:
        return normalized if normalized.startswith("http") else f"http://{normalized}"
    return "http://127.0.0.1:7890"


def build_missav_settings_widget(parent=None) -> MissAVSettingsWidget:
    return MissAVSettingsWidget(parent)


def read_missav_run_options(widget: QWidget | None) -> dict[str, str | bool]:
    if not isinstance(widget, MissAVSettingsWidget):
        return {
            "individual_only": False,
            "priority": "中文字幕优先",
            "proxy": "http://127.0.0.1:7890",
        }

    is_individual = widget.chk_individual.isChecked()
    priority = widget.combo_priority.currentText()
    proxy_str = widget.combo_proxy.currentText()
    proxy_url = build_missav_proxy_url(proxy_str)

    cfg.set("missav", "individual_only", is_individual)
    cfg.set("missav", "priority", priority)
    cfg.update_missav_proxy(proxy_str, proxy_url)

    return {
        "individual_only": is_individual,
        "priority": priority,
        "proxy": proxy_url,
    }
