from __future__ import annotations

from unittest.mock import Mock

from app.spiders.kuaishou.spider import KuaishouSpider


def _spider(keyword: str) -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.keyword = keyword
    spider.config = {"timeout": 60}
    spider.log = Mock()
    spider.is_running = True
    spider._goto_with_retry = Mock(return_value=True)
    return spider


def test_target_navigation_reuses_equivalent_current_page() -> None:
    target = "https://www.kuaishou.com/profile/demo?source=SEARCH&tab=video"
    spider = _spider(target)
    page = Mock()
    page.url = "https://www.kuaishou.com/profile/demo?tab=video&source=SEARCH"

    result = spider._navigate_to_target_page(page, Mock())

    assert result is page
    spider._goto_with_retry.assert_not_called()


def test_keyword_search_uses_direct_video_results_route() -> None:
    spider = _spider("测试主播")
    page = Mock()
    page.url = "https://www.kuaishou.com/"

    result = spider._search_keyword_via_site(page, spider.keyword)

    assert result is page
    spider._goto_with_retry.assert_called_once_with(
        page,
        "https://www.kuaishou.com/search/video?searchKey=%E6%B5%8B%E8%AF%95%E4%B8%BB%E6%92%AD",
        description="打开快手搜索页",
    )
    page.locator.assert_not_called()


def test_keyword_search_reuses_result_page_loaded_during_login() -> None:
    spider = _spider("测试 主播&1")
    page = Mock()
    page.url = (
        "https://www.kuaishou.com/search/video?"
        "searchKey=%E6%B5%8B%E8%AF%95+%E4%B8%BB%E6%92%AD%261"
    )

    result = spider._search_keyword_via_site(page, spider.keyword)

    assert result is page
    spider._goto_with_retry.assert_not_called()


def test_plain_keyword_preloads_search_results_for_login_check() -> None:
    spider = _spider("测试 主播&1")

    assert spider._entry_url_for_login() == (
        "https://www.kuaishou.com/search/video?"
        "searchKey=%E6%B5%8B%E8%AF%95+%E4%B8%BB%E6%92%AD%261"
    )


def test_keyword_result_navigation_waits_for_commit_with_bounded_timeout() -> None:
    spider = _spider("测试主播")
    spider.__dict__.pop("_goto_with_retry", None)
    spider.config["timeout"] = 90
    spider.interruptible_playwright_goto = Mock(return_value=True)
    spider.interruptible_page_wait = Mock(return_value=True)
    page = Mock()
    target = spider._keyword_search_url(spider.keyword)

    assert spider._goto_with_retry(page, target, description="关键词结果页") is True

    spider.interruptible_playwright_goto.assert_called_once_with(
        page,
        target,
        timeout=spider.SEARCH_NAVIGATION_TIMEOUT_MS,
        wait_until="commit",
    )


def test_visible_session_preflights_target_before_browser_launch() -> None:
    target = "https://www.kuaishou.com/profile/demo"
    spider = _spider(target)
    spider._playwright_launch_kwargs = Mock(return_value={"headless": False})
    spider._entry_url_for_login = Mock(return_value=target)
    spider._ensure_login = Mock(return_value=False)
    spider._track_playwright_browser = Mock()
    spider._close_tracked_playwright_browser = Mock()
    policy = Mock()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    playwright = Mock()
    browser = Mock()
    events: list[str] = []
    policy.require_public_url.side_effect = lambda _url: events.append("preflight")
    playwright.chromium.launch.side_effect = lambda **_kwargs: (
        events.append("launch") or browser
    )
    spider._create_browser_context = Mock()

    spider._run_browser_session(
        playwright,
        "ks_auth.json",
        headless=False,
        allow_manual_login=True,
    )

    assert events[:2] == ["preflight", "launch"]
    policy.require_public_url.assert_called_once_with(target)


def test_manual_login_success_does_not_force_navigation_to_homepage() -> None:
    spider = _spider("demo")
    spider._goto_with_retry = Mock(return_value=False)
    spider._navigation_error_reason = Mock(return_value=None)
    spider._user_cookie_values = Mock(return_value=set())
    spider._open_login_entry = Mock()
    spider._wait_for_manual_login = Mock(return_value=True)
    spider.interruptible_playwright_goto = Mock(return_value=True)
    page = Mock()

    assert spider._ensure_login(page, Mock(), "missing-auth.json") is True

    spider.interruptible_playwright_goto.assert_not_called()


def test_profile_search_does_not_recurse_into_blank_popup() -> None:
    spider = _spider("demo")
    spider._switch_search_to_user_tab = Mock()
    spider._has_video_list = Mock(return_value=False)
    spider.interruptible_page_wait = Mock(return_value=True)
    page = Mock()
    page.url = "https://www.kuaishou.com/search/author?searchKey=demo"
    page.is_closed.return_value = False
    blank_popup = Mock()
    blank_popup.url = "about:blank"
    blank_popup.is_closed.return_value = False
    context = Mock()
    context.pages = [page]

    hidden = Mock()
    hidden.first = hidden
    hidden.is_visible.return_value = False
    user_link = Mock()
    user_link.first = user_link
    user_link.is_visible.return_value = True
    user_link.inner_text.return_value = "demo"
    user_link.click.side_effect = lambda: context.pages.append(blank_popup)

    def locator(selector: str):
        if selector in {
            ".card-item .detail-user-name",
            "a[href*='/profile/']",
            "[class*='user-name']",
            "[class*='author'] a",
        }:
            return user_link
        return hidden

    page.locator.side_effect = locator
    spider._locator_visible = lambda item: item.is_visible()

    assert spider._open_profile_from_search_results(page, context, "demo") is None

    user_link.click.assert_called_once()
    spider._has_video_list.assert_not_called()
    blank_popup.bring_to_front.assert_not_called()
