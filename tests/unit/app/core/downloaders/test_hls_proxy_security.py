from __future__ import annotations

import io
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pytest

from app.core.downloaders import hls_proxy as subject
from app.exceptions import ExternalToolError
from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation


ROOT_URL = "https://media.example/master.m3u8"
CANONICAL_ROOT_URL = "https://media.example:443/master.m3u8"
TASK_A = "task-a"
TASK_B = "task-b"
SECRET_A = b"a" * 32
SECRET_B = b"b" * 32


@dataclass
class _MutableClock:
    value: int

    def __call__(self) -> int:
        return self.value


class _RecordingDownloader:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.playlists: dict[str, bytes] = {}
        self.response: _FakeResponse | None = None
        self.fetch_result: tuple | None = None

    @staticmethod
    def _headers_for_hls_proxy_upstream(
        _upstream_url: str,
        headers: dict[str, str],
    ) -> dict[str, str]:
        # Credential scoping belongs to the proxy capability boundary. This
        # fake intentionally preserves its input so a missing filter is visible.
        return dict(headers)

    def _hls_proxy_fetch_upstream(
        self,
        upstream_url: str,
        headers: dict[str, str],
        _upstream_proxy: str | None,
        *,
        domain_policy=None,
    ) -> tuple[int, str, bytes, str, tuple[str, ...]]:
        del domain_policy
        self.requests.append((upstream_url, dict(headers)))
        if self.fetch_result is not None:
            return self.fetch_result
        body = self.playlists.get(upstream_url, b"segment")
        content_type = "application/vnd.apple.mpegurl" if upstream_url in self.playlists else "video/mp2t"
        return 200, content_type, body, upstream_url, (upstream_url,)

    def _hls_proxy_open_upstream(
        self,
        upstream_url: str,
        headers: dict[str, str],
        _upstream_proxy: str | None,
        *,
        domain_policy=None,
    ):
        del domain_policy
        self.requests.append((upstream_url, dict(headers)))
        return self.response or _FakeResponse(url=upstream_url)


class _FakeResponse:
    def __init__(self, *, url: str, redirect_chain: tuple[str, ...] = ()) -> None:
        self.url = url
        self.redirect_chain = redirect_chain
        self.status_code = 200
        self.headers = {"Content-Type": "video/mp2t", "Content-Length": "7"}
        self.content = b"segment"
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeHandler:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.status: int | None = None
        self.response_headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers.append((name, value))

    def end_headers(self) -> None:
        return


def _new_proxy(
    *,
    task_id: str = TASK_A,
    secret: bytes = SECRET_A,
    expires_at: int = 1_900,
    clock: _MutableClock | None = None,
    headers: dict[str, str] | None = None,
    domain_policy: DomainPolicyEngine | None = None,
) -> tuple[subject._LocalHlsProxy, _RecordingDownloader, _MutableClock]:
    capability_type = getattr(subject, "HlsCapability", None)
    assert capability_type is not None, "Task 2 must define HlsCapability"
    active_clock = clock or _MutableClock(1_000)
    capability = capability_type(task_id=task_id, secret=secret, expires_at=expires_at)
    downloader = _RecordingDownloader()
    try:
        proxy = subject._LocalHlsProxy(
            downloader,
            ROOT_URL,
            headers or {},
            None,
            capability=capability,
            clock=active_clock,
            domain_policy=domain_policy,
        )
    except TypeError as exc:
        pytest.fail(f"_LocalHlsProxy must accept capability and clock injection: {exc}")
    proxy.base_url = "http://127.0.0.1:31337"
    return proxy, downloader, active_clock


def _new_basic_proxy(
    *,
    headers: dict[str, str] | None = None,
) -> tuple[subject._LocalHlsProxy, _RecordingDownloader]:
    downloader = _RecordingDownloader()
    proxy = subject._LocalHlsProxy(downloader, ROOT_URL, headers or {}, None)
    proxy.base_url = "http://127.0.0.1:31337"
    return proxy, downloader


def _path(local_url: str) -> str:
    parts = urlsplit(local_url)
    return urlunsplit(("", "", parts.path, parts.query, ""))


def _required_method(owner, name: str):
    method = getattr(owner, name, None)
    assert callable(method), f"Task 2 must define {type(owner).__name__}.{name}()"
    return method


def _tamper_query(path: str, key: str) -> str:
    parts = urlsplit(path)
    query = parse_qs(parts.query, keep_blank_values=True)
    original = query[key][0]
    query[key] = [("x" if not original.startswith("x") else "y") + original[1:]]
    return urlunsplit(("", "", parts.path, urlencode(query, doseq=True), ""))


def _replace_query(path: str, key: str, value: str) -> str:
    parts = urlsplit(path)
    query = parse_qs(parts.query, keep_blank_values=True)
    query[key] = [value]
    return urlunsplit(("", "", parts.path, urlencode(query, doseq=True), ""))


def _remove_query(path: str, key: str) -> str:
    parts = urlsplit(path)
    query = parse_qs(parts.query, keep_blank_values=True)
    query.pop(key, None)
    return urlunsplit(("", "", parts.path, urlencode(query, doseq=True), ""))


def _public_resolver(host: str, port: int | None, **_kwargs):
    del host
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 443))]


def _record_playlist_fail_closed(proxy: subject._LocalHlsProxy, playlist: str) -> None:
    record_playlist = _required_method(proxy, "record_playlist")
    with pytest.raises((ExternalToolError, DomainPolicyViolation)):
        record_playlist(ROOT_URL, playlist)


def test_hls_proxy_rejects_unsigned_expired_and_unlisted_urls() -> None:
    proxy, _downloader, clock = _new_proxy(expires_at=1_100)
    verify_path = _required_method(proxy, "verify_path")

    assert verify_path("/hls?u=aHR0cHM6Ly9tZWRpYS5leGFtcGxlL21hc3Rlci5tM3U4") is None

    signed_root = _path(proxy.local_url_for(ROOT_URL))
    clock.value = 1_100
    assert verify_path(signed_root) is None

    clock.value = 1_101
    assert verify_path(signed_root) is None

    clock.value = 1_000
    unlisted = _path(proxy.local_url_for("https://media.example/not-in-playlist.ts"))
    assert verify_path(unlisted) is None


