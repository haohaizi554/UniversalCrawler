"""供 N_m3u8DL-RE 下载器使用的本地受控 HLS 代理。"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import hmac
import http.server
import re
import secrets
import socketserver
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.debug_logger import debug_logger
from app.exceptions import ExternalToolError
from shared.network.pinned_transport import (
    canonicalize_request_target,
    curl_resolve_options as _pinned_curl_resolve_options,
)
from shared.runtime_options import DomainPolicyViolation

if TYPE_CHECKING:
    from shared.runtime_options import DomainPolicyEngine

    from .m3u8 import N_m3u8DL_RE_Downloader


_CAPABILITY_TTL_SECONDS = 15 * 60
_MAX_CAPABILITY_PATH_CHARS = 16 * 1024
_MAX_ENCODED_URL_CHARS = 12 * 1024
_MAX_UPSTREAM_URL_CHARS = 8 * 1024
_MAX_PLAYLIST_CHARS = 8 * 1024 * 1024
_MAX_PLAYLIST_LINES = 50_000
_MAX_TASK_MEMBERS = 50_000
_MAX_PLAYLIST_DEPTH = 16
_MAX_CONCURRENT_REQUESTS = 4
_MAX_PLAYLIST_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_MEDIA_RESPONSE_BYTES = 32 * 1024 * 1024
_HLS_CLASSIFICATION_PREFIX_BYTES = 4096
_MAX_HLS_RESPONSE_HEADER_BYTES = 64 * 1024
_PROCESS_REQUEST_SLOTS = threading.BoundedSemaphore(_MAX_CONCURRENT_REQUESTS)
_CLIENT_SOCKET_TIMEOUT_SECONDS = 10.0
_SERVER_POLL_INTERVAL_SECONDS = 0.05
_STARTUP_TIMEOUT_SECONDS = 1.0
_STOP_TIMEOUT_SECONDS = 2.0
_URI_ATTRIBUTE = re.compile(r'(?<![A-Z0-9-])URI=(["\'])(.*?)\1', re.IGNORECASE)
_UNQUOTED_URI_ATTRIBUTE = re.compile(r'(?<![A-Z0-9-])URI\s*=', re.IGNORECASE)
_SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")
_CURL_WRITEFUNC_ERROR = 0xFFFFFFFF
_ALWAYS_DROP_UPSTREAM_HEADERS = frozenset({"host", "proxy-authorization"})
_CROSS_ORIGIN_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie"})
_FORBIDDEN_PLAYLIST_TAGS = ("#EXT-X-CONTENT-STEERING", "#EXT-X-DEFINE")
_URI_RESOURCE_TAGS = frozenset(
    {
        "#EXT-X-I-FRAME-STREAM-INF",
        "#EXT-X-IMAGE-STREAM-INF",
        "#EXT-X-KEY",
        "#EXT-X-MAP",
        "#EXT-X-MEDIA",
        "#EXT-X-PART",
        "#EXT-X-PRELOAD-HINT",
        "#EXT-X-RENDITION-REPORT",
        "#EXT-X-SESSION-KEY",
    }
)


class HlsCapabilityError(ExternalToolError):
    """A local request failed capability or membership verification."""


class HlsClientRequestError(ExternalToolError):
    """A local client supplied an invalid forwarding header."""


class HlsProxyLifecycleError(ExternalToolError):
    """The local listener could not prove that startup or cleanup completed."""


@dataclass(frozen=True, slots=True)
class HlsCapability:
    task_id: str
    secret: bytes = field(repr=False)
    expires_at: int

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or _TASK_ID.fullmatch(self.task_id) is None:
            raise ValueError("HLS capability task_id is invalid")
        if type(self.secret) is not bytes or len(self.secret) < 32:
            raise ValueError("HLS capability secret must contain at least 32 bytes")
        if type(self.expires_at) is not int or self.expires_at <= 0:
            raise ValueError("HLS capability expiry is invalid")


@dataclass(frozen=True, slots=True)
class _HlsMember:
    url: str
    kind: str
    parent_url: str | None
    discovery: str
    depth: int


def _diagnostic_exception(exc: BaseException) -> RuntimeError:
    """Retain the failure type without logging attacker-controlled exception text."""

    return RuntimeError(f"local HLS proxy failure ({type(exc).__name__})")


def _log_diagnostic_best_effort(
    component: str,
    action: str,
    exc: BaseException,
    *,
    context: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Keep diagnostics from changing proxy response and cleanup semantics."""

    try:
        debug_logger.log_exception(
            component,
            action,
            _diagnostic_exception(exc),
            context=context,
            details=details,
        )
    except BaseException:
        return


def _record_secondary_cleanup_failure(
    primary_error: BaseException,
    cleanup_error: BaseException,
) -> None:
    """Report cleanup without changing the already-active download failure."""

    try:
        add_note = object.__getattribute__(primary_error, "add_note")
    except BaseException:
        add_note = None
    if callable(add_note):
        try:
            add_note("local HLS proxy cleanup failed; preserved the primary download error")
        except BaseException:
            pass
    _log_diagnostic_best_effort(
        "N_m3u8DL_RE_Downloader",
        "local_hls_proxy_cleanup_after_download_error",
        cleanup_error,
    )


@contextlib.contextmanager
def _hls_proxy_cleanup_scope(cleanup: Callable[[], None] | None) -> Iterator[None]:
    primary_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            if cleanup is not None:
                cleanup()
        except BaseException as cleanup_error:
            if primary_error is None:
                raise
            try:
                _record_secondary_cleanup_failure(primary_error, cleanup_error)
            except BaseException:
                pass


def looks_like_hls_playlist(url: str, content_type: str, body: bytes) -> bool:
    if b"#EXTM3U" in body[:4096]:
        return True
    lowered_type = str(content_type or "").lower()
    if "mpegurl" in lowered_type or "m3u8" in lowered_type:
        return True
    return ".m3u8" in str(url or "").lower()


def looks_like_hls_playlist_url(url: str, content_type: str) -> bool:
    lowered_type = str(content_type or "").lower()
    if "mpegurl" in lowered_type or "m3u8" in lowered_type:
        return True
    return ".m3u8" in str(url or "").lower()


def _hls_response_budget(upstream_url: str) -> int | None:
    if looks_like_hls_playlist_url(upstream_url, ""):
        return _MAX_PLAYLIST_RESPONSE_BYTES
    if looks_like_hls_media_resource(upstream_url):
        return _MAX_MEDIA_RESPONSE_BYTES
    return None


