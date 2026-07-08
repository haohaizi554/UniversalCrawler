"""WebSocket transport adapter with bounded per-connection backpressure."""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.services.frontend_event_aggregator import FrontendEventPriority, priority_for_topic
from app.web.logging_utils import log_web_exception

@dataclass(slots=True)
class OutboundMessage:
    event_type: str
    data: Any
    text: str
    priority: FrontendEventPriority
    coalesce_key: tuple[str, str]

@dataclass(slots=True)
class WebSocketConnection:
    """Represents an active WebSocket session connection."""

    ws: WebSocket
    session_id: str
    send_lock: asyncio.Lock
    queue_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    queue_event: asyncio.Event = field(default_factory=asyncio.Event)
    outbound_queue: deque[OutboundMessage] = field(default_factory=deque)
    sender_task: asyncio.Task | None = None
    metrics: dict[str, int] = field(default_factory=lambda: {
        "enqueued": 0,
        "sent": 0,
        "coalesced": 0,
        "dropped_noisy": 0,
        "dropped_overflow": 0,
    })

class ConnectionManager:
    """Manage WebSocket connections and bounded per-session sending."""

    def __init__(self, *, max_queue_size: int = 256) -> None:
        self.active_connections: dict[str, list[WebSocketConnection]] = {}
        self._connections_lock = threading.Lock()
        self._max_queue_size = max(1, int(max_queue_size))

    async def connect(self, ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        conn = WebSocketConnection(
            ws=ws,
            session_id=session_id,
            send_lock=asyncio.Lock(),
        )
        conn.sender_task = asyncio.create_task(self._sender_loop(conn))
        with self._connections_lock:
            self.active_connections.setdefault(session_id, []).append(conn)

    def disconnect(self, ws: WebSocket) -> None:
        removed: list[WebSocketConnection] = []
        with self._connections_lock:
            empty_session_ids: list[str] = []
            for session_id, connections in self.active_connections.items():
                for conn in list(connections):
                    if conn.ws is ws:
                        connections.remove(conn)
                        removed.append(conn)
                        break
                if not connections:
                    empty_session_ids.append(session_id)
            for session_id in empty_session_ids:
                self.active_connections.pop(session_id, None)
        self._cancel_removed_senders(removed)

    async def broadcast(self, event_type: str, data: Any = None) -> bool:
        with self._connections_lock:
            connections = [
                conn
                for session_connections in self.active_connections.values()
                for conn in list(session_connections)
            ]
        return await self._emit_to_connections(connections, event_type, data)

    async def emit_to_session(self, session_id: str, event_type: str, data: Any = None) -> bool:
        with self._connections_lock:
            connections = list(self.active_connections.get(session_id, ()))
        return await self._emit_to_connections(connections, event_type, data)

    def connection_metrics(self) -> dict[str, Any]:
        with self._connections_lock:
            connections = [
                conn
                for session_connections in self.active_connections.values()
                for conn in session_connections
            ]
        return {
            "connection_count": len(connections),
            "max_queue_size": self._max_queue_size,
            "connections": [
                {
                    "session_id": conn.session_id,
                    "queue_size": len(conn.outbound_queue),
                    **dict(conn.metrics),
                }
                for conn in connections
            ],
        }

    async def _emit_to_connections(
        self,
        connections: list[WebSocketConnection],
        event_type: str,
        data: Any = None,
    ) -> bool:
        if not connections:
            return False
        message = await self._build_message_async(event_type, data)
        accepted = False
        for conn in list(connections):
            accepted = await self._enqueue(conn, message) or accepted
        return accepted

    async def _build_message_async(self, event_type: str, data: Any) -> OutboundMessage:
        return await asyncio.get_running_loop().run_in_executor(None, self._build_message, event_type, data)

    def _build_message(self, event_type: str, data: Any) -> OutboundMessage:
        normalized_type = str(event_type or "")
        text = json.dumps({"type": normalized_type, "data": data}, ensure_ascii=False)
        priority = self._message_priority(normalized_type, data)
        return OutboundMessage(
            event_type=normalized_type,
            data=data,
            text=text,
            priority=priority,
            coalesce_key=self._coalesce_key(normalized_type, data),
        )

    @staticmethod
    def _message_priority(event_type: str, data: Any) -> FrontendEventPriority:
        if event_type == "frontend_delta" and isinstance(data, dict):
            raw = str(data.get("priority") or "").lower()
            if raw == "critical":
                return FrontendEventPriority.CRITICAL
            if raw == "normal":
                return FrontendEventPriority.NORMAL
            return FrontendEventPriority.NOISY
        return priority_for_topic(event_type)

    @staticmethod
    def _coalesce_key(event_type: str, data: Any) -> tuple[str, str]:
        if event_type == "frontend_delta":
            return (event_type, "frontend")
        if isinstance(data, dict):
            entity_id = data.get("video_id") or data.get("id") or data.get("trace_id") or ""
            if entity_id:
                return (event_type, str(entity_id))
        return (event_type, "")

    async def _enqueue(self, conn: WebSocketConnection, message: OutboundMessage) -> bool:
        async with conn.queue_lock:
            if message.priority == FrontendEventPriority.NOISY and self._replace_coalesced(conn, message):
                conn.metrics["coalesced"] += 1
                conn.queue_event.set()
                return True
            if len(conn.outbound_queue) >= self._max_queue_size:
                made_room_for_delta = False
                if (
                    message.event_type == "frontend_delta"
                    and message.priority == FrontendEventPriority.NOISY
                    and self._drop_queued_below_priority(conn, FrontendEventPriority.NORMAL)
                ):
                    made_room_for_delta = True
                if message.priority == FrontendEventPriority.NOISY:
                    if not made_room_for_delta and len(conn.outbound_queue) >= self._max_queue_size:
                        conn.metrics["dropped_noisy"] += 1
                        return False
                elif not self._drop_queued_below_priority(conn, message.priority):
                    if message.priority != FrontendEventPriority.CRITICAL:
                        conn.metrics["dropped_overflow"] += 1
                        return False
                    conn.outbound_queue.popleft()
                    conn.metrics["dropped_overflow"] += 1
            conn.outbound_queue.append(message)
            conn.metrics["enqueued"] += 1
            conn.queue_event.set()
            return True

    @staticmethod
    def _replace_coalesced(conn: WebSocketConnection, message: OutboundMessage) -> bool:
        if message.priority != FrontendEventPriority.NOISY:
            return False
        for index, queued in enumerate(conn.outbound_queue):
            if (
                queued.priority == FrontendEventPriority.NOISY
                and queued.event_type == message.event_type
                and queued.coalesce_key == message.coalesce_key
            ):
                conn.outbound_queue[index] = message
                return True
        return False

    @staticmethod
    def _drop_queued_below_priority(conn: WebSocketConnection, priority: FrontendEventPriority) -> bool:
        for candidate_priority in (FrontendEventPriority.NOISY, FrontendEventPriority.NORMAL):
            if candidate_priority >= priority:
                continue
            for queued in list(conn.outbound_queue):
                if queued.priority == candidate_priority:
                    conn.outbound_queue.remove(queued)
                    if candidate_priority == FrontendEventPriority.NOISY:
                        conn.metrics["dropped_noisy"] += 1
                    else:
                        conn.metrics["dropped_overflow"] += 1
                    return True
        return False

    async def _sender_loop(self, conn: WebSocketConnection) -> None:
        try:
            while True:
                await conn.queue_event.wait()
                while True:
                    async with conn.queue_lock:
                        if not conn.outbound_queue:
                            conn.queue_event.clear()
                            break
                        message = conn.outbound_queue.popleft()
                    try:
                        async with conn.send_lock:
                            await conn.ws.send_text(message.text)
                        conn.metrics["sent"] += 1
                    except Exception as exc:
                        log_web_exception(
                            "ConnectionManager",
                            "sender_loop",
                            exc,
                            context={"session_id": conn.session_id, "event_type": message.event_type},
                        )
                        self.disconnect(conn.ws)
                        return
        except asyncio.CancelledError:
            return

    @staticmethod
    def _cancel_removed_senders(connections: list[WebSocketConnection]) -> None:
        current_task = None
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            pass
        for conn in connections:
            task = conn.sender_task
            if task is not None and task is not current_task and not task.done():
                task.cancel()
            conn.queue_event.set()
