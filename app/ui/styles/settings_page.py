from __future__ import annotations

from collections.abc import Mapping


def generate_settings_page_stylesheet(
    colors: Mapping[str, str],
    *,
    page_title_px: int,
    detail_title_px: int,
    card_title_px: int,
    body_px: int,
    small_px: int,
    combo_px: int,
    inline_button_px: int,
) -> str:
    c = colors
    return f"""
            QWidget#SettingsPage {{
                background: transparent;
            }}

            QLabel#SettingsPageTitle {{
                color: {c["text"]};
                font-size: {page_title_px}px;
                font-weight: 800;
                padding: 0px;
            }}

            QLabel#SettingsPageSubtitle {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 500;
            }}

            QLabel#SettingsActionFeedback {{
                color: {c["success"]};
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                padding: 3px 10px;
                font-size: {small_px}px;
                font-weight: 600;
            }}

            QLabel#SettingsActionFeedback[status="error"] {{
                color: {c["danger"]};
            }}

            QFrame#SettingsMainPanel {{
                background: transparent;
                border: none;
            }}

            QFrame#SettingsSideNav {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 14px;
            }}

            QFrame#SettingsDetailPanel {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 14px;
            }}

            QPushButton#SettingsNavButton {{
                text-align: left;
                padding-left: 10px;
                padding-right: 10px;
                border: 1px solid transparent;
                border-radius: 9px;
                background: transparent;
                color: {c["text"]};
                font-size: {body_px}px;
                font-weight: 600;
            }}

            QPushButton#SettingsNavButton:hover {{
                background: {c["panel_soft"]};
                border-color: {c["border"]};
            }}

            QPushButton#SettingsNavButton:checked,
            QPushButton#SettingsNavButton[active="true"] {{
                background: {c["accent_soft"]};
                color: {c["accent"]};
                border-left: 3px solid {c["accent"]};
                font-weight: 800;
            }}

            QLabel#SettingsNavTitle {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 700;
                padding-left: 8px;
            }}

            QLabel#SettingsDetailTitle {{
                color: {c["text"]};
                font-size: {detail_title_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsDetailSubtitle {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 500;
            }}

            QLabel#SettingsDetailIcon {{
                background: {c["accent_soft"]};
                border-radius: 16px;
            }}

            QFrame#SettingsFormCard {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 12px;
            }}

            QFrame#SettingsSettingRow {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QFrame#SettingsSettingRow:hover {{
                border-color: {c["border_strong"]};
                background: {c["input"]};
            }}

            QLabel#SettingsItemTitle {{
                color: {c["text"]};
                font-size: {body_px}px;
                font-weight: 700;
            }}

            QLabel#SettingsItemDescription {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 400;
            }}

            QFrame#SettingsHintCard {{
                background: {c["accent_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QLabel#SettingsHintIcon {{
                background: {c["accent"]};
                color: #ffffff;
                border-radius: 10px;
                font-size: {small_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsHintText {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 500;
            }}

            QFrame#SettingsPlatformTablePanel {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 11px;
            }}

            QFrame#SettingsPlatformSummaryBar {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 11px;
            }}

            QFrame#SettingsPlatformSummaryChip {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 15px;
            }}

            QFrame#SettingsPlatformSummaryChip[kind="success"] {{
                background: rgba(34, 197, 94, 0.10);
                border: 1px solid rgba(34, 197, 94, 0.24);
            }}

            QFrame#SettingsPlatformSummaryChip[kind="warning"] {{
                background: rgba(245, 158, 11, 0.10);
                border: 1px solid rgba(245, 158, 11, 0.24);
            }}

            QFrame#SettingsPlatformSummaryChip[kind="accent"] {{
                background: {c["accent_soft"]};
                border: 1px solid {c["border"]};
            }}

            QLabel#SettingsPlatformSummaryLabel {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 600;
            }}

            QLabel#SettingsPlatformSummaryValue {{
                color: {c["text"]};
                font-size: {body_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsPlatformSummaryValue[kind="success"] {{
                color: {c["success"]};
            }}

            QLabel#SettingsPlatformSummaryValue[kind="warning"] {{
                color: {c["warning"]};
            }}

            QLabel#SettingsPlatformSummaryValue[kind="accent"] {{
                color: {c["accent"]};
            }}

            QFrame#SettingsCard {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 14px;
            }}

            QFrame#SettingsCardDivider {{
                background: {c["border"]};
                border: none;
                margin-top: 2px;
                margin-bottom: 8px;
            }}

            QLabel#SettingsCardTitle {{
                color: {c["text"]};
                font-size: {card_title_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsCardIcon {{
                background: transparent;
            }}

            QLabel#SettingsRowLabel {{
                color: {c["muted"]};
                font-size: {body_px}px;
                font-weight: 500;
            }}

            QLabel#SettingsPlatformHeaderCell {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 800;
            }}

            QWidget#SettingsPlatformHeader {{
                background: {c["panel_soft"]};
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }}

            QLabel#SettingsPlatformName {{
                color: {c["text"]};
                font-size: {body_px}px;
            }}

            QLabel#SettingsAuthBadge[authenticated="true"] {{
                color: {c["success"]};
                background: rgba(34, 197, 94, 0.14);
                border: 1px solid rgba(34, 197, 94, 0.32);
                border-radius: 14px;
                font-size: {small_px}px;
                font-weight: 800;
                padding: 0px 8px;
            }}

            QLabel#SettingsAuthBadge[authenticated="false"] {{
                color: {c["warning"]};
                background: rgba(245, 158, 11, 0.14);
                border: 1px solid rgba(245, 158, 11, 0.32);
                border-radius: 14px;
                font-size: {small_px}px;
                font-weight: 800;
                padding: 0px 8px;
            }}

            QFrame#SettingsPathField {{
                background: {c["input"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QLineEdit#SettingsLineEdit {{
                background: transparent;
                border: none;
                color: {c["text"]};
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
                font-size: {body_px}px;
                padding: 0px;
            }}

            QLineEdit#SettingsProxyCustomEdit {{
                background: {c["input"]};
                border: 1px solid {c["border_strong"]};
                border-radius: 8px;
                color: {c["text"]};
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
                font-size: {combo_px}px;
                min-height: 40px;
                max-height: 40px;
                padding: 0px 10px;
            }}

            QLineEdit#SettingsProxyCustomEdit[customProxyActive="true"] {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
            }}

            QLineEdit#SettingsProxyCustomEdit:disabled {{
                color: {c["muted"]};
                background: {c["panel_soft"]};
                border-color: {c["border"]};
            }}

            QToolButton#SettingsPathBrowse {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                padding: 5px;
            }}

            QToolButton#SettingsPathBrowse:hover {{
                background: {c["accent_soft"]};
                border-color: {c["accent"]};
            }}

            QToolButton#SettingsPathBrowse:pressed {{
                background: {c["row_selected"]};
                border-color: {c["accent_hover"]};
            }}

            QToolButton#SettingsInlineButton {{
                background: transparent;
                border: none;
                color: {c["muted"]};
                font-size: {inline_button_px}px;
                font-weight: 700;
            }}

            QToolButton#SettingsInlineButton:hover {{
                color: {c["accent"]};
            }}

            QComboBox#SettingsCombo {{
                background: {c["input"]};
                border: 1px solid {c["border_strong"]};
                border-radius: 8px;
                color: {c["text"]};
                font-size: {combo_px}px;
                padding: 0px 10px 0px 12px;
                min-height: 38px;
                max-height: 40px;
            }}

            QComboBox#SettingsCombo:hover {{
                border-color: {c["accent"]};
                background: {c["input"]};
            }}

            QFrame#SettingsPathField:hover {{
                border-color: {c["border_strong"]};
            }}

            QFrame#SettingsPathField[focused="true"] {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
            }}

            QComboBox#SettingsCombo:focus {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
            }}

            QComboBox#SettingsCombo:on,
            QComboBox#SettingsCombo[popupOpen="true"],
            QComboBox#SettingsCombo[customProxy="true"] {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
                color: {c["text"]};
            }}

            QComboBox#SettingsCombo QLineEdit {{
                background: transparent;
                border: none;
                color: {c["text"]};
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
                padding: 0px 4px 0px 0px;
            }}

            QComboBox#SettingsCombo QLineEdit:read-only {{
                color: {c["text"]};
            }}

            QComboBox#SettingsCombo:disabled {{
                color: {c["muted"]};
                background: {c["panel_soft"]};
            }}

            QComboBox#SettingsCombo::drop-down {{
                border: none;
                width: 0px;
            }}

            QComboBox#SettingsCombo::down-arrow {{
                image: none;
                width: 0px;
                height: 0px;
            }}

            QComboBox#SettingsCombo QAbstractItemView {{
                background: {c["panel"]};
                color: {c["text"]};
                border: 2px solid {c["accent"]};
                border-radius: 8px;
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
            }}

            QPushButton#SettingsActionButton {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                color: {c["text"]};
                font-size: {small_px}px;
                min-height: 36px;
                max-height: 38px;
                padding: 0px 10px;
            }}

            QPushButton#SettingsActionButton:hover {{
                border-color: {c["accent"]};
                color: {c["accent"]};
            }}

            QWidget#SettingsSegmented {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QPushButton#SettingsSegmentButton {{
                background: transparent;
                border: none;
                color: {c["muted"]};
                font-size: {body_px}px;
                font-weight: 700;
                padding: 0px;
                min-height: 36px;
            }}

            QPushButton#SettingsSegmentButton:checked {{
                background: {c["accent"]};
                color: #ffffff;
                border-radius: 8px;
            }}

            QScrollArea#SettingsPlatformScroll {{
                background: transparent;
                border: none;
            }}

            QScrollArea#SettingsPlatformScroll > QWidget > QWidget {{
                background: transparent;
            }}

            QWidget#SettingsPlatformRow {{
                border-bottom: 1px solid {c["border"]};
                background: {c["panel"]};
            }}

            QWidget#SettingsPlatformRow:hover {{
                background: {c["panel_soft"]};
            }}

            QCheckBox#SettingsUiSwitch {{
                spacing: 0;
                background: transparent;
            }}

            QCheckBox#SettingsUiSwitch::indicator {{
                width: 0px;
                height: 0px;
                border: none;
                background: transparent;
            }}
            """