def _local_hls_proxy_thread_count(thread_count: str | int | None) -> int:
    try:
        requested = int(thread_count or _MAX_CONCURRENT_REQUESTS)
    except (TypeError, ValueError):
        requested = _MAX_CONCURRENT_REQUESTS
    return max(1, min(requested, _MAX_CONCURRENT_REQUESTS))


def build_hls_proxy_upstream_headers(
    upstream_url: str,
    headers: dict[str, str],
) -> dict[str, str]:
    upstream_headers = dict(headers)
    if looks_like_hls_playlist_url(upstream_url, ""):
        return upstream_headers
    upstream_headers.pop("Origin", None)
    upstream_headers["Accept"] = "*/*"
    upstream_headers["Accept-Encoding"] = "identity;q=1, *;q=0"
    upstream_headers.setdefault("Accept-Language", "zh-CN,zh;q=0.9,en-CN;q=0.8,en;q=0.7")
    upstream_headers.setdefault("Cache-Control", "no-cache")
    upstream_headers.setdefault("Pragma", "no-cache")
    upstream_headers["Priority"] = "i"
    upstream_headers["Sec-Fetch-Dest"] = "video"
    upstream_headers["Sec-Fetch-Mode"] = "no-cors"
    upstream_headers["Sec-Fetch-Site"] = "same-origin"
    return upstream_headers


class _BoundedHlsResponseBody:
    """Classify one response from headers/prefix before applying its hard limit."""

    def __init__(self, upstream_url: str) -> None:
        fixed_budget = _hls_response_budget(upstream_url)
        self._url_budget = fixed_budget
        self._url_kind = (
            "playlist"
            if fixed_budget == _MAX_PLAYLIST_RESPONSE_BYTES
            else "media"
            if fixed_budget == _MAX_MEDIA_RESPONSE_BYTES
            else None
        )
        self.kind = self._url_kind
        self.max_bytes = fixed_budget or _HLS_CLASSIFICATION_PREFIX_BYTES
        self.buffered = bytearray()
        self.prefix = bytearray()
        self.too_large = False

    def _set_kind(self, kind: str) -> None:
        self.kind = kind
        self.max_bytes = (
            _MAX_PLAYLIST_RESPONSE_BYTES if kind == "playlist" else _MAX_MEDIA_RESPONSE_BYTES
        )

    def _observe_content_type(self, content_type: str) -> None:
        value = str(content_type or "").lower()
        if "mpegurl" in value or "m3u8" in value:
            self._set_kind("playlist")
        elif value:
            self._set_kind("media")

    def _observe_prefix(self, chunk: bytes) -> None:
        remaining = _HLS_CLASSIFICATION_PREFIX_BYTES - len(self.prefix)
        if remaining > 0:
            self.prefix.extend(chunk[:remaining])
        if b"#EXTM3U" in self.prefix:
            self._set_kind("playlist")
        elif self.kind is None and len(self.prefix) >= _HLS_CLASSIFICATION_PREFIX_BYTES:
            self._set_kind("media")

    def collect_header(self, line: bytes) -> int:
        raw_line = bytes(line)
        if raw_line.startswith(b"HTTP/"):
            self.kind = self._url_kind
            self.max_bytes = self._url_budget or _HLS_CLASSIFICATION_PREFIX_BYTES
        name, separator, value = raw_line.partition(b":")
        if separator and name.strip().lower() == b"content-type":
            self._observe_content_type(value.decode("latin-1", errors="replace").strip())
        return len(raw_line)

    def collect(self, chunk: bytes) -> int:
        self._observe_prefix(chunk)
        if len(self.buffered) + len(chunk) > self.max_bytes:
            self.too_large = True
            return _CURL_WRITEFUNC_ERROR
        self.buffered.extend(chunk)
        return len(chunk)

    def raise_if_oversized(self, exc: BaseException) -> None:
        if self.too_large:
            raise DomainPolicyViolation("HLS upstream response exceeds size limit") from exc

    def finalize(self, response: Any, close_response: Callable[[], None]) -> bytes:
        def close_best_effort() -> None:
            try:
                close_response()
            except BaseException:
                pass

        try:
            response_headers = getattr(response, "headers", {}) or {}
            content_type = response_headers.get("Content-Type") or response_headers.get(
                "content-type", ""
            )
            self._observe_content_type(content_type)
            raw_content = getattr(response, "content", b"") or b""
            callback_body = bytes(self.buffered)
            raw_body = bytes(raw_content)
        except (TypeError, ValueError) as exc:
            close_best_effort()
            raise DomainPolicyViolation("HLS upstream response body is invalid") from exc
        try:
            self._observe_prefix(callback_body or raw_body)
            self._set_kind(self.kind or "media")
            if self.too_large:
                raise DomainPolicyViolation("HLS upstream response exceeds size limit")
            if len(callback_body) > self.max_bytes or len(raw_body) > self.max_bytes:
                raise DomainPolicyViolation("HLS upstream response exceeds size limit")
            if callback_body and raw_body and callback_body != raw_body:
                raise DomainPolicyViolation("HLS upstream response body is inconsistent")
            payload = callback_body or raw_body
            if callback_body and raw_body != callback_body:
                response.content = payload
            return payload
        except BaseException:
            close_best_effort()
            raise


def response_content_bytes(response) -> bytes:
    content = getattr(response, "content", None)
    if content:
        return bytes(content or b"")
    chunks = []
    for chunk in response_iter_bytes(response):
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


def response_iter_bytes(response, chunk_size: int = 256 * 1024):
    content = getattr(response, "content", None)
    if content:
        payload = bytes(content)
        chunk_size = max(1, int(chunk_size))
        for offset in range(0, len(payload), chunk_size):
            yield payload[offset : offset + chunk_size]
        return
    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        try:
            yield from iter_content()
            return
        except TypeError:
            try:
                yield from iter_content(chunk_size=chunk_size)
                return
            except TypeError:
                yield from iter_content(chunk_size)
                return


