from __future__ import annotations

import threading
import unittest
from typing import Any
from unittest.mock import patch

from app.core.event_bus import EventBus


class EventBusPublishSubscribeTests(unittest.TestCase):
    def test_publish_delivers_to_all_subscribers(self) -> None:
        bus = EventBus()
        calls: list[tuple[str, str]] = []
        bus.subscribe("topic", lambda payload: calls.append(("first", payload)))
        bus.subscribe("topic", lambda payload: calls.append(("second", payload)))

        bus.publish("topic", "payload")

        self.assertEqual(calls, [("first", "payload"), ("second", "payload")])

    def test_unsubscribe_stops_delivery(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        def handler(payload: str) -> None:
            calls.append(payload)

        bus.subscribe("topic", handler)
        bus.unsubscribe("topic", handler)
        bus.publish("topic", "payload")

        self.assertEqual(calls, [])

    def test_publish_no_subscribers_no_error(self) -> None:
        bus = EventBus()

        bus.publish("missing", {"value": 1})

        self.assertEqual(bus.snapshot()[0]["topic"], "missing")

    def test_subscribe_multiple_topics(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        def handler(payload: str) -> None:
            calls.append(payload)

        bus.subscribe("first", handler)
        bus.subscribe("second", handler)
        bus.publish("first", "a")
        bus.publish("second", "b")

        self.assertEqual(calls, ["a", "b"])

    def test_unsubscribe_without_handler_clears_topic(self) -> None:
        bus = EventBus()
        calls: list[str] = []
        bus.subscribe("topic", calls.append)
        bus.unsubscribe("topic")

        bus.publish("topic", "payload")

        self.assertEqual(calls, [])


class EventBusRecursionTests(unittest.TestCase):
    def test_publish_within_depth_limit(self) -> None:
        bus = EventBus()
        bus.MAX_PUBLISH_DEPTH = 4
        calls: list[int] = []

        def republish(payload: int) -> None:
            calls.append(payload)
            if payload < 2:
                bus.publish("loop", payload + 1)

        bus.subscribe("loop", republish)

        bus.publish("loop", 0)

        self.assertEqual(calls, [0, 1, 2])

    def test_publish_exceeds_depth_limit_suppressed(self) -> None:
        bus = EventBus()
        bus.MAX_PUBLISH_DEPTH = 2
        calls: list[int] = []

        def republish(payload: int) -> None:
            calls.append(payload)
            bus.publish("loop", payload + 1)

        bus.subscribe("loop", republish)

        with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
            bus.publish("loop", 0)

        self.assertEqual(calls, [0, 1])
        self.assertTrue(any("publish suppressed" in line for line in logs.output))

    def test_recursive_publish_chain_breaks(self) -> None:
        bus = EventBus()
        bus.MAX_PUBLISH_DEPTH = 3
        calls: list[int] = []

        def republish(payload: int) -> None:
            calls.append(payload)
            bus.publish("loop", payload + 1)

        bus.subscribe("loop", republish)

        with self.assertLogs("app.core.event_bus", level="WARNING"):
            bus.publish("loop", 0)

        self.assertEqual(len(calls), 3)
        self.assertLessEqual(max(calls), 2)


class EventBusHandlerIsolationTests(unittest.TestCase):
    def test_slow_handler_does_not_block_others(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        def slow_handler(_payload: object) -> None:
            calls.append("slow")

        def fast_handler(_payload: object) -> None:
            calls.append("fast")

        bus.subscribe("topic", slow_handler)
        bus.subscribe("topic", fast_handler)
        monotonic_values = [0.0, 0.0, 0.0, 0.0, 1.0, 1.3, 1.3, 1.3]

        with patch("app.core.event_bus.time.monotonic", side_effect=monotonic_values):
            with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
                bus.publish("topic", None)

        self.assertEqual(calls, ["slow", "fast"])
        self.assertTrue(any("slow handler" in line for line in logs.output))

    def test_handler_exception_does_not_kill_bus(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        def broken(_payload: object) -> None:
            raise RuntimeError("boom")

        bus.subscribe("topic", broken)
        bus.subscribe("topic", lambda payload: calls.append(str(payload)))

        with patch.object(bus._logger, "exception") as exception:
            bus.publish("topic", "ok")

        exception.assert_called_once()
        self.assertEqual(calls, ["ok"])


class EventBusAsyncBackpressureTests(unittest.TestCase):
    def test_async_noisy_events_are_latest_state_wins_per_entity(self) -> None:
        bus = EventBus()
        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        seen: list[int] = []

        def handler(payload: dict[str, Any]) -> None:
            if not started.is_set():
                started.set()
                release.wait(timeout=2)
            seen.append(int(payload["progress"]))
            if len(seen) >= 2:
                finished.set()

        bus.subscribe_async("videos.update", handler)
        try:
            bus.publish("videos.update", {"video_id": "v1", "progress": 0})
            self.assertTrue(started.wait(timeout=2))
            for progress in range(1, 50):
                bus.publish("videos.update", {"video_id": "v1", "progress": progress})
            release.set()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, [0, 49])

    def test_async_metadata_events_are_latest_state_wins_per_video(self) -> None:
        bus = EventBus()
        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        seen: list[bool] = []

        def handler(payload: dict[str, Any]) -> None:
            if not started.is_set():
                started.set()
                release.wait(timeout=2)
            seen.append(bool(payload["metadata"]))
            if len(seen) >= 2:
                finished.set()

        bus.subscribe_async("videos.metadata", handler)
        try:
            bus.publish("videos.metadata", {"video_id": "done", "metadata": False})
            self.assertTrue(started.wait(timeout=2))
            bus.publish("videos.metadata", {"video_id": "done", "metadata": False})
            bus.publish("videos.metadata", {"video_id": "done", "metadata": True})
            release.set()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, [False, True])

    def test_async_app_state_changed_progress_is_latest_state_wins_per_video(self) -> None:
        bus = EventBus()
        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        seen: list[int] = []

        def handler(payload: dict[str, Any]) -> None:
            if not started.is_set():
                started.set()
                release.wait(timeout=2)
            seen.append(int(payload["progress"]))
            if len(seen) >= 2:
                finished.set()

        bus.subscribe_async("app_state.changed", handler)
        try:
            bus.publish("app_state.changed", {"topic": "videos.update", "video_id": "v1", "progress": 0})
            self.assertTrue(started.wait(timeout=2))
            for progress in range(1, 50):
                bus.publish("app_state.changed", {"topic": "videos.update", "video_id": "v1", "progress": progress})
            release.set()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, [0, 49])

    def test_async_logs_append_events_are_latest_state_wins_per_topic(self) -> None:
        bus = EventBus()
        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        seen: list[int] = []

        def handler(payload: dict[str, Any]) -> None:
            if not started.is_set():
                started.set()
                release.wait(timeout=2)
            seen.append(int(payload["count"]))
            if len(seen) >= 2:
                finished.set()

        bus.subscribe_async("logs.append", handler)
        try:
            bus.publish("logs.append", {"count": 1})
            self.assertTrue(started.wait(timeout=2))
            for count in range(2, 51):
                bus.publish("logs.append", {"count": count})
            release.set()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, [1, 50])

    def test_async_app_state_changed_logs_append_is_latest_state_wins_per_topic(self) -> None:
        bus = EventBus()
        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        seen: list[int] = []

        def handler(payload: dict[str, Any]) -> None:
            if not started.is_set():
                started.set()
                release.wait(timeout=2)
            seen.append(int(payload["count"]))
            if len(seen) >= 2:
                finished.set()

        bus.subscribe_async("app_state.changed", handler)
        try:
            bus.publish("app_state.changed", {"topic": "logs.append", "count": 1})
            self.assertTrue(started.wait(timeout=2))
            for count in range(2, 51):
                bus.publish("app_state.changed", {"topic": "logs.append", "count": count})
            release.set()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, [1, 50])

    def test_async_non_noisy_events_keep_fifo_order(self) -> None:
        bus = EventBus()
        finished = threading.Event()
        seen: list[int] = []

        def handler(payload: dict[str, int]) -> None:
            seen.append(payload["index"])
            if len(seen) >= 3:
                finished.set()

        bus.subscribe_async("normal", handler)
        try:
            for index in range(3):
                bus.publish("normal", {"index": index})
            self.assertTrue(finished.wait(timeout=2))
        finally:
            bus.shutdown()

        self.assertEqual(seen, [0, 1, 2])

    def test_wait_for_async_idle_tracks_running_handlers(self) -> None:
        bus = EventBus()
        started = threading.Event()
        release = threading.Event()
        seen: list[str] = []

        def handler(payload: str) -> None:
            started.set()
            release.wait(timeout=2)
            seen.append(payload)

        bus.subscribe_async("normal", handler)
        try:
            bus.publish("normal", "payload")
            self.assertTrue(started.wait(timeout=2))
            self.assertFalse(bus.wait_for_async_idle(timeout=0.01))
            release.set()
            self.assertTrue(bus.wait_for_async_idle(timeout=2))
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, ["payload"])

    def test_wait_for_async_idle_times_out_while_handler_is_blocked(self) -> None:
        bus = EventBus()
        started = threading.Event()
        release = threading.Event()

        def handler(payload: str) -> None:
            started.set()
            release.wait(timeout=2)

        bus.subscribe_async("normal", handler)
        try:
            bus.publish("normal", "payload")
            self.assertTrue(started.wait(timeout=2))

            self.assertFalse(bus.wait_for_async_idle(timeout=0.01))

            release.set()
            self.assertTrue(bus.wait_for_async_idle(timeout=2))
        finally:
            release.set()
            bus.shutdown()

    def test_wait_for_async_idle_returns_false_from_async_worker_thread(self) -> None:
        bus = EventBus()
        finished = threading.Event()
        results: list[bool] = []

        def handler(payload: str) -> None:
            results.append(bus.wait_for_async_idle(timeout=1))
            finished.set()

        bus.subscribe_async("normal", handler)
        try:
            bus.publish("normal", "payload")
            self.assertTrue(finished.wait(timeout=2))
            self.assertTrue(bus.wait_for_async_idle(timeout=2))
        finally:
            bus.shutdown()

        self.assertEqual(results, [False])


