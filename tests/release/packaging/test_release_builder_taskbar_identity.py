from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from app.utils.qt_runtime import (  # noqa: E402
    MAIN_APP_USER_MODEL_ID,
    RELEASE_BUILDER_APP_USER_MODEL_ID,
)
from release_tool import panel as panel_module  # noqa: E402


class _FakeSignal:
    def connect(self, callback) -> None:
        self.callback = callback

    def emit(self) -> None:
        self.callback()


def test_release_builder_uses_a_dedicated_windows_taskbar_identity():
    assert RELEASE_BUILDER_APP_USER_MODEL_ID
    assert RELEASE_BUILDER_APP_USER_MODEL_ID != MAIN_APP_USER_MODEL_ID


def test_launch_rebinds_reused_application_before_creating_release_window(
    monkeypatch,
):
    events: list[object] = []
    icon = object()

    class ExistingApplication:
        def setApplicationName(self, value: str) -> None:
            events.append(("application_name", value))

        def setOrganizationName(self, value: str) -> None:
            events.append(("organization_name", value))

        def setWindowIcon(self, value: object) -> None:
            events.append(("application_icon", value))

        def exec(self):
            raise AssertionError("existing QApplication event loop must not be re-entered")

    existing = ExistingApplication()

    class ApplicationFacade:
        @staticmethod
        def instance():
            return existing

    class FakeWindow:
        def __init__(self) -> None:
            events.append("window_created")
            self.destroyed = _FakeSignal()

        def show(self) -> None:
            events.append("window_shown")

        def setAttribute(self, attribute, enabled) -> None:
            assert attribute == Qt.WidgetAttribute.WA_DeleteOnClose
            assert enabled is True

    monkeypatch.setattr(panel_module, "QApplication", ApplicationFacade)
    monkeypatch.setattr(panel_module, "QIcon", lambda _path: icon)
    monkeypatch.setattr(
        panel_module,
        "release_builder_icon_path",
        lambda: Path("release-builder.ico"),
    )
    monkeypatch.setattr(panel_module, "ReleaseBuilderWindow", FakeWindow)
    monkeypatch.setattr(
        panel_module,
        "ensure_windows_app_user_model_id",
        lambda value: events.append(("app_user_model_id", value)),
    )

    assert panel_module.launch_release_builder_panel() == 0
    assert events[0] == (
        "app_user_model_id",
        RELEASE_BUILDER_APP_USER_MODEL_ID,
    )
    assert ("application_icon", icon) in events
    assert events.index(("application_icon", icon)) < events.index("window_created")
    assert events.index("window_created") < events.index("window_shown")

    fake_window = panel_module._LAUNCHED_WINDOWS.popitem()[1]
    fake_window.destroyed.emit()
    panel_module._LAUNCHED_WINDOWS.clear()
