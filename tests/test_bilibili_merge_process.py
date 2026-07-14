"""Deterministic coverage for the Bilibili ffmpeg merge lifecycle."""

from __future__ import annotations

import subprocess
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.downloaders import bilibili as bilibili_module
from app.core.downloaders.bilibili import BilibiliDownloader
from app.exceptions import DownloaderStoppedError, MergeError


MERGE_COMMAND = ["ffmpeg", "-i", "video.m4s", "output.mp4"]


class IterableStderr:
    """Blocking stderr stream that reaches EOF only after process shutdown."""

    def __init__(self, lines: list[str] | tuple[str, ...] = ()) -> None:
        self._lines = tuple(lines)
        self._released = threading.Event()
        self.completed = threading.Event()
        self.iteration_count = 0

    def __iter__(self):
        self.iteration_count += 1
        try:
            yield from self._lines
            if not self._released.wait(timeout=1.0):
                raise AssertionError("stderr stayed open after process shutdown")
        finally:
            self.completed.set()

    def release(self) -> None:
        self._released.set()


class TrackingThread(threading.Thread):
    """Real worker thread that records the production cleanup join."""

    def __init__(self, *args: Any, join_timeouts: list[float | None], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._join_timeouts = join_timeouts

    def join(self, timeout: float | None = None) -> None:
        self._join_timeouts.append(timeout)
        super().join(timeout)


class ThreadFactory:
    def __init__(self) -> None:
        self.join_timeouts: list[float | None] = []

    def __call__(self, *args: Any, **kwargs: Any) -> TrackingThread:
        return TrackingThread(*args, join_timeouts=self.join_timeouts, **kwargs)


class FakeProcess:
    """Complete Popen lifecycle double used by the production merge loop."""

    def __init__(
        self,
        poll_results: list[int | None],
        *,
        stderr_lines: list[str] | tuple[str, ...] = (),
        wait_results: list[int | BaseException] | None = None,
    ) -> None:
        self.stderr = IterableStderr(stderr_lines)
        self.returncode: int | None = None
        self._poll_results = list(poll_results)
        self._wait_results = list(wait_results or [])
        self.poll_calls = 0
        self.wait_timeouts: list[float | int | None] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        if not self._poll_results:
            raise AssertionError("unexpected extra poll")
        self.poll_calls += 1
        result = self._poll_results.pop(0)
        if result is not None:
            self.returncode = result
            self.stderr.release()
        return result

    def wait(self, timeout: float | int | None = None) -> int:
        self.wait_timeouts.append(timeout)
        result: int | BaseException = (
            self._wait_results.pop(0) if self._wait_results else 0
        )
        if isinstance(result, BaseException):
            raise result
        self.returncode = result
        self.stderr.release()
        return result

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.stderr.release()


class PopenFactory:
    def __init__(
        self, process: FakeProcess | None = None, *, error: OSError | None = None
    ) -> None:
        self.process = process
        self.error = error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.thread_factory = ThreadFactory()

    def __call__(self, *args: Any, **kwargs: Any) -> FakeProcess:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        assert self.process is not None
        return self.process


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def __call__(self) -> float:
        if not self._values:
            raise AssertionError("unexpected monotonic clock read")
        return self._values.pop(0)


def install_merge_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    process: FakeProcess | None = None,
    startup_error: OSError | None = None,
    clock_values: list[float],
    timeout_setting: object = 300,
) -> tuple[PopenFactory, list[float], object]:
    factory = PopenFactory(process, error=startup_error)
    sleep_calls: list[float] = []
    startupinfo = object()
    monkeypatch.setattr(
        bilibili_module,
        "subprocess",
        SimpleNamespace(
            Popen=factory,
            DEVNULL=subprocess.DEVNULL,
            PIPE=subprocess.PIPE,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )
    monkeypatch.setattr(
        bilibili_module, "build_hidden_startupinfo", lambda: startupinfo
    )
    monkeypatch.setattr(
        bilibili_module,
        "time",
        SimpleNamespace(
            monotonic=FakeClock(clock_values),
            sleep=sleep_calls.append,
        ),
    )
    monkeypatch.setattr(
        bilibili_module,
        "threading",
        SimpleNamespace(Thread=factory.thread_factory),
    )
    monkeypatch.setattr(
        bilibili_module,
        "cfg",
        SimpleNamespace(get=lambda _section, _key, _default=None: timeout_setting),
    )
    return factory, sleep_calls, startupinfo


def run_merge(
    tmp_path,
    *,
    progress_callback=lambda *_args, **_kwargs: None,
    check_stop_func=lambda: False,
) -> None:
    BilibiliDownloader()._run_merge_process(
        list(MERGE_COMMAND),
        save_path=str(tmp_path / "output.mp4"),
        temp_v=str(tmp_path / "video.m4s"),
        temp_a=str(tmp_path / "audio.m4s"),
        progress_callback=progress_callback,
        check_stop_func=check_stop_func,
        bytes_downloaded=75,
        bytes_total=100,
        trace_id="merge-trace",
    )


def test_merge_process_success_emits_real_file_progress_and_exits(
    monkeypatch, tmp_path
):
    (tmp_path / "video.m4s").write_bytes(b"v" * 60)
    (tmp_path / "audio.m4s").write_bytes(b"a" * 40)
    (tmp_path / "output.mp4").write_bytes(b"m" * 50)
    process = FakeProcess([None, 0], stderr_lines=["frame=1\n"])
    factory, sleep_calls, startupinfo = install_merge_runtime(
        monkeypatch,
        process=process,
        clock_values=[0.0, 0.1, 1.1],
        timeout_setting=120,
    )
    progress_events: list[tuple[int, dict[str, Any]]] = []

    run_merge(
        tmp_path,
        progress_callback=lambda value, **details: progress_events.append(
            (value, details)
        ),
    )

    assert progress_events == [
        (
            94,
            {
                "bytes_downloaded": 75,
                "bytes_total": 100,
                "phase": "merging",
                "phase_message": "ffmpeg 合并音视频中",
                "write_status": "写入完成",
                "merge_status": "合并中",
            },
        )
    ]
    assert sleep_calls == [0.2]
    assert process.poll_calls == 2
    assert process.wait_timeouts == []
    assert process.terminate_calls == process.kill_calls == 0
    assert process.stderr.iteration_count == 1
    assert process.stderr.completed.is_set()
    assert factory.thread_factory.join_timeouts == [1.0]
    popen_args, popen_kwargs = factory.calls[0]
    assert popen_args == (MERGE_COMMAND,)
    assert popen_kwargs == {
        "startupinfo": startupinfo,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }


def test_merge_process_nonzero_exit_reports_only_last_eight_stderr_lines(
    monkeypatch, tmp_path
):
    stderr_lines = [f"line-{index}\n" for index in range(1, 26)] + ["  \n"]
    process = FakeProcess([9], stderr_lines=stderr_lines)
    factory, sleep_calls, _startupinfo = install_merge_runtime(
        monkeypatch,
        process=process,
        clock_values=[0.0],
    )
    log_events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bilibili_module.debug_logger,
        "log",
        lambda *args, **kwargs: log_events.append(kwargs),
    )

    with pytest.raises(MergeError, match=r"code=9") as raised:
        run_merge(tmp_path)

    expected_tail = "\n".join(f"line-{index}" for index in range(18, 26))
    assert expected_tail in str(raised.value)
    assert "line-17\n" not in str(raised.value)
    assert log_events == [
        {
            "component": "BilibiliDownloader",
            "action": "merge_error",
            "level": "ERROR",
            "message": "ffmpeg 合并音视频失败",
            "status_code": "BILI_MERGE_ERROR",
            "details": {"return_code": 9, "stderr_tail": expected_tail},
            "trace_id": "merge-trace",
        }
    ]
    assert sleep_calls == []
    assert process.terminate_calls == process.kill_calls == 0
    assert process.stderr.completed.is_set()
    assert factory.thread_factory.join_timeouts == [1.0]


