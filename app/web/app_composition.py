"""Web 应用组合对象构建。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from fastapi import FastAPI, Request

from app.web.controller_route_service import WebControllerRouteService
from app.web.directory_service import WebDirectoryService
from app.web.file_response_service import WebFileResponseService
from app.web.http_session import HttpSessionCoordinator
from app.web.search_service import SearchRouteRuntime, WebSearchService
from app.web.session_runtime import WebSessionContext, WebSessionRegistry
from app.web.ws_bootstrap import WebSocketBootstrapper
from app.web.ws_dispatcher import WebSocketMessageDispatcher
from app.web.ws_runtime import WebSocketRuntime
from app.web.ws_session_binding import WebSocketSessionBinder
from app.web.ws_transport import ConnectionManager
from app.web.workflow_route_service import WebWorkflowRouteService

GetSearchRuntime = Callable[[], SearchRouteRuntime]

@dataclass(slots=True)
class WebAppComposition:
    manager: ConnectionManager
    ws_bootstrapper: WebSocketBootstrapper
    ws_runtime: WebSocketRuntime
    session_registry: WebSessionRegistry
    default_context: Any
    http_sessions: HttpSessionCoordinator
    ws_session_binder: WebSocketSessionBinder
    directory_service: WebDirectoryService
    controller_route_service: WebControllerRouteService
    file_response_service: WebFileResponseService
    workflow_route_service: WebWorkflowRouteService
    search_service: WebSearchService

    def get_request_context(self, request: Request) -> WebSessionContext:
        return self.http_sessions.get_request_context(request)

def build_web_app_composition(
    *,
    controller_factory,
    workflow_factory,
    session_cookie_name: str,
    session_token_cookie_name: str,
    csrf_cookie_name: str,
    session_token_header: str,
    default_session_id: str,
    search_runtime_provider: GetSearchRuntime,
    access_token: str | None = None,
    access_cookie_name: str = "ucrawl_access_token",
) -> WebAppComposition:
    """构建 Web app 运行所需的组合对象。"""

    manager = ConnectionManager()
    ws_bootstrapper = WebSocketBootstrapper()
    ws_dispatcher = WebSocketMessageDispatcher()
    ws_runtime = WebSocketRuntime(connection_manager=manager, dispatcher=ws_dispatcher)

    def send_factory(session_id: str) -> Callable[[str, Any], Coroutine[Any, Any, bool]]:
        def send(event_type: str, data: Any = None) -> Coroutine[Any, Any, bool]:
            return manager.emit_to_session(session_id, event_type, data)

        return send

    session_registry = WebSessionRegistry(
        send_factory=send_factory,
        controller_factory=controller_factory,
        workflow_factory=workflow_factory,
        pinned_session_ids={default_session_id},
    )
    http_sessions = HttpSessionCoordinator(
        session_registry=session_registry,
        session_cookie_name=session_cookie_name,
        session_token_cookie_name=session_token_cookie_name,
        csrf_cookie_name=csrf_cookie_name,
        session_token_header=session_token_header,
        default_session_id=default_session_id,
        access_token=access_token,
        access_cookie_name=access_cookie_name,
    )
    ws_session_binder = WebSocketSessionBinder(
        session_registry,
        default_session_id=default_session_id,
        access_token=access_token,
        access_cookie_name=access_cookie_name,
    )
    default_context = session_registry.get_or_create(default_session_id)

    def _get_request_context(request: Request) -> WebSessionContext:
        return http_sessions.get_request_context(request)

    def _require_allowed_directory(context: WebSessionContext, directory: str) -> str:
        return http_sessions.require_allowed_directory(context, directory)

    def _has_valid_session_token(request: Request) -> bool:
        return http_sessions.has_valid_session_token(request)

    directory_service = WebDirectoryService(
        get_request_context=_get_request_context,
        require_allowed_directory=_require_allowed_directory,
        native_folder_picker_enabled=not bool(access_token),
    )
    controller_route_service = WebControllerRouteService(get_request_context=_get_request_context)
    file_response_service = WebFileResponseService(
        get_request_context=_get_request_context,
        has_valid_session_token=_has_valid_session_token,
    )
    workflow_route_service = WebWorkflowRouteService(get_request_context=_get_request_context)
    search_service = WebSearchService(
        get_request_context=_get_request_context,
        runtime_provider=search_runtime_provider,
    )

    return WebAppComposition(
        manager=manager,
        ws_bootstrapper=ws_bootstrapper,
        ws_runtime=ws_runtime,
        session_registry=session_registry,
        default_context=default_context,
        http_sessions=http_sessions,
        ws_session_binder=ws_session_binder,
        directory_service=directory_service,
        controller_route_service=controller_route_service,
        file_response_service=file_response_service,
        workflow_route_service=workflow_route_service,
        search_service=search_service,
    )

def publish_app_state(
    app: FastAPI,
    *,
    composition: WebAppComposition,
    session_cookie_name: str,
    session_token_cookie_name: str,
    csrf_cookie_name: str,
    session_token_header: str,
    access_cookie_name: str = "ucrawl_access_token",
) -> None:
    """将 Web 运行时关键对象发布到 app.state。"""

    app.state.web_session_registry = composition.session_registry
    app.state.web_connection_manager = composition.manager
    app.state.web_session_cookie_name = session_cookie_name
    app.state.web_session_token_cookie_name = session_token_cookie_name
    app.state.web_csrf_cookie_name = csrf_cookie_name
    app.state.web_session_token_header = session_token_header
    app.state.web_access_cookie_name = access_cookie_name
