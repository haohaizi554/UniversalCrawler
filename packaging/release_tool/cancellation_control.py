"""Filesystem handshake that linearizes release cancellation and publication."""

from __future__ import annotations

import ctypes
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any


CANCEL_MARKER = "cancel.requested"
IRREVERSIBLE_MARKER = "irreversible.started"
_PROCESS_JOB_NAME = re.compile(
    r"^Local\\UniversalCrawlerRelease-[0-9a-f]{32}$"
)
_ERROR_ALREADY_EXISTS = 183
_JOB_OBJECT_ASSIGN_PROCESS = 0x0001
_JOB_OBJECT_QUERY = 0x0004
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DUPLICATE_CLOSE_SOURCE = 0x00000001
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_EVENT_PREFIX = "@@UCRAWL_RELEASE_EVENT@@"
_BOOTSTRAP_LAYOUT = (
    "--release-job-bootstrap",
    "--job-name",
    "--script",
    "--request-file",
    "--control-directory",
)


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobObjectBasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class CancellationControlError(RuntimeError):
    """The cancellation channel cannot prove that a process signal is safe."""


def _windows_kernel32() -> Any:
    if not sys.platform.startswith("win"):
        raise CancellationControlError(
            "release process jobs are unavailable on this platform"
        )
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenJobObjectW.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.OpenJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.DuplicateHandle.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.DuplicateHandle.restype = wintypes.BOOL
        kernel32.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
    except (AttributeError, OSError, TypeError, ValueError) as error:
        raise CancellationControlError(
            "release process jobs are unavailable"
        ) from error
    return kernel32


def _windows_error(message: str) -> CancellationControlError:
    error_code = ctypes.get_last_error()
    return CancellationControlError(f"{message} (Windows error {error_code})")


def _close_windows_handle(kernel32: Any, handle: Any) -> None:
    if handle and not kernel32.CloseHandle(handle):
        raise _windows_error("release process job handle could not be closed")


def _assign_windows_process(kernel32: Any, job_handle: Any, process_handle: Any) -> None:
    already_assigned = wintypes.BOOL()
    if not kernel32.IsProcessInJob(
        process_handle,
        job_handle,
        ctypes.byref(already_assigned),
    ):
        raise _windows_error("release process job membership could not be verified")
    if already_assigned.value:
        return
    if not kernel32.AssignProcessToJobObject(job_handle, process_handle):
        raise _windows_error("release process could not join its process job")


def _attach_control_diagnostic(primary: BaseException, diagnostic: str) -> None:
    try:
        add_note = getattr(primary, "add_note", None)
    except BaseException:
        return
    if callable(add_note):
        try:
            add_note(diagnostic)
        except BaseException:
            pass


