from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from curl_cffi.const import CurlOpt

from shared.network import pinned_transport as pinned_transport_module
from shared.network.pinned_transport import (
    PinnedTransport,
    canonicalize_host,
    canonicalize_request_target,
    curl_resolve_options,
)
from shared.runtime_options import DomainPolicyViolation
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


@dataclass
class _FakeResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    content: bytes = b""
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class _RecordingSession:
    def __init__(self, responses: deque[_FakeResponse], barrier: Barrier | None = None) -> None:
        self._responses = responses
        self._barrier = barrier
        self.curl_options = {CurlOpt.NOSIGNAL: 1}
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs):
        if self._barrier is not None:
            self._barrier.wait(timeout=2.0)
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(kwargs.get("headers") or {}),
                "curl_options": dict(self.curl_options),
            }
        )
        return self._responses.popleft()

    def close(self) -> None:
        self.closed = True


class _CookieJarSession(_RecordingSession):
    def __init__(self, responses: deque[_FakeResponse], barrier: Barrier | None = None) -> None:
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
    "host",
    ["example..com", ".example.com", "example.com..", "example.com...", ""],
)
def test_canonicalize_host_rejects_empty_labels_and_multiple_terminal_dots(host: str) -> None:
    with pytest.raises(DomainPolicyViolation, match="host"):
        canonicalize_host(host)


def test_canonicalize_host_accepts_exactly_one_terminal_dot_and_idna() -> None:
    assert canonicalize_host("BÜCHER.Example.") == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "host",
    ["127.1", "0177.0.0.1", "0x7f000001", "0x7f.0.0.1", "2130706433"],
)
def test_canonicalize_host_rejects_legacy_numeric_ipv4_spellings(host: str) -> None:
    with pytest.raises(DomainPolicyViolation, match="host"):
        canonicalize_host(host)


@pytest.mark.parametrize("url", ["https://example.com:0/a", "https://example.com:/a"])
def test_canonicalize_request_target_rejects_zero_and_empty_explicit_ports(url: str) -> None:
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


def test_redirect_hops_share_one_canonical_target_without_system_dns(monkeypatch) -> None:
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
        call["curl_options"][CurlOpt.RESOLVE][0].split(":", 2)[:2]
        for call in calls
    ] == [["xn--bcher-kva.example", "443"], ["cdn.example", "8443"]]
    assert all(call["curl_options"][CurlOpt.PROXY] == "" for call in calls)
    assert all(session.closed for session in factory.sessions)
    system_dns.assert_not_called()


def test_cross_origin_redirect_drops_credentials_before_next_request() -> None:
    factory = _RecordingSessionFactory(
        [
            _FakeResponse(302, "https://one.example:443/a", {"Location": "https://two.example/b"}),
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
        "Proxy-Authorization": "Basic secret",
        "X-Public": "kept",
    }
    assert factory.sessions[1].calls[0]["headers"] == {"X-Public": "kept"}


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
            executor.submit(transport.request, "GET", "https://one.example/a", headers={}),
            executor.submit(transport.request, "GET", "https://two.example/b", headers={}),
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


def test_real_curl_response_overflow_is_translated_to_policy_violation(monkeypatch) -> None:
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


def test_media_subprocess_environment_drops_proxy_and_cookie_variables(monkeypatch) -> None:
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