def test_hls_capability_is_task_local_and_tamper_evident() -> None:
    proxy_a, _downloader_a, _clock_a = _new_proxy(task_id=TASK_A, secret=SECRET_A)
    proxy_b, _downloader_b, _clock_b = _new_proxy(task_id=TASK_B, secret=SECRET_B)
    verify_a = _required_method(proxy_a, "verify_path")
    verify_b = _required_method(proxy_b, "verify_path")

    signed_path = _path(proxy_a.local_url_for(ROOT_URL))
    query = parse_qs(urlsplit(signed_path).query)
    assert set(query) == {"task", "exp", "u", "sig"}
    assert verify_a(signed_path) == CANONICAL_ROOT_URL
    assert verify_b(signed_path) is None
    assert verify_a(_tamper_query(signed_path, "u")) is None
    assert verify_a(_tamper_query(signed_path, "sig")) is None


@pytest.mark.parametrize("key", ["task", "exp", "u", "sig"])
def test_hls_capability_rejects_duplicate_query_keys(key: str) -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    value = parse_qs(urlsplit(signed_path).query, keep_blank_values=True)[key][0]

    assert verify_path(f"{signed_path}&{urlencode({key: value})}") is None


def test_hls_capability_rejects_noncanonical_and_damaged_base64() -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    encoded_url = parse_qs(urlsplit(signed_path).query, keep_blank_values=True)["u"][0]

    assert verify_path(_replace_query(signed_path, "u", encoded_url.rstrip("=") + "===")) is None
    assert verify_path(_replace_query(signed_path, "u", "%%%not-base64%%%")) is None


@pytest.mark.parametrize("key", ["task", "exp", "u", "sig"])
def test_hls_capability_rejects_missing_and_empty_required_query_values(key: str) -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))

    assert verify_path(_remove_query(signed_path, key)) is None
    assert verify_path(_replace_query(signed_path, key, "")) is None


def test_hls_capability_rejects_wrong_path_unknown_parameters_and_oversized_url_token() -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    query = urlsplit(signed_path).query

    assert verify_path("") is None
    assert verify_path("/") is None
    assert verify_path(f"/not-hls?{query}") is None
    assert verify_path(f"{signed_path}&unknown=1") is None
    assert verify_path(_replace_query(signed_path, "u", "A" * 16_385)) is None


@pytest.mark.parametrize("noncanonical_exp", ["+1900", "01900", "1900.0", " 1900"])
def test_hls_capability_rejects_noncanonical_expiry(noncanonical_exp: str) -> None:
    proxy, _downloader, _clock = _new_proxy(expires_at=1_900)
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))

    assert verify_path(_replace_query(signed_path, "exp", noncanonical_exp)) is None


def test_hls_capability_rejects_absolute_and_noncanonical_query_forms() -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    parts = urlsplit(signed_path)
    reversed_query = urlencode(list(reversed(list(parse_qs(parts.query).items()))), doseq=True)

    assert verify_path(f"http://127.0.0.1:31337{signed_path}") is None
    assert verify_path(urlunsplit(("", "", parts.path, reversed_query, ""))) is None
    assert verify_path(signed_path.replace("task=", "%74ask=", 1)) is None


def test_hls_capability_ttl_cannot_exceed_fifteen_minutes() -> None:
    capability = subject.HlsCapability(task_id=TASK_A, secret=SECRET_A, expires_at=1_901)
    with pytest.raises(subject.HlsCapabilityError, match="expiry|TTL|15"):
        subject._LocalHlsProxy(
            _RecordingDownloader(),
            ROOT_URL,
            {},
            None,
            capability=capability,
            clock=_MutableClock(1_000),
        )


def test_hls_capability_monotonic_deadline_prevents_wall_clock_rollback_extension() -> None:
    wall_clock = _MutableClock(1_000)
    monotonic_clock = _MutableClock(5_000)
    capability = subject.HlsCapability(task_id=TASK_A, secret=SECRET_A, expires_at=1_900)
    proxy = subject._LocalHlsProxy(
        _RecordingDownloader(),
        ROOT_URL,
        {},
        None,
        capability=capability,
        clock=wall_clock,
        monotonic_clock=monotonic_clock,
    )
    proxy.base_url = "http://127.0.0.1:31337"
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    wall_clock.value = 900
    monotonic_clock.value = 5_900

    assert proxy.verify_path(signed_path) is None


def test_hls_capability_task_id_is_safe_for_query_and_diagnostic_context() -> None:
    with pytest.raises(ValueError, match="task_id"):
        subject.HlsCapability(
            task_id="task\r\nX-Diagnostic-Leak: secret",
            secret=SECRET_A,
            expires_at=1_900,
        )


def test_hls_membership_contains_root_and_every_supported_playlist_uri() -> None:
    proxy, _downloader, _clock = _new_proxy()
    record_playlist = _required_method(proxy, "record_playlist")
    verify_path = _required_method(proxy, "verify_path")
    playlist = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="audio/index.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,AUDIO="audio"
variants/main.m3u8
#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"
#EXT-X-MAP:URI='init/init.mp4'
#EXTINF:4,
segments/one.ts
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=120000,URI="iframes/index.m3u8"
#EXT-X-IMAGE-STREAM-INF:BANDWIDTH=24000,URI="images/index.m3u8"
"""
    expected_members = {
        CANONICAL_ROOT_URL,
        "https://media.example:443/audio/index.m3u8",
        "https://media.example:443/variants/main.m3u8",
        "https://media.example:443/keys/key.bin",
        "https://media.example:443/init/init.mp4",
        "https://media.example:443/segments/one.ts",
        "https://media.example:443/iframes/index.m3u8",
        "https://media.example:443/images/index.m3u8",
    }

    record_playlist(ROOT_URL, playlist)

    for canonical_url in expected_members:
        input_url = canonical_url.replace("media.example:443", "media.example")
        assert verify_path(_path(proxy.local_url_for(input_url))) == canonical_url
    assert verify_path(_path(proxy.local_url_for("https://media.example/segments/two.ts"))) is None


def test_hls_playlist_rejects_mixed_quoted_and_unquoted_uri_attributes_atomically() -> None:
    proxy, _downloader, _clock = _new_proxy()
    playlist = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/index.m3u8",URI=private/index.m3u8
"""

    _record_playlist_fail_closed(proxy, playlist)

    assert proxy.members == {CANONICAL_ROOT_URL}


