from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import time
from unittest.mock import Mock, call, patch

import pytest
from curl_cffi.const import CurlOpt
from curl_cffi.requests import RequestsError as CurlRequestsError
from curl_cffi.requests import get as real_curl_get

from app.services.auth_service import AuthService
from app.spiders.kuaishou.spider import KuaishouSpider
from shared.runtime_options import DomainPolicyEngine


def _public_policy(*addresses: str) -> DomainPolicyEngine:
    resolved = addresses or ("93.184.216.34",)
    return DomainPolicyEngine(
        resolver=lambda *_args, **_kwargs: [
            (None, None, None, None, (address, 443))
            for address in resolved
        ]
    )


def _spider() -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.config = {"timeout": 60}
    spider.user_agent = "test-agent"
    spider.log = Mock()
    spider._effective_proxy_server = Mock(return_value=None)
    spider._public_domain_policy = _public_policy()
    spider._load_saved_storage_state = Mock(return_value=None)
    return spider


def _with_saved_share_cookies(
    spider: KuaishouSpider,
    tmp_path,
    cookies: list[dict[str, object]],
) -> dict[str, list[dict]]:
    auth_file = tmp_path / "ks_auth.json"
    AuthService().save_json_file(
        str(auth_file),
        {"cookies": cookies, "origins": []},
    )
    spider.auth_service = AuthService()
    storage_state = spider.auth_service.load_playwright_storage_state(
        str(auth_file)
    )
    assert storage_state is not None
    return storage_state


@contextmanager
def _running_http_server(handler: type[BaseHTTPRequestHandler]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_pins_validated_public_addresses(
    request_get: Mock,
) -> None:
    spider = _spider()
    spider._public_domain_policy = _public_policy(
        "2001:4860:4860::8888",
        "93.184.216.34",
    )
    url = "https://www.kuaishou.com:8443/f/example"
    response = Mock(
        url="https://www.kuaishou.com:8443/profile/example",
        status_code=200,
        headers={},
    )
    request_get.return_value = response

    spider._resolve_short_share_url(url)

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "www.kuaishou.com:8443:[2001:4860:4860::8888],93.184.216.34"
    ]
    assert request_get.call_args.kwargs["curl_options"][CurlOpt.PROXY] == ""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.kuaishou.com/f/example",
            "www.kuaishou.com:443:93.184.216.34",
        ),
        (
            "http://www.kuaishou.com/f/example",
            "www.kuaishou.com:80:93.184.216.34",
        ),
    ],
)
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_uses_scheme_default_port(
    request_get: Mock,
    url: str,
    expected: str,
) -> None:
    spider = _spider()
    response = Mock(
        url=url.replace("/f/", "/profile/"),
        status_code=200,
        headers={},
    )
    request_get.return_value = response

    spider._resolve_short_share_url(url)

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [expected]
    assert request_get.call_args.kwargs["curl_options"][CurlOpt.PROXY] == ""


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_preserves_idna_and_trailing_dot_host(
    request_get: Mock,
) -> None:
    spider = _spider()
    url = "https://\u5feb\u624b.kuaishou.com./f/example"
    transport_url = "https://xn--66tu6c.kuaishou.com./f/example"
    policy = Mock(spec=DomainPolicyEngine)
    policy.REDIRECT_STATUS_CODES = DomainPolicyEngine.REDIRECT_STATUS_CODES
    policy.resolve_public_addresses.return_value = ("93.184.216.34",)
    spider._public_domain_policy_engine = Mock(return_value=policy)
    response = Mock(
        url="https://\u5feb\u624b.kuaishou.com./profile/example",
        status_code=200,
        headers={},
    )
    request_get.return_value = response

    spider._resolve_short_share_url(url)

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "xn--66tu6c.kuaishou.com.:443:93.184.216.34"
    ]
    assert request_get.call_args.kwargs["curl_options"][CurlOpt.PROXY] == ""
    assert request_get.call_args.args == (transport_url,)
    policy.resolve_public_addresses.assert_called_once_with(transport_url)