def curl_resolve_options(url: str, addresses: tuple[str, ...]) -> dict[Any, Any]:
    """把 curl 固定到已通过策略校验的公网地址，防止解析结果漂移。"""
    target = canonicalize_request_target(url)
    options = _pinned_curl_resolve_options(target, addresses, disable_proxy=True)
    from curl_cffi.const import CurlOpt

    options.update(
        {
            CurlOpt.NOSIGNAL: 1,
            CurlOpt.FRESH_CONNECT: 1,
            CurlOpt.FORBID_REUSE: 1,
        }
    )
    return options


def prepare_hls_curl_request(
    url: str,
    domain_policy: "DomainPolicyEngine | None",
    upstream_proxy: str | None,
) -> tuple[str, dict[Any, Any] | None]:
    request_url = canonicalize_request_target(url).url
    if domain_policy is None:
        return request_url, None
    if upstream_proxy:
        domain_policy.require_public_url(request_url)
        return request_url, None
    addresses = domain_policy.resolve_public_addresses(request_url)
    return request_url, curl_resolve_options(request_url, addresses)


class _HlsResponseHeaders:
    """Collect the final header block through curl_cffi's public callback API."""

    def __init__(self, callback: Callable[[bytes], int]) -> None:
        self.callback = callback
        self.lines: list[bytes] = []
        self.size = 0
        self.too_large = False

    def write(self, line: bytes) -> int:
        raw_line = bytes(line)
        if self.callback(raw_line) != len(raw_line):
            return _CURL_WRITEFUNC_ERROR
        stripped = raw_line.rstrip(b"\r\n")
        is_status = stripped.startswith(b"HTTP/")
        if is_status:
            self.lines.clear()
            self.size = len(raw_line)
        else:
            self.size += len(raw_line)
        if self.size > _MAX_HLS_RESPONSE_HEADER_BYTES:
            self.too_large = True
            return _CURL_WRITEFUNC_ERROR
        if stripped and not is_status:
            if stripped[:1] in {b" ", b"\t"} and self.lines:
                self.lines[-1] += stripped
            else:
                self.lines.append(stripped)
        return len(raw_line)

    def apply(self, curl_requests: Any, response: Any) -> None:
        headers_type = getattr(curl_requests, "Headers", None)
        if not callable(headers_type):
            raise DomainPolicyViolation("curl session cannot expose bounded HLS headers")
        response.headers = headers_type(self.lines)


@dataclass(slots=True)
class _HlsCurlResponse:
    status_code: int
    headers: Any
    content: bytes
    url: str

    def close(self) -> None:
        return


def _staged_curl_get(
    curl_requests: Any,
    url: str,
    kwargs: dict[str, Any],
    header_callback: Callable[[bytes], int],
):
    from curl_cffi import Curl
    from curl_cffi.const import CurlInfo, CurlOpt

    request_kwargs = dict(kwargs)
    curl_options = dict(request_kwargs.pop("curl_options", None) or {})
    response_headers = _HlsResponseHeaders(header_callback)
    response_body = bytearray()

    def collect_body(chunk: bytes) -> int:
        response_body.extend(chunk)
        return len(chunk)

    content_callback = request_kwargs.pop("content_callback", None) or collect_body
    headers = request_kwargs.pop("headers", {}) or {}
    timeout = float(request_kwargs.pop("timeout", 60))
    impersonate = request_kwargs.pop("impersonate", None)
    allow_redirects = bool(request_kwargs.pop("allow_redirects", False))
    proxy = request_kwargs.pop("proxy", None)
    if request_kwargs.pop("stream", False) or request_kwargs:
        raise TypeError("unsupported bounded HLS curl request options")

    curl = Curl()
    with _hls_proxy_cleanup_scope(curl.close):
        try:
            impersonation_target = "chrome124" if impersonate == "chrome" else impersonate
            if impersonation_target and curl.impersonate(str(impersonation_target)) != 0:
                raise DomainPolicyViolation("curl browser impersonation is unavailable")
            curl.setopt(CurlOpt.URL, str(url).encode("utf-8"))
            curl.setopt(CurlOpt.TIMEOUT_MS, max(1, int(timeout * 1000)))
            curl.setopt(CurlOpt.FOLLOWLOCATION, int(allow_redirects))
            curl.setopt(
                CurlOpt.HTTPHEADER,
                [f"{name}: {value}".encode("utf-8") for name, value in headers.items()],
            )
            for option, value in curl_options.items():
                curl.setopt(option, value)
            curl.setopt(CurlOpt.PROXY, str(proxy or ""))
            curl.setopt(CurlOpt.NOPROXY, "")
            curl.setopt(CurlOpt.WRITEFUNCTION, content_callback)
            curl.setopt(CurlOpt.HEADERFUNCTION, response_headers.write)
            curl.perform()
            effective_url = curl.getinfo(CurlInfo.EFFECTIVE_URL)
            response = _HlsCurlResponse(
                status_code=int(curl.getinfo(CurlInfo.RESPONSE_CODE)),
                headers={},
                content=bytes(response_body),
                url=(
                    effective_url.decode("utf-8", errors="replace")
                    if isinstance(effective_url, bytes)
                    else str(effective_url)
                ),
            )
        except Exception as exc:
            if response_headers.too_large:
                raise DomainPolicyViolation("HLS upstream response headers exceed size limit") from exc
            raise
    response_headers.apply(curl_requests, response)
    return response


def perform_hls_curl_get(
    curl_requests: Any,
    url: str,
    kwargs: dict[str, Any],
    header_callback: Callable[[bytes], int] | None,
):
    if header_callback is not None:
        return _staged_curl_get(curl_requests, url, kwargs, header_callback)
    try:
        return curl_requests.get(url, **kwargs)
    except TypeError:
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("impersonate", None)
        if retry_kwargs.get("stream"):
            retry_kwargs.pop("stream", None)
        return curl_requests.get(url, **retry_kwargs)


def looks_like_hls_media_resource(url: str) -> bool:
    path = urllib.parse.urlparse(str(url or "")).path.lower()
    return path.endswith((".ts", ".m4s", ".mp4", ".m4v", ".aac", ".mp3"))