def test_hls_playlist_rewrites_case_insensitive_uri_attribute_without_escape() -> None:
    proxy, _downloader, _clock = _new_proxy()
    rewritten = proxy.record_playlist(
        ROOT_URL,
        '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,uri="keys/key.bin"\n',
    )

    assert 'uri="https://media.example/keys/key.bin"' not in rewritten
    assert "http://" in rewritten
    assert proxy.verify_path(_path(proxy.local_url_for("https://media.example/keys/key.bin"))) == (
        "https://media.example:443/keys/key.bin"
    )


def test_hls_capability_authorizes_resources_only_from_an_authorized_parent() -> None:
    proxy, _downloader, _clock = _new_proxy()
    authorize = _required_method(proxy, "authorize_playlist_resource")
    verify_path = _required_method(proxy, "verify_path")
    allowed_child = "https://cdn.example/segment.ts"
    blocked_child = "https://cdn.example/not-discovered.ts"

    authorize(ROOT_URL, allowed_child)
    assert verify_path(_path(proxy.local_url_for(allowed_child))) == "https://cdn.example:443/segment.ts"

    try:
        authorize("https://media.example/unlisted.m3u8", blocked_child)
    except (ExternalToolError, DomainPolicyViolation):
        # Either an explicit rejection or a no-op is acceptable; both must keep
        # the child outside the capability membership.
        pass
    assert verify_path(_path(proxy.local_url_for(blocked_child))) is None


class _NoPolicyProbeBeforeAuthorization:
    def __init__(self) -> None:
        self.checked_urls: list[str] = []

    def require_public_url(self, url: str) -> str:
        self.checked_urls.append(url)
        raise AssertionError("policy must not inspect descendants of an unauthorized member")


def test_playlist_authorization_checks_parent_membership_before_domain_policy() -> None:
    policy = _NoPolicyProbeBeforeAuthorization()
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)  # type: ignore[arg-type]

    with pytest.raises(subject.HlsCapabilityError, match="parent|authorized"):
        proxy.authorize_playlist_resource(
            "https://media.example/unlisted.m3u8",
            "https://probe.example/segment.ts",
        )

    assert policy.checked_urls == []


class _CountingPublicPolicy:
    def __init__(self) -> None:
        self.checked_urls: list[str] = []

    def require_public_url(self, url: str) -> str:
        self.checked_urls.append(url)
        return url


def test_playlist_deduplicates_resources_before_policy_checks() -> None:
    policy = _CountingPublicPolicy()
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)  # type: ignore[arg-type]
    repeated = "\n".join(["#EXTINF:4,", "segments/one.ts"] * 100)

    proxy.record_playlist(ROOT_URL, f"#EXTM3U\n{repeated}\n")

    assert policy.checked_urls == ["https://media.example:443/segments/one.ts"]


def test_playlist_capacity_rejection_happens_before_policy_checks(monkeypatch) -> None:
    policy = _CountingPublicPolicy()
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)  # type: ignore[arg-type]
    monkeypatch.setattr(subject, "_MAX_TASK_MEMBERS", 1)

    with pytest.raises(subject.HlsCapabilityError, match="member limit"):
        proxy.record_playlist(ROOT_URL, "#EXTM3U\n#EXTINF:4,\nsegments/one.ts\n")

    assert policy.checked_urls == []


def test_hls_playlist_membership_update_is_atomic_when_any_child_is_private() -> None:
    policy = DomainPolicyEngine(resolver=_public_resolver)
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)
    verify_path = _required_method(proxy, "verify_path")
    allowed_child = "https://media.example/segments/allowed.ts"
    playlist = """#EXTM3U
#EXTINF:4,
segments/allowed.ts
#EXTINF:4,
http://127.0.0.1/private.ts
"""

    _record_playlist_fail_closed(proxy, playlist)

    assert verify_path(_path(proxy.local_url_for(ROOT_URL))) == CANONICAL_ROOT_URL
    assert verify_path(_path(proxy.local_url_for(allowed_child))) is None


def test_ll_hls_part_preload_hint_and_rendition_report_are_members_and_rewritten() -> None:
    proxy, downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    playlist = """#EXTM3U
#EXT-X-PART:DURATION=0.333,URI="parts/part-1.m4s"
#EXT-X-PRELOAD-HINT:TYPE=PART,URI="parts/next.m4s"
#EXT-X-RENDITION-REPORT:URI="../alternate/live.m3u8",LAST-MSN=12,LAST-PART=3
"""
    downloader.playlists[CANONICAL_ROOT_URL] = playlist.encode("utf-8")

    status, content_type, body = proxy.fetch(ROOT_URL)

    rewritten = body.decode("utf-8")
    local_urls = re.findall(r"http://127\.0\.0\.1:31337/hls\?[^\"'\s]+", rewritten)
    resolved_targets = {verify_path(_path(local_url)) for local_url in local_urls}
    assert status == 200
    assert content_type.startswith("application/vnd.apple.mpegurl")
    assert resolved_targets == {
        "https://media.example:443/parts/part-1.m4s",
        "https://media.example:443/parts/next.m4s",
        "https://media.example:443/alternate/live.m3u8",
    }


@pytest.mark.parametrize(
    ("playlist", "apparently_safe_child"),
    [
        (
            """#EXTM3U
#EXT-X-CONTENT-STEERING:SERVER-URI="steering.json",PATHWAY-ID="cdn-a"
#EXTINF:4,
segments/allowed.ts
""",
            "https://media.example/segments/allowed.ts",
        ),
        (
            """#EXTM3U
#EXT-X-DEFINE:NAME="cdn",VALUE="https://cdn.example"
#EXTINF:4,
{$cdn}/segment.ts
""",
            "https://cdn.example/segment.ts",
        ),
    ],
)
def test_hls_content_steering_and_variable_playlists_fail_closed_without_membership_delta(
    playlist: str,
    apparently_safe_child: str,
) -> None:
    policy = DomainPolicyEngine(resolver=_public_resolver)
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)
    verify_path = _required_method(proxy, "verify_path")

    _record_playlist_fail_closed(proxy, playlist)

    assert verify_path(_path(proxy.local_url_for(ROOT_URL))) == CANONICAL_ROOT_URL
    assert verify_path(_path(proxy.local_url_for(apparently_safe_child))) is None


