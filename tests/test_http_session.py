from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from app.web.http_session import HttpSessionCoordinator
from app.web.session_runtime import WebSessionRegistry


class HttpSessionCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: SimpleNamespace(current_save_dir="downloads"),
            workflow_factory=lambda _controller, _send: object(),
        )
        self.coordinator = HttpSessionCoordinator(
            session_registry=self.registry,
            session_cookie_name="ucrawl_session",
            session_token_cookie_name="ucrawl_session_token",
            csrf_cookie_name="ucrawl_csrf_token",
            session_token_header="X-Ucrawl-Session-Token",
            default_session_id="default",
        )

    @staticmethod
    def _request(*, client_host: str, cookies=None, headers=None, method="GET"):
        return SimpleNamespace(
            client=SimpleNamespace(host=client_host),
            cookies=cookies or {},
            headers=headers or {},
            method=method,
            state=SimpleNamespace(),
            url=SimpleNamespace(
                path="/api/frontend/state",
                scheme="http",
                netloc="127.0.0.1:8000",
                hostname="127.0.0.1",
            ),
        )

    async def test_remote_api_request_without_session_token_is_rejected(self) -> None:
        request = self._request(client_host="192.0.2.10")

        async def call_next(_request):
            return JSONResponse({"status": "ok"})

        response = await self.coordinator.handle(
            request,
            call_next,
        )

        self.assertEqual(response.status_code, 403)

    async def test_local_api_request_without_token_keeps_desktop_compatibility(self) -> None:
        request = self._request(client_host="127.0.0.1")

        async def call_next(_request):
            return JSONResponse({"status": "ok"})

        response = await self.coordinator.handle(
            request,
            call_next,
        )

        self.assertEqual(response.status_code, 200)

    def test_csrf_cookie_is_accepted_as_double_submit_session_token(self) -> None:
        context = self.registry.get_or_create("session-a")
        request = self._request(
            client_host="192.0.2.10",
            cookies={
                "ucrawl_session": "session-a",
                "ucrawl_csrf_token": context.csrf_token,
            },
        )
        request.state.session_context = context

        self.assertTrue(self.coordinator.has_valid_session_token(request, context))


if __name__ == "__main__":
    unittest.main()
