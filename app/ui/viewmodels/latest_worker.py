from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar

from app.debug_logger import debug_logger


RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class LatestRequestWorker(Generic[RequestT, ResultT]):
    """单槽后台 worker：新请求覆盖尚未开始处理的旧请求。

    适合前端快照、日志筛选、分页这类“只关心最新 UI 状态”的任务，
    可以把高频刷新合并掉，避免 UI 线程被过期结果反复打断。
    """

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
            # generation 是结果防抖边界：即便旧请求已经开始执行，也只能在
            # 自己仍是最新一代时回调 on_result。
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
                # 丢弃执行期间被新请求取代的结果，避免页面回滚到旧筛选/旧分页。
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
