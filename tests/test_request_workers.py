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
