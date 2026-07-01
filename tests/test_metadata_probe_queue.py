from __future__ import annotations

import unittest

from app.services.metadata_probe_queue import MetadataProbeQueue


class FakeTimer:
    timers: list["FakeTimer"] = []

    def __init__(self, delay: float, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.__class__.timers.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


class MetadataProbeQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTimer.timers.clear()

    def _make_queue(self, calls: list[tuple[str, str]], *, batch_size: int = 2, closed=lambda: False):
        return MetadataProbeQueue(
            retry_callback=lambda video_id, path: calls.append((video_id, path)) or True,
            key_factory=lambda video_id, path: f"{video_id}\0{path.lower()}",
            batch_size_provider=lambda: batch_size,
            closed_checker=closed,
            timer_factory=FakeTimer,
        )

    def test_queue_deduplicates_by_key_and_drains_in_batches(self):
        calls: list[tuple[str, str]] = []
        queue = self._make_queue(calls, batch_size=1)

        queue.queue("v1", "D:/A.mp4")
        queue.queue("v1", "d:/a.mp4")
        queue.queue("v2", "D:/B.mp4")

        self.assertEqual(len(queue.pending), 2)
        self.assertEqual(len(FakeTimer.timers), 1)

        queue.drain()
        self.assertEqual(calls, [("v1", "d:/a.mp4")])
        self.assertEqual(len(queue.pending), 1)
        self.assertEqual(len(FakeTimer.timers), 2)

        queue.drain()
        self.assertEqual(calls, [("v1", "d:/a.mp4"), ("v2", "D:/B.mp4")])
        self.assertEqual(queue.pending, {})

    def test_cancel_invalidates_late_timer_callback(self):
        calls: list[tuple[str, str]] = []
        queue = self._make_queue(calls)

        queue.queue("v1", "D:/A.mp4")
        timer = queue.timer
        self.assertIsNotNone(timer)
        queue.cancel()
        timer.callback()

        self.assertTrue(timer.cancelled)
        self.assertEqual(queue.pending, {})
        self.assertEqual(calls, [])

    def test_close_prevents_new_work(self):
        calls: list[tuple[str, str]] = []
        queue = self._make_queue(calls)

        queue.cancel(close=True)
        queue.queue("v1", "D:/A.mp4")
        queue.drain()

        self.assertTrue(queue.closed)
        self.assertEqual(queue.pending, {})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