def test_real_curl_uses_ascii_trailing_dot_pin_and_ignores_environment_proxy(
) -> None:
    target_reached = threading.Event()
    proxy_reached = threading.Event()
    observed_cookie_headers: list[str] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            target_reached.set()
            observed_cookie_headers.append(self.headers.get("Cookie", ""))
            payload = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            return

    class ProxyTrapHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            proxy_reached.set()
            payload = b"proxy trap"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            return

    observed_urls: list[str] = []
    observed_options: list[dict[object, object]] = []

    def perform_real_request(url: str, **kwargs: object):
        observed_urls.append(url)
        curl_options = dict(kwargs["curl_options"])
        observed_options.append(dict(curl_options))
        curl_options[CurlOpt.RESOLVE] = [
            f"{entry.rsplit(':', 1)[0]}:127.0.0.1"
            for entry in curl_options[CurlOpt.RESOLVE]
        ]
        return real_curl_get(
            url,
            **{**kwargs, "curl_options": curl_options},
        )

    with (
        _running_http_server(TargetHandler) as target_server,
        _running_http_server(ProxyTrapHandler) as proxy_server,
    ):
        target_port = int(target_server.server_address[1])
        proxy_port = int(proxy_server.server_address[1])
        candidate = (
            f"http://\u5feb\u624b.kuaishou.com.:{target_port}"
            "/f/example?label=%E5%BF%AB%E6%89%8B#section"
        )
        transport_url = (
            f"http://xn--66tu6c.kuaishou.com.:{target_port}"
            "/f/example?label=%E5%BF%AB%E6%89%8B#section"
        )
        spider = _spider()
        spider.auth_service = AuthService()
        storage_state = {
            "cookies": [
                {
                    "name": "ks_session",
                    "value": "saved-login",
                    "domain": ".kuaishou.com",
                    "path": "/f",
                },
                {
                    "name": "secure_only",
                    "value": "must-not-send-over-http",
                    "domain": ".kuaishou.com",
                    "path": "/f",
                    "secure": True,
                },
            ],
            "origins": [],
        }
        environment = {
            "ALL_PROXY": f"http://127.0.0.1:{proxy_port}",
            "HTTP_PROXY": f"http://127.0.0.1:{proxy_port}",
            "http_proxy": f"http://127.0.0.1:{proxy_port}",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "app.spiders.kuaishou.share_runtime.curl_get",
                side_effect=perform_real_request,
            ),
        ):
            spider._resolve_short_share_url(
                candidate,
                storage_state=storage_state,
            )

    assert observed_urls == [transport_url]
    assert observed_options[0][CurlOpt.PROXY] == ""
    assert target_reached.is_set()
    assert not proxy_reached.is_set()
    assert observed_cookie_headers == ["ks_session=saved-login"]


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_when_no_address_is_resolved(
    request_get: Mock,
) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.return_value = ()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    url = "https://www.kuaishou.com/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "93.184.216.34,127.0.0.1",
        "2001:4860:4860::8888%1],[::1",
    ],
)
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_for_invalid_pinned_address(
    request_get: Mock,
    address: str,
) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.return_value = (address,)
    spider._public_domain_policy_engine = Mock(return_value=policy)
    url = "https://www.kuaishou.com/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_for_zero_port(request_get: Mock) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.return_value = ("93.184.216.34",)
    spider._public_domain_policy_engine = Mock(return_value=policy)
    url = "https://www.kuaishou.com:0/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_redirect_revalidates_and_repins_each_hop(
    request_get: Mock,
) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.REDIRECT_STATUS_CODES = DomainPolicyEngine.REDIRECT_STATUS_CODES
    policy.resolve_public_addresses.side_effect = [
        ("93.184.216.34",),
        ("2001:4860:4860::8888",),
    ]
    spider._public_domain_policy_engine = Mock(return_value=policy)
    first_url = "https://\u5feb\u624b.kuaishou.com./f/example"
    final_url = "https://\u5feb\u624b.chenzhongtech.com.:8443/short-video/3xj8abcde"
    first_transport_url = "https://xn--66tu6c.kuaishou.com./f/example"
    final_transport_url = (
        "https://xn--66tu6c.chenzhongtech.com.:8443/short-video/3xj8abcde"
    )
    first = Mock(url=first_url, status_code=302, headers={"Location": final_url})
    final = Mock(url=final_url, status_code=200, headers={}, encoding="utf-8")
    request_get.side_effect = [first, final]

    assert spider._resolve_short_share_url(first_url) == final_url
    assert [item.args[0] for item in request_get.call_args_list] == [
        first_transport_url,
        final_transport_url,
    ]
    assert request_get.call_args_list[0].kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "xn--66tu6c.kuaishou.com.:443:93.184.216.34"
    ]
    assert request_get.call_args_list[1].kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "xn--66tu6c.chenzhongtech.com.:8443:[2001:4860:4860::8888]"
    ]
    assert [
        item.kwargs["curl_options"][CurlOpt.PROXY]
        for item in request_get.call_args_list
    ] == ["", ""]
    assert policy.resolve_public_addresses.call_args_list == [
        call(first_transport_url),
        call(final_transport_url),
    ]
    first.close.assert_called_once()
    spider._close_pending_share_response()
    final.close.assert_called_once()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_rejects_sixth_redirect_and_closes_every_response(
    request_get: Mock,
) -> None:
    spider = _spider()
    start_url = "https://www.kuaishou.com/f/example"
    responses = [
        Mock(
            url=f"https://www.kuaishou.com/f/hop-{index}",
            status_code=302,
            headers={
                "Location": f"https://www.kuaishou.com/f/hop-{index + 1}"
            },
        )
        for index in range(spider.SHORT_LINK_MAX_REDIRECTS + 1)
    ]
    request_get.side_effect = responses

    assert spider._resolve_short_share_url(start_url) == start_url

    assert request_get.call_count == spider.SHORT_LINK_MAX_REDIRECTS + 1
    for response in responses:
        response.close.assert_called_once()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_redirect_recomputes_saved_cookies_for_each_hop(
    request_get: Mock,
    tmp_path,
) -> None:
    spider = _spider()
    storage_state = _with_saved_share_cookies(
        spider,
        tmp_path,
        [
            {
                "name": "ks_root",
                "value": "ks-root",
                "domain": ".kuaishou.com",
                "path": "/",
                "secure": True,
            },
            {
                "name": "ks_share",
                "value": "ks-share",
                "domain": "www.kuaishou.com",
                "path": "/f",
                "secure": True,
            },
            {
                "name": "ks_detail",
                "value": "ks-detail",
                "domain": ".kuaishou.com",
                "path": "/short-video",
                "secure": True,
            },
            {
                "name": "ct_root",
                "value": "ct-root",
                "domain": ".chenzhongtech.com",
                "path": "/",
                "secure": True,
            },
            {
                "name": "hostless",
                "value": "must-not-leak",
                "path": "/",
            },
            {
                "name": "expired",
                "value": "must-not-send",
                "domain": ".kuaishou.com",
                "path": "/",
                "expires": time.time() - 60,
            },
            {
                "name": "invalid_expiry",
                "value": "must-not-send",
                "domain": ".kuaishou.com",
                "path": "/",
                "expires": "not-a-number",
            },
            {
                "name": "overflow_expiry",
                "value": "must-not-send",
                "domain": ".kuaishou.com",
                "path": "/",
                "expires": 10**500,
            },
            {
                "name": "missing_path",
                "value": "must-not-send",
                "domain": ".kuaishou.com",
            },
            {
                "name": "unsafe",
                "value": "bad\r\nX-Injected: yes",
                "domain": ".kuaishou.com",
                "path": "/",
            },
        ],
    )
    first_url = "https://www.kuaishou.com/f/example"
    final_url = "https://www.chenzhongtech.com/short-video/3xj8abcde"
    first = Mock(url=first_url, status_code=302, headers={"Location": final_url})
    final = Mock(url=final_url, status_code=200, headers={}, encoding="utf-8")
    request_get.side_effect = [first, final]

    assert (
        spider._resolve_short_share_url(
            first_url,
            storage_state=storage_state,
        )
        == final_url
    )

    assert request_get.call_args_list[0].kwargs["cookies"] == {
        "ks_root": "ks-root",
        "ks_share": "ks-share",
    }
    assert request_get.call_args_list[1].kwargs["cookies"] == {
        "ct_root": "ct-root"
    }
    logged = " ".join(str(item) for item in spider.log.call_args_list)
    assert "ks-root" not in logged
    assert "ks-share" not in logged
    assert "ct-root" not in logged
    spider._close_pending_share_response()


