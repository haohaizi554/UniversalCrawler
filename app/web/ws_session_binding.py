"""WebSocket 会话恢复与鉴权绑定。"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.web.session_runtime import (
    WebSessionCapacityError,
    WebSessionContext,
    WebSessionRegistry,
    is_allowed_origin,
    is_local_host,
)

@dataclass(slots=True)
class WebSocketSessionBinding:
    """描述一个已通过鉴权的 WebSocket 会话绑定。"""

    session_id: str
    context: WebSessionContext
    _release_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    def release(self) -> None:
        """Release the startup/runtime lease exactly once."""
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self.context.mark_websocket_disconnected()

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
        origin = ws.headers.get("origin")
        expected_origin = f"{ws.url.scheme.replace('ws', 'http', 1)}://{ws.url.netloc}"
        client = getattr(ws, "client", None)
        client_host = getattr(client, "host", None)

        # 浏览器会始终发送 Origin；仅保留本机非浏览器客户端的无 Origin 兼容路径。
        # 远程客户端即使拿到会话 Cookie，也不能绕过同源检查直接建立控制通道。
        if (not origin and not is_local_host(client_host)) or (
            origin and not is_allowed_origin(origin, expected_origin=expected_origin)
        ):
            await ws.close(code=1008, reason="forbidden origin")
            return None

        session_id = ws.cookies.get("ucrawl_session") or ws.cookies.get("ucrawl_session_id") or self._default_session_id
        token = ws.cookies.get("ucrawl_session_token") or ""
        try:
            context = self._session_registry.acquire_websocket_context(session_id, token)
        except WebSessionCapacityError:
            await ws.close(code=1013, reason="session capacity exhausted")
            return None
        if context is None:
            await ws.close(code=1008, reason="invalid session token")
            return None
        binding = WebSocketSessionBinding(session_id=session_id, context=context)

        return binding
