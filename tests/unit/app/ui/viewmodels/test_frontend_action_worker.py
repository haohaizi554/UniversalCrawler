from __future__ import annotations

import threading

from app.ui.viewmodels.frontend_action_worker import FrontendActionRequest, FrontendActionWorker


class RecordingService:
    def __init__(self) -> None:
        self.thread_id: int | None = None

    def handle_action(self, action: str, payload: dict) -> dict:
        self.thread_id = threading.get_ident()
        return {"status": "ok", "action": action, "payload": payload}


def test_frontend_action_worker_runs_handle_action_off_calling_thread() -> None:
    service = RecordingService()
    event = threading.Event()
    results = []
    worker = FrontendActionWorker(lambda result: (results.append(result), event.set()))
    try:
        worker.submit(
            FrontendActionRequest(
                sequence=1,
                service=service,
                service_token=id(service),
                action="log_operation",
                payload={"operation": "refresh"},
            )
        )

        assert event.wait(2)
        assert service.thread_id is not None
        assert service.thread_id != threading.get_ident()
        assert results[0].result["status"] == "ok"
        assert results[0].payload == {"operation": "refresh"}
    finally:
        worker.shutdown()


def test_frontend_action_worker_reports_action_errors() -> None:
    class BrokenService:
        def handle_action(self, _action: str, _payload: dict) -> dict:
            raise RuntimeError("boom")

    event = threading.Event()
    results = []
    service = BrokenService()
    worker = FrontendActionWorker(lambda result: (results.append(result), event.set()))
    try:
        worker.submit(
            FrontendActionRequest(
                sequence=2,
                service=service,
                service_token=id(service),
                action="log_operation",
                payload={"operation": "export"},
            )
        )

        assert event.wait(2)
        assert results[0].result["status"] == "error"
        assert "boom" in results[0].result["message"]
    finally:
        worker.shutdown()
