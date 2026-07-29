from __future__ import annotations

import unittest
import asyncio
from pathlib import Path
import threading
import time
from unittest import mock

from app.web.session_runtime import WebSessionCapacityError, WebSessionRegistry

class _FakeFrontendStateService:
    def __init__(self):
        self.profile_providers = []

    def set_tool_execution_profile_provider(self, provider):
        self.profile_providers.append(provider)


class _FakeController:
    def __init__(self):
        self.current_save_dir = "downloads"
        self.shutdown_calls = 0
        self.shutdown_event = threading.Event()
        self.frontend_state_service = _FakeFrontendStateService()

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

    def test_disposal_concurrency_and_queue_are_bounded(self):
        release_shutdown = threading.Event()
        workers_started = threading.Event()
        state_lock = threading.Lock()
        active_shutdowns = 0
        max_active_shutdowns = 0
        started_shutdowns = 0
        completed_shutdowns = 0

        class _BlockingController(_FakeController):
            def shutdown(inner_self):
                nonlocal active_shutdowns
                nonlocal max_active_shutdowns
                nonlocal started_shutdowns
                nonlocal completed_shutdowns
                with state_lock:
                    active_shutdowns += 1
                    started_shutdowns += 1
                    max_active_shutdowns = max(max_active_shutdowns, active_shutdowns)
                    if started_shutdowns >= 2:
                        workers_started.set()
                release_shutdown.wait(timeout=2)
                time.sleep(0.02)
                with state_lock:
                    active_shutdowns -= 1
                    completed_shutdowns += 1
                inner_self.shutdown_calls += 1
                inner_self.shutdown_event.set()

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: _BlockingController(),
            workflow_factory=lambda controller, _send: object(),
            max_contexts=20,
            idle_ttl_seconds=10.0,
            monotonic=lambda: 100.0,
        )
        contexts = [registry.get_or_create(f"session-{index}") for index in range(11)]

        for context in contexts[:10]:
            registry._dispose_context(context.session_id)

        self.assertTrue(workers_started.wait(timeout=1))
        start = time.perf_counter()
        extra_future = registry._dispose_context(contexts[-1].session_id)
        try:
            self.assertIsNone(extra_future)
            self.assertLess(time.perf_counter() - start, 0.1)
            self.assertIn(contexts[-1].session_id, registry._contexts)
            with state_lock:
                self.assertLessEqual(max_active_shutdowns, 2)
        finally:
            release_shutdown.set()

        for context in contexts[:10]:
            self.assertTrue(context.controller.shutdown_event.wait(timeout=2))
        retry_future = registry._dispose_context(contexts[-1].session_id)
        self.assertIsNotNone(retry_future)
        self.assertTrue(contexts[-1].controller.shutdown_event.wait(timeout=2))
        registry.shutdown_all(wait=True, timeout=2.0)
        self.assertEqual(completed_shutdowns, len(contexts))

    def test_saturated_disposal_capacity_never_blocks_the_event_loop(self):
        release_shutdown = threading.Event()
        entered_shutdown = threading.Event()
        constructed_controllers = 0

        class _BlockingController(_FakeController):
            def shutdown(inner_self):
                entered_shutdown.set()
                release_shutdown.wait(timeout=0.5)
                inner_self.shutdown_calls += 1
                inner_self.shutdown_event.set()

        def controller_factory(_loop, _send):
            nonlocal constructed_controllers
            constructed_controllers += 1
            return _BlockingController()

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=controller_factory,
            workflow_factory=lambda controller, _send: object(),
            max_contexts=2,
            idle_ttl_seconds=10.0,
            monotonic=lambda: 100.0,
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        first = registry.get_or_create("session-a")
        second = registry.get_or_create("session-b")
        registry._dispose_context(first.session_id)
        self.assertTrue(entered_shutdown.wait(timeout=1))
        third = registry.get_or_create("session-c")

        async def run_case():
            heartbeat = asyncio.create_task(asyncio.sleep(0.01))
            start = time.perf_counter()
            with self.assertRaises(WebSessionCapacityError):
                registry.get_or_create("session-d")
            await asyncio.wait_for(heartbeat, timeout=0.1)
            self.assertLess(time.perf_counter() - start, 0.1)

        try:
            asyncio.run(run_case())
            self.assertIs(registry.get_or_create(second.session_id), second)
            self.assertEqual(constructed_controllers, 3)
            self.assertEqual(set(registry._contexts), {second.session_id, third.session_id})
        finally:
            release_shutdown.set()
            registry.shutdown_all(wait=True, timeout=2.0)

    def test_concurrent_session_admission_cannot_exceed_capacity(self):
        release_shutdown = threading.Event()
        entered_shutdown = threading.Event()

        class _BlockingController(_FakeController):
            def shutdown(inner_self):
                entered_shutdown.set()
                release_shutdown.wait(timeout=1)
                inner_self.shutdown_calls += 1
                inner_self.shutdown_event.set()

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: _BlockingController(),
            workflow_factory=lambda controller, _send: object(),
            max_contexts=1,
            idle_ttl_seconds=10.0,
            monotonic=lambda: 100.0,
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        original = registry.get_or_create("original")
        barrier = threading.Barrier(3)
        admitted: list[str] = []
        rejected: list[str] = []

        def admit(session_id: str) -> None:
            barrier.wait()
            try:
                registry.get_or_create(session_id)
            except WebSessionCapacityError:
                rejected.append(session_id)
            else:
                admitted.append(session_id)

        threads = [
            threading.Thread(target=admit, args=(session_id,), daemon=True)
            for session_id in ("session-a", "session-b")
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=1)

        try:
            self.assertTrue(entered_shutdown.wait(timeout=1))
            self.assertEqual(len(admitted), 1)
            self.assertEqual(len(rejected), 1)
            self.assertEqual(len(registry._contexts), 1)
            self.assertNotIn(original.session_id, registry._contexts)
        finally:
            release_shutdown.set()
            registry.shutdown_all(wait=True, timeout=2.0)

    def test_capacity_rejection_does_not_construct_or_replace_a_protected_context(self):
        constructed_controllers = 0

        def controller_factory(_loop, _send):
            nonlocal constructed_controllers
            constructed_controllers += 1
            return _FakeController()

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=controller_factory,
            workflow_factory=lambda controller, _send: object(),
            max_contexts=1,
            pinned_session_ids={"pinned"},
        )
        pinned = registry.get_or_create("pinned")

        with self.assertRaises(WebSessionCapacityError):
            registry.get_or_create("new-session")

        self.assertEqual(constructed_controllers, 1)
        self.assertIs(registry.get_or_create("pinned"), pinned)
        self.assertEqual(registry._contexts, {"pinned": pinned})
        registry.shutdown_all(wait=True, timeout=1.0)

    def test_submit_failure_restores_eviction_candidate_and_releases_capacity(self):
        controllers: list[_FakeController] = []

        def controller_factory(_loop, _send):
            controller = _FakeController()
            controllers.append(controller)
            return controller

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=controller_factory,
            workflow_factory=lambda controller, _send: object(),
            max_contexts=1,
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        original = registry.get_or_create("original")

        with mock.patch.object(
            registry._disposal_executor,
            "submit",
            side_effect=RuntimeError("executor unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "executor unavailable"):
                registry.get_or_create("failed-admission")

        self.assertEqual(registry._contexts, {"original": original})
        self.assertEqual(original.controller.shutdown_calls, 0)
        self.assertEqual(controllers[1].shutdown_calls, 1)

        replacement = registry.get_or_create("replacement")
        self.assertIs(registry._contexts["replacement"], replacement)
        self.assertTrue(original.controller.shutdown_event.wait(timeout=1))
        registry.shutdown_all(wait=True, timeout=1.0)

    def test_prune_keeps_stale_context_until_disposal_capacity_recovers(self):
        clock = [100.0]
        release_shutdown = threading.Event()

        class _BlockingController(_FakeController):
            def shutdown(inner_self):
                release_shutdown.wait(timeout=1)
                inner_self.shutdown_calls += 1
                inner_self.shutdown_event.set()

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: _BlockingController(),
            workflow_factory=lambda controller, _send: object(),
            max_contexts=2,
            idle_ttl_seconds=1.0,
            monotonic=lambda: clock[0],
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        first = registry.get_or_create("session-a")
        stale = registry.get_or_create("session-b")
        registry._dispose_context(first.session_id)
        clock[0] += 2.0

        registry.prune()
        self.assertIn(stale.session_id, registry._contexts)

        release_shutdown.set()
        self.assertTrue(first.controller.shutdown_event.wait(timeout=1))
        registry.prune()
        self.assertNotIn(stale.session_id, registry._contexts)
        self.assertTrue(stale.controller.shutdown_event.wait(timeout=1))
        registry.shutdown_all(wait=True, timeout=2.0)

    def test_prune_rechecks_candidate_after_websocket_lease_is_acquired(self):
        clock = [100.0]
        selected_for_prune = threading.Event()
        continue_prune = threading.Event()
        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: _FakeController(),
            workflow_factory=lambda controller, _send: object(),
            max_contexts=2,
            idle_ttl_seconds=1.0,
            monotonic=lambda: clock[0],
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        context = registry.get_or_create("session-a")
        clock[0] += 2.0
        original_dispose = registry._dispose_context

        def delayed_dispose(session_id, **kwargs):
            selected_for_prune.set()
            continue_prune.wait(timeout=1)
            return original_dispose(session_id, **kwargs)

        registry._dispose_context = delayed_dispose
        prune_thread = threading.Thread(target=registry.prune, daemon=True)
        prune_thread.start()
        self.assertTrue(selected_for_prune.wait(timeout=1))

        leased = registry.acquire_websocket_context(
            context.session_id,
            context.session_token,
        )
        continue_prune.set()
        prune_thread.join(timeout=1)

        self.assertFalse(prune_thread.is_alive())
        self.assertIs(leased, context)
        self.assertIs(registry._contexts[context.session_id], context)
        self.assertEqual(context.controller.shutdown_calls, 0)
        context.mark_websocket_disconnected()
        registry._dispose_context = original_dispose
        registry.shutdown_all(wait=True, timeout=1.0)

    def test_shutdown_all_retains_and_drains_terminal_backlog_after_timeout(self):
        release_shutdown = threading.Event()
        controllers: list[_FakeController] = []

        class _BlockingController(_FakeController):
            def shutdown(inner_self):
                release_shutdown.wait(timeout=1)
                inner_self.shutdown_calls += 1
                inner_self.shutdown_event.set()

        def controller_factory(_loop, _send):
            controller = _BlockingController()
            controllers.append(controller)
            return controller

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=controller_factory,
            workflow_factory=lambda controller, _send: object(),
            max_contexts=3,
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        for index in range(3):
            registry.get_or_create(f"session-{index}")

        start = time.perf_counter()
        registry.shutdown_all(wait=True, timeout=0.05)

        self.assertLess(time.perf_counter() - start, 0.2)
        self.assertEqual(registry._contexts, {})
        self.assertTrue(registry._terminal_disposal_backlog)

        release_shutdown.set()
        registry.shutdown_all(wait=True, timeout=2.0)
        for controller in controllers:
            self.assertTrue(controller.shutdown_event.wait(timeout=1))
            self.assertEqual(controller.shutdown_calls, 1)

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

    def test_context_binds_one_dynamic_public_tool_profile_provider(self):
        context = self.registry.get_or_create("tool-session")
        service = context.controller.frontend_state_service

        self.assertEqual(len(service.profile_providers), 1)
        provider = service.profile_providers[0]
        initial = provider()
        self.assertEqual(initial.host_surface, "public_web")
        self.assertEqual(initial.owner_id, "web:tool-session")
        self.assertFalse(initial.allow_tool_execution)
        self.assertEqual(initial.tool_permissions, frozenset())
        self.assertEqual(initial.approved_roots, frozenset())

        context.approve_directory("more-downloads")
        refreshed = provider()

        self.assertEqual(refreshed.owner_id, initial.owner_id)
        self.assertEqual(refreshed.approved_roots, frozenset())
        self.assertEqual(len(service.profile_providers), 1)

    def test_shutdown_all_disposes_every_context_including_pinned_sessions(self):
        default_context = self.registry.get_or_create("__default__")
        other_context = self.registry.get_or_create("session-a")

        self.registry.shutdown_all(wait=True, timeout=1.0)

        self.assertEqual(self.registry._contexts, {})
        self.assertTrue(default_context.controller.shutdown_event.is_set())
        self.assertTrue(other_context.controller.shutdown_event.is_set())
        self.assertEqual(default_context.controller.shutdown_calls, 1)
        self.assertEqual(other_context.controller.shutdown_calls, 1)

if __name__ == "__main__":
    unittest.main()