@pytest.mark.parametrize(
    "metadata_tag",
    [
        '#EXT-X-SESSION-DATA:DATA-ID="account",URI="account/private.json"',
        '#EXT-X-UNKNOWN:URI="account/private.json"',
    ],
)
def test_hls_playlist_rejects_uri_attributes_on_non_media_tags_atomically(
    metadata_tag: str,
) -> None:
    proxy, _downloader, _clock = _new_proxy()
    unauthorized = "https://media.example/account/private.json"

    with pytest.raises(subject.HlsCapabilityError, match="URI|tag|unsupported"):
        proxy.record_playlist(ROOT_URL, f"#EXTM3U\n{metadata_tag}\n")

    assert proxy.members == {CANONICAL_ROOT_URL}
    assert proxy.verify_path(_path(proxy.local_url_for(unauthorized))) is None


def test_hls_proxy_stop_revokes_previously_signed_paths() -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    assert verify_path(signed_path) == CANONICAL_ROOT_URL

    proxy.stop()

    assert verify_path(signed_path) is None


def test_hls_proxy_start_failure_closes_bound_server_and_clears_state(monkeypatch) -> None:
    proxy, _downloader = _new_basic_proxy()
    server_type = subject._ThreadingHlsProxyServer
    created_servers = []

    def create_server(*args, **kwargs):
        server = server_type(*args, **kwargs)
        created_servers.append(server)
        return server

    monkeypatch.setattr(subject, "_ThreadingHlsProxyServer", create_server)
    try:
        with patch.object(
            subject.threading.Thread,
            "start",
            side_effect=RuntimeError("thread start failed"),
        ):
            with pytest.raises(RuntimeError, match="thread start failed"):
                proxy.start()

        assert proxy.server is None
        assert proxy.thread is None
        assert proxy.base_url == ""
        assert proxy.url == ""
        assert created_servers[0].socket.fileno() == -1
    finally:
        for server in created_servers:
            server.server_close()


def test_hls_proxy_start_rejects_immediately_dead_listener_and_can_retry(monkeypatch) -> None:
    proxy, _downloader = _new_basic_proxy()
    server_type = subject._ThreadingHlsProxyServer
    created_servers = []

    def create_server(*args, **kwargs):
        server = server_type(*args, **kwargs)
        created_servers.append(server)
        return server

    monkeypatch.setattr(subject, "_ThreadingHlsProxyServer", create_server)
    monkeypatch.setattr(subject, "_STARTUP_TIMEOUT_SECONDS", 0.1, raising=False)
    try:
        with patch.object(server_type, "serve_forever", return_value=None):
            with pytest.raises(ExternalToolError, match="start|ready|listener"):
                proxy.start()

        assert proxy.server is None
        assert proxy.thread is None
        assert proxy.base_url == ""
        assert proxy.url == ""
        assert created_servers[0].socket.fileno() == -1

        assert proxy.start() is proxy
        assert proxy.thread is not None and proxy.thread.is_alive()
        assert proxy.url.startswith("http://127.0.0.1:")
    finally:
        if proxy.thread is not None and not proxy.thread.is_alive():
            if proxy.server is not None:
                proxy.server.server_close()
            proxy.server = None
            proxy.thread = None
        else:
            proxy.stop()
        for server in created_servers:
            server.server_close()


