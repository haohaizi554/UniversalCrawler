from __future__ import annotations

import weakref

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QItemSelectionModel, QObject, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QListView,
    QStyle,
    QStyleOptionComboBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from app.ui.styles.themes import resolve_is_dark_theme, theme_colors

FULL_EXPAND_ROW_LIMIT = 12
DEFAULT_ROW_HEIGHT = 40
MIN_ROW_HEIGHT = 28
POPUP_BORDER_WIDTH = 2
POPUP_BORDER_RADIUS = 8


def _int_property(obj: QObject, name: str) -> int:
    try:
        return int(obj.property(name) or 0)
    except (TypeError, ValueError, RuntimeError):
        return 0


def _bool_property(obj: QObject, name: str) -> bool:
    try:
        value = obj.property(name)
    except RuntimeError:
        return False
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _qt_object_alive(obj: QObject | None) -> bool:
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except (AttributeError, RuntimeError, TypeError):
        return False


def _combo_colors(combo: QComboBox) -> dict[str, str]:
    return theme_colors(resolve_is_dark_theme(combo))


def themed_combo_stylesheet(combo: QComboBox, *, radius: int = 8, horizontal_padding: int = 8) -> str:
    """返回所有 GUI 下拉框共用的紧凑控件样式。"""
    colors = _combo_colors(combo)
    return f"""
    QComboBox {{
        min-height: 30px;
        border: 1px solid {colors["border_strong"]};
        border-radius: {radius}px;
        background: {colors["input"]};
        color: {colors["text"]};
        padding: 0px {horizontal_padding}px;
        selection-background-color: {colors["accent"]};
        selection-color: #ffffff;
    }}
    QComboBox:hover {{
        border-color: {colors["accent"]};
        background: {colors["input"]};
    }}
    QComboBox:focus,
    QComboBox:on,
    QComboBox[popupOpen="true"],
    QComboBox[customProxy="true"] {{
        border: 2px solid {colors["accent"]};
        background: {colors["input"]};
    }}
    QComboBox:disabled {{
        background: {colors["panel_soft"]};
        border-color: {colors["border"]};
        color: {colors["muted"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 0px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border: none;
        width: 0px;
        height: 0px;
    }}
    QComboBox QAbstractItemView {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 2px solid {colors["accent"]};
        border-radius: {radius}px;
        selection-background-color: {colors["accent"]};
        selection-color: #ffffff;
        padding: 0px;
    }}
    QComboBox QAbstractItemView::item {{
        border: none;
        padding: 4px 8px;
    }}
    QComboBox QAbstractItemView::item:selected,
    QComboBox QAbstractItemView::item:selected:hover,
    QComboBox QAbstractItemView::item:hover {{
        background: transparent;
    }}
    """


def combo_widest_item_text_width(combo: QComboBox) -> int:
    metrics = combo.fontMetrics()
    widths: list[int] = []
    for index in range(combo.count()):
        icon = combo.itemIcon(index)
        icon_extra = combo.iconSize().width() + 6 if not icon.isNull() else 0
        widths.append(metrics.horizontalAdvance(combo.itemText(index)) + icon_extra)
    if not widths:
        widths.append(metrics.horizontalAdvance(combo.currentText() or ""))
    return max(widths, default=0)


def combo_edit_field_width(combo: QComboBox) -> int:
    try:
        combo.ensurePolished()
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        rect = combo.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            combo,
        )
        return max(0, int(rect.width()))
    except (RuntimeError, TypeError):
        return max(0, combo.width())


def fit_combo_width_to_contents(
    combo: QComboBox,
    *,
    min_width: int = 0,
    max_width: int = 640,
    horizontal_padding: int = 16,
    set_popup_max_width: bool = True,
) -> int:
    widest = combo_widest_item_text_width(combo)
    state_reserve = 4
    target_width = max(
        int(min_width),
        min(int(max_width), widest + max(0, int(horizontal_padding)) + state_reserve),
    )
    for _ in range(4):
        combo.setFixedWidth(target_width)
        edit_width = combo_edit_field_width(combo)
        if edit_width <= 0 or edit_width >= widest or target_width >= max_width:
            break
        target_width = min(int(max_width), target_width + widest - edit_width)
    combo.setFixedWidth(target_width)
    if set_popup_max_width:
        combo.setProperty("comboPopupMaxWidth", target_width)
        combo.setProperty("comboPopupClampToControl", "true")
    return target_width


