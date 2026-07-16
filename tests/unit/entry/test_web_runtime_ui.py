"""Web 入口端口对话框与托盘组件的离屏 Qt 行为测试。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _disable_entry_branding(monkeypatch: pytest.MonkeyPatch) -> None:
    from entry import web_port_dialog

    monkeypatch.setattr(web_port_dialog, "load_qt_icon", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        web_port_dialog,
        "ensure_windows_app_user_model_id",
        lambda *_args, **_kwargs: None,
    )


def test_port_dialog_returns_default_without_constructing_conflict_dialog(
    qt_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from entry.web_port_dialog import resolve_port_with_dialog

    _disable_entry_branding(monkeypatch)
    probes: list[tuple[str, int]] = []

    result = resolve_port_with_dialog(
        8000,
        is_port_in_use=lambda host, port: probes.append((host, port)) or False,
        port_probe_range=5,
    )

    assert result == 8000
    assert probes == [("0.0.0.0", 8000)]


def test_port_dialog_accepts_first_suggested_available_port(
    qt_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PyQt6.QtWidgets import QDialog

    from entry.web_port_dialog import resolve_port_with_dialog

    _disable_entry_branding(monkeypatch)
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    probes: list[int] = []

    def is_port_in_use(_host: str, port: int) -> bool:
        probes.append(port)
        return port == 8000

    assert resolve_port_with_dialog(
        8000,
        is_port_in_use=is_port_in_use,
        port_probe_range=3,
    ) == 8001
    assert probes == [8000, 8001, 8001]


def test_port_dialog_cancel_exits_without_starting_server(
    qt_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PyQt6.QtWidgets import QDialog

    from entry.web_port_dialog import resolve_port_with_dialog

    _disable_entry_branding(monkeypatch)
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.DialogCode.Rejected)

    with pytest.raises(SystemExit) as exc_info:
        resolve_port_with_dialog(
            8000,
            is_port_in_use=lambda _host, port: port == 8000,
            port_probe_range=2,
        )

    assert exc_info.value.code == 0


def test_tray_menu_opens_browser_and_signals_shutdown(
    qt_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PyQt6.QtWidgets import QSystemTrayIcon

    from entry import web_tray_ui

    project_root = Path(__file__).resolve().parents[3]
    opened: list[str] = []
    shutdown_event = Mock()
    monkeypatch.setattr(web_tray_ui, "resolve_icon_path", lambda *_args, **_kwargs: project_root / "Web.ico")
    monkeypatch.setattr(web_tray_ui.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda _tray: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *_args, **_kwargs: None)

    tray = web_tray_ui.create_tray_icon(qt_app, "http://127.0.0.1:8000", shutdown_event)
    actions = [action for action in tray.contextMenu().actions() if not action.isSeparator()]
    actions[0].trigger()
    actions[1].trigger()
    tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)

    assert tray.toolTip() == "UCrawl Web - http://127.0.0.1:8000"
    assert opened == ["http://127.0.0.1:8000", "http://127.0.0.1:8000"]
    shutdown_event.set.assert_called_once_with()
    tray.deleteLater()
