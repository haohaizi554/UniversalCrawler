"""Canonical, DNS-pinned curl transport for public network operations."""

from __future__ import annotations

import ipaddress
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from shared.runtime_options import (
    PUBLIC_DOMAIN_POLICY,
    DomainPolicyEngine,
    DomainPolicyViolation,
)

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_LEGACY_NUMERIC_IPV4_COMPONENT = re.compile(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)\Z")
_CURL_WRITEFUNC_ERROR = 0xFFFFFFFF
_SENSITIVE_REDIRECT_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)


@dataclass(frozen=True, slots=True)
class CanonicalRequestTarget:
    """One canonical authority shared by policy, DNS pinning, and curl."""

    url: str
    scheme: str
    host: str
    port: int
    authority: str


@dataclass(frozen=True, slots=True)
class PinnedResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]
    body: bytes
    redirect_chain: tuple[str, ...] = ()

    @property
    def content(self) -> bytes:
        """Match the response attribute consumed by existing downloader code."""

        return self.body

    @property
    def text(self) -> str:
        """Decode bounded response bytes without exposing a mutable stream."""

        return self.body.decode("utf-8", errors="replace")

    def close(self) -> None:
        """Provide response compatibility; the private curl handle is already closed."""

    def iter_content(self, chunk_size: int = 256 * 1024):
        """Yield bounded response bytes using the downloader streaming protocol."""

        size = max(1, int(chunk_size))
        for offset in range(0, len(self.body), size):
            yield self.body[offset : offset + size]


def canonicalize_host(host: str) -> str:
    """Return one unambiguous ASCII host or fail before DNS is consulted."""

    if type(host) is not str:
        raise DomainPolicyViolation("host must be a string")
    if not host or host != host.strip() or any(ord(char) < 0x20 for char in host):
        raise DomainPolicyViolation("host is invalid")
    terminal_dots = len(host) - len(host.rstrip("."))
    if terminal_dots > 1:
        raise DomainPolicyViolation("host has multiple terminal dots")
    source = host[:-1] if terminal_dots == 1 else host
    if not source or "%" in source:
        raise DomainPolicyViolation("host is invalid")

    try:
        return ipaddress.ip_address(source).compressed.lower()
    except ValueError:
        pass

    numeric_components = source.split(".")
    if 1 <= len(numeric_components) <= 4 and all(
        _LEGACY_NUMERIC_IPV4_COMPONENT.fullmatch(component)
        for component in numeric_components
    ):
        raise DomainPolicyViolation("host uses ambiguous numeric IPv4 syntax")

    labels = numeric_components
    if any(not label for label in labels):
        raise DomainPolicyViolation("host contains an empty label")
    canonical_labels: list[str] = []
    for label in labels:
        try:
            canonical = label.encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError) as exc:
            raise DomainPolicyViolation("host contains an invalid IDNA label") from exc
        if len(canonical) > 63 or _HOST_LABEL.fullmatch(canonical) is None:
            raise DomainPolicyViolation("host contains an invalid IDNA label")
        canonical_labels.append(canonical)
    canonical_host = ".".join(canonical_labels)
    if len(canonical_host) > 253:
        raise DomainPolicyViolation("host is too long")
    return canonical_host


