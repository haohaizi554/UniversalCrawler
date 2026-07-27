"""供 N_m3u8DL-RE 下载器使用的本地受控 HLS 代理。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.server
import re
import secrets
import socketserver
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.debug_logger import debug_logger
from app.exceptions import ExternalToolError
from shared.network.pinned_transport import (
    canonicalize_request_target,
    curl_resolve_options as _pinned_curl_resolve_options,
)

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
_CLIENT_SOCKET_TIMEOUT_SECONDS = 10.0
_URI_ATTRIBUTE = re.compile(r'(?<![A-Z0-9-])URI=(["\'])(.*?)\1', re.IGNORECASE)
_UNQUOTED_URI_ATTRIBUTE = re.compile(r'(?<![A-Z0-9-])URI\s*=', re.IGNORECASE)
_SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")
_ALWAYS_DROP_UPSTREAM_HEADERS = frozenset({"host", "proxy-authorization"})
_CROSS_ORIGIN_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie"})
_FORBIDDEN_PLAYLIST_TAGS = ("#EXT-X-CONTENT-STEERING", "#EXT-X-DEFINE")


class HlsCapabilityError(ExternalToolError):
    """A local request failed capability or membership verification."""


class HlsClientRequestError(ExternalToolError):
    """A local client supplied an invalid forwarding header."""


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
    return _pinned_curl_resolve_options(target, addresses, disable_proxy=True)


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
        try:
            super().process_request_thread(request, client_address)
        finally:
            owner = getattr(self, "owner", None)
            if owner is not None:
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
            debug_logger.log_exception(
                "N_m3u8DL_RE_Downloader",
                "local_hls_proxy_error",
                _diagnostic_exception(exc),
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
        root_kind = "playlist" if looks_like_hls_playlist_url(self.root_url, "") else "unknown"
        self._members: dict[str, _HlsMember] = {
            self.root_url: _HlsMember(self.root_url, root_kind, None, "root", 0)
        }
        self._revoked = False
        self._credential_origin = self._url_origin(self.root_url)
        self._request_slots = threading.BoundedSemaphore(16)
        self._completed_members: set[str] = set()
        self._segment_total = 0
        self._segment_completed = 0
        self._bytes_served = 0

    def start(self) -> "_LocalHlsProxy":
        with self._lock:
            if self._revoked:
                raise HlsCapabilityError("local HLS capability is revoked")
            if self.server is not None:
                return self
            server = _ThreadingHlsProxyServer(("127.0.0.1", 0), _HlsProxyHandler)
            server.owner = self  # type: ignore[attr-defined]
            host, port = server.server_address[:2]
            host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
            self.base_url = f"http://{host_text}:{port}"
            self.url = self.local_url_for(self.root_url)
            thread = threading.Thread(
                target=server.serve_forever,
                name="ucp-hls-proxy",
                daemon=True,
            )
            self.server = server
            self.thread = thread
            thread.start()
            return self

    def stop(self) -> None:
        self.revoke()
        with self._lock:
            server, thread = self.server, self.thread
            self.server = None
            self.thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True
            self._members.clear()

    @property
    def members(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._members)

    def acquire_request_slot(self) -> bool:
        return self._request_slots.acquire(blocking=False)

    def release_request_slot(self) -> None:
        self._request_slots.release()

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
                except (OSError, RuntimeError, AttributeError) as exc:
                    debug_logger.log_exception(
                        "M3U8Proxy",
                        "close_upstream_response",
                        _diagnostic_exception(exc),
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
            except (BrokenPipeError, OSError, RuntimeError) as exc:
                debug_logger.log_exception(
                    "M3U8Proxy",
                    "flush_response_body",
                    _diagnostic_exception(exc),
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
