"""WebSocket 会话恢复与鉴权绑定。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import WebSocket

from app.web.session_runtime import WebSessionContext, WebSessionRegistry, is_allowed_origin, is_local_host

@dataclass(slots=True)
class WebSocketSessionBinding:
    """描述一个已通过鉴权的 WebSocket 会话绑定。"""

    session_id: str
    context: WebSessionContext

class WebSocketSessionBinder:
    """负责从 WebSocket 请求恢复会话并完成鉴权。"""

    def __init__(
        self,
        session_registry: WebSessionRegistry,
        *,
        default_session_id: str,
        access_token: str | None = None,
        access_cookie_name: str = "ucrawl_access_token",
    ) -> None:
        self._session_registry = session_registry
        self._default_session_id = default_session_id
        self._access_token = str(access_token or "")
        self._access_cookie_name = access_cookie_name

    async def bind(self, ws: WebSocket) -> WebSocketSessionBinding | None:
        if self._access_token:
            access_token = ws.cookies.get(self._access_cookie_name)
            if not secrets.compare_digest(access_token or "", self._access_token):
                await ws.close(code=1008, reason="invalid access token")
                return None
        session_id = ws.cookies.get("ucrawl_session") or ws.cookies.get("ucrawl_session_id") or self._default_session_id
        context = self._session_registry.get_or_create(session_id)
        origin = ws.headers.get("origin")
        token = ws.cookies.get("ucrawl_session_token")
        expected_origin = f"{ws.url.scheme.replace('ws', 'http', 1)}://{ws.url.netloc}"
        token_valid = secrets.compare_digest(token or "", context.session_token)
        client = getattr(ws, "client", None)
        client_host = getattr(client, "host", None)

        # 浏览器会始终发送 Origin；仅保留本机非浏览器客户端的无 Origin 兼容路径。
        # 远程客户端即使拿到会话 Cookie，也不能绕过同源检查直接建立控制通道。
        if (not origin and not is_local_host(client_host)) or (
            origin and not is_allowed_origin(origin, expected_origin=expected_origin)
        ):
            await ws.close(code=1008, reason="forbidden origin")
            return None
        if not token_valid:
            await ws.close(code=1008, reason="invalid session token")
            return None

        return WebSocketSessionBinding(session_id=session_id, context=context)