def test_hls_proxy_stop_retains_blocked_handler_state_until_retry(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    client_errors: list[BaseException] = []
    media_url = "https://media.example/segment.ts"
    canonical_media_url = "https://media.example:443/segment.ts"

    class _BlockingResponse:
        status_code = 200
        url = canonical_media_url
        redirect_chain = (canonical_media_url,)
        headers = {"Content-Type": "video/mp2t"}
        content = b""

        @staticmethod
        def iter_content():
            entered.set()
            release.wait()
            yield b"segment"

        @staticmethod
        def close() -> None:
            return

    proxy, downloader = _new_basic_proxy()
    proxy.authorize_playlist_resource(ROOT_URL, media_url, kind="media")
    downloader.response = _BlockingResponse()  # type: ignore[assignment]
    monkeypatch.setattr(subject, "_STOP_TIMEOUT_SECONDS", 0.1, raising=False)
    proxy.start()
    server = proxy.server
    listener = proxy.thread

    def request_media() -> None:
        try:
            parts = urlsplit(proxy.local_url_for(media_url))
            request_target = urlunsplit(("", "", parts.path, parts.query, ""))
            with socket.create_connection((parts.hostname, parts.port), timeout=2) as client:
                client.settimeout(3)
                client.sendall(
                    (
                        f"GET {request_target} HTTP/1.0\r\n"
                        "Host: 127.0.0.1\r\n\r\n"
                    ).encode("ascii")
                )
                while client.recv(4096):
                    pass
        except BaseException as exc:
            client_errors.append(exc)

    client = threading.Thread(target=request_media, name="blocked-hls-client", daemon=True)
    client.start()
    try:
        assert entered.wait(2), "the real proxy handler never reached the blocking response"

        stop_started = time.monotonic()
        with pytest.raises(ExternalToolError, match="cleanup|active|handler|request"):
            proxy.stop()
        assert time.monotonic() - stop_started < 0.5

        assert proxy.server is server
        assert proxy.thread is listener
        assert server is not None and server.socket.fileno() == -1
        assert listener is not None and not listener.is_alive()

        release.set()
        client.join(timeout=2)
        assert not client.is_alive()
        assert client_errors == []

        proxy.stop()

        assert proxy.server is None
        assert proxy.thread is None
        assert proxy.base_url == ""
        assert proxy.url == ""

        replacement, _replacement_downloader = _new_basic_proxy()
        reacquired = [replacement.acquire_request_slot() for _index in range(5)]
        try:
            assert reacquired == [True] * 4 + [False]
        finally:
            for accepted in reacquired:
                if accepted:
                    replacement.release_request_slot()
    finally:
        release.set()
        client.join(timeout=2)
        try:
            proxy.stop()
        except ExternalToolError:
            pass


def test_hls_proxy_stop_attempts_close_and_join_when_shutdown_diagnostics_fail() -> None:
    class _TrackingSocket:
        def __init__(self) -> None:
            self.closed = False

        def fileno(self) -> int:
            return -1 if self.closed else 1

    class _FailingServer:
        def __init__(self) -> None:
            self.shutdown_calls = 0
            self.close_calls = 0
            self.socket = _TrackingSocket()
            self.ready_event = threading.Event()
            self.ready_event.set()

        def shutdown(self) -> None:
            self.shutdown_calls += 1
            raise RuntimeError("shutdown failed")

        def server_close(self) -> None:
            self.close_calls += 1
            self.socket.closed = True

    class _TrackingThread:
        def __init__(self) -> None:
            self.join_calls: list[float | None] = []
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> None:
            self.join_calls.append(timeout)
            self.alive = False

    proxy, _downloader = _new_basic_proxy()
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    server = _FailingServer()
    thread = _TrackingThread()
    proxy.server = server  # type: ignore[assignment]
    proxy.thread = thread  # type: ignore[assignment]

    with patch.object(
        subject.debug_logger,
        "log_exception",
        side_effect=RuntimeError("diagnostic logger failed"),
    ):
        proxy.stop()

    assert server.shutdown_calls == 1
    assert server.close_calls == 1
    assert len(thread.join_calls) == 1
    assert thread.join_calls[0] is not None and 0 < thread.join_calls[0] <= 2
    assert proxy.server is None
    assert proxy.thread is None
    assert proxy.verify_path(signed_path) is None


def test_hls_proxy_shutdown_obeys_hard_cleanup_deadline() -> None:
    entered = threading.Event()
    release = threading.Event()

    class _Socket:
        closed = False

        def fileno(self) -> int:
            return -1 if self.closed else 1

    class _BlockingServer:
        ready_event = threading.Event()
        socket = _Socket()

        def shutdown(self) -> None:
            entered.set()
            release.wait(2)

        def server_close(self) -> None:
            self.socket.closed = True

    class _AliveThread:
        @staticmethod
        def is_alive() -> bool:
            return True

        @staticmethod
        def join(timeout=None) -> None:
            return

    server = _BlockingServer()
    server.ready_event.set()
    proxy, _downloader = _new_basic_proxy()
    errors: list[BaseException] = []

    def cleanup() -> None:
        try:
            proxy._cleanup_listener(server, _AliveThread(), timeout=0.05)  # type: ignore[arg-type]
        except BaseException as exc:
            errors.append(exc)

    cleanup_thread = threading.Thread(target=cleanup, daemon=True)
    started = time.monotonic()
    cleanup_thread.start()
    assert entered.wait(1)
    cleanup_thread.join(timeout=0.25)
    completed_within_deadline = not cleanup_thread.is_alive()
    elapsed = time.monotonic() - started
    release.set()
    cleanup_thread.join(timeout=1)

    assert completed_within_deadline
    assert elapsed < 0.25
    assert len(errors) == 1
    assert isinstance(errors[0], subject.HlsProxyLifecycleError)
    assert server.socket.closed


@pytest.mark.parametrize(
    ("url", "content_type", "accepted"),
    [
        ("https://cdn.example/video.mp4", "application/vnd.apple.mpegurl", False),
        ("https://cdn.example/master.m3u8", "video/mp4", True),
    ],
)
def test_hls_response_content_type_overrides_misleading_url_suffix(
    url: str,
    content_type: str,
    accepted: bool,
) -> None:
    with patch.object(subject, "_MAX_PLAYLIST_RESPONSE_BYTES", 4), patch.object(
        subject, "_MAX_MEDIA_RESPONSE_BYTES", 8
    ):
        body = subject._BoundedHlsResponseBody(url)
        body.collect_header(f"Content-Type: {content_type}\r\n".encode())
        result = body.collect(b"12345")

    assert (result == 5) is accepted
    assert body.too_large is not accepted


def test_hls_response_classification_resets_for_final_header_block() -> None:
    with patch.object(subject, "_MAX_PLAYLIST_RESPONSE_BYTES", 4), patch.object(
        subject, "_MAX_MEDIA_RESPONSE_BYTES", 8
    ):
        body = subject._BoundedHlsResponseBody("https://cdn.example/master.m3u8")
        body.collect_header(b"HTTP/1.1 200 Connection established\r\n")
        body.collect_header(b"Content-Type: video/mp4\r\n")
        body.collect_header(b"HTTP/2 200\r\n")
        result = body.collect(b"12345")

    assert result == subject._CURL_WRITEFUNC_ERROR
    assert body.too_large


def test_hls_curl_close_failure_cannot_replace_primary_transfer_error() -> None:
    primary = RuntimeError("perform failed")
    curl = Mock()
    curl.impersonate.return_value = 0
    curl.perform.side_effect = primary
    curl.close.side_effect = OSError("close failed")
    requests_api = SimpleNamespace(Headers=lambda lines: lines)

    with patch("curl_cffi.Curl", return_value=curl), patch.object(
        subject.debug_logger,
        "log_exception",
        side_effect=RuntimeError("diagnostic failed"),
    ):
        with pytest.raises(RuntimeError, match="perform failed") as caught:
            subject._staged_curl_get(
                requests_api,
                "https://cdn.example/video.mp4",
                {"headers": {}, "timeout": 1, "allow_redirects": False},
                lambda line: len(line),
            )

    assert caught.value is primary
    assert any("cleanup failed" in note for note in getattr(primary, "__notes__", ()))


def test_hls_curl_close_failure_after_success_fails_closed() -> None:
    curl = Mock()
    curl.impersonate.return_value = 0
    curl.getinfo.side_effect = [b"https://cdn.example/video.mp4", 200]
    curl.close.side_effect = OSError("close failed")

    with patch("curl_cffi.Curl", return_value=curl):
        with pytest.raises(OSError, match="close failed"):
            subject._staged_curl_get(
                SimpleNamespace(Headers=lambda lines: lines),
                "https://cdn.example/video.mp4",
                {"headers": {}, "timeout": 1, "allow_redirects": False},
                lambda line: len(line),
            )


def test_hls_staged_close_type_error_never_retries_request() -> None:
    curl = Mock()
    curl.impersonate.return_value = 0
    curl.getinfo.side_effect = [b"https://cdn.example/video.mp4", 200]
    curl.close.side_effect = TypeError("close failed")

    with patch("curl_cffi.Curl", return_value=curl) as curl_factory:
        with pytest.raises(TypeError, match="close failed"):
            subject.perform_hls_curl_get(
                SimpleNamespace(Headers=lambda lines: lines),
                "https://cdn.example/video.mp4",
                {
                    "headers": {},
                    "timeout": 1,
                    "impersonate": "chrome",
                    "allow_redirects": False,
                },
                lambda line: len(line),
            )

    curl_factory.assert_called_once_with()
    curl.perform.assert_called_once_with()


def test_hls_header_budget_counts_status_crlf_and_terminal_blank_line() -> None:
    status = b"HTTP/1.1 200 OK\r\n"
    header = b"X-Test: value\r\n"
    terminal = b"\r\n"
    with patch.object(subject, "_MAX_HLS_RESPONSE_HEADER_BYTES", len(status + header + terminal) - 1):
        response_headers = subject._HlsResponseHeaders(lambda line: len(line))
        assert response_headers.write(status) == len(status)
        assert response_headers.write(header) == len(header)
        assert response_headers.write(terminal) == subject._CURL_WRITEFUNC_ERROR

    assert response_headers.too_large
    assert response_headers.size == len(status + header + terminal)


def test_hls_header_budget_restarts_with_and_limits_new_status_line() -> None:
    first_status = b"HTTP/1.1 100 Continue\r\n"
    second_status = b"HTTP/2 200 " + b"x" * 32 + b"\r\n"
    with patch.object(subject, "_MAX_HLS_RESPONSE_HEADER_BYTES", len(second_status) - 1):
        response_headers = subject._HlsResponseHeaders(lambda line: len(line))
        assert response_headers.write(first_status) == len(first_status)
        assert response_headers.write(b"X-Ignored: value\r\n") != subject._CURL_WRITEFUNC_ERROR
        assert response_headers.write(second_status) == subject._CURL_WRITEFUNC_ERROR

    assert response_headers.too_large
    assert response_headers.size == len(second_status)
    assert response_headers.lines == []


def test_hls_capability_explicit_revoke_invalidates_previously_signed_paths() -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    revoke = _required_method(proxy, "revoke")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    assert verify_path(signed_path) == CANONICAL_ROOT_URL

    revoke()

    assert verify_path(signed_path) is None


def test_hls_redirect_chain_can_expand_membership_only_from_authorized_request() -> None:
    proxy, _downloader, _clock = _new_proxy()
    authorize_redirect_chain = _required_method(proxy, "authorize_redirect_chain")
    verify_path = _required_method(proxy, "verify_path")
    redirect_chain = (
        ROOT_URL,
        "https://edge-a.example/redirected.m3u8",
        "https://edge-b.example/final.m3u8",
    )

    authorize_redirect_chain(ROOT_URL, redirect_chain)
    assert verify_path(_path(proxy.local_url_for(redirect_chain[1]))) == "https://edge-a.example:443/redirected.m3u8"
    assert verify_path(_path(proxy.local_url_for(redirect_chain[2]))) == "https://edge-b.example:443/final.m3u8"

    unauthorized_final = "https://edge-b.example/not-authorized.m3u8"
    try:
        authorize_redirect_chain("https://media.example/unlisted.m3u8", (unauthorized_final,))
    except (ExternalToolError, DomainPolicyViolation):
        pass
    assert verify_path(_path(proxy.local_url_for(unauthorized_final))) is None


@pytest.mark.parametrize(
    "redirect_chain",
    [(), ("https://edge.example/final.m3u8",)],
)
def test_hls_redirect_chain_requires_nonempty_chain_starting_with_requested_url(
    redirect_chain: tuple[str, ...],
) -> None:
    proxy, _downloader, _clock = _new_proxy()

    with pytest.raises(subject.HlsCapabilityError, match="provenance|start|non-empty"):
        proxy.authorize_redirect_chain(ROOT_URL, redirect_chain)

    if redirect_chain:
        assert proxy.verify_path(_path(proxy.local_url_for(redirect_chain[-1]))) is None


def test_redirect_authorization_checks_requested_member_before_domain_policy() -> None:
    policy = _NoPolicyProbeBeforeAuthorization()
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)  # type: ignore[arg-type]
    requested = "https://media.example/unlisted.m3u8"

    with pytest.raises(subject.HlsCapabilityError, match="source|authorized"):
        proxy.authorize_redirect_chain(
            requested,
            (requested, "https://probe.example/final.m3u8"),
        )

    assert policy.checked_urls == []


