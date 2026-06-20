from __future__ import annotations

import asyncio
import unittest

from app.web.ws_transport import ConnectionManager, WebSocketConnection

class WsTransportBackpressureTests(unittest.IsolatedAsyncioTestCase):
    def _connection(self) -> WebSocketConnection:
        return WebSocketConnection(ws=object(), session_id="s1", send_lock=asyncio.Lock())

    async def test_noisy_messages_coalesce_when_entity_matches(self):
        manager = ConnectionManager(max_queue_size=8)
        conn = self._connection()

        await manager._enqueue(conn, manager._build_message("video_state_changed", {"video_id": "v1", "progress": 10}))
        await manager._enqueue(conn, manager._build_message("video_state_changed", {"video_id": "v1", "progress": 90}))

        self.assertEqual(len(conn.outbound_queue), 1)
        self.assertEqual(conn.metrics["coalesced"], 1)
        self.assertIn('"progress": 90', conn.outbound_queue[0].text)

    async def test_critical_message_displaces_noisy_when_queue_is_full(self):
        manager = ConnectionManager(max_queue_size=2)
        conn = self._connection()

        await manager._enqueue(conn, manager._build_message("video_state_changed", {"video_id": "v1", "progress": 10}))
        await manager._enqueue(conn, manager._build_message("video_state_changed", {"video_id": "v2", "progress": 20}))
        await manager._enqueue(conn, manager._build_message("task_finished", {"video_id": "v3"}))

        queued_types = [message.event_type for message in conn.outbound_queue]
        self.assertIn("task_finished", queued_types)
        self.assertLessEqual(len(conn.outbound_queue), 2)
        self.assertEqual(conn.metrics["dropped_noisy"], 1)

    async def test_noisy_message_is_dropped_when_full_and_not_coalescable(self):
        manager = ConnectionManager(max_queue_size=1)
        conn = self._connection()

        await manager._enqueue(conn, manager._build_message("task_started", {"video_id": "v1"}))
        await manager._enqueue(conn, manager._build_message("video_state_changed", {"video_id": "v2", "progress": 20}))

        self.assertEqual([message.event_type for message in conn.outbound_queue], ["task_started"])
        self.assertEqual(conn.metrics["dropped_noisy"], 1)

if __name__ == "__main__":
    unittest.main()
