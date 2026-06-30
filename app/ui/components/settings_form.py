from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components.settings_controls import UiSwitch


@dataclass(frozen=True)
class SettingsFormBuilder:
    translate: Callable[[str], str]
    scaled_px: Callable[..., int]
    content_card_width: Callable[[], int]
    effective_control_width: Callable[[int], int]
    safe_icon_pixmap: Callable[[str, int], QPixmap | None]
    fallback_group_icon_text: Callable[[str], str]
    fallback_detail_icon_style: Callable[[], str]
    group_icons: dict[str, str]
    group_descriptions: dict[str, str]
    default_group_descriptions: dict[str, str]
    group_hints: dict[str, str]
    setting_short_descriptions: dict[str, str]
    setting_descriptions: dict[str, str]
    switch_wrap_width: int

    def build_form_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SettingsFormCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedWidth(self.content_card_width())

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        return card, layout

    def build_group_hint_card(self, group_name: str) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingsHintCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedWidth(self.content_card_width())
        card.setFixedHeight(40)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        icon = QLabel("i")
        icon.setObjectName("SettingsHintIcon")
        icon.setFixedSize(20, 20)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        raw_text = self.group_hints.get(group_name, "")
        text = QLabel(self.translate(raw_text))
        text.setObjectName("SettingsHintText")
        text.setWordWrap(False)
        text.setToolTip(self.translate(raw_text))
        text.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(icon)
        layout.addWidget(text, 1)
        return card

    def build_detail_header(self, group_name: str) -> QWidget:
        row = QWidget()
        row.setObjectName("SettingsDetailHeader")
        row.setFixedHeight(58)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setObjectName("SettingsDetailIcon")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_file = self.group_icons.get(group_name, "nav_settings.png")
        pixmap = self.safe_icon_pixmap(icon_file, 22)
        if pixmap is not None and not pixmap.isNull():
            icon.setPixmap(pixmap)
        else:
            icon.setText(self.fallback_group_icon_text(group_name))
            icon.setStyleSheet(self.fallback_detail_icon_style())

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel(self.translate(group_name))
        title.setObjectName("SettingsDetailTitle")

        subtitle_text = self.group_descriptions.get(group_name, "") or self.default_group_descriptions.get(group_name, "")
        subtitle = QLabel(self.translate(subtitle_text))
        subtitle.setObjectName("SettingsDetailSubtitle")
        subtitle.setWordWrap(False)
        subtitle.setToolTip(self.translate(subtitle_text))
        subtitle.setMinimumWidth(0)

        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)

        layout.addWidget(icon)
        layout.addWidget(text_box, 1)
        return row

    def build_setting_row(
        self,
        label: str,
        control: QWidget,
        *,
        control_width: int,
        compact: bool = False,
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("SettingsSettingRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setFixedHeight(self.scaled_px(56 if compact else 60, minimum=56 if compact else 60))

        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(18)

        text_box = QWidget()
        text_box.setObjectName("SettingsItemTextBox")
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel(self.translate(label))
        title.setObjectName("SettingsItemTitle")
        title.setWordWrap(False)
        title.setFixedHeight(20)

        short_desc = self.setting_short_descriptions.get(label, "")
        long_desc = self.setting_descriptions.get(label, short_desc)
        title.setToolTip(self.translate(long_desc))
        row.setToolTip(self.translate(long_desc))

        text_layout.addWidget(title)
        if short_desc:
            desc = QLabel(self.translate(short_desc))
            desc.setObjectName("SettingsItemDescription")
            desc.setWordWrap(False)
            desc.setFixedHeight(18)
            desc.setToolTip(self.translate(long_desc))
            text_layout.addWidget(desc)

        control_wrap = QWidget()
        control_wrap.setObjectName("SettingsControlWrap")
        control_layout = QHBoxLayout(control_wrap)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)

        self._apply_control_height(control)
        if isinstance(control, UiSwitch):
            control_layout.addStretch(1)
            control_layout.addWidget(control)
            control_wrap.setFixedWidth(self.switch_wrap_width)
        else:
            effective_width = self.effective_control_width(control_width)
            control.setFixedWidth(effective_width)
            control_layout.addWidget(control)
            control_wrap.setFixedWidth(effective_width)

        layout.addWidget(text_box, 1)
        layout.addWidget(control_wrap, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    @staticmethod
    def _apply_control_height(control: QWidget) -> None:
        custom_control_height = control.property("settingsControlHeight")
        try:
            control_height = int(custom_control_height) if custom_control_height is not None else 0
        except (TypeError, ValueError):
            control_height = 0
        if control_height > 0:
            control.setMinimumHeight(control_height)
            control.setMaximumHeight(control_height)
        else:
            control.setMinimumHeight(36)
            control.setMaximumHeight(38)
