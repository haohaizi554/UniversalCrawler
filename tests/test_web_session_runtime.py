from __future__ import annotations

import unittest
import asyncio
import threading
import time

from app.web.session_runtime import WebSessionRegistry

class _FakeController:
    def __init__(self):
        self.current_save_dir = "downloads"
        self.shutdown_calls = 0
        self.shutdown_event = threading.Event()

    def shutdown(self):
        self.shutdown_calls += 1
        self.shutdown_event.set()

class WebSessionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]

        def _monotonic():
            return self.clock[0]

        self.registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: _FakeController(),
            workflow_factory=lambda controller, _send: object(),
            max_contexts=3,
            idle_ttl_seconds=10.0,
            pinned_session_ids={"__default__"},
            monotonic=_monotonic,
        )

    def test_prune_drops_idle_sessions_but_keeps_pinned_default_context(self):
        default_context = self.registry.get_or_create("__default__")
        stale_context = self.registry.get_or_create("session-a")

        self.clock[0] += 11.0
        self.registry.prune()

        self.assertIn("__default__", self.registry._contexts)
        self.assertNotIn("session-a", self.registry._contexts)
        self.assertEqual(default_context.controller.shutdown_calls, 0)
        self.assertTrue(stale_context.controller.shutdown_event.wait(timeout=1))
        self.assertEqual(stale_context.controller.shutdown_calls, 1)

    def test_registry_evicts_least_recently_used_context_when_capacity_exceeded(self):
        self.registry.get_or_create("__default__")
        first = self.registry.get_or_create("session-a")
        self.clock[0] += 1.0
        second = self.registry.get_or_create("session-b")
        self.clock[0] += 1.0
        self.registry.get_or_create("session-c")

        self.assertNotIn("session-a", self.registry._contexts)
        self.assertIn("session-b", self.registry._contexts)
        self.assertIn("session-c", self.registry._contexts)
        self.assertTrue(first.controller.shutdown_event.wait(timeout=1))
        self.assertEqual(first.controller.shutdown_calls, 1)
        self.assertEqual(second.controller.shutdown_calls, 0)

    def test_dispose_context_returns_without_waiting_for_slow_shutdown(self):
        context = self.registry.get_or_create("slow-session")
        release_shutdown = threading.Event()
        entered_shutdown = threading.Event()

        def slow_shutdown():
            entered_shutdown.set()
            release_shutdown.wait(timeout=1)

        context.controller.shutdown = slow_shutdown

        start = time.perf_counter()
        self.registry._dispose_context("slow-session")

        self.assertNotIn("slow-session", self.registry._contexts)
        self.assertTrue(entered_shutdown.wait(timeout=1))
        self.assertLess(time.perf_counter() - start, 0.2)
        release_shutdown.set()

    def test_prune_keeps_context_with_active_websocket(self):
        context = self.registry.get_or_create("session-active")
        context.mark_websocket_connected()
        self.clock[0] += 11.0

        self.registry.prune()

        self.assertIn("session-active", self.registry._contexts)
        self.assertEqual(context.controller.shutdown_calls, 0)

    def test_context_tracks_background_tasks_until_done(self):
        async def run_case():
            context = self.registry.get_or_create("task-session")
            task = asyncio.create_task(asyncio.sleep(0))

            tracked = context.track_background_task(task)

            self.assertIs(tracked, task)
            self.assertIn(task, context.background_tasks)
            await task
            await asyncio.sleep(0)
            self.assertNotIn(task, context.background_tasks)

        asyncio.run(run_case())

if __name__ == "__main__":
    unittest.main()
