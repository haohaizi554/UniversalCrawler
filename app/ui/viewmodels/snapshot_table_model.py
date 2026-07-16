"""为快照驱动页面提供可复用的只读表格 Model。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QIcon

from app.services.icon_registry import ui_icon_path
from shared.icon_contract import platform_icon_file, queue_status_icon_file
from shared.localization import is_translation_of, normalize_language, platform_display_name, source_text_for_translation, tr
from app.utils.qt_runtime import load_qt_icon

SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 2
PENDING_METADATA_LABEL = "\u68c0\u6d4b\u4e2d"
PENDING_METADATA_COLUMNS = {"duration", "resolution"}
PENDING_METADATA_EMPTY_VALUES = {"", "--", PENDING_METADATA_LABEL}

class SnapshotTableModel(QAbstractTableModel):
    """按稳定 ID 和签名局部发出 Model/View 信号，避免整表 reset 丢失选择与滚动位置。"""

    def __init__(self, *, headers: list[str], columns: list[str], icon_columns: set[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._headers = list(headers)
        self._columns = list(columns)
        self._icon_columns = set(icon_columns or ())
        self._rows: list[dict[str, Any]] = []
        self._signature: tuple[Any, ...] | None = None
        self._icon_cache: dict[str, QIcon] = {}
        self._missing_icon_files: set[str] = set()
        self._language = "zh-CN"

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt 重写签名
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt 重写签名
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = self._columns[index.column()]
        value = row.get(key, "")
        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole}:
            if key == "title" and role == Qt.ItemDataRole.ToolTipRole:
                subtitle = str(row.get("subtitle") or "")
                title = str(value)
                return f"{title}\n{subtitle}" if subtitle else title
            if key == "source_display" and role == Qt.ItemDataRole.ToolTipRole:
                return str(row.get("source_display_full") or value)
            if key == "message_summary" and role == Qt.ItemDataRole.ToolTipRole:
                return str(row.get("message") or row.get("message_summary") or value)
            if key in PENDING_METADATA_COLUMNS and self._is_metadata_pending(row, value):
                return tr(PENDING_METADATA_LABEL, self._language)
            if key in {"status", "status_label", "level", "level_display", "reason_label"}:
                return tr(str(value), self._language)
            if key == "platform":
                return platform_display_name(row.get("platform_id"), self._language, fallback=value)
            return str(value)
        if key == "title" and role == SUBTITLE_ROLE:
            return str(row.get("subtitle") or "")
        if role == Qt.ItemDataRole.DecorationRole and key in self._icon_columns:
            icon_file = str(row.get(f"{key}_icon_file") or "")
            if not icon_file and key == "source_display":
                platform_id = str(row.get("platform_id") or "")
                if platform_id and platform_id != "system":
                    icon_file = platform_icon_file(platform_id)
            if not icon_file and key.endswith("_label"):
                icon_file = str(row.get(f"{key[:-6]}_icon_file") or "")
            if not icon_file and key == "platform":
                icon_file = platform_icon_file(str(row.get("platform_id") or ""))
            elif not icon_file and key == "status":
                icon_file = queue_status_icon_file(str(row.get("status") or ""))
            if icon_file:
                return self._cached_icon(icon_file)
        if role == Qt.ItemDataRole.UserRole and index.column() == 0:
            return row.get("id", "")
        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = str(row.get(f"{key}_align") or "").strip().lower()
            if align == "center":
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            if align == "left":
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            if align == "right":
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

            left_keys = {
                "time",
                "title",
                "source",
                "source_display",
                "message",
                "message_summary",
                "subtitle",
                "platform",
                "reason",
                "reason_label",
            }
            center_keys = {
                "level",
                "level_display",
                "trace_id",
                "status",
                "status_label",
            }
            if key in left_keys:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            if key in center_keys:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            if index.column() == 0:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return tr(self._headers[section], self._language)
        return super().headerData(section, orientation, role)

    def set_headers(self, headers: list[str]) -> None:
        headers = self._source_headers_from_display(headers)
        if headers == self._headers:
            return
        self._headers = headers
        if headers:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(headers) - 1)

    def _source_headers_from_display(self, headers: list[str]) -> list[str]:
        normalized: list[str] = []
        for index, header in enumerate(headers):
            text = str(header or "")
            current_source = self._headers[index] if index < len(self._headers) else ""
            if current_source and is_translation_of(text, current_source):
                normalized.append(current_source)
            else:
                normalized.append(source_text_for_translation(text))
        return normalized

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        if self._headers:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._headers) - 1)
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, max(0, self.columnCount() - 1)),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole],
            )

    def set_rows(self, rows: list[dict[str, Any]]) -> bool:
        rows = list(rows)
        signature = self._build_signature(rows)
        if signature == self._signature:
            return False

        if self._signature is None:
            return self._set_rows_without_signature(rows, signature)

        old_signature = self._signature
        old_ids = [item[0] for item in old_signature]
        new_ids = [item[0] for item in signature]
        same_ids = [item[0] for item in signature] == [item[0] for item in old_signature]
        if same_ids and len(rows) == len(self._rows):
            self._replace_existing_rows(rows, old_signature, signature, len(rows))
        elif old_ids == new_ids[: len(old_ids)]:
            self._replace_existing_rows(rows, old_signature, signature, len(old_ids))
            first = len(old_ids)
            last = len(new_ids) - 1
            if first <= last:
                self.beginInsertRows(QModelIndex(), first, last)
                self._rows.extend(rows[first : last + 1])
                self.endInsertRows()
        elif new_ids == old_ids[: len(new_ids)]:
            self._replace_existing_rows(rows, old_signature, signature, len(new_ids))
            first = len(new_ids)
            last = len(old_ids) - 1
            if first <= last:
                self.beginRemoveRows(QModelIndex(), first, last)
                del self._rows[first:]
                self.endRemoveRows()
        elif self._has_same_unique_ids(old_ids, new_ids):
            self.layoutAboutToBeChanged.emit()
            self._rows = rows
            self.layoutChanged.emit()
        elif self._has_unique_ids(old_ids) and self._has_unique_ids(new_ids):
            self._reconcile_unique_rows(rows, signature, new_ids)
        else:
            self.beginResetModel()
            self._rows = rows
            self.endResetModel()
        self._signature = signature
        return True

    def _reconcile_unique_rows(
        self,
        rows: list[dict[str, Any]],
        signature: tuple[Any, ...],
        new_ids: list[Any],
    ) -> None:
        """Apply middle insertions/removals without resetting the Qt model."""

        new_id_set = set(new_ids)
        removed_indexes = [
            index
            for index, row in enumerate(self._rows)
            if row.get("id", "") not in new_id_set
        ]
        for first, last in reversed(self._contiguous_ranges(removed_indexes)):
            self.beginRemoveRows(QModelIndex(), first, last)
            del self._rows[first : last + 1]
            self.endRemoveRows()

        current_ids = [row.get("id", "") for row in self._rows]
        current_id_set = set(current_ids)
        for target_index, item_id in enumerate(new_ids):
            if item_id in current_id_set:
                continue
            insertion_index = min(target_index, len(self._rows))
            self.beginInsertRows(QModelIndex(), insertion_index, insertion_index)
            self._rows.insert(insertion_index, rows[target_index])
            self.endInsertRows()
            current_ids.insert(insertion_index, item_id)
            current_id_set.add(item_id)

        current_signature = self._build_signature(self._rows)
        current_ids = [row.get("id", "") for row in self._rows]
        if current_ids != new_ids:
            self.layoutAboutToBeChanged.emit()
            self._rows = rows
            self.layoutChanged.emit()
            return
        self._replace_existing_rows(
            rows,
            current_signature,
            signature,
            len(rows),
        )

    def _set_rows_without_signature(self, rows: list[dict[str, Any]], signature: tuple[Any, ...]) -> bool:
        if self._rows:
            self.beginResetModel()
            self._rows = rows
            self.endResetModel()
            self._signature = signature
            return True
        if rows:
            self.beginInsertRows(QModelIndex(), 0, len(rows) - 1)
            self._rows = rows
            self.endInsertRows()
            self._signature = signature
            return True
        self._signature = signature
        return False

    def _replace_existing_rows(
        self,
        rows: list[dict[str, Any]],
        old_signature: tuple[Any, ...],
        new_signature: tuple[Any, ...],
        count: int,
    ) -> None:
        if count <= 0:
            return
        for row_index in range(count):
            old = old_signature[row_index]
            new = new_signature[row_index]
            self._rows[row_index] = rows[row_index]
            if old == new:
                continue
            self.dataChanged.emit(
                self.index(row_index, 0),
                self.index(row_index, self.columnCount() - 1),
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.UserRole,
                    Qt.ItemDataRole.DecorationRole,
                    Qt.ItemDataRole.TextAlignmentRole,
                ],
            )

    def force_reset(self) -> None:
        self._signature = None

    def row_for_id(self, item_id: str) -> int:
        for row, item in enumerate(self._rows):
            if item.get("id") == item_id:
                return row
        return -1

    def id_order(self) -> list[str]:
        return [item.get("id", "") for item in self._rows if item.get("id")]

    def row_at(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _build_signature(self, rows: list[dict[str, Any]]) -> tuple[Any, ...]:
        return tuple(
            (
                row.get("id", ""),
                tuple(str(row.get(column, "")) for column in self._columns),
                tuple(str(row.get(f"{column}_icon_file") or row.get(f"{column[:-6]}_icon_file" if column.endswith("_label") else "") or "") for column in self._columns),
                str(row.get("platform_id", "")),
                str(row.get("subtitle", "")),
                bool(row.get("metadata_pending")),
            )
            for row in rows
        )

    @staticmethod
    def _has_same_unique_ids(old_ids: list[Any], new_ids: list[Any]) -> bool:
        if len(old_ids) != len(new_ids) or not old_ids:
            return False
        if any(not item_id for item_id in old_ids) or any(not item_id for item_id in new_ids):
            return False
        return len(set(old_ids)) == len(old_ids) and set(old_ids) == set(new_ids)

    @staticmethod
    def _has_unique_ids(item_ids: list[Any]) -> bool:
        return bool(item_ids) and all(item_ids) and len(set(item_ids)) == len(item_ids)

    @staticmethod
    def _contiguous_ranges(indexes: list[int]) -> list[tuple[int, int]]:
        if not indexes:
            return []
        ranges: list[tuple[int, int]] = []
        first = previous = indexes[0]
        for index in indexes[1:]:
            if index == previous + 1:
                previous = index
                continue
            ranges.append((first, previous))
            first = previous = index
        ranges.append((first, previous))
        return ranges

    @staticmethod
    def _is_metadata_pending(row: dict[str, Any], value: Any) -> bool:
        text = str(value or "").strip()
        if text == PENDING_METADATA_LABEL:
            return True
        if not row.get("metadata_pending"):
            return False
        return text in PENDING_METADATA_EMPTY_VALUES

    def _cached_icon(self, icon_file: str) -> QIcon | None:
        normalized = str(icon_file or "").strip()
        if not normalized or normalized in self._missing_icon_files:
            return None
        cached = self._icon_cache.get(normalized)
        if cached is not None:
            return cached
        icon = load_qt_icon([ui_icon_path(normalized)])
        if icon is None:
            self._missing_icon_files.add(normalized)
            return None
        self._icon_cache[normalized] = icon
        return icon
