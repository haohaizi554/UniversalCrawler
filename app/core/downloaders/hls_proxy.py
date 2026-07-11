"""Local HLS proxy used by the N_m3u8DL-RE downloader."""

from __future__ import annotations

import base64
import http.server
import re
import socketserver
import threading
import urllib.parse
from typing import TYPE_CHECKING, Any

from app.debug_logger import debug_logger
from app.exceptions import ExternalToolError

if TYPE_CHECKING:
    from shared.runtime_options import DomainPolicyEngine

    from .m3u8 import N_m3u8DL_RE_Downloader


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

    return re.sub(r"URI=([\"'])(.*?)(?:\1)", replace_uri, line)


class _ThreadingHlsProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _HlsProxyHandler(http.server.BaseHTTPRequestHandler):
    server: _ThreadingHlsProxyServer

    def do_GET(self) -> None:
        owner = getattr(self.server, "owner", None)
        if owner is None:
            self.send_error(500)
            return
        try:
            upstream_url = owner.upstream_url_from_path(self.path)
            owner.serve(self, upstream_url)
        except Exception as exc:
            debug_logger.log_exception(
                "N_m3u8DL_RE_Downloader",
                "local_hls_proxy_error",
                exc,
                context={"path": self.path},
            )
            self.send_error(502)
            return

    def log_message(self, _format: str, *args: Any) -> None:
        return


class _LocalHlsProxy:
    def __init__(
        self,
        downloader: "N_m3u8DL_RE_Downloader",
        root_url: str,
        headers: dict[str, str],
        upstream_proxy: str | None,
        *,
        domain_policy: "DomainPolicyEngine | None" = None,
    ) -> None:
        self.downloader = downloader
        self.root_url = root_url
        self.headers = dict(headers)
        self.upstream_proxy = upstream_proxy
        self.domain_policy = domain_policy
        self.server: _ThreadingHlsProxyServer | None = None
        self.thread: threading.Thread | None = None
        self.base_url = ""
        self.url = ""
        self._lock = threading.Lock()
        self._segment_total = 0
        self._segment_completed = 0
        self._bytes_served = 0

    def start(self) -> "_LocalHlsProxy":
        self.server = _ThreadingHlsProxyServer(("127.0.0.1", 0), _HlsProxyHandler)
        self.server.owner = self  # type: ignore[attr-defined]
        host, port = self.server.server_address[:2]
        host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
        self.base_url = f"http://{host_text}:{port}"
        self.url = self.local_url_for(self.root_url)
        self.thread = threading.Thread(target=self.server.serve_forever, name="ucp-hls-proxy", daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)

    def local_url_for(self, upstream_url: str) -> str:
        token = base64.urlsafe_b64encode(str(upstream_url).encode("utf-8")).decode("ascii")
        return f"{self.base_url}/hls?u={urllib.parse.quote(token)}"

    def upstream_url_from_path(self, path: str) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        token = (query.get("u") or [""])[0]
        if not token:
            return self.root_url
        try:
            return base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ExternalToolError("Invalid local HLS proxy URL token") from exc

    def fetch(self, upstream_url: str) -> tuple[int, str, bytes]:
        upstream_headers = self.downloader._headers_for_hls_proxy_upstream(upstream_url, self.headers)
        status, content_type, body = self.downloader._hls_proxy_fetch_upstream(
            upstream_url,
            upstream_headers,
            self.upstream_proxy,
            domain_policy=self.domain_policy,
        )
        if looks_like_hls_playlist(upstream_url, content_type, body):
            text = body.decode("utf-8", errors="replace")
            self._record_playlist(text)
            rewritten = rewrite_hls_playlist_for_proxy(text, upstream_url, self.local_url_for)
            return 200, "application/vnd.apple.mpegurl; charset=utf-8", rewritten.encode("utf-8")
        self._record_resource(upstream_url, len(body))
        return status, content_type, body

    def serve(self, handler: http.server.BaseHTTPRequestHandler, upstream_url: str) -> None:
        upstream_headers = self.downloader._headers_for_hls_proxy_upstream(upstream_url, self.headers)
        response = self.downloader._hls_proxy_open_upstream(
            upstream_url,
            upstream_headers,
            self.upstream_proxy,
            domain_policy=self.domain_policy,
        )
        try:
            resolved_url = str(getattr(response, "url", "") or upstream_url)
            status = int(getattr(response, "status_code", 0) or 0)
            response_headers = getattr(response, "headers", {}) or {}
            content_type = str(response_headers.get("Content-Type", "") or "")
            if looks_like_hls_playlist_url(resolved_url, content_type):
                body = response_content_bytes(response)
                text = body.decode("utf-8", errors="replace")
                self._record_playlist(text)
                rewritten = rewrite_hls_playlist_for_proxy(text, resolved_url, self.local_url_for)
                payload = rewritten.encode("utf-8")
                handler.send_response(200)
                handler.send_header("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8")
                handler.send_header("Content-Length", str(len(payload)))
                handler.send_header("Access-Control-Allow-Origin", "*")
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
                header_value = str(response_headers.get(header_name) or "").strip()
                if header_value:
                    handler.send_header(header_name, header_value)
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.end_headers()
            self._stream_response_body(handler, resolved_url, response)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except (OSError, RuntimeError, AttributeError) as exc:
                    debug_logger.log_exception("M3U8Proxy", "close_upstream_response", exc, details={"url": upstream_url})

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
                debug_logger.log_exception("M3U8Proxy", "flush_response_body", exc, details={"url": upstream_url})
            self._record_resource_bytes(len(chunk))
            completed = True
        if completed:
            self._record_resource_complete(upstream_url)

    def _record_playlist(self, playlist_text: str) -> None:
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
        with self._lock:
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