class EventBusStormAndLockTests(unittest.TestCase):
    def test_storm_detection_triggers_warning(self) -> None:
        bus = EventBus()

        with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
            for index in range(6):
                bus.publish("storm", index)

        self.assertTrue(any("storm detected" in line for line in logs.output))

    def test_storm_detection_normal_rate_no_warning(self) -> None:
        bus = EventBus()
        monotonic_values: list[float] = []
        for index in range(6):
            monotonic_values.extend([index * 1.1] * 4)

        with patch("app.core.event_bus.time.monotonic", side_effect=monotonic_values):
            with patch.object(bus._logger, "warning") as warning:
                for index in range(6):
                    bus.publish("normal", index)

        warning.assert_not_called()

    def test_lock_wait_warning(self) -> None:
        bus = EventBus()

        with patch("app.core.event_bus.time.monotonic", side_effect=[0.0, 1.2, 1.2]):
            with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
                bus.subscribe("topic", lambda _payload: None)

        self.assertTrue(any("lock wait" in line for line in logs.output))

    def test_lock_hold_warning(self) -> None:
        bus = EventBus()

        with patch("app.core.event_bus.time.monotonic", side_effect=[0.0, 0.0, 1.2]):
            with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
                bus.subscribe("topic", lambda _payload: None)

        self.assertTrue(any("lock held" in line for line in logs.output))


