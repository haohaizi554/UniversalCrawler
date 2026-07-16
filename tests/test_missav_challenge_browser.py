from __future__ import annotations

from unittest.mock import Mock, call

from playwright.sync_api import Error as PlaywrightError

from app.spiders.missav.spider import MissAVSpider


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
