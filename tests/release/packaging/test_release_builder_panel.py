from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtCore import QObject, QProcess, QRect, Qt, pyqtSignal
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QScrollArea

from tests.support.paths import PROJECT_ROOT


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))

from app.ui.dialogs.chromed_dialog import ChromedDialog
from app.ui.components.combo_popup import ThemedComboBox
from app.ui.layout.window_chrome import WindowChromeFrame
from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
from release_tool.events import EVENT_PREFIX
from release_tool.models import (
    BuildRequest,
    ReleaseMode,
    ReleaseResult,
    ReleaseStage,
    RemoteReleaseInfo,
)
from release_tool import panel as panel_module
from release_tool import process_controller as process_controller_module
from release_tool.panel import (
    ReleaseBuilderWindow,
    build_confirmation_summary,
)
from release_tool.panel_policy import PanelBuildIntent
from release_tool.process_controller import (
    ReleaseProcessController,
    _BackgroundLogWriter,
)
from release_tool.proxy import PROXY_ENVIRONMENT_VARIABLES, ProxySelection


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeProcess(QObject):
    readyReadStandardOutput = pyqtSignal()
    readyReadStandardError = pyqtSignal()
    finished = pyqtSignal(int, QProcess.ExitStatus)
    errorOccurred = pyqtSignal(QProcess.ProcessError)

    def __init__(self) -> None:
        super().__init__()
        self.program = ""
        self.arguments: list[str] = []
        self.environment = None
        self.working_directory = ""
        self.started = False
        self.terminated = False
        self.killed = False
        self._state = QProcess.ProcessState.NotRunning
        self._stdout = b""
        self._stderr = b""
        self._pid = 4242

    def setProgram(self, value: str) -> None:
        self.program = value

    def setArguments(self, value: list[str]) -> None:
        self.arguments = list(value)

    def setProcessEnvironment(self, value) -> None:
        self.environment = value

    def setWorkingDirectory(self, value: str) -> None:
        self.working_directory = value

    def start(self) -> None:
        self.started = True
        self._state = QProcess.ProcessState.Running

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._state = QProcess.ProcessState.NotRunning

    def state(self):
        return self._state

    def processId(self) -> int:
        return self._pid

    def readAllStandardOutput(self) -> bytes:
        value, self._stdout = self._stdout, b""
        return value

    def readAllStandardError(self) -> bytes:
        value, self._stderr = self._stderr, b""
        return value

    def set_stdout(self, value: bytes) -> None:
        self._stdout = value

    def set_stderr(self, value: bytes) -> None:
        self._stderr = value


class FakeQtProcess(QProcess):
    def __init__(self) -> None:
        super().__init__()
        self.program = ""
        self.arguments: list[str] = []
        self.environment = None
        self.working_directory = ""
        self.terminated = False
        self.killed = False
        self._fake_state = QProcess.ProcessState.NotRunning
        self._pid = 4343

    def setProgram(self, value: str) -> None:
        self.program = value

    def setArguments(self, value: list[str]) -> None:
        self.arguments = list(value)

    def setProcessEnvironment(self, value) -> None:
        self.environment = value

    def setWorkingDirectory(self, value: str) -> None:
        self.working_directory = value

    def start(self) -> None:
        self._fake_state = QProcess.ProcessState.Running

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._fake_state = QProcess.ProcessState.NotRunning

    def state(self):
        return self._fake_state

    def processId(self) -> int:
        return self._pid

    def readAllStandardOutput(self) -> bytes:
        return b""

    def readAllStandardError(self) -> bytes:
        return b""


def success_event(sequence: int = 1) -> str:
    payload = {
        "kind": "result",
        "sequence": sequence,
        "timestamp": "2026-07-19T00:00:00Z",
        "stage": "succeeded",
        "progress": 100,
        "message": "",
        "data": {"status": "succeeded"},
    }
    return EVENT_PREFIX + json.dumps(payload)


def stage_event(sequence: int = 1, progress: int = 35) -> str:
    payload = {
        "kind": "stage",
        "sequence": sequence,
        "timestamp": "2026-07-19T00:00:00Z",
        "stage": "building_portable",
        "progress": progress,
        "message": "Building",
        "data": {},
    }
    return EVENT_PREFIX + json.dumps(payload)


def log_event(
    sequence: int = 1,
    progress: int = 35,
    message: str = "packaging output",
) -> str:
    payload = {
        "kind": "log",
        "sequence": sequence,
        "timestamp": "2026-07-19T00:00:00Z",
        "stage": "building_portable",
        "progress": progress,
        "message": message,
        "data": {},
    }
    return EVENT_PREFIX + json.dumps(payload)


def error_event(sequence: int = 1, progress: int = 35) -> str:
    payload = {
        "kind": "error",
        "sequence": sequence,
        "timestamp": "2026-07-19T00:00:00Z",
        "stage": "building_portable",
        "progress": progress,
        "message": "portable build failed",
        "data": {},
    }
    return EVENT_PREFIX + json.dumps(payload)


