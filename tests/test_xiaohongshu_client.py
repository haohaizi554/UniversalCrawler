from __future__ import annotations

from typing import Any

import pytest
import requests

from app.exceptions import SpiderParseError
from app.spiders.xiaohongshu import client as client_module
from app.spiders.xiaohongshu.client import XiaohongshuClient


_MISSING = object()


class _Response:
    """Complete response double for every attribute consumed by the client."""

    def __init__(
        self,
        *,
        payload: Any = _MISSING,
        text: str = "",
        status_error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self._payload = payload
        self._status_error = status_error
        self._json_error = json_error
        self.text = text
        self.raise_for_status_calls = 0
        self.json_calls = 0

    def raise_for_status(self) -> None:
        self.raise_for_status_calls += 1
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        self.json_calls += 1
        if self._json_error is not None:
            raise self._json_error
        if self._payload is _MISSING:
            raise AssertionError("response payload was not configured")
        return self._payload


class _Session:
    """Stateful requests.Session boundary double with queued outcomes."""

    def __init__(self, outcomes: tuple[_Response | Exception, ...] = ()) -> None:
        self.headers: dict[str, str] = {}
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.close_calls = 0
        self.close_error: Exception | None = None

    def _request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if not self._outcomes:
            raise AssertionError(f"unexpected {method} request to {url}")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get(self, url: str, **kwargs: Any) -> _Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _Response:
        return self._request("POST", url, **kwargs)

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    *outcomes: _Response | Exception,
    cookie_str: str = "a1=unit-a1; web_session=unit-session",
    proxy: str | None = None,
    timeout: int = 17,
) -> tuple[XiaohongshuClient, _Session]:
    session = _Session(outcomes)
    monkeypatch.setattr(client_module.requests, "Session", lambda: session)
    client = XiaohongshuClient(
        user_agent="unit-test-agent",
        cookie_str=cookie_str,
        proxy=proxy,
        timeout=timeout,
    )
    return client, session


@pytest.fixture
def signing_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def sign_boundary(**kwargs: Any) -> dict[str, str]:
        calls.append(dict(kwargs))
        return {"X-S": "XYS_unit-signature", "X-T": "1700000000000"}

    monkeypatch.setattr(client_module, "sign_xiaohongshu_headers", sign_boundary)
    return calls


def test_query_string_encodes_scalar_list_none_and_reserved_values() -> None:
    query = XiaohongshuClient._build_query_string(
        {
            "keyword": "穿搭 灵感",
            "image_formats": ["jpg", "webp", "avif"],
            "cursor": None,
            "path": "folder/item?full=true",
        }
    )

    assert query == (
        "keyword=%E7%A9%BF%E6%90%AD%20%E7%81%B5%E6%84%9F"
        "&image_formats=jpg,webp,avif&cursor=&path=folder%2Fitem%3Ffull%3Dtrue"
    )


def test_creator_notes_runs_real_signed_get_with_encoded_query(
    monkeypatch: pytest.MonkeyPatch,
    signing_calls: list[dict[str, Any]],
) -> None:
    response = _Response(
        payload={"success": True, "data": {"notes": [{"id": "note-1"}]}}
    )
    client, session = _make_client(
        monkeypatch,
        response,
        proxy="http://127.0.0.1:8899",
    )

    result = client.get_creator_notes(
        user_id="user/1",
        cursor="next page",
        page_size=3,
        xsec_token="token/?",
        xsec_source="pc_feed",
    )

    expected_params = {
        "num": 3,
        "cursor": "next page",
        "user_id": "user/1",
        "image_formats": "jpg,webp,avif",
        "xsec_token": "token/?",
        "xsec_source": "pc_feed",
    }
    assert result == {"notes": [{"id": "note-1"}]}
    assert signing_calls == [
        {
            "uri": "/api/sns/web/v1/user_posted",
            "data": expected_params,
            "cookie_str": "a1=unit-a1; web_session=unit-session",
            "method": "GET",
        }
    ]
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == (
        "https://edith.xiaohongshu.com/api/sns/web/v1/user_posted"
        "?num=3&cursor=next%20page&user_id=user%2F1&image_formats=jpg,webp,avif"
        "&xsec_token=token%2F%3F&xsec_source=pc_feed"
    )
    assert call["kwargs"] == {
        "headers": {
            "User-Agent": "unit-test-agent",
            "Referer": "https://www.xiaohongshu.com/",
            "Origin": "https://www.xiaohongshu.com",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Cookie": "a1=unit-a1; web_session=unit-session",
            "X-S": "XYS_unit-signature",
            "X-T": "1700000000000",
        },
        "timeout": 17,
        "proxies": {"http": "http://127.0.0.1:8899", "https": "http://127.0.0.1:8899"},
    }
    assert response.raise_for_status_calls == 1
    assert response.json_calls == 1


def test_search_notes_runs_real_post_with_compact_unicode_json(
    monkeypatch: pytest.MonkeyPatch,
    signing_calls: list[dict[str, Any]],
) -> None:
    response = _Response(
        payload={"success": True, "data": {"items": [], "has_more": False}}
    )
    client, session = _make_client(monkeypatch, response)

    result = client.search_notes(
        keyword="穿搭 灵感",
        page=2,
        page_size=15,
        search_id="fixed-search-id",
        sort="time_descending",
        note_type=1,
    )

    expected_data = {
        "keyword": "穿搭 灵感",
        "page": 2,
        "page_size": 15,
        "search_id": "fixed-search-id",
        "sort": "time_descending",
        "note_type": 1,
    }
    assert result == {"items": [], "has_more": False}
    assert signing_calls == [
        {
            "uri": "/api/sns/web/v1/search/notes",
            "data": expected_data,
            "cookie_str": "a1=unit-a1; web_session=unit-session",
            "method": "POST",
        }
    ]
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
    assert call["kwargs"]["data"] == (
        '{"keyword":"穿搭 灵感","page":2,"page_size":15,'
        '"search_id":"fixed-search-id","sort":"time_descending","note_type":1}'
    )
    assert call["kwargs"]["headers"]["X-S"] == "XYS_unit-signature"
    assert call["kwargs"]["timeout"] == 17
    assert call["kwargs"]["proxies"] is None
    assert response.raise_for_status_calls == 1
    assert response.json_calls == 1


