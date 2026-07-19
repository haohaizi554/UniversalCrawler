"""Themed Qt panel for planning and running release builds."""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PyQt6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QRect,
    QSignalBlocker,
    QThread,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.log_panel import LogPanel
from app.ui.dialogs.chromed_dialog import ChromedDialog
from app.ui.layout.window_chrome import WindowChromeFrame
from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
from app.ui.styles import (
    apply_application_theme,
    build_palette,
    resolve_is_dark_theme,
    theme_colors,
)

from .events import EVENT_PREFIX, ReleaseEvent, parse_event_line, redact_release_text
from .icon_builder import release_builder_icon_path
from .models import (
    BuildRequest,
    ReleaseMode,
    ReleaseResult,
    ReleaseStage,
    RemoteReleaseInfo,
)
from .modes import resolve_release_mode, validate_build_request
from .proxy import ProxySelection, build_proxy_environment, project_proxy_options
from .remote import fetch_latest_release
from .versioning import read_project_version


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = PROJECT_ROOT / "packaging" / "build_release.py"
DEFAULT_REPOSITORY = "haohaizi554/UniversalCrawler"
LOG_INTERVAL_MS = 50
MAX_LINES_PER_TICK = 200
DEFAULT_LOG_CAPACITY = 5000
WRITER_CAPACITY = 4096
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_ACTIVE_REMOTE_THREADS: set[QThread] = set()


class _RemoteLoaderWorker(QObject):
    completed = pyqtSignal(int, object)

    def __init__(
        self,
        generation: int,
        loader: Callable[[str, Mapping[str, str]], RemoteReleaseInfo],
        repository: str,
        environment: Mapping[str, str],
    ) -> None:
        super().__init__()
        self._generation = generation
        self._loader = loader
        self._repository = repository
        self._environment = dict(environment)

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._loader(self._repository, self._environment)
            if not isinstance(result, RemoteReleaseInfo):
                raise TypeError("remote loader returned an invalid result")
        except Exception as error:
            result = RemoteReleaseInfo.unavailable(redact_release_text(str(error)))
        self.completed.emit(self._generation, result)


class _BackgroundLogWriter:
    """Write redacted log lines on one bounded background queue."""

    def __init__(self, path: Path, *, capacity: int = WRITER_CAPACITY) -> None:
        self.path = Path(path)
        self._queue: queue.Queue[str] = queue.Queue(maxsize=max(1, int(capacity)))
        self._stop = threading.Event()
        self._dropped = 0
        self.error = ""
        self._thread = threading.Thread(
            target=self._run,
            name="release-log-writer",
            daemon=False,
        )
        self._thread.start()

    @property
    def active(self) -> bool:
        return self._thread.is_alive()

    def submit(self, line: str) -> None:
        safe_line = redact_release_text(str(line)).rstrip("\r\n")
        try:
            self._queue.put_nowait(safe_line)
        except queue.Full:
            self._dropped += 1

    def close(self) -> None:
        if self._stop.is_set():
            if self._thread.is_alive():
                self._thread.join()
            return
        if self._dropped:
            try:
                self._queue.put_nowait(
                    f"[log writer dropped {self._dropped} lines during a burst]"
                )
            except queue.Full:
                pass
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                while not self._stop.is_set() or not self._queue.empty():
                    try:
                        line = self._queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    stream.write(f"{line}\n")
                    self._queue.task_done()
                stream.flush()
        except (OSError, UnicodeError):
            self.error = "failed to write release log"
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break


