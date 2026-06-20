from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

class IslandCard(QFrame):
    """Rounded surface card used to group related UI into visual islands."""

    def __init__(self, *, object_name: str = "IslandCard", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(10)

    def add_widget(self, widget: QWidget, *, stretch: int = 0) -> None:
        self.content_layout.addWidget(widget, stretch)

    def set_running(self, running: bool) -> None:
        self.setProperty("running", "true" if running else "false")
        self.style().unpolish(self)
        self.style().polish(self)
