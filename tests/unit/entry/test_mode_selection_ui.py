from pathlib import Path

from entry import mode_selection_ui


def test_mode_selection_dialog_minimum_stays_inside_available_geometry():
    assert mode_selection_ui._viewport_safe_dialog_minimum(1093, 614) == (720, 582)
    assert mode_selection_ui._viewport_safe_dialog_minimum(400, 300) == (368, 268)


def test_packaged_qt_panel_hides_source_only_cards(monkeypatch):
    monkeypatch.setattr(mode_selection_ui.sys, "frozen", True, raising=False)

    modes = {spec[1] for spec in mode_selection_ui._visible_qt_mode_specs()}

    assert mode_selection_ui.Mode.TEST not in modes
    assert mode_selection_ui.Mode.REPORT not in modes
    assert mode_selection_ui.Mode.RELEASE not in modes
    assert modes == {
        mode_selection_ui.Mode.GUI,
        mode_selection_ui.Mode.WEB,
        mode_selection_ui.Mode.INTERACTIVE,
        mode_selection_ui.Mode.CLI,
    }


def test_source_qt_panel_exposes_release_builder_card(monkeypatch):
    monkeypatch.setattr(mode_selection_ui.sys, "frozen", False, raising=False)

    specs = {
        spec[1]: spec
        for spec in mode_selection_ui._visible_qt_mode_specs()
    }

    assert specs[mode_selection_ui.Mode.RELEASE][2:6] == (
        "7",
        "发布构建工具",
        "构建安装包、签名清单并按需发布热更新资产",
        "开发",
    )


def test_mode_cards_use_button_semantics_and_non_scrolling_single_column():
    source = Path(mode_selection_ui.__file__).read_text(encoding="utf-8")

    assert "class ModeCardButton(QPushButton)" in source
    assert "Qt.Key.Key_Return" in source
    assert "Qt.Key.Key_Enter" in source
    assert "setAccessibleName" in source
    assert "QScrollArea" not in source
    assert "body.addWidget(card, 1)" in source
    assert "card.setMinimumHeight(52)" in source
    assert "desc_label.setWordWrap(True)" in source
    assert ".clicked.connect" in source
    assert "card.mousePressEvent =" not in source
    assert "dialog.setMinimumSize(QSize(720, 720))" not in source


def test_stdio_modes_explain_that_they_open_an_independent_console():
    source = Path(mode_selection_ui.__file__).read_text(encoding="utf-8")

    assert "独立终端" in source
    assert "命令行终端" in source
    assert "查看用法后可继续输入命令" in source