def apply_themed_combo_box(
    combo: QComboBox,
    *,
    row_height: int = DEFAULT_ROW_HEIGHT,
    visible_rows: int | None = None,
    control_style: bool = True,
) -> QComboBox:
    """让既有下拉框使用共享主题弹层及可选控件外观。"""
    combo.setProperty("themedCombo", "true")
    combo.setProperty("themedComboManaged", "true")
    combo.setProperty("themedComboControlStyle", "true" if control_style else "false")
    if combo.view() is None or not isinstance(combo.view(), QListView):
        view = QListView(combo)
        view.setObjectName("ThemedComboPopup")
        combo.setView(view)
    if control_style:
        combo.setStyleSheet(themed_combo_stylesheet(combo))
    polish_combo_popup(combo, visible_rows=visible_rows, row_height=row_height)
    return combo


def refresh_themed_combo_boxes(root: QWidget | QComboBox | None) -> None:
    """主题、字体或 palette 变化后刷新受管下拉框的 QSS。"""
    if root is None:
        return

    combos: list[QComboBox] = []
    if isinstance(root, QComboBox):
        combos.append(root)
    if isinstance(root, QWidget):
        combos.extend(root.findChildren(QComboBox))

    seen: set[int] = set()
    for combo in combos:
        if not _qt_object_alive(combo):
            continue
        if id(combo) in seen or combo.property("themedComboManaged") != "true":
            continue
        seen.add(id(combo))
        try:
            view = combo.view()
            popup = view.window() if _qt_object_alive(view) else None
            if _qt_object_alive(popup) and popup.isVisible():
                combo.hidePopup()
                combo.setProperty("popupOpen", "false")
                continue
        except RuntimeError:
            continue
        row_height = _int_property(combo, "comboPopupRowHeight") or DEFAULT_ROW_HEIGHT
        visible_rows = _int_property(combo, "comboPopupVisibleRows") or None
        control_style = combo.property("themedComboControlStyle") != "false"
        apply_themed_combo_box(
            combo,
            row_height=row_height,
            visible_rows=visible_rows,
            control_style=control_style,
        )
        combo.style().unpolish(combo)
        combo.style().polish(combo)
        combo.update()


