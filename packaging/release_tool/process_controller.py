"""Qt process, protocol, cancellation, and audit-log ownership for releases."""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PyQt6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)

from .events import EVENT_PREFIX, ReleaseEvent, parse_event_line, redact_release_text
from .models import BuildRequest, ReleaseMode, ReleaseResult, ReleaseStage
from .modes import resolve_release_mode, validate_build_request
from .proxy import ProxySelection, build_proxy_environment


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_INTERVAL_MS = 50
MAX_LINES_PER_TICK = 200
DEFAULT_LOG_CAPACITY = 5000
WRITER_CAPACITY = 4096
WRITER_CLOSE_TIMEOUT_SECONDS = 0.25
WRITER_ABANDON_TIMEOUT_SECONDS = 5.0
WRITER_CLOSE_POLL_MS = 50
TASKKILL_CONFIRMATION_MS = 250
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _default_stream_factory(path: Path, *args: Any, **kwargs: Any):
    return path.open(*args, **kwargs)


class _BackgroundLogWriter:
    """Write redacted log lines on a bounded worker queue."""

    def __init__(
        self,
        path: Path,
        *,
        capacity: int = WRITER_CAPACITY,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self._stream_factory = stream_factory or _default_stream_factory
        self._queue: queue.Queue[str] = queue.Queue(maxsize=max(1, int(capacity)))
        self._stop = threading.Event()
        self._drop_lock = threading.Lock()
        self._dropped = 0
        self.error = ""
        self._thread = threading.Thread(
            target=self._run,
            name="release-log-writer",
            daemon=True,
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
            with self._drop_lock:
                self._dropped += 1

    def close(
        self,
        *,
        timeout_seconds: float = WRITER_CLOSE_TIMEOUT_SECONDS,
    ) -> bool:
        self._stop.set()
        self._thread.join(max(0.0, float(timeout_seconds)))
        return not self._thread.is_alive()

    def _run(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._stream_factory(
                self.path,
                "a",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                while not self._stop.is_set() or not self._queue.empty():
                    try:
                        line = self._queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    stream.write(f"{line}\n")
                    self._queue.task_done()
                with self._drop_lock:
                    dropped = self._dropped
                if dropped:
                    stream.write(
                        f"[release log dropped {dropped} lines during a burst]\n"
                    )
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
    """Own one release child process until every lifecycle resource is closed."""

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
        writer_factory: Callable[[Path], _BackgroundLogWriter] | None = None,
        writer_close_timeout_seconds: float = WRITER_CLOSE_TIMEOUT_SECONDS,
        writer_abandon_timeout_seconds: float = WRITER_ABANDON_TIMEOUT_SECONDS,
        taskkill_process_factory: Callable[[QObject], QProcess] | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.request_directory = (
            Path(request_directory)
            if request_directory is not None
            else Path(tempfile.gettempdir())
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
        self._writer_close_timer = QTimer(self)
        self._writer_close_timer.setInterval(WRITER_CLOSE_POLL_MS)
        self._writer_close_timer.timeout.connect(self._poll_writer_close)
        self._taskkill_confirmation_timer = QTimer(self)
        self._taskkill_confirmation_timer.setSingleShot(True)
        self._taskkill_confirmation_timer.setInterval(TASKKILL_CONFIRMATION_MS)
        self._taskkill_confirmation_timer.timeout.connect(
            self._confirm_target_after_taskkill
        )
        self._pending_logs: deque[str] = deque(maxlen=max(1, int(log_capacity)))
        self._stdout_partial = ""
        self._stderr_partial = ""
        self._last_sequence = 0
        self._last_progress = 0
        self._terminal_event: ReleaseEvent | None = None
        self._protocol_error = ""
        self._fatal_event_error = ""
        self._request_file: Path | None = None
        self._writer_factory = writer_factory or _BackgroundLogWriter
        self._writer_close_timeout_seconds = max(
            0.0,
            float(writer_close_timeout_seconds),
        )
        self._writer_abandon_timeout_seconds = max(
            0.0,
            float(writer_abandon_timeout_seconds),
        )
        self._writer_close_deadline: float | None = None
        self._log_writer: _BackgroundLogWriter | None = None
        self._writer_failure_reported = False
        self.audit_log_warning = ""
        self._taskkill_process_factory = taskkill_process_factory or QProcess
        self._taskkill_process: QProcess | None = None
        self._running = False
        self._finished = False
        self._completion_pending = False
        self._completed_emitted = False
        self._cancel_requested = False
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

    @property
    def shutdown_complete(self) -> bool:
        return (
            not self._running
            and not self._completion_pending
            and self._log_writer is None
            and not self._taskkill_is_running()
        )

    def start(self, request: BuildRequest, proxy: ProxySelection) -> None:
        if self._running or self._completion_pending:
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
            self._log_writer = self._writer_factory(self.persistent_log_path)
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
        except BaseException as error:
            self._running = False
            self.running_changed.emit(False)
            self._cleanup_request_file()
            self._mark_result_failed(redact_release_text(str(error)))
            self._completion_pending = True
            self._finish_writer_or_defer()
            self._maybe_emit_completed()
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
        if not self._cancel_requested:
            self._cancel_requested = True
            self.process.terminate()
            self.cancel_timer.start()
            self.stage_changed.emit(
                ReleaseStage.CANCELLED.value,
                self._last_progress,
                "Cancellation requested",
            )

    @pyqtSlot()
    def escalate_cancel(self) -> None:
        if not self._running or not self._target_process_is_running():
            return
        process_id = int(self.process.processId())
        if not isinstance(self.process, QProcess):
            self.process.kill()
            return
        if sys.platform.startswith("win") and process_id > 0:
            self._start_taskkill(process_id)
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
        self.read_stdout()
        self.read_stderr()
        self._flush_partial_streams()
        self._finished = True
        self.cancel_timer.stop()
        self._taskkill_confirmation_timer.stop()
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
        self.flush_log_batch()
        self._completion_pending = True
        self.running_changed.emit(False)
        self._finish_writer_or_defer()
        self._maybe_emit_completed()

    def shutdown(self) -> bool:
        if self._running:
            self.cancel()
            return False
        if self._completion_pending:
            self._finish_writer_or_defer()
            self._maybe_emit_completed()
            return self.shutdown_complete
        self.cancel_timer.stop()
        self._log_timer.stop()
        self._taskkill_confirmation_timer.stop()
        self._cleanup_request_file()
        if self._log_writer is not None:
            self._completion_pending = True
            self._finish_writer_or_defer()
            self._maybe_emit_completed()
        return self.shutdown_complete

    def _connect_process_signals(self) -> None:
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

    def _reset_protocol(self) -> None:
        self._finished = False
        self._completion_pending = False
        self._completed_emitted = False
        self._cancel_requested = False
        self._last_sequence = 0
        self._last_progress = 0
        self._terminal_event = None
        self._protocol_error = ""
        self._fatal_event_error = ""
        self._stdout_partial = ""
        self._stderr_partial = ""
        self._writer_failure_reported = False
        self._writer_close_deadline = None
        self.audit_log_warning = ""
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
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        nonce = uuid.uuid4().hex[:8]
        safe_mode = _SAFE_FILENAME.sub("_", mode.value)
        safe_version = _SAFE_FILENAME.sub("_", version)
        return (
            self.log_directory
            / f"{timestamp}-{nonce}-{safe_mode}-{safe_version}.log"
        )

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
        safe_message = redact_release_text(event.message)
        self.stage_changed.emit(
            event.stage.value,
            event.progress,
            safe_message,
        )
        if event.kind == "error":
            if not self._fatal_event_error:
                self._fatal_event_error = safe_message or "release error event"
            self.error_reported.emit(self._fatal_event_error)
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
        if self._fatal_event_error:
            return self._fatal_event_error
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

    def _target_process_is_running(self) -> bool:
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
            self.error_reported.emit(
                "release request file could not be deleted"
            )
        finally:
            self._request_file = None

    def _finish_writer_or_defer(self) -> None:
        writer = self._log_writer
        if writer is None:
            return
        closed = writer.close(
            timeout_seconds=self._writer_close_timeout_seconds,
        )
        self._record_writer_failure(writer)
        if closed:
            self._log_writer = None
            self._writer_close_deadline = None
            self._writer_close_timer.stop()
        else:
            if self._writer_close_deadline is None:
                self._writer_close_deadline = (
                    time.monotonic() + self._writer_abandon_timeout_seconds
                )
            if time.monotonic() >= self._writer_close_deadline:
                self._abandon_log_writer()
                return
        if self._log_writer is not None and not self._writer_close_timer.isActive():
            self._writer_close_timer.start()

    @pyqtSlot()
    def _poll_writer_close(self) -> None:
        writer = self._log_writer
        if writer is None:
            self._writer_close_timer.stop()
            self._maybe_emit_completed()
            return
        if writer.close(timeout_seconds=0.0):
            self._record_writer_failure(writer)
            self._log_writer = None
            self._writer_close_deadline = None
            self._writer_close_timer.stop()
            self._maybe_emit_completed()
            return
        deadline = self._writer_close_deadline
        if deadline is not None and time.monotonic() >= deadline:
            self._abandon_log_writer()
            self._maybe_emit_completed()

    def _record_writer_failure(self, writer: _BackgroundLogWriter) -> None:
        if not writer.error or self._writer_failure_reported:
            return
        self._writer_failure_reported = True
        self.error_reported.emit(writer.error)
        self._mark_result_failed(writer.error)

    def _abandon_log_writer(self) -> None:
        if self._log_writer is None:
            return
        self.audit_log_warning = (
            "release audit log did not close before the shutdown deadline; "
            "the log may be incomplete"
        )
        self.error_reported.emit(self.audit_log_warning)
        self._log_writer = None
        self._writer_close_deadline = None
        self._writer_close_timer.stop()

    def _mark_result_failed(self, message: str) -> None:
        safe_message = redact_release_text(message)
        self.result = ReleaseResult(
            mode=self._mode,
            stage=ReleaseStage.FAILED,
            errors=(safe_message,),
            error=safe_message,
        )

    def _maybe_emit_completed(self) -> None:
        if (
            not self._completion_pending
            or self._completed_emitted
            or self._log_writer is not None
            or self._taskkill_is_running()
        ):
            return
        self._completion_pending = False
        self._completed_emitted = True
        self.completed.emit(self.result)

    def _start_taskkill(self, process_id: int) -> None:
        if self._taskkill_is_running():
            return
        taskkill = self._taskkill_process_factory(self)
        taskkill.setProgram("taskkill")
        taskkill.setArguments(["/PID", str(process_id), "/T", "/F"])
        taskkill.finished.connect(self._on_taskkill_finished)
        taskkill.errorOccurred.connect(self._on_taskkill_error)
        self._taskkill_process = taskkill
        taskkill.start()

    def _taskkill_is_running(self) -> bool:
        taskkill = self._taskkill_process
        if taskkill is None:
            return False
        try:
            return taskkill.state() != QProcess.ProcessState.NotRunning
        except RuntimeError:
            return False

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_taskkill_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        taskkill, self._taskkill_process = self._taskkill_process, None
        if taskkill is not None:
            taskkill.deleteLater()
        if (
            exit_status != QProcess.ExitStatus.NormalExit
            or int(exit_code) != 0
        ) and self._running:
            self.process.kill()
        elif self._running:
            self._taskkill_confirmation_timer.start()
        self._maybe_emit_completed()

    @pyqtSlot(QProcess.ProcessError)
    def _on_taskkill_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._running:
            taskkill, self._taskkill_process = self._taskkill_process, None
            if taskkill is not None:
                taskkill.deleteLater()
            self.process.kill()

    @pyqtSlot()
    def _confirm_target_after_taskkill(self) -> None:
        if not self._running:
            return
        if self._target_process_is_running():
            self.process.kill()

    @pyqtSlot(QProcess.ProcessError)
    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and not self._finished:
            self._set_protocol_error("release process failed to start")
            self.on_finished(-1, QProcess.ExitStatus.CrashExit)


__all__ = ["ReleaseProcessController"]