class EventBusSnapshotTests(unittest.TestCase):
    def test_snapshot_returns_recent_events(self) -> None:
        bus = EventBus()

        for index in range(105):
            bus.publish("topic", index)

        snapshot = bus.snapshot()
        self.assertEqual(len(snapshot), 100)
        self.assertEqual(snapshot[0]["payload"], 5)
        self.assertEqual(snapshot[-1]["payload"], 104)

    def test_snapshot_with_topic_filter_can_be_derived_from_recent_events(self) -> None:
        bus = EventBus()
        bus.publish("first", 1)
        bus.publish("second", 2)
        bus.publish("first", 3)

        filtered = [event for event in bus.snapshot() if event["topic"] == "first"]

        self.assertEqual([event["payload"] for event in filtered], [1, 3])

    def test_snapshot_returns_mutation_isolated_events(self) -> None:
        bus = EventBus()
        payload = {"value": 1}
        bus.publish("topic", payload)

        snapshot = bus.snapshot()
        snapshot[0]["topic"] = "mutated"

        self.assertEqual(bus.snapshot()[0]["topic"], "topic")


class EventBusConcurrencyTests(unittest.TestCase):
    def test_concurrent_publish_thread_safe(self) -> None:
        bus = EventBus()
        calls: list[int] = []
        errors: list[BaseException] = []
        calls_lock = threading.Lock()

        def handler(payload: int) -> None:
            with calls_lock:
                calls.append(payload)

        def worker(base: int) -> None:
            try:
                for offset in range(50):
                    bus.publish("topic", base + offset)
            except BaseException as exc:  # pragma: no cover - assertion records unexpected failures
                with calls_lock:
                    errors.append(exc)

        bus.subscribe("topic", handler)
        threads = [threading.Thread(target=worker, args=(index * 1000,)) for index in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(calls), 250)

    def test_concurrent_subscribe_unsubscribe_thread_safe(self) -> None:
        bus = EventBus()
        errors: list[BaseException] = []
        lock = threading.Lock()

        def handler(_payload: Any) -> None:
            return None

        def worker() -> None:
            try:
                for _ in range(100):
                    bus.subscribe("topic", handler)
                    bus.unsubscribe("topic", handler)
            except BaseException as exc:  # pragma: no cover - assertion records unexpected failures
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))


if __name__ == "__main__":
    unittest.main()
