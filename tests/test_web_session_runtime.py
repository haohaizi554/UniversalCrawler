from __future__ import annotations

import unittest

from app.web.session_runtime import WebSessionRegistry


class _FakeController:
    def __init__(self):
        self.current_save_dir = "downloads"
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


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
        self.assertEqual(first.controller.shutdown_calls, 1)
        self.assertEqual(second.controller.shutdown_calls, 0)


if __name__ == "__main__":
    unittest.main()