def pump_until(qapp: QApplication, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert predicate()


def make_request(**changes) -> BuildRequest:
    values = {
        "target_version": "3.6.20",
        "remote": RemoteReleaseInfo.available("3.6.19"),
        "run_smoke_tests": False,
    }
    values.update(changes)
    return BuildRequest(**values)


def make_panel(qapp, **kwargs) -> ReleaseBuilderWindow:
    window = ReleaseBuilderWindow(
        project_version=kwargs.pop("project_version", "3.6.20"),
        remote_loader=kwargs.pop(
            "remote_loader", lambda *_args: RemoteReleaseInfo.available("3.6.21")
        ),
        **kwargs,
    )
    pump_until(qapp, lambda: not window.remote_lookup_active)
    return window


def test_panel_reuses_project_chrome_theme_root_and_safe_defaults(qapp):
    window = ReleaseBuilderWindow(
        project_version="3.6.20",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        assert isinstance(window.chrome_frame, WindowChromeFrame)
        assert isinstance(
            window._window_chrome_controller, FramelessWindowChromeController
        )
        assert window.property("ucpThemeRoot") is True
        assert Path(window.windowIcon().name() or window.icon_path).name == "release-builder.ico"
        assert window.check_sign_manifest.isChecked() is False
        assert window.check_push_main.isChecked() is False
        assert window.check_create_release.isChecked() is False
        assert window.check_upload_assets.isChecked() is False
        assert len(window.section_widgets) == 6
    finally:
        window.shutdown()


def test_title_bar_maximize_action_uses_shared_native_controller_truth(qapp):
    window = make_panel(qapp)
    try:
        window.show()
        qapp.processEvents()
        controller = window._window_chrome_controller
        hwnd = int(window.winId())
        controller._windows_hwnd = hwnd
        controller._is_hwnd_maximized = Mock(side_effect=[False, True])
        controller.set_hwnd_maximized = Mock(return_value=True)

        assert controller._toggle_maximized_callback is None
        assert not hasattr(window, "_toggle_maximized")

        with patch(
            "app.ui.layout.window_chrome_controller.sys.platform",
            "win32",
        ), patch("app.ui.layout.window_chrome_controller.QTimer.singleShot"):
            window.window_title_bar.maximize_restore_requested.emit()

        controller.set_hwnd_maximized.assert_called_once_with(hwnd, True)
        assert window.window_title_bar.btn_maximize._maximized is True
        assert window.window_title_bar.btn_maximize.toolTip() == "还原"

        controller._is_hwnd_maximized = Mock(side_effect=[True, False])
        controller.set_hwnd_maximized.reset_mock()
        with patch(
            "app.ui.layout.window_chrome_controller.sys.platform",
            "win32",
        ), patch("app.ui.layout.window_chrome_controller.QTimer.singleShot"):
            window.window_title_bar.maximize_restore_requested.emit()

        controller.set_hwnd_maximized.assert_called_once_with(hwnd, False)
        assert window.window_title_bar.btn_maximize._maximized is False
        assert window.window_title_bar.btn_maximize.toolTip() == "最大化"
    finally:
        window.shutdown()


def test_panel_canonicalizes_prefixed_version_before_build(qapp):
    window = make_panel(qapp)
    try:
        window.target_version_edit.setText("v3.1.1")

        request = window._request_from_controls()
        summary = build_confirmation_summary(
            request,
            ReleaseMode.LOCAL_REBUILD,
            asset_names=(),
        )

        assert request.target_version == "3.1.1"
        assert "版本：3.1.1" in summary
        assert "Git 标签：v3.1.1" in summary
        assert "vv3.1.1" not in summary
    finally:
        window.shutdown()


def test_release_builder_user_facing_controls_are_chinese(qapp):
    window = make_panel(qapp)
    try:
        assert window.windowTitle() == "UniversalCrawler 发布构建工具"
        assert window.chrome_frame.title_bar.title_label.text() == (
            "UniversalCrawler 发布构建工具"
        )
        assert [section.title() for section in window.section_widgets] == [
            "版本信息",
            "构建选项",
            "签名与信任",
            "代码仓库与发布",
            "网络与代理",
            "执行进度与日志",
        ]
        assert window.refresh_remote_button.text() == "刷新"
        assert window.check_build_portable.text() == "便携版"
        assert window.check_build_installer.text() == "安装包"
        assert window.check_sign_manifest.text() == "签署更新清单"
        assert window.check_upload_assets.text() == "上传资产"
        assert window.start_button.text() == "开始构建"
        assert window.cancel_button.text() == "取消"
        assert window.copy_log_button.text() == "复制选中内容"
        assert window.export_log_button.text() == "导出日志副本"
        assert window.clear_log_button.text() == "清空显示"
        assert window.open_log_directory_button.text() == "打开日志目录"
        assert (
            window.open_installer_directory_button.text()
            == "打开安装包目录"
        )
        assert window.mode_badge.text() == "本地调试"
    finally:
        window.shutdown()


def test_release_notes_path_follows_target_version_and_clears_without_match(
    qapp,
    tmp_path,
):
    notes_directory = tmp_path / "docs" / "releases"
    notes_directory.mkdir(parents=True)
    first_notes = notes_directory / "v3.6.20.md"
    second_notes = notes_directory / "v3.6.21.md"
    first_notes.write_text("# v3.6.20", encoding="utf-8")
    second_notes.write_text("# v3.6.21", encoding="utf-8")
    window = make_panel(
        qapp,
        project_root=tmp_path,
        project_version="3.6.20",
    )
    try:
        assert window.notes_edit.text() == str(first_notes.resolve())

        window.target_version_edit.setText("v3.6.21")
        assert window.notes_edit.text() == str(second_notes.resolve())

        window.target_version_edit.setText("3.6.22")
        assert window.notes_edit.text() == ""
    finally:
        window.shutdown()


def test_release_notes_picker_defaults_to_project_release_notes_directory(
    qapp,
    tmp_path,
):
    notes_directory = tmp_path / "docs" / "releases"
    notes_directory.mkdir(parents=True)
    window = make_panel(
        qapp,
        project_root=tmp_path,
        project_version="3.6.20",
    )
    try:
        with patch.object(
            panel_module.QFileDialog,
            "getOpenFileName",
            return_value=("", ""),
        ) as get_open_file_name:
            window._choose_release_notes()

        assert get_open_file_name.call_args.args[2] == str(notes_directory)
    finally:
        window.shutdown()


def test_open_installer_directory_button_uses_build_output_directory(
    qapp,
    tmp_path,
):
    window = make_panel(
        qapp,
        project_root=tmp_path,
        project_version="3.6.20",
    )
    try:
        with patch.object(
            panel_module.QDesktopServices,
            "openUrl",
            return_value=True,
        ) as open_url:
            window.open_installer_directory_button.click()
            qapp.processEvents()

        expected = tmp_path.resolve() / "dist" / "installer"
        assert expected.is_dir()
        opened_url = open_url.call_args.args[0]
        assert Path(opened_url.toLocalFile()) == expected
    finally:
        window.shutdown()


def test_equal_remote_version_recommends_same_release_with_safe_defaults(qapp):
    window = make_panel(
        qapp,
        project_version="3.6.21",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
        source_identity_checker=lambda *_args: True,
    )
    try:
        assert window.panel_intent is PanelBuildIntent.SAME_RELEASE
        assert window.mode_same_button.isChecked() is True
        assert window.check_sign_manifest.isChecked() is True
        assert window.check_commit_version.isChecked() is False
        assert window.check_push_main.isChecked() is True
        assert window.check_create_tag.isChecked() is True
        assert window.check_create_release.isChecked() is True
        assert window.check_upload_assets.isChecked() is True
        assert window.check_upload_public_key.isChecked() is True
        assert window.check_verify_remote.isChecked() is True
        assert window.check_generate_key.isChecked() is False
        assert window.check_rotate_trust_anchor.isChecked() is False
    finally:
        window.shutdown()


def test_equal_version_with_diverged_base_tag_still_creates_new_revision(qapp, tmp_path):
    release_notes = tmp_path / "docs" / "releases" / "v3.6.21.md"
    release_notes.parent.mkdir(parents=True)
    release_notes.write_text("revision notes\n", encoding="utf-8")
    window = make_panel(
        qapp,
        project_root=tmp_path,
        project_version="3.6.21",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
        source_identity_checker=lambda *_args: False,
    )
    try:
        assert window.panel_intent is PanelBuildIntent.SAME_RELEASE
        assert window._mode is ReleaseMode.SAME_RELEASE_REPAIR
        assert window.mode_same_button.isChecked() is True
        assert window.mode_same_button.isEnabled() is True
        assert window.check_build_installer.isChecked() is True
        assert window.start_button.isEnabled() is True
        assert window.target_release_label.text() == "v3.6.21-r1"
        assert window.validation_label.text() == ""
    finally:
        window.shutdown()


def test_interrupted_tag_for_current_head_is_presented_as_resumable(qapp):
    inventory = RemoteReleaseInfo.available(
        "v3.6.21",
        occupied_tags=("v3.6.21-r1", "v3.6.21"),
        resumable_tags=("v3.6.21-r1",),
    )
    window = make_panel(
        qapp,
        project_version="3.6.21",
        remote_loader=lambda *_args: inventory,
    )
    try:
        request = window._request_from_controls()

        assert request.release_revision == 1
        assert window.target_release_label.text() == "v3.6.21-r1"
        assert window.mode_badge.text() == "继续未完成修订"
        assert "继续该修订" in window.validation_label.text()
        assert "补齐缺失" in window.mode_same_button.toolTip()
        assert window.start_button.isEnabled() is True
        assert "继续未完成修订" in build_confirmation_summary(
            request,
            ReleaseMode.SAME_RELEASE_REPAIR,
            asset_names=("setup.exe",),
        )
    finally:
        window.shutdown()


def test_interrupted_tag_for_old_head_advances_target_without_moving_tag(qapp):
    inventory = RemoteReleaseInfo.available(
        "v3.6.21",
        occupied_tags=("v3.6.21-r1", "v3.6.21"),
    )
    window = make_panel(
        qapp,
        project_version="3.6.21",
        remote_loader=lambda *_args: inventory,
    )
    try:
        request = window._request_from_controls()

        assert request.release_revision == 2
        assert window.target_release_label.text() == "v3.6.21-r2"
        assert "未完成标签 v3.6.21-r1" in window.validation_label.text()
        assert "已顺延为 v3.6.21-r2" in window.validation_label.text()
        assert window.start_button.isEnabled() is True
    finally:
        window.shutdown()


def test_release_tag_identity_checker_detects_diverged_head(tmp_path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Test"],
        cwd=tmp_path,
        check=True,
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tagged source\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "tagged source"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "tag", "v3.6.21"], cwd=tmp_path, check=True)

    assert panel_module._release_tag_matches_head(tmp_path, "3.6.21") is True

    tracked.write_text("new source\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "new source"],
        cwd=tmp_path,
        check=True,
    )

    assert panel_module._release_tag_matches_head(tmp_path, "3.6.21") is False


def test_higher_version_recommends_complete_new_release_chain(qapp):
    window = make_panel(
        qapp,
        project_version="3.6.22",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        assert window.panel_intent is PanelBuildIntent.NEW_RELEASE
        assert window.mode_release_button.isChecked() is True
        assert window.check_sign_manifest.isChecked() is True
        assert window.check_commit_version.isChecked() is True
        assert window.check_push_main.isChecked() is True
        assert window.check_create_tag.isChecked() is True
        assert window.check_create_release.isChecked() is True
        assert window.check_upload_assets.isChecked() is True
        assert window.check_upload_public_key.isChecked() is True
        assert window.check_verify_remote.isChecked() is True
        assert window.check_generate_key.isChecked() is False
        assert window.check_rotate_trust_anchor.isChecked() is False
    finally:
        window.shutdown()


def test_mode_state_is_restored_instead_of_reapplying_defaults(qapp):
    window = make_panel(
        qapp,
        project_version="3.6.22",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        window.check_upload_public_key.setChecked(False)
        window.mode_local_button.click()
        assert window.panel_intent is PanelBuildIntent.LOCAL
        assert window.check_upload_public_key.isChecked() is False

        window.mode_release_button.click()

        assert window.panel_intent is PanelBuildIntent.NEW_RELEASE
        assert window.check_upload_public_key.isChecked() is False
        assert window.check_upload_assets.isChecked() is True
    finally:
        window.shutdown()


def test_manual_local_override_on_higher_version_never_writes_remote(qapp):
    window = make_panel(
        qapp,
        project_version="3.6.22",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        window.mode_local_button.click()
        request = window._request_from_controls()

        assert window.panel_intent is PanelBuildIntent.LOCAL
        assert request.offline_debug is True
        assert request.same_release_repair is False
        assert request.sign_manifest is False
        assert request.commit_version_changes is False
        assert request.push_main is False
        assert request.create_or_reuse_tag is False
        assert request.create_or_update_release is False
        assert request.upload_release_assets is False
        assert request.upload_public_key is False
        assert request.verify_remote_assets is False
    finally:
        window.shutdown()


def test_local_override_survives_target_and_remote_form_refreshes(qapp):
    window = make_panel(
        qapp,
        project_version="3.6.22",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        window.mode_local_button.click()
        window.repository_edit.setText("owner/other")
        window.target_version_edit.setText("3.6.23")
        window.refresh_mode()

        assert window.panel_intent is PanelBuildIntent.LOCAL
        assert window.mode_local_button.isChecked() is True
    finally:
        window.shutdown()


def test_local_debug_mode_projects_disabled_remote_and_signing_controls(qapp):
    window = make_panel(qapp, remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"))
    try:
        window.target_version_edit.setText("3.6.20")
        window.refresh_mode()

        assert window.mode_badge.property("releaseMode") == "local_debug"
        assert window.check_upload_assets.isEnabled() is False
        assert window.check_push_main.isEnabled() is False
        assert window.check_sign_manifest.isEnabled() is False
        assert window.private_key_edit.isEnabled() is False
    finally:
        window.shutdown()


def test_remote_unknown_is_automatically_restricted_to_offline_local_mode(qapp):
    window = make_panel(
        qapp,
        remote_loader=lambda *_args: RemoteReleaseInfo.unavailable("network unavailable"),
    )
    try:
        request = window._request_from_controls()
        assert window.panel_intent is PanelBuildIntent.LOCAL
        assert window.mode_badge.property("releaseMode") == "offline_debug"
        assert window.mode_same_button.isEnabled() is False
        assert window.mode_release_button.isEnabled() is False
        assert request.offline_debug is True
        assert request.same_release_repair is False
        assert request.sign_manifest is False
        assert request.push_main is False
        assert request.upload_release_assets is False
    finally:
        window.shutdown()


def test_custom_proxy_endpoint_tracks_project_proxy_option(qapp):
    window = make_panel(qapp)
    try:
        window.show()
        qapp.processEvents()
        assert window.custom_proxy_edit.isEnabled() is False
        assert window.custom_proxy_edit.isHidden() is True

        window.proxy_combo.setCurrentIndex(window.proxy_combo.findData("自定义"))
        qapp.processEvents()

        assert window.custom_proxy_edit.isEnabled() is True
        assert window.custom_proxy_edit.isHidden() is False
        assert window.proxy_control.property("customProxySurface") == "split"
        assert window.proxy_combo.geometry().top() == (
            window.custom_proxy_edit.geometry().top()
        )
        assert window.proxy_combo.geometry().bottom() == (
            window.custom_proxy_edit.geometry().bottom()
        )
    finally:
        window.shutdown()


def test_private_key_field_uses_canonical_default_path(qapp):
    window = make_panel(qapp)
    try:
        key_path = Path(window.private_key_edit.text())

        assert key_path.name == "update_manifest_ed25519_private.pem"
        assert key_path.is_absolute()
        assert PROJECT_ROOT not in key_path.parents
    finally:
        window.shutdown()


def test_release_builder_proxy_uses_shared_themed_combo(qapp):
    window = make_panel(qapp)
    try:
        assert isinstance(window.proxy_combo, ThemedComboBox)
        assert window.proxy_combo.property("themedComboManaged") == "true"
        assert window.proxy_combo.property("comboPopupClampToControl") is True
        assert window.proxy_combo.view().property("comboPopupFullExpand") == "true"
    finally:
        window.shutdown()


def test_release_builder_uses_two_column_workbench_without_outer_scroll(qapp):
    window = make_panel(qapp)
    try:
        assert window.findChild(QScrollArea, "ReleaseBuilderScroll") is None
        assert window.left_configuration_column is not None
        assert window.execution_column is not None
        assert window.section_widgets[:5] == window.configuration_sections
        assert window.section_widgets[5] is window.execution_section
        assert len(window.configuration_sections) == 5
    finally:
        window.shutdown()


def test_mode_selector_and_build_options_have_stable_card_dimensions(qapp):
    window = make_panel(qapp)
    try:
        assert window.mode_local_button.minimumHeight() >= 44
        assert window.mode_same_button.minimumHeight() >= 44
        assert window.mode_release_button.minimumHeight() >= 44
        assert window.check_build_portable.isCheckable()
        assert window.check_build_portable.minimumHeight() >= 42
        assert window.check_build_installer.property("releaseOptionCard") is True
    finally:
        window.shutdown()


def test_remote_refresh_preserves_known_mode_until_new_result_arrives(qapp):
    refresh_release = threading.Event()

    def delayed_loader(*_args):
        refresh_release.wait(2)
        return RemoteReleaseInfo.available("3.6.21")

    window = make_panel(
        qapp,
        project_version="3.6.22",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        assert window.panel_intent is PanelBuildIntent.NEW_RELEASE
        window._remote_loader = delayed_loader
        window.start_remote_lookup()
        qapp.processEvents()

        assert window.panel_intent is PanelBuildIntent.NEW_RELEASE
        assert window.remote_info == RemoteReleaseInfo.available("3.6.21")
        assert window.remote_version_label.text().startswith("正在检查")
        assert window.start_button.isEnabled() is False
    finally:
        refresh_release.set()
        pump_until(qapp, lambda: not window.remote_lookup_active)
        window.shutdown()


def test_mode_and_option_cards_use_semantic_properties(qapp):
    window = make_panel(qapp)
    try:
        assert (
            window.mode_release_button.property("releaseModeChoice")
            == "new_release"
        )
        assert (
            window.check_build_installer.property("releaseOptionCard")
            is True
        )
        assert "QPushButton#ReleaseModeChoice" in window.styleSheet()
        assert "QPushButton#ReleaseOptionCard" in window.styleSheet()
    finally:
        window.shutdown()


def test_workbench_columns_and_log_panel_do_not_overlap_at_reference_size(qapp):
    window = make_panel(qapp)
    try:
        window.resize(1480, 860)
        window.show()
        qapp.processEvents()

        left = window.left_configuration_column.geometry()
        right = window.execution_column.geometry()
        assert left.right() < right.left()
        assert window.execution_section.height() > 600
        assert window.log_panel.height() > 300
    finally:
        window.close()
        window.shutdown()


@pytest.mark.parametrize("size", [(1366, 768), (980, 680)])
def test_configuration_cards_are_not_compressed_or_clipped(qapp, size):
    window = make_panel(qapp)
    try:
        window.resize(*size)
        window.show()
        qapp.processEvents()

        for section in window.configuration_sections:
            assert section.height() >= section.minimumSizeHint().height()
            assert section.body.geometry().bottom() <= section.contentsRect().bottom()

        mode_parent = window.mode_local_button.parentWidget()
        for button in (
            window.mode_local_button,
            window.mode_same_button,
            window.mode_release_button,
        ):
            assert button.isVisible()
            assert button.geometry().bottom() <= mode_parent.rect().bottom()

        release_parent = window.check_verify_remote.parentWidget()
        assert (
            window.check_verify_remote.geometry().bottom()
            <= release_parent.rect().bottom()
        )
    finally:
        window.close()
        window.shutdown()


def test_compact_mode_and_release_option_labels_fit_without_clipping(qapp):
    window = make_panel(qapp)
    try:
        window.resize(980, 680)
        window.show()
        qapp.processEvents()

        for button in (
            window.mode_local_button,
            window.mode_same_button,
            window.mode_release_button,
        ):
            widest_line = max(
                button.fontMetrics().horizontalAdvance(line)
                for line in button.text().splitlines()
            )
            assert widest_line + 20 <= button.width()

        for control in (
            window.check_generate_key,
            window.check_rotate_trust_anchor,
            window.check_sign_manifest,
            *window._release_option_controls,
        ):
            assert control.sizeHint().width() <= control.width()
    finally:
        window.close()
        window.shutdown()


@pytest.mark.parametrize("size", [(1480, 860), (1366, 768), (980, 680)])
def test_configuration_and_execution_columns_share_the_same_bottom_edge(qapp, size):
    window = make_panel(qapp)
    try:
        window.resize(*size)
        window.show()
        qapp.processEvents()

        left_bottom = window.configuration_sections[-1].geometry().bottom()
        right_bottom = window.execution_section.geometry().bottom()
        assert abs(left_bottom - right_bottom) <= 1
    finally:
        window.close()
        window.shutdown()


def test_remote_lookup_is_async_and_late_result_is_ignored_after_teardown(qapp):
    release_loader = threading.Event()
    loader_started = threading.Event()
    ui_thread_id = threading.get_ident()
    loader_thread_ids: list[int] = []

    def slow_loader(*_args):
        loader_thread_ids.append(threading.get_ident())
        loader_started.set()
        release_loader.wait(2)
        return RemoteReleaseInfo.available("9.9.9")

    window = ReleaseBuilderWindow(project_version="3.6.20", remote_loader=slow_loader)
    assert loader_started.wait(1)
    assert len(loader_thread_ids) == 1
    assert loader_thread_ids[0] != ui_thread_id

    window.shutdown()
    release_loader.set()
    pump_until(qapp, lambda: not window.remote_lookup_active)

    assert window.remote_info == RemoteReleaseInfo.unknown()


def test_close_waits_for_active_remote_lookup_and_ignores_late_result(qapp):
    release_loader = threading.Event()
    loader_started = threading.Event()

    def slow_loader(*_args):
        loader_started.set()
        release_loader.wait(2)
        return RemoteReleaseInfo.available("9.9.9")

    window = ReleaseBuilderWindow(
        project_version="3.6.20",
        remote_loader=slow_loader,
    )
    window.show()
    qapp.processEvents()
    assert loader_started.wait(1)

    assert window.close() is False
    assert window.isVisible() is True
    assert window.remote_lookup_active is True

    release_loader.set()
    pump_until(qapp, lambda: not window.remote_lookup_active)
    pump_until(qapp, lambda: not window.isVisible())

    assert window.remote_info == RemoteReleaseInfo.unknown()


def test_qprocess_uses_exact_program_argv_proxy_environment_and_secret_safe_request(
    qapp, tmp_path, monkeypatch
):
    fake = FakeProcess()
    monkeypatch.setenv("HTTP_PROXY", "http://ambient:8080")
    controller = ReleaseProcessController(
        process=fake,
        project_root=PROJECT_ROOT,
        request_directory=tmp_path,
        log_directory=tmp_path / "logs",
    )
    request = make_request(
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        proxy_label="直连",
    )

    controller.start(request, ProxySelection.direct())

    assert fake.program == sys.executable
    assert fake.arguments == [
        str(PROJECT_ROOT / "packaging" / "build_release.py"),
        "--headless",
        "--request-file",
        str(controller.request_file),
    ]
    assert all(
        not fake.environment.contains(variable)
        for variable in PROXY_ENVIRONMENT_VARIABLES
    )
    request_payload = controller.request_file.read_text(encoding="utf-8")
    assert "RELEASE_PRIVATE_KEY_PATH" in request_payload
    assert "PRIVATE KEY-----" not in request_payload
    assert "ambient:8080" not in " ".join(fake.arguments)
    assert "RELEASE_PRIVATE_KEY_PATH" not in " ".join(fake.arguments)

    controller.feed_stdout(success_event() + "\n")
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)


def test_partial_lines_are_buffered_flood_is_bounded_and_stage_is_immediate(qapp):
    controller = ReleaseProcessController(process=FakeProcess(), log_capacity=12)
    batches: list[list[str]] = []
    stages: list[tuple[str, int]] = []
    controller.log_lines_ready.connect(lambda lines: batches.append(list(lines)))
    controller.stage_changed.connect(
        lambda stage, progress, _message: stages.append((stage, progress))
    )

    controller.feed_stdout("partial")
    assert controller.pending_log_count == 0
    controller.feed_stdout(" line\n" + "".join(f"log-{index}\n" for index in range(40)))
    controller.feed_stdout(stage_event() + "\n")

    assert controller.pending_log_count == 12
    assert stages == [("building_portable", 35)]
    controller.flush_log_batch()
    assert sum(len(batch) for batch in batches) == 12
    assert all(len(batch) <= 200 for batch in batches)


def test_structured_log_event_is_visible_and_does_not_break_terminal_result(qapp):
    controller = ReleaseProcessController(process=FakeProcess())
    batches: list[str] = []
    controller.log_lines_ready.connect(
        lambda lines: batches.extend(str(line) for line in lines)
    )

    controller.feed_stdout(stage_event(sequence=1) + "\n")
    controller.feed_stdout(log_event(sequence=2) + "\n")
    controller.feed_stdout(success_event(sequence=3) + "\n")
    controller.flush_log_batch()
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)

    assert controller.result.succeeded is True
    assert batches == ["packaging output"]


def test_structured_error_event_fails_closed_even_if_success_result_follows(qapp):
    controller = ReleaseProcessController(process=FakeProcess())

    controller.feed_stdout(stage_event(sequence=1) + "\n")
    controller.feed_stdout(log_event(sequence=2) + "\n")
    controller.feed_stdout(error_event(sequence=3) + "\n")
    controller.feed_stdout(success_event(sequence=4) + "\n")
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)

    assert controller.result.succeeded is False
    assert "portable build failed" in controller.result.error
    assert "unknown release event kind" not in controller.result.error


def test_unknown_structured_event_kind_still_fails_closed(qapp):
    controller = ReleaseProcessController(process=FakeProcess())
    payload = {
        "kind": "mystery",
        "sequence": 1,
        "timestamp": "2026-07-19T00:00:00Z",
        "stage": "building_portable",
        "progress": 35,
        "message": "unexpected",
        "data": {},
    }

    controller.feed_stdout(EVENT_PREFIX + json.dumps(payload) + "\n")
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)

    assert controller.result.succeeded is False
    assert controller.result.error == "unknown release event kind"


def test_finished_drains_unread_qprocess_output_before_terminal_judgement(qapp):
    fake = FakeProcess()
    fake.set_stdout((success_event() + "\n").encode("utf-8"))
    fake.set_stderr(b"last stderr line")
    controller = ReleaseProcessController(process=fake)
    batches: list[str] = []
    controller.log_lines_ready.connect(
        lambda lines: batches.extend(str(line) for line in lines)
    )

    controller.on_finished(0, QProcess.ExitStatus.NormalExit)

    assert controller.result.succeeded is True
    assert "last stderr line" in batches


def test_real_qprocess_finished_drains_output_without_ready_read_slots(qapp):
    process = QProcess()
    controller = ReleaseProcessController(process=process)
    completed = QSignalSpy(controller.completed)
    process.readyReadStandardOutput.disconnect()
    process.readyReadStandardError.disconnect()
    payload = (success_event() + "\n").encode("utf-8")
    process.setProgram(sys.executable)
    process.setArguments(
        [
            "-c",
            f"import sys; sys.stdout.buffer.write({payload!r}); sys.stdout.flush()",
        ]
    )

    process.start()
    if not completed:
        assert completed.wait(10_000)

    assert controller.result.succeeded is True


@pytest.mark.parametrize(
    ("event_lines", "exit_code", "exit_status", "succeeded", "error_fragment"),
    (
        ((success_event(),), 0, QProcess.ExitStatus.NormalExit, True, ""),
        ((), 0, QProcess.ExitStatus.NormalExit, False, "final result event"),
        ((success_event(), success_event(2)), 0, QProcess.ExitStatus.NormalExit, False, "duplicate"),
        ((success_event(2),), 0, QProcess.ExitStatus.NormalExit, False, "out of order"),
        ((success_event(),), 1, QProcess.ExitStatus.NormalExit, False, "exit code"),
        ((success_event(),), 0, QProcess.ExitStatus.CrashExit, False, "abnormally"),
    ),
)
def test_success_requires_one_ordered_result_and_normal_zero_exit(
    qapp, event_lines, exit_code, exit_status, succeeded, error_fragment
):
    controller = ReleaseProcessController(process=FakeProcess())
    for line in event_lines:
        controller.feed_stdout(line + "\n")

    controller.on_finished(exit_code, exit_status)

    assert controller.result.succeeded is succeeded
    if error_fragment:
        assert error_fragment in controller.result.error


def test_malformed_result_fails_closed_and_redacts_error(qapp):
    controller = ReleaseProcessController(process=FakeProcess())

    controller.feed_stdout(
        EVENT_PREFIX + '{"kind":"result","token":"github_pat_super_secret"}\n'
    )
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)

    assert controller.result.succeeded is False
    assert "malformed" in controller.result.error
    assert "github_pat_super_secret" not in controller.result.error


def test_cancel_terminates_then_escalates_and_cleanup_is_deterministic(
    qapp, tmp_path
):
    fake = FakeProcess()
    controller = ReleaseProcessController(
        process=fake,
        request_directory=tmp_path,
        log_directory=tmp_path / "logs",
    )
    controller.start(make_request(), ProxySelection.system())
    request_file = controller.request_file

    controller.cancel()
    assert fake.terminated is True
    assert controller.cancel_timer.interval() == 5000

    controller.escalate_cancel()
    assert fake.killed is True
    controller.on_finished(1, QProcess.ExitStatus.CrashExit)
    assert not request_file.exists()
    assert controller.cancel_timer.isActive() is False
    assert controller.log_writer_active is False


def test_shutdown_retains_process_state_until_target_reports_stopped(qapp, tmp_path):
    fake = FakeProcess()
    controller = ReleaseProcessController(
        process=fake,
        request_directory=tmp_path,
        log_directory=tmp_path / "logs",
    )
    controller.start(make_request(), ProxySelection.system())
    request_file = controller.request_file

    assert controller.shutdown() is False

    assert fake.terminated is True
    assert fake.killed is False
    assert controller.running is True
    assert controller.cancel_timer.isActive() is True
    assert request_file.exists()

    controller.escalate_cancel()
    assert fake.killed is True
    assert controller.running is True
    assert request_file.exists()

    controller.on_finished(1, QProcess.ExitStatus.CrashExit)
    assert controller.running is False
    assert not request_file.exists()


def test_windows_escalation_tracks_taskkill_until_confirmation(
    qapp, tmp_path, monkeypatch
):
    target = FakeQtProcess()
    taskkill = FakeProcess()
    monkeypatch.setattr(process_controller_module.sys, "platform", "win32")
    controller = ReleaseProcessController(
        process=target,
        request_directory=tmp_path,
        log_directory=tmp_path / "logs",
        taskkill_process_factory=lambda _parent: taskkill,
    )
    controller.start(make_request(), ProxySelection.system())
    request_file = controller.request_file

    controller.cancel()
    controller.escalate_cancel()

    assert controller._taskkill_process is taskkill
    assert taskkill.program == "taskkill"
    assert taskkill.arguments == ["/PID", "4343", "/T", "/F"]
    assert controller.running is True
    assert request_file.exists()

    taskkill._state = QProcess.ProcessState.NotRunning
    taskkill.finished.emit(0, QProcess.ExitStatus.NormalExit)
    assert controller._taskkill_process is None
    assert controller._taskkill_confirmation_timer.isActive() is True

    controller._confirm_target_after_taskkill()
    assert target.killed is True
    assert controller.running is True
    assert request_file.exists()

    controller.on_finished(1, QProcess.ExitStatus.CrashExit)
    assert controller.running is False
    assert not request_file.exists()


def test_window_close_while_running_retains_controller_until_stopped(qapp, tmp_path):
    fake = FakeProcess()
    controller = ReleaseProcessController(
        process=fake,
        request_directory=tmp_path,
        log_directory=tmp_path / "logs",
    )
    window = make_panel(qapp, process_controller=controller)
    try:
        controller.start(make_request(), ProxySelection.system())
        request_file = controller.request_file
        window.show()
        qapp.processEvents()

        assert window.close() is False
        assert fake.terminated is True
        assert controller.running is True
        assert request_file.exists()
        assert window.isVisible() is True

        controller.on_finished(1, QProcess.ExitStatus.CrashExit)
        pump_until(qapp, lambda: not window.isVisible())
        assert not request_file.exists()
    finally:
        window.shutdown()


class _BlockingStream:
    def __init__(self) -> None:
        self.write_started = threading.Event()
        self.release_write = threading.Event()
        self.writes: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def write(self, value: str) -> int:
        self.write_started.set()
        self.release_write.wait(2)
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        return None


class _DeferredCloseWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.can_close = False
        self.active = True
        self.error = ""
        self.progress_count = 0

    def submit(self, _line: str) -> None:
        return None

    def close(self, *, timeout_seconds: float) -> bool:
        if not self.can_close:
            return False
        self.active = False
        return True


def test_background_writer_close_is_bounded_and_drop_notice_is_reliable(tmp_path):
    stream = _BlockingStream()
    writer = _BackgroundLogWriter(
        tmp_path / "audit.log",
        capacity=1,
        stream_factory=lambda *_args, **_kwargs: stream,
    )
    writer.submit("first")
    assert stream.write_started.wait(1)
    writer.submit("queued")
    for index in range(20):
        writer.submit(f"dropped-{index}")

    started = time.monotonic()
    assert writer.close(timeout_seconds=0.02) is False
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert writer.error == ""
    assert writer._thread.daemon is True

    stream.release_write.set()
    assert writer.close(timeout_seconds=1.0) is True
    assert "dropped" in "".join(stream.writes)


def test_pending_writer_close_does_not_turn_success_into_failure(tmp_path):
    writers: list[_DeferredCloseWriter] = []

    def create_writer(path: Path) -> _DeferredCloseWriter:
        writer = _DeferredCloseWriter(path)
        writers.append(writer)
        return writer

    controller = ReleaseProcessController(
        process=FakeProcess(),
        log_directory=tmp_path / "logs",
        writer_factory=create_writer,
        writer_close_timeout_seconds=0.0,
    )
    controller._log_writer = create_writer(tmp_path / "audit.log")
    controller.result = ReleaseResult(
        mode=ReleaseMode.NEW_RELEASE,
        stage=ReleaseStage.SUCCEEDED,
    )
    controller._completion_pending = True

    controller._finish_writer_or_defer()

    assert controller.result.succeeded is True
    assert controller.shutdown_complete is False

    writers[-1].can_close = True
    controller._poll_writer_close()

    assert controller.result.succeeded is True
    assert controller.shutdown_complete is True


def test_writer_shutdown_deadline_allows_application_exit(tmp_path):
    writer = _DeferredCloseWriter(tmp_path / "audit.log")
    controller = ReleaseProcessController(
        process=FakeProcess(),
        log_directory=tmp_path / "logs",
        writer_factory=lambda _path: writer,
        writer_close_timeout_seconds=0.0,
        writer_stall_timeout_seconds=0.0,
        writer_hard_close_timeout_seconds=0.0,
    )
    controller._log_writer = writer
    controller.result = ReleaseResult(
        mode=ReleaseMode.NEW_RELEASE,
        stage=ReleaseStage.SUCCEEDED,
    )
    controller._completion_pending = True

    controller._finish_writer_or_defer()
    controller._maybe_emit_completed()

    assert controller.shutdown_complete is True
    assert controller.result.succeeded is True
    assert "may be incomplete" in controller.audit_log_warning


@pytest.mark.parametrize(
    ("result", "expected_error"),
    (
        (
            ReleaseResult(
                mode=ReleaseMode.NEW_RELEASE,
                stage=ReleaseStage.SUCCEEDED,
            ),
            "",
        ),
        (
            ReleaseResult(
                mode=ReleaseMode.NEW_RELEASE,
                stage=ReleaseStage.FAILED,
                errors=("upload failed",),
                error="upload failed",
            ),
            "upload failed",
        ),
    ),
)
def test_writer_io_error_preserves_release_result(
    tmp_path,
    result,
    expected_error,
):
    writer = _DeferredCloseWriter(tmp_path / "audit.log")
    writer.can_close = True
    writer.error = "failed to write release log"
    controller = ReleaseProcessController(
        process=FakeProcess(),
        writer_factory=lambda _path: writer,
    )
    controller._log_writer = writer
    controller.result = result

    controller._finish_writer_or_defer()

    assert controller.result is result
    assert controller.result.error == expected_error
    assert controller.audit_log_warning == writer.error


def test_writer_progress_refreshes_stall_deadline_until_hard_limit(tmp_path):
    now = [0.0]
    writer = _DeferredCloseWriter(tmp_path / "audit.log")
    controller = ReleaseProcessController(
        process=FakeProcess(),
        writer_factory=lambda _path: writer,
        writer_close_timeout_seconds=0.0,
        writer_stall_timeout_seconds=5.0,
        writer_hard_close_timeout_seconds=30.0,
        monotonic_clock=lambda: now[0],
    )
    controller._log_writer = writer

    controller._finish_writer_or_defer()
    for tick in (4.9, 9.8, 14.7):
        now[0] = tick
        writer.progress_count += 1
        controller._poll_writer_close()
        assert controller.log_writer_active is True

    now[0] = 19.8
    controller._poll_writer_close()

    assert controller.log_writer_active is False
    assert "may be incomplete" in controller.audit_log_warning


def test_writer_hard_deadline_bounds_continuous_slow_progress(tmp_path):
    now = [0.0]
    writer = _DeferredCloseWriter(tmp_path / "audit.log")
    controller = ReleaseProcessController(
        process=FakeProcess(),
        writer_factory=lambda _path: writer,
        writer_close_timeout_seconds=0.0,
        writer_stall_timeout_seconds=5.0,
        writer_hard_close_timeout_seconds=12.0,
        monotonic_clock=lambda: now[0],
    )
    controller._log_writer = writer

    controller._finish_writer_or_defer()
    for tick in (4.0, 8.0):
        now[0] = tick
        writer.progress_count += 1
        controller._poll_writer_close()
        assert controller.log_writer_active is True

    now[0] = 12.0
    writer.progress_count += 1
    controller._poll_writer_close()

    assert controller.log_writer_active is False
    assert "may be incomplete" in controller.audit_log_warning


def test_start_failure_retains_writer_until_bounded_close_completes(tmp_path):
    writers: list[_DeferredCloseWriter] = []

    def create_writer(path: Path) -> _DeferredCloseWriter:
        writer = _DeferredCloseWriter(path)
        writers.append(writer)
        return writer

    controller = ReleaseProcessController(
        process=FakeProcess(),
        request_directory=tmp_path,
        log_directory=tmp_path / "logs",
        writer_factory=create_writer,
        writer_close_timeout_seconds=0.0,
    )

    with pytest.raises(ValueError, match="invalid proxy selection"):
        controller.start(
            make_request(proxy_label="invalid"),
            ProxySelection(label="invalid"),
        )

    assert controller.shutdown_complete is False
    assert controller.log_writer_active is True

    writers[0].can_close = True
    controller._poll_writer_close()

    assert controller.shutdown_complete is True
    assert controller.log_writer_active is False


def test_audit_log_paths_are_unique_within_one_second(tmp_path):
    controller = ReleaseProcessController(
        process=FakeProcess(),
        log_directory=tmp_path,
    )

    first = controller._new_log_path(ReleaseMode.NEW_RELEASE, "3.6.20")
    second = controller._new_log_path(ReleaseMode.NEW_RELEASE, "3.6.20")

    assert first != second
    assert first.parent == second.parent == tmp_path


def test_confirmation_summary_uses_safe_fields_and_chromed_dialog(qapp):
    request = make_request(
        repository="owner/repository",
        release_notes_path="D:/notes/release.md",
        private_key_path="D:/secrets/private.pem",
        proxy_label="系统代理",
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
    )

    summary = build_confirmation_summary(
        request,
        ReleaseMode.NEW_RELEASE,
        asset_names=(
            "UniversalCrawler-Setup.exe",
            "latest.json",
            "latest.json.sig",
        ),
    )
    window = make_panel(qapp)
    try:
        dialog = window.create_confirmation_dialog(summary)
        assert isinstance(dialog, ChromedDialog)
        assert "3.6.20" in summary
        assert "owner/repository" in summary
        assert "release.md" in summary
        assert "private.pem" not in summary
        assert "token" not in summary.lower()
        assert "UniversalCrawler-Setup.exe" in summary
        assert "版本：" in summary
        assert "发布模式：" in summary
        assert "发布说明：" in summary
        assert "Version:" not in summary
        assert "Mode:" not in summary
        assert "Release notes:" not in summary
    finally:
        window.shutdown()


@pytest.mark.parametrize(
    ("available", "expected"),
    (
        (QRect(0, 0, 1920, 1080), QRect(220, 110, 1480, 860)),
        (QRect(20, 30, 900, 700), QRect(20, 30, 900, 700)),
        (QRect(-1600, 10, 1200, 760), QRect(-1600, 10, 1200, 760)),
    ),
)
def test_initial_geometry_is_centered_and_constrained(available, expected):
    assert ReleaseBuilderWindow.constrained_geometry(available) == expected


def test_launch_does_not_reenter_an_existing_qapplication(qapp, monkeypatch):
    class ExistingApplication:
        def setWindowIcon(self, icon) -> None:
            self.window_icon = icon

        def exec(self):
            raise AssertionError("existing QApplication event loop must not be re-entered")

    class ApplicationFacade:
        @staticmethod
        def instance():
            return existing

    class FakeSignal:
        def connect(self, callback) -> None:
            self.callback = callback

        def emit(self) -> None:
            self.callback()

    class FakeWindow:
        def __init__(self) -> None:
            self.destroyed = FakeSignal()
            self.delete_on_close = False

        def show(self) -> None:
            self.shown = True

        def setAttribute(self, attribute, enabled) -> None:
            if attribute == Qt.WidgetAttribute.WA_DeleteOnClose:
                self.delete_on_close = bool(enabled)

    existing = ExistingApplication()
    fake_window = FakeWindow()
    monkeypatch.setattr(panel_module, "QApplication", ApplicationFacade)
    monkeypatch.setattr(panel_module, "ReleaseBuilderWindow", lambda: fake_window)

    assert panel_module.launch_release_builder_panel() == 0
    assert existing.window_icon.isNull() is False
    assert fake_window.shown is True
    assert fake_window.delete_on_close is True
    assert panel_module._LAUNCHED_WINDOWS[id(fake_window)] is fake_window

    fake_window.destroyed.emit()

    assert id(fake_window) not in panel_module._LAUNCHED_WINDOWS
    panel_module._LAUNCHED_WINDOWS.clear()


def test_process_controller_is_defined_in_dedicated_module():
    assert ReleaseProcessController.__module__ == "release_tool.process_controller"
