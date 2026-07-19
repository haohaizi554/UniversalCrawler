from pathlib import Path

from entry import mode_selection_ui


def test_mode_selection_dialog_minimum_stays_inside_available_geometry():
    assert mode_selection_ui._viewport_safe_dialog_minimum(1093, 614) == (720, 582)
    assert mode_selection_ui._viewport_safe_dialog_minimum(400, 300) == (368, 268)


def test_packaged_qt_panel_hides_test_and_report_cards(monkeypatch):
    monkeypatch.setattr(mode_selection_ui.sys, "frozen", True, raising=False)

    modes = {spec[1] for spec in mode_selection_ui._visible_qt_mode_specs()}

    assert mode_selection_ui.Mode.TEST not in modes
    assert mode_selection_ui.Mode.REPORT not in modes
    assert modes == {
        mode_selection_ui.Mode.GUI,
        mode_selection_ui.Mode.WEB,
        mode_selection_ui.Mode.INTERACTIVE,
        mode_selection_ui.Mode.CLI,
    }


def test_mode_cards_use_button_semantics_focus_activation_and_scroll_container():
    source = Path(mode_selection_ui.__file__).read_text(encoding="utf-8")

    assert "class ModeCardButton(QPushButton)" in source
    assert "Qt.Key.Key_Return" in source
    assert "Qt.Key.Key_Enter" in source
    assert "setAccessibleName" in source
    assert "QScrollArea" in source
    assert ".clicked.connect" in source
    assert "card.mousePressEvent =" not in source
    assert "dialog.setMinimumSize(QSize(720, 720))" not in source


def test_stdio_modes_explain_that_they_open_an_independent_console():
    source = Path(mode_selection_ui.__file__).read_text(encoding="utf-8")

    assert "独立终端" in source
    assert "命令行终端" in source
    assert "查看用法后可继续输入命令" in source
