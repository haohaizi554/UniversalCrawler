from __future__ import annotations

import io
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch
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
    try:
        record_playlist(ROOT_URL, playlist)
    except (ExternalToolError, DomainPolicyViolation):
        return


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
"""
    expected_members = {
        CANONICAL_ROOT_URL,
        "https://media.example:443/audio/index.m3u8",
        "https://media.example:443/variants/main.m3u8",
        "https://media.example:443/keys/key.bin",
        "https://media.example:443/init/init.mp4",
        "https://media.example:443/segments/one.ts",
        "https://media.example:443/iframes/index.m3u8",
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


def test_hls_proxy_stop_revokes_previously_signed_paths() -> None:
    proxy, _downloader, _clock = _new_proxy()
    verify_path = _required_method(proxy, "verify_path")
    signed_path = _path(proxy.local_url_for(ROOT_URL))
    assert verify_path(signed_path) == CANONICAL_ROOT_URL

    proxy.stop()

    assert verify_path(signed_path) is None


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


def test_hls_proxy_request_admission_is_bounded_and_reusable() -> None:
    proxy, _downloader = _new_basic_proxy()
    admitted = [proxy.acquire_request_slot() for _index in range(17)]

    assert admitted == [True] * 16 + [False]
    proxy.release_request_slot()
    assert proxy.acquire_request_slot()
    for _index in range(16):
        proxy.release_request_slot()


def test_loopback_admission_bounds_partial_request_threads_and_recovers() -> None:
    proxy, _downloader = _new_basic_proxy()
    partial_clients: list[socket.socket] = []
    with patch.object(subject, "_CLIENT_SOCKET_TIMEOUT_SECONDS", 2.0):
        proxy.start()
        try:
            assert proxy.server is not None
            target = proxy.server.server_address[:2]
            for _index in range(16):
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
            while getattr(proxy._request_slots, "_value", 0) != 16 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert getattr(proxy._request_slots, "_value", 0) == 16

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
