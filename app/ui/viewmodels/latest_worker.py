from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar

from app.debug_logger import debug_logger


RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class LatestRequestWorker(Generic[RequestT, ResultT]):
    """Single-slot worker: newer requests replace older pending work."""

    def __init__(
        self,
        *,
        name: str,
        on_result: Callable[[ResultT], None],
        process: Callable[[RequestT], ResultT | None],
    ) -> None:
        self._on_result = on_result
        self._process = process
        self._condition = threading.Condition()
        self._pending: tuple[int, RequestT] | None = None
        self._generation = 0
        self._shutdown = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, request: RequestT) -> None:
        with self._condition:
            if self._shutdown:
                return
            self._generation += 1
            self._pending = (self._generation, request)
            self._condition.notify()

    def shutdown(self) -> None:
        with self._condition:
            self._shutdown = True
            self._condition.notify()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._shutdown:
                    self._condition.wait()
                if self._shutdown:
                    return
                generation, request = self._pending
                self._pending = None
            if request is None:
                continue
            try:
                result = self._process(request)
            except Exception as exc:
                debug_logger.log_exception(
                    "LatestRequestWorker",
                    "process",
                    exc,
                    details={"request_type": type(request).__name__},
                )
                continue
            if result is None:
                continue
            with self._condition:
                if generation != self._generation or self._shutdown:
                    continue
            try:
                self._on_result(result)
            except RuntimeError:
                return
            except Exception as exc:
                debug_logger.log_exception(
                    "LatestRequestWorker",
                    "on_result",
                    exc,
                    details={"result_type": type(result).__name__},
                )