class ReleaseProcessController(QObject):
    """Own one release child process and its fail-closed event protocol."""

    log_lines_ready = pyqtSignal(object)
    stage_changed = pyqtSignal(str, int, str)
    error_reported = pyqtSignal(str)
    running_changed = pyqtSignal(bool)
    completed = pyqtSignal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        process: QProcess | None = None,
        project_root: Path = PROJECT_ROOT,
        request_directory: Path | None = None,
        log_directory: Path | None = None,
        log_capacity: int = DEFAULT_LOG_CAPACITY,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.request_directory = (
            Path(request_directory) if request_directory is not None else Path(tempfile.gettempdir())
        )
        self.log_directory = (
            Path(log_directory)
            if log_directory is not None
            else self.project_root / "dist" / "release-logs"
        )
        self.process = process if process is not None else QProcess(self)
        self.cancel_timer = QTimer(self)
        self.cancel_timer.setSingleShot(True)
        self.cancel_timer.setInterval(5000)
        self.cancel_timer.timeout.connect(self.escalate_cancel)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(LOG_INTERVAL_MS)
        self._log_timer.timeout.connect(self.flush_log_batch)
        self._pending_logs: deque[str] = deque(maxlen=max(1, int(log_capacity)))
        self._stdout_partial = ""
        self._stderr_partial = ""
        self._last_sequence = 0
        self._last_progress = 0
        self._terminal_event: ReleaseEvent | None = None
        self._protocol_error = ""
        self._request_file: Path | None = None
        self._log_writer: _BackgroundLogWriter | None = None
        self._running = False
        self._finished = False
        self._mode = ReleaseMode.LOCAL_DEBUG
        self.result = ReleaseResult(
            mode=self._mode,
            stage=ReleaseStage.IDLE,
        )
        self.persistent_log_path: Path | None = None
        self._connect_process_signals()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def request_file(self) -> Path:
        if self._request_file is None:
            raise RuntimeError("release request has not been created")
        return self._request_file

    @property
    def pending_log_count(self) -> int:
        return len(self._pending_logs)

    @property
    def log_writer_active(self) -> bool:
        return self._log_writer is not None and self._log_writer.active

    def start(self, request: BuildRequest, proxy: ProxySelection) -> None:
        if self._running:
            raise RuntimeError("release process is already running")
        self._reset_protocol()
        self._mode = resolve_release_mode(
            request.target_version,
            request.remote,
            same_release_repair=request.same_release_repair,
            offline_debug=request.offline_debug,
        )
        errors = validate_build_request(request)
        if errors:
            raise ValueError("; ".join(errors))

        try:
            self._request_file = self._write_request_file(request)
            self.persistent_log_path = self._new_log_path(
                self._mode,
                request.target_version,
            )
            self._log_writer = _BackgroundLogWriter(self.persistent_log_path)
            environment = build_proxy_environment(proxy, os.environ)
            process_environment = QProcessEnvironment()
            for key, value in environment.items():
                process_environment.insert(str(key), str(value))
            arguments = [
                str(self.project_root / "packaging" / "build_release.py"),
                "--headless",
                "--request-file",
                str(self._request_file),
            ]
            self.process.setProgram(sys.executable)
            self.process.setArguments(arguments)
            self.process.setProcessEnvironment(process_environment)
            self.process.setWorkingDirectory(str(self.project_root))
            self._running = True
            self.running_changed.emit(True)
            self.process.start()
        except BaseException:
            self._running = False
            self.running_changed.emit(False)
            self._cleanup_request_file()
            self._close_log_writer()
            raise

    def feed_stdout(self, data: bytes | bytearray | str) -> None:
        self._stdout_partial = self._feed_stream(
            self._stdout_partial,
            self._decoded(data),
            structured=True,
        )

    def feed_stderr(self, data: bytes | bytearray | str) -> None:
        self._stderr_partial = self._feed_stream(
            self._stderr_partial,
            self._decoded(data),
            structured=False,
        )

    @pyqtSlot()
    def read_stdout(self) -> None:
        self.feed_stdout(bytes(self.process.readAllStandardOutput()))

    @pyqtSlot()
    def read_stderr(self) -> None:
        self.feed_stderr(bytes(self.process.readAllStandardError()))

    @pyqtSlot()
    def flush_log_batch(self) -> None:
        if not self._pending_logs:
            self._log_timer.stop()
            return
        lines = [
            self._pending_logs.popleft()
            for _ in range(min(MAX_LINES_PER_TICK, len(self._pending_logs)))
        ]
        self.log_lines_ready.emit(lines)
        if not self._pending_logs:
            self._log_timer.stop()

    @pyqtSlot()
    def cancel(self) -> None:
        if not self._running:
            return
        self.process.terminate()
        self.cancel_timer.start()
        self.stage_changed.emit(
            ReleaseStage.CANCELLED.value,
            self._last_progress,
            "Cancellation requested",
        )

    @pyqtSlot()
    def escalate_cancel(self) -> None:
        if not self._process_is_running():
            return
        process_id = int(self.process.processId())
        if not isinstance(self.process, QProcess):
            self.process.kill()
            return
        if sys.platform.startswith("win") and process_id > 0:
            QProcess.startDetached(
                "taskkill",
                ["/PID", str(process_id), "/T", "/F"],
            )
        else:
            self.process.kill()

    @pyqtSlot(int, QProcess.ExitStatus)
    def on_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancel_timer.stop()
        self._flush_partial_streams()
        self._running = False
        error = self._completion_error(exit_code, exit_status)
        terminal = self._terminal_event
        if not error and terminal is not None:
            self.result = ReleaseResult(
                mode=self._mode,
                stage=ReleaseStage.SUCCEEDED,
            )
        else:
            stage = terminal.stage if terminal is not None else ReleaseStage.FAILED
            if stage is ReleaseStage.SUCCEEDED:
                stage = ReleaseStage.FAILED
            terminal_error = error or self._terminal_error(terminal)
            self.result = ReleaseResult(
                mode=self._mode,
                stage=stage,
                errors=(terminal_error,) if terminal_error else (),
                error=terminal_error,
            )
        self._cleanup_request_file()
        self._close_log_writer()
        self.flush_log_batch()
        self.running_changed.emit(False)
        self.completed.emit(self.result)

    def shutdown(self) -> None:
        self.cancel_timer.stop()
        self._log_timer.stop()
        if self._process_is_running():
            self.process.terminate()
            self.escalate_cancel()
        self._running = False
        self._cleanup_request_file()
        self._close_log_writer()
        self._pending_logs.clear()

    def _connect_process_signals(self) -> None:
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

    def _reset_protocol(self) -> None:
        self._finished = False
        self._last_sequence = 0
        self._last_progress = 0
        self._terminal_event = None
        self._protocol_error = ""
        self._stdout_partial = ""
        self._stderr_partial = ""
        self.result = ReleaseResult(mode=self._mode, stage=ReleaseStage.IDLE)

    def _write_request_file(self, request: BuildRequest) -> Path:
        private_key_path = str(request.private_key_path or "")
        if (
            "-----BEGIN" in private_key_path
            or "\n" in private_key_path
            or "\r" in private_key_path
        ):
            raise ValueError("private key must be a path or reference")
        custom_proxy = str(request.custom_proxy or "")
        parsed_proxy = urlsplit(
            custom_proxy if "://" in custom_proxy else f"//{custom_proxy}"
        )
        if parsed_proxy.username is not None or parsed_proxy.password is not None:
            raise ValueError("proxy credentials must use an environment reference")

        self.request_directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=".ucrawl-release-",
            suffix=".json",
            dir=self.request_directory,
            text=True,
        )
        path = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    asdict(request),
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                stream.write("\n")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def _new_log_path(self, mode: ReleaseMode, version: str) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_mode = _SAFE_FILENAME.sub("_", mode.value)
        safe_version = _SAFE_FILENAME.sub("_", version)
        return self.log_directory / f"{timestamp}-{safe_mode}-{safe_version}.log"

    @staticmethod
    def _decoded(data: bytes | bytearray | str) -> str:
        if isinstance(data, str):
            return data
        return bytes(data).decode("utf-8", errors="replace")

    def _feed_stream(self, partial: str, text: str, *, structured: bool) -> str:
        combined = partial + text
        lines = combined.splitlines(keepends=True)
        trailing = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            trailing = lines.pop()
        for line in lines:
            self._accept_line(line.rstrip("\r\n"), structured=structured)
        return trailing

    def _accept_line(self, line: str, *, structured: bool) -> None:
        safe_line = redact_release_text(line)
        if self._log_writer is not None:
            self._log_writer.submit(safe_line)
        if structured and line.startswith(EVENT_PREFIX):
            try:
                event = parse_event_line(line)
            except (ValueError, TypeError, json.JSONDecodeError):
                self._set_protocol_error("malformed release event")
                return
            if event is None:
                self._set_protocol_error("malformed release event")
                return
            self._handle_event(event)
            return
        self._pending_logs.append(safe_line)
        if not self._log_timer.isActive():
            self._log_timer.start()

    def _handle_event(self, event: ReleaseEvent) -> None:
        if self._terminal_event is not None:
            label = (
                "duplicate final result event"
                if event.kind == "result"
                else "event received after final result event"
            )
            self._set_protocol_error(label)
            return
        if event.sequence != self._last_sequence + 1:
            self._set_protocol_error("release event sequence is out of order")
            return
        if event.progress < self._last_progress:
            self._set_protocol_error("release event progress is out of order")
            return
        if event.kind not in {"stage", "error", "result"}:
            self._set_protocol_error("unknown release event kind")
            return
        self._last_sequence = event.sequence
        self._last_progress = event.progress
        self.stage_changed.emit(
            event.stage.value,
            event.progress,
            event.message,
        )
        if event.kind == "error":
            self.error_reported.emit(event.message or "Release stage failed")
        if event.kind == "result":
            self._terminal_event = event

    def _set_protocol_error(self, message: str) -> None:
        if not self._protocol_error:
            self._protocol_error = redact_release_text(message)
            self.error_reported.emit(self._protocol_error)

    def _flush_partial_streams(self) -> None:
        if self._stdout_partial:
            self._accept_line(self._stdout_partial, structured=True)
            self._stdout_partial = ""
        if self._stderr_partial:
            self._accept_line(self._stderr_partial, structured=False)
            self._stderr_partial = ""

    def _completion_error(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> str:
        if self._protocol_error:
            return self._protocol_error
        if self._terminal_event is None:
            return "missing final result event"
        if exit_status != QProcess.ExitStatus.NormalExit:
            return "release process exited abnormally"
        if int(exit_code) != 0:
            return f"release process returned exit code {int(exit_code)}"
        if self._terminal_event.stage is not ReleaseStage.SUCCEEDED:
            return self._terminal_error(self._terminal_event)
        status = self._terminal_event.data.get("status")
        if status != "succeeded":
            return "final result event did not confirm success"
        return ""

    @staticmethod
    def _terminal_error(event: ReleaseEvent | None) -> str:
        if event is None:
            return "release process failed"
        data_error = event.data.get("error")
        if isinstance(data_error, str) and data_error:
            return redact_release_text(data_error)
        if event.message:
            return redact_release_text(event.message)
        if event.stage is ReleaseStage.CANCELLED:
            return "release process was cancelled"
        return f"release process reported {event.stage.value}"

    def _process_is_running(self) -> bool:
        try:
            return self.process.state() != QProcess.ProcessState.NotRunning
        except RuntimeError:
            return False

    def _cleanup_request_file(self) -> None:
        if self._request_file is None:
            return
        try:
            self._request_file.unlink(missing_ok=True)
        except OSError:
            self.error_reported.emit("release request file could not be deleted")
        finally:
            self._request_file = None

    def _close_log_writer(self) -> None:
        writer, self._log_writer = self._log_writer, None
        if writer is None:
            return
        writer.close()
        if writer.error:
            self.error_reported.emit(writer.error)

    @pyqtSlot(QProcess.ProcessError)
    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if error is QProcess.ProcessError.FailedToStart and not self._finished:
            self._set_protocol_error("release process failed to start")
            self.on_finished(-1, QProcess.ExitStatus.CrashExit)


class _ConfirmationDialog(ChromedDialog):
    def __init__(self, parent: QWidget, summary: str) -> None:
        super().__init__(
            parent,
            title="Confirm remote release actions",
            object_name="ReleaseRemoteConfirmation",
            body_margins=(20, 18, 20, 18),
            body_spacing=14,
        )
        label = QLabel(summary, self)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content_layout.addWidget(label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start release")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.content_layout.addWidget(buttons)
        self.setMinimumWidth(560)


def build_confirmation_summary(
    request: BuildRequest,
    mode: ReleaseMode,
    *,
    asset_names: Iterable[str],
) -> str:
    """Build a redacted summary containing only approved confirmation fields."""

    repository = _safe_repository_label(request.repository)
    notes_path = redact_release_text(str(request.release_notes_path or "").strip())
    assets = tuple(
        redact_release_text(Path(str(name)).name)
        for name in asset_names
        if str(name).strip()
    )
    values = (
        ("Version", redact_release_text(request.target_version)),
        ("Mode", mode.value),
        ("Tag", f"v{redact_release_text(request.target_version)}"),
        ("Repository", repository),
        ("Proxy", redact_release_text(request.proxy_label)),
        ("Release notes", notes_path or "(none)"),
        ("Assets", ", ".join(assets) if assets else "(none)"),
    )
    return "\n".join(f"{label}: {value}" for label, value in values)


def _safe_repository_label(repository: str) -> str:
    value = redact_release_text(str(repository or "").strip())
    if "://" not in value:
        return value
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


class ReleaseBuilderWindow(QWidget):
    """Top-level release builder with shared project chrome and theme."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        project_version: str | None = None,
        remote_loader: Callable[[str, Mapping[str, str]], RemoteReleaseInfo]
        | None = None,
        process_controller: ReleaseProcessController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReleaseBuilderWindow")
        self.setProperty("ucpThemeRoot", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("UniversalCrawler Release Builder")
        self.icon_path = str(release_builder_icon_path())
        self.setWindowIcon(QIcon(self.icon_path))
        self._is_dark = resolve_is_dark_theme(self)
        self._colors = theme_colors(self._is_dark)
        self.setPalette(build_palette(self._is_dark))
        self.remote_info = RemoteReleaseInfo.unknown()
        self._remote_loader = remote_loader or (
            lambda repository, environment: fetch_latest_release(
                repository,
                environment=environment,
            )
        )
        self._remote_generation = 0
        self._remote_thread: QThread | None = None
        self._remote_worker: _RemoteLoaderWorker | None = None
        self._accept_remote_results = True
        self._close_pending = False
        self._shutting_down = False
        self._mode: ReleaseMode | None = None
        self._project_version = project_version or read_project_version(PROJECT_ROOT)

        self.chrome_frame = WindowChromeFrame(
            title="UniversalCrawler Release Builder",
            icon=QIcon(self.icon_path),
            is_dark_theme=self._is_dark,
            show_minimize=True,
            show_maximize=True,
            show_close=True,
            parent=self,
        )
        self.window_title_bar = self.chrome_frame.title_bar
        self.window_title_bar.minimize_requested.connect(self.showMinimized)
        self.window_title_bar.maximize_restore_requested.connect(
            self._toggle_maximized
        )
        self.window_title_bar.close_requested.connect(self.close)
        self._window_chrome_controller = FramelessWindowChromeController(
            self,
            title_bar_getter=lambda: self.window_title_bar,
            toggle_maximized=self._toggle_maximized,
            resizable=True,
            minimizable=True,
            maximizable=True,
        )
        self._window_chrome_controller.set_window_flags()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.chrome_frame)
        self._build_body()

        self.process_controller = process_controller or ReleaseProcessController(
            self,
            project_root=PROJECT_ROOT,
        )
        self._connect_controller()
        self._connect_form()
        self._apply_theme()
        self._apply_initial_geometry()
        self.refresh_mode()
        self.start_remote_lookup()

    @property
    def remote_lookup_active(self) -> bool:
        thread = self._remote_thread
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            return False

    @staticmethod
    def constrained_geometry(available: QRect) -> QRect:
        width = min(1180, max(1, available.width()))
        height = min(820, max(1, available.height()))
        x = available.x() + (available.width() - width) // 2
        y = available.y() + (available.height() - height) // 2
        return QRect(x, y, width, height)

    def refresh_mode(self) -> None:
        request = self._request_from_controls()
        try:
            mode = resolve_release_mode(
                request.target_version,
                request.remote,
                same_release_repair=request.same_release_repair,
                offline_debug=request.offline_debug,
            )
        except ValueError as error:
            self._mode = None
            mode_name = (
                "remote_unknown"
                if str(error) == "remote release state is unknown"
                else "invalid"
            )
            self._set_mode_badge(mode_name)
        else:
            self._mode = mode
            self._set_mode_badge(mode.value)
            self._project_mode_controls(mode)
            request = self._request_from_controls()

        errors = validate_build_request(request)
        self.validation_label.setText("\n".join(errors))
        can_start = (
            self._mode is not None
            and not errors
            and not self.process_controller.running
        )
        self.start_button.setEnabled(can_start)
        self.cancel_button.setEnabled(self.process_controller.running)

    def start_remote_lookup(self) -> None:
        if self.remote_lookup_active or self._shutting_down:
            return
        self._remote_generation += 1
        generation = self._remote_generation
        self.remote_info = RemoteReleaseInfo.unknown()
        self.remote_version_label.setText("Checking...")
        self.refresh_remote_button.setEnabled(False)
        self.refresh_mode()
        try:
            environment = build_proxy_environment(
                self._proxy_selection(),
                os.environ,
            )
        except ValueError as error:
            self._on_remote_result(
                generation,
                RemoteReleaseInfo.unavailable(str(error)),
            )
            return

        thread = QThread()
        worker = _RemoteLoaderWorker(
            generation,
            self._remote_loader,
            self.repository_edit.text().strip(),
            environment,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_remote_result)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_remote_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        _ACTIVE_REMOTE_THREADS.add(thread)
        self._remote_thread = thread
        self._remote_worker = worker
        thread.start()

    def create_confirmation_dialog(self, summary: str) -> ChromedDialog:
        return _ConfirmationDialog(self, summary)

    def start_build(self) -> None:
        request = self._request_from_controls()
        errors = validate_build_request(request)
        if errors:
            self.validation_label.setText("\n".join(errors))
            self.refresh_mode()
            return
        try:
            mode = resolve_release_mode(
                request.target_version,
                request.remote,
                same_release_repair=request.same_release_repair,
                offline_debug=request.offline_debug,
            )
        except ValueError as error:
            self.validation_label.setText(str(error))
            self.refresh_mode()
            return
        if self._has_remote_writes(request):
            summary = build_confirmation_summary(
                request,
                mode,
                asset_names=self._asset_names(request),
            )
            dialog = self.create_confirmation_dialog(summary)
            if dialog.exec() != int(ChromedDialog.DialogCode.Accepted):
                return
        try:
            self.process_controller.start(request, self._proxy_selection())
        except (OSError, RuntimeError, ValueError) as error:
            self._on_process_error(redact_release_text(str(error)))

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._accept_remote_results = False
        self._remote_generation += 1
        thread = self._remote_thread
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass
        self.process_controller.shutdown()
        self._window_chrome_controller.uninstall()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._window_chrome_controller.install()
        self._window_chrome_controller.on_show_event()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.process_controller.running:
            self._close_pending = True
            self.process_controller.cancel()
            event.ignore()
            return
        self.shutdown()
        event.accept()

    def nativeEvent(self, event_type, message):  # noqa: N802
        hit_test = self._window_chrome_controller.handle_native_event(
            event_type,
            message,
        )
        if hit_test is not None:
            return True, hit_test
        return False, 0

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._window_chrome_controller.mouse_press_event(event):
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if self._window_chrome_controller.event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    def _build_body(self) -> None:
        scroll = QScrollArea(self.chrome_frame.body)
        scroll.setObjectName("ReleaseBuilderScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        content.setObjectName("ReleaseBuilderContent")
        sections = QVBoxLayout(content)
        sections.setContentsMargins(18, 16, 18, 18)
        sections.setSpacing(12)
        self.section_widgets: list[QGroupBox] = []

        self._build_version_section(sections)
        self._build_build_section(sections)
        self._build_signing_section(sections)
        self._build_release_section(sections)
        self._build_network_section(sections)
        self._build_execution_section(sections)
        sections.addStretch(1)
        scroll.setWidget(content)
        self.chrome_frame.body_layout.addWidget(scroll)

    def _new_section(self, title: str, sections: QVBoxLayout) -> QGroupBox:
        group = QGroupBox(title)
        group.setProperty("releaseSection", True)
        group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.section_widgets.append(group)
        sections.addWidget(group)
        return group

    def _build_version_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("Version", sections)
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        self.target_version_edit = QLineEdit(self._project_version)
        self.target_version_edit.setMinimumWidth(180)
        self.remote_version_label = QLabel("Not checked")
        self.remote_version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_remote_button = QPushButton("Refresh")
        remote_row = QHBoxLayout()
        remote_row.addWidget(self.remote_version_label, 1)
        remote_row.addWidget(self.refresh_remote_button)
        self.check_same_release_repair = QCheckBox("Allow same-release repair")
        self.check_offline_debug = QCheckBox("Explicit offline local debug")
        layout.addWidget(QLabel("Target version"), 0, 0)
        layout.addWidget(self.target_version_edit, 0, 1)
        layout.addWidget(QLabel("Latest remote"), 1, 0)
        layout.addLayout(remote_row, 1, 1)
        layout.addWidget(self.check_same_release_repair, 2, 1)
        layout.addWidget(self.check_offline_debug, 3, 1)

    def _build_build_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("Build", sections)
        layout = QHBoxLayout(group)
        self.check_apply_version = QCheckBox("Apply version")
        self.check_apply_version.setChecked(True)
        self.check_build_portable = QCheckBox("Portable")
        self.check_build_portable.setChecked(True)
        self.check_build_installer = QCheckBox("Installer")
        self.check_build_installer.setChecked(True)
        self.check_smoke_tests = QCheckBox("Smoke tests")
        self.check_smoke_tests.setChecked(True)
        for control in (
            self.check_apply_version,
            self.check_build_portable,
            self.check_build_installer,
            self.check_smoke_tests,
        ):
            layout.addWidget(control)
        layout.addStretch(1)

    def _build_signing_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("Signing", sections)
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        self.private_key_edit = QLineEdit()
        self.private_key_edit.setPlaceholderText("Private key path or env:REFERENCE")
        self.private_key_button = QPushButton("Choose")
        key_row = QHBoxLayout()
        key_row.addWidget(self.private_key_edit, 1)
        key_row.addWidget(self.private_key_button)
        self.check_generate_key = QCheckBox("Generate manifest key")
        self.check_rotate_trust_anchor = QCheckBox("Rotate trust anchor")
        self.check_sign_manifest = QCheckBox("Sign manifest")
        layout.addWidget(QLabel("Private key"), 0, 0)
        layout.addLayout(key_row, 0, 1)
        options = QHBoxLayout()
        options.addWidget(self.check_generate_key)
        options.addWidget(self.check_rotate_trust_anchor)
        options.addWidget(self.check_sign_manifest)
        options.addStretch(1)
        layout.addLayout(options, 1, 1)

    def _build_release_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("Git / Release", sections)
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        self.repository_edit = QLineEdit(DEFAULT_REPOSITORY)
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Release notes path")
        self.notes_button = QPushButton("Choose")
        notes_row = QHBoxLayout()
        notes_row.addWidget(self.notes_edit, 1)
        notes_row.addWidget(self.notes_button)
        layout.addWidget(QLabel("Repository"), 0, 0)
        layout.addWidget(self.repository_edit, 0, 1)
        layout.addWidget(QLabel("Release notes"), 1, 0)
        layout.addLayout(notes_row, 1, 1)
        self.check_commit_version = QCheckBox("Commit version")
        self.check_push_main = QCheckBox("Push main")
        self.check_create_tag = QCheckBox("Create/reuse tag")
        self.check_create_release = QCheckBox("Create/update release")
        self.check_upload_assets = QCheckBox("Upload assets")
        self.check_upload_public_key = QCheckBox("Upload public key")
        self.check_verify_remote = QCheckBox("Verify remote assets")
        option_grid = QGridLayout()
        for index, control in enumerate(
            (
                self.check_commit_version,
                self.check_push_main,
                self.check_create_tag,
                self.check_create_release,
                self.check_upload_assets,
                self.check_upload_public_key,
                self.check_verify_remote,
            )
        ):
            option_grid.addWidget(control, index // 4, index % 4)
        layout.addLayout(option_grid, 2, 1)
        self._remote_controls = (
            self.check_commit_version,
            self.check_push_main,
            self.check_create_tag,
            self.check_create_release,
            self.check_upload_assets,
            self.check_upload_public_key,
            self.check_verify_remote,
        )

    def _build_network_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("Network", sections)
        layout = QFormLayout(group)
        self.proxy_combo = QComboBox()
        for option in project_proxy_options():
            label = str(option.get("label") or option.get("value") or "")
            value = str(option.get("value") or label)
            self.proxy_combo.addItem(label, value)
        if self.proxy_combo.count() == 0:
            self.proxy_combo.addItem("System proxy", "System proxy")
            self.proxy_combo.addItem("Direct", "Direct")
            self.proxy_combo.addItem("Custom", "Custom")
        self.custom_proxy_edit = QLineEdit()
        self.custom_proxy_edit.setPlaceholderText("Proxy endpoint or env:REFERENCE")
        layout.addRow("Proxy", self.proxy_combo)
        layout.addRow("Custom endpoint", self.custom_proxy_edit)

    def _build_execution_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("Execution / Log", sections)
        layout = QVBoxLayout(group)
        status_row = QHBoxLayout()
        self.mode_badge = QLabel("remote_unknown")
        self.mode_badge.setObjectName("ReleaseModeBadge")
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.start_button = QPushButton("Start build")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        status_row.addWidget(self.mode_badge)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.start_button)
        status_row.addWidget(self.cancel_button)
        layout.addLayout(status_row)
        self.validation_label = QLabel()
        self.validation_label.setObjectName("ReleaseValidation")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        tools = QHBoxLayout()
        self.copy_log_button = QPushButton("Copy selection")
        self.export_log_button = QPushButton("Export copy")
        self.clear_log_button = QPushButton("Clear view")
        self.open_log_directory_button = QPushButton("Open log directory")
        for button in (
            self.copy_log_button,
            self.export_log_button,
            self.clear_log_button,
            self.open_log_directory_button,
        ):
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.log_panel = LogPanel()
        self.log_panel.setMinimumHeight(190)
        layout.addWidget(self.log_panel, 1)

    def _connect_form(self) -> None:
        for control in (
            self.check_same_release_repair,
            self.check_offline_debug,
            self.check_apply_version,
            self.check_build_portable,
            self.check_build_installer,
            self.check_smoke_tests,
            self.check_generate_key,
            self.check_rotate_trust_anchor,
            self.check_sign_manifest,
            self.check_commit_version,
            self.check_push_main,
            self.check_create_tag,
            self.check_create_release,
            self.check_upload_assets,
            self.check_upload_public_key,
            self.check_verify_remote,
        ):
            control.toggled.connect(self.refresh_mode)
        for edit in (
            self.target_version_edit,
            self.private_key_edit,
            self.repository_edit,
            self.notes_edit,
            self.custom_proxy_edit,
        ):
            edit.textChanged.connect(self.refresh_mode)
        self.proxy_combo.currentIndexChanged.connect(self._on_proxy_changed)
        self.refresh_remote_button.clicked.connect(self.start_remote_lookup)
        self.private_key_button.clicked.connect(self._choose_private_key)
        self.notes_button.clicked.connect(self._choose_release_notes)
        self.start_button.clicked.connect(self.start_build)
        self.cancel_button.clicked.connect(self.process_controller.cancel)
        self.copy_log_button.clicked.connect(self.log_panel.copy)
        self.export_log_button.clicked.connect(self._export_log_copy)
        self.clear_log_button.clicked.connect(self.log_panel.clear)
        self.open_log_directory_button.clicked.connect(self._open_log_directory)
        self._sync_custom_proxy_enabled()

    def _connect_controller(self) -> None:
        self.process_controller.log_lines_ready.connect(self.log_panel.append_logs)
        self.process_controller.stage_changed.connect(self._on_stage_changed)
        self.process_controller.error_reported.connect(self._on_process_error)
        self.process_controller.running_changed.connect(self._on_running_changed)
        self.process_controller.completed.connect(self._on_process_completed)

    def _apply_theme(self) -> None:
        apply_application_theme(self._is_dark)
        self.setPalette(build_palette(self._is_dark))
        self.chrome_frame.apply_theme(self._is_dark)
        self._colors = theme_colors(self._is_dark)
        base = self.styleSheet()
        semantic = f"""
        QWidget#ReleaseBuilderContent {{
            background: {self._colors["bg"]};
        }}
        QGroupBox[releaseSection="true"] {{
            background: {self._colors["panel"]};
            border: 1px solid {self._colors["border"]};
            border-radius: 6px;
            margin-top: 10px;
            padding: 12px;
        }}
        QGroupBox[releaseSection="true"]::title {{
            color: {self._colors["text"]};
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 5px;
        }}
        QLabel#ReleaseModeBadge {{
            color: {self._colors["accent"]};
            background: {self._colors["accent_soft"]};
            border: 1px solid {self._colors["border_strong"]};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QLabel#ReleaseValidation {{
            color: {self._colors["danger"]};
        }}
        """
        self.setStyleSheet(f"{base}\n{semantic}")

    def _apply_initial_geometry(self) -> None:
        app = QApplication.instance()
        screen = self.screen() or (app.primaryScreen() if app is not None else None)
        if screen is None:
            self.resize(1180, 820)
            self.setMinimumSize(880, 640)
            return
        available = screen.availableGeometry()
        geometry = self.constrained_geometry(available)
        self.setMinimumSize(
            min(880, geometry.width()),
            min(640, geometry.height()),
        )
        self.setGeometry(geometry)

    def _request_from_controls(self) -> BuildRequest:
        return BuildRequest(
            target_version=self.target_version_edit.text().strip(),
            repository=self.repository_edit.text().strip(),
            release_notes_path=self.notes_edit.text().strip(),
            build_portable=self.check_build_portable.isChecked(),
            build_installer=self.check_build_installer.isChecked(),
            run_smoke_tests=self.check_smoke_tests.isChecked(),
            same_release_repair=self.check_same_release_repair.isChecked(),
            offline_debug=self.check_offline_debug.isChecked(),
            apply_version=self.check_apply_version.isChecked(),
            generate_manifest_key=self.check_generate_key.isChecked(),
            rotate_trust_anchor=self.check_rotate_trust_anchor.isChecked(),
            private_key_path=self.private_key_edit.text().strip(),
            sign_manifest=self.check_sign_manifest.isChecked(),
            commit_version_changes=self.check_commit_version.isChecked(),
            push_main=self.check_push_main.isChecked(),
            create_or_reuse_tag=self.check_create_tag.isChecked(),
            create_or_update_release=self.check_create_release.isChecked(),
            upload_release_assets=self.check_upload_assets.isChecked(),
            upload_public_key=self.check_upload_public_key.isChecked(),
            verify_remote_assets=self.check_verify_remote.isChecked(),
            proxy_label=self._proxy_label(),
            custom_proxy=self.custom_proxy_edit.text().strip(),
            remote=self.remote_info,
        )

    def _proxy_label(self) -> str:
        data = self.proxy_combo.currentData()
        return str(data if data is not None else self.proxy_combo.currentText())

    def _proxy_selection(self) -> ProxySelection:
        return ProxySelection(
            label=self._proxy_label(),
            endpoint=self.custom_proxy_edit.text().strip(),
        )

    def _project_mode_controls(self, mode: ReleaseMode) -> None:
        local_mode = mode in {
            ReleaseMode.LOCAL_DEBUG,
            ReleaseMode.LOCAL_REBUILD,
            ReleaseMode.OFFLINE_DEBUG,
        }
        restricted_controls = self._remote_controls + (
            self.check_generate_key,
            self.check_rotate_trust_anchor,
            self.check_sign_manifest,
        )
        for control in restricted_controls:
            if local_mode and control.isChecked():
                blocker = QSignalBlocker(control)
                control.setChecked(False)
                del blocker
            control.setEnabled(not local_mode and not self.process_controller.running)
        signing_enabled = not local_mode and not self.process_controller.running
        self.private_key_edit.setEnabled(signing_enabled)
        self.private_key_button.setEnabled(signing_enabled)

    def _set_mode_badge(self, mode_name: str) -> None:
        self.mode_badge.setText(mode_name.replace("_", " ").title())
        self.mode_badge.setProperty("releaseMode", mode_name)
        self.mode_badge.style().unpolish(self.mode_badge)
        self.mode_badge.style().polish(self.mode_badge)

    @pyqtSlot(int, object)
    def _on_remote_result(
        self,
        generation: int,
        result: RemoteReleaseInfo,
    ) -> None:
        if (
            not self._accept_remote_results
            or generation != self._remote_generation
        ):
            return
        self.remote_info = result
        if result.is_available:
            self.remote_version_label.setText(result.version)
        else:
            self.remote_version_label.setText(
                result.error or "Remote release unknown"
            )
        self.refresh_mode()

    def _on_remote_thread_finished(self, thread: QThread) -> None:
        _ACTIVE_REMOTE_THREADS.discard(thread)
        if self._remote_thread is thread:
            self._remote_worker = None
            self.refresh_remote_button.setEnabled(not self._shutting_down)

    @pyqtSlot(str, int, str)
    def _on_stage_changed(
        self,
        stage: str,
        progress: int,
        message: str,
    ) -> None:
        self.progress_bar.setValue(progress)
        self.status_label.setText(message or stage.replace("_", " ").title())

    @pyqtSlot(str)
    def _on_process_error(self, message: str) -> None:
        self.status_label.setText(redact_release_text(message))

    @pyqtSlot(bool)
    def _on_running_changed(self, running: bool) -> None:
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(running)
        if not running:
            self.refresh_mode()

    @pyqtSlot(object)
    def _on_process_completed(self, result: ReleaseResult) -> None:
        if result.succeeded:
            self.status_label.setText("Release build succeeded")
            self.progress_bar.setValue(100)
        else:
            self.status_label.setText(
                redact_release_text(result.error or "Release build failed")
            )
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def _on_proxy_changed(self) -> None:
        self._sync_custom_proxy_enabled()
        self.refresh_mode()

    def _sync_custom_proxy_enabled(self) -> None:
        self.custom_proxy_edit.setEnabled(
            self._proxy_label() in {"自定义", "Custom", "custom", "Custom proxy"}
        )

    def _choose_private_key(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose private key",
            "",
            "Key files (*.pem *.key);;All files (*)",
        )
        if path:
            self.private_key_edit.setText(path)

    def _choose_release_notes(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose release notes",
            "",
            "Markdown (*.md);;Text files (*.txt);;All files (*)",
        )
        if path:
            self.notes_edit.setText(path)

    def _export_log_copy(self) -> None:
        source = self.process_controller.persistent_log_path
        default_name = source.name if source is not None else "release-build.log"
        destination, _filter = QFileDialog.getSaveFileName(
            self,
            "Export release log",
            default_name,
            "Log files (*.log);;All files (*)",
        )
        if not destination:
            return
        try:
            if source is not None and source.is_file():
                Path(destination).write_bytes(source.read_bytes())
            else:
                Path(destination).write_text(
                    self.log_panel.toPlainText(),
                    encoding="utf-8",
                )
        except OSError:
            QMessageBox.warning(self, "Export failed", "Could not export the log.")

    def _open_log_directory(self) -> None:
        directory = self.process_controller.log_directory
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    @staticmethod
    def _has_remote_writes(request: BuildRequest) -> bool:
        return any(
            (
                request.push_main,
                request.create_or_reuse_tag,
                request.create_or_update_release,
                request.upload_release_assets,
                request.upload_public_key,
            )
        )

    @staticmethod
    def _asset_names(request: BuildRequest) -> tuple[str, ...]:
        assets: list[str] = []
        if request.upload_release_assets:
            assets.extend(
                (
                    "UniversalCrawler-Setup.exe",
                    "latest.json",
                    "latest.json.sig",
                )
            )
        if request.upload_public_key:
            assets.append("manifest-public-key.pem")
        return tuple(assets)

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.chrome_frame.set_maximized(self.isMaximized())


def launch_release_builder_panel() -> int:
    """Launch the standalone release-builder application."""

    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(sys.argv)
    icon = QIcon(str(release_builder_icon_path()))
    if owns_application:
        app.setWindowIcon(icon)
    window = ReleaseBuilderWindow()
    window.show()
    return int(app.exec())


__all__ = [
    "ReleaseBuilderWindow",
    "ReleaseProcessController",
    "build_confirmation_summary",
    "launch_release_builder_panel",
]
