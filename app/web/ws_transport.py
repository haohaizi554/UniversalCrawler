"""WebSocket 传输层适配器。"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.web.logging_utils import log_web_exception

@dataclass(slots=True)
class WebSocketConnection:
    """表示一个活动中的 WebSocket 会话连接。"""

    ws: WebSocket
    session_id: str
    send_lock: asyncio.Lock


class ConnectionManager:
    """管理 WebSocket 连接与按会话发送。"""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocketConnection]] = {}
        self._connections_lock = threading.Lock()

    async def connect(self, ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        with self._connections_lock:
            self.active_connections.setdefault(session_id, []).append(
                WebSocketConnection(
                    ws=ws,
                    session_id=session_id,
                    send_lock=asyncio.Lock(),
                )
            )

    def disconnect(self, ws: WebSocket) -> None:
        with self._connections_lock:
            empty_session_ids: list[str] = []
            for session_id, connections in self.active_connections.items():
                for conn in list(connections):
                    if conn.ws is ws:
                        connections.remove(conn)
                        break
                if not connections:
                    empty_session_ids.append(session_id)
            for session_id in empty_session_ids:
                self.active_connections.pop(session_id, None)

    async def broadcast(self, event_type: str, data: Any = None) -> None:
        with self._connections_lock:
            connections = [
                conn
                for session_connections in self.active_connections.values()
                for conn in list(session_connections)
            ]
        await self._emit_to_connections(connections, event_type, data)

    async def emit_to_session(self, session_id: str, event_type: str, data: Any = None) -> None:
        with self._connections_lock:
            connections = list(self.active_connections.get(session_id, ()))
        await self._emit_to_connections(connections, event_type, data)

    async def _emit_to_connections(
        self,
        connections: list[WebSocketConnection],
        event_type: str,
        data: Any = None,
    ) -> None:
        if not connections:
            return

        msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        dead_connections: list[WebSocket] = []
        for conn in list(connections):
            try:
                async with conn.send_lock:
                    await conn.ws.send_text(msg)
            except Exception as exc:
                log_web_exception(
                    "ConnectionManager",
                    "emit_to_connections",
                    exc,
                    context={"session_id": conn.session_id, "event_type": event_type},
                )
                dead_connections.append(conn.ws)
        for ws in dead_connections:
            self.disconnect(ws)
