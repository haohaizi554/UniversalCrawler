from __future__ import annotations

import tempfile
import time
import unittest
from unittest.mock import patch

import pytest

from app.core.event_bus import EventBus
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.cache_service import CacheService
from app.services.frontend_event_aggregator import FrontendEventAggregator
from app.services.frontend_state_service import FrontendStateService
from shared.log_platforms import builtin_platform_metas
from app.ui.viewmodels.log_query_worker import LogQueryRequest, query_log_items

pytestmark = pytest.mark.benchmark


def _assert_duration_under(test_case: unittest.TestCase, duration: float, threshold: float) -> None:
    test_case.assertLess(
        duration,
        threshold * 2,
        f"duration {duration:.3f}s exceeded benchmark budget {threshold * 2:.3f}s",
    )


class PerformanceBenchmarkTests(unittest.TestCase):
    def test_snapshot_build_performance(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            cache = CacheService(namespace="benchmark-snapshot", cache_dir=temp_dir)
            app_state = AppState(event_bus=EventBus(), cache_service=cache)
            for index in range(1000):
                item = VideoItem(
                    url=f"https://example.com/video/{index}",
                    title=f"Benchmark video {index}",
                    source="bilibili",
                )
                app_state.videos[item.id] = item
            logs = [
                {
                    "id": f"log-{index}",
                    "time": "2026-07-07 00:00:00",
                    "level": "INFO",
                    "raw_level": "INFO",
                    "message": f"benchmark message {index}",
                    "message_summary": f"benchmark message {index}",
                    "platform_id": "system",
                    "trace_id": f"trace-{index % 100}",
                }
                for index in range(5000)
            ]
            service = FrontendStateService(app_state=app_state, cache_service=cache)
            service.log_items = lambda: logs  # type: ignore[method-assign]
            try:
                started = time.perf_counter()
                snapshot = service.get_snapshot(sections=frozenset({"queue_items", "app_status", "log_items"}))
                duration = time.perf_counter() - started
            finally:
                service.destroy()

        self.assertEqual(len(snapshot["queue_items"]), 1000)
        self.assertEqual(len(snapshot["log_items"]), 5000)
        _assert_duration_under(self, duration, 0.20)

    def test_log_query_worker_performance(self) -> None:
        items = tuple(
            {
                "id": f"log-{index}",
                "time": f"2026-07-07 00:{index % 60:02d}:00",
                "level": "ERROR" if index % 5 == 0 else "INFO",
                "raw_level": "ERROR" if index % 5 == 0 else "INFO",
                "message": f"benchmark message {index}",
                "message_summary": f"benchmark message {index}",
                "log_scope": "download" if index % 2 else "system",
                "platform_id": "bilibili",
                "trace_id": f"trace-{index % 100}",
            }
            for index in range(10000)
        )
        platform_meta = builtin_platform_metas()
        request = LogQueryRequest(
            sequence=1,
            items=items,
            categories=("all", "system", "download", "error"),
            category="all",
            level="all",
            time_range="all",
            platform_id=None,
            trace_query="",
            keyword="benchmark",
            platform_options=tuple(platform_meta.values()),
            platform_meta_by_id=platform_meta,
            page=2,
            page_size=100,
        )

        started = time.perf_counter()
        result = query_log_items(request)
        duration = time.perf_counter() - started

        self.assertEqual(result.total_count, 10000)
        self.assertEqual(result.matched_count, 10000)
        self.assertEqual(result.visible_count, 100)
        _assert_duration_under(self, duration, 8.0)

    def test_event_bus_publish_throughput(self) -> None:
        bus = EventBus()
        calls: list[int] = []
        bus.subscribe("benchmark", calls.append)

        with patch.object(bus._logger, "warning"):
            started = time.perf_counter()
            for index in range(10000):
                bus.publish("benchmark", index)
            duration = time.perf_counter() - started

        self.assertEqual(len(calls), 10000)
        _assert_duration_under(self, duration, 0.50)

    def test_frontend_state_service_delta_merge(self) -> None:
        aggregator = FrontendEventAggregator(max_pending_events=2048)

        started = time.perf_counter()
        for index in range(1000):
            aggregator.record("videos.update", {"video_id": f"video-{index % 100}", "progress": index % 100})
        sections = aggregator.sections_since(0)
        pending_events = aggregator.peek().pending_events
        duration = time.perf_counter() - started

        self.assertIn("active_downloads", sections)
        self.assertIn("app_status", sections)
        self.assertLessEqual(len(pending_events), 100)
        _assert_duration_under(self, duration, 0.25)


if __name__ == "__main__":
    unittest.main()
