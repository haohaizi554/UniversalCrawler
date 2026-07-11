"""HTTP REST 路由装配。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.web.api_result import error_result, finalize_api_result
from app.web.controller_route_service import require_valid_video_id


def _finalize_route_result(payload: Any, *, enforce_statuses: set[int] | None = None) -> Any:
    """Preserve legacy 200 error bodies except for explicit security boundaries."""
    if not isinstance(payload, dict) or not (payload.get("status") == "error" or "error" in payload):
        return payload
    status_code = int(payload.get("http_status", 400))
    if status_code in (enforce_statuses or set()):
        return finalize_api_result(payload)
    body = dict(payload)
    body.pop("http_status", None)
    return body

class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="allow")

class ConfigUpdatesRequest(RootModel[dict[str, dict[str, Any]]]):
    pass

class FrontendActionRequest(_RequestModel):
    action: str = Field(..., min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    frontend_version: int | None = Field(default=0, ge=0)


async def _run_controller_worker_call(func: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)

def build_rest_router(
    *,
    get_request_context: Callable[[Request], Any],
    search_service,
    workflow_route_service,
    controller_route_service,
    directory_service,
    file_response_service,
) -> APIRouter:
    """构建 Web HTTP 路由。"""

    router = APIRouter()

    @router.get("/api/ping")
    async def ping():
        from cli import __version__

        return {"status": "ok", "version": __version__}

    @router.get("/api/session/bootstrap")
    async def bootstrap_session(request: Request):
        context = get_request_context(request)
        return {"status": "ok", "session_id": context.session_id}

    @router.get("/api/platforms")
    async def get_platforms(request: Request):
        return await _run_controller_worker_call(get_request_context(request).controller.get_platforms)

    @router.get("/api/config")
    async def get_config(request: Request):
        return await _run_controller_worker_call(get_request_context(request).controller.get_config)

    @router.put("/api/config")
    async def update_config(request: Request, updates: ConfigUpdatesRequest):
        controller = get_request_context(request).controller
        handler = getattr(controller, "async_update_config", None)
        if callable(handler):
            errors = await handler(updates.root)
        else:
            errors = await _run_controller_worker_call(controller.update_config, updates.root)
        if errors:
            joined = "; ".join(f"{error.section}.{error.key}: {error.error}" for error in errors)
            return _finalize_route_result(error_result(joined, http_status=400))
        return {"status": "ok"}

    @router.get("/api/state")
    async def get_state(request: Request):
        return await _run_controller_worker_call(get_request_context(request).controller.get_state)

    @router.get("/api/frontend/state")
    async def get_frontend_state(request: Request):
        controller = get_request_context(request).controller
        getter = getattr(controller, "get_frontend_state", None)
        if callable(getter):
            return await _run_controller_worker_call(getter)
        return {"status": "error", "message": "frontend state is unavailable"}

    @router.get("/api/frontend/delta")
    async def get_frontend_delta(request: Request, since_version: int = Query(default=0, ge=0)):
        controller = get_request_context(request).controller
        getter = getattr(controller, "get_frontend_delta", None)
        if callable(getter):
            return await _run_controller_worker_call(getter, since_version)
        snapshot_getter = getattr(controller, "get_frontend_state", None)
        if callable(snapshot_getter):
            sections = await _run_controller_worker_call(snapshot_getter)
            return {"version": 0, "base_version": since_version, "full": True, "sections": sections}
        return {"status": "error", "message": "frontend delta is unavailable"}

    @router.get("/api/frontend/icons")
    async def get_frontend_icons(request: Request):
        controller = get_request_context(request).controller
        getter = getattr(controller, "get_frontend_icons", None)
        if callable(getter):
            return getter()
        return {"status": "error", "message": "frontend icons are unavailable"}

    @router.get("/api/i18n/{language}")
    async def get_i18n_catalog(language: str):
        from app.ui.localization import SUPPORTED_LANGUAGES, TRANSLATIONS

        normalized = str(language or "").strip()
        if normalized not in SUPPORTED_LANGUAGES or normalized == "zh-CN":
            return {}
        return TRANSLATIONS.get(normalized, {})

    @router.post("/api/frontend/action")
    async def frontend_action(request: Request, body: FrontendActionRequest):
        controller = get_request_context(request).controller
        handler = getattr(controller, "async_handle_frontend_action", None)
        if not callable(handler):
            handler = getattr(controller, "handle_frontend_action", None)
        try:
            frontend_version = int(body.frontend_version or 0)
        except (TypeError, ValueError):
            frontend_version = 0
        if callable(handler):
            result = handler(body.action, body.payload)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                delta_getter = getattr(controller, "get_frontend_delta", None)
                if callable(delta_getter):
                    try:
                        delta = await _run_controller_worker_call(delta_getter, frontend_version)
                    except Exception:
                        delta = None
                    if isinstance(delta, dict):
                        result = dict(result)
                        result["frontend_delta"] = delta
            return result
        return _finalize_route_result(error_result("frontend action is unavailable", http_status=501))

    @router.post("/api/scan")
    async def scan_directory(request: Request, body: dict):
        result = await directory_service.scan_directory(request, body)
        return _finalize_route_result(result, enforce_statuses={403})

    @router.post("/api/search")
    async def search(request: Request, body: dict):
        return _finalize_route_result(await search_service.search(request, body))

    @router.post("/api/crawl/start")
    async def start_crawl(request: Request, body: dict):
        return _finalize_route_result(await workflow_route_service.start_crawl(request, body))

    @router.post("/api/crawl/stop")
    async def stop_crawl(request: Request):
        return _finalize_route_result(await workflow_route_service.stop_crawl(request))

    @router.post("/api/crawl/select")
    async def select_tasks(request: Request, body: dict):
        return _finalize_route_result(await workflow_route_service.select_tasks(request, body))

    @router.post("/api/debug/trigger-select")
    async def debug_trigger_select(request: Request):
        result = await controller_route_service.trigger_select(request)
        return _finalize_route_result(result, enforce_statuses={404})

    @router.delete("/api/video/{video_id}")
    async def delete_video(request: Request, video_id: str):
        result = await controller_route_service.delete_video(request, video_id)
        return _finalize_route_result(result, enforce_statuses={400, 403})

    @router.post("/api/video/rename")
    async def rename_video(request: Request, body: dict):
        result = await controller_route_service.rename_video(request, body)
        if not isinstance(body.get("video_id"), str) or not isinstance(body.get("new_title"), str):
            return _finalize_route_result(result)
        if not body.get("video_id"):
            return _finalize_route_result(result)
        return _finalize_route_result(result, enforce_statuses={400, 403})

    @router.post("/api/download")
    async def download_video(request: Request, body: dict):
        return _finalize_route_result(await workflow_route_service.direct_download(request, body))

    @router.get("/api/media/{video_id}")
    async def get_media(request: Request, video_id: str, range_header: str | None = Header(default=None, alias="Range")):
        require_valid_video_id(video_id)
        return await file_response_service.get_media(request, video_id, range_header)

    @router.get("/api/dir/list")
    async def list_directory(request: Request, path: str = ""):
        result = await directory_service.list_directory(request, path)
        return _finalize_route_result(result, enforce_statuses={403})

    @router.post("/api/dir/change")
    async def change_dir(request: Request):
        result = await directory_service.change_dir(request)
        return _finalize_route_result(result, enforce_statuses={403})

    @router.post("/api/dir/pick-native")
    async def pick_native_folder(request: Request):
        return _finalize_route_result(await directory_service.pick_native_folder(request))

    @router.get("/api/debug/latest-log")
    async def download_latest_log(request: Request):
        return await file_response_service.async_latest_log_response(request)

    @router.get("/api/debug/error-summary")
    async def download_error_summary(request: Request):
        return await file_response_service.async_latest_error_summary_response(request)

    return router
