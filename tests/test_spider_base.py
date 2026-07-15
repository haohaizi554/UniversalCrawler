"""BaseSpider 纯 Python 线程与信号契约测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
import threading
from unittest.mock import Mock, patch

from app.models.video_item import VideoItem
from app.spiders.base import BaseSpider
from app.utils.callback_signal import CallbackSignal
from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation

class _DummySpider(BaseSpider):
    """最小 spider 实现，用于验证 BaseSpider 信号和线程契约。"""

    def run(self):
        self.log("started")
        self.emit_video(
            url="https://cdn.example.com/demo.mp4",
            title="demo",
            source="douyin",
            meta={"trace_id": "trace-spider-base"},
        )
        self.sig_finished.emit()

class _RunImplSpider(BaseSpider):
    def _run_impl(self):
        self.log("impl")

class BaseSpiderTests(unittest.TestCase):
    def setUp(self):
        public_policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [
                (None, None, None, None, ("93.184.216.34", 443))
            ]
        )
        policy_patch = patch("app.spiders.base.PUBLIC_DOMAIN_POLICY", public_policy)
        policy_patch.start()
        self.addCleanup(policy_patch.stop)

    def test_restricted_request_hook_rejects_off_platform_redirect(self):
        spider = _DummySpider(keyword="demo", config={})
        spider._public_domain_policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [
                (None, None, None, None, ("93.184.216.34", 443))
            ]
        )
        request_kwargs = spider._restricted_public_request_kwargs(
            "https://b23.tv/demo",
            allowed_hosts=("b23.tv", "bilibili.com"),
        )
        hook = request_kwargs["hooks"]["response"]
        response = SimpleNamespace(
            status_code=302,
            url="https://b23.tv/demo",
            headers={"Location": "https://attacker.example/payload"},
        )

        with self.assertRaisesRegex(DomainPolicyViolation, "不属于目标平台"):
            hook(response)

    def test_playwright_navigation_rejects_hostname_resolving_to_loopback(self):
        spider = _DummySpider(keyword="demo", config={})
        spider._public_domain_policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [
                (None, None, None, None, ("127.0.0.1", 443))
            ]
        )
        page = SimpleNamespace(
            url="about:blank",
            goto=lambda *_args, **_kwargs: self.fail("page.goto must not be called"),
        )

        with self.assertRaisesRegex(DomainPolicyViolation, "本地或内网"):
            spider.interruptible_playwright_goto(
                page,
                "https://internal.example/private",
            )

    def test_playwright_route_aborts_private_subresources(self):
        spider = _DummySpider(keyword="demo", config={})
        spider._public_domain_policy = DomainPolicyEngine(
            resolver=lambda host, *_args, **_kwargs: [
                (None, None, None, None, ("127.0.0.1" if host == "internal.example" else "93.184.216.34", 443))
            ]
        )
        route_handlers = []

        class FakePage:
            url = "about:blank"

            def route(self, pattern, handler):
                self.pattern = pattern
                route_handlers.append(handler)

            def goto(self, url, **_kwargs):
                self.url = url

        page = FakePage()
        self.assertTrue(spider.interruptible_playwright_goto(page, "https://example.com"))

        route = SimpleNamespace(abort=Mock(), continue_=Mock())
        request = SimpleNamespace(url="http://internal.example/latest/meta-data")
        route_handlers[0](route, request)

        self.assertEqual(page.pattern, "**/*")
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    def test_playwright_route_is_installed_on_context_for_popup_navigation(self):
        spider = _DummySpider(keyword="demo", config={})
        spider._public_domain_policy = DomainPolicyEngine(
            resolver=lambda host, *_args, **_kwargs: [
                (None, None, None, None, ("127.0.0.1" if host == "internal.example" else "93.184.216.34", 443))
            ]
        )
        context_handlers = []
        page_handlers = []

        class FakeContext:
            def add_init_script(self, _script):
                return None

            def route(self, pattern, handler):
                self.pattern = pattern
                context_handlers.append(handler)

        class FakePage:
            url = "about:blank"
            context = FakeContext()

            def route(self, _pattern, handler):
                page_handlers.append(handler)

            def goto(self, url, **_kwargs):
                self.url = url

        page = FakePage()
        self.assertTrue(spider.interruptible_playwright_goto(page, "https://example.com"))

        self.assertEqual(page.context.pattern, "**/*")
        self.assertEqual(len(context_handlers), 1)
        self.assertEqual(page_handlers, [])

        popup_route = SimpleNamespace(abort=Mock(), continue_=Mock())
        popup_request = SimpleNamespace(url="http://internal.example/admin")
        context_handlers[0](popup_route, popup_request)

        popup_route.abort.assert_called_once()
        popup_route.continue_.assert_not_called()

    def test_playwright_route_rejects_private_websockets_before_connecting(self):
        spider = _DummySpider(keyword="demo", config={})
        spider._public_domain_policy = DomainPolicyEngine(
            resolver=lambda host, *_args, **_kwargs: [
                (None, None, None, None, ("127.0.0.1" if host == "internal.example" else "93.184.216.34", 443))
            ]
        )
        websocket_handlers = []
        init_scripts = []

        class FakeContext:
            def add_init_script(self, script):
                init_scripts.append(script)

        class FakePage:
            url = "about:blank"
            context = FakeContext()

            def route(self, _pattern, _handler):
                return None

            def route_web_socket(self, pattern, handler):
                self.websocket_pattern = pattern
                websocket_handlers.append(handler)

            def goto(self, url, **_kwargs):
                self.url = url

        page = FakePage()
        self.assertTrue(spider.interruptible_playwright_goto(page, "https://example.com"))
        self.assertEqual(page.websocket_pattern, "**/*")
        self.assertEqual(len(websocket_handlers), 1)
        self.assertEqual(len(init_scripts), 1)
        self.assertIn("WebSocket", init_scripts[0])
        self.assertIn("SharedWorker", init_scripts[0])

        private_socket = SimpleNamespace(
            url="ws://internal.example/latest/meta-data",
            close=Mock(),
            connect_to_server=Mock(),
        )
        websocket_handlers[0](private_socket)
        private_socket.close.assert_called_once()
        private_socket.connect_to_server.assert_not_called()

        public_socket = SimpleNamespace(
            url="wss://example.com/events",
            close=Mock(),
            connect_to_server=Mock(),
        )
        websocket_handlers[0](public_socket)
        public_socket.close.assert_not_called()
        public_socket.connect_to_server.assert_called_once_with()

    def test_playwright_context_blocks_service_workers_from_bypassing_routes(self):
        spider = _DummySpider(keyword="demo", config={})

        context_kwargs = spider._playwright_context_kwargs(user_agent="ua-demo")

        self.assertEqual(context_kwargs["service_workers"], "block")

    def test_base_spider_runs_without_qt_and_emits_callbacks(self):
        logs: list[str] = []
        items = []
        finished = []

        spider = _DummySpider(keyword="demo", config={})
        spider.sig_log.connect(logs.append)
        spider.sig_item_found.connect(items.append)
        spider.sig_finished.connect(lambda: finished.append(True))

        spider.start()

        self.assertTrue(spider.wait(1000))
        self.assertFalse(spider.isRunning())
        self.assertEqual(logs, ["started"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "demo")
        self.assertEqual(finished, [True])

    def test_emit_video_marks_discovered_download_as_public_network(self):
        spider = _DummySpider(keyword="demo", config={})
        items = []
        spider.sig_item_found.connect(items.append)

        spider.emit_video(
            url="https://cdn.example.com/demo.mp4",
            title="demo",
            source="douyin",
            meta={"trace_id": "trace-one", "_network_policy": "local"},
        )

        self.assertEqual(items[0].meta["_network_policy"], "public")

    def test_emit_videos_marks_every_discovered_download_as_public_network(self):
        spider = _DummySpider(keyword="demo", config={})
        batches = []
        spider.sig_items_found.connect(batches.append)
        items = [
            VideoItem(url="https://cdn.example.com/one.mp4", title="one", source="douyin"),
            VideoItem(url="https://cdn.example.com/two.mp4", title="two", source="douyin"),
        ]

        emitted = spider.emit_videos(items)

        self.assertEqual(emitted, 2)
        self.assertEqual(
            [item.meta["_network_policy"] for item in batches[0]],
            ["public", "public"],
        )

    def test_base_run_marks_internal_running_state_false_before_finish_signal(self):
        observed: list[bool] = []
        spider = _RunImplSpider(keyword="demo", config={})
        spider.sig_finished.connect(lambda: observed.append(spider.is_running))

        spider.start()

        self.assertTrue(spider.wait(1000))
        self.assertEqual(observed, [False])
        self.assertFalse(spider.is_running)

    def test_callback_signal_disconnect_clears_subscribers(self):
        logs: list[str] = []
        spider = _DummySpider(keyword="demo", config={})
        spider.sig_log.connect(logs.append)
        spider.sig_log.disconnect()

        spider.log("ignored")

        self.assertEqual(logs, [])

    def test_callback_signal_isolates_failing_subscribers(self):
        signal = CallbackSignal()
        calls: list[tuple[str, str]] = []

        def broken(value: str) -> None:
            calls.append(("broken", value))
            raise RuntimeError("boom")

        def healthy(value: str) -> None:
            calls.append(("healthy", value))

        signal.connect(broken)
        signal.connect(healthy)

        with self.assertLogs("app.utils.callback_signal", level="ERROR") as logs:
            signal.emit("payload")

        self.assertEqual(calls, [("broken", "payload"), ("healthy", "payload")])
        self.assertTrue(any("subscriber failed" in line for line in logs.output))

    def test_callback_signal_warns_for_slow_subscribers(self):
        signal = CallbackSignal()
        signal.SLOW_CALLBACK_SECONDS = 0.01
        signal.connect(lambda: None)

        with (
            patch("app.utils.callback_signal.time.perf_counter", side_effect=[10.0, 10.2]),
            self.assertLogs("app.utils.callback_signal", level="WARNING") as logs,
        ):
            signal.emit()

        self.assertTrue(any("subscriber was slow" in line for line in logs.output))

    def test_is_running_property_tolerates_concurrent_reads_and_writes(self):
        spider = _DummySpider(keyword="demo", config={})
        errors: list[Exception] = []

        def writer(value: bool) -> None:
            try:
                for _ in range(100):
                    spider.is_running = value
                    self.assertIsInstance(spider.is_running, bool)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(value,)) for value in (False, True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        spider.is_running = False

        self.assertEqual(errors, [])
        self.assertFalse(spider.is_running)

    def test_browser_headless_follows_visibility_setting_except_login(self):
        spider = _DummySpider(keyword="demo", config={"show_browser_window": False})

        self.assertTrue(spider._browser_headless())
        self.assertFalse(spider._browser_headless(login_window=True))

        spider.config = {"show_browser_window": "visible"}
        self.assertFalse(spider._browser_headless())

        spider.config = {"show_browser_window": "headless"}
        self.assertTrue(spider._browser_headless())

    def test_stop_closes_tracked_playwright_browser_from_control_thread(self):
        spider = _DummySpider(keyword="demo", config={})

        class FakeBrowser:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        browser = FakeBrowser()
        spider._track_playwright_browser(browser)

        # stop 可能从 GUI/CLI 控制线程调用，不能依赖 spider 自己的 run 线程
        # 才能关闭 Playwright 浏览器资源。
        worker = threading.Thread(target=spider.stop)
        worker.start()
        worker.join(timeout=1)

        self.assertTrue(browser.closed)
        self.assertFalse(spider.is_playwright_browser_tracked())
        self.assertFalse(spider.is_running)

    def test_interruptible_playwright_goto_returns_when_stopped_during_timeout_slice(self):
        spider = _DummySpider(keyword="demo", config={})
        calls: list[int] = []

        class PlaywrightLikeTimeoutError(Exception):
            pass

        PlaywrightLikeTimeoutError.__name__ = "TimeoutError"

        class FakePage:
            def goto(self, *_args, **_kwargs):
                calls.append(1)
                spider.is_running = False
                raise PlaywrightLikeTimeoutError("timeout")

        # Playwright 的超时异常如果同时伴随 stop，应当作为中断返回 False，
        # 避免继续重试已经被用户取消的导航。
        result = spider.interruptible_playwright_goto(FakePage(), "https://example.com", timeout=60000, slice_ms=10)

        self.assertFalse(result)
        self.assertEqual(len(calls), 1)

    def test_interruptible_playwright_goto_uses_one_full_timeout_navigation(self):
        spider = _DummySpider(keyword="demo", config={})
        calls: list[int] = []

        class PlaywrightLikeTimeoutError(Exception):
            pass

        PlaywrightLikeTimeoutError.__name__ = "TimeoutError"

        class FakePage:
            url = "about:blank"

            def goto(self, url, *_args, **_kwargs):
                calls.append(_kwargs["timeout"])
                self.url = url
                raise PlaywrightLikeTimeoutError("slow load")

        result = spider.interruptible_playwright_goto(
            FakePage(),
            "https://example.com/slow",
            timeout=60000,
            slice_ms=15000,
        )

        self.assertTrue(result)
        self.assertEqual(calls, [60000])

    def test_interruptible_playwright_reload_uses_one_full_timeout_reload(self):
        spider = _DummySpider(keyword="demo", config={})
        calls: list[int] = []

        class PlaywrightLikeTimeoutError(Exception):
            pass

        PlaywrightLikeTimeoutError.__name__ = "TimeoutError"

        class FakePage:
            url = "https://example.com/current"

            def reload(self, *_args, **_kwargs):
                calls.append(_kwargs["timeout"])
                raise PlaywrightLikeTimeoutError("slow reload")

        result = spider.interruptible_playwright_reload(
            FakePage(),
            timeout=60000,
            wait_until="domcontentloaded",
        )

        self.assertTrue(result)
        self.assertEqual(calls, [60000])

    def test_guard_request_lazily_initializes_guardrails_for_minimal_test_doubles(self):
        spider = _DummySpider.__new__(_DummySpider)
        spider.config = {}
        spider.is_running = True

        spider.guard_request("douyin")

        self.assertEqual(spider.budget.snapshot()["total"], 1)

    def test_emit_video_is_local_dispatch_not_rate_limited(self):
        spider = _DummySpider(keyword="demo", config={})
        emitted = []
        guard_calls = []

        def guard_request(*args, **kwargs):
            guard_calls.append((args, kwargs))
            raise AssertionError("emit_video must not rate-limit local item dispatch")

        spider.guard_request = guard_request
        spider.sig_item_found.connect(emitted.append)

        spider.emit_video(
            url="https://cdn.example.com/one.jpg",
            title="one",
            source="xiaohongshu",
            meta={"trace_id": "xhs_emit_test", "content_type": "image"},
        )

        self.assertEqual(guard_calls, [])
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].source, "xiaohongshu")
        self.assertEqual(emitted[0].meta["content_type"], "image")

if __name__ == "__main__":
    unittest.main()