class NoFocusItemDelegate(QStyledItemDelegate):
    """绘制下拉行时移除 Qt 原生黑色焦点框。"""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001
        clean_option = QStyleOptionViewItem(option)
        parent = self.parent()
        row_rect = self._full_row_rect(option)
        selected = bool(clean_option.state & QStyle.StateFlag.State_Selected)
        if not selected and isinstance(parent, QAbstractItemView):
            selection_model = parent.selectionModel()
            selected = bool(
                (selection_model is not None and selection_model.isSelected(index))
                or parent.currentIndex() == index
            )
        hovered = bool(clean_option.state & QStyle.StateFlag.State_MouseOver)
        clean_option.state &= ~QStyle.StateFlag.State_HasFocus
        clean_option.state &= ~QStyle.StateFlag.State_Selected
        clean_option.state &= ~QStyle.StateFlag.State_MouseOver
        if selected:
            painter.save()
            self._clip_to_popup_round_rect(painter, parent)
            painter.fillRect(row_rect, option.palette.color(QPalette.ColorRole.Highlight))
            painter.restore()
            clean_option.palette.setColor(QPalette.ColorRole.Text, option.palette.color(QPalette.ColorRole.HighlightedText))
        elif hovered:
            painter.save()
            self._clip_to_popup_round_rect(painter, parent)
            painter.fillRect(row_rect, option.palette.color(QPalette.ColorRole.AlternateBase))
            painter.restore()
        clean_option.rect = row_rect
        super().paint(painter, clean_option, index)
        self._paint_popup_border(painter, option, index)

    def _clip_to_popup_round_rect(self, painter: QPainter, parent: object) -> None:
        if not isinstance(parent, QAbstractItemView):
            return
        radius = _int_property(parent, "comboPopupBorderRadius") or POPUP_BORDER_RADIUS
        rect = parent.viewport().rect().adjusted(1, 1, -1, -1)
        if not rect.isValid():
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.setClipPath(path)

    def _full_row_rect(self, option: QStyleOptionViewItem) -> QRect:
        parent = self.parent()
        if not isinstance(parent, QAbstractItemView):
            return QRect(option.rect)
        rect = QRect(option.rect)
        viewport_rect = parent.viewport().rect()
        if viewport_rect.isValid():
            rect.setLeft(viewport_rect.left())
            rect.setRight(viewport_rect.right())
        return rect

    def _paint_popup_border(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        parent = self.parent()
        if not isinstance(parent, QAbstractItemView):
            return
        if parent.property("comboPopupPaintedBorder") != "true":
            return

        color_name = str(parent.property("comboPopupAccent") or "")
        color = QColor(color_name) if color_name else option.palette.color(QPalette.ColorRole.Highlight)
        if not color.isValid():
            color = option.palette.color(QPalette.ColorRole.Highlight)

        radius = _int_property(parent, "comboPopupBorderRadius") or POPUP_BORDER_RADIUS
        rect = parent.viewport().rect().adjusted(1, 1, -2, -2)
        if not rect.isValid():
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(color, POPUP_BORDER_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802, ANN001
        size = super().sizeHint(option, index)
        parent = self.parent()
        row_height = _int_property(parent, "comboPopupRowHeight") if parent is not None else 0
        row_height = row_height or DEFAULT_ROW_HEIGHT
        size.setHeight(max(MIN_ROW_HEIGHT, row_height))
        if isinstance(parent, QAbstractItemView):
            size.setWidth(max(size.width(), parent.viewport().width(), parent.width()))
        return size


class ComboPopupEventFilter(QObject):
    """锁定完全展开的弹层，避免隐藏滚动仍制造底部空白。"""

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view_ref = weakref.ref(view)
        self._lock_pending = False
        self._lock_attempts = 0
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_popup_lock)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001, N802
        view = self._resolve_view(watched)
        try:
            full_expand = (
                _qt_object_alive(view)
                and isinstance(view, QAbstractItemView)
                and view.property("comboPopupFullExpand") == "true"
            )
        except RuntimeError:
            full_expand = False
        if full_expand:
            if event.type() == QEvent.Type.Wheel:
                self._reset_scroll(view)
                return True
            if event.type() in {QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest}:
                self._schedule_popup_lock()
        return super().eventFilter(watched, event)

    def _resolve_view(self, watched) -> QAbstractItemView | None:  # noqa: ANN001
        current_view = self._view_ref()
        if _qt_object_alive(current_view) and isinstance(current_view, QAbstractItemView):
            return current_view
        view = getattr(watched, "_combo_popup_view", None)
        if _qt_object_alive(view) and isinstance(view, QAbstractItemView):
            return view
        if _qt_object_alive(watched) and isinstance(watched, QAbstractItemView):
            return watched
        if not _qt_object_alive(watched):
            return None
        parent = getattr(watched, "parent", lambda: None)()
        while parent is not None:
            if not _qt_object_alive(parent):
                return None
            if isinstance(parent, QAbstractItemView):
                return parent
            parent = getattr(parent, "parent", lambda: None)()
        return None

    def _schedule_popup_lock(self, *, force: bool = False) -> None:
        if self._lock_pending and not force:
            return
        self._lock_pending = True
        self._lock_attempts = 0
        self._flush_timer.start(0)

    def _flush_popup_lock(self) -> None:
        view = self._resolve_view(None)
        if _qt_object_alive(view) and isinstance(view, QAbstractItemView):
            self._lock_popup_geometry(view)

        retry_delays = (20, 80, 160)
        if self._lock_attempts < len(retry_delays):
            delay = retry_delays[self._lock_attempts]
            self._lock_attempts += 1
            self._flush_timer.start(delay)
        else:
            self._lock_pending = False

    @staticmethod
    def _reset_scroll(view: QAbstractItemView) -> None:
        if not _qt_object_alive(view):
            return
        try:
            bar = view.verticalScrollBar()
            if not _qt_object_alive(bar):
                return
            bar.setRange(0, 0)
            bar.setValue(0)
        except RuntimeError:
            return

    @staticmethod
    def _lock_popup_geometry(view: QAbstractItemView) -> None:
        if not _qt_object_alive(view):
            return
        try:
            ComboPopupEventFilter._reset_scroll(view)
            target_width = _int_property(view, "comboPopupTargetWidth")
            target_height = _int_property(view, "comboPopupTargetHeight")
            if target_width <= 0:
                return
            view.setMinimumWidth(target_width)
            view.setMaximumWidth(target_width)
            if view.width() != target_width:
                view.resize(target_width, view.height())
            if target_height > 0:
                view.setMinimumHeight(target_height)
                view.setMaximumHeight(target_height)
                if view.height() != target_height:
                    view.resize(target_width, target_height)
            for popup in _combo_popup_windows(view):
                _lock_popup_widget(popup, target_width, target_height)
        except RuntimeError:
            return

    @staticmethod
    def _lock_popup_geometry_later(view_ref: weakref.ReferenceType[QAbstractItemView]) -> None:
        view = view_ref()
        if not _qt_object_alive(view) or not isinstance(view, QAbstractItemView):
            return
        ComboPopupEventFilter._lock_popup_geometry(view)


def _is_combo_popup_widget(widget: QWidget | None, view: QAbstractItemView) -> bool:
    if widget is None or widget is view:
        return False
    try:
        return widget.windowType() == Qt.WindowType.Popup or bool(widget.windowFlags() & Qt.WindowType.Popup)
    except RuntimeError:
        return False


def _combo_popup_windows(view: QAbstractItemView) -> list[QWidget]:
    widgets: list[QWidget] = []
    seen: set[int] = set()
    for widget in (view.window(), view.parentWidget()):
        if not _is_combo_popup_widget(widget, view):
            continue
        key = id(widget)
        if key in seen:
            continue
        seen.add(key)
        widgets.append(widget)
    return widgets


def _lock_popup_widget(popup: QWidget, target_width: int, target_height: int = 0) -> None:
    try:
        layout = popup.layout()
        if layout is not None:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        popup.setContentsMargins(0, 0, 0, 0)
        if target_height > 0:
            popup.setMinimumSize(target_width, target_height)
            popup.setMaximumSize(target_width, target_height)
            if popup.width() != target_width or popup.height() != target_height:
                popup.resize(target_width, target_height)
        else:
            popup.setMinimumWidth(target_width)
            popup.setMaximumWidth(target_width)
            if popup.width() != target_width:
                popup.resize(target_width, popup.height())
    except RuntimeError:
        return


def polish_combo_popup(combo: QComboBox, *, visible_rows: int | None = None, row_height: int | None = None) -> None:
    """统一弹层选中行对齐，并移除原生焦点外观。"""
    combo.setProperty("themedCombo", "true")
    view = combo.view()
    if view is None:
        return

    stored_visible_rows = _int_property(combo, "comboPopupVisibleRows")
    requested_rows = int(visible_rows) if visible_rows is not None else (stored_visible_rows or combo.count())
    visible_count = max(1, min(combo.count() or 1, requested_rows or combo.count() or 1))
    if combo.count() <= FULL_EXPAND_ROW_LIMIT:
        visible_count = max(1, combo.count() or 1)

    fully_expanded = combo.count() <= visible_count
    stored_row_height = _int_property(combo, "comboPopupRowHeight") or _int_property(view, "comboPopupRowHeight")
    fallback_height = int(row_height) if row_height is not None else (stored_row_height or DEFAULT_ROW_HEIGHT)
    fallback_height = max(MIN_ROW_HEIGHT, fallback_height)
    colors = _combo_colors(combo)
    hidden_scrollbar_style = (
        "width: 0px; height: 0px; margin: 0px; border: none; background: transparent;"
        if fully_expanded
        else ""
    )
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["accent_soft"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    view.setPalette(palette)
    view.setAutoFillBackground(True)
    view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setLineWidth(0)
    view.setContentsMargins(0, 0, 0, 0)
    try:
        view.setViewportMargins(0, 0, 0, 0)
    except RuntimeError:
        pass
    if isinstance(view, QListView):
        view.setSpacing(0)
        view.setViewMode(QListView.ViewMode.ListMode)
        view.setResizeMode(QListView.ResizeMode.Fixed)
        view.setMovement(QListView.Movement.Static)
    popup_style = (
        f"""
        QAbstractItemView {{
            background: {colors["panel"]};
            color: {colors["text"]};
            border: none;
            border-radius: {POPUP_BORDER_RADIUS}px;
            padding: 0px;
            selection-background-color: {colors["accent"]};
            selection-color: #ffffff;
        }}
        QAbstractItemView::item {{
            min-height: {fallback_height}px;
            padding: 4px 8px;
        }}
        QAbstractItemView::item:selected,
        QAbstractItemView::item:selected:hover,
        QAbstractItemView::item:hover {{
            background: transparent;
        }}
        QAbstractItemView QScrollBar:vertical,
        QAbstractItemView QScrollBar:horizontal,
        QAbstractItemView QScrollBar::handle:vertical,
        QAbstractItemView QScrollBar::handle:horizontal,
        QAbstractItemView QScrollBar::add-line:vertical,
        QAbstractItemView QScrollBar::sub-line:vertical,
        QAbstractItemView QScrollBar::add-line:horizontal,
        QAbstractItemView QScrollBar::sub-line:horizontal,
        QAbstractItemView QScrollBar::add-page:vertical,
        QAbstractItemView QScrollBar::sub-page:vertical,
        QAbstractItemView QScrollBar::add-page:horizontal,
        QAbstractItemView QScrollBar::sub-page:horizontal {{
            {hidden_scrollbar_style}
        }}
        """
    )
    view.setStyleSheet(popup_style)
    for popup in _combo_popup_windows(view):
        try:
            popup.setObjectName("PolishedComboPopupWindow")
            popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            popup.setAutoFillBackground(True)
            popup.setContentsMargins(0, 0, 0, 0)
            popup.setPalette(palette)
            popup.setStyleSheet(
                f"""
                QWidget#PolishedComboPopupWindow {{
                    background: {colors["panel"]};
                    color: {colors["text"]};
                    border: none;
                    border-radius: {POPUP_BORDER_RADIUS}px;
                }}
                QAbstractItemView {{
                    border: none;
                    border-radius: {POPUP_BORDER_RADIUS}px;
                    background: {colors["panel"]};
                    color: {colors["text"]};
                    selection-background-color: {colors["accent"]};
                    selection-color: #ffffff;
                }}
                QAbstractItemView QScrollBar:vertical,
                QAbstractItemView QScrollBar:horizontal,
                QAbstractItemView QScrollBar::handle:vertical,
                QAbstractItemView QScrollBar::handle:horizontal,
                QAbstractItemView QScrollBar::add-line:vertical,
                QAbstractItemView QScrollBar::sub-line:vertical,
                QAbstractItemView QScrollBar::add-line:horizontal,
                QAbstractItemView QScrollBar::sub-line:horizontal,
                QAbstractItemView QScrollBar::add-page:vertical,
                QAbstractItemView QScrollBar::sub-page:vertical,
                QAbstractItemView QScrollBar::add-page:horizontal,
                QAbstractItemView QScrollBar::sub-page:horizontal {{
                    {hidden_scrollbar_style}
                }}
                """
            )
        except RuntimeError:
            continue
    combo.setProperty("comboPopupRowHeight", fallback_height)
    combo.setProperty("comboPopupVisibleRows", visible_count)
    view.setProperty("comboPopupRowHeight", fallback_height)
    view.setProperty("comboPopupPaintedBorder", "true")
    view.setProperty("comboPopupBorderRadius", POPUP_BORDER_RADIUS)
    view.setProperty("comboPopupAccent", colors["accent"])
    view.viewport().setAutoFillBackground(False)
    view.viewport().setStyleSheet("background: transparent; border: none;")
    view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if hasattr(view, "setTextElideMode"):
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        if fully_expanded
        else Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    view.setProperty("comboPopupFullExpand", "true" if fully_expanded else "false")
    scroll_bar = view.verticalScrollBar()
    if fully_expanded:
        scroll_bar.setRange(0, 0)
        scroll_bar.setValue(0)
        scroll_bar.setEnabled(False)
        scroll_bar.setFixedWidth(0)
        scroll_bar.hide()
        horizontal_scroll_bar = view.horizontalScrollBar()
        horizontal_scroll_bar.setRange(0, 0)
        horizontal_scroll_bar.setValue(0)
        horizontal_scroll_bar.setEnabled(False)
        horizontal_scroll_bar.setFixedHeight(0)
        horizontal_scroll_bar.hide()
    else:
        scroll_bar.setMinimumWidth(0)
        scroll_bar.setMaximumWidth(16777215)
        scroll_bar.setEnabled(True)
        horizontal_scroll_bar = view.horizontalScrollBar()
        horizontal_scroll_bar.setMinimumHeight(0)
        horizontal_scroll_bar.setMaximumHeight(16777215)
        horizontal_scroll_bar.setEnabled(True)
    if not isinstance(getattr(view, "_combo_popup_event_filter", None), ComboPopupEventFilter):
        popup_filter = ComboPopupEventFilter(view)
        view.installEventFilter(popup_filter)
        view.viewport().installEventFilter(popup_filter)
        view._combo_popup_event_filter = popup_filter
    if not isinstance(view.itemDelegate(), NoFocusItemDelegate):
        delegate = NoFocusItemDelegate(view)
        combo.setItemDelegate(delegate)
        view.setItemDelegate(delegate)
        # 保留 Python 包装对象的强引用，否则 Qt 绘制时 delegate 可能已被回收。
        combo._no_focus_item_delegate = delegate
        view._no_focus_item_delegate = delegate
    if hasattr(view, "setUniformItemSizes"):
        view.setUniformItemSizes(True)
    combo.setMaxVisibleItems(visible_count)
    widest_item = max(
        (
            view.fontMetrics().horizontalAdvance(combo.itemText(index))
            + (36 if not combo.itemIcon(index).isNull() else 0)
            + 18
            for index in range(combo.count())
        ),
        default=combo.width(),
    )
    target_width = max(combo.width(), combo.minimumWidth(), min(640, widest_item))
    try:
        max_width = int(combo.property("comboPopupMaxWidth") or 0)
    except (TypeError, ValueError):
        max_width = 0
    if max_width > 0:
        target_width = min(target_width, max(combo.width(), combo.minimumWidth(), max_width))
    if _bool_property(combo, "comboPopupClampToControl") and combo.width() > 0:
        target_width = combo.width()
    view.setProperty("comboPopupTargetWidth", target_width)
    view.setMinimumWidth(target_width)
    view.setMaximumWidth(target_width)
    for popup in _combo_popup_windows(view):
        _lock_popup_widget(popup, target_width)
    actual_row_height = fallback_height
    if combo.count() > 0:
        try:
            actual_row_height = max(fallback_height, int(view.sizeHintForRow(0) or 0))
        except (TypeError, ValueError, RuntimeError):
            actual_row_height = fallback_height
    combo.setProperty("comboPopupRowHeight", actual_row_height)
    combo.setProperty("comboPopupVisibleRows", visible_count)
    view.setProperty("comboPopupRowHeight", actual_row_height)
    if isinstance(view, QListView):
        view.setGridSize(QSize(target_width, actual_row_height))

    current = combo.currentIndex()
    if current >= 0:
        model_index = combo.model().index(current, 0)
        view.setCurrentIndex(model_index)
        selection_model = view.selectionModel()
        if selection_model is not None:
            selection_model.select(
                model_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
            )
        if fully_expanded:
            scroll_bar.setValue(0)
        else:
            view.scrollTo(view.currentIndex(), QAbstractItemView.ScrollHint.PositionAtCenter)

    popup_height = actual_row_height * visible_count
    view.setProperty("comboPopupTargetHeight", popup_height)
    view.setMinimumHeight(popup_height)
    view.setMaximumHeight(popup_height)
    popup_filter = getattr(view, "_combo_popup_event_filter", None)
    for popup in _combo_popup_windows(view):
        if isinstance(popup_filter, ComboPopupEventFilter):
            try:
                if getattr(popup, "_combo_popup_event_filter", None) is not popup_filter:
                    popup.installEventFilter(popup_filter)
                    popup._combo_popup_event_filter = popup_filter
                popup._combo_popup_view = view
            except RuntimeError:
                pass
        _lock_popup_widget(popup, target_width, popup_height)
    if isinstance(popup_filter, ComboPopupEventFilter):
        popup_filter._schedule_popup_lock(force=True)


def schedule_combo_popup_repolish(combo: QComboBox) -> None:
    """等待 Qt/Windows 完成本地弹层布局后，分阶段重校 geometry。"""
    combo_ref = weakref.ref(combo)
    for delay in (0, 30, 90, 180, 360):
        QTimer.singleShot(delay, lambda combo_ref=combo_ref: _repolish_combo_popup_later(combo_ref))


def _repolish_combo_popup_later(combo_ref: weakref.ReferenceType[QComboBox]) -> None:
    combo = combo_ref()
    if not _qt_object_alive(combo) or not isinstance(combo, QComboBox):
        return
    if combo.property("popupOpen") == "false":
        return
    try:
        if not combo.isVisible() or not combo.window().isVisible():
            return
    except RuntimeError:
        return
    view = combo.view()
    if not _qt_object_alive(view):
        return
    popup = view.window()
    if not _qt_object_alive(popup) or not popup.isVisible():
        return
    try:
        if not (popup.windowFlags() & Qt.WindowType.Popup):
            popup.hide()
            combo.setProperty("popupOpen", "false")
            return
    except RuntimeError:
        return
    visible_rows = _int_property(combo, "comboPopupVisibleRows") or max(1, min(combo.count() or 1, FULL_EXPAND_ROW_LIMIT))
    row_height = _int_property(combo, "comboPopupRowHeight") or _int_property(view, "comboPopupRowHeight") or DEFAULT_ROW_HEIGHT
    polish_combo_popup(combo, visible_rows=visible_rows, row_height=row_height)


class PolishedComboBox(QComboBox):
    """弹层行对齐且不绘制原生焦点框的 QComboBox。"""

    def showPopup(self) -> None:  # noqa: N802
        polish_combo_popup(self)
        super().showPopup()
        polish_combo_popup(self)
        schedule_combo_popup_repolish(self)


class ThemedComboBox(PolishedComboBox):
    """统一遵循主题与弹层策略的共享下拉框。"""

    def __init__(self, parent=None, *, row_height: int = DEFAULT_ROW_HEIGHT) -> None:
        super().__init__(parent)
        self._themed_row_height = int(row_height or DEFAULT_ROW_HEIGHT)
        apply_themed_combo_box(self, row_height=self._themed_row_height)

    def showPopup(self) -> None:  # noqa: N802
        apply_themed_combo_box(self, row_height=self._themed_row_height)
        self.setProperty("popupOpen", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        super().showPopup()

    def hidePopup(self) -> None:  # noqa: N802
        super().hidePopup()
        self.setProperty("popupOpen", "false")
        self.style().unpolish(self)
        self.style().polish(self)