def count_hls_media_entries(playlist_text: str) -> int:
    count = 0
    for raw_line in str(playlist_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        path = urllib.parse.urlparse(line).path.lower()
        if path.endswith(".m3u8"):
            continue
        count += 1
    return count


def rewrite_hls_playlist_for_proxy(playlist_text: str, playlist_url: str, local_url_for) -> str:
    base_url = str(playlist_url or "")
    rewritten_lines: list[str] = []
    for raw_line in str(playlist_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            rewritten_lines.append(raw_line)
            continue
        if line.startswith("#"):
            rewritten_lines.append(rewrite_hls_attribute_uris(raw_line, base_url, local_url_for))
            continue
        absolute_url = urllib.parse.urljoin(base_url, line)
        rewritten_lines.append(local_url_for(absolute_url))
    return "\n".join(rewritten_lines) + "\n"


def rewrite_hls_attribute_uris(line: str, base_url: str, local_url_for) -> str:
    def replace_uri(match):
        quote = match.group(1)
        uri = match.group(2)
        absolute_url = urllib.parse.urljoin(base_url, uri)
        return f"URI={quote}{local_url_for(absolute_url)}{quote}"

    return _URI_ATTRIBUTE.sub(replace_uri, line)


class _ThreadingHlsProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ready_event = threading.Event()
        self.stopped_event = threading.Event()
        self.listener_error: BaseException | None = None

    def service_actions(self) -> None:
        # ``Thread.start()`` only proves that Python scheduled the thread. The
        # first completed serve_forever poll proves that the listener loop ran.
        self.ready_event.set()

    def process_request(self, request: Any, client_address: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is None or not owner.acquire_request_slot():
            self.shutdown_request(request)
            return
        try:
            request.settimeout(_CLIENT_SOCKET_TIMEOUT_SECONDS)
            super().process_request(request, client_address)
        except Exception:
            owner.release_request_slot()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.mark_request_handler_started()
        try:
            super().process_request_thread(request, client_address)
        finally:
            if owner is not None:
                owner.mark_request_handler_stopped()
                owner.release_request_slot()


class _HlsProxyHandler(http.server.BaseHTTPRequestHandler):
    server: _ThreadingHlsProxyServer
    server_version = "UniversalCrawlerHLS"
    sys_version = ""

    def do_GET(self) -> None:
        owner = getattr(self.server, "owner", None)
        if owner is None:
            self.send_error(500)
            return
        upstream_url = owner.verify_path(self.path)
        if upstream_url is None:
            self.send_error(403)
            return
        try:
            owner.serve(self, upstream_url)
        except HlsClientRequestError:
            self.send_error(400)
        except Exception as exc:
            _log_diagnostic_best_effort(
                "N_m3u8DL_RE_Downloader",
                "local_hls_proxy_error",
                exc,
                context={"task_id": owner.capability.task_id},
            )
            self.send_error(502)

    def log_message(self, _format: str, *args: Any) -> None:
        return


class _LocalHlsProxy:
    """把本地 HTTP 服务绑定到 loopback，并代理调用方编码进本地 URL 的上游地址。

    上游 URL 的来源约束和首跳凭据投递范围由调用方负责；跨源重定向时会剥离
    Authorization、Cookie、Host 和 Proxy-Authorization 等敏感头。
    """

    def __init__(
        self,
        downloader: "N_m3u8DL_RE_Downloader",
        root_url: str,
        headers: dict[str, str],
        upstream_proxy: str | None,
        *,
        domain_policy: "DomainPolicyEngine | None" = None,
        allow_upstream_proxy: bool = True,
        capability: HlsCapability | None = None,
        clock: Callable[[], float] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.downloader = downloader
        self.root_url = self._canonical_member_url(root_url)
        self.headers = dict(headers)
        # The composition root decides whether this operation may use a user proxy.
        self.upstream_proxy = upstream_proxy if allow_upstream_proxy else None
        self.domain_policy = domain_policy
        self._clock = clock or time.time
        self._monotonic_clock = monotonic_clock or time.monotonic
        now = float(self._clock())
        self.capability = capability or HlsCapability(
            task_id=secrets.token_urlsafe(18),
            secret=secrets.token_bytes(32),
            expires_at=int(now) + _CAPABILITY_TTL_SECONDS,
        )
        if self.capability.expires_at - now > _CAPABILITY_TTL_SECONDS:
            raise HlsCapabilityError("HLS capability expiry exceeds the 15 minute TTL")
        self._monotonic_deadline = float(self._monotonic_clock()) + max(
            0.0, self.capability.expires_at - now
        )
        self.server: _ThreadingHlsProxyServer | None = None
        self.thread: threading.Thread | None = None
        self.base_url = ""
        self.url = ""
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._request_condition = threading.Condition(self._lock)
        root_kind = "playlist" if looks_like_hls_playlist_url(self.root_url, "") else "unknown"
        self._members: dict[str, _HlsMember] = {
            self.root_url: _HlsMember(self.root_url, root_kind, None, "root", 0)
        }
        self._revoked = False
        self._credential_origin = self._url_origin(self.root_url)
        self._request_slots = _PROCESS_REQUEST_SLOTS
        self._active_requests = 0
        self._handler_thread_ids: set[int] = set()
        self._completed_members: set[str] = set()
        self._segment_total = 0
        self._segment_completed = 0
        self._bytes_served = 0

    def start(self) -> "_LocalHlsProxy":
        with self._lifecycle_lock:
            with self._lock:
                if self._revoked:
                    raise HlsCapabilityError("local HLS capability is revoked")
                existing_server, existing_thread = self.server, self.thread
            if existing_server is not None or existing_thread is not None:
                if self._listener_is_ready(existing_server, existing_thread):
                    return self
                self._cleanup_listener(
                    existing_server,
                    existing_thread,
                    timeout=_STOP_TIMEOUT_SECONDS,
                )

            server = _ThreadingHlsProxyServer(("127.0.0.1", 0), _HlsProxyHandler)
            server.owner = self  # type: ignore[attr-defined]
            host, port = server.server_address[:2]
            host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
            thread = threading.Thread(
                target=self._run_listener,
                args=(server,),
                name="ucp-hls-proxy",
                daemon=True,
            )
            with self._lock:
                self.base_url = f"http://{host_text}:{port}"
                self.url = self.local_url_for(self.root_url)
                self.server = server
                self.thread = thread
            try:
                thread.start()
                self._wait_until_listener_ready(server, thread)
            except BaseException as start_exc:
                try:
                    self._cleanup_listener(
                        server,
                        thread,
                        timeout=_STOP_TIMEOUT_SECONDS,
                    )
                except HlsProxyLifecycleError as cleanup_exc:
                    raise cleanup_exc from start_exc
                raise
            return self

    def stop(self) -> None:
        self.revoke()
        with self._lifecycle_lock:
            with self._lock:
                server, thread = self.server, self.thread
                if server is None and thread is None:
                    self.base_url = ""
                    self.url = ""
                    return
            self._cleanup_listener(server, thread, timeout=_STOP_TIMEOUT_SECONDS)

    @staticmethod
    def _run_listener(server: _ThreadingHlsProxyServer) -> None:
        try:
            server.serve_forever(poll_interval=_SERVER_POLL_INTERVAL_SECONDS)
        except BaseException as exc:
            server.listener_error = exc
        finally:
            server.stopped_event.set()

    @staticmethod
    def _thread_is_alive(thread: threading.Thread | None) -> bool:
        if thread is None:
            return False
        try:
            return bool(thread.is_alive())
        except Exception:
            return True

    @staticmethod
    def _listener_socket_is_closed(server: _ThreadingHlsProxyServer | None) -> bool:
        if server is None:
            return True
        socket_object = getattr(server, "socket", None)
        fileno = getattr(socket_object, "fileno", None)
        if not callable(fileno):
            return False
        try:
            return int(fileno()) < 0
        except (OSError, TypeError, ValueError):
            return False

    def _listener_is_ready(
        self,
        server: _ThreadingHlsProxyServer | None,
        thread: threading.Thread | None,
    ) -> bool:
        ready_event = getattr(server, "ready_event", None)
        return bool(
            server is not None
            and thread is not None
            and self._thread_is_alive(thread)
            and not self._listener_socket_is_closed(server)
            and isinstance(ready_event, threading.Event)
            and ready_event.is_set()
        )

    def _wait_until_listener_ready(
        self,
        server: _ThreadingHlsProxyServer,
        thread: threading.Thread,
    ) -> None:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._listener_is_ready(server, thread):
                return
            if server.stopped_event.is_set() or not self._thread_is_alive(thread):
                break
            server.ready_event.wait(timeout=0.01)
        if server.listener_error is not None:
            raise HlsProxyLifecycleError("local HLS listener failed during startup") from server.listener_error
        raise HlsProxyLifecycleError("local HLS listener did not become ready")

    def _wait_for_request_convergence(self, deadline: float) -> bool:
        current_ident = threading.get_ident()
        with self._request_condition:
            if current_ident in self._handler_thread_ids:
                return self._active_requests == 0
            while self._active_requests:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._request_condition.wait(timeout=remaining)
            return True

    def _cleanup_listener(
        self,
        server: _ThreadingHlsProxyServer | None,
        thread: threading.Thread | None,
        *,
        timeout: float,
    ) -> None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        current_thread = threading.current_thread()
        ready_event = getattr(server, "ready_event", None)
        listener_entered_loop = bool(
            isinstance(ready_event, threading.Event) and ready_event.is_set()
        )
        shutdown_timed_out = False
        if (
            server is not None
            and listener_entered_loop
            and self._thread_is_alive(thread)
            and thread is not current_thread
        ):
            shutdown_done = threading.Event()
            shutdown_errors: list[BaseException] = []

            def request_shutdown() -> None:
                try:
                    server.shutdown()
                except BaseException as exc:
                    shutdown_errors.append(exc)
                finally:
                    shutdown_done.set()

            try:
                threading.Thread(
                    target=request_shutdown,
                    name="ucp-hls-proxy-shutdown",
                    daemon=True,
                ).start()
            except Exception as exc:
                shutdown_errors.append(exc)
                shutdown_done.set()
            shutdown_timed_out = not shutdown_done.wait(
                timeout=max(0.0, deadline - time.monotonic())
            )
            for exc in shutdown_errors:
                _log_diagnostic_best_effort("M3U8Proxy", "shutdown_server", exc)
        if server is not None:
            try:
                server.server_close()
            except Exception as exc:
                _log_diagnostic_best_effort(
                    "M3U8Proxy",
                    "close_server",
                    exc,
                    details={"task_id": self.capability.task_id},
                )
        if thread is not None and thread is not current_thread and self._thread_is_alive(thread):
            try:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            except Exception as exc:
                _log_diagnostic_best_effort(
                    "M3U8Proxy",
                    "join_server_thread",
                    exc,
                    details={"task_id": self.capability.task_id},
                )

        listener_stopped = not self._thread_is_alive(thread)
        socket_closed = self._listener_socket_is_closed(server)
        requests_stopped = self._wait_for_request_convergence(deadline)
        incomplete = []
        if shutdown_timed_out:
            incomplete.append("server shutdown")
        if not listener_stopped:
            incomplete.append("listener thread")
        if not socket_closed:
            incomplete.append("listener socket")
        if not requests_stopped:
            incomplete.append("active request handlers")
        if incomplete:
            raise HlsProxyLifecycleError(
                f"local HLS proxy cleanup incomplete: {', '.join(incomplete)}"
            )

        with self._lock:
            if self.server is server and self.thread is thread:
                self.server = None
                self.thread = None
                self.base_url = ""
                self.url = ""

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True
            self._members.clear()

    @property
    def members(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._members)

    def acquire_request_slot(self) -> bool:
        with self._request_condition:
            if self._revoked or not self._request_slots.acquire(blocking=False):
                return False
            self._active_requests += 1
            return True

    def release_request_slot(self) -> None:
        with self._request_condition:
            if self._active_requests <= 0:
                raise RuntimeError("local HLS request slot accounting underflow")
            self._active_requests -= 1
            self._request_slots.release()
            self._request_condition.notify_all()

    def mark_request_handler_started(self) -> None:
        with self._request_condition:
            self._handler_thread_ids.add(threading.get_ident())

    def mark_request_handler_stopped(self) -> None:
        with self._request_condition:
            self._handler_thread_ids.discard(threading.get_ident())

    @staticmethod
    def _canonical_member_url(url: str) -> str:
        if type(url) is not str:
            raise HlsCapabilityError("HLS upstream URL must be a string")
        value = url
        if len(value) > _MAX_UPSTREAM_URL_CHARS:
            raise HlsCapabilityError("HLS upstream URL exceeds size limit")
        canonical = canonicalize_request_target(value).url
        if len(canonical) > _MAX_UPSTREAM_URL_CHARS:
            raise HlsCapabilityError("HLS upstream URL exceeds size limit")
        return canonical

    @staticmethod
    def _encode_member_url(url: str) -> str:
        return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")

    def _signature(self, upstream_url: str) -> str:
        payload = b"ucp-hls-v1\0" + b"\0".join(
            (
                self.capability.task_id.encode("utf-8"),
                str(self.capability.expires_at).encode("ascii"),
                upstream_url.encode("utf-8"),
            )
        )
        return hmac.new(self.capability.secret, payload, hashlib.sha256).hexdigest()

    def local_url_for(self, upstream_url: str) -> str:
        canonical = self._canonical_member_url(upstream_url)
        query = urllib.parse.urlencode(
            {
                "task": self.capability.task_id,
                "exp": str(self.capability.expires_at),
                "u": self._encode_member_url(canonical),
                "sig": self._signature(canonical),
            }
        )
        return f"{self.base_url}/hls?{query}"

    def verify_path(self, path: str) -> str | None:
        if type(path) is not str or len(path) > _MAX_CAPABILITY_PATH_CHARS:
            return None
        try:
            parts = urllib.parse.urlsplit(path)
            if parts.scheme or parts.netloc or parts.path != "/hls" or parts.fragment:
                return None
            pairs = urllib.parse.parse_qsl(
                parts.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=4,
            )
        except (TypeError, ValueError):
            return None
        if len(pairs) != 4 or {key for key, _value in pairs} != {"task", "exp", "u", "sig"}:
            return None
        values = {key: value for key, value in pairs}
        if any(not value for value in values.values()):
            return None
        canonical_query = urllib.parse.urlencode(
            [(key, values[key]) for key in ("task", "exp", "u", "sig")]
        )
        if parts.query != canonical_query:
            return None
        if not hmac.compare_digest(values["task"], self.capability.task_id):
            return None
        expected_expiry = str(self.capability.expires_at)
        if values["exp"] != expected_expiry:
            return None
        if float(self._clock()) >= self.capability.expires_at:
            return None
        if float(self._monotonic_clock()) >= self._monotonic_deadline:
            return None
        encoded_url = values["u"]
        if len(encoded_url) > _MAX_ENCODED_URL_CHARS:
            return None
        try:
            padding = "=" * (-len(encoded_url) % 4)
            decoded_bytes = base64.b64decode(
                (encoded_url + padding).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            decoded_url = decoded_bytes.decode("utf-8")
            canonical = self._canonical_member_url(decoded_url)
        except (UnicodeError, ValueError, binascii.Error, HlsCapabilityError):
            return None
        if decoded_url != canonical or self._encode_member_url(canonical) != encoded_url:
            return None
        signature = values["sig"]
        if _SIGNATURE.fullmatch(signature) is None:
            return None
        if not hmac.compare_digest(signature, self._signature(canonical)):
            return None
        with self._lock:
            if self._revoked or canonical not in self._members:
                return None
        return canonical

    def upstream_url_from_path(self, path: str) -> str:
        upstream_url = self.verify_path(path)
        if upstream_url is None:
            raise HlsCapabilityError("invalid or expired local HLS capability")
        return upstream_url

    @staticmethod
    def _url_origin(url: str) -> tuple[str, str, int]:
        target = canonicalize_request_target(url)
        return target.scheme, target.host, target.port

    def _require_active_member(self, upstream_url: str) -> _HlsMember:
        canonical = self._canonical_member_url(upstream_url)
        with self._lock:
            member = self._members.get(canonical)
            if self._revoked or member is None:
                raise HlsCapabilityError("HLS resource is not authorized for this task")
            return member

    def _canonical_discovered_url(self, parent_url: str, resource_url: str) -> str:
        if "{$" in resource_url:
            raise HlsCapabilityError("HLS variable substitution is not supported")
        return self._canonical_member_url(urllib.parse.urljoin(parent_url, resource_url))

    def authorize_playlist_resource(
        self,
        parent_url: str,
        resource_url: str,
        *,
        kind: str = "auxiliary",
    ) -> None:
        parent = self._canonical_member_url(parent_url)
        with self._lock:
            parent_member = self._members.get(parent)
            if self._revoked or parent_member is None:
                raise HlsCapabilityError("HLS parent resource is not authorized")
        child = self._canonical_discovered_url(parent, resource_url)
        with self._lock:
            if self._revoked or self._members.get(parent) != parent_member:
                raise HlsCapabilityError("HLS parent authorization changed")
            depth = parent_member.depth + 1
            if depth > _MAX_PLAYLIST_DEPTH:
                raise HlsCapabilityError("HLS playlist nesting exceeds limit")
            if child not in self._members and len(self._members) >= _MAX_TASK_MEMBERS:
                raise HlsCapabilityError("HLS task member limit exceeded")
        if self.domain_policy is not None:
            self.domain_policy.require_public_url(child)
        with self._lock:
            if self._revoked or self._members.get(parent) != parent_member:
                raise HlsCapabilityError("HLS parent authorization changed")
            if child not in self._members and len(self._members) >= _MAX_TASK_MEMBERS:
                raise HlsCapabilityError("HLS task member limit exceeded")
            self._members.setdefault(
                child,
                _HlsMember(child, kind, parent, "playlist", depth),
            )

    @staticmethod
    def _playlist_resource_kind(tag: str, resource_url: str) -> str:
        if tag in {
            "#EXT-X-MEDIA",
            "#EXT-X-I-FRAME-STREAM-INF",
            "#EXT-X-IMAGE-STREAM-INF",
            "#EXT-X-RENDITION-REPORT",
        }:
            return "playlist"
        if tag in {"#EXT-X-KEY", "#EXT-X-SESSION-KEY"}:
            return "key"
        if tag == "#EXT-X-MAP":
            return "map"
        if tag in {"#EXT-X-PART", "#EXT-X-PRELOAD-HINT"}:
            return "media"
        path = urllib.parse.urlsplit(resource_url).path.lower()
        return "playlist" if path.endswith(".m3u8") else "auxiliary"

    def _playlist_resources(self, parent_url: str, playlist_text: str) -> list[tuple[str, str]]:
        if len(playlist_text) > _MAX_PLAYLIST_CHARS:
            raise HlsCapabilityError("HLS playlist exceeds size limit")
        lines = playlist_text.splitlines()
        if len(lines) > _MAX_PLAYLIST_LINES:
            raise HlsCapabilityError("HLS playlist line limit exceeded")
        resources: list[tuple[str, str]] = []
        pending_variant = False
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                tag = line.split(":", 1)[0].upper()
                if pending_variant:
                    raise HlsCapabilityError("HLS variant URI is missing")
                if tag.startswith(_FORBIDDEN_PLAYLIST_TAGS):
                    raise HlsCapabilityError(f"unsupported HLS control tag: {tag}")
                matches = list(_URI_ATTRIBUTE.finditer(line))
                if matches and tag not in _URI_RESOURCE_TAGS:
                    raise HlsCapabilityError(f"unsupported HLS URI-bearing tag: {tag}")
                residual = _URI_ATTRIBUTE.sub("", line)
                if _UNQUOTED_URI_ATTRIBUTE.search(residual):
                    raise HlsCapabilityError("HLS URI attributes must be quoted")
                for match in matches:
                    raw_url = match.group(2)
                    resources.append(
                        (
                            self._canonical_discovered_url(parent_url, raw_url),
                            self._playlist_resource_kind(tag, raw_url),
                        )
                    )
                pending_variant = tag == "#EXT-X-STREAM-INF"
                continue
            kind = "playlist" if pending_variant else self._playlist_resource_kind("", line)
            resources.append((self._canonical_discovered_url(parent_url, line), kind))
            pending_variant = False
        if pending_variant:
            raise HlsCapabilityError("HLS variant URI is missing")
        return resources

    def record_playlist(self, parent_url: str, playlist_text: str) -> str:
        parent = self._canonical_member_url(parent_url)
        parent_member = self._require_active_member(parent)
        resources = self._playlist_resources(parent, playlist_text)
        resources_by_url: dict[str, str] = {}
        for resource_url, kind in resources:
            if resource_url not in resources_by_url or kind == "playlist":
                resources_by_url[resource_url] = kind
        unique_resources = list(resources_by_url.items())
        with self._lock:
            current_parent = self._members.get(parent)
            if self._revoked or current_parent != parent_member:
                raise HlsCapabilityError("HLS parent authorization changed")
            depth = parent_member.depth + 1
            if depth > _MAX_PLAYLIST_DEPTH:
                raise HlsCapabilityError("HLS playlist nesting exceeds limit")
            new_urls = [url for url, _kind in unique_resources if url not in self._members]
            if len(self._members) + len(new_urls) > _MAX_TASK_MEMBERS:
                raise HlsCapabilityError("HLS task member limit exceeded")
        if self.domain_policy is not None:
            for resource_url in new_urls:
                self.domain_policy.require_public_url(resource_url)
        with self._lock:
            current_parent = self._members.get(parent)
            if self._revoked or current_parent != parent_member:
                raise HlsCapabilityError("HLS parent authorization changed")
            new_urls = [url for url, _kind in unique_resources if url not in self._members]
            if len(self._members) + len(new_urls) > _MAX_TASK_MEMBERS:
                raise HlsCapabilityError("HLS task member limit exceeded")
            for resource_url, kind in unique_resources:
                self._members.setdefault(
                    resource_url,
                    _HlsMember(resource_url, kind, parent, "playlist", depth),
                )
        self._record_playlist_progress(playlist_text)
        return rewrite_hls_playlist_for_proxy(playlist_text, parent, self.local_url_for)

    def authorize_redirect_chain(self, requested_url: str, redirect_chain: tuple[str, ...]) -> str:
        requested = self._canonical_member_url(requested_url)
        with self._lock:
            member = self._members.get(requested)
            if self._revoked or member is None:
                raise HlsCapabilityError("HLS redirect source is not authorized")

        if type(redirect_chain) is not tuple or not redirect_chain:
            raise HlsCapabilityError("HLS redirect provenance must be a non-empty tuple")
        chain = tuple(self._canonical_member_url(url) for url in redirect_chain)
        if chain[0] != requested:
            raise HlsCapabilityError("HLS redirect chain must start with the requested URL")
        targets = chain[1:]
        for target_url in targets:
            if self.domain_policy is not None:
                self.domain_policy.require_public_url(target_url)
        with self._lock:
            if self._revoked or self._members.get(requested) != member:
                raise HlsCapabilityError("HLS redirect source authorization changed")
            new_urls = {url for url in targets if url not in self._members}
            if len(self._members) + len(new_urls) > _MAX_TASK_MEMBERS:
                raise HlsCapabilityError("HLS task member limit exceeded")
            previous = requested
            for target_url in targets:
                self._members.setdefault(
                    target_url,
                    _HlsMember(target_url, member.kind, previous, "redirect", member.depth),
                )
                previous = target_url
        return targets[-1] if targets else requested

    def _authorize_redirect_metadata(
        self,
        requested_url: str,
        final_url: str,
        redirect_chain: tuple[str, ...],
    ) -> str:
        requested = self._require_active_member(requested_url).url
        final = self._canonical_member_url(final_url)
        if not redirect_chain:
            if final != requested:
                raise HlsCapabilityError("HLS response omitted redirect provenance")
            return requested
        if type(redirect_chain) is not tuple:
            raise HlsCapabilityError("HLS redirect provenance must be a tuple")
        canonical_chain = tuple(self._canonical_member_url(url) for url in redirect_chain)
        if canonical_chain[-1] != final:
            raise HlsCapabilityError("HLS redirect chain final URL does not match response URL")
        authorized_final = self.authorize_redirect_chain(requested, canonical_chain)
        if authorized_final != final:  # defense in depth for future chain formats
            raise HlsCapabilityError("HLS redirect authorization final URL mismatch")
        return authorized_final

    def _authorize_response_url(self, requested_url: str, response: Any) -> str:
        requested = self._require_active_member(requested_url).url
        chain = tuple(getattr(response, "redirect_chain", ()) or ())
        final_url = getattr(response, "url", "") or requested
        return self._authorize_redirect_metadata(requested, final_url, chain)

    def upstream_headers_for(self, upstream_url: str) -> dict[str, str]:
        canonical = self._require_active_member(upstream_url).url
        headers = self.downloader._headers_for_hls_proxy_upstream(canonical, self.headers)
        cross_origin = self._url_origin(canonical) != self._credential_origin
        blocked = set(_ALWAYS_DROP_UPSTREAM_HEADERS)
        if cross_origin:
            blocked.update(_CROSS_ORIGIN_CREDENTIAL_HEADERS)
        return {key: value for key, value in headers.items() if key.lower() not in blocked}

    def fetch(self, upstream_url: str) -> tuple[int, str, bytes]:
        requested_url = self._require_active_member(upstream_url).url
        upstream_headers = self.upstream_headers_for(requested_url)
        result = self.downloader._hls_proxy_fetch_upstream(
            requested_url,
            upstream_headers,
            self.upstream_proxy,
            domain_policy=self.domain_policy,
        )
        status, content_type, body = result[:3]
        if len(result) != 5:
            raise HlsCapabilityError("HLS fetch returned invalid redirect metadata")
        chain = result[4]
        if type(chain) is not tuple:
            raise HlsCapabilityError("HLS fetch redirect provenance must be a tuple")
        resolved_url = self._authorize_redirect_metadata(requested_url, result[3], chain)
        if looks_like_hls_playlist(resolved_url, content_type, body):
            text = body.decode("utf-8", errors="replace")
            rewritten = self.record_playlist(resolved_url, text)
            return 200, "application/vnd.apple.mpegurl; charset=utf-8", rewritten.encode("utf-8")
        self._record_resource(resolved_url, len(body))
        return status, content_type, body

    def serve(self, handler: http.server.BaseHTTPRequestHandler, upstream_url: str) -> None:
        requested_member = self._require_active_member(upstream_url)
        requested_url = requested_member.url
        upstream_headers = self.upstream_headers_for(requested_url)
        # ffmpeg 可能通过代理随机定位 MP4 数据；必须转发 Range 条件头，
        # 否则每次请求都会退化为默认的 ``bytes=0-``，导致拖动和续传失效。
        request_headers = getattr(handler, "headers", {})
        get_request_header = getattr(request_headers, "get", None)
        if callable(get_request_header):
            for header_name in ("Range", "If-Range"):
                header_value = str(get_request_header(header_name, "") or "").strip()
                if header_value:
                    upstream_headers[header_name] = self._validate_forwarded_header(
                        header_name, header_value
                    )
        response = self.downloader._hls_proxy_open_upstream(
            requested_url,
            upstream_headers,
            self.upstream_proxy,
            domain_policy=self.domain_policy,
        )
        try:
            resolved_url = self._authorize_response_url(requested_url, response)
            status = int(getattr(response, "status_code", 0) or 0)
            response_headers = {
                str(key).lower(): str(value)
                for key, value in (getattr(response, "headers", {}) or {}).items()
            }
            content_type = response_headers.get("content-type", "")
            body_preview = bytes(getattr(response, "content", b"") or b"")[:4096]
            is_playlist = requested_member.kind == "playlist" or looks_like_hls_playlist(
                resolved_url,
                content_type,
                body_preview,
            )
            if status in (200, 206) and is_playlist:
                body = response_content_bytes(response)
                text = body.decode("utf-8", errors="replace")
                rewritten = self.record_playlist(resolved_url, text)
                payload = rewritten.encode("utf-8")
                handler.send_response(200)
                handler.send_header("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8")
                handler.send_header("Content-Length", str(len(payload)))
                handler.end_headers()
                handler.wfile.write(payload)
                return

            handler.send_response(status)
            handler.send_header("Content-Type", content_type or "application/octet-stream")
            for header_name in (
                "Content-Length",
                "Content-Range",
                "Accept-Ranges",
                "ETag",
                "Last-Modified",
                "Cache-Control",
            ):
                header_value = response_headers.get(header_name.lower(), "").strip()
                if header_value:
                    handler.send_header(header_name, header_value)
            handler.end_headers()
            self._stream_response_body(handler, resolved_url, response)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    _log_diagnostic_best_effort(
                        "M3U8Proxy",
                        "close_upstream_response",
                        exc,
                        details={"task_id": self.capability.task_id},
                    )

    @staticmethod
    def _validate_forwarded_header(name: str, value: str) -> str:
        if len(value) > 256 or "\r" in value or "\n" in value:
            raise HlsClientRequestError(f"invalid local HLS {name} header")
        if name.lower() != "range":
            return value
        if len(value) > 128 or "," in value:
            raise HlsClientRequestError("multiple or oversized HLS ranges are not supported")
        match = _RANGE.fullmatch(value)
        if match is None or not any(match.groups()):
            raise HlsClientRequestError("invalid local HLS Range header")
        start, end = match.groups()
        if not start and int(end) == 0:
            raise HlsClientRequestError("invalid local HLS Range suffix")
        if start and end and int(start) > int(end):
            raise HlsClientRequestError("invalid local HLS Range interval")
        return value

    def _stream_response_body(
        self,
        handler: http.server.BaseHTTPRequestHandler,
        upstream_url: str,
        response,
    ) -> None:
        completed = False
        for chunk in response_iter_bytes(response):
            if not chunk:
                continue
            handler.wfile.write(chunk)
            try:
                handler.wfile.flush()
            except Exception as exc:
                _log_diagnostic_best_effort(
                    "M3U8Proxy",
                    "flush_response_body",
                    exc,
                    details={"task_id": self.capability.task_id},
                )
            self._record_resource_bytes(len(chunk))
            completed = True
        if completed:
            self._record_resource_complete(upstream_url)

    def _record_playlist_progress(self, playlist_text: str) -> None:
        segment_total = count_hls_media_entries(playlist_text)
        if segment_total <= 0:
            return
        with self._lock:
            self._segment_total = max(self._segment_total, segment_total)

    def _record_resource(self, upstream_url: str, byte_count: int) -> None:
        self._record_resource_bytes(byte_count)
        self._record_resource_complete(upstream_url)

    def _record_resource_bytes(self, byte_count: int) -> None:
        with self._lock:
            self._bytes_served += max(0, int(byte_count or 0))

    def _record_resource_complete(self, upstream_url: str) -> None:
        canonical = self._canonical_member_url(upstream_url)
        with self._lock:
            if canonical in self._completed_members:
                return
            self._completed_members.add(canonical)
            if looks_like_hls_media_resource(upstream_url) or not looks_like_hls_playlist_url(upstream_url, ""):
                self._segment_completed += 1

    def progress_snapshot(self) -> tuple[int, int]:
        with self._lock:
            segment_total = self._segment_total
            segment_completed = self._segment_completed
            bytes_served = self._bytes_served
        if segment_total > 0:
            progress = 10 + int(min(segment_completed, segment_total) * 85 / segment_total)
            return min(95, max(10, progress)), bytes_served
        return 0, bytes_served
