"""WebSocket 连接建立后的初始化流程。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.web.logging_utils import log_web_exception
from app.web.session_runtime import WebSessionContext

CreateTaskFn = Callable[[Awaitable[Any]], asyncio.Task[Any]]

async def _run_controller_worker_call(func: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)

def _encode_message(event_type: str, data: Any) -> str:
    return json.dumps({"type": event_type, "data": data}, ensure_ascii=False)

async def _send_json(ws: WebSocket, event_type: str, data: Any) -> None:
    text = await _run_controller_worker_call(_encode_message, event_type, data)
    await ws.send_text(text)

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
            state = await _run_controller_worker_call(controller.get_state)
            await _send_json(ws, "init_state", state)
            getter = getattr(controller, "get_frontend_state", None)
            if callable(getter):
                snapshot = await _run_controller_worker_call(getter)
                await _send_json(ws, "frontend_state", snapshot)
                marker = getattr(getattr(controller, "bridge", None), "mark_frontend_version_sent", None)
                if callable(marker):
                    marker(snapshot.get("version", 0) if isinstance(snapshot, dict) else 0)
            platforms = await _run_controller_worker_call(controller.get_platforms)
            await _send_json(ws, "platforms", platforms)
            config = await _run_controller_worker_call(controller.get_config)
            await _send_json(ws, "config", config)
            await self._replay_cached_videos(ws, controller)
        except Exception as exc:
            log_web_exception("WebSocketBootstrapper", "send_initial_snapshot", exc)

    async def _replay_cached_videos(self, ws: WebSocket, controller: Any) -> None:
        payloads = await _run_controller_worker_call(self._cached_video_payloads, controller)
        for payload in payloads:
            await _send_json(ws, "item_found", payload)

    def _cached_video_payloads(self, controller: Any) -> list[dict[str, Any]]:
        snapshot = getattr(controller, "_video_items_snapshot", None)
        videos = snapshot() if callable(snapshot) else getattr(controller, "videos", None)
        if not videos:
            return []
        payloads: list[dict[str, Any]] = []
        for item in videos.values():
            payload = self._serialize_cached_item(controller, item)
            if not payload:
                continue
            payloads.append(payload)
        return payloads

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
            except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
                log_web_exception("WebSocketBootstrapper", "serialize_cached_item", exc)
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

            task = create_task(_run_initial_scan())
            tracker = getattr(context, "track_background_task", None)
            if callable(tracker):
                tracker(task)
        except Exception as exc:
            controller._bootstrap_scan_pending = False
            log_web_exception("WebSocketBootstrapper", "kickoff_initial_scan", exc)
