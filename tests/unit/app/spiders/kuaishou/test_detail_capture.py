from __future__ import annotations

from unittest.mock import Mock

from app.spiders.kuaishou.spider import KuaishouSpider


def _spider() -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.is_running = True
    spider.config = {}
    spider.log = Mock()
    spider.debug_state = Mock()
    spider.new_trace_id = Mock(return_value="ks-share-1")
    spider.task_builder = Mock()
    spider.task_builder.build_download_meta.return_value = {"trace_id": "ks-share-1"}
    spider.emit_video = Mock()
    spider._extract_detail_title = Mock(return_value="shared work")
    spider._extract_detail_dom_media_url = Mock(return_value="")
    spider.interruptible_page_wait = Mock(return_value=True)
    spider.interruptible_playwright_reload = Mock(return_value=True)
    return spider


def _page() -> Mock:
    page = Mock()
    page.url = "https://www.kuaishou.com/short-video/3xj8abcde"
    page.locator.return_value.first = page.locator.return_value
    return page


def test_detail_capture_does_not_reload_when_media_is_unavailable() -> None:
    spider = _spider()
    page = _page()

    assert spider._capture_single_detail_page(page) is False

    spider.interruptible_playwright_reload.assert_not_called()


def test_detail_capture_returns_as_soon_as_response_event_has_media() -> None:
    spider = _spider()
    page = _page()
    handlers: dict[str, object] = {}
    page.on.side_effect = lambda event, handler: handlers.__setitem__(event, handler)
    response = Mock()
    response.url = "https://cdn.example.com/video.mp4"
    response.headers = {"content-type": "video/mp4"}
    response.request.resource_type = "media"

    def pump_events(_page, wait_ms, **_kwargs):
        assert wait_ms <= 250
        handlers["response"](response)
        return True

    spider.interruptible_page_wait.side_effect = pump_events

    assert spider._capture_single_detail_page(page) is True

    spider.emit_video.assert_called_once()
    spider.interruptible_playwright_reload.assert_not_called()
