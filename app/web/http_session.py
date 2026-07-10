"""HTTP 会话恢复与 API 请求鉴权。"""

from __future__ import annotations

import secrets
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from app.web.session_runtime import WebSessionContext, WebSessionRegistry, is_allowed_origin, is_local_host

class HttpSessionCoordinator:
    """封装 HTTP 会话中间件、上下文恢复与目录权限代理。"""

    def __init__(
        self,
        *,
        session_registry: WebSessionRegistry,
        session_cookie_name: str,
        session_token_cookie_name: str,
        csrf_cookie_name: str,
        session_token_header: str,
        default_session_id: str,
    ) -> None:
        self._session_registry = session_registry
        self._session_cookie_name = session_cookie_name
        self._session_token_cookie_name = session_token_cookie_name
        self._csrf_cookie_name = csrf_cookie_name
        self._session_token_header = session_token_header
        self._default_session_id = default_session_id

    async def handle(self, request: Request, call_next):
        session_id = request.cookies.get(self._session_cookie_name) or uuid4().hex
        context = self._session_registry.get_or_create(session_id)
        request.state.session_id = session_id
        request.state.session_context = context

        is_api_request = request.url.path.startswith("/api/")
        client = getattr(request, "client", None)
        client_host = getattr(client, "host", None)
        token_valid = self.has_valid_session_token(request, context)
        if is_api_request and not is_local_host(client_host) and not token_valid:
            return JSONResponse({"status": "error", "error": "缺少或无效的会话令牌"}, status_code=403)

        if is_api_request and request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and not self.is_request_origin_allowed(request, origin):
                return JSONResponse({"status": "error", "error": "不允许的请求来源"}, status_code=403)
            if origin and not token_valid:
                return JSONResponse({"status": "error", "error": "缺少或无效的会话令牌"}, status_code=403)

        response = await call_next(request)
        secure_cookie = request.url.scheme == "https"
        if self._session_cookie_name not in request.cookies:
            response.set_cookie(
                self._session_cookie_name,
                session_id,
                httponly=True,
                samesite="strict",
                secure=secure_cookie,
            )
        if request.cookies.get(self._session_token_cookie_name) != context.session_token:
            response.set_cookie(
                self._session_token_cookie_name,
                context.session_token,
                httponly=True,
                samesite="strict",
                secure=secure_cookie,
            )
        if request.cookies.get(self._csrf_cookie_name) != context.csrf_token:
            response.set_cookie(
                self._csrf_cookie_name,
                context.csrf_token,
                httponly=False,
                samesite="strict",
                secure=secure_cookie,
            )
        return response

    def get_request_context(self, request: Request) -> WebSessionContext:
        context = getattr(request.state, "session_context", None)
        if context is not None:
            return context
        session_id = getattr(request.state, "session_id", None) or self._default_session_id
        return self._session_registry.get_or_create(session_id)

    def has_valid_session_token(self, request: Request, context: WebSessionContext | None = None) -> bool:
        session_context = context or self.get_request_context(request)
        request_token = request.headers.get(self._session_token_header) or request.cookies.get(self._csrf_cookie_name)
        return secrets.compare_digest(request_token or "", session_context.csrf_token)

    @staticmethod
    def _request_origin(request: Request) -> str:
        return f"{request.url.scheme}://{request.url.netloc}"

    def is_request_origin_allowed(self, request: Request, origin: str | None) -> bool:
        if origin:
            return is_allowed_origin(origin, expected_origin=self._request_origin(request))
        return is_local_host(request.url.hostname)

    @staticmethod
    def require_allowed_directory(context: WebSessionContext, directory: str) -> str:
        return context.require_directory(directory)