def test_response_redirect_chain_final_url_mismatch_is_rejected_atomically() -> None:
    proxy, downloader, _clock = _new_proxy()
    mismatched_hop = "https://edge.example/not-the-response.m3u8"
    final_url = "https://edge.example/final.m3u8"
    downloader.response = _FakeResponse(
        url=final_url,
        redirect_chain=(ROOT_URL, mismatched_hop),
    )

    with pytest.raises(subject.HlsCapabilityError, match="redirect|provenance|final"):
        proxy.serve(_FakeHandler(), ROOT_URL)

    assert downloader.response.closed
    assert proxy.verify_path(_path(proxy.local_url_for(mismatched_hop))) is None
    assert proxy.verify_path(_path(proxy.local_url_for(final_url))) is None


def test_fetch_redirect_chain_final_url_mismatch_is_rejected_atomically() -> None:
    proxy, downloader, _clock = _new_proxy()
    mismatched_hop = "https://edge.example/not-the-result.m3u8"
    final_url = "https://edge.example/final.m3u8"
    downloader.fetch_result = (
        200,
        "video/mp2t",
        b"segment",
        final_url,
        (ROOT_URL, mismatched_hop),
    )

    with pytest.raises(subject.HlsCapabilityError, match="redirect|provenance|final"):
        proxy.fetch(ROOT_URL)

    assert proxy.verify_path(_path(proxy.local_url_for(mismatched_hop))) is None
    assert proxy.verify_path(_path(proxy.local_url_for(final_url))) is None