class WindowsReleaseProcessJob:
    """Own a Windows Job Object that contains the entire release process tree."""

    def __init__(self, *, name: str, handle: Any, kernel32: Any) -> None:
        self.name = name
        self._handle = handle
        self._kernel32 = kernel32

    @classmethod
    def create(cls) -> "WindowsReleaseProcessJob":
        kernel32 = _windows_kernel32()
        name = f"Local\\UniversalCrawlerRelease-{uuid.uuid4().hex}"
        ctypes.set_last_error(0)
        handle = kernel32.CreateJobObjectW(None, name)
        if not handle:
            raise _windows_error("release process job could not be created")
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            try:
                _close_windows_handle(kernel32, handle)
            finally:
                raise CancellationControlError(
                    "release process job name unexpectedly already exists"
                ) from None
        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            try:
                error = _windows_error(
                    "release process job safety policy could not be applied"
                )
            finally:
                try:
                    _close_windows_handle(kernel32, handle)
                except CancellationControlError:
                    pass
            raise error
        return cls(name=name, handle=handle, kernel32=kernel32)

    def assign_process(self, process_id: int) -> None:
        if isinstance(process_id, bool) or not isinstance(process_id, int):
            raise CancellationControlError("release process id is invalid")
        if process_id <= 0:
            raise CancellationControlError("release process id is invalid")
        handle = self._require_handle()
        process_handle = self._kernel32.OpenProcess(
            _PROCESS_TERMINATE
            | _PROCESS_SET_QUOTA
            | _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id,
        )
        if not process_handle:
            raise _windows_error("release process could not be opened for assignment")
        assignment_error: BaseException | None = None
        try:
            _assign_windows_process(self._kernel32, handle, process_handle)
        except BaseException as error:
            assignment_error = error
        try:
            _close_windows_handle(self._kernel32, process_handle)
        except BaseException:
            if assignment_error is None:
                raise
            _attach_control_diagnostic(
                assignment_error,
                "process handle cleanup failed: "
                "release process job handle could not be closed",
            )
        if assignment_error is not None:
            raise assignment_error

    def terminate(self) -> None:
        if not self._kernel32.TerminateJobObject(self._require_handle(), 1):
            raise _windows_error("release process job could not be terminated")

    def has_active_processes(self) -> bool:
        accounting = _JobObjectBasicAccountingInformation()
        if not self._kernel32.QueryInformationJobObject(
            self._require_handle(),
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise _windows_error("release process job state could not be read")
        return int(accounting.ActiveProcesses) > 0

    def close(self) -> None:
        handle = self._handle
        if not handle:
            return
        _close_windows_handle(self._kernel32, handle)
        self._handle = None

    def force_close(self) -> None:
        """Close through DUPLICATE_CLOSE_SOURCE after ordinary close retries.

        Windows guarantees that the source handle is closed regardless of the
        DuplicateHandle return status. Passing no target process creates no
        replacement handle, so KILL_ON_JOB_CLOSE still observes the last close.
        """

        handle = self._handle
        if not handle:
            return
        self._kernel32.DuplicateHandle(
            self._kernel32.GetCurrentProcess(),
            handle,
            None,
            None,
            0,
            False,
            _DUPLICATE_CLOSE_SOURCE,
        )
        self._handle = None

    def _require_handle(self) -> Any:
        if not self._handle:
            raise CancellationControlError("release process job is closed")
        return self._handle

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:
            pass


def join_windows_process_job(name: str) -> None:
    """Join the named parent-owned Job before release work starts."""

    normalized = str(name)
    if not _PROCESS_JOB_NAME.fullmatch(normalized):
        raise CancellationControlError("release process job name is invalid")
    kernel32 = _windows_kernel32()
    handle = kernel32.OpenJobObjectW(
        _JOB_OBJECT_ASSIGN_PROCESS | _JOB_OBJECT_QUERY,
        False,
        normalized,
    )
    if not handle:
        raise _windows_error("release process job could not be opened")
    assignment_error: BaseException | None = None
    try:
        _assign_windows_process(
            kernel32,
            handle,
            kernel32.GetCurrentProcess(),
        )
    except BaseException as error:
        assignment_error = error
    try:
        _close_windows_handle(kernel32, handle)
    except BaseException:
        if assignment_error is None:
            raise
        _attach_control_diagnostic(
            assignment_error,
            "process job cleanup failed: "
            "release process job handle could not be closed",
        )
    if assignment_error is not None:
        raise assignment_error


def run_windows_release_bootstrap(argv: list[str]) -> int:
    """Join the Job before enabling site imports and running release code."""

    values = list(argv)
    if len(values) != 9:
        print("invalid release process bootstrap arguments", file=sys.stderr)
        return 2
    layout = tuple(values[index] for index in (0, 1, 3, 5, 7))
    if layout != _BOOTSTRAP_LAYOUT:
        print("invalid release process bootstrap arguments", file=sys.stderr)
        return 2
    job_name, script, request_file, control_directory = values[2::2]
    try:
        join_windows_process_job(job_name)
    except (CancellationControlError, OSError, RuntimeError, TypeError, ValueError):
        try:
            Path(request_file).unlink(missing_ok=True)
        except OSError:
            pass
        _emit_bootstrap_failure()
        return 1

    # The controller invokes this module with ``python -S``. Only after the
    # process is contained may third-party site imports and release code run.
    import runpy
    import site

    site.main()
    sys.argv = [
        script,
        "--headless",
        "--request-file",
        request_file,
        "--control-directory",
        control_directory,
        "--job-name",
        job_name,
    ]
    runpy.run_path(script, run_name="__main__")
    return 0


def _emit_bootstrap_failure() -> None:
    from datetime import UTC, datetime

    message = "release process job bootstrap failed"
    events = (
        ("stage", "preflight", "", {}),
        ("error", "preflight", message, {}),
        ("stage", "failed", "", {}),
        ("result", "failed", "", {"status": "failed", "error": message}),
    )
    for sequence, (kind, stage, event_message, data) in enumerate(events, 1):
        payload = {
            "data": data,
            "kind": kind,
            "message": event_message,
            "progress": 0,
            "sequence": sequence,
            "stage": stage,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        print(_EVENT_PREFIX + json.dumps(payload, sort_keys=True), flush=True)


class ReleaseCancellationControl:
    """Coordinate one parent process and one release child through atomic markers."""

    def __init__(self, directory: Path) -> None:
        try:
            resolved = Path(directory).resolve(strict=True)
            if not resolved.is_dir():
                raise OSError("control path is not a directory")
        except (OSError, RuntimeError, ValueError) as error:
            raise CancellationControlError(
                "release cancellation control is unavailable"
            ) from error
        self.directory = resolved

    @classmethod
    def create(cls, parent: Path) -> "ReleaseCancellationControl":
        try:
            root = Path(parent).resolve(strict=True)
            if not root.is_dir():
                raise OSError("control parent is not a directory")
            directory = Path(
                tempfile.mkdtemp(
                    prefix=".ucrawl-release-control-",
                    dir=root,
                )
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise CancellationControlError(
                "release cancellation control could not be created"
            ) from error
        return cls(directory)

    @property
    def cancel_path(self) -> Path:
        return self.directory / CANCEL_MARKER

    @property
    def irreversible_path(self) -> Path:
        return self.directory / IRREVERSIBLE_MARKER

    def request_cancel(self) -> bool:
        """Publish cancellation first, then report whether signalling stays safe."""

        self._create_marker(self.cancel_path, b"cancel\n")
        return not self.is_irreversible()

    def begin_irreversible(self) -> bool:
        """Publish the irreversible point first, then reject an earlier cancel."""

        self._create_marker(self.irreversible_path, b"irreversible\n")
        return not self.is_cancel_requested()

    def is_cancel_requested(self) -> bool:
        return self._marker_exists(self.cancel_path)

    def is_irreversible(self) -> bool:
        return self._marker_exists(self.irreversible_path)

    def may_signal_process(self) -> bool:
        """Fail closed unless cancellation exists and publication has not begun."""

        return self.is_cancel_requested() and not self.is_irreversible()

    def cleanup(self) -> None:
        """Remove only protocol-owned files and the now-empty control directory."""

        failed = False
        for marker in (self.cancel_path, self.irreversible_path):
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                failed = True
        try:
            self.directory.rmdir()
        except OSError:
            failed = True
        if failed:
            raise CancellationControlError(
                "release cancellation control could not be deleted"
            )

    def _create_marker(self, path: Path, payload: bytes) -> None:
        self._require_directory()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            if not self._marker_exists(path):
                raise CancellationControlError(
                    "release cancellation control is inconsistent"
                ) from None
            return
        except OSError as error:
            raise CancellationControlError(
                "release cancellation control could not be updated"
            ) from error
        update_error: OSError | None = None
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except OSError as error:
            update_error = error
        try:
            os.close(descriptor)
        except OSError as error:
            if update_error is None:
                update_error = error
        if update_error is not None:
            raise CancellationControlError(
                "release cancellation control could not be updated"
            ) from update_error

    def _marker_exists(self, path: Path) -> bool:
        self._require_directory()
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise CancellationControlError(
                "release cancellation control could not be read"
            ) from error
        # Any unexpected object at a marker path is treated as present. This is
        # safer than following it or assuming cancellation/signalling is absent.
        return True

    def _require_directory(self) -> None:
        try:
            mode = self.directory.lstat().st_mode
        except OSError as error:
            raise CancellationControlError(
                "release cancellation control is unavailable"
            ) from error
        if not stat.S_ISDIR(mode):
            raise CancellationControlError(
                "release cancellation control is unavailable"
            )


__all__ = [
    "CANCEL_MARKER",
    "IRREVERSIBLE_MARKER",
    "CancellationControlError",
    "ReleaseCancellationControl",
    "WindowsReleaseProcessJob",
    "join_windows_process_job",
    "run_windows_release_bootstrap",
]


if __name__ == "__main__":
    raise SystemExit(run_windows_release_bootstrap(sys.argv[1:]))
