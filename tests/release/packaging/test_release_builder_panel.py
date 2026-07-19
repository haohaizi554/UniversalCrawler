from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QObject, QProcess, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication

from tests.support.paths import PROJECT_ROOT


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))

from app.ui.dialogs.chromed_dialog import ChromedDialog
from app.ui.layout.window_chrome import WindowChromeFrame
from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
from release_tool.events import EVENT_PREFIX
from release_tool.models import BuildRequest, ReleaseMode, RemoteReleaseInfo, ReleaseStage
from release_tool import panel as panel_module
from release_tool import process_controller as process_controller_module
from release_tool.panel import (
    ReleaseBuilderWindow,
    build_confirmation_summary,
)
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


def test_remote_unknown_fails_closed_until_offline_debug_is_explicit(qapp):
    window = make_panel(
        qapp,
        remote_loader=lambda *_args: RemoteReleaseInfo.unavailable("network unavailable"),
    )
    try:
        assert window.mode_badge.property("releaseMode") == "remote_unknown"
        assert window.start_button.isEnabled() is False

        window.check_offline_debug.setChecked(True)
        window.refresh_mode()

        assert window.mode_badge.property("releaseMode") == "offline_debug"
        assert "remote release state is unknown" not in window.validation_label.text()
    finally:
        window.shutdown()


def test_custom_proxy_endpoint_tracks_project_proxy_option(qapp):
    window = make_panel(qapp)
    try:
        assert window.custom_proxy_edit.isEnabled() is False

        window.proxy_combo.setCurrentIndex(window.proxy_combo.findData("自定义"))

        assert window.custom_proxy_edit.isEnabled() is True
    finally:
        window.shutdown()


def test_remote_lookup_is_async_and_late_result_is_ignored_after_teardown(qapp):
    release_loader = threading.Event()
    loader_started = threading.Event()

    def slow_loader(*_args):
        loader_started.set()
        release_loader.wait(2)
        return RemoteReleaseInfo.available("9.9.9")

    started = time.monotonic()
    window = ReleaseBuilderWindow(project_version="3.6.20", remote_loader=slow_loader)
    assert time.monotonic() - started < 0.25
    assert loader_started.wait(1)

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


def test_structured_error_event_fails_closed_even_if_success_result_follows(qapp):
    controller = ReleaseProcessController(process=FakeProcess())

    controller.feed_stdout(error_event() + "\n")
    controller.feed_stdout(success_event(sequence=2) + "\n")
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)

    assert controller.result.succeeded is False
    assert "portable build failed" in controller.result.error


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
    pump_until(qapp, lambda: controller.result.succeeded, timeout=3.0)

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

    def submit(self, _line: str) -> None:
        return None

    def close(self, *, timeout_seconds: float) -> bool:
        if not self.can_close:
            self.error = "timed out while closing release log"
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
    assert "timed out" in writer.error

    stream.release_write.set()
    assert writer.close(timeout_seconds=1.0) is True
    assert "dropped" in "".join(stream.writes)


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
    finally:
        window.shutdown()


@pytest.mark.parametrize(
    ("available", "expected"),
    (
        (QRect(0, 0, 1920, 1080), QRect(370, 130, 1180, 820)),
        (QRect(20, 30, 900, 700), QRect(20, 30, 900, 700)),
        (QRect(-1600, 10, 1200, 760), QRect(-1590, 10, 1180, 760)),
    ),
)
def test_initial_geometry_is_centered_and_constrained(available, expected):
    assert ReleaseBuilderWindow.constrained_geometry(available) == expected


def test_launch_does_not_reenter_an_existing_qapplication(qapp, monkeypatch):
    class ExistingApplication:
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
    assert fake_window.shown is True
    assert fake_window.delete_on_close is True
    assert panel_module._LAUNCHED_WINDOWS[id(fake_window)] is fake_window

    fake_window.destroyed.emit()

    assert id(fake_window) not in panel_module._LAUNCHED_WINDOWS
    panel_module._LAUNCHED_WINDOWS.clear()


def test_process_controller_is_defined_in_dedicated_module():
    assert ReleaseProcessController.__module__ == "release_tool.process_controller"