def test_fetch_rejects_legacy_result_without_redirect_provenance() -> None:
    proxy, downloader, _clock = _new_proxy()
    downloader.fetch_result = (200, "video/mp2t", b"segment")

    with pytest.raises(subject.HlsCapabilityError, match="redirect metadata"):
        proxy.fetch(ROOT_URL)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"content-type": "application/vnd.apple.mpegurl"},
    ],
)
def test_extensionless_playlist_never_escapes_membership_validation(
    headers: dict[str, str],
) -> None:
    root_url = "https://media.example/watch"
    downloader = _RecordingDownloader()
    response = _FakeResponse(url="https://media.example:443/watch")
    response.headers = headers
    response.content = b"#EXTM3U\n#EXTINF:4,\nhttp://127.0.0.1/private.ts\n"
    downloader.response = response
    proxy = subject._LocalHlsProxy(
        downloader,
        root_url,
        {},
        None,
        domain_policy=DomainPolicyEngine(resolver=_public_resolver),
    )

    with pytest.raises(DomainPolicyViolation):
        proxy.serve(_FakeHandler(), root_url)

    assert proxy.members == {"https://media.example:443/watch"}


def test_redirect_membership_update_is_atomic_when_any_hop_is_private() -> None:
    policy = DomainPolicyEngine(resolver=_public_resolver)
    proxy, _downloader, _clock = _new_proxy(domain_policy=policy)
    public_hop = "https://edge.example/redirected.m3u8"

    with pytest.raises((subject.HlsCapabilityError, DomainPolicyViolation)):
        proxy.authorize_redirect_chain(
            ROOT_URL,
            (ROOT_URL, public_hop, "http://127.0.0.1/private.m3u8"),
        )

    assert proxy.verify_path(_path(proxy.local_url_for(public_hop))) is None


def test_hls_proxy_strips_cross_origin_credentials_and_host() -> None:
    credentials = {
        "Cookie": "sid=secret",
        "Authorization": "Bearer secret",
        "Proxy-Authorization": "Basic secret",
        "Host": "media.example",
        "User-Agent": "safe-agent",
    }
    proxy, downloader = _new_basic_proxy(headers=credentials)
    cross_origin_url = "https://cdn.example/segment.ts"
    proxy.authorize_playlist_resource(ROOT_URL, cross_origin_url)

    proxy.fetch(cross_origin_url)

    sent_headers = downloader.requests[-1][1]
    sensitive = {"cookie", "authorization", "proxy-authorization", "host"}
    assert sensitive.isdisjoint(name.lower() for name in sent_headers)
    assert sent_headers["User-Agent"] == "safe-agent"


def test_hls_proxy_preserves_scoped_credentials_but_never_caller_host_for_capability_origin() -> None:
    credentials = {
        "Cookie": "sid=secret",
        "Authorization": "Bearer secret",
        "Proxy-Authorization": "Basic secret",
        "Host": "media.example",
    }
    proxy, downloader = _new_basic_proxy(headers=credentials)

    proxy.fetch(ROOT_URL)

    assert downloader.requests[-1][1] == {
        "Cookie": "sid=secret",
        "Authorization": "Bearer secret",
    }


def test_hls_proxy_never_emits_wildcard_cors() -> None:
    proxy, _downloader = _new_basic_proxy()
    handler = _FakeHandler()

    proxy.serve(handler, ROOT_URL)

    cors_values = [value for name, value in handler.response_headers if name.lower() == "access-control-allow-origin"]
    assert "*" not in cors_values


@pytest.mark.parametrize(
    "header_value",
    ["bytes=-0", "bytes=10-9", "bytes=0-1,3-4", "bytes=0-1\r\nX-Leak: secret"],
)
def test_hls_proxy_rejects_invalid_or_ambiguous_range_headers(header_value: str) -> None:
    with pytest.raises(subject.HlsClientRequestError, match="Range|range"):
        subject._LocalHlsProxy._validate_forwarded_header("Range", header_value)


@pytest.mark.parametrize("header_value", ["bytes=0-499", "bytes=500-", "bytes=-500"])
def test_hls_proxy_accepts_one_well_formed_byte_range(header_value: str) -> None:
    assert subject._LocalHlsProxy._validate_forwarded_header("Range", header_value) == header_value


def test_hls_proxy_request_admission_is_process_wide_and_reusable() -> None:
    first_proxy, _first_downloader = _new_basic_proxy()
    second_proxy, _second_downloader = _new_basic_proxy()
    acquisition_order = [first_proxy, second_proxy] * 3
    admitted: list[bool] = []
    acquired_by: list[subject._LocalHlsProxy] = []

    try:
        for proxy in acquisition_order:
            accepted = proxy.acquire_request_slot()
            admitted.append(accepted)
            if accepted:
                acquired_by.append(proxy)

        assert admitted == [True] * 4 + [False] * 2
        first_proxy.revoke()
    finally:
        for proxy in acquired_by:
            proxy.release_request_slot()

    assert not first_proxy.acquire_request_slot()
    reacquired = [second_proxy.acquire_request_slot() for _index in range(5)]
    assert reacquired == [True] * 4 + [False]
    for _index in range(4):
        second_proxy.release_request_slot()


def test_hls_proxy_handler_failure_releases_shared_admission_slot() -> None:
    proxy, _downloader = _new_basic_proxy()
    replacement, _replacement_downloader = _new_basic_proxy()
    server = subject._ThreadingHlsProxyServer(("127.0.0.1", 0), subject._HlsProxyHandler)
    server.owner = proxy  # type: ignore[attr-defined]
    server.finish_request = Mock(side_effect=RuntimeError("handler failed"))
    server.handle_error = Mock()
    server.shutdown_request = Mock()

    try:
        assert proxy.acquire_request_slot()
        server.process_request_thread(Mock(), ("127.0.0.1", 12345))
        assert proxy._active_requests == 0

        reacquired = [replacement.acquire_request_slot() for _index in range(5)]
        try:
            assert reacquired == [True] * 4 + [False]
        finally:
            for accepted in reacquired:
                if accepted:
                    replacement.release_request_slot()
    finally:
        server.server_close()


