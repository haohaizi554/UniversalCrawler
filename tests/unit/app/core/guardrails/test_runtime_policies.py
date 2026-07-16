from __future__ import annotations

import json
import re
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from app.core.event_bus import EventBus
from app.core.guardrails.crawl_budget import BudgetExhausted, CrawlBudget, RateLimitCancelled
from app.core.guardrails.pii_detection import get_masked_count, reset_masked_count, sanitize, sanitize_text
from app.core.guardrails.rate_limiter import RESILIENCE_PROFILES, RateLimiter
from app.spiders.base import BaseSpider
from tests.support.paths import PROJECT_ROOT


class ManualClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class GuardedSpider(BaseSpider):
    def run(self) -> None:
        return None


class CrawlBudgetGuardrailTests(unittest.TestCase):
    def test_crawl_budget_allows_within_limit(self) -> None:
        budget = CrawlBudget(max_requests_per_platform=3, max_total=5)

        budget.consume("bilibili")
        budget.consume("bilibili")

        self.assertEqual(budget.remaining("bilibili"), 1)
        self.assertEqual(budget.snapshot()["per_platform"], {"bilibili": 2})

    def test_crawl_budget_blocks_when_exhausted(self) -> None:
        budget = CrawlBudget(max_requests_per_platform=1, max_total=10)

        budget.consume("douyin")

        with self.assertRaises(BudgetExhausted):
            budget.consume("douyin")

    def test_crawl_budget_resets_per_platform(self) -> None:
        budget = CrawlBudget(max_requests_per_platform=2, max_total=10)

        budget.consume("douyin", amount=2)
        budget.consume("bilibili")

        self.assertEqual(budget.remaining("douyin"), 0)
        self.assertEqual(budget.remaining("bilibili"), 1)

    def test_crawl_budget_total_limit_enforced(self) -> None:
        budget = CrawlBudget(max_requests_per_platform=10, max_total=3)

        budget.consume("douyin", amount=2)
        budget.consume("bilibili")

        with self.assertRaises(BudgetExhausted):
            budget.consume("kuaishou")

    def test_crawl_budget_check_before_request(self) -> None:
        spider = GuardedSpider(
            "demo",
            {"platform": "bilibili", "guardrails": {"budget": {"max_requests_per_platform": 1, "max_total": 1}}},
        )
        spider.rate_limiter = MagicMock()
        spider.rate_limiter.acquire.return_value = True

        spider.guard_request()

        with self.assertRaises(BudgetExhausted):
            spider.guard_request()
        spider.rate_limiter.acquire.assert_called_once()

    def test_crawl_budget_token_consumption_tracking(self) -> None:
        budget = CrawlBudget(max_requests_per_platform=10, max_total=20)

        budget.consume("xiaohongshu", amount=4)
        budget.consume("missav", amount=3)

        self.assertEqual(
            budget.snapshot(),
            {
                "max_requests_per_platform": 10,
                "max_total": 20,
                "total": 7,
                "per_platform": {"xiaohongshu": 4, "missav": 3},
            },
        )

    def test_crawl_budget_rejects_non_positive_amount(self) -> None:
        budget = CrawlBudget()

        with self.assertRaises(ValueError):
            budget.consume("bilibili", amount=0)