def canonicalize_request_target(url: str) -> CanonicalRequestTarget:
    """Canonicalize an HTTP(S) URL without preserving userinfo or fragments."""

    if type(url) is not str or not url or url != url.strip():
        raise DomainPolicyViolation("invalid public request URL")
    if any(ord(char) < 0x20 for char in url):
        raise DomainPolicyViolation("invalid public request URL")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DomainPolicyViolation("invalid public request URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise DomainPolicyViolation("invalid public request URL scheme")
    if parts.username is not None or parts.password is not None:
        raise DomainPolicyViolation("invalid public request URL userinfo")
    host = canonicalize_host(parts.hostname or "")
    if parts.netloc.endswith(":"):
        raise DomainPolicyViolation("invalid public request port")
    try:
        explicit_port = parts.port
    except ValueError as exc:
        raise DomainPolicyViolation("invalid public request port") from exc
    port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise DomainPolicyViolation("invalid public request port")
    authority_host = f"[{host}]" if ":" in host else host
    authority = f"{authority_host}:{port}"
    path = parts.path or "/"
    if not path.startswith("/"):
        raise DomainPolicyViolation("invalid public request path")
    canonical_url = urlunsplit((scheme, authority, path, parts.query, ""))
    return CanonicalRequestTarget(canonical_url, scheme, host, port, authority)


def curl_resolve_options(
    target: CanonicalRequestTarget,
    addresses: Sequence[str],
    *,
    disable_proxy: bool = True,
) -> dict[Any, Any]:
    """Build one curl resolve map from already policy-validated IP addresses."""

    from curl_cffi.const import CurlOpt

    if not isinstance(target, CanonicalRequestTarget):
        raise TypeError("target must be a CanonicalRequestTarget")
    pinned: list[str] = []
    seen: set[str] = set()
    for raw_address in addresses:
        if type(raw_address) is not str:
            raise DomainPolicyViolation("resolved address is invalid")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise DomainPolicyViolation("resolved address is invalid") from exc
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise DomainPolicyViolation("resolved address is not public")
        normalized = address.compressed.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        pinned.append(f"[{normalized}]" if address.version == 6 else normalized)
    if not pinned:
        raise DomainPolicyViolation("public host has no validated addresses")
    try:
        literal_host = ipaddress.ip_address(target.host).compressed.lower()
    except ValueError:
        literal_host = ""
    if literal_host:
        if literal_host not in seen:
            raise DomainPolicyViolation("literal host is not among validated addresses")
        return {CurlOpt.PROXY: ""} if disable_proxy else {}
    resolve_host = f"[{target.host}]" if ":" in target.host else target.host
    options: dict[Any, Any] = {
        CurlOpt.RESOLVE: [f"{resolve_host}:{target.port}:{','.join(pinned)}"]
    }
    if disable_proxy:
        options[CurlOpt.PROXY] = ""
    return options


def _default_session_factory():
    from curl_cffi import requests as curl_requests

    return curl_requests.Session(impersonate="chrome")


def _copy_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    copied: dict[str, str] = {}
    for key, value in headers.items():
        if type(key) is not str or type(value) is not str:
            raise TypeError("request headers must contain only strings")
        if key.lower() in {"host", "proxy-authorization"}:
            continue
        copied[key] = value
    return copied


def _response_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return {}
    return {
        key: value
        for key, value in headers.items()
        if type(key) is str and type(value) is str
    }


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


class PinnedTransport:
    """Perform one operation in one private curl session with pinned DNS."""

    def __init__(
        self,
        *,
        policy: DomainPolicyEngine | Any = PUBLIC_DOMAIN_POLICY,
        session_factory: Callable[[], Any] | None = None,
        timeout: float = 60.0,
        max_response_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._policy = policy
        self._session_factory = session_factory or _default_session_factory
        self._timeout = float(timeout)
        self._max_response_bytes = int(max_response_bytes)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        max_redirects: int = 5,
    ) -> PinnedResponse:
        normalized_method = str(method or "").upper()
        if normalized_method not in {
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "OPTIONS",
            "HEAD",
            "TRACE",
            "PATCH",
        }:
            raise ValueError("unsupported HTTP method")
        if body is not None and type(body) is not bytes:
            raise TypeError("body must be bytes or None")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")

        request_headers = _copy_request_headers(headers)
        target = canonicalize_request_target(url)
        redirect_chain = [target.url]
        session: Any | None = None
        base_curl_options: dict[Any, Any] = {}

        def open_session() -> None:
            nonlocal session, base_curl_options
            candidate = self._session_factory()
            options = getattr(candidate, "curl_options", {})
            if not isinstance(options, dict):
                _close_session(candidate)
                raise DomainPolicyViolation("curl session cannot enforce pinned DNS")
            session = candidate
            base_curl_options = dict(options)

        deadline = time.monotonic() + self._timeout
        current_method = normalized_method
        current_body = body
        response: Any | None = None
        try:
            for redirect_count in range(max_redirects + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("public request deadline exceeded")
                addresses = self._policy.resolve_public_addresses(target.url)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("public request deadline exceeded")
                if session is None:
                    open_session()
                if session is None:  # pragma: no cover - open_session either assigns or raises
                    raise RuntimeError("private curl session is unavailable")
                session.curl_options = {
                    **base_curl_options,
                    **curl_resolve_options(target, addresses, disable_proxy=True),
                }
                buffered = bytearray()
                response_too_large = False

                def collect(chunk: bytes) -> int:
                    nonlocal response_too_large
                    if len(buffered) + len(chunk) > self._max_response_bytes:
                        response_too_large = True
                        return _CURL_WRITEFUNC_ERROR
                    buffered.extend(chunk)
                    return len(chunk)

                try:
                    response = session.request(
                        current_method,
                        target.url,
                        headers=request_headers,
                        data=current_body,
                        allow_redirects=False,
                        timeout=remaining,
                        content_callback=collect,
                    )
                except Exception as exc:
                    if response_too_large:
                        raise DomainPolicyViolation(
                            "public response exceeds size limit"
                        ) from exc
                    raise
                status_code = int(getattr(response, "status_code", 0) or 0)
                response_headers = _response_headers(response)
                location = response_headers.get("Location") or response_headers.get("location")
                if status_code not in DomainPolicyEngine.REDIRECT_STATUS_CODES or not location:
                    raw_content = getattr(response, "content", b"") or b""
                    payload = bytes(buffered) if buffered else bytes(raw_content)
                    if len(payload) > self._max_response_bytes:
                        raise DomainPolicyViolation("public response exceeds size limit")
                    result = PinnedResponse(
                        status_code=status_code,
                        url=target.url,
                        headers=response_headers,
                        body=payload,
                        redirect_chain=tuple(redirect_chain),
                    )
                    _close_response(response)
                    response = None
                    return result
                if redirect_count >= max_redirects:
                    raise DomainPolicyViolation("public redirect limit exceeded")

                next_target = canonicalize_request_target(urljoin(target.url, location))
                origin_changed = (target.scheme, target.host, target.port) != (
                    next_target.scheme,
                    next_target.host,
                    next_target.port,
                )
                if origin_changed:
                    request_headers = {
                        key: value
                        for key, value in request_headers.items()
                        if key.lower() not in _SENSITIVE_REDIRECT_HEADERS
                    }
                if status_code == 303 or (
                    status_code in {301, 302} and current_method == "POST"
                ):
                    current_method = "GET"
                    current_body = None
                _close_response(response)
                response = None
                if origin_changed:
                    _close_session(session)
                    session = None
                target = next_target
                redirect_chain.append(target.url)
        finally:
            if response is not None:
                _close_response(response)
            if session is not None:
                _close_session(session)
        raise DomainPolicyViolation("public redirect limit exceeded")
