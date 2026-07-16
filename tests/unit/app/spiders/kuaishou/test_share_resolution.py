from __future__ import annotations

import threading
import time
from unittest.mock import Mock, patch

import pytest
from curl_cffi.requests import RequestsError as CurlRequestsError

from app.spiders.kuaishou.spider import KuaishouSpider


def _spider() -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.config = {"timeout": 60}
    spider.user_agent = "test-agent"
    spider.log = Mock()
    spider._effective_proxy_server = Mock(return_value=None)
    spider._restricted_public_request_kwargs = Mock(return_value={})
    return spider


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_final_response_is_reused_for_detail_parsing(request_get: Mock) -> None:
    spider = _spider()
    final_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    response = Mock()
    response.url = final_url
    response.text = (
        '<script>window.__APOLLO_STATE__='
        '{"defaultClient":{"VisionVideoDetailPhoto:3xj8abcde":'
        '{"caption":"分享作品","photoUrl":"https://cdn.example.com/video.mp4"}}};'
        "</script>"
    )
    response.iter_content.return_value = [response.text.encode("utf-8")]
    response.encoding = "utf-8"
    response.status_code = 200
    response.headers = {}

    def perform_request(_url, **kwargs):
        assert kwargs["content_callback"](response.text.encode("utf-8")) > 0
        return response

    request_get.side_effect = perform_request

    normalized = spider._normalize_keyword("https://www.kuaishou.com/f/example")
    title, media_url = spider._fetch_share_detail_via_http(normalized)

    assert normalized == final_url
    assert (title, media_url) == ("分享作品", "https://cdn.example.com/video.mp4")
    assert request_get.call_count == 1
    assert callable(request_get.call_args.kwargs["content_callback"])
    assert request_get.call_args.kwargs["headers"] == {
        "User-Agent": "test-agent",
        "Referer": "https://www.kuaishou.com/",
    }
    response.close.assert_called_once()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_resolution_uses_bounded_network_timeout(request_get: Mock) -> None:
    spider = _spider()
    response = Mock()
    response.url = "https://www.kuaishou.com/profile/example"
    response.status_code = 200
    response.headers = {}
    request_get.return_value = response

    spider._resolve_short_share_url("https://www.kuaishou.com/f/example")

    connect_timeout, read_timeout = request_get.call_args.kwargs["timeout"]
    assert 0 < connect_timeout <= 5.0
    assert 0 < read_timeout <= 12.0
    assert connect_timeout + read_timeout <= spider.SHORT_LINK_TOTAL_TIMEOUT_SECONDS
    assert request_get.call_args.kwargs["allow_redirects"] is False
    response.close.assert_called_once()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_recomputes_transport_budget_after_policy_validation(
    request_get: Mock,
) -> None:
    spider = _spider()
    spider._restricted_short_link_request_kwargs = Mock(return_value={})
    response = Mock()
    response.url = "https://www.kuaishou.com/profile/example"
    response.status_code = 200
    response.headers = {}
    request_get.return_value = response

    with patch(
        "app.spiders.kuaishou.share_runtime.time.monotonic",
        side_effect=[0.0, 0.0, 12.0],
    ):
        spider._resolve_short_share_url("https://www.kuaishou.com/f/example")

    connect_timeout, read_timeout = request_get.call_args.kwargs["timeout"]
    assert connect_timeout + read_timeout <= 3.0


def test_share_detail_http_stops_reading_oversized_html() -> None:
    spider = _spider()
    detail_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    response = Mock()
    response.url = detail_url
    response.encoding = "utf-8"
    response.iter_content.return_value = [
        b"x" * (spider.SHARE_DETAIL_HTML_MAX_BYTES + 1)
    ]
    spider._pending_share_response = (detail_url, response)

    assert spider._fetch_share_detail_via_http(detail_url) == ("", "")

    response.iter_content.assert_called_once()
    response.close.assert_called_once()


def test_failed_short_link_http_resolution_still_uses_share_browser_flow() -> None:
    spider = _spider()
    short_url = "https://www.kuaishou.com/f/example"
    spider.keyword = short_url
    spider.is_running = True
    spider._normalize_keyword = Mock(return_value=short_url)
    spider._try_direct_share_download = Mock(return_value=False)
    spider._run_share_browser_session = Mock(return_value="completed")
    spider._run_browser_session = Mock(return_value="completed")
    spider._emit_finished = Mock()
    playwright = Mock()

    with patch("app.spiders.kuaishou.spider.sync_playwright") as sync:
        sync.return_value.__enter__.return_value = playwright
        spider.run()

    spider._run_share_browser_session.assert_called_once()
    spider._run_browser_session.assert_not_called()


