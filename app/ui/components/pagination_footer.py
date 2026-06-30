from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.ui.components.combo_popup import ThemedComboBox, fit_combo_width_to_contents


class PaginationFooter(QWidget):
    """Shared footer for table pages with count, page controls and page size."""

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
            self.page_size_combo.addItem(f"{option_value} 条/页", option_value)
        self.fit_page_size_combo_width()

        layout.addWidget(self.btn_prev)
        layout.addWidget(self.page_label)
        layout.addWidget(self.btn_next)
        layout.addWidget(self.page_size_combo)

        self.btn_prev.clicked.connect(lambda: self.page_requested.emit(-1))
        self.btn_next.clicked.connect(lambda: self.page_requested.emit(1))
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

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
        self.total_label.setText(f"共 {max(0, int(total_items or 0))} 项")
        self.page_label.setText(f"{current_page} / {total_pages} 页")
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