def test_merge_process_stop_terminates_then_kills_when_waits_expire(
    monkeypatch, tmp_path
):
    process = FakeProcess(
        [None],
        wait_results=[
            subprocess.TimeoutExpired(MERGE_COMMAND, timeout=5),
            subprocess.TimeoutExpired(MERGE_COMMAND, timeout=2),
        ],
    )
    factory, sleep_calls, _startupinfo = install_merge_runtime(
        monkeypatch,
        process=process,
        clock_values=[0.0],
    )

    with pytest.raises(DownloaderStoppedError, match="用户停止下载"):
        run_merge(tmp_path, check_stop_func=lambda: True)

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_timeouts == [5, 2]
    assert process.stderr.completed.is_set()
    assert factory.thread_factory.join_timeouts == [1.0]
    assert sleep_calls == []


def test_merge_process_timeout_kills_process_and_reports_stderr(monkeypatch, tmp_path):
    process = FakeProcess(
        [None],
        stderr_lines=[" frame stalled \n"],
        wait_results=[-9],
    )
    factory, sleep_calls, _startupinfo = install_merge_runtime(
        monkeypatch,
        process=process,
        clock_values=[0.0, 30.5],
        timeout_setting=1,
    )
    log_events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bilibili_module.debug_logger,
        "log",
        lambda *args, **kwargs: log_events.append(kwargs),
    )

    with pytest.raises(MergeError, match="30s") as raised:
        run_merge(tmp_path)

    assert "frame stalled" in str(raised.value)
    assert process.terminate_calls == 0
    assert process.kill_calls == 1
    assert process.wait_timeouts == [2]
    assert process.stderr.completed.is_set()
    assert factory.thread_factory.join_timeouts == [1.0]
    assert log_events[0]["action"] == "merge_timeout"
    assert log_events[0]["details"] == {
        "timeout_seconds": 30,
        "stderr_tail": "frame stalled",
    }
    assert sleep_calls == []


