"""WebSocket 路由装配。"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, WebSocket

def build_ws_router(
    *,
    session_binder,
    connection_manager,
    bootstrapper,
    ws_runtime,
    create_task_provider: Callable[[], object],
) -> APIRouter:

    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        binding = await session_binder.bind(ws)
        if binding is None:
            return
        await connection_manager.connect(ws, binding.session_id)
        await bootstrapper.initialize(ws, binding.context, create_task_fn=create_task_provider())
        await ws_runtime.run(ws, binding.context)

    return router
