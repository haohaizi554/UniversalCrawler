from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.ui.components.combo_popup import ThemedComboBox, fit_combo_width_to_contents
from shared.localization import normalize_language, tr


class PaginationFooter(QWidget):
    """表格页共用的计数、翻页与每页数量控件。"""

    page_requested = pyqtSignal(int)
    page_size_changed = pyqtSignal(int)

    def __init__(
        self,
        page_size_options: Iterable[int] = (20, 50, 100),
        *,
        default_page_size: int = 20,
        combo_min_width: int = 78,
        combo_max_width: int = 112,
        combo_padding: int = 16,
        object_name: str = "",
    ) -> None:
        super().__init__()
        if object_name:
            self.setObjectName(object_name)
        self._page_size = int(default_page_size or 20)
        self._combo_min_width = int(combo_min_width)
        self._combo_max_width = int(combo_max_width)
        self._combo_padding = int(combo_padding)
        self._language = "zh-CN"
        self._last_total_items = 0
        self._last_current_page = 1
        self._last_total_pages = 1

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.total_label = QLabel("共 0 项")
        self.total_label.setObjectName("MutedLabel")
        layout.addWidget(self.total_label)
        layout.addStretch(1)

        self.btn_prev = QPushButton("‹")
        self.btn_prev.setObjectName("PaginationButton")
        self.btn_prev.setToolTip("上一页")
        self.btn_prev.setFixedSize(38, 34)

        self.page_label = QLabel("1 / 1 页")
        self.page_label.setObjectName("MutedLabel")

        self.btn_next = QPushButton("›")
        self.btn_next.setObjectName("PaginationButton")
        self.btn_next.setToolTip("下一页")
        self.btn_next.setFixedSize(38, 34)

        self.page_size_combo = ThemedComboBox(row_height=32)
        self.page_size_combo.setFixedHeight(34)
        for option in page_size_options:
            option_value = int(option)
            self.page_size_combo.addItem(self._page_size_label(option_value), option_value)
        self.fit_page_size_combo_width()

        layout.addWidget(self.btn_prev)
        layout.addWidget(self.page_label)
        layout.addWidget(self.btn_next)
        layout.addWidget(self.page_size_combo)

        self.btn_prev.clicked.connect(lambda: self.page_requested.emit(-1))
        self.btn_next.clicked.connect(lambda: self.page_requested.emit(1))
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

    def set_language(self, language: str | None) -> None:
        self._language = normalize_language(language)
        self.btn_prev.setToolTip(self._t("上一页"))
        self.btn_next.setToolTip(self._t("下一页"))
        blocked = self.page_size_combo.blockSignals(True)
        try:
            for index in range(self.page_size_combo.count()):
                value = int(self.page_size_combo.itemData(index) or 0)
                self.page_size_combo.setItemText(index, self._page_size_label(value))
        finally:
            self.page_size_combo.blockSignals(blocked)
        self.fit_page_size_combo_width()
        self._sync_labels()

    def _t(self, text: str) -> str:
        return tr(text, self._language)

    def _total_label_text(self, count: int) -> str:
        if self._language == "en-US":
            return f"{count} items"
        if self._language == "zh-TW":
            return f"共 {count} 項"
        return f"共 {count} 项"

    def _page_label_text(self, current_page: int, total_pages: int) -> str:
        if self._language == "en-US":
            return f"{current_page} / {total_pages} pages"
        if self._language == "zh-TW":
            return f"{current_page} / {total_pages} 頁"
        return f"{current_page} / {total_pages} 页"

    def _page_size_label(self, count: int) -> str:
        if self._language == "en-US":
            return f"{count} / page"
        if self._language == "zh-TW":
            return f"{count} 條/頁"
        return f"{count} 条/页"

    def _sync_labels(self) -> None:
        self.total_label.setText(self._total_label_text(self._last_total_items))
        self.page_label.setText(self._page_label_text(self._last_current_page, self._last_total_pages))

    @property
    def page_size(self) -> int:
        return self._page_size

    def fit_page_size_combo_width(self) -> None:
        fit_combo_width_to_contents(
            self.page_size_combo,
            min_width=self._combo_min_width,
            max_width=self._combo_max_width,
            horizontal_padding=self._combo_padding,
        )

    def sync(self, *, total_items: int, current_page: int, total_pages: int, page_size: int) -> None:
        current_page = max(1, int(current_page or 1))
        total_pages = max(1, int(total_pages or 1))
        self._page_size = int(page_size or self._page_size or 20)
        self._last_total_items = max(0, int(total_items or 0))
        self._last_current_page = current_page
        self._last_total_pages = total_pages
        self._sync_labels()
        self.btn_prev.setEnabled(current_page > 1)
        self.btn_next.setEnabled(current_page < total_pages)
        index = self.page_size_combo.findData(self._page_size)
        if index >= 0 and self.page_size_combo.currentIndex() != index:
            blocked = self.page_size_combo.blockSignals(True)
            self.page_size_combo.setCurrentIndex(index)
            self.page_size_combo.blockSignals(blocked)

    def _on_page_size_changed(self) -> None:
        self._page_size = int(self.page_size_combo.currentData() or self._page_size or 20)
        self.page_size_changed.emit(self._page_size)
