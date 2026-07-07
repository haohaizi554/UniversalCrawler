from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar


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
        self._pending: RequestT | None = None
        self._shutdown = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, request: RequestT) -> None:
        with self._condition:
            if self._shutdown:
                return
            self._pending = request
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
                request = self._pending
                self._pending = None
            if request is None:
                continue
            result = self._process(request)
            if result is None:
                continue
            try:
                self._on_result(result)
            except RuntimeError:
                return
