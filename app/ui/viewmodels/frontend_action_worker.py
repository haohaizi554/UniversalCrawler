from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.debug_logger import debug_logger
from app.ui.viewmodels.sequential_worker import SequentialRequestWorker


@dataclass(frozen=True)
class FrontendActionRequest:
    sequence: int
    service: Any
    service_token: int
    action: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class FrontendActionResult:
    sequence: int
    service_token: int
    action: str
    payload: dict[str, Any]
    result: dict[str, Any]


class FrontendActionWorker:
    """Sequential worker for GUI actions that may touch disk, cache, or OS APIs."""

    def __init__(self, on_result: Callable[[FrontendActionResult], None]) -> None:
        self._worker = SequentialRequestWorker(
            name="frontend-action-worker",
            on_result=on_result,
            process=self._process,
        )

    def submit(self, request: FrontendActionRequest) -> None:
        self._worker.submit(request)

    def shutdown(self) -> None:
        self._worker.shutdown()

    @staticmethod
    def _process(request: FrontendActionRequest) -> FrontendActionResult:
        payload = dict(request.payload or {})
        try:
            handler = getattr(request.service, "handle_action", None)
            if not callable(handler):
                result: dict[str, Any] = {"status": "error", "message": "frontend action service is unavailable"}
            else:
                raw_result = handler(request.action, payload)
                result = raw_result if isinstance(raw_result, dict) else {"status": "ok", "data": raw_result}
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendActionWorker",
                request.action,
                exc,
                details={"sequence": request.sequence, "payload_keys": sorted(payload.keys())},
            )
            result = {"status": "error", "message": str(exc)}
        return FrontendActionResult(
            sequence=request.sequence,
            service_token=request.service_token,
            action=request.action,
            payload=payload,
            result=result,
        )