@pytest.mark.parametrize(
    ("response", "message"),
    [
        pytest.param(
            _Response(
                text="<html>gateway failure</html>",
                json_error=ValueError("invalid JSON"),
            ),
            "JSON",
            id="malformed-json",
        ),
        pytest.param(
            _Response(payload=["unexpected", "array"], text='["unexpected","array"]'),
            None,
            id="non-object-json",
        ),
        pytest.param(
            _Response(
                payload={"success": False, "code": 300012, "msg": "login required"},
                text='{"success":false}',
            ),
            "code=300012: login required",
            id="business-error",
        ),
    ],
)
def test_post_rejects_malformed_and_business_error_payloads(
    monkeypatch: pytest.MonkeyPatch,
    signing_calls: list[dict[str, Any]],
    response: _Response,
    message: str | None,
) -> None:
    client, session = _make_client(monkeypatch, response)

    with pytest.raises(SpiderParseError, match=message):
        client.post("/api/sns/web/v1/test", {"note_id": "note-1"})

    assert len(signing_calls) == 1
    assert len(session.calls) == 1
    assert response.raise_for_status_calls == 1
    assert response.json_calls == 1


def test_html_detail_uses_http_and_parser_boundaries_then_adds_security_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = "<html><script>window.__INITIAL_STATE__={}</script></html>"
    response = _Response(text=html)
    client, session = _make_client(monkeypatch, response)
    parser_calls: list[tuple[str, str]] = []

    def parse_boundary(note_id: str, page_html: str) -> dict[str, Any]:
        parser_calls.append((note_id, page_html))
        return {"note_id": note_id, "title": "offline detail"}

    monkeypatch.setattr(client_module, "extract_note_detail_from_html", parse_boundary)

    detail = client.get_note_detail_from_html(
        note_id="note-42",
        xsec_token="fixed-token",
        xsec_source="pc_search",
    )

    assert detail == {
        "note_id": "note-42",
        "title": "offline detail",
        "xsec_token": "fixed-token",
        "xsec_source": "pc_search",
    }
    assert parser_calls == [("note-42", html)]
    assert session.calls == [
        {
            "method": "GET",
            "url": (
                "https://www.xiaohongshu.com/explore/note-42"
                "?xsec_token=fixed-token&xsec_source=pc_search"
            ),
            "kwargs": {
                "headers": dict(session.headers),
                "timeout": 17,
                "proxies": None,
            },
        }
    ]
    assert response.raise_for_status_calls == 1
    assert response.json_calls == 0


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        pytest.param(
            _Response(payload={"data": {"basic_info": {"user_id": "user-1"}}}),
            True,
            id="logged-in-payload",
        ),
        pytest.param(_Response(payload={}), False, id="guest-payload"),
        pytest.param(
            _Response(status_error=requests.HTTPError("unauthorized")),
            False,
            id="http-error",
        ),
        pytest.param(
            _Response(json_error=ValueError("invalid JSON")),
            None,
            id="invalid-json",
        ),
        pytest.param(requests.Timeout("probe timed out"), None, id="request-error"),
    ],
)
def test_login_probe_returns_true_false_or_none(
    monkeypatch: pytest.MonkeyPatch,
    signing_calls: list[dict[str, Any]],
    outcome: _Response | Exception,
    expected: bool | None,
) -> None:
    client, session = _make_client(monkeypatch, outcome)

    assert client.probe_login_status() is expected

    assert signing_calls == [
        {
            "uri": "/api/sns/web/v1/user/selfinfo",
            "data": {},
            "cookie_str": "a1=unit-a1; web_session=unit-session",
            "method": "GET",
        }
    ]
    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == (
        "https://edith.xiaohongshu.com/api/sns/web/v1/user/selfinfo"
    )


@pytest.mark.parametrize(
    ("cookie_str", "expected"),
    [
        pytest.param("a1=ready", True, id="a1-only"),
        pytest.param("web_session=session-only", False, id="missing-a1"),
        pytest.param("", False, id="empty"),
    ],
)
def test_cookie_readiness_requires_a1_cookie(
    monkeypatch: pytest.MonkeyPatch,
    cookie_str: str,
    expected: bool,
) -> None:
    client, session = _make_client(monkeypatch, cookie_str=cookie_str)

    assert client.check_cookie_ready() is expected
    assert session.calls == []


@pytest.mark.parametrize(
    "close_error",
    [
        pytest.param(
            requests.RequestException("close request failure"), id="request-error"
        ),
        pytest.param(RuntimeError("close runtime failure"), id="runtime-error"),
        pytest.param(AttributeError("close attribute failure"), id="attribute-error"),
    ],
)
def test_close_isolates_supported_session_errors(
    monkeypatch: pytest.MonkeyPatch,
    close_error: Exception,
) -> None:
    client, session = _make_client(monkeypatch)
    session.close_error = close_error

    client.close()

    assert session.close_calls == 1
