"""FastAPI 服务器：REST API + WebSocket + 静态文件服务。"""

from __future__ import annotations

import asyncio
import mimetypes

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.utils.runtime_paths import resolve_resource_file
from app.web.rest_router import build_rest_router
from app.web.session_runtime import configured_allowed_origins
from app.web.ws_router import build_ws_router
from shared.runtime_adapters import run_cli_search
from shared.version import __version__

# 仅为旧导入提供默认会话，实际请求必须从 session_context 取控制器。
controller = None

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _configured_index_html(index_path, config_manager) -> str:
    """把持久化主题写入首帧 HTML。

    浏览器存储只作为渲染提示，不能覆盖 GUI/Web 共用配置。读取前刷新配置，
    使其他进程刚写入的主题也能在新页面首帧生效，避免主题闪烁。
    """
    reload_if_changed = getattr(config_manager, "reload_if_changed", None)
    if callable(reload_if_changed):
        reload_if_changed()
    theme = str(config_manager.get("common", "theme", "light") or "light").lower()
    if theme not in {"light", "dark"}:
        theme = "light"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace('data-theme="light"', f'data-theme="{theme}"', 1)
    return html.replace("__UCRAWL_VERSION__", f"v{__version__}")


def _apply_no_cache_headers(response):
    for key, value in NO_CACHE_HEADERS.items():
        response.headers[key] = value
    return response


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        return _apply_no_cache_headers(response)

STATIC_DIR = resolve_resource_file("app/web/static")
UI_ICON_DIR = resolve_resource_file("UI/icon")
# 使用独立 URL 绕开浏览器对历史 /favicon.ico 404 的强缓存；资源副本随 Web 包安装。
WEB_FAVICON_PATH = resolve_resource_file("app/web/static/webui-icon.ico")
SESSION_COOKIE_NAME = "ucrawl_session"
SESSION_TOKEN_COOKIE_NAME = "ucrawl_session_token"
CSRF_COOKIE_NAME = "ucrawl_csrf_token"
ACCESS_COOKIE_NAME = "ucrawl_access_token"
SESSION_TOKEN_HEADER = "X-Ucrawl-Session-Token"
DEFAULT_SESSION_ID = "default"

mimetypes.init()

def create_app(lifespan=None, *, access_token: str | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(title="Universal Crawler Pro", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(configured_allowed_origins()),
        allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )



    global controller
    from app.web.controller import WebController
    from app.web.workflows import (
        WebWorkflowService,
        build_selection_strategy as _build_selection_strategy,
        merge_default_config as _merge_default_config,
        validate_config_types as _validate_config_types,
    )
    # 不在 create_app 时获取事件循环，因为 uvicorn 可能使用不同的事件循环
    # 传入 None，在首次 emit 时延迟获取正确的事件循环
    from app.web.app_composition import build_web_app_composition, publish_app_state
    from app.web.search_service import SearchRouteRuntime

    def _search_runtime_provider() -> SearchRouteRuntime:
        return SearchRouteRuntime(
            build_selection_strategy=_build_selection_strategy,
            merge_default_config=_merge_default_config,
            validate_config_types=_validate_config_types,
            run_cli_search=run_cli_search,
        )

    composition = build_web_app_composition(
        controller_factory=WebController,
        workflow_factory=WebWorkflowService,
        session_cookie_name=SESSION_COOKIE_NAME,
        session_token_cookie_name=SESSION_TOKEN_COOKIE_NAME,
        csrf_cookie_name=CSRF_COOKIE_NAME,
        session_token_header=SESSION_TOKEN_HEADER,
        default_session_id=DEFAULT_SESSION_ID,
        search_runtime_provider=_search_runtime_provider,
        access_token=access_token,
        access_cookie_name=ACCESS_COOKIE_NAME,
    )
    publish_app_state(
        app,
        composition=composition,
        session_cookie_name=SESSION_COOKIE_NAME,
        session_token_cookie_name=SESSION_TOKEN_COOKIE_NAME,
        csrf_cookie_name=CSRF_COOKIE_NAME,
        session_token_header=SESSION_TOKEN_HEADER,
        access_cookie_name=ACCESS_COOKIE_NAME,
    )
    controller = composition.default_context.controller

    @app.middleware("http")
    async def http_session_middleware(request: Request, call_next):
        return await composition.http_sessions.handle(request, call_next)

    # REST/WS 只能从组合式路由注册。目录授权、会话鉴权和输入校验都位于
    # 对应服务中；不要在 server.py 再复制一套端点，否则两条路径会漂移。
    app.include_router(
        build_rest_router(
            get_request_context=composition.get_request_context,
            search_service=composition.search_service,
            workflow_route_service=composition.workflow_route_service,
            controller_route_service=composition.controller_route_service,
            directory_service=composition.directory_service,
            file_response_service=composition.file_response_service,
        )
    )
    app.include_router(
        build_ws_router(
            session_binder=composition.ws_session_binder,
            connection_manager=composition.manager,
            bootstrapper=composition.ws_bootstrapper,
            ws_runtime=composition.ws_runtime,
            create_task_provider=lambda: asyncio.create_task,
        )
    )

    @app.get("/")
    async def composed_serve_index():
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            from app.config import cfg

            try:
                html = _configured_index_html(index_path, cfg)
            except (OSError, RuntimeError, ValueError):
                return _apply_no_cache_headers(FileResponse(str(index_path)))
            return _apply_no_cache_headers(HTMLResponse(html))
        return {"error": "index.html not found"}

    @app.get("/webui-icon.ico", include_in_schema=False)
    async def serve_webui_favicon():
        if not WEB_FAVICON_PATH.is_file():
            raise HTTPException(status_code=404, detail="WebUI icon not found")
        return _apply_no_cache_headers(
            FileResponse(str(WEB_FAVICON_PATH), media_type="image/x-icon")
        )

    # 静态目录最后挂载，避免覆盖更具体的 API 路由。
    if STATIC_DIR.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")
    if UI_ICON_DIR.exists():
        app.mount("/ui-icon", StaticFiles(directory=str(UI_ICON_DIR)), name="ui-icon")

    return app
