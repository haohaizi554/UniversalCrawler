from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar

from app.debug_logger import debug_logger


RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class SequentialRequestWorker(Generic[RequestT, ResultT]):
    """FIFO 后台 worker：按提交顺序处理每个请求。

    适合导出、文件写入等不能被“最新请求”覆盖的操作；与
    LatestRequestWorker 的语义刻意区分。
    """

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
            self._pending.clear()
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
            try:
                result = self._process(request)
            except Exception as exc:
                debug_logger.log_exception(
                    "SequentialRequestWorker",
                    "process",
                    exc,
                    details={"request_type": type(request).__name__},
                )
                continue
            with self._condition:
                if self._shutdown:
                    return
            try:
                self._on_result(result)
            except RuntimeError:
                return
            except Exception as exc:
                debug_logger.log_exception(
                    "SequentialRequestWorker",
                    "on_result",
                    exc,
                    details={"result_type": type(result).__name__},
                )
