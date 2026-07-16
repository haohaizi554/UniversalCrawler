from __future__ import annotations

import threading

from app.ui.viewmodels.latest_worker import LatestRequestWorker
from app.ui.viewmodels.sequential_worker import SequentialRequestWorker


def test_latest_request_worker_survives_process_exception() -> None:
    ready = threading.Event()
    received: list[str] = []

    def process(request: str) -> str:
        if request == "boom":
            raise RuntimeError("boom")
        return request

    def on_result(result: str) -> None:
        received.append(result)
        ready.set()

    worker = LatestRequestWorker(name="test-latest-worker", on_result=on_result, process=process)
    try:
        worker.submit("boom")
        worker.submit("ok")
        assert ready.wait(timeout=2)
    finally:
        worker.shutdown()

    assert received[-1] == "ok"


def test_latest_request_worker_drops_result_when_newer_request_arrives_during_processing() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    latest_delivered = threading.Event()
    received: list[str] = []

    def process(request: str) -> str:
        if request == "first":
            first_started.set()
            assert release_first.wait(timeout=2)
        return request

    def on_result(result: str) -> None:
        received.append(result)
        if result == "second":
            latest_delivered.set()

    worker = LatestRequestWorker(name="test-latest-drop-worker", on_result=on_result, process=process)
    try:
        worker.submit("first")
        assert first_started.wait(timeout=2)
        worker.submit("second")
        release_first.set()
        assert latest_delivered.wait(timeout=2)
    finally:
        worker.shutdown()

    assert received == ["second"]


def test_sequential_request_worker_survives_process_exception_and_keeps_order() -> None:
    ready = threading.Event()
    received: list[str] = []

    def process(request: str) -> str:
        if request == "boom":
            raise RuntimeError("boom")
        return request

    def on_result(result: str) -> None:
        received.append(result)
        if received == ["first", "second"]:
            ready.set()

    worker = SequentialRequestWorker(name="test-sequential-worker", on_result=on_result, process=process)
    try:
        worker.submit("first")
        worker.submit("boom")
        worker.submit("second")
        assert ready.wait(timeout=2)
    finally:
        worker.shutdown()

    assert received == ["first", "second"]


def test_worker_result_callback_exception_does_not_kill_worker() -> None:
    ready = threading.Event()
    attempts: list[str] = []

    def on_result(result: str) -> None:
        attempts.append(result)
        if result == "first":
            raise ValueError("callback boom")
        ready.set()

    worker = SequentialRequestWorker(
        name="test-callback-worker",
        on_result=on_result,
        process=lambda request: request,
    )
    try:
        worker.submit("first")
        worker.submit("second")
        assert ready.wait(timeout=2)
    finally:
        worker.shutdown()

    assert attempts == ["first", "second"]


def test_sequential_worker_does_not_callback_after_shutdown() -> None:
    started = threading.Event()
    release = threading.Event()
    received: list[str] = []

    def process(request: str) -> str:
        started.set()
        assert release.wait(timeout=3)
        return request

    worker = SequentialRequestWorker(
        name="test-sequential-shutdown-worker",
        on_result=received.append,
        process=process,
    )
    worker.submit("late-result")
    assert started.wait(timeout=2)

    worker.shutdown()
    release.set()
    worker._thread.join(timeout=2)

    assert received == []
