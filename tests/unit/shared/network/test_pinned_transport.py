from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Thread
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from curl_cffi import Curl
from curl_cffi import requests as curl_requests
from curl_cffi.const import CurlOpt

from shared.network import pinned_transport as pinned_transport_module
from shared.network.pinned_transport import (
    PinnedResponse,
    PinnedTransport,
    PinnedTransportNetworkError,
    canonicalize_host,
    canonicalize_request_target,
    curl_resolve_options,
)
from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation
from shared.subprocess_env import isolated_media_subprocess_env


def test_transport_module_import_does_not_require_optional_curl_dependency() -> None:
    script = """
import builtins
real_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name == 'curl_cffi' or name.startswith('curl_cffi.'):
        raise ImportError('curl_cffi intentionally unavailable')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked_import
import shared.network.pinned_transport
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_transport_rejects_unbounded_or_non_numeric_timeout(timeout) -> None:
    with pytest.raises(ValueError, match="timeout"):
        PinnedTransport(timeout=timeout)


def test_transport_rejects_integer_timeout_too_large_for_float() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PinnedTransport(timeout=10**10_000)


@pytest.mark.parametrize("timeout", [86_400.000_001, 10**308, 1e308])
def test_transport_rejects_finite_timeout_above_one_day(timeout) -> None:
    with pytest.raises(ValueError, match="timeout"):
        PinnedTransport(timeout=timeout)


def test_transport_accepts_one_day_timeout_boundary() -> None:
    PinnedTransport(timeout=86_400)


@pytest.mark.parametrize("max_response_bytes", [0, -1, 1.5, True])
def test_transport_rejects_invalid_response_budget(max_response_bytes) -> None:
    with pytest.raises(ValueError, match="max_response_bytes"):
        PinnedTransport(max_response_bytes=max_response_bytes)


@dataclass
class _FakeResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    content: bytes = b""
    closed: bool = False
    close_calls: int = 0
    close_error: BaseException | None = None

    def iter_content(self, chunk_size: int | None = None):
        size = 3 if chunk_size is None else max(1, int(chunk_size))
        for offset in range(0, len(self.content), size):
            yield self.content[offset : offset + size]

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _install_real_connect_to(curl: Curl, entry: str) -> Callable[[], None]:
    """Install CONNECT_TO across the oldest and current supported curl_cffi APIs."""

    try:
        curl.setopt(CurlOpt.CONNECT_TO, [entry])
    except (NotImplementedError, TypeError):
        from curl_cffi import _wrapper

        connect_to = _wrapper.lib.curl_slist_append(
            _wrapper.ffi.NULL,
            entry.encode("ascii"),
        )
        result = _wrapper.lib._curl_easy_setopt(
            curl._curl,
            CurlOpt.CONNECT_TO,
            connect_to,
        )
        assert result == 0

        def free_connect_to() -> None:
            _wrapper.lib.curl_slist_free_all(connect_to)

        return free_connect_to
    return lambda: None


class _RecordingSession:
    def __init__(
        self, responses: deque[_FakeResponse], barrier: Barrier | None = None
    ) -> None:
        self._responses = responses
        self._barrier = barrier
        self.curl_options = {CurlOpt.NOSIGNAL: 1}
        self.calls: list[dict[str, object]] = []
        self.closed = False
        self.close_calls = 0
        self.close_error: BaseException | None = None

    def request(self, method: str, url: str, **kwargs):
        if self._barrier is not None:
            self._barrier.wait(timeout=2.0)
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(kwargs.get("headers") or {}),
                "data": kwargs.get("data"),
                "curl_options": dict(self.curl_options),
            }
        )
        return self._responses.popleft()

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _HostileCurlOptionsSession:
    def __init__(
        self,
        *,
        getter_errors: dict[int, BaseException] | None = None,
        setter_error: BaseException | None = None,
        store_assignment: bool = True,
        mutate_resolve_assignment: bool = False,
        assignment_mutator: Callable[[dict[object, object]], None] | None = None,
    ) -> None:
        self._curl_options = {CurlOpt.NOSIGNAL: 1}
        self._getter_errors = getter_errors or {}
        self._setter_error = setter_error
        self._store_assignment = store_assignment
        self._mutate_resolve_assignment = mutate_resolve_assignment
        self._assignment_mutator = assignment_mutator
        self.getter_calls = 0
        self.setter_calls = 0
        self.request_calls = 0
        self.close_calls = 0
        self.close_error: BaseException | None = None

    @property
    def curl_options(self):
        self.getter_calls += 1
        error = self._getter_errors.get(self.getter_calls)
        if error is not None:
            raise error
        return self._curl_options

    @curl_options.setter
    def curl_options(self, value) -> None:
        self.setter_calls += 1
        if self._setter_error is not None:
            raise self._setter_error
        if self._mutate_resolve_assignment and CurlOpt.RESOLVE in value:
            value[CurlOpt.RESOLVE][:] = ["one.example:443:127.0.0.1"]
        if self._assignment_mutator is not None:
            self._assignment_mutator(value)
        if self._store_assignment:
            self._curl_options = value

    def request(self, *_args, **_kwargs):
        self.request_calls += 1
        return _FakeResponse(200, "https://one.example:443/a", {}, b"unsafe")

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class _CookieJarSession(_RecordingSession):
    def __init__(
        self, responses: deque[_FakeResponse], barrier: Barrier | None = None
    ) -> None:
        super().__init__(responses, barrier)
        self._domain_cookie = ""

    def request(self, method: str, url: str, **kwargs):
        effective_headers = dict(kwargs.get("headers") or {})
        host = str(urlsplit(url).hostname or "")
        if self._domain_cookie and host.endswith(".example.test"):
            effective_headers.setdefault("Cookie", self._domain_cookie)
        kwargs["headers"] = effective_headers
        response = super().request(method, url, **kwargs)
        set_cookie = str(response.headers.get("Set-Cookie") or "")
        if "Domain=.example.test" in set_cookie:
            self._domain_cookie = set_cookie.split(";", 1)[0]
        return response


class _RecordingSessionFactory:
    def __init__(
        self,
        responses: list[_FakeResponse],
        *,
        barrier: Barrier | None = None,
        session_type: type[_RecordingSession] = _RecordingSession,
    ) -> None:
        self.responses = deque(responses)
        self.barrier = barrier
        self.session_type = session_type
        self.sessions: list[_RecordingSession] = []

    def __call__(self) -> _RecordingSession:
        session = self.session_type(self.responses, self.barrier)
        self.sessions.append(session)
        return session


class _CapturingPolicy:
    def __init__(self) -> None:
        self.checked_urls: list[str] = []

    def resolve_public_addresses(self, url: str) -> tuple[str, ...]:
        self.checked_urls.append(url)
        if "xn--bcher-kva.example" in url:
            return ("93.184.216.34",)
        if "one.example" in url:
            return ("1.1.1.1",)
        if "two.example" in url:
            return ("8.8.8.8",)
        return ("8.8.4.4", "2606:4700:4700::1111")


def test_domain_policy_resolves_each_transport_hop_exactly_once() -> None:
    resolver_calls: list[tuple[str, int | None]] = []

    def resolver(host: str, port: int | None, **_kwargs):
        resolver_calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    response = _FakeResponse(200, "https://public.example:443/file", {}, b"ok")

    result = PinnedTransport(
        policy=DomainPolicyEngine(resolver=resolver),
        session_factory=lambda: _RecordingSession(deque([response])),
    ).request("GET", "https://public.example/file", headers={})

    assert result.body == b"ok"
    assert resolver_calls == [("public.example", 443)]


def test_domain_policy_resolver_api_keeps_temporary_dns_failure_out_of_policy_violations() -> None:
    dns_error = socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")

    def resolver(*_args, **_kwargs):
        raise dns_error

    policy = DomainPolicyEngine(resolver=resolver)

    with pytest.raises(OSError) as exc_info:
        policy.resolve_public_addresses("https://public.example/file")

    assert exc_info.value is dns_error
    assert not isinstance(exc_info.value, DomainPolicyViolation)


def test_domain_policy_preflight_converts_temporary_dns_failure_to_policy_rejection() -> None:
    dns_error = socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")

    def resolver(*_args, **_kwargs):
        raise dns_error

    with pytest.raises(DomainPolicyViolation, match="无法解析") as exc_info:
        DomainPolicyEngine(resolver=resolver).require_public_url(
            "https://public.example/file"
        )

    assert exc_info.value.__cause__ is dns_error


def test_transport_normalizes_temporary_dns_failure_as_retryable_network_error() -> None:
    dns_error = socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")
    resolver_calls = 0

    def resolver(*_args, **_kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        raise dns_error

    with pytest.raises(PinnedTransportNetworkError, match="name resolution failed") as exc_info:
        PinnedTransport(
            policy=DomainPolicyEngine(resolver=resolver),
            session_factory=lambda: pytest.fail("DNS failure must precede session creation"),
        ).request("GET", "https://public.example/file", headers={})

    assert exc_info.value.__cause__ is dns_error
    assert resolver_calls == 1


def test_transport_keeps_private_dns_answers_as_policy_violations() -> None:
    policy = DomainPolicyEngine(
        resolver=lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]
    )

    with pytest.raises(DomainPolicyViolation):
        PinnedTransport(
            policy=policy,
            session_factory=lambda: pytest.fail("unsafe DNS must precede session creation"),
        ).request("GET", "https://public.example/file", headers={})


def test_public_curl_options_pin_dns_and_disable_environment_proxy() -> None:
    target = canonicalize_request_target("https://CDN.Example.:8443/a.ts")

    options = curl_resolve_options(
        target,
        ("8.8.8.8", "2606:4700:4700::1111"),
        disable_proxy=True,
    )

    assert target.url == "https://cdn.example:8443/a.ts"
    assert target.authority == "cdn.example:8443"
    assert options[CurlOpt.RESOLVE] == [
        "cdn.example:8443:8.8.8.8,[2606:4700:4700::1111]"
    ]
    assert options[CurlOpt.PROXY] == ""


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Test": "safe\r\nHost: attacker.example"},
        {"X-Test\nHost": "attacker.example"},
        {"Host ": "attacker.example"},
        {"X-Test": "value\x00suffix"},
    ],
)
def test_request_headers_reject_control_characters_and_invalid_names(headers) -> None:
    policy = _CapturingPolicy()

    with pytest.raises(DomainPolicyViolation, match="header"):
        PinnedTransport(policy=policy).request(
            "GET",
            "https://one.example/resource",
            headers=headers,
        )

    assert policy.checked_urls == []


@pytest.mark.parametrize("max_redirects", [-1, 1.5, True])
def test_request_rejects_invalid_redirect_budget(max_redirects) -> None:
    with pytest.raises(ValueError, match="max_redirects"):
        PinnedTransport(policy=_CapturingPolicy()).request(
            "GET",
            "https://one.example/resource",
            headers={},
            max_redirects=max_redirects,
        )


@pytest.mark.parametrize(
    "host",
    ["example..com", ".example.com", "example.com..", "example.com...", ""],
)
def test_canonicalize_host_rejects_empty_labels_and_multiple_terminal_dots(
    host: str,
) -> None:
    with pytest.raises(DomainPolicyViolation, match="host"):
        canonicalize_host(host)


def test_canonicalize_host_accepts_exactly_one_terminal_dot_and_idna() -> None:
    assert canonicalize_host("BÜCHER.Example.") == "xn--bcher-kva.example"


def test_canonicalize_host_uses_nontransitional_idna2008() -> None:
    assert canonicalize_host("faß.de") == "xn--fa-hia.de"
    target = canonicalize_request_target("https://faß.de./download")

    assert target.host == "xn--fa-hia.de"
    assert target.url == "https://xn--fa-hia.de:443/download"
    assert curl_resolve_options(target, ("1.1.1.1",))[CurlOpt.RESOLVE] == [
        "xn--fa-hia.de:443:1.1.1.1"
    ]


@pytest.mark.parametrize("host", ["ab\u200dcd.example", "abcא.example"])
def test_canonicalize_host_rejects_invalid_joiner_and_bidi(host: str) -> None:
    with pytest.raises(DomainPolicyViolation, match="IDNA"):
        canonicalize_host(host)


@pytest.mark.parametrize(
    "host",
    ["127.1", "0177.0.0.1", "0x7f000001", "0x7f.0.0.1", "2130706433"],
)
def test_canonicalize_host_rejects_legacy_numeric_ipv4_spellings(host: str) -> None:
    with pytest.raises(DomainPolicyViolation, match="host"):
        canonicalize_host(host)


@pytest.mark.parametrize("url", ["https://example.com:0/a", "https://example.com:/a"])
def test_canonicalize_request_target_rejects_zero_and_empty_explicit_ports(
    url: str,
) -> None:
    with pytest.raises(DomainPolicyViolation, match="port"):
        canonicalize_request_target(url)


def test_canonicalize_request_target_brackets_ipv6_and_needs_no_dns_override() -> None:
    target = canonicalize_request_target("https://[2606:4700:4700::1111]:8443/a")

    assert target.authority == "[2606:4700:4700::1111]:8443"
    assert target.url == "https://[2606:4700:4700::1111]:8443/a"
    options = curl_resolve_options(target, ("2606:4700:4700::1111",))
    assert CurlOpt.RESOLVE not in options
    assert options[CurlOpt.PROXY] == ""


def test_literal_target_fails_closed_when_policy_address_does_not_match() -> None:
    target = canonicalize_request_target("https://8.8.8.8/a")

    with pytest.raises(DomainPolicyViolation, match="literal host"):
        curl_resolve_options(target, ("1.1.1.1",))


def test_redirect_hops_share_one_canonical_target_without_system_dns(
    monkeypatch,
) -> None:
    system_dns = Mock(side_effect=AssertionError("system DNS fallback"))
    monkeypatch.setattr(socket, "getaddrinfo", system_dns)
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                status_code=302,
                url="https://xn--bcher-kva.example:443/start",
                headers={"Location": "https://CDN.Example.:8443/final"},
            ),
            _FakeResponse(
                status_code=200,
                url="https://cdn.example:8443/final",
                headers={},
                content=b"ok",
            ),
        ]
    )
    policy = _CapturingPolicy()

    result = PinnedTransport(policy=policy, session_factory=factory).request(
        "GET",
        "https://BÜCHER.Example./start",
        headers={"Host": "attacker.example"},
    )

    assert result.body == b"ok"
    assert policy.checked_urls == [
        "https://xn--bcher-kva.example:443/start",
        "https://cdn.example:8443/final",
    ]
    calls = [call for session in factory.sessions for call in session.calls]
    assert len(factory.sessions) == 2
    assert [call["url"] for call in calls] == policy.checked_urls
    assert [call["headers"] for call in calls] == [{}, {}]
    assert [
        call["curl_options"][CurlOpt.RESOLVE][0].split(":", 2)[:2] for call in calls
    ] == [["xn--bcher-kva.example", "443"], ["cdn.example", "8443"]]
    assert all(call["curl_options"][CurlOpt.PROXY] == "" for call in calls)
    assert all(call["curl_options"][CurlOpt.FRESH_CONNECT] == 1 for call in calls)
    assert all(call["curl_options"][CurlOpt.FORBID_REUSE] == 1 for call in calls)
    assert all(session.closed for session in factory.sessions)
    system_dns.assert_not_called()


def test_redirect_location_header_name_is_case_insensitive() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                302,
                "https://one.example:443/start",
                {"lOcAtIoN": "/final"},
            ),
            _FakeResponse(200, "https://one.example:443/final", {}, b"ok"),
        ]
    )

    result = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=factory,
    ).request("GET", "https://one.example/start", headers={})

    assert result.status_code == 200
    assert result.url == "https://one.example:443/final"
    assert result.redirect_chain == (
        "https://one.example:443/start",
        "https://one.example:443/final",
    )


def test_pinned_response_four_positional_arguments_keep_compatibility() -> None:
    response = PinnedResponse(200, "https://one.example:443/a", {}, b"ok")

    assert response.redirect_chain == ()


def test_response_records_canonical_url_when_no_redirect_occurs() -> None:
    factory = _RecordingSessionFactory(
        [_FakeResponse(200, "https://one.example:443/a", {}, b"ok")]
    )

    result = PinnedTransport(
        policy=_CapturingPolicy(), session_factory=factory
    ).request("GET", "HTTPS://ONE.Example./a", headers={})

    assert result.redirect_chain == ("https://one.example:443/a",)


def test_response_records_every_canonical_same_origin_redirect_hop() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(302, "https://one.example:443/a", {"Location": "/b?step=1"}),
            _FakeResponse(307, "https://one.example:443/b?step=1", {"Location": "./c"}),
            _FakeResponse(200, "https://one.example:443/c", {}, b"ok"),
        ]
    )

    result = PinnedTransport(
        policy=_CapturingPolicy(), session_factory=factory
    ).request("GET", "https://ONE.Example./a", headers={})

    assert result.redirect_chain == (
        "https://one.example:443/a",
        "https://one.example:443/b?step=1",
        "https://one.example:443/c",
    )


def test_response_records_every_canonical_cross_origin_redirect_hop() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                302,
                "https://one.example:443/a",
                {"Location": "HTTPS://TWO.Example./b"},
            ),
            _FakeResponse(
                308,
                "https://two.example:443/b",
                {"Location": "https://BÜCHER.Example./final"},
            ),
            _FakeResponse(200, "https://xn--bcher-kva.example:443/final", {}, b"ok"),
        ]
    )

    result = PinnedTransport(
        policy=_CapturingPolicy(), session_factory=factory
    ).request("GET", "https://ONE.Example./a", headers={})

    assert result.redirect_chain == (
        "https://one.example:443/a",
        "https://two.example:443/b",
        "https://xn--bcher-kva.example:443/final",
    )


def test_cross_origin_redirect_drops_credentials_before_next_request() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                302, "https://one.example:443/a", {"Location": "https://two.example/b"}
            ),
            _FakeResponse(200, "https://two.example:443/b", {}, b"ok"),
        ]
    )

    PinnedTransport(policy=_CapturingPolicy(), session_factory=factory).request(
        "GET",
        "https://one.example/a",
        headers={
            "Cookie": "session=secret",
            "Authorization": "Bearer secret",
            "Proxy-Authorization": "Basic secret",
            "X-Public": "kept",
        },
    )

    assert len(factory.sessions) == 2
    assert factory.sessions[0].calls[0]["headers"] == {
        "Cookie": "session=secret",
        "Authorization": "Bearer secret",
        "X-Public": "kept",
    }
    assert factory.sessions[1].calls[0]["headers"] == {"X-Public": "kept"}


@pytest.mark.parametrize(
    ("status_code", "method"),
    [(301, "POST"), (302, "POST"), (303, "PUT")],
)
def test_redirects_rewritten_to_get_drop_body_and_framing_headers(
    status_code: int,
    method: str,
) -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(status_code, "https://one.example:443/a", {"Location": "/b"}),
            _FakeResponse(200, "https://one.example:443/b", {}, b"ok"),
        ]
    )

    PinnedTransport(policy=_CapturingPolicy(), session_factory=factory).request(
        method,
        "https://one.example/a",
        headers={
            "Content-Encoding": "gzip",
            "content-language": "en",
            "CONTENT-LOCATION": "/payload",
            "Content-Type": "text/plain",
            "Content-Length": "7",
            "TRANSFER-ENCODING": "chunked",
            "Trailer": "Digest",
            "EXPECT": "100-continue",
            "X-Public": "kept",
        },
        body=b"payload",
    )

    assert factory.sessions[0].calls[1]["method"] == "GET"
    assert factory.sessions[0].calls[1]["data"] is None
    assert factory.sessions[0].calls[1]["headers"] == {"X-Public": "kept"}


def test_303_redirect_preserves_head_but_drops_body_and_body_headers() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(303, "https://one.example:443/a", {"Location": "/b"}),
            _FakeResponse(200, "https://one.example:443/b", {}, b""),
        ]
    )

    PinnedTransport(policy=_CapturingPolicy(), session_factory=factory).request(
        "HEAD",
        "https://one.example/a",
        headers={
            "Content-Encoding": "gzip",
            "content-language": "en",
            "CONTENT-LOCATION": "/payload",
            "Content-Type": "text/plain",
            "Content-Length": "7",
            "TRANSFER-ENCODING": "chunked",
            "Trailer": "Digest",
            "EXPECT": "100-continue",
            "X-Public": "kept",
        },
        body=b"payload",
    )

    assert factory.sessions[0].calls[1]["method"] == "HEAD"
    assert factory.sessions[0].calls[1]["data"] is None
    assert factory.sessions[0].calls[1]["headers"] == {"X-Public": "kept"}


def test_proxy_authorization_is_never_sent_to_an_origin() -> None:
    factory = _RecordingSessionFactory(
        [_FakeResponse(200, "https://one.example:443/a", {}, b"ok")]
    )

    PinnedTransport(policy=_CapturingPolicy(), session_factory=factory).request(
        "GET",
        "https://one.example/a",
        headers={"Proxy-Authorization": "Basic secret", "X-Public": "kept"},
    )

    assert factory.sessions[0].calls[0]["headers"] == {"X-Public": "kept"}


def test_cross_origin_redirect_drops_session_cookie_jar() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                302,
                "https://a.example.test:443/a",
                {
                    "Location": "https://b.example.test/b",
                    "Set-Cookie": "sid=secret; Domain=.example.test; Secure",
                },
            ),
            _FakeResponse(200, "https://b.example.test:443/b", {}, b"ok"),
        ],
        session_type=_CookieJarSession,
    )

    PinnedTransport(policy=_CapturingPolicy(), session_factory=factory).request(
        "GET",
        "https://a.example.test/a",
        headers={},
    )

    assert len(factory.sessions) == 2
    assert "Cookie" not in factory.sessions[1].calls[0]["headers"]


def test_same_origin_redirect_keeps_operation_cookie_jar() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                302,
                "https://a.example.test:443/a",
                {
                    "Location": "/b",
                    "Set-Cookie": "sid=kept; Domain=.example.test; Secure",
                },
            ),
            _FakeResponse(200, "https://a.example.test:443/b", {}, b"ok"),
        ],
        session_type=_CookieJarSession,
    )

    PinnedTransport(policy=_CapturingPolicy(), session_factory=factory).request(
        "GET",
        "https://a.example.test/a",
        headers={},
    )

    assert len(factory.sessions) == 1
    assert factory.sessions[0].calls[1]["headers"]["Cookie"] == "sid=kept"


def test_resolver_time_counts_against_total_deadline() -> None:
    class SlowPolicy(_CapturingPolicy):
        def resolve_public_addresses(self, url: str) -> tuple[str, ...]:
            time.sleep(0.03)
            return super().resolve_public_addresses(url)

    factory = _RecordingSessionFactory(
        [_FakeResponse(200, "https://one.example:443/a", {}, b"late")]
    )

    with pytest.raises(TimeoutError, match="deadline"):
        PinnedTransport(
            policy=SlowPolicy(),
            session_factory=factory,
            timeout=0.005,
        ).request("GET", "https://one.example/a", headers={})

    assert factory.sessions == []


def test_session_setup_time_counts_against_total_deadline() -> None:
    session = _RecordingSession(
        deque([_FakeResponse(200, "https://one.example:443/a", {}, b"late")])
    )

    def slow_factory() -> _RecordingSession:
        time.sleep(0.03)
        return session

    with pytest.raises(TimeoutError, match="deadline"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=slow_factory,
            timeout=0.005,
        ).request("GET", "https://one.example/a", headers={})

    assert session.calls == []
    assert session.close_calls == 1


def test_response_completion_time_counts_against_total_deadline() -> None:
    response = _FakeResponse(200, "https://one.example:443/a", {}, b"late")

    class SlowSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            time.sleep(0.03)
            return super().request(method, url, **kwargs)

    session = SlowSession(deque([response]))

    with pytest.raises(TimeoutError, match="deadline"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            timeout=0.005,
        ).request("GET", "https://one.example/a", headers={})

    assert len(session.calls) == 1
    assert response.close_calls == 1
    assert session.close_calls == 1


def test_real_curl_never_reinterprets_rejected_numeric_host_as_loopback() -> None:
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"loopback")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(DomainPolicyViolation, match="host"):
            PinnedTransport(policy=_CapturingPolicy(), timeout=2.0).request(
                "GET",
                f"http://0x7f000001:{server.server_port}/",
                headers={},
            )
        assert hits == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_transport_rejects_explicit_real_session_before_request(
    monkeypatch,
) -> None:
    pinned_hits: list[str] = []
    steered_hits: list[str] = []

    class PinnedHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            pinned_hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"pinned")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class SteeredHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            steered_hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"steered")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    pinned_server = ThreadingHTTPServer(("127.0.0.1", 0), PinnedHandler)
    steered_server = ThreadingHTTPServer(("127.0.0.1", 0), SteeredHandler)
    pinned_thread = Thread(target=pinned_server.serve_forever, daemon=True)
    steered_thread = Thread(target=steered_server.serve_forever, daemon=True)
    pinned_thread.start()
    steered_thread.start()
    curl = Curl()
    free_connect_to = _install_real_connect_to(
        curl,
        (
            f"one.example:{pinned_server.server_port}:"
            f"127.0.0.1:{steered_server.server_port}"
        ),
    )
    session = curl_requests.Session(
        curl=curl,
        impersonate="chrome",
        trust_env=False,
        allow_redirects=False,
        use_thread_local_curl=False,
    )
    monkeypatch.setattr(
        pinned_transport_module,
        "curl_resolve_options",
        lambda target, *_args, **_kwargs: {
            CurlOpt.RESOLVE: [f"{target.host}:{target.port}:127.0.0.1"],
            CurlOpt.PROXY: "",
        },
    )
    try:
        with pytest.raises(DomainPolicyViolation, match="owned"):
            PinnedTransport(
                policy=_CapturingPolicy(),
                session_factory=lambda: session,
                timeout=2,
            ).request(
                "GET",
                f"http://one.example:{pinned_server.server_port}/custom-handle",
                headers={},
            )
        assert pinned_hits == []
        assert steered_hits == []
    finally:
        session.close()
        free_connect_to()
        pinned_server.shutdown()
        steered_server.shutdown()
        pinned_server.server_close()
        steered_server.server_close()
        pinned_thread.join(timeout=2.0)
        steered_thread.join(timeout=2.0)


def test_same_origin_redirect_uses_the_newly_pinned_address(monkeypatch) -> None:
    first_hits: list[str] = []
    second_hits: list[str] = []

    class FirstHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            first_hits.append(self.path)
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"old-address"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class SecondHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            second_hits.append(self.path)
            body = b"new-address"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    first_server = ThreadingHTTPServer(("127.0.0.1", 0), FirstHandler)
    second_server = ThreadingHTTPServer(
        ("127.0.0.2", first_server.server_port),
        SecondHandler,
    )
    first_thread = Thread(target=first_server.serve_forever, daemon=True)
    second_thread = Thread(target=second_server.serve_forever, daemon=True)
    first_thread.start()
    second_thread.start()

    class RebindingPolicy:
        def __init__(self) -> None:
            self.calls = 0

        def resolve_public_addresses(self, _url: str) -> tuple[str, ...]:
            self.calls += 1
            return ("127.0.0.1",) if self.calls == 1 else ("127.0.0.2",)

    monkeypatch.setattr(
        pinned_transport_module,
        "curl_resolve_options",
        lambda target, addresses, **_kwargs: {
            CurlOpt.RESOLVE: [
                f"{target.host}:{target.port}:{','.join(addresses)}"
            ],
            CurlOpt.PROXY: "",
        },
    )

    try:
        response = PinnedTransport(policy=RebindingPolicy(), timeout=2).request(
            "GET",
            f"http://one.example:{first_server.server_port}/start",
            headers={},
        )

        assert response.body == b"new-address"
        assert first_hits == ["/start"]
        assert second_hits == ["/final"]
    finally:
        first_server.shutdown()
        second_server.shutdown()
        first_server.server_close()
        second_server.server_close()
        first_thread.join(timeout=2.0)
        second_thread.join(timeout=2.0)


def test_real_session_with_inherited_origin_headers_is_rejected_before_request() -> (
    None
):
    hits: list[tuple[str | None, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(
                (self.headers.get("Host"), self.headers.get("Authorization"))
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"loopback")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    curl = Curl()
    free_connect_to = _install_real_connect_to(
        curl,
        (
            f"one.example:{server.server_port}:"
            f"127.0.0.1:{server.server_port}"
        ),
    )
    session = curl_requests.Session(
        curl=curl,
        impersonate="chrome",
        headers={
            "Host": "inherited.invalid",
            "Authorization": "Bearer inherited",
        },
        trust_env=False,
        allow_redirects=False,
        use_thread_local_curl=False,
    )
    try:
        with pytest.raises(DomainPolicyViolation, match="transport owned"):
            PinnedTransport(
                policy=_CapturingPolicy(),
                session_factory=lambda: session,
                timeout=0.25,
            ).request(
                "GET",
                f"http://one.example:{server.server_port}/inherited-headers",
                headers={},
            )
        assert hits == []
    finally:
        session.close()
        free_connect_to()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_pinned_transport_never_reuses_or_mutates_an_external_session() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(200, "https://one.example:443/a", {}, b"one"),
            _FakeResponse(200, "https://two.example:443/b", {}, b"two"),
        ]
    )
    shared_session = _RecordingSession(deque())
    transport = PinnedTransport(policy=_CapturingPolicy(), session_factory=factory)

    assert transport.request("GET", "https://one.example/a", headers={}).body == b"one"
    assert transport.request("GET", "https://two.example/b", headers={}).body == b"two"

    assert len(factory.sessions) == 2
    assert factory.sessions[0] is not factory.sessions[1]
    assert all(session.closed for session in factory.sessions)
    assert shared_session.curl_options == {CurlOpt.NOSIGNAL: 1}


def test_transport_closes_and_rejects_session_without_curl_options() -> None:
    class MissingCurlOptionsSession:
        def __init__(self) -> None:
            self.closed = False
            self.request_calls = 0

        def request(self, *_args, **_kwargs):
            self.request_calls += 1
            return _FakeResponse(200, "https://one.example:443/a", {}, b"unsafe")

        def close(self) -> None:
            self.closed = True

    session = MissingCurlOptionsSession()

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.closed
    assert session.request_calls == 0


@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "streaming"])
@pytest.mark.parametrize(
    "rejection_branch",
    ["real-injected", "options-not-dict", "dirty-state"],
)
@pytest.mark.parametrize(
    ("error_type", "error_args"),
    [(KeyboardInterrupt, ("stop",)), (SystemExit, (7,))],
    ids=["keyboard-interrupt", "system-exit"],
)
def test_candidate_rejection_prefers_cleanup_control_flow_before_policy_error(
    monkeypatch,
    streaming: bool,
    rejection_branch: str,
    error_type: type[BaseException],
    error_args: tuple[object, ...],
) -> None:
    cleanup_error = error_type(*error_args)

    class Candidate:
        def __init__(self) -> None:
            self.curl_options: object = {}
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            raise cleanup_error

    candidate = Candidate()
    if rejection_branch == "real-injected":
        monkeypatch.setattr(curl_requests, "Session", Candidate)
    elif rejection_branch == "options-not-dict":
        candidate.curl_options = ()
    else:
        monkeypatch.setattr(
            pinned_transport_module,
            "_real_session_request_state_is_clean",
            lambda _candidate: False,
        )
    transport = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: candidate,
        max_response_bytes=16,
    )

    with pytest.raises(error_type) as exc_info:
        if streaming:
            transport.request_to_sink(
                "GET",
                "https://one.example/file",
                headers={},
                sink=lambda _chunk: None,
                max_total_bytes=16,
            )
        else:
            transport.request("GET", "https://one.example/file", headers={})

    assert exc_info.value is cleanup_error
    assert candidate.close_calls == 1


@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "streaming"])
@pytest.mark.parametrize(
    "primary_kind",
    ["ordinary", "policy"],
)
@pytest.mark.parametrize(
    ("cleanup_type", "cleanup_args"),
    [(KeyboardInterrupt, ("stop",)), (SystemExit, (7,))],
    ids=["keyboard-interrupt-cleanup", "system-exit-cleanup"],
)
def test_candidate_getter_primary_survives_cleanup_control_flow_with_safe_note(
    streaming: bool,
    primary_kind: str,
    cleanup_type: type[BaseException],
    cleanup_args: tuple[object, ...],
) -> None:
    primary_error: BaseException
    if primary_kind == "ordinary":
        primary_error = RuntimeError("getter failed")
    else:
        primary_error = DomainPolicyViolation("getter policy failed")
    cleanup_error = cleanup_type(*cleanup_args)

    class GetterFailingCandidate:
        close_calls = 0

        @property
        def curl_options(self):
            raise primary_error

        def close(self) -> None:
            self.close_calls += 1
            raise cleanup_error

    candidate = GetterFailingCandidate()
    transport = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: candidate,
        max_response_bytes=16,
    )

    with pytest.raises(type(primary_error)) as exc_info:
        if streaming:
            transport.request_to_sink(
                "GET",
                "https://one.example/file",
                headers={},
                sink=lambda _chunk: None,
                max_total_bytes=16,
            )
        else:
            transport.request("GET", "https://one.example/file", headers={})

    assert exc_info.value is primary_error
    assert candidate.close_calls == 1
    assert any(
        "session" in note and cleanup_type.__name__ in note
        for note in primary_error.__notes__
    )


@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "streaming"])
@pytest.mark.parametrize(
    "failure_stage",
    ["policy-rejection", "getter-primary"],
)
def test_candidate_cleanup_hostile_type_name_cannot_replace_the_outcome(
    streaming: bool,
    failure_stage: str,
) -> None:
    class HostileNameMeta(type):
        @property
        def __name__(cls) -> str:
            raise SystemExit("cleanup type-name lookup must not run")

    class HostileCleanupError(Exception, metaclass=HostileNameMeta):
        pass

    cleanup_error = HostileCleanupError("private cleanup detail")
    primary_error = RuntimeError("getter primary")

    class Candidate:
        close_calls = 0

        @property
        def curl_options(self):
            if failure_stage == "getter-primary":
                raise primary_error
            return ()

        def close(self) -> None:
            self.close_calls += 1
            raise cleanup_error

    candidate = Candidate()
    transport = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: candidate,
        max_response_bytes=16,
    )
    expected_error = primary_error if failure_stage == "getter-primary" else None

    if expected_error is None:
        expectation = pytest.raises(DomainPolicyViolation, match="pinned DNS")
    else:
        expectation = pytest.raises(RuntimeError, match="getter primary")
    with expectation as exc_info:
        if streaming:
            transport.request_to_sink(
                "GET",
                "https://one.example/file",
                headers={},
                sink=lambda _chunk: None,
                max_total_bytes=16,
            )
        else:
            transport.request("GET", "https://one.example/file", headers={})

    if expected_error is not None:
        assert exc_info.value is expected_error
    assert candidate.close_calls == 1


def test_transport_rejects_noop_curl_options_setter_before_request() -> None:
    session = _HostileCurlOptionsSession(store_assignment=False)

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.setter_calls == 1
    assert session.getter_calls == 2
    assert session.request_calls == 0
    assert session.close_calls == 1


def test_transport_rejects_in_place_resolve_tampering_before_request() -> None:
    session = _HostileCurlOptionsSession(mutate_resolve_assignment=True)

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.setter_calls == 1
    assert session.getter_calls == 2
    assert session.request_calls == 0
    assert session.close_calls == 1


@pytest.mark.parametrize(
    ("steering_option", "steering_value"),
    [
        pytest.param(
            CurlOpt.URL,
            "http://127.0.0.1/internal",
            id="url",
        ),
        pytest.param(
            CurlOpt.CONNECT_TO,
            ["one.example:443:127.0.0.1:8080"],
            id="connect-to",
        ),
    ],
)
def test_transport_rejects_setter_injected_steering_option_before_request(
    steering_option: object,
    steering_value: object,
) -> None:
    def inject_steering_option(options: dict[object, object]) -> None:
        options[steering_option] = steering_value

    session = _HostileCurlOptionsSession(
        assignment_mutator=inject_steering_option
    )

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.setter_calls == 1
    assert session.getter_calls == 2
    assert session.request_calls == 0
    assert session.close_calls == 1


def test_transport_discards_initial_steering_options_before_request() -> None:
    session = _RecordingSession(
        deque([_FakeResponse(200, "https://one.example:443/a", {}, b"safe")])
    )
    session.curl_options = {
        CurlOpt.NOSIGNAL: 0,
        CurlOpt.URL: "http://127.0.0.1/internal",
        CurlOpt.CONNECT_TO: ["one.example:443:127.0.0.1:8080"],
    }

    response = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: session,
    ).request("GET", "https://one.example/a", headers={})

    assert response.body == b"safe"
    assert session.calls[0]["curl_options"] == {
        CurlOpt.NOSIGNAL: 1,
        CurlOpt.FRESH_CONNECT: 1,
        CurlOpt.FORBID_REUSE: 1,
        CurlOpt.RESOLVE: ["one.example:443:1.1.1.1"],
        CurlOpt.PROXY: "",
    }
    assert session.close_calls == 1


@pytest.mark.parametrize("mutation", ["delete", "replace"])
def test_transport_rejects_missing_or_replaced_authoritative_option_before_request(
    mutation: str,
) -> None:
    def mutate_authoritative_option(options: dict[object, object]) -> None:
        if mutation == "delete":
            del options[CurlOpt.NOSIGNAL]
        else:
            options[CurlOpt.NOSIGNAL] = 0

    session = _HostileCurlOptionsSession(
        assignment_mutator=mutate_authoritative_option
    )

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.setter_calls == 1
    assert session.getter_calls == 2
    assert session.request_calls == 0
    assert session.close_calls == 1


@pytest.mark.parametrize(
    "setter_error",
    [RuntimeError("setter failure"), AttributeError("curl_options is read-only")],
    ids=["setter-error", "read-only"],
)
def test_transport_rejects_curl_options_setter_failure_before_request(
    setter_error: BaseException,
) -> None:
    session = _HostileCurlOptionsSession(setter_error=setter_error)

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.setter_calls == 1
    assert session.getter_calls == 1
    assert session.request_calls == 0
    assert session.close_calls == 1


def test_transport_rejects_curl_options_reread_failure_before_request() -> None:
    session = _HostileCurlOptionsSession(
        getter_errors={2: RuntimeError("curl_options reread failure")}
    )

    with pytest.raises(DomainPolicyViolation, match="pinned DNS"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert session.setter_calls == 1
    assert session.getter_calls == 2
    assert session.request_calls == 0
    assert session.close_calls == 1


@pytest.mark.parametrize(
    "control_error",
    [KeyboardInterrupt("stop"), SystemExit(7)],
    ids=["keyboard-interrupt", "system-exit"],
)
def test_transport_closes_candidate_and_preserves_control_flow_from_curl_options_getter(
    control_error: BaseException,
) -> None:
    session = _HostileCurlOptionsSession(getter_errors={1: control_error})
    session.close_error = LookupError("candidate cleanup failure")

    with pytest.raises(type(control_error)) as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert exc_info.value is control_error
    assert session.setter_calls == 0
    assert session.getter_calls == 1
    assert session.request_calls == 0
    assert session.close_calls == 1


@pytest.mark.parametrize("failure_stage", ["setter", "reread-getter"])
@pytest.mark.parametrize(
    ("error_type", "error_args"),
    [(KeyboardInterrupt, ("stop",)), (SystemExit, (7,))],
    ids=["keyboard-interrupt", "system-exit"],
)
def test_transport_preserves_control_flow_during_pin_update_and_closes_session(
    failure_stage: str,
    error_type: type[BaseException],
    error_args: tuple[object, ...],
) -> None:
    control_error = error_type(*error_args)
    if failure_stage == "setter":
        session = _HostileCurlOptionsSession(setter_error=control_error)
    else:
        session = _HostileCurlOptionsSession(getter_errors={2: control_error})
    session.close_error = LookupError("session cleanup failure")

    with pytest.raises(error_type) as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert exc_info.value is control_error
    assert session.request_calls == 0
    assert session.close_calls == 1


def test_request_error_survives_session_cleanup_failure() -> None:
    primary_error = RuntimeError("request primary")
    cleanup_error = LookupError("session cleanup")

    class RequestFailingSession(_RecordingSession):
        def request(self, *_args, **_kwargs):
            raise primary_error

    session = RequestFailingSession(deque())
    session.close_error = cleanup_error

    with pytest.raises(PinnedTransportNetworkError, match="public request failed") as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert exc_info.value.__cause__ is primary_error
    assert session.close_calls == 1


def test_resolver_error_survives_session_cleanup_failure_after_redirect() -> None:
    primary_error = DomainPolicyViolation("resolver primary")

    class SecondHopFailingPolicy(_CapturingPolicy):
        def resolve_public_addresses(self, url: str) -> tuple[str, ...]:
            if self.checked_urls:
                raise primary_error
            return super().resolve_public_addresses(url)

    first_response = _FakeResponse(
        302,
        "https://one.example:443/a",
        {"Location": "/b"},
    )
    session = _RecordingSession(deque([first_response]))
    session.close_error = LookupError("session cleanup")

    with pytest.raises(DomainPolicyViolation, match="resolver primary") as exc_info:
        PinnedTransport(
            policy=SecondHopFailingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert exc_info.value is primary_error
    assert first_response.close_calls == 1
    assert session.close_calls == 1


@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "streaming"])
@pytest.mark.parametrize(
    ("cleanup_type", "cleanup_args"),
    [(KeyboardInterrupt, ("stop",)), (SystemExit, (7,))],
    ids=["keyboard-interrupt-cleanup", "system-exit-cleanup"],
)
def test_policy_primary_survives_cleanup_control_flow_with_safe_note(
    streaming: bool,
    cleanup_type: type[BaseException],
    cleanup_args: tuple[object, ...],
) -> None:
    primary_error = DomainPolicyViolation("resolver primary")

    class SecondHopFailingPolicy(_CapturingPolicy):
        def resolve_public_addresses(self, url: str) -> tuple[str, ...]:
            if self.checked_urls:
                raise primary_error
            return super().resolve_public_addresses(url)

    first_response = _FakeResponse(
        302,
        "https://one.example:443/a",
        {"Location": "/b"},
    )
    session_type = _StreamingCallbackSession if streaming else _RecordingSession
    session = session_type(deque([first_response]))
    session.close_error = cleanup_type(*cleanup_args)
    transport = PinnedTransport(
        policy=SecondHopFailingPolicy(),
        session_factory=lambda: session,
        max_response_bytes=16,
    )

    with pytest.raises(DomainPolicyViolation) as exc_info:
        if streaming:
            transport.request_to_sink(
                "GET",
                "https://one.example/a",
                headers={},
                sink=lambda _chunk: None,
                max_total_bytes=16,
            )
        else:
            transport.request("GET", "https://one.example/a", headers={})

    assert exc_info.value is primary_error
    assert first_response.close_calls == 1
    assert session.close_calls == 1
    assert any(
        "session" in note and cleanup_type.__name__ in note
        for note in primary_error.__notes__
    )


def test_size_limit_error_survives_cleanup_failures_and_attempts_both_closes() -> None:
    response = _FakeResponse(
        200,
        "https://one.example:443/a",
        {},
        b"12345",
        close_error=LookupError("response cleanup"),
    )
    session = _RecordingSession(deque([response]))
    session.close_error = RuntimeError("session cleanup")

    with pytest.raises(DomainPolicyViolation, match="size limit") as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=4,
        ).request("GET", "https://one.example/a", headers={})

    assert response.close_calls == 1
    assert session.close_calls == 1
    assert any("response" in note and "LookupError" in note for note in exc_info.value.__notes__)
    assert any("session" in note and "RuntimeError" in note for note in exc_info.value.__notes__)


def test_cleanup_failure_is_visible_without_primary_error_and_attempts_both_closes() -> (
    None
):
    response_error = LookupError("response cleanup")
    response = _FakeResponse(
        200,
        "https://one.example:443/a",
        {},
        b"ok",
        close_error=response_error,
    )
    session = _RecordingSession(deque([response]))
    session.close_error = RuntimeError("session cleanup")

    with pytest.raises(
        PinnedTransportNetworkError,
        match="public transport cleanup failed",
    ) as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
        ).request("GET", "https://one.example/a", headers={})

    assert exc_info.value.__cause__ is response_error
    assert response.close_calls == 1
    assert session.close_calls == 1


@pytest.mark.parametrize(
    "control_error",
    [KeyboardInterrupt("stop"), SystemExit(7)],
    ids=["keyboard-interrupt", "system-exit"],
)
@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "streaming"])
def test_cleanup_prefers_later_control_flow_over_earlier_ordinary_error(
    control_error: BaseException,
    streaming: bool,
) -> None:
    response = _FakeResponse(
        200,
        "https://one.example:443/file",
        {},
        b"ok",
        close_error=OSError("ordinary response cleanup"),
    )
    session_type = _StreamingCallbackSession if streaming else _RecordingSession
    session = session_type(deque([response]))
    session.close_error = control_error
    transport = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: session,
        max_response_bytes=16,
    )

    with pytest.raises(type(control_error)) as exc_info:
        if streaming:
            transport.request_to_sink(
                "GET",
                "https://one.example/file",
                headers={},
                sink=lambda _chunk: None,
                max_total_bytes=16,
            )
        else:
            transport.request("GET", "https://one.example/file", headers={})

    assert exc_info.value is control_error
    assert response.close_calls == 1
    assert session.close_calls == 1


@pytest.mark.parametrize(
    "control_error",
    [KeyboardInterrupt("stop"), SystemExit(7)],
    ids=["keyboard-interrupt", "system-exit"],
)
@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "streaming"])
def test_redirect_cleanup_prefers_later_control_flow_over_response_close_error(
    control_error: BaseException,
    streaming: bool,
) -> None:
    response = _FakeResponse(
        302,
        "https://one.example:443/start",
        {"Location": "/final"},
        close_error=OSError("ordinary redirect response cleanup"),
    )
    session_type = _StreamingCallbackSession if streaming else _RecordingSession
    session = session_type(deque([response]))
    session.close_error = control_error
    transport = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: session,
        max_response_bytes=16,
    )

    with pytest.raises(type(control_error)) as exc_info:
        if streaming:
            transport.request_to_sink(
                "GET",
                "https://one.example/start",
                headers={},
                sink=lambda _chunk: None,
                max_total_bytes=16,
            )
        else:
            transport.request("GET", "https://one.example/start", headers={})

    assert exc_info.value is control_error
    assert response.close_calls == 1
    assert session.close_calls == 1


def test_parallel_pinned_requests_keep_distinct_handles_and_resolve_maps() -> None:
    barrier = Barrier(2)
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(200, "https://one.example:443/a", {}, b"one"),
            _FakeResponse(200, "https://two.example:443/b", {}, b"two"),
        ],
        barrier=barrier,
    )
    transport = PinnedTransport(policy=_CapturingPolicy(), session_factory=factory)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(
                transport.request, "GET", "https://one.example/a", headers={}
            ),
            executor.submit(
                transport.request, "GET", "https://two.example/b", headers={}
            ),
        ]
        assert {future.result().body for future in results} == {b"one", b"two"}

    assert len(factory.sessions) == 2
    assert factory.sessions[0] is not factory.sessions[1]
    resolve_maps = {
        session.calls[0]["curl_options"][CurlOpt.RESOLVE][0]
        for session in factory.sessions
    }
    assert len(resolve_maps) == 2
    assert all(session.closed for session in factory.sessions)


def test_pinned_transport_aborts_when_streamed_response_exceeds_bound() -> None:
    class CallbackSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            response = super().request(method, url, **kwargs)
            kwargs["content_callback"](response.content)
            return response

    factory = _RecordingSessionFactory(
        [_FakeResponse(200, "https://one.example:443/a", {}, b"12345")],
        session_type=CallbackSession,
    )

    with pytest.raises(DomainPolicyViolation, match="size limit"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=factory,
            max_response_bytes=4,
        ).request("GET", "https://one.example/a", headers={})

    assert factory.sessions[0].closed


def test_transport_rejects_ignored_callback_overflow_and_closes_resources() -> None:
    response = _FakeResponse(
        200,
        "https://one.example:443/a",
        {},
        b"12",
    )

    class IgnoringCallbackReturnSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            returned_response = super().request(method, url, **kwargs)
            kwargs["content_callback"](b"12345")
            return returned_response

    session = IgnoringCallbackReturnSession(deque([response]))

    with pytest.raises(DomainPolicyViolation, match="size limit"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=4,
        ).request("GET", "https://one.example/a", headers={})

    assert response.close_calls == 1
    assert session.close_calls == 1


def test_transport_rejects_larger_raw_body_hidden_by_partial_callback() -> None:
    response = _FakeResponse(
        200,
        "https://one.example:443/a",
        {},
        b"12345",
    )

    class PartialCallbackSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            returned_response = super().request(method, url, **kwargs)
            kwargs["content_callback"](b"12")
            return returned_response

    session = PartialCallbackSession(deque([response]))

    with pytest.raises(DomainPolicyViolation, match="size limit"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=4,
        ).request("GET", "https://one.example/a", headers={})

    assert response.close_calls == 1
    assert session.close_calls == 1


def test_transport_rejects_inconsistent_callback_and_raw_body_within_budget() -> None:
    response = _FakeResponse(
        200,
        "https://one.example:443/a",
        {},
        b"34",
    )

    class InconsistentCallbackSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            returned_response = super().request(method, url, **kwargs)
            kwargs["content_callback"](b"12")
            return returned_response

    session = InconsistentCallbackSession(deque([response]))

    with pytest.raises(DomainPolicyViolation, match="inconsistent response body"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=4,
        ).request("GET", "https://one.example/a", headers={})

    assert response.close_calls == 1
    assert session.close_calls == 1


def test_transport_enforces_raw_body_limit_before_following_redirect() -> None:
    redirect_response = _FakeResponse(
        302,
        "https://one.example:443/a",
        {"Location": "/next"},
        b"12345",
    )
    final_response = _FakeResponse(
        200,
        "https://one.example:443/next",
        {},
        b"ok",
    )
    session = _RecordingSession(deque([redirect_response, final_response]))

    with pytest.raises(DomainPolicyViolation, match="size limit"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=4,
        ).request("GET", "https://one.example/a", headers={})

    assert len(session.calls) == 1
    assert redirect_response.close_calls == 1
    assert final_response.close_calls == 0
    assert session.close_calls == 1


def test_real_curl_response_overflow_is_translated_to_policy_violation(
    monkeypatch,
) -> None:
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "64")
            self.end_headers()
            self.wfile.write(b"x" * 64)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class LoopbackHarnessPolicy:
        @staticmethod
        def resolve_public_addresses(_url: str) -> tuple[str, ...]:
            return ("127.0.0.1",)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        pinned_transport_module,
        "curl_resolve_options",
        lambda *_args, **_kwargs: {CurlOpt.PROXY: ""},
    )
    try:
        with pytest.raises(DomainPolicyViolation, match="size limit"):
            PinnedTransport(
                policy=LoopbackHarnessPolicy(),
                timeout=2,
                max_response_bytes=4,
            ).request(
                "GET",
                f"http://127.0.0.1:{server.server_port}/overflow",
                headers={},
            )
        assert hits == ["/overflow"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_curl_streams_bounded_response_directly_to_sink(monkeypatch) -> None:
    payload = b"installer-chunk-" * 4096

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class LoopbackHarnessPolicy:
        @staticmethod
        def resolve_public_addresses(_url: str) -> tuple[str, ...]:
            return ("127.0.0.1",)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        pinned_transport_module,
        "curl_resolve_options",
        lambda *_args, **_kwargs: {CurlOpt.PROXY: ""},
    )
    output = bytearray()
    response_budget = len(payload) + 4096
    events: list[str] = []

    def validate_response(status: int, headers: dict[str, str]) -> None:
        events.append("headers")
        assert status == 200
        assert int(headers["Content-Length"]) == len(payload)

    def consume(chunk: bytes) -> None:
        assert events == ["headers"]
        output.extend(chunk)
    try:
        result = PinnedTransport(
            policy=LoopbackHarnessPolicy(),
            timeout=2,
            max_response_bytes=response_budget,
        ).request_to_sink(
            "GET",
            f"http://127.0.0.1:{server.server_port}/installer",
            headers={},
            sink=consume,
            response_validator=validate_response,
            accepted_statuses={200},
            max_total_bytes=response_budget,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert output == payload
    assert events == ["headers"]
    assert result.bytes_written == len(payload)
    assert len(payload) < result.total_response_bytes <= response_budget


class _StreamingCallbackSession(_RecordingSession):
    def request(self, method: str, url: str, **kwargs):
        assert kwargs.get("stream") is not True
        response = super().request(method, url, **kwargs)
        self.curl = SimpleNamespace(
            getinfo=lambda _info: response.status_code,
        )
        kwargs["response_start_callback"](response.status_code, response.headers)
        callback = kwargs["content_callback"]
        for offset in range(0, len(response.content), 3):
            chunk = response.content[offset : offset + 3]
            if callback(chunk) != len(chunk):
                raise OSError("curl write callback aborted")
        return response


class _RawHeaderStreamingSession(_RecordingSession):
    def request(self, method: str, url: str, **kwargs):
        response = super().request(method, url, **kwargs)
        self.curl = SimpleNamespace(getinfo=lambda _info: response.status_code)
        raw_lines = [f"HTTP/1.1 {response.status_code} Test\r\n".encode("ascii")]
        raw_lines.extend(
            f"{name}: {value}\r\n".encode("latin-1")
            for name, value in response.headers.items()
        )
        raw_lines.append(b"\r\n")
        for line in raw_lines:
            kwargs["header_callback"](line)
        kwargs["response_start_callback"](response.status_code, response.headers)
        callback = kwargs["content_callback"]
        for offset in range(0, len(response.content), 3):
            chunk = response.content[offset : offset + 3]
            if callback(chunk) != len(chunk):
                raise OSError("curl write callback aborted")
        return response


class _BodyBeforeHeadersSession(_RecordingSession):
    def request(self, method: str, url: str, **kwargs):
        response = super().request(method, url, **kwargs)
        self.curl = SimpleNamespace(getinfo=lambda _info: response.status_code)
        kwargs["content_callback"](response.content)
        return response


def test_streaming_transport_writes_bounded_body_without_buffering_again() -> None:
    response = _FakeResponse(200, "https://one.example:443/file", {}, b"payload")
    factory = _RecordingSessionFactory(
        [response],
        session_type=_StreamingCallbackSession,
    )
    output = bytearray()

    result = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=factory,
        max_response_bytes=16,
    ).request_to_sink(
        "GET",
        "https://one.example/file",
        headers={},
        sink=output.extend,
        accepted_statuses={200},
        max_total_bytes=8,
    )

    assert output == b"payload"
    assert result.status_code == 200
    assert result.bytes_written == len(output)
    assert result.total_response_bytes == len(output)
    options = factory.sessions[0].calls[0]["curl_options"]
    assert options[CurlOpt.PROXY] == ""
    assert options[CurlOpt.FRESH_CONNECT] == 1
    assert options[CurlOpt.FORBID_REUSE] == 1
    assert options[CurlOpt.RESOLVE] == ["one.example:443:1.1.1.1"]


def test_streaming_transport_rejects_body_before_header_validation() -> None:
    response = _FakeResponse(200, "https://one.example:443/file", {}, b"payload")
    output = bytearray()

    with pytest.raises(DomainPolicyViolation, match="headers were not validated before body"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: _BodyBeforeHeadersSession(deque([response])),
            max_response_bytes=16,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=output.extend,
            response_validator=lambda _status, _headers: None,
            accepted_statuses={200},
            max_total_bytes=16,
        )

    assert output == b""


def test_streaming_transport_discards_redirect_body_and_strips_cross_origin_secrets() -> None:
    policy = _CapturingPolicy()
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(
                302,
                "https://one.example:443/file",
                {"Location": "https://two.example/final"},
                b"redirect-body",
            ),
            _FakeResponse(200, "https://two.example:443/final", {}, b"installer"),
        ],
        session_type=_StreamingCallbackSession,
    )
    output = bytearray()

    result = PinnedTransport(
        policy=policy,
        session_factory=factory,
        max_response_bytes=64,
    ).request_to_sink(
        "GET",
        "https://one.example/file",
        headers={"Authorization": "Bearer secret", "Cookie": "session=secret", "X-Test": "ok"},
        sink=output.extend,
        accepted_statuses={200},
        max_total_bytes=64,
    )

    assert output == b"installer"
    assert result.redirect_chain == (
        "https://one.example:443/file",
        "https://two.example:443/final",
    )
    assert policy.checked_urls == list(result.redirect_chain)
    second_headers = factory.sessions[1].calls[0]["headers"]
    assert "Authorization" not in second_headers
    assert "Cookie" not in second_headers
    assert second_headers["X-Test"] == "ok"


def test_streaming_total_budget_counts_raw_headers_and_body_across_redirects() -> None:
    first = _FakeResponse(
        302,
        "https://one.example:443/start",
        {"lOcAtIoN": "https://two.example/final", "X-Hop": "one"},
        b"abc",
    )
    second = _FakeResponse(
        200,
        "https://two.example:443/final",
        {"X-Hop": "two"},
        b"done",
    )
    expected_total = sum(
        len(line)
        for line in (
            b"HTTP/1.1 302 Test\r\n",
            b"lOcAtIoN: https://two.example/final\r\n",
            b"X-Hop: one\r\n",
            b"\r\n",
            b"abc",
            b"HTTP/1.1 200 Test\r\n",
            b"X-Hop: two\r\n",
            b"\r\n",
            b"done",
        )
    )
    factory = _RecordingSessionFactory(
        [first, second],
        session_type=_RawHeaderStreamingSession,
    )
    output = bytearray()

    result = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=factory,
        max_response_bytes=expected_total,
    ).request_to_sink(
        "GET",
        "https://one.example/start",
        headers={},
        sink=output.extend,
        accepted_statuses={200},
        max_total_bytes=expected_total,
    )

    assert output == b"done"
    assert result.total_response_bytes == expected_total


def test_streaming_total_budget_rejects_headers_and_body_one_byte_over_limit() -> None:
    response = _FakeResponse(
        200,
        "https://one.example:443/file",
        {"X-Budget": "header"},
        b"body",
    )
    expected_total = sum(
        map(
            len,
            (
                b"HTTP/1.1 200 Test\r\n",
                b"X-Budget: header\r\n",
                b"\r\n",
                b"body",
            ),
        )
    )

    with pytest.raises(DomainPolicyViolation, match="size limit"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: _RawHeaderStreamingSession(deque([response])),
            max_response_bytes=expected_total,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=lambda _chunk: None,
            accepted_statuses={200},
            max_total_bytes=expected_total - 1,
        )


def test_streaming_transport_aborts_before_sink_when_total_body_limit_is_exceeded() -> None:
    factory = _RecordingSessionFactory(
        [_FakeResponse(200, "https://one.example:443/file", {}, b"12345")],
        session_type=_StreamingCallbackSession,
    )
    output = bytearray()

    with pytest.raises(DomainPolicyViolation, match="size limit"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=factory,
            max_response_bytes=8,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=output.extend,
            accepted_statuses={200},
            max_total_bytes=4,
        )

    assert output == b"123"
    assert factory.sessions[0].closed


def test_streaming_transport_preserves_sink_baseexception_over_cleanup_failures() -> None:
    class SinkFailure(BaseException):
        pass

    primary = SinkFailure("sink failed")
    response = _FakeResponse(
        200,
        "https://one.example:443/file",
        {},
        b"payload",
        close_error=SystemExit("response cleanup"),
    )
    class ReturningAfterCallbackAbortSession(_StreamingCallbackSession):
        def request(self, method: str, url: str, **kwargs):
            response = _RecordingSession.request(self, method, url, **kwargs)
            self.curl = SimpleNamespace(getinfo=lambda _info: response.status_code)
            kwargs["response_start_callback"](response.status_code, response.headers)
            kwargs["content_callback"](response.content)
            return response

    session = ReturningAfterCallbackAbortSession(deque([response]))
    session.close_error = KeyboardInterrupt("session cleanup")

    def sink(_chunk: bytes) -> None:
        raise primary

    with pytest.raises(SinkFailure) as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=16,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=sink,
            accepted_statuses={200},
            max_total_bytes=16,
        )

    assert exc_info.value is primary
    assert response.close_calls == 1
    assert session.close_calls == 1
    assert any("response" in note and "SystemExit" in note for note in primary.__notes__)
    assert any("session" in note and "KeyboardInterrupt" in note for note in primary.__notes__)


def test_streaming_transport_never_reads_materialized_response_content() -> None:
    class NoContentResponse:
        status_code = 200
        url = "https://one.example:443/file"
        headers: dict[str, str] = {}

        @property
        def content(self):
            raise AssertionError("streaming transport must not materialize response.content")

        def close(self) -> None:
            return None

    class NoContentSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            self.calls.append({"method": method, "url": url, "curl_options": dict(self.curl_options)})
            self.curl = SimpleNamespace(getinfo=lambda _info: 200)
            kwargs["response_start_callback"](200, {})
            assert kwargs["content_callback"](b"safe") == 4
            return NoContentResponse()

    output = bytearray()
    result = PinnedTransport(
        policy=_CapturingPolicy(),
        session_factory=lambda: NoContentSession(deque()),
        max_response_bytes=8,
    ).request_to_sink(
        "GET",
        "https://one.example/file",
        headers={},
        sink=output.extend,
        accepted_statuses={200},
        max_total_bytes=8,
    )

    assert output == b"safe"
    assert result.bytes_written == 4


def test_streaming_transport_normalizes_session_network_errors() -> None:
    class FailingSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            del method, url, kwargs
            raise OSError("connection reset")

    with pytest.raises(PinnedTransportNetworkError, match="public request failed"):
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: FailingSession(deque()),
            max_response_bytes=8,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=lambda _chunk: None,
        )


def test_buffered_transport_normalizes_session_network_errors() -> None:
    class CurlLikeFailure(Exception):
        pass

    primary = CurlLikeFailure("curl connection reset")

    class FailingSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs):
            del method, url, kwargs
            raise primary

    with pytest.raises(PinnedTransportNetworkError, match="public request failed") as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: FailingSession(deque()),
            max_response_bytes=8,
        ).request(
            "GET",
            "https://one.example/file",
            headers={},
        )

    assert exc_info.value.__cause__ is primary


def test_buffered_transport_normalizes_success_cleanup_errors() -> None:
    response = _FakeResponse(200, "https://one.example:443/file", {}, b"safe")
    session = _RecordingSession(deque([response]))
    session.close_error = OSError("curl close failed")

    with pytest.raises(PinnedTransportNetworkError, match="transport cleanup") as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=8,
        ).request("GET", "https://one.example/file", headers={})

    assert isinstance(exc_info.value.__cause__, OSError)
    assert response.close_calls == 1
    assert session.close_calls == 1


def test_buffered_transport_normalizes_same_origin_redirect_response_cleanup() -> None:
    redirect = _FakeResponse(
        302,
        "https://one.example:443/file",
        {"Location": "/final"},
        close_error=OSError("redirect close failed"),
    )
    session = _RecordingSession(deque([redirect]))

    with pytest.raises(
        PinnedTransportNetworkError,
        match="redirect response cleanup",
    ) as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=8,
        ).request("GET", "https://one.example/file", headers={})

    assert isinstance(exc_info.value.__cause__, OSError)
    assert redirect.close_calls == 1
    assert session.close_calls == 1


def test_buffered_transport_normalizes_cross_origin_old_session_cleanup() -> None:
    responses = deque(
        [
            _FakeResponse(
                302,
                "https://one.example:443/file",
                {"Location": "https://two.example/final"},
            ),
            _FakeResponse(200, "https://two.example:443/final", {}, b"safe"),
        ]
    )
    first = _RecordingSession(responses)
    first.close_error = OSError("old session close failed")
    second = _RecordingSession(responses)
    sessions = iter((first, second))

    with pytest.raises(
        PinnedTransportNetworkError,
        match="redirect session cleanup",
    ) as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: next(sessions),
            max_response_bytes=8,
        ).request("GET", "https://one.example/file", headers={})

    assert isinstance(exc_info.value.__cause__, OSError)
    assert first.close_calls == 1
    assert second.close_calls == 0


def test_streaming_transport_normalizes_success_cleanup_errors() -> None:
    response = _FakeResponse(200, "https://one.example:443/file", {}, b"safe")
    session = _StreamingCallbackSession(deque([response]))
    session.close_error = OSError("curl close failed")

    with pytest.raises(PinnedTransportNetworkError, match="transport cleanup") as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=8,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=lambda _chunk: None,
        )

    assert isinstance(exc_info.value.__cause__, OSError)
    assert response.close_calls == 1
    assert session.close_calls == 1


def test_streaming_transport_normalizes_redirect_cleanup_errors() -> None:
    response = _FakeResponse(
        302,
        "https://one.example:443/file",
        {"Location": "/final"},
        b"redirect",
        close_error=OSError("redirect close failed"),
    )
    session = _StreamingCallbackSession(deque([response]))

    with pytest.raises(PinnedTransportNetworkError, match="redirect response cleanup") as exc_info:
        PinnedTransport(
            policy=_CapturingPolicy(),
            session_factory=lambda: session,
            max_response_bytes=16,
        ).request_to_sink(
            "GET",
            "https://one.example/file",
            headers={},
            sink=lambda _chunk: None,
        )

    assert isinstance(exc_info.value.__cause__, OSError)
    assert response.close_calls == 1
    assert session.close_calls == 1


def test_media_subprocess_environment_drops_proxy_and_cookie_variables(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:1080")
    monkeypatch.setenv("COOKIE", "secret")
    monkeypatch.setenv("AUTHORIZATION", "Bearer secret")

    env = isolated_media_subprocess_env()

    assert env["SystemRoot"] == r"C:\Windows"
    assert env["PATH"] == r"C:\Windows\System32"
    assert "HTTPS_PROXY" not in env
    assert "all_proxy" not in env
    assert "COOKIE" not in env
    assert "AUTHORIZATION" not in env


def test_media_subprocess_environment_rejects_sensitive_explicit_extra() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        isolated_media_subprocess_env(extra={"HTTPS_PROXY": "http://127.0.0.1:8888"})
