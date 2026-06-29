"""静态首页与静态资源装配。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

class NoCacheStaticFiles(StaticFiles):
    """Static file mount that disables browser caching for packaged/local UI assets."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        for key, value in NO_CACHE_HEADERS.items():
            response.headers[key] = value
        return response

def build_static_router(*, static_dir: Path) -> APIRouter:
    """构建首页静态路由。"""

    router = APIRouter()

    @router.get("/")
    async def serve_index():
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path), headers=NO_CACHE_HEADERS)
        return {"error": "index.html not found"}

    return router

def mount_static_files(app: FastAPI, *, static_dir: Path) -> None:
    """挂载静态目录。"""

    if static_dir.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(static_dir)), name="static")
