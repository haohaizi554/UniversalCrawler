"""HTTP REST 路由装配。"""

from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.web.api_result import error_result, finalize_api_result
from app.web.controller_route_service import require_valid_video_id


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConfigUpdatesRequest(RootModel[dict[str, dict[str, Any]]]):
    pass


class ScanDirectoryRequest(_RequestModel):
    directory: str | None = Field(default=None, max_length=4096)
    scan_limit: int | None = Field(default=None, ge=1, le=5000)


class SearchRequest(_RequestModel):
    source: str = Field(..., min_length=1, max_length=64)
    keyword: str = Field(..., min_length=1, max_length=200)
    save_dir: str | None = Field(default=None, max_length=4096)
    config: dict[str, Any] = Field(default_factory=dict)
    selection: dict[str, Any] | None = None
    timeout: float | None = None
    run_timeout: float | None = None
    download: Any = True


class DownloadRequest(_RequestModel):
    url: str = Field(..., min_length=1, max_length=4096)
    source: str = Field(..., min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    save_dir: str | None = Field(default=None, max_length=4096)
    timeout: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)

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
        return get_request_context(request).controller.get_platforms()

    @router.get("/api/config")
    async def get_config(request: Request):
        return get_request_context(request).controller.get_config()

    @router.put("/api/config")
    async def update_config(request: Request, updates: ConfigUpdatesRequest):
        errors = get_request_context(request).controller.update_config(updates.root)
        if errors:
            joined = "; ".join(f"{error.section}.{error.key}: {error.error}" for error in errors)
            return finalize_api_result(error_result(joined, http_status=400))
        return {"status": "ok"}

    @router.get("/api/state")
    async def get_state(request: Request):
        return get_request_context(request).controller.get_state()

    @router.post("/api/scan")
    async def scan_directory(request: Request, body: ScanDirectoryRequest):
        return finalize_api_result(await directory_service.scan_directory(request, body.model_dump(exclude_none=True)))

    @router.post("/api/search")
    async def search(request: Request, body: SearchRequest):
        return finalize_api_result(
            await search_service.search(request, body.model_dump(exclude_none=True, exclude_defaults=True))
        )

    @router.post("/api/crawl/start")
    async def start_crawl(request: Request, body: dict):
        return finalize_api_result(await workflow_route_service.start_crawl(request, body))

    @router.post("/api/crawl/stop")
    async def stop_crawl(request: Request):
        return finalize_api_result(await workflow_route_service.stop_crawl(request))

    @router.post("/api/crawl/select")
    async def select_tasks(request: Request, body: dict):
        return finalize_api_result(await workflow_route_service.select_tasks(request, body))

    if os.getenv("UCRAWL_DEBUG_ROUTES", "0") == "1":
        @router.post("/api/debug/trigger-select")
        async def debug_trigger_select(request: Request):
            return finalize_api_result(await controller_route_service.trigger_select(request))

    @router.delete("/api/video/{video_id}")
    async def delete_video(request: Request, video_id: str):
        return finalize_api_result(await controller_route_service.delete_video(request, video_id))

    @router.post("/api/video/rename")
    async def rename_video(request: Request, body: dict):
        return finalize_api_result(await controller_route_service.rename_video(request, body))

    @router.post("/api/download")
    async def download_video(request: Request, body: DownloadRequest):
        return finalize_api_result(
            await workflow_route_service.direct_download(request, body.model_dump(exclude_none=True, exclude_defaults=True))
        )

    @router.get("/api/media/{video_id}")
    async def get_media(request: Request, video_id: str, range_header: str | None = Header(default=None, alias="Range")):
        require_valid_video_id(video_id)
        return await file_response_service.get_media(request, video_id, range_header)

    @router.get("/api/dir/list")
    async def list_directory(request: Request, path: str = ""):
        return finalize_api_result(await directory_service.list_directory(request, path))

    @router.post("/api/dir/change")
    async def change_dir(request: Request):
        return finalize_api_result(await directory_service.change_dir(request))

    @router.post("/api/dir/pick-native")
    async def pick_native_folder(request: Request):
        return finalize_api_result(await directory_service.pick_native_folder(request))

    @router.get("/api/debug/latest-log")
    async def download_latest_log(request: Request):
        return file_response_service.latest_log_response(request)

    @router.get("/api/debug/error-summary")
    async def download_error_summary(request: Request):
        return file_response_service.latest_error_summary_response(request)

    return router
