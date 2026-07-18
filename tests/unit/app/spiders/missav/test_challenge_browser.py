from __future__ import annotations

from unittest.mock import Mock, call, patch

from playwright.sync_api import Error as PlaywrightError

from app.spiders.missav.challenge_session import BrowserAttachment
from app.spiders.missav.spider import MissAVSpider, _ChallengeBrowserRuntime


def _spider() -> MissAVSpider:
    spider = MissAVSpider.__new__(MissAVSpider)
    spider.config = {}
    spider.log = Mock()
    spider.is_running = True
    return spider


def test_headed_missav_prefers_system_chrome_channel() -> None:
    spider = _spider()
    spider._playwright_launch_kwargs = Mock(
        return_value={"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}
    )
    playwright = Mock()
    browser = Mock(version="150.0.7871.124")
    playwright.chromium.launch.return_value = browser

    result = spider._launch_challenge_browser(playwright, headless=False)

    assert result is browser
    playwright.chromium.launch.assert_called_once_with(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        channel="chrome",
    )


def test_headed_missav_falls_back_from_system_channels_to_bundled_browser() -> None:
    spider = _spider()
    launch_kwargs = {"headless": False, "args": []}
    spider._playwright_launch_kwargs = Mock(return_value=launch_kwargs)
    playwright = Mock()
    bundled = Mock(version="143.0.7499.4")
    playwright.chromium.launch.side_effect = [
        PlaywrightError("chrome unavailable"),
        PlaywrightError("edge unavailable"),
        bundled,
    ]

    result = spider._launch_challenge_browser(playwright, headless=False)

    assert result is bundled
    assert playwright.chromium.launch.call_args_list == [
        call(**launch_kwargs, channel="chrome"),
        call(**launch_kwargs, channel="msedge"),
        call(**launch_kwargs),
    ]


def test_missav_context_preserves_native_user_agent_and_web_apis() -> None:
    spider = _spider()
    spider._playwright_context_kwargs = Mock(
        return_value={
            "user_agent": "Mozilla/5.0 Chrome/135.0.0.0",
            "locale": "zh-CN",
            "service_workers": "block",
        }
    )
    spider._apply_stealth_to_context = Mock()
    browser = Mock()
    context = Mock()
    browser.new_context.return_value = context

    result = spider._create_challenge_context(browser)

    assert result is context
    browser.new_context.assert_called_once_with(locale="zh-CN", service_workers="block")
    spider._apply_stealth_to_context.assert_not_called()


def test_missav_detects_chinese_cloudflare_unsupported_page() -> None:
    spider = _spider()
    page = Mock()
    page.title.return_value = "请稍候..."
    page.locator.return_value.inner_text.return_value = (
        "正在进行安全验证\n浏览器不支持\n您的浏览器不支持所需的安全验证"
    )

    assert spider._cloudflare_challenge_state(page) == "unsupported"


def test_missav_waits_until_cloudflare_challenge_clears() -> None:
    spider = _spider()
    spider._cloudflare_challenge_state = Mock(side_effect=["pending", "pending", "clear"])
    spider.interruptible_sleep = Mock(return_value=True)

    assert spider._wait_for_cloudflare_challenge(Mock(), timeout_ms=5000) is True
    assert spider.interruptible_sleep.call_count == 2


def test_missav_stops_when_cloudflare_rejects_browser() -> None:
    spider = _spider()
    spider._cloudflare_challenge_state = Mock(return_value="unsupported")
    spider.interruptible_sleep = Mock(return_value=True)

    assert spider._wait_for_cloudflare_challenge(Mock(), timeout_ms=5000) is False
    spider.interruptible_sleep.assert_not_called()
    assert "不支持" in spider.log.call_args.args[0]


def test_headed_runtime_waits_for_challenge_before_starting_playwright() -> None:
    spider = _spider()
    spider._browser_headless = Mock(return_value=False)
    spider._configured_timeout_ms = Mock(return_value=60_000)
    events: list[str] = []

    session = Mock()
    session.start.side_effect = lambda _url: events.append("start")
    session.wait_for_ready_page.side_effect = lambda *_args, **_kwargs: (
        events.append("ready")
    )
    browser = Mock()
    context = Mock()
    page = Mock()
    session.attach.side_effect = lambda *_args, **_kwargs: (
        events.append("attach")
        or BrowserAttachment(browser=browser, context=context, page=page)
    )
    playwright = Mock()
    playwright_manager = Mock()
    playwright_manager.start.side_effect = lambda: (
        events.append("playwright") or playwright
    )

    with (
        patch(
            "app.spiders.missav.spider.ExternalChromeChallengeSession",
            return_value=session,
        ),
        patch(
            "app.spiders.missav.spider.sync_playwright",
            return_value=playwright_manager,
        ),
    ):
        with spider._challenge_browser_runtime(
            "https://missav.ai/cn/search/CAWD-377",
            None,
        ) as runtime:
            assert runtime.page is page

    assert events[:4] == ["start", "ready", "playwright", "attach"]


def test_external_second_navigation_disconnects_before_opening_url() -> None:
    spider = _spider()
    events: list[str] = []
    session = Mock()
    session.open_url.side_effect = lambda _url: events.append("open")
    runtime = _ChallengeBrowserRuntime(
        playwright=Mock(),
        browser=Mock(),
        context=Mock(),
        page=Mock(),
        external_session=session,
    )
    spider._disconnect_external_browser = Mock(
        side_effect=lambda _runtime: events.append("disconnect")
    )
    spider._wait_for_external_challenge = Mock(
        side_effect=lambda *_args, **_kwargs: events.append("ready") or True
    )
    spider._attach_external_browser = Mock(
        side_effect=lambda *_args, **_kwargs: events.append("attach") or True
    )

    assert (
        spider._navigate_external_challenge(
            runtime,
            "https://missav.ai/cn/search/CAWD-377?filters=chinese-subtitle",
            timeout_ms=60_000,
        )
        is True
    )
    assert events == ["disconnect", "open", "ready", "attach"]


def test_disconnect_external_browser_does_not_close_chrome() -> None:
    spider = _spider()
    playwright = Mock()
    browser = Mock()
    runtime = _ChallengeBrowserRuntime(
        playwright=playwright,
        browser=browser,
        context=Mock(),
        page=Mock(),
        external_session=Mock(),
    )
    spider._clear_playwright_browser = Mock()
    spider._stop_tracked_playwright_instance = Mock()

    spider._disconnect_external_browser(runtime)

    browser.close.assert_not_called()
    spider._clear_playwright_browser.assert_called_once_with(browser)
    spider._stop_tracked_playwright_instance.assert_called_once_with(playwright)
    assert runtime.playwright is None
    assert runtime.browser is None
    assert runtime.context is None
    assert runtime.page is None


def test_player_warning_is_not_mistaken_for_cloudflare_rejection() -> None:
    spider = _spider()
    page = Mock()
    page.title.return_value = "CAWD-377 | MissAV"
    page.locator.return_value.inner_text.return_value = (
        "Video player error: browser not supported"
    )

    assert spider._cloudflare_challenge_state(page) == "clear"
