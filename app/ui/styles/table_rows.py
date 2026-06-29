"""Shared helpers for table row click/selection highlighting."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPalette
from PyQt6.QtWidgets import QAbstractItemView, QStyle, QStyleOptionViewItem, QTableWidget, QWidget

def install_stable_vertical_scrollbar(view: QAbstractItemView) -> None:
    """Always reserve vertical scrollbar gutter to avoid layout shift flicker."""
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

def row_is_selected(option: QStyleOptionViewItem) -> bool:
    return bool(option.state & QStyle.StateFlag.State_Selected)

def normalize_table_item_option(option: QStyleOptionViewItem) -> None:
    """Keep row visuals click-driven: ignore hover/current focus tinting."""
    option.state &= ~QStyle.StateFlag.State_HasFocus
    if row_is_selected(option):
        return
    option.state &= ~QStyle.StateFlag.State_MouseOver

def selection_fill_color(option: QStyleOptionViewItem) -> QColor:
    return option.palette.color(QPalette.ColorRole.Highlight)

def paint_item_selection_background(painter: QPainter, option: QStyleOptionViewItem) -> None:
    """Paint the full cell rect with the palette highlight color when selected."""
    normalize_table_item_option(option)
    if not row_is_selected(option):
        return
    painter.save()
    painter.fillRect(option.rect, selection_fill_color(option))
    painter.restore()

def install_click_only_row_selection(view: QAbstractItemView) -> None:
    """Highlight rows only after click; moving the mouse must not tint the current row."""
    if getattr(view, "_click_only_rows_installed", False):
        return
    view._click_only_rows_installed = True

    def mouse_move_event(event) -> None:  # type: ignore[no-redef]
        QWidget.mouseMoveEvent(view, event)

    view.mouseMoveEvent = mouse_move_event  # type: ignore[method-assign]

def bind_qtablewidget_row_selection(table: QTableWidget) -> None:
    """Keep item and cell-widget backgrounds in sync with the selected row."""
    install_click_only_row_selection(table)
    model = table.selectionModel()
    if model is None:
        return

    def _sync(_selected=None, _deselected=None) -> None:
        sync_qtablewidget_row_highlights(table)

    model.selectionChanged.connect(_sync)
    _sync()

def sync_qtablewidget_row_highlights(table: QTableWidget) -> None:
    selected_rows = {index.row() for index in table.selectionModel().selectedRows()}
    palette = table.palette()
    highlight = palette.color(QPalette.ColorRole.Highlight)
    base = palette.color(QPalette.ColorRole.Base)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    use_alternate = table.alternatingRowColors()

    for row in range(table.rowCount()):
        background = highlight if row in selected_rows else (alternate if use_alternate and row % 2 else base)
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is not None:
                item.setBackground(background)
            widget = table.cellWidget(row, column)
            if widget is not None:
                _tint_widget_background(widget, background)

def _tint_widget_background(widget: QWidget, color: QColor) -> None:
    widget.setAutoFillBackground(True)
    palette = widget.palette()
    palette.setColor(widget.backgroundRole(), color)
    widget.setPalette(palette)