def test_cached_short_link_http_error_falls_back_to_share_browser() -> None:
    spider = _spider()
    detail_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    response = Mock()
    response.url = detail_url
    response.raise_for_status.side_effect = CurlRequestsError("HTTP 403")
    spider.keyword = detail_url
    spider.is_running = True
    spider._pending_share_response = (detail_url, response, None)
    spider._normalize_keyword = Mock(return_value=detail_url)
    spider._run_share_browser_session = Mock(return_value="completed")
    spider._emit_finished = Mock()
    playwright = Mock()

    with patch("app.spiders.kuaishou.spider.sync_playwright") as sync:
        sync.return_value.__enter__.return_value = playwright
        spider.run()

    spider._run_share_browser_session.assert_called_once()
    browser_args = spider._run_share_browser_session.call_args.args
    assert browser_args[0] is playwright
    assert str(browser_args[1]).replace("\\", "/").endswith("/ks_auth.json")
    response.close.assert_called_once()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_network_failure_preserves_share_classification(
    request_get: Mock,
) -> None:
    spider = _spider()
    short_url = "https://v.kuaishou.com/example"
    request_get.side_effect = CurlRequestsError("offline")

    assert spider._resolve_short_share_url(short_url) == short_url
    assert spider._is_short_share_url(short_url)


def test_short_link_policy_validation_obeys_total_deadline() -> None:
    spider = _spider()
    blocker = threading.Event()
    spider._restricted_public_request_kwargs.side_effect = (
        lambda *_args, **_kwargs: blocker.wait(0.5)
    )
    started = time.perf_counter()

    with pytest.raises(CurlRequestsError, match="validation timeout"):
        spider._restricted_short_link_request_kwargs(
            "https://v.kuaishou.com/example",
            deadline=time.monotonic() + 0.02,
        )

    assert time.perf_counter() - started < 0.25


def test_short_link_policy_validation_bounds_hung_workers() -> None:
    spider = _spider()
    blocker = threading.Event()
    entered = threading.Event()

    def block_validation(*_args, **_kwargs):
        entered.set()
        blocker.wait(0.5)
        return {}

    spider._restricted_public_request_kwargs.side_effect = block_validation
    gate = threading.BoundedSemaphore(1)
    try:
        with patch(
            "app.spiders.kuaishou.share_runtime._SHORT_LINK_POLICY_SLOTS",
            gate,
        ):
            with pytest.raises(CurlRequestsError, match="validation timeout"):
                spider._restricted_short_link_request_kwargs(
                    "https://v.kuaishou.com/first",
                    deadline=time.monotonic() + 0.02,
                )
            assert entered.is_set()
            with pytest.raises(CurlRequestsError, match="validation timeout"):
                spider._restricted_short_link_request_kwargs(
                    "https://v.kuaishou.com/second",
                    deadline=time.monotonic() + 0.02,
                )
    finally:
        blocker.set()

    assert spider._restricted_public_request_kwargs.call_count == 1


def test_bounded_html_reader_stops_at_total_deadline() -> None:
    spider = _spider()
    response = Mock()
    response.encoding = "utf-8"
    response.iter_content.return_value = [b"first", b"second"]

    with patch(
        "app.spiders.kuaishou.share_runtime.time.monotonic",
        return_value=16.0,
        create=True,
    ):
        assert spider._read_bounded_response_text(
            response,
            deadline=15.0,
        ) == ""


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_aborts_body_after_total_deadline(
    request_get: Mock,
) -> None:
    spider = _spider()
    short_url = "https://www.kuaishou.com/f/example"

    def slow_response(_url, **kwargs):
        assert kwargs["content_callback"](b"late") == 0
        raise CurlRequestsError("write aborted")

    request_get.side_effect = slow_response
    with patch(
        "app.spiders.kuaishou.share_runtime.time.monotonic",
        side_effect=[0.0, 0.0, 16.0],
    ):
        assert spider._resolve_short_share_url(short_url) == short_url
