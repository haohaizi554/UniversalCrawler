from app.ui.styles.settings_page import generate_settings_page_stylesheet


def _colors():
    return {
        "text": "#111111",
        "muted": "#666666",
        "success": "#22c55e",
        "danger": "#ef4444",
        "warning": "#f59e0b",
        "panel": "#ffffff",
        "panel_soft": "#f8fafc",
        "border": "#d7dde8",
        "border_strong": "#94a3b8",
        "accent": "#7c3aed",
        "accent_soft": "#ede9fe",
        "accent_hover": "#6d28d9",
        "input": "#ffffff",
        "row_selected": "#e0e7ff",
        "scrollbar": "#cbd5e1",
        "scrollbar_hover": "#94a3b8",
    }


def test_settings_page_stylesheet_contains_core_selectors_and_theme_values():
    qss = generate_settings_page_stylesheet(
        _colors(),
        page_title_px=22,
        detail_title_px=19,
        card_title_px=16,
        body_px=13,
        small_px=12,
        combo_px=13,
        inline_button_px=14,
    )

    assert "QWidget#SettingsPage" in qss
    assert "QComboBox#SettingsCombo" in qss
    assert "QLineEdit#SettingsProxyCustomEdit[customProxyActive=\"true\"]" in qss
    assert "QToolButton#SettingsPathBrowse:hover" in qss
    assert "border: 1px solid #7c3aed" in qss
    assert "border-color: #7c3aed" in qss
    assert "font-size: 22px" in qss