@pytest.mark.parametrize(
    "proxy",
    ["http://127.0.0.1:7890", "socks5h://127.0.0.1:7890"],
)
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_when_proxy_controls_dns(
    request_get: Mock,
    proxy: str,
) -> None:
    spider = _spider()
    spider._effective_proxy_server.return_value = proxy
    url = "https://www.kuaishou.com/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


def test_short_link_http_success_reuses_detail_without_browser_fallback(
    tmp_path,
) -> None:
    spider = _spider()
    storage_state = _with_saved_share_cookies(
        spider,
        tmp_path,
        [
            {
                "name": "ks_session",
                "value": "saved-login",
                "domain": ".kuaishou.com",
                "path": "/",
                "secure": True,
            }
        ],
    )
    spider._load_saved_storage_state = Mock(return_value=storage_state)
    persistence_baseline = {"cookies": [{"name": "original"}]}
    spider._loaded_storage_state = persistence_baseline
    spider.keyword = "https://www.kuaishou.com/f/example"
    spider.task_builder = Mock()
    spider.task_builder.build_download_meta.return_value = {"trace_id": "share-test"}
    spider.new_trace_id = Mock(return_value="share-test")
    spider.debug_state = Mock()
    spider.emit_video = Mock()
    spider._emit_finished = Mock()
    final_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    html = (
        '<script>window.__APOLLO_STATE__='
        '{"defaultClient":{"VisionVideoDetailPhoto:3xj8abcde":'
        '{"caption":"\u5206\u4eab\u4f5c\u54c1",'
        '"photoUrl":"https://cdn.example.com/video.mp4"}}};'
        "</script>"
    )
    response = Mock(url=final_url, status_code=200, headers={}, encoding="utf-8")

    def perform_request(_url, **kwargs):
        payload = html.encode("utf-8")
        assert kwargs["content_callback"](payload) == len(payload)
        return response

    with (
        patch(
            "app.spiders.kuaishou.share_runtime.curl_get",
            side_effect=perform_request,
        ) as request_get,
        patch("app.spiders.kuaishou.spider.sync_playwright") as sync_playwright,
    ):
        spider.run()

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "www.kuaishou.com:443:93.184.216.34"
    ]
    assert request_get.call_args.kwargs["curl_options"][CurlOpt.PROXY] == ""
    assert request_get.call_args.kwargs["cookies"] == {
        "ks_session": "saved-login"
    }
    spider._load_saved_storage_state.assert_called_once()
    assert spider._loaded_storage_state is persistence_baseline
    sync_playwright.assert_not_called()
    spider.emit_video.assert_called_once()
    response.close.assert_called_once()


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
    url = "https://www.kuaishou.com/f/example"
    spider._restricted_short_link_request_kwargs = Mock(return_value=(url, {}))
    response = Mock()
    response.url = "https://www.kuaishou.com/profile/example"
    response.status_code = 200
    response.headers = {}
    request_get.return_value = response

    with patch(
        "app.spiders.kuaishou.share_runtime.time.monotonic",
        side_effect=[0.0, 0.0, 12.0],
    ):
        spider._resolve_short_share_url(url)

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


