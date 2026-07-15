"""提供表格行点击与选中高亮的共享工具。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPalette
from PyQt6.QtWidgets import QAbstractItemView, QStyle, QStyleOptionViewItem, QTableWidget, QWidget

def install_stable_vertical_scrollbar(view: QAbstractItemView) -> None:
    """始终预留垂直滚动条槽位，避免布局位移闪烁。"""
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

def row_is_selected(option: QStyleOptionViewItem) -> bool:
    return bool(option.state & QStyle.StateFlag.State_Selected)

def row_is_hovered(option: QStyleOptionViewItem) -> bool:
    return bool(option.state & QStyle.StateFlag.State_MouseOver)

def normalize_table_item_option(option: QStyleOptionViewItem) -> None:
    """禁用原生焦点和 `hover` 叠层，由共享行绘制统一管理状态。"""
    option.state &= ~QStyle.StateFlag.State_HasFocus
    option.state &= ~QStyle.StateFlag.State_MouseOver

def selection_fill_color(option: QStyleOptionViewItem) -> QColor:
    return option.palette.color(QPalette.ColorRole.Highlight)

def hover_fill_color(option: QStyleOptionViewItem) -> QColor:
    """返回 `item view` 共用的未选中行 `hover` 填充色。"""
    return _blend_colors(
        option.palette.color(QPalette.ColorRole.Base),
        option.palette.color(QPalette.ColorRole.Highlight),
        0.08,
    )

def row_interaction_fill_color(option: QStyleOptionViewItem) -> QColor | None:
    """解析行状态优先级：`selected` 优先，`hover` 仅作辅助。"""
    if row_is_selected(option):
        return selection_fill_color(option)
    if row_is_hovered(option):
        return hover_fill_color(option)
    return None

def paint_item_interaction_background(painter: QPainter, option: QStyleOptionViewItem) -> None:
    """绘制统一的表格行 `hover` 与 `selected` 背景。"""
    color = row_interaction_fill_color(option)
    normalize_table_item_option(option)
    if color is None:
        return
    painter.save()
    painter.fillRect(option.rect, color)
    painter.restore()

def paint_item_selection_background(painter: QPainter, option: QStyleOptionViewItem) -> None:
    """共享行状态绘制的兼容别名。"""
    paint_item_interaction_background(painter, option)

def _blend_colors(base: QColor, overlay: QColor, alpha: float) -> QColor:
    alpha = max(0.0, min(1.0, alpha))
    inverse = 1.0 - alpha
    return QColor(
        round(base.red() * inverse + overlay.red() * alpha),
        round(base.green() * inverse + overlay.green() * alpha),
        round(base.blue() * inverse + overlay.blue() * alpha),
        255,
    )

def install_click_only_row_selection(view: QAbstractItemView) -> None:
    """行选择只由点击驱动，鼠标移动不得改变当前行。"""
    if getattr(view, "_click_only_rows_installed", False):
        return
    view._click_only_rows_installed = True

    def mouse_move_event(event) -> None:  # type: ignore[no-redef]
        QWidget.mouseMoveEvent(view, event)

    view.mouseMoveEvent = mouse_move_event  # type: ignore[method-assign]

def bind_qtablewidget_row_selection(table: QTableWidget) -> None:
    """让 item 与单元格控件背景和选中行保持同步。"""
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
