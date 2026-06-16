"""WebSocket 消息循环运行时。"""

from __future__ import annotations

import json

from fastapi import WebSocket, WebSocketDisconnect

from app.web.logging_utils import log_web_event, log_web_exception
from app.web.session_runtime import WebSessionContext
from app.web.ws_dispatcher import WebSocketMessageDispatcher
from app.web.ws_transport import ConnectionManager


class WebSocketRuntime:
    """封装 WebSocket 消息接收循环与断连清理。"""

    MAX_MESSAGE_CHARS = 64 * 1024

    def __init__(
        self,
        *,
        connection_manager: ConnectionManager,
        dispatcher: WebSocketMessageDispatcher,
    ) -> None:
        self._connection_manager = connection_manager
        self._dispatcher = dispatcher

    async def run(self, ws: WebSocket, context: WebSessionContext) -> None:
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > self.MAX_MESSAGE_CHARS:
                    log_web_event(
                        "WebSocketRuntime",
                        "oversized_message",
                        "收到超长 WebSocket 消息，连接已关闭",
                        level="WARNING",
                        context={"session_id": getattr(context, "session_id", "")},
                        details={"message_length": len(raw), "max_length": self.MAX_MESSAGE_CHARS},
                    )
                    await ws.close(code=1009, reason="message too large")
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log_web_event(
                        "WebSocketRuntime",
                        "invalid_json_message",
                        "收到非法 JSON 消息",
                        level="WARNING",
                        context={"session_id": getattr(context, "session_id", "")},
                        details={"payload_preview": raw[:200]},
                    )
                    continue
                await self._dispatcher.handle(msg, context)
        except WebSocketDisconnect:
            self._connection_manager.disconnect(ws)
        except Exception as exc:
            log_web_exception(
                "WebSocketRuntime",
                "run",
                exc,
                context={"session_id": getattr(context, "session_id", "")},
            )
            self._connection_manager.disconnect(ws)