def test_loopback_admission_bounds_partial_request_threads_and_recovers() -> None:
    proxy, _downloader = _new_basic_proxy()
    partial_clients: list[socket.socket] = []
    with patch.object(subject, "_CLIENT_SOCKET_TIMEOUT_SECONDS", 2.0):
        proxy.start()
        try:
            assert proxy.server is not None
            target = proxy.server.server_address[:2]
            for _index in range(4):
                client = socket.create_connection(target, timeout=1)
                client.sendall(b"GET /hls?")
                partial_clients.append(client)

            deadline = time.monotonic() + 2
            while getattr(proxy._request_slots, "_value", 1) != 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert getattr(proxy._request_slots, "_value", 1) == 0

            overflow = socket.create_connection(target, timeout=1)
            overflow.settimeout(1)
            try:
                overflow.sendall(b"GET / HTTP/1.0\r\n\r\n")
                try:
                    assert overflow.recv(1) == b""
                except OSError:
                    pass
            finally:
                overflow.close()

            for client in partial_clients:
                client.close()
            partial_clients.clear()
            deadline = time.monotonic() + 2
            while getattr(proxy._request_slots, "_value", 0) != 4 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert getattr(proxy._request_slots, "_value", 0) == 4

            parts = urlsplit(proxy.url)
            request_target = urlunsplit(("", "", parts.path, parts.query, ""))
            with socket.create_connection(target, timeout=1) as healthy:
                healthy.sendall(
                    (
                        f"GET {request_target} HTTP/1.0\r\n"
                        "Host: 127.0.0.1\r\n\r\n"
                    ).encode("ascii")
                )
                response = b""
                while chunk := healthy.recv(4096):
                    response += chunk
            assert response.startswith(b"HTTP/1.0 200")
        finally:
            for client in partial_clients:
                client.close()
            proxy.stop()


def test_hls_member_updates_remain_consistent_under_concurrency() -> None:
    proxy, _downloader, _clock = _new_proxy()
    children = [f"https://cdn.example/segment-{index}.ts" for index in range(32)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda child: proxy.authorize_playlist_resource(ROOT_URL, child), children))

    assert all(proxy.verify_path(_path(proxy.local_url_for(child))) is not None for child in children)


def test_hls_member_capacity_failure_keeps_playlist_update_atomic(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_MAX_TASK_MEMBERS", 2)
    proxy, _downloader, _clock = _new_proxy()
    first = "https://cdn.example/first.ts"
    second = "https://cdn.example/second.ts"
    playlist = """#EXTM3U
#EXTINF:4,
https://cdn.example/first.ts
#EXTINF:4,
https://cdn.example/second.ts
"""

    with pytest.raises(subject.HlsCapabilityError, match="member limit"):
        proxy.record_playlist(ROOT_URL, playlist)

    assert proxy.verify_path(_path(proxy.local_url_for(first))) is None
    assert proxy.verify_path(_path(proxy.local_url_for(second))) is None


def test_hls_handler_does_not_log_client_path_or_upstream_exception_secrets() -> None:
    class _FailingOwner:
        capability = SimpleNamespace(task_id=TASK_A)

        @staticmethod
        def verify_path(_path_value: str) -> str:
            return CANONICAL_ROOT_URL

        @staticmethod
        def acquire_request_slot() -> bool:
            return True

        @staticmethod
        def release_request_slot() -> None:
            return

        @staticmethod
        def serve(_handler, _upstream_url: str) -> None:
            raise RuntimeError("https://user:pass@cdn.example/a.ts?sig=upstream-secret")

    errors: list[int] = []
    handler = SimpleNamespace(
        server=SimpleNamespace(owner=_FailingOwner()),
        path="/hls?sig=client-secret",
        send_error=errors.append,
    )
    with patch.object(subject.debug_logger, "log_exception") as logged:
        subject._HlsProxyHandler.do_GET(handler)

    rendered_log_call = repr(logged.call_args)
    assert errors == [502]
    assert "client-secret" not in rendered_log_call
    assert "upstream-secret" not in rendered_log_call
    assert "user:pass" not in rendered_log_call


def test_hls_handler_returns_502_even_when_diagnostic_logging_fails() -> None:
    class _FailingOwner:
        capability = SimpleNamespace(task_id=TASK_A)

        @staticmethod
        def verify_path(_path_value: str) -> str:
            return CANONICAL_ROOT_URL

        @staticmethod
        def serve(_handler, _upstream_url: str) -> None:
            raise RuntimeError("upstream failed")

    errors: list[int] = []
    handler = SimpleNamespace(
        server=SimpleNamespace(owner=_FailingOwner()),
        path="/hls",
        send_error=errors.append,
    )

    with patch.object(
        subject.debug_logger,
        "log_exception",
        side_effect=RuntimeError("diagnostic logger failed"),
    ):
        subject._HlsProxyHandler.do_GET(handler)

    assert errors == [502]


@pytest.mark.parametrize("close_error", [RuntimeError, ValueError])
def test_hls_response_cleanup_never_masks_a_completed_response(close_error) -> None:
    class _CloseFails(_FakeResponse):
        def close(self) -> None:
            raise close_error("close failed")

    proxy, downloader = _new_basic_proxy()
    media_url = "https://media.example/segment.ts"
    proxy.authorize_playlist_resource(ROOT_URL, media_url, kind="media")
    downloader.response = _CloseFails(url=media_url)
    handler = _FakeHandler()

    with patch.object(
        subject.debug_logger,
        "log_exception",
        side_effect=RuntimeError("diagnostic logger failed"),
    ):
        proxy.serve(handler, media_url)

    assert handler.status == 200
    assert handler.wfile.getvalue() == b"segment"


def test_hls_flush_diagnostic_failure_does_not_interrupt_streaming() -> None:
    class _FlushFails(io.BytesIO):
        def flush(self) -> None:
            raise OSError("client flush failed")

    proxy, _downloader = _new_basic_proxy()
    media_url = "https://media.example/segment.ts"
    proxy.authorize_playlist_resource(ROOT_URL, media_url, kind="media")
    handler = _FakeHandler()
    handler.wfile = _FlushFails()

    with patch.object(
        subject.debug_logger,
        "log_exception",
        side_effect=RuntimeError("diagnostic logger failed"),
    ):
        proxy.serve(handler, media_url)

    assert handler.wfile.getvalue() == b"segment"
    assert proxy.progress_snapshot() == (0, 7)
