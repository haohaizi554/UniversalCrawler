from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.web.ws_router import build_ws_router


class WebSocketRouterTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _endpoint(*, binding, connect=None, initialize=None, run=None):
        session_binder = SimpleNamespace(bind=AsyncMock(return_value=binding))
        connection_manager = SimpleNamespace(
            connect=connect or AsyncMock(),
        )
        bootstrapper = SimpleNamespace(
            initialize=initialize or AsyncMock(),
        )
        ws_runtime = SimpleNamespace(run=run or AsyncMock())
        router = build_ws_router(
            session_binder=session_binder,
            connection_manager=connection_manager,
            bootstrapper=bootstrapper,
            ws_runtime=ws_runtime,
            create_task_provider=lambda: object(),
        )
        endpoint = next(route.endpoint for route in router.routes if route.path == "/ws")
        return endpoint

    async def test_connection_failure_releases_bound_session_once(self):
        binding = SimpleNamespace(
            session_id="session-a",
            context=object(),
            release=Mock(),
        )
        endpoint = self._endpoint(
            binding=binding,
            connect=AsyncMock(side_effect=RuntimeError("connect failed")),
        )

        with self.assertRaisesRegex(RuntimeError, "connect failed"):
            await endpoint(object())

        binding.release.assert_called_once_with()

    async def test_normal_runtime_completion_releases_bound_session_once(self):
        binding = SimpleNamespace(
            session_id="session-a",
            context=object(),
            release=Mock(),
        )
        endpoint = self._endpoint(binding=binding)

        await endpoint(object())

        binding.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
