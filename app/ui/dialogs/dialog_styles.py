from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from app.services.icon_registry import resolve_ui_icon_path


def _dialog_check_icon_url() -> str:
    resolved = resolve_ui_icon_path("status_success.png")
    if resolved is not None:
        return resolved.as_posix()
    return "UI/icon/status_success.png"


def themed_dialog_stylesheet(colors: dict[str, str]) -> str:
    """Scoped QSS for modal dialogs that must not fall back to native widget colors."""
    check_icon_url = _dialog_check_icon_url()
    return f"""
    QDialog {{
        background-color: {colors["bg"]};
        color: {colors["text"]};
    }}
    QFrame#DialogSurface {{
        background-color: {colors["panel"]};
        border: 1px solid {colors["border"]};
        border-radius: 10px;
    }}
    QLabel#DialogTitle {{
        color: {colors["text"]};
        font-weight: 700;
        font-size: 18px;
        background: transparent;
    }}
    QLabel#DialogDescription,
    QLabel#SelectionDialogHeader {{
        color: {colors["muted"]};
        background: transparent;
    }}
    QLabel#DialogBody {{
        color: {colors["text"]};
        background: transparent;
        font-weight: 600;
    }}
    QLabel#DialogStatus {{
        color: {colors["muted"]};
        background: {colors["panel_soft"]};
        border: 1px solid {colors["border"]};
        border-radius: 7px;
        padding: 8px 10px;
    }}
    QFrame#UpdateHero {{
        background: transparent;
        border: none;
    }}
    QFrame#UpdateHero QLabel#DialogBody {{
        font-size: 14px;
        font-weight: 700;
    }}
    QLabel#UpdateStatusBadge {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 10px;
        font-size: 12px;
        font-weight: 700;
        background: {colors["panel_soft"]};
        color: {colors["muted"]};
        border: 1px solid {colors["border"]};
    }}
    QLabel#UpdateStatusBadge[tone="success"] {{
        color: {colors["success"]};
        background: {colors["panel_soft"]};
        border-color: {colors["success"]};
    }}
    QLabel#UpdateStatusBadge[tone="accent"] {{
        color: {colors["accent"]};
        background: {colors["accent_soft"]};
        border-color: {colors["accent"]};
    }}
    QLabel#UpdateStatusBadge[tone="warning"] {{
        color: {colors["warning"]};
        background: {colors["panel_soft"]};
        border-color: {colors["warning"]};
    }}
    QLabel#UpdateStatusBadge[tone="danger"] {{
        color: {colors["danger"]};
        background: {colors["panel_soft"]};
        border-color: {colors["danger"]};
    }}
    QFrame#UpdateVersionPanel {{
        background: {colors["panel"]};
        border: 1px solid {colors["border"]};
        border-radius: 10px;
    }}
    QLabel#UpdateVersionLabel {{
        color: {colors["muted"]};
        background: transparent;
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#UpdateVersionValue {{
        color: {colors["text"]};
        background: transparent;
        font-size: 16px;
        font-weight: 800;
    }}
    QLabel#UpdateVersionValue[tone="success"] {{
        color: {colors["success"]};
    }}
    QLabel#UpdateVersionValue[tone="accent"] {{
        color: {colors["accent"]};
    }}
    QLabel#UpdateVersionValue[tone="warning"] {{
        color: {colors["warning"]};
    }}
    QLabel#UpdateVersionValue[tone="danger"] {{
        color: {colors["danger"]};
    }}
    QLabel#UpdateVersionArrow {{
        color: {colors["muted"]};
        background: transparent;
        font-size: 18px;
        font-weight: 700;
    }}
    QFrame#UpdateDetailCard {{
        background: {colors["panel_soft"]};
        border: 1px solid {colors["border"]};
        border-radius: 10px;
    }}
    QFrame#UpdateDetailCard QLabel#DialogStatus {{
        color: {colors["muted"]};
        background: transparent;
        border: none;
        padding: 0;
    }}
    QLabel#UpdateDetailTitle {{
        color: {colors["text"]};
        background: transparent;
        font-weight: 700;
        font-size: 13px;
    }}
    QLabel#UpdateReleaseLink {{
        color: {colors["accent"]};
        background: transparent;
        font-weight: 700;
    }}
    QLabel#UpdateReleaseLink:hover {{
        color: {colors["accent_hover"]};
    }}
    QTableWidget#SelectionTable {{
        background-color: {colors["panel"]};
        alternate-background-color: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
        gridline-color: {colors["border"]};
        selection-background-color: {colors["row_selected"]};
        selection-color: {colors["text"]};
    }}
    QTableWidget#SelectionTable::item {{
        border-bottom: 1px solid {colors["border"]};
        padding: 0 8px;
    }}
    QTableWidget#SelectionTable::item:selected {{
        background-color: {colors["row_selected"]};
        color: {colors["text"]};
    }}
    QTableWidget#SelectionTable QHeaderView::section {{
        background-color: {colors["panel_soft"]};
        color: {colors["text"]};
        border: none;
        border-bottom: 1px solid {colors["border"]};
        padding: 0 8px;
        font-weight: 700;
    }}
    QScrollBar:vertical {{
        background: {colors["panel_soft"]};
        width: 10px;
        margin: 0px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {colors["border_strong"]};
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {colors["accent"]};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
        border: none;
        background: transparent;
    }}
    QCheckBox#DialogCheckBox {{
        color: {colors["text"]};
        background: transparent;
        spacing: 10px;
        min-height: 34px;
    }}
    QCheckBox#DialogCheckBox::indicator {{
        width: 22px;
        height: 22px;
        border-radius: 7px;
        border: 2px solid {colors["border_strong"]};
        background-color: {colors["input"]};
    }}
    QCheckBox#DialogCheckBox::indicator:hover {{
        border-color: {colors["accent"]};
        background-color: {colors["panel_soft"]};
    }}
    QCheckBox#DialogCheckBox::indicator:checked {{
        background-color: {colors["accent"]};
        border-color: {colors["accent"]};
        image: url("{check_icon_url}");
    }}
    QWidget#DialogOptionRow {{
        background: transparent;
        color: {colors["text"]};
        min-height: 34px;
    }}
    QLabel#DialogOptionLabel {{
        color: {colors["text"]};
        background: transparent;
    }}
    QPushButton#DialogPrimaryButton,
    QPushButton#PrimaryBtn {{
        min-height: 36px;
        background-color: {colors["accent"]};
        border: 1px solid {colors["accent"]};
        border-radius: 8px;
        color: #ffffff;
        font-weight: 700;
        padding: 0 18px;
    }}
    QPushButton#DialogPrimaryButton:hover:enabled,
    QPushButton#PrimaryBtn:hover:enabled {{
        background-color: {colors["accent_hover"]};
        border-color: {colors["accent_hover"]};
    }}
    QPushButton#DialogNeutralButton,
    QPushButton#SelectionActionBtn,
    QPushButton#DangerBtn {{
        min-height: 36px;
        background-color: {colors["panel"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
        color: {colors["text"]};
        font-weight: 700;
        padding: 0 18px;
    }}
    QPushButton#DialogNeutralButton:hover:enabled,
    QPushButton#SelectionActionBtn:hover:enabled,
    QPushButton#DangerBtn:hover:enabled {{
        background-color: {colors["panel_soft"]};
        border-color: {colors["accent"]};
        color: {colors["accent"]};
    }}
    """


def apply_themed_dialog_styles(widget: QWidget, colors: dict[str, str]) -> None:
    widget.setStyleSheet(themed_dialog_stylesheet(colors))
