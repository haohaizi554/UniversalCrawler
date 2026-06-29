"""Workflow 型 Web 路由服务。"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Request

from app.web.api_result import error_result

class WebWorkflowRouteService:
    """封装 crawl/download 等基于 session workflow 的路由委派。"""

    def __init__(self, *, get_request_context: Callable[[Request], Any]) -> None:
        self._get_request_context = get_request_context

    @staticmethod
    def _normalize_authorized_save_dir(context: Any, body: dict) -> dict | None:
        save_dir = body.get("save_dir")
        if save_dir is None or not isinstance(save_dir, str):
            return body
        try:
            normalized = context.require_directory(save_dir)
        except PermissionError as exc:
            return error_result(str(exc), http_status=403)
        payload = dict(body)
        payload["save_dir"] = normalized
        return payload

    async def start_crawl(self, request: Request, body: dict) -> dict:
        context = self._get_request_context(request)
        payload = self._normalize_authorized_save_dir(context, body)
        if isinstance(payload, dict) and payload.get("status") == "error":
            return payload
        return await context.workflow.start_crawl(payload, log_error=False)

    async def stop_crawl(self, request: Request) -> dict:
        self._get_request_context(request).controller.stop_crawl()
        return {"status": "ok"}

    async def select_tasks(self, request: Request, body: dict) -> dict:
        return await self._get_request_context(request).workflow.select_tasks(body, log_error=False)

    async def direct_download(self, request: Request, body: dict) -> dict:
        context = self._get_request_context(request)
        payload = self._normalize_authorized_save_dir(context, body)
        if isinstance(payload, dict) and payload.get("status") == "error":
            return payload
        return await context.workflow.direct_download(payload, log_error=False)