class RateLimiterGuardrailTests(unittest.TestCase):
    def test_rate_limiter_rejects_request_larger_than_bucket_capacity(self) -> None:
        clock = ManualClock()
        limiter = RateLimiter(1.0, burst=1.0, monotonic=clock.monotonic, sleep=clock.sleep)

        with self.assertRaises(ValueError):
            limiter.acquire(2.0, cancel_check=lambda: True)

        self.assertEqual(clock.sleeps, [])

    def test_rate_limiter_allows_burst_within_capacity(self) -> None:
        clock = ManualClock()
        limiter = RateLimiter(1.0, burst=2.0, monotonic=clock.monotonic, sleep=clock.sleep)

        self.assertTrue(limiter.acquire())
        self.assertTrue(limiter.acquire())
        self.assertEqual(clock.sleeps, [])

    def test_rate_limiter_blocks_when_exceeded(self) -> None:
        clock = ManualClock()
        limiter = RateLimiter(1.0, burst=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()

        allowed = limiter.acquire(cancel_check=lambda: True)

        self.assertFalse(allowed)
        self.assertEqual(clock.sleeps, [])

    def test_rate_limiter_platform_specific_profiles(self) -> None:
        douyin = RateLimiter.for_platform("douyin")
        missav = RateLimiter.for_platform("missav")
        unknown = RateLimiter.for_platform("unknown")

        self.assertEqual(douyin.tokens_per_second, RESILIENCE_PROFILES["douyin"])
        self.assertEqual(missav.tokens_per_second, RESILIENCE_PROFILES["missav"])
        self.assertEqual(unknown.tokens_per_second, 1.0)

    def test_rate_limiter_token_bucket_refill(self) -> None:
        clock = ManualClock()
        limiter = RateLimiter(2.0, burst=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()

        self.assertTrue(limiter.acquire())

        self.assertGreaterEqual(clock.now, 0.5)
        self.assertTrue(clock.sleeps)

    def test_rate_limiter_concurrent_access_thread_safe(self) -> None:
        limiter = RateLimiter(1000.0, burst=20.0)
        results: list[bool] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                value = limiter.acquire()
                with lock:
                    results.append(value)
            except BaseException as exc:  # pragma: no cover - assertion records unexpected failures
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(results, [True] * 20)

    def test_base_spider_raises_when_rate_limit_cancelled(self) -> None:
        spider = GuardedSpider("demo", {"platform": "bilibili"})
        spider.budget = CrawlBudget(max_requests_per_platform=5, max_total=5)
        spider.rate_limiter = MagicMock()
        spider.rate_limiter.acquire.return_value = False

        with self.assertRaises(RateLimitCancelled):
            spider.guard_request(cancel_check=lambda: True)


class PIIDetectionGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_masked_count()

    def test_pii_detection_limits_hostile_container_depth(self) -> None:
        value: Any = "13800138000"
        for _ in range(1200):
            value = [value]

        masked = sanitize(value)

        current = masked
        for _ in range(64):
            current = current[0]
        self.assertEqual(current, "<max-depth-exceeded>")

    def test_pii_detection_phone_number(self) -> None:
        masked = sanitize_text("请联系 +86 13800138000 或 13900139000")

        self.assertEqual(masked, "请联系 138****8000 或 139****9000")
        self.assertEqual(get_masked_count()["phone"], 2)

    def test_pii_detection_id_card(self) -> None:
        masked = sanitize_text("证件 11010519991212333X 已登记")

        self.assertEqual(masked, "证件 110105********333X 已登记")
        self.assertEqual(get_masked_count()["id_card"], 1)

    def test_pii_detection_email(self) -> None:
        masked = sanitize_text("邮箱 user.name@example.com")

        self.assertEqual(masked, "邮箱 us***@example.com")
        self.assertEqual(get_masked_count()["email"], 1)

    def test_pii_detection_bank_card(self) -> None:
        masked = sanitize_text("卡号 6222021234567890")

        self.assertEqual(masked, "卡号 622202******7890")
        self.assertEqual(get_masked_count()["bank_card"], 1)

    def test_pii_detection_sanitizes_video_title(self) -> None:
        spider = GuardedSpider("demo", {"platform": "bilibili"})
        emitted: list[Any] = []
        spider.sig_item_found.connect(emitted.append)

        spider.emit_video("https://example.com/video", "客户 13800138000 的视频", "bilibili")

        self.assertEqual(emitted[0].title, "客户 138****8000 的视频")

    def test_pii_detection_sanitizes_video_description(self) -> None:
        spider = GuardedSpider("demo", {"platform": "bilibili"})
        emitted: list[Any] = []
        spider.sig_item_found.connect(emitted.append)

        spider.emit_video(
            "https://example.com/video",
            "demo",
            "bilibili",
            meta={"description": "联系 user@example.com 获取资料"},
        )

        self.assertEqual(emitted[0].meta["description"], "联系 us***@example.com 获取资料")

    def test_pii_detection_preserves_non_pii_text(self) -> None:
        value = {"title": "普通视频标题", "tags": ["科普", "自然"]}

        self.assertEqual(sanitize(value), value)
        self.assertEqual(get_masked_count(), {"phone": 0, "id_card": 0, "email": 0, "bank_card": 0})

    def test_pii_detection_empty_and_none_input(self) -> None:
        self.assertEqual(sanitize_text(""), "")
        self.assertIsNone(sanitize(None))
        self.assertEqual(sanitize([]), [])


class AntiRecursionGuardrailTests(unittest.TestCase):
    def test_anti_recursion_depth_limit(self) -> None:
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
        self.assertTrue(any("recursion depth" in line for line in logs.output))

    def test_anti_recursion_frequency_limit(self) -> None:
        bus = EventBus()

        with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
            for index in range(7):
                bus.publish("storm", index)

        self.assertTrue(any("storm detected" in line for line in logs.output))

    def test_anti_recursion_recovers_after_cooldown(self) -> None:
        bus = EventBus()
        times = [0.0] * 24 + [2.0] * 4

        with patch("app.core.event_bus.time.monotonic", side_effect=times):
            for index in range(6):
                bus.publish("storm", index)
            with patch.object(bus._logger, "warning") as warning:
                bus.publish("storm", "after-cooldown")

        warning.assert_not_called()

    def test_anti_recursion_depth_state_resets_after_suppression(self) -> None:
        bus = EventBus()
        bus.MAX_PUBLISH_DEPTH = 1
        seen: list[str] = []

        def recursive(_payload: object) -> None:
            bus.publish("loop", "nested")

        bus.subscribe("loop", recursive)
        bus.subscribe("safe", lambda payload: seen.append(str(payload)))

        with self.assertLogs("app.core.event_bus", level="WARNING"):
            bus.publish("loop", "start")
        bus.publish("safe", "ok")

        self.assertEqual(seen, ["ok"])

    def test_anti_recursion_frequency_is_topic_scoped(self) -> None:
        bus = EventBus()

        with patch.object(bus._logger, "warning") as warning:
            for index in range(5):
                bus.publish(f"topic-{index}", index)

        warning.assert_not_called()

    def test_event_bus_async_subscriber_does_not_block_publisher(self) -> None:
        bus = EventBus()
        started = threading.Event()
        release = threading.Event()
        seen: list[str] = []

        def slow_handler(payload: object) -> None:
            started.set()
            release.wait(timeout=2)
            seen.append(str(payload))

        bus.subscribe_async("slow", slow_handler)
        try:
            bus.publish("slow", "payload")
            self.assertTrue(started.wait(timeout=2))
            self.assertEqual(seen, [])
        finally:
            release.set()
            bus.shutdown()

        self.assertEqual(seen, ["payload"])


class UIAsyncGuardrailTests(unittest.TestCase):
    def test_production_code_does_not_pump_qt_process_events(self) -> None:
        project_root = PROJECT_ROOT
        offenders: list[str] = []
        for path in (project_root / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "processEvents(" in text:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_gui_and_controller_hot_paths_do_not_use_time_sleep(self) -> None:
        project_root = PROJECT_ROOT
        offenders: list[str] = []
        roots = [
            project_root / "app" / "ui",
            project_root / "app" / "controllers",
        ]
        for root in roots:
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "time.sleep(" in text:
                    offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_browser_e2e_does_not_use_legacy_fixed_3_5_second_waits(self) -> None:
        project_root = PROJECT_ROOT
        forbidden = ("time.sleep(3.5", "wait_for_timeout(3500", "sleep(3500")
        offenders: list[str] = []
        for path in (project_root / "tests").rglob("test_web*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_gui_controllers_do_not_synchronously_build_frontend_snapshots(self) -> None:
        project_root = PROJECT_ROOT
        offenders: list[str] = []
        for path in (project_root / "app" / "controllers").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "get_snapshot(" in text:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_main_window_app_state_event_bus_handler_uses_qt_queue(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("_app_state_changed_queued = pyqtSignal(object)", text)
        self.assertIn("def _subscribe_app_state_changed(self):", text)
        self.assertIn('subscribe_async("app_state.changed", self._queue_app_state_changed)', text)
        self.assertIn("self._app_state_handler = self._subscribe_app_state_changed()", text)
        self.assertNotIn('self.event_bus.subscribe("app_state.changed", self._on_app_state_changed)', text)

    def test_event_bus_coalesces_async_app_state_changed_progress_events(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "core" / "event_bus.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn('"app_state.changed"', text)
        self.assertIn("ASYNC_NOISY_TOPICS", text)
        self.assertIn("payload.get(\"video_id\")", text)

    def test_frontend_state_service_config_listener_prefers_async_event_bus_subscription(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "frontend_state_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('subscribe_async = getattr(self.config, "subscribe_async", None)', text)
        self.assertIn('subscribe_async("config.changed", self._on_config_changed)', text)

    def test_frontend_state_service_app_state_listener_only_queues_before_flush(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "frontend_state_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('getattr(self.app_state.event_bus, "subscribe_async", None)', text)
        self.assertIn('subscribe_app_state(\n            "app_state.changed",\n            self._queue_app_state_change,', text)
        queue_block = text.split("def _queue_app_state_change", 1)[1].split(
            "def flush_pending_app_state_events",
            1,
        )[0]
        self.assertNotIn("_event_aggregator.record", queue_block)
        self.assertNotIn("_materialize_stage_title_for_event", queue_block)
        self.assertIn("flush_pending_app_state_events()", text)

    def test_web_directory_listing_does_not_walk_filesystem_on_event_loop(self) -> None:
        project_root = PROJECT_ROOT
        service_text = (project_root / "app" / "web" / "directory_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        server_text = (project_root / "app" / "web" / "server.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        service_block = service_text.split("async def list_directory", 1)[1].split(
            "@staticmethod\n    def _collect_subdirectories",
            1,
        )[0]
        self.assertIn("run_in_executor", service_block)
        self.assertNotIn("os.listdir(", service_block)
        self.assertIn("build_rest_router", server_text)
        self.assertNotIn("os.listdir(", server_text)

    def test_cache_service_sqlite_connections_are_context_managed(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "cache_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        sqlite_lines = [line.strip() for line in text.splitlines() if "sqlite3.connect(" in line]

        self.assertTrue(sqlite_lines)
        self.assertNotIn("self._conn", text)
        self.assertNotIn("self._connection", text)
        self.assertIn("from contextlib import closing", text)
        self.assertTrue(all(line.startswith("with closing(sqlite3.connect(") for line in sqlite_lines))

    def test_failed_record_store_sqlite_connections_are_context_managed(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "failed_record_store.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        sqlite_lines = [line.strip() for line in text.splitlines() if "sqlite3.connect(" in line]

        self.assertTrue(sqlite_lines)
        self.assertNotIn("self._conn", text)
        self.assertNotIn("self._connection", text)
        self.assertIn("from contextlib import closing", text)
        self.assertTrue(all(line.startswith("with closing(sqlite3.connect(") for line in sqlite_lines))

    def test_failed_record_store_exposes_structured_sql_query(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "failed_record_store.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("class FailedRecordQuery", text)
        self.assertIn("def query_records", text)
        self.assertIn("def _build_where_clause", text)
        self.assertIn("SELECT COUNT(*) FROM failed_records", text)
        self.assertIn("platform = ?", text)
        self.assertIn("trace_id LIKE ?", text)
        self.assertIn("payload_json LIKE ?", text)

    def test_failed_record_store_sqlite_queries_stay_out_of_ui_layers(self) -> None:
        project_root = PROJECT_ROOT
        roots = (
            project_root / "app" / "ui",
            project_root / "app" / "controllers",
            project_root / "app" / "web",
        )
        forbidden = (
            ".query_records(",
            ".records_snapshot(",
            "FailedRecordQuery(",
            "FailedRecordQueryResult(",
        )

        for root in roots:
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in forbidden:
                    with self.subTest(path=path.relative_to(project_root), token=token):
                        self.assertNotIn(token, text)

    def test_log_center_page_does_not_classify_logs_on_ui_thread(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "pages" / "log_center_page.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        forbidden = (
            "classification_facts",
            "derive_log_scope",
            "derive_event_stage",
            "derive_scope_reason",
            "_debug_classification",
            "_derive_log_scope",
            "_derive_event_stage",
            "decorate_log_item",
            "localize_log_text",
            "_decorate_log_item",
            "_localize_log_text",
        )

        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, text)

    def test_failed_page_uses_worker_display_projection_for_dynamic_logs(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "pages" / "failed_page.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("prepare_failed_item_for_display", text)
        self.assertIn("item_transformer=", text)
        self.assertIn("reason_detail_display", text)
        self.assertIn("log_excerpt_display_items", text)
        self.assertIn("solutions_display", text)
        self.assertNotIn("localize_log_text", text)
        self.assertNotIn("def _format_log_time", text)
        self.assertNotIn("text.split()", text)

    def test_active_download_timeline_uses_worker_display_projection(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "pages" / "active_downloads_page.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        timeline_block = text.split("class EventTimelineWidget", 1)[1].split(
            "class WideHitCheckBox",
            1,
        )[0]
        paint_block = timeline_block.split("def paintEvent", 1)[1]

        self.assertIn("prepare_active_item_for_display", text)
        self.assertIn("item_transformer=", text)
        self.assertIn("message_display", paint_block)
        self.assertNotIn("re.match", timeline_block)
        self.assertNotIn("_localized_message", timeline_block)
        self.assertNotIn("localize_active_event_message", timeline_block)

    def test_app_shell_video_lookup_uses_page_item_index(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "layout" / "app_shell.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        lookup_block = text.split("def row_for_video_id", 1)[1].split("def show_image", 1)[0]

        self.assertIn("_page_item_rows", text)
        self.assertIn("_refresh_page_item_indexes", text)
        self.assertIn("_page_item_indexes_initialized", text)
        self.assertNotIn("enumerate(self._items_for_page", lookup_block)
        self.assertNotIn("any(item.get(\"id\")", lookup_block)

    def test_frontend_snapshot_worker_materializes_page_indexes_for_app_shell(self) -> None:
        project_root = PROJECT_ROOT
        worker_text = (project_root / "app" / "ui" / "viewmodels" / "frontend_snapshot_worker.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        main_window_text = (project_root / "app" / "ui" / "main_window.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        app_shell_text = (project_root / "app" / "ui" / "layout" / "app_shell.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        render_call = main_window_text.split("self.app_shell.render(", 1)[1].split(
            "self._record_frontend_render_duration",
            1,
        )[0]

        self.assertIn("page_item_rows: dict[str, dict[str, int]]", worker_text)
        self.assertIn("completed_item_ids: tuple[str, ...]", worker_text)
        self.assertIn("_page_item_indexes(snapshot)", worker_text)
        self.assertIn("page_item_rows=result.page_item_rows", render_call)
        self.assertIn("completed_item_ids=result.completed_item_ids", render_call)
        self.assertIn("_apply_worker_page_item_indexes", app_shell_text)

    def test_media_host_play_video_submits_file_probe_before_playback(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "controllers" / "media_host_controller_mixin.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        play_block = text.split("def play_video", 1)[1].split(
            "def _should_check_playback_file_in_background",
            1,
        )[0]

        self.assertIn("_submit_playback_file_check", play_block)
        self.assertNotIn("os.path.exists", play_block)
        self.assertIn("def _submit_playback_file_check", text)

    def test_media_host_clear_queue_reuses_short_task_runner(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "controllers" / "media_host_controller_mixin.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        clear_block = text.split("def on_clear_queue", 1)[1].split(
            "def _should_clear_queue_in_background",
            1,
        )[0]

        self.assertIn("_ensure_short_task_runner().submit", clear_block)
        self.assertNotIn("threading.Thread", clear_block)
        self.assertNotIn("ClearDownloadQueueWorker", clear_block)

    def test_media_host_rename_video_submits_file_transaction_before_ui_finalize(self) -> None:
        project_root = PROJECT_ROOT
        host_text = (project_root / "app" / "controllers" / "media_host_controller_mixin.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        library_text = (project_root / "app" / "services" / "media_library_runtime.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        rename_block = host_text.split("def on_rename_video", 1)[1].split("def on_delete_video", 1)[0]

        self.assertIn("_submit_rename_video_task", rename_block)
        self.assertIn("_finalize_rename_video", rename_block)
        self.assertNotIn("os.path.exists", rename_block)
        self.assertIn("def _rename_video_io", library_text)

    def test_controller_media_entrypoints_do_not_probe_files_inline(self) -> None:
        project_root = PROJECT_ROOT
        host_text = (project_root / "app" / "controllers" / "media_host_controller_mixin.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        library_text = (project_root / "app" / "services" / "media_library_runtime.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        host_boundaries = (
            ("def play_video", "def _should_check_playback_file_in_background"),
            ("def on_rename_video", "def _submit_rename_video_task"),
            ("def on_delete_video", "def _submit_delete_video_task"),
        )

        for start, end in host_boundaries:
            with self.subTest(start=start):
                block = host_text.split(start, 1)[1].split(end, 1)[0]
                self.assertNotIn("os.path.exists", block)
                self.assertNotIn(".stat(", block)
                self.assertNotIn("open(", block)

        allowed_controller_io_helpers = {
            "app/controllers/media_host_controller_mixin.py": {"_playback_file_exists"},
            "app/services/media_library_runtime.py": {"_rename_video_io"},
        }
        for relative_path, allowed_helpers in allowed_controller_io_helpers.items():
            text = (project_root / relative_path).read_text(encoding="utf-8", errors="ignore")
            if "os.path.exists" not in text:
                continue
            for chunk in text.split("\n    def ")[1:]:
                method_name = chunk.split("(", 1)[0].strip()
                if "os.path.exists" in chunk:
                    with self.subTest(path=relative_path, method=method_name):
                        self.assertIn(method_name, allowed_helpers)

        self.assertIn("_ensure_short_task_runner().submit", host_text)
        self.assertIn("def _rename_video_io", library_text)

    def test_web_controller_media_paths_do_not_stat_on_event_loop(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "web" / "controller.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        async_rename_block = text.split("async def async_rename_video", 1)[1].split(
            "# ---- 配置 ----",
            1,
        )[0]
        get_media_path_block = text.split("def get_media_path", 1)[1].split(
            "# ---- 辅助 ----",
            1,
        )[0]

        self.assertNotIn("os.path.exists", async_rename_block)
        self.assertNotIn("os.path.exists", get_media_path_block)
        self.assertIn("run_in_executor", async_rename_block)

    def test_web_debug_file_downloads_do_not_probe_files_on_event_loop(self) -> None:
        project_root = PROJECT_ROOT
        router_text = (project_root / "app" / "web" / "rest_router.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        server_text = (project_root / "app" / "web" / "server.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        router_block = router_text.split('async def download_latest_log', 1)[1].split("return router", 1)[0]
        self.assertIn("await file_response_service.async_latest_log_response", router_block)
        self.assertIn("await file_response_service.async_latest_error_summary_response", router_block)
        self.assertIn("build_rest_router", server_text)
        self.assertNotIn("async def download_latest_log", server_text)

    def test_start_task_marquee_uses_low_frequency_timer(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "components" / "start_task_button.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("_MARQUEE_INTERVAL_MS = 120", text)
        self.assertIn("_MARQUEE_DEGREES_PER_TICK = 12.0", text)
        self.assertNotIn("setInterval(45)", text)

    def test_download_options_snapshot_uses_runtime_memory_not_cache_service(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "frontend_state_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        snapshot_block = text.split("def download_options_snapshot", 1)[1].split("def app_status", 1)[0]
        update_block = text.split("def _action_update_download_options", 1)[1].split("def _action_update_setting", 1)[0]

        self.assertIn("self._download_runtime_get", snapshot_block)
        self.assertNotIn("self.cache_service.get", snapshot_block)
        self.assertIn('self._download_runtime_options["auto_retry"]', update_block)

    def test_log_file_open_actions_use_frontend_action_worker(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "main_window.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        handler = text.split("def _handle_log_action", 1)[1].split("def _should_throttle_log_refresh", 1)[0]

        self.assertIn('self._submit_frontend_action("log_operation"', handler)
        self.assertNotIn("sig_open_latest_log.emit", handler)
        self.assertNotIn("sig_open_error_summary.emit", handler)

        controller_text = (project_root / "app" / "controllers" / "application_controller.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        self.assertNotIn("sig_open_latest_log.connect", controller_text)
        self.assertNotIn("sig_open_error_summary.connect", controller_text)

    def test_qtablewidget_hot_paths_do_not_clear_and_rebuild_rows(self) -> None:
        project_root = PROJECT_ROOT
        offenders: list[str] = []
        for path in (project_root / "app" / "ui").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "setRowCount(0)" in text:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_domain_event_bus_handlers_only_queue_dispatch(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "controllers" / "application_controller.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("self._spider_domain_event_handler = self._queue_spider_domain_event", text)
        self.assertIn("self._download_domain_event_handler = self._queue_download_domain_event", text)
        self.assertIn('subscribe_async = getattr(self.event_bus, "subscribe_async", None)', text)
        self.assertIn("self._host()._queue_on_ui(lambda: dispatcher(event))", text)
        self.assertNotIn("self._host()._run_on_ui(lambda: dispatcher(event))", text)
        self.assertNotIn("QTimer.singleShot(0, lambda: dispatcher(event))", text)
        self.assertNotIn("QThread.currentThread()", text)
        self.assertNotIn('self.event_bus.subscribe("spider.domain_event", self._dispatch_spider_event)', text)
        self.assertNotIn('self.event_bus.subscribe("download.domain_event", self._dispatch_download_event)', text)
        self.assertNotIn('self.event_bus.subscribe("spider.domain_event", self._spider_domain_event_handler)', text)
        self.assertNotIn(
            'self.event_bus.subscribe("download.domain_event", self._download_domain_event_handler)',
            text,
        )

    def test_spider_selection_dialog_uses_host_ui_queue(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "controllers" / "crawl_controller_mixin.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        block = text.split("def _schedule_spider_selection", 1)[1].split("def _create_spider", 1)[0]

        self.assertIn("_queue_on_ui", block)
        self.assertNotIn("QCoreApplication", block)
        self.assertNotIn("QThread.currentThread()", block)
        self.assertNotIn("QTimer.singleShot", block)

    def test_four_state_gui_pages_use_list_page_worker_batches(self) -> None:
        project_root = PROJECT_ROOT
        page_paths = [
            project_root / "app" / "ui" / "pages" / "download_queue_page.py",
            project_root / "app" / "ui" / "pages" / "active_downloads_page.py",
            project_root / "app" / "ui" / "pages" / "completed_page.py",
            project_root / "app" / "ui" / "pages" / "failed_page.py",
        ]
        forbidden = ("page_slice(", "page_for_item(", "total_pages(")

        for path in page_paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(path=path.name):
                self.assertIn("ListPageWorker", text)
                self.assertNotIn("build_list_page_result", text)
                self.assertNotIn("ASYNC_ITEM_THRESHOLD", text)
                self.assertIn("Qt.ConnectionType.QueuedConnection", text)
                for needle in forbidden:
                    self.assertNotIn(needle, text)

        queue_text = page_paths[0].read_text(encoding="utf-8", errors="ignore")
        completed_text = page_paths[2].read_text(encoding="utf-8", errors="ignore")
        self.assertIn("selected_id_moves_page=True", queue_text)
        self.assertIn("selected_id_moves_page=False", queue_text)
        self.assertIn("selected_id_moves_page=True", completed_text)
        self.assertIn("selected_id_moves_page=False", completed_text)

    def test_event_bus_noisy_async_topics_use_latest_state_wins(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "core" / "event_bus.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("ASYNC_NOISY_TOPICS", text)
        self.assertIn("ASYNC_TOPIC_LATEST_KEYS", text)
        self.assertIn("_async_pending_latest", text)
        self.assertIn("_AsyncTaskKey", text)
        self.assertIn("_enqueue_latest_async_handler", text)
        self.assertIn("_async_topic_latest_key", text)
        for topic in ("videos.update", "videos.metadata", "video_state_changed", "task_progress", "logs.append", "log"):
            with self.subTest(topic=topic):
                self.assertIn(topic, text)

    def test_gui_hot_widgets_do_not_touch_files_cache_or_sqlite(self) -> None:
        project_root = PROJECT_ROOT
        forbidden = (
            "read_text(",
            "read_bytes(",
            "write_text(",
            "write_bytes(",
            "sqlite3",
            "DiskCache",
            "cache_service.",
            "get_snapshot(",
        )
        paths = [project_root / "app" / "ui" / "main_window.py"]
        paths.extend((project_root / "app" / "ui" / "pages").rglob("*.py"))
        paths.extend((project_root / "app" / "ui" / "components").rglob("*.py"))
        paths.extend((project_root / "app" / "ui" / "dialogs").rglob("*.py"))
        paths.extend((project_root / "app" / "ui" / "layout").rglob("*.py"))
        paths.extend(
            [
                project_root / "app" / "ui" / "gui_selection_strategy.py",
            ]
        )
        offenders: list[str] = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_ui_and_web_hot_paths_do_not_call_synchronous_log_refresh(self) -> None:
        project_root = PROJECT_ROOT
        forbidden = (
            "refresh_file_log_cache(",
            "refresh_now(",
            "wait_for_idle(",
        )
        roots = [
            project_root / "app" / "ui",
            project_root / "app" / "controllers",
            project_root / "app" / "web",
        ]
        offenders: list[str] = []
        for root in roots:
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if any(token in text for token in forbidden):
                    offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_frontend_state_service_file_log_cache_uses_background_worker(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "frontend_state_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        constructor_block = text.split("self._file_log_cache_store = FrontendLogCache(", 1)[1].split(
            "self._running_state",
            1,
        )[0]

        self.assertIn("worker_enabled=True", constructor_block)
        self.assertIn("on_refresh=self._on_file_log_cache_refreshed", constructor_block)

    def test_runtime_i18n_catalog_is_static_and_matches_json_sources(self) -> None:
        project_root = PROJECT_ROOT
        from shared.i18n_catalogs import CATALOGS

        expected = {"zh-CN": {}, "en-US": {}, "zh-TW": {}}
        for language in ("en-US", "zh-TW"):
            path = project_root / "app" / "ui" / "i18n" / f"{language}.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            expected[language] = {str(key): str(value) for key, value in raw.items()}

        catalog_source = (project_root / "shared" / "i18n_catalogs.py").read_text(encoding="utf-8")
        longest_line = max((len(line) for line in catalog_source.splitlines()), default=0)

        self.assertEqual(CATALOGS, expected)
        self.assertLessEqual(longest_line, 240)

    def test_fifo_workers_use_shared_sequential_worker(self) -> None:
        project_root = PROJECT_ROOT
        worker_sources = (
            project_root / "app" / "ui" / "viewmodels" / "frontend_action_worker.py",
            project_root / "app" / "ui" / "viewmodels" / "log_detail_worker.py",
        )
        for path in worker_sources:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIn("SequentialRequestWorker", text)
                self.assertNotIn("threading.Condition(", text)
                self.assertNotIn("threading.Thread(", text)

    def test_main_window_log_action_does_not_call_frontend_service_inline(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")
        block = text.split("def _handle_log_action", 1)[1].split("def _should_throttle_log_refresh", 1)[0]

        self.assertNotIn(".handle_action(", block)

    def test_main_window_slow_frontend_actions_use_worker(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")
        boundaries = [
            ("def _refresh_platform_auth_if_needed", "def _on_page_changed"),
            ("def _open_item_directory", "def _retry_failed_item"),
            ("def _retry_failed_item", "def _copy_item_diagnostics"),
            ("def _copy_item_diagnostics", "def _update_basic_setting"),
            ("def _update_basic_setting", "def _apply_runtime_setting_after_update"),
            ("def _update_download_options", "def _update_completed_metadata"),
            ("def _pause_download_item", "def _run_tool"),
            ("def _run_tool", "def _register_file_associations_from_frontend"),
            ("def _register_file_associations_from_frontend", None),
        ]

        for start, end in boundaries:
            with self.subTest(start=start):
                block = text.split(start, 1)[1]
                if end is not None:
                    block = block.split(end, 1)[0]
                self.assertNotIn(".handle_action(", block)
                self.assertIn("_submit_frontend_action(", block)

    def test_file_association_registration_stays_on_frontend_action_worker(self) -> None:
        project_root = PROJECT_ROOT
        main_window_text = (project_root / "app" / "ui" / "main_window.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        controller_text = (project_root / "app" / "controllers" / "application_controller.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        click_block = main_window_text.split("def on_btn_file_association_clicked", 1)[1].split(
            "def show_file_association_dialog",
            1,
        )[0]

        self.assertIn("_register_file_associations_from_frontend(", click_block)
        self.assertNotIn("sig_register_file_associations.emit", click_block)
        self.assertNotIn("WindowsFileAssociationService", controller_text)
        self.assertNotIn("def on_register_file_associations", controller_text)
        self.assertNotIn("def _current_executable_path", controller_text)
        self.assertNotIn("sig_register_file_associations.connect", controller_text)
        self.assertNotIn("register_current_user(", controller_text)

    def test_update_check_request_uses_shared_latest_worker(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")
        request_block = text.split("def _on_update_check_requested", 1)[1].split(
            "def _try_begin_update_check",
            1,
        )[0]

        self.assertIn("LatestRequestWorker", text)
        self.assertIn("_update_check_worker", request_block)
        self.assertIn("worker.submit(", request_block)
        self.assertNotIn("threading.Thread", request_block)
        self.assertNotIn(".start()", request_block)

    def test_main_window_completed_metadata_update_uses_worker_action(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")
        block = text.split("def _update_completed_metadata", 1)[1].split("def _pause_download_item", 1)[0]

        self.assertIn('_submit_frontend_action(\n            "update_completed_metadata"', block)
        self.assertNotIn("._frontend_state_service.update_completed_metadata", block)

    def test_media_preview_play_video_uses_async_repair_cache_lookup(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "components" / "media_preview_panel.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        play_video_block = text.split("def play_video", 1)[1].split("def stop_playback", 1)[0]

        self.assertIn("_submit_cached_playable_path_lookup", play_video_block)
        self.assertIn("sig_cached_playable_path_ready", text)
        self.assertNotIn("cached_playable_path(", play_video_block)

    def test_media_preview_disk_backed_state_uses_short_task_runners(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "ui" / "components" / "media_preview_panel.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        init_block = text.split("def __init__", 1)[1].split("def set_language", 1)[0]
        restore_block = text.split("def _submit_playback_position_restore", 1)[1].split(
            "def _submit_playback_position_save",
            1,
        )[0]
        save_block = text.split("def _submit_playback_position_save", 1)[1].split(
            "def _submit_playback_position_delete",
            1,
        )[0]
        delete_block = text.split("def _submit_playback_position_delete", 1)[1].split(
            "def _submit_playback_position_clear",
            1,
        )[0]
        clear_block = text.split("def _submit_playback_position_clear", 1)[1].split(
            "def _refresh_image_auto_advance_timer",
            1,
        )[0]

        self.assertIn("MkvPlaybackRepairService(cleanup_on_init=False)", init_block)
        self.assertIn("PlaybackPositionService(load_on_init=False)", init_block)
        self.assertIn("_playback_position_task_runner = ShortTaskRunner", init_block)
        for block in (restore_block, save_block, delete_block, clear_block):
            with self.subTest(block=block[:48]):
                self.assertIn("_playback_position_task_runner.submit", block)

    def test_failed_record_store_worker_state_resets_in_finally(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "services" / "failed_record_store.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        worker_block = text.split("def _worker_loop", 1)[1].split("def _init_db", 1)[0]

        self.assertIn("except Exception as exc", worker_block)
        self.assertIn("finally:", worker_block)
        self.assertIn("self._writing = False", worker_block)
        self.assertIn("self._refreshing = False", worker_block)

    def test_gui_hot_paths_do_not_persist_config_inline(self) -> None:
        project_root = PROJECT_ROOT
        files = [
            project_root / "app" / "ui" / "main_window.py",
            project_root / "app" / "ui" / "plugin_settings.py",
        ]

        for path in files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("cfg.set(", text)
                self.assertNotIn("cfg.set_many(", text)
                self.assertNotIn("cfg.update_missav_proxy(", text)

    def test_web_frontend_routes_do_not_build_snapshots_on_event_loop(self) -> None:
        project_root = PROJECT_ROOT
        forbidden = (
            "return controller.get_frontend_state()",
            "return getter(since_version)",
            '"sections": snapshot_getter()',
            "delta = delta_getter(frontend_version)",
        )
        offenders: list[str] = []
        for path in (project_root / "app" / "web").glob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_web_controller_sync_api_work_runs_in_executor(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "web" / "controller.py").read_text(encoding="utf-8", errors="ignore")
        operation_block = text.split("async def _run_api_operation", 1)[1].split("async def async_update_config", 1)[0]
        action_block = text.split("async def async_handle_frontend_action", 1)[1].split("    # ----", 1)[0]

        self.assertIn("run_in_executor", operation_block)
        self.assertIn("inspect.iscoroutinefunction(func)", operation_block)
        self.assertIn("self._run_api_operation(\"frontend_action\", self.handle_frontend_action", action_block)

    def test_web_media_range_streaming_does_not_read_files_on_event_loop(self) -> None:
        project_root = PROJECT_ROOT
        service_text = (project_root / "app" / "web" / "file_response_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        server_text = (project_root / "app" / "web" / "server.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        router_text = (project_root / "app" / "web" / "rest_router.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertNotIn("async def stream_range", service_text)
        self.assertNotIn("async def stream_range", server_text)
        self.assertIn("run_in_executor", service_text)
        self.assertIn("def _iter_file_range", service_text)
        self.assertNotIn("def _iter_file_range", server_text)
        self.assertNotIn("def _media_file_info", server_text)
        media_route_block = router_text.split('@router.get("/api/media/{video_id}")', 1)[1].split(
            '@router.get("/api/dir/list")',
            1,
        )[0]
        self.assertIn("file_response_service.get_media", media_route_block)
        self.assertIn('alias="Range"', media_route_block)
        self.assertIn("range_header", media_route_block)
        self.assertNotIn("require_session_token=False", media_route_block)
        self.assertNotIn("StreamingResponse", media_route_block)
        self.assertNotIn("FileResponse", media_route_block)
        self.assertNotIn('@app.get("/api/media/{video_id}")', server_text)

    def test_web_bootstrap_and_rest_getters_use_worker_executor(self) -> None:
        project_root = PROJECT_ROOT
        bootstrap = (project_root / "app" / "web" / "ws_bootstrap.py").read_text(encoding="utf-8", errors="ignore")
        rest_router = (project_root / "app" / "web" / "rest_router.py").read_text(encoding="utf-8", errors="ignore")
        server = (project_root / "app" / "web" / "server.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("run_in_executor", bootstrap)
        self.assertIn("await _run_controller_worker_call(controller.get_state)", bootstrap)
        self.assertIn("snapshot = await _run_controller_worker_call(getter)", bootstrap)
        self.assertIn("await _run_controller_worker_call(_encode_message", bootstrap)
        self.assertNotIn("snapshot = getter()", bootstrap)
        self.assertNotIn("await ws.send_text(json.dumps", bootstrap)

        self.assertIn("await _run_controller_worker_call(get_request_context(request).controller.get_platforms)", rest_router)
        self.assertIn("await _run_controller_worker_call(get_request_context(request).controller.get_config)", rest_router)
        self.assertIn("await _run_controller_worker_call(get_request_context(request).controller.get_state)", rest_router)

        self.assertIn("build_rest_router", server)
        self.assertNotIn('@app.get("/api/platforms")', server)
        self.assertNotIn('@app.get("/api/config")', server)
        self.assertNotIn('@app.get("/api/state")', server)

    def test_websocket_dispatcher_config_mutations_use_worker_executor(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "web" / "ws_dispatcher.py").read_text(encoding="utf-8", errors="ignore")
        theme_block = text.split("async def _handle_change_theme", 1)[1].split(
            "async def _handle_change_source",
            1,
        )[0]
        source_block = text.split("async def _handle_change_source", 1)[1].split(
            "async def _handle_save_config",
            1,
        )[0]
        save_block = text.split("async def _handle_save_config", 1)[1].split(
            "async def _handle_delete_video",
            1,
        )[0]

        self.assertIn("def _set_config_values", text)
        self.assertIn("def _set_config_value", text)
        self.assertIn("await _run_controller_worker_call(self._set_config_values, \"common\", theme_values)", theme_block)
        self.assertNotIn("cfg.set(", theme_block)
        self.assertNotIn("set_many(", theme_block)

        self.assertIn(
            'await _run_controller_worker_call(self._set_config_value, "common", "last_source", new_source)',
            source_block,
        )
        self.assertNotIn("cfg.set(", source_block)

        self.assertIn("await _run_controller_worker_call(", save_block)
        self.assertIn("self._config_service.update_single_config,", save_block)
        self.assertIn("approved_roots=approved_roots", save_block)
        self.assertNotIn("self._config_service.update_single_config(section, key, value)", save_block)

    def test_web_stop_crawl_handlers_use_worker_executor(self) -> None:
        project_root = PROJECT_ROOT
        dispatcher_text = (project_root / "app" / "web" / "ws_dispatcher.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        workflow_text = (project_root / "app" / "web" / "workflow_route_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        server_text = (project_root / "app" / "web" / "server.py").read_text(encoding="utf-8", errors="ignore")

        dispatcher_block = dispatcher_text.split("async def _handle_stop_crawl", 1)[1].split(
            "async def _handle_select_tasks",
            1,
        )[0]
        workflow_block = workflow_text.split("async def stop_crawl", 1)[1].split(
            "async def select_tasks",
            1,
        )[0]

        self.assertIn("await _run_controller_worker_call(context.controller.stop_crawl)", dispatcher_block)
        self.assertNotIn("context.controller.stop_crawl()", dispatcher_block)

        self.assertIn("await _run_controller_worker_call(context.controller.stop_crawl)", workflow_block)
        self.assertNotIn(".controller.stop_crawl()", workflow_block)

        self.assertIn("build_rest_router", server_text)
        self.assertNotIn("async def stop_crawl", server_text)

    def test_websocket_transport_encodes_outbound_messages_off_loop(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "app" / "web" / "ws_transport.py").read_text(encoding="utf-8", errors="ignore")
        emit_block = text.split("async def _emit_to_connections", 1)[1].split("    def _build_message", 1)[0]
        build_async_block = text.split("async def _build_message_async", 1)[1].split("    def _build_message", 1)[0]

        self.assertIn("message = await self._build_message_async(event_type, data)", emit_block)
        self.assertIn("run_in_executor", build_async_block)
        self.assertNotIn("message = self._build_message(event_type, data)", emit_block)

    def test_frontend_refresh_doc_has_entry_audit_and_current_baseline(self) -> None:
        project_root = PROJECT_ROOT
        text = (project_root / "docs" / "engineering" / "frontend-refresh-and-concurrency.md").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("## 入口审计表", text)
        for row in (
            "| GUI 日志中心 |",
            "| GUI 失败列表 |",
            "| GUI 四态列表 |",
            "| Web `/api/frontend/state` |",
            "| Web `/api/frontend/delta` |",
            "| WebSocket `frontend_action` |",
            "| Web 爬取控制 |",
            "| Web 媒体文件 |",
            "| Spider/parser 解析缓存 |",
        ):
            with self.subTest(row=row):
                self.assertIn(row, text)
        full_command = (
            "python -X faulthandler -m pytest -q --timeout=90 "
            "--timeout-method=thread --session-timeout=1500"
        )
        self.assertIn(full_command, text)
        baseline = re.search(
            rf"2026-07-14[^\n]*full：`{re.escape(full_command)}`：`(?P<passed>\d+) passed, "
            r"(?P<skipped>\d+) skipped, (?P<warnings>\d+) warnings in [^`]+`",
            text,
        )
        self.assertIsNotNone(baseline, "missing structured full-suite baseline")
        assert baseline is not None
        self.assertEqual(int(baseline.group("passed")), 2613)
        self.assertEqual(int(baseline.group("skipped")), 3)
        self.assertEqual(int(baseline.group("warnings")), 2)
        self.assertNotIn("2244 passed", text)
        self.assertIn("app.spiders.parser_cache.cached_parser_result()", text)


if __name__ == "__main__":
    unittest.main()
