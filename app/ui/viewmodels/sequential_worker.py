from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar


RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class SequentialRequestWorker(Generic[RequestT, ResultT]):
    """FIFO worker for ordered background requests."""

    def __init__(
        self,
        *,
        name: str,
        on_result: Callable[[ResultT], None],
        process: Callable[[RequestT], ResultT],
    ) -> None:
        self._on_result = on_result
        self._process = process
        self._condition = threading.Condition()
        self._pending: deque[RequestT] = deque()
        self._shutdown = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, request: RequestT) -> None:
        with self._condition:
            if self._shutdown:
                return
            self._pending.append(request)
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
                while not self._pending and not self._shutdown:
                    self._condition.wait()
                if self._shutdown:
                    return
                request = self._pending.popleft()
            result = self._process(request)
            try:
                self._on_result(result)
            except RuntimeError:
                return