def test_missing_saved_state_keeps_http_anonymous_and_uses_browser_fallback(
) -> None:
    spider = _spider()
    short_url = "https://www.kuaishou.com/f/example"
    final_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    spider.keyword = short_url
    spider.is_running = True
    spider._run_share_browser_session = Mock(return_value="completed")
    spider._run_browser_session = Mock(return_value="completed")
    spider._emit_finished = Mock()
    response = Mock(
        url=final_url,
        status_code=200,
        headers={},
        encoding="utf-8",
    )

    def perform_request(_url, **kwargs):
        assert kwargs["cookies"] is None
        payload = (
            '<script>window.__APOLLO_STATE__={"defaultClient":{}};'
            "</script>"
        ).encode()
        assert kwargs["content_callback"](payload) == len(payload)
        return response

    with (
        patch(
            "app.spiders.kuaishou.share_runtime.curl_get",
            side_effect=perform_request,
        ),
        patch("app.spiders.kuaishou.spider.sync_playwright") as sync,
    ):
        sync.return_value.__enter__.return_value = Mock()
        spider.run()

    spider._load_saved_storage_state.assert_called_once()
    spider._run_share_browser_session.assert_called_once()
    spider._run_browser_session.assert_not_called()
    response.close.assert_called_once()


def test_corrupt_saved_state_keeps_http_anonymous_and_uses_browser_fallback(
    tmp_path,
) -> None:
    spider = _spider()
    del spider._load_saved_storage_state
    spider.auth_service = AuthService()
    short_url = "https://www.kuaishou.com/f/example"
    final_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    spider.keyword = short_url
    spider.is_running = True
    spider._run_share_browser_session = Mock(return_value="completed")
    spider._run_browser_session = Mock(return_value="completed")
    spider._emit_finished = Mock()
    auth_file = tmp_path / "ks_auth.json"
    auth_file.write_text("{not-json", encoding="utf-8")
    response = Mock(
        url=final_url,
        status_code=200,
        headers={},
        encoding="utf-8",
    )

    def perform_request(_url, **kwargs):
        assert kwargs["cookies"] is None
        payload = (
            '<script>window.__APOLLO_STATE__={"defaultClient":{}};'
            "</script>"
        ).encode()
        assert kwargs["content_callback"](payload) == len(payload)
        return response

    with (
        patch(
            "app.spiders.kuaishou.share_runtime.curl_get",
            side_effect=perform_request,
        ),
        patch(
            "app.spiders.kuaishou.spider.cfg.get",
            return_value=str(auth_file),
        ),
        patch("app.spiders.kuaishou.spider.sync_playwright") as sync,
    ):
        sync.return_value.__enter__.return_value = Mock()
        spider.run()

    spider._run_share_browser_session.assert_called_once()
    spider._run_browser_session.assert_not_called()
    response.close.assert_called_once()


