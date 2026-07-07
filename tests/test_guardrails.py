from __future__ import annotations

import json
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
        project_root = Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        for path in (project_root / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "processEvents(" in text:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_browser_e2e_does_not_use_legacy_fixed_3_5_second_waits(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        forbidden = ("time.sleep(3.5", "wait_for_timeout(3500", "sleep(3500")
        offenders: list[str] = []
        for path in (project_root / "tests").rglob("test_web*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_gui_controllers_do_not_synchronously_build_frontend_snapshots(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        for path in (project_root / "app" / "controllers").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "get_snapshot(" in text:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_main_window_app_state_event_bus_handler_uses_qt_queue(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("_app_state_changed_queued = pyqtSignal(object)", text)
        self.assertIn('self.event_bus.subscribe("app_state.changed", self._queue_app_state_changed)', text)
        self.assertNotIn('self.event_bus.subscribe("app_state.changed", self._on_app_state_changed)', text)

    def test_frontend_state_service_config_listener_prefers_async_event_bus_subscription(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "services" / "frontend_state_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('subscribe_async = getattr(self.config, "subscribe_async", None)', text)
        self.assertIn('subscribe_async("config.changed", self._on_config_changed)', text)

    def test_frontend_state_service_app_state_listener_only_queues_before_flush(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "services" / "frontend_state_service.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('self.app_state.event_bus.subscribe(\n            "app_state.changed",\n            self._queue_app_state_change,', text)
        queue_block = text.split("def _queue_app_state_change", 1)[1].split(
            "def flush_pending_app_state_events",
            1,
        )[0]
        self.assertNotIn("_event_aggregator.record", queue_block)
        self.assertNotIn("_materialize_stage_title_for_event", queue_block)
        self.assertIn("flush_pending_app_state_events()", text)

    def test_cache_service_sqlite_connections_are_context_managed(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
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
        project_root = Path(__file__).resolve().parents[1]
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

    def test_log_center_page_does_not_classify_logs_on_ui_thread(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
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
        )

        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, text)

    def test_start_task_marquee_uses_low_frequency_timer(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "ui" / "components" / "start_task_button.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("_MARQUEE_INTERVAL_MS = 120", text)
        self.assertIn("_MARQUEE_DEGREES_PER_TICK = 12.0", text)
        self.assertNotIn("setInterval(45)", text)

    def test_log_file_open_actions_use_frontend_action_worker(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "ui" / "main_window.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        handler = text.split("def _handle_log_action", 1)[1].split("def _should_throttle_log_refresh", 1)[0]

        self.assertIn('self._submit_frontend_action("log_operation"', handler)
        self.assertNotIn("sig_open_latest_log.emit", handler)
        self.assertNotIn("sig_open_error_summary.emit", handler)

    def test_qtablewidget_hot_paths_do_not_clear_and_rebuild_rows(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        for path in (project_root / "app" / "ui").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "setRowCount(0)" in text:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_domain_event_bus_handlers_only_queue_dispatch(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "controllers" / "application_controller.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("self._spider_domain_event_handler = self._queue_spider_domain_event", text)
        self.assertIn("self._download_domain_event_handler = self._queue_download_domain_event", text)
        self.assertIn("QTimer.singleShot(0, lambda: dispatcher(event))", text)
        self.assertNotIn('self.event_bus.subscribe("spider.domain_event", self._dispatch_spider_event)', text)
        self.assertNotIn('self.event_bus.subscribe("download.domain_event", self._dispatch_download_event)', text)

    def test_event_bus_noisy_async_topics_use_latest_state_wins(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "core" / "event_bus.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("ASYNC_NOISY_TOPICS", text)
        self.assertIn("_async_pending_latest", text)
        self.assertIn("_AsyncTaskKey", text)
        self.assertIn("_enqueue_latest_async_handler", text)
        for topic in ("videos.update", "video_state_changed", "task_progress", "logs.append", "log"):
            with self.subTest(topic=topic):
                self.assertIn(topic, text)

    def test_gui_hot_widgets_do_not_touch_files_cache_or_sqlite(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
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
                project_root / "app" / "ui" / "localization.py",
            ]
        )
        offenders: list[str] = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_runtime_i18n_catalog_is_static_and_matches_json_sources(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        from app.ui.i18n_catalogs import CATALOGS

        expected = {"zh-CN": {}, "en-US": {}, "zh-TW": {}}
        for language in ("en-US", "zh-TW"):
            path = project_root / "app" / "ui" / "i18n" / f"{language}.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            expected[language] = {str(key): str(value) for key, value in raw.items()}

        self.assertEqual(CATALOGS, expected)

    def test_fifo_workers_use_shared_sequential_worker(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
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
        project_root = Path(__file__).resolve().parents[1]
        text = (project_root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8", errors="ignore")
        block = text.split("def _handle_log_action", 1)[1].split("def _should_throttle_log_refresh", 1)[0]

        self.assertNotIn(".handle_action(", block)

    def test_main_window_slow_frontend_actions_use_worker(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
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

    def test_gui_hot_paths_do_not_persist_config_inline(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
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
        project_root = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