def test_merge_process_timeout_preserves_merge_error_when_kill_wait_expires(
    monkeypatch, tmp_path
):
    process = FakeProcess(
        [None],
        stderr_lines=[" encoder stuck \n"],
        wait_results=[subprocess.TimeoutExpired(MERGE_COMMAND, timeout=2)],
    )
    factory, sleep_calls, _startupinfo = install_merge_runtime(
        monkeypatch,
        process=process,
        clock_values=[0.0, 30.5],
        timeout_setting=1,
    )

    with pytest.raises(MergeError, match="30s") as raised:
        run_merge(tmp_path)

    assert "encoder stuck" in str(raised.value)
    assert process.kill_calls == 1
    assert process.wait_timeouts == [2]
    assert process.stderr.completed.is_set()
    assert factory.thread_factory.join_timeouts == [1.0]
    assert sleep_calls == []


def test_merge_process_wraps_popen_startup_oserror(monkeypatch, tmp_path):
    startup_error = OSError("ffmpeg executable missing")
    factory, sleep_calls, _startupinfo = install_merge_runtime(
        monkeypatch,
        startup_error=startup_error,
        clock_values=[],
    )

    with pytest.raises(MergeError, match="ffmpeg executable missing") as raised:
        run_merge(tmp_path)

    assert raised.value.__cause__ is startup_error
    assert len(factory.calls) == 1
    assert sleep_calls == []


def test_merge_target_size_ignores_oserror_for_missing_sidecar(tmp_path):
    video_path = tmp_path / "video.m4s"
    video_path.write_bytes(b"video")

    total = BilibiliDownloader._merge_target_size(
        str(video_path), str(tmp_path / "missing-audio.m4s")
    )

    assert total == 5


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("not-a-number", 300), (object(), 300), ("5", 30)],
    ids=["invalid-value", "invalid-type", "minimum"],
)
def test_merge_timeout_uses_safe_default_and_minimum(monkeypatch, configured, expected):
    monkeypatch.setattr(
        bilibili_module,
        "cfg",
        SimpleNamespace(get=lambda _section, _key, _default=None: configured),
    )

    assert BilibiliDownloader._merge_timeout_seconds() == expected


@pytest.mark.parametrize(
    ("target_total", "fallback", "expected"),
    [(0, 0, 91), (-1, 96, 96), (0, 999, 98)],
)
def test_merge_progress_without_target_is_bounded(
    monkeypatch, target_total, fallback, expected
):
    def unexpected_getsize(_path):
        raise AssertionError("target-free progress must not inspect the output")

    monkeypatch.setattr(bilibili_module.os.path, "getsize", unexpected_getsize)

    assert (
        BilibiliDownloader._merge_progress_from_file(
            "output.mp4", target_total, fallback=fallback
        )
        == expected
    )


@pytest.mark.parametrize(
    ("output_size", "expected"),
    [(-25, 91), (0, 91), (50, 94), (100, 98), (150, 98)],
)
def test_merge_progress_from_file_clamps_output_ratio(
    monkeypatch, output_size, expected
):
    monkeypatch.setattr(bilibili_module.os.path, "getsize", lambda _path: output_size)

    assert (
        BilibiliDownloader._merge_progress_from_file("output.mp4", 100, fallback=95)
        == expected
    )


def test_merge_progress_from_missing_output_uses_lower_bound(monkeypatch):
    def missing_output(_path):
        raise OSError("output not created yet")

    monkeypatch.setattr(bilibili_module.os.path, "getsize", missing_output)

    assert (
        BilibiliDownloader._merge_progress_from_file("output.mp4", 100, fallback=97)
        == 91
    )
