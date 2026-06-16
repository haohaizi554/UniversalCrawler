"""WebSocket 连接建立后的初始化流程。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.web.logging_utils import log_web_exception
from app.web.session_runtime import WebSessionContext


CreateTaskFn = Callable[[Awaitable[Any]], asyncio.Task[Any]]


class WebSocketBootstrapper:
    """封装 WebSocket 连接成功后的首包与初始化副作用。"""

    async def initialize(
        self,
        ws: WebSocket,
        context: WebSessionContext,
        *,
        create_task_fn: CreateTaskFn | None = None,
    ) -> None:
        await self._send_initial_snapshot(ws, context)
        await self._kickoff_initial_scan(context, create_task_fn=create_task_fn)

    async def _send_initial_snapshot(self, ws: WebSocket, context: WebSessionContext) -> None:
        controller = context.controller
        try:
            await ws.send_text(json.dumps({"type": "init_state", "data": controller.get_state()}, ensure_ascii=False))
            await ws.send_text(json.dumps({"type": "platforms", "data": controller.get_platforms()}, ensure_ascii=False))
            await ws.send_text(json.dumps({"type": "config", "data": controller.get_config()}, ensure_ascii=False))
            await self._replay_cached_videos(ws, controller)
        except Exception as exc:
            log_web_exception("WebSocketBootstrapper", "send_initial_snapshot", exc)

    async def _replay_cached_videos(self, ws: WebSocket, controller: Any) -> None:
        videos = getattr(controller, "videos", None)
        if not videos:
            return
        for item in videos.values():
            payload = self._serialize_cached_item(controller, item)
            if not payload:
                continue
            await ws.send_text(json.dumps({"type": "item_found", "data": payload}, ensure_ascii=False))

    @staticmethod
    def _serialize_cached_item(controller: Any, item: Any) -> dict[str, Any] | None:
        if item is None:
            return None
        if isinstance(item, dict):
            return item
        serializer = getattr(controller, "_video_item_to_dict", None)
        if callable(serializer):
            try:
                return serializer(item)
            except Exception:
                pass
        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            try:
                result = to_dict()
                return result if isinstance(result, dict) else None
            except Exception:
                return None
        return None

    async def _kickoff_initial_scan(
        self,
        context: WebSessionContext,
        *,
        create_task_fn: CreateTaskFn | None = None,
    ) -> None:
        controller = context.controller
        create_task = create_task_fn or asyncio.create_task
        try:
            controller.bridge.set_loop(asyncio.get_running_loop())
            spider = getattr(controller, "current_spider", None)
            spider_running = bool(spider and spider.isRunning())
            if spider_running or getattr(controller, "_bootstrap_scan_pending", False):
                return
            controller._bootstrap_scan_pending = True

            async def _run_initial_scan() -> None:
                try:
                    await controller.async_scan_local_dir()
                finally:
                    controller._bootstrap_scan_pending = False

            create_task(_run_initial_scan())
        except Exception as exc:
            log_web_exception("WebSocketBootstrapper", "kickoff_initial_scan", exc)