def test_overlong_idna_label_preserves_short_link_and_runs_browser_fallback() -> None:
    spider = _spider()
    overlong_label = "\u00e9" * 64
    short_url = f"https://{overlong_label}.kuaishou.com/f/example"

    def idna_resolver(host: str, *_args: object, **_kwargs: object):
        host.encode("idna")
        return []

    spider._public_domain_policy = DomainPolicyEngine(resolver=idna_resolver)
    spider.keyword = short_url
    spider.is_running = True
    spider._run_share_browser_session = Mock(return_value="completed")
    spider._run_browser_session = Mock(return_value="completed")
    spider._emit_finished = Mock()
    playwright = Mock()

    with (
        patch("app.spiders.kuaishou.share_runtime.curl_get") as request_get,
        patch("app.spiders.kuaishou.spider.sync_playwright") as sync,
    ):
        sync.return_value.__enter__.return_value = playwright
        spider.run()

    assert spider.keyword == short_url
    assert spider._is_short_share_url(spider.keyword)
    request_get.assert_not_called()
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
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.side_effect = (
        lambda *_args, **_kwargs: blocker.wait(0.5)
    )
    spider._public_domain_policy_engine = Mock(return_value=policy)
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
    policy = Mock(spec=DomainPolicyEngine)

    def block_validation(*_args, **_kwargs):
        entered.set()
        blocker.wait(0.5)
        return ("93.184.216.34",)

    policy.resolve_public_addresses.side_effect = block_validation
    spider._public_domain_policy_engine = Mock(return_value=policy)
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

    assert policy.resolve_public_addresses.call_count == 1


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
