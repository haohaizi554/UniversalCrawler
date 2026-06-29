from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget


class SmartWrapLabel(QLabel):
    """Selectable label that wraps paths and URLs at useful segment boundaries."""

    BREAK = "\u200b"

    def __init__(self, value: Any = "", parent: QWidget | None = None, *, compact: bool = True) -> None:
        super().__init__(parent)
        self._raw_text = ""
        self._line_gap = 0 if compact else 1
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setProperty("i18nSkipText", "true")
        self.setText(value)

    @staticmethod
    def _separator_chunks(text: str) -> list[str]:
        chunks: list[str] = []
        chunk = ""
        index = 0
        while index < len(text):
            chunk += text[index]
            if text[index] in "\\/":
                index += 1
                while index < len(text) and text[index] in "\\/":
                    chunk += text[index]
                    index += 1
                chunks.append(chunk)
                chunk = ""
                continue
            index += 1
        if chunk:
            chunks.append(chunk)
        return chunks

    @staticmethod
    def _split_long_chunk(chunk: str, max_width: int, metrics) -> list[str]:  # noqa: ANN001
        lines: list[str] = []
        current = ""
        for char in chunk:
            candidate = current + char
            if current and metrics.horizontalAdvance(candidate) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    @classmethod
    def wrap_text(cls, value: Any, max_width: int | None = None, metrics=None) -> str:  # noqa: ANN001
        text = str(value or "")
        if not text:
            return ""
        if max_width is None or metrics is None or max_width <= 20:
            return text.replace("\\", "\\" + cls.BREAK).replace("/", "/" + cls.BREAK)
        lines: list[str] = []
        current = ""
        for chunk in cls._separator_chunks(text):
            candidate = current + chunk
            if current and metrics.horizontalAdvance(candidate) > max_width:
                lines.append(current)
                if metrics.horizontalAdvance(chunk) > max_width:
                    split = cls._split_long_chunk(chunk, max_width, metrics)
                    lines.extend(split[:-1])
                    current = split[-1] if split else ""
                else:
                    current = chunk
            elif not current and metrics.horizontalAdvance(chunk) > max_width:
                split = cls._split_long_chunk(chunk, max_width, metrics)
                lines.extend(split[:-1])
                current = split[-1] if split else ""
            else:
                current = candidate
        if current:
            lines.append(current)
        return "\n".join(lines)

    def setText(self, value: Any) -> None:  # type: ignore[override]
        self._raw_text = str(value or "")
        self._refresh_wrapped_text()
        self.setToolTip(self._raw_text)
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        metrics = self.fontMetrics()
        text = self.wrap_text(self._raw_text, max(1, width), metrics)
        line_count = max(1, len(text.splitlines()))
        margins = self.contentsMargins()
        return margins.top() + margins.bottom() + line_count * metrics.lineSpacing() + max(0, line_count - 1) * self._line_gap

    def sizeHint(self) -> QSize:  # type: ignore[override]
        width = max(1, self.contentsRect().width() or self.width() or 240)
        return QSize(0, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(0, self.fontMetrics().lineSpacing())

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._refresh_wrapped_text()

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self._refresh_wrapped_text()

    def _refresh_wrapped_text(self) -> None:
        width = self._effective_wrap_width()
        text = self.wrap_text(self._raw_text, width, self.fontMetrics())
        if text != super().text():
            QLabel.setText(self, text)
            self.updateGeometry()

    def raw_text(self) -> str:
        return self._raw_text

    def _effective_wrap_width(self) -> int:
        width = max(0, self.contentsRect().width())
        parent = self.parentWidget()
        if parent is not None:
            available = parent.contentsRect().width() - self.x()
            if available > 0:
                width = min(width or available, available)
        return max(1, width)
