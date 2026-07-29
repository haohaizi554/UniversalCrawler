"""Canonical, DNS-pinned curl transport for public network operations."""

from __future__ import annotations

import ipaddress
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
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
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_CURL_WRITEFUNC_ERROR = 0xFFFFFFFF
_MAX_TIMEOUT_SECONDS = 86_400.0
_SENSITIVE_REDIRECT_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)
_REDIRECT_BODY_AND_FRAMING_HEADERS = frozenset(
    {
        "content-encoding",
        "content-language",
        "content-length",
        "content-location",
        "content-type",
        "expect",
        "trailer",
        "transfer-encoding",
    }
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
    port = (
        explicit_port
        if explicit_port is not None
        else (443 if scheme == "https" else 80)
    )
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

    return curl_requests.Session(
        impersonate="chrome",
        trust_env=False,
        allow_redirects=False,
    )


def _copy_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise TypeError("request headers must be a mapping")
    copied: dict[str, str] = {}
    for key, value in headers.items():
        if type(key) is not str or type(value) is not str:
            raise TypeError("request headers must contain only strings")
        if _HEADER_NAME.fullmatch(key) is None or any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in value
        ):
            raise DomainPolicyViolation("request header is invalid")
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


def _close_resources(
    response: Any | None,
    session: Any | None,
    *,
    suppress_errors: bool,
) -> None:
    first_error: BaseException | None = None
    for resource, close_resource in (
        (response, _close_response),
        (session, _close_session),
    ):
        if resource is None:
            continue
        try:
            close_resource(resource)
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None and not suppress_errors:
        raise first_error


def _curl_option_value_matches_exactly(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _curl_option_value_matches_exactly(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return bool(actual == expected)


def _curl_options_match_exactly(actual: Any, expected: dict[Any, Any]) -> bool:
    if type(actual) is not dict or len(actual) != len(expected):
        return False
    if {id(option) for option in actual} != {id(option) for option in expected}:
        return False
    return all(
        _curl_option_value_matches_exactly(actual[option], expected_value)
        for option, expected_value in expected.items()
    )


def _real_session_request_state_is_clean(session: Any) -> bool:
    """Reject curl_cffi Session defaults that would be merged into a request."""

    from curl_cffi import requests as curl_requests

    if not isinstance(session, curl_requests.Session):
        return True
    if type(session) is not curl_requests.Session:
        return False
    try:
        retry = getattr(session, "retry", None)
        retry_is_default = retry is None or (
            type(getattr(retry, "count", None)) is int
            and retry.count == 0
            and type(getattr(retry, "delay", None)) in {int, float}
            and float(retry.delay) == 0.0
            and type(getattr(retry, "jitter", None)) in {int, float}
            and float(retry.jitter) == 0.0
            and getattr(retry, "backoff", None) == "linear"
        )
        return bool(
            not session.headers
            and not session.cookies
            and session.auth is None
            and session.base_url is None
            and session.params is None
            and not session.proxies
            and session.proxy_auth is None
            and session.verify is True
            and session.trust_env is False
            and session.ja3 is None
            and session.akamai is None
            and session.extra_fp is None
            and session.impersonate == "chrome"
            and session.default_headers is True
            and session.http_version is None
            and session.interface is None
            and session.cert is None
            and retry_is_default
            and getattr(session, "perk", None) is None
            and getattr(session, "response_class", curl_requests.Response)
            is curl_requests.Response
            and getattr(session, "raise_for_status", False) is False
            and getattr(session, "discard_cookies", False) is False
            and not getattr(session, "curl_infos", ())
            and getattr(session, "debug", False) is False
            and getattr(session, "_thread", None) is None
            and getattr(session, "_closed", False) is False
            and getattr(session, "_use_thread_local_curl", True) is True
            and getattr(session, "_is_customized_curl", False) is False
        )
    except Exception:
        return False


def _reset_real_session_handle(session: Any) -> None:
    """Reset an injected real handle so options outside curl_options cannot survive."""

    from curl_cffi import requests as curl_requests

    if not isinstance(session, curl_requests.Session):
        return
    try:
        reset = session.curl.reset
        if not callable(reset):
            raise TypeError("curl reset is unavailable")
        reset()
    except BaseException as exc:
        if not isinstance(exc, Exception):
            raise
        raise DomainPolicyViolation(
            "curl session cannot reset inherited request state"
        ) from exc


def _bounded_response_body(
    response: Any,
    buffered: bytearray,
    max_response_bytes: int,
) -> bytes:
    raw_content = getattr(response, "content", b"") or b""
    try:
        callback_body = bytes(buffered)
        raw_body = bytes(raw_content)
    except (TypeError, ValueError) as exc:
        raise DomainPolicyViolation("public response body is invalid") from exc
    if (
        len(callback_body) > max_response_bytes
        or len(raw_body) > max_response_bytes
    ):
        raise DomainPolicyViolation("public response exceeds size limit")
    if callback_body and raw_body and callback_body != raw_body:
        raise DomainPolicyViolation("public response has inconsistent response body")
    return callback_body or raw_body


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
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be positive")
        try:
            normalized_timeout = float(timeout)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("timeout must be positive") from exc
        if (
            not math.isfinite(normalized_timeout)
            or normalized_timeout <= 0
            or normalized_timeout > _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout must be positive and at most 86400 seconds")
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._policy = policy
        self._owns_real_session_factory = session_factory is None
        self._session_factory = session_factory or _default_session_factory
        self._timeout = normalized_timeout
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
        if type(method) is not str:
            raise ValueError("unsupported HTTP method")
        normalized_method = method.upper()
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
        if type(max_redirects) is not int or max_redirects < 0:
            raise ValueError("max_redirects must be a non-negative integer")

        request_headers = _copy_request_headers(headers)
        target = canonicalize_request_target(url)
        redirect_chain = [target.url]
        session: Any | None = None

        def open_session() -> None:
            nonlocal session
            candidate = self._session_factory()
            from curl_cffi import requests as curl_requests

            if (
                isinstance(candidate, curl_requests.Session)
                and not self._owns_real_session_factory
            ):
                _close_resources(None, candidate, suppress_errors=True)
                raise DomainPolicyViolation(
                    "real curl sessions must be transport owned"
                )
            try:
                options = candidate.curl_options
            except BaseException as exc:
                _close_resources(None, candidate, suppress_errors=True)
                if not isinstance(exc, Exception):
                    raise
                raise DomainPolicyViolation(
                    "curl session cannot enforce pinned DNS"
                ) from exc
            if type(options) is not dict:
                _close_resources(None, candidate, suppress_errors=True)
                raise DomainPolicyViolation("curl session cannot enforce pinned DNS")
            if not _real_session_request_state_is_clean(candidate):
                _close_resources(None, candidate, suppress_errors=True)
                raise DomainPolicyViolation(
                    "curl session contains inherited request state"
                )
            session = candidate

        deadline = time.monotonic() + self._timeout
        current_method = normalized_method
        current_body = body
        response: Any | None = None
        primary_error: BaseException | None = None
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
                if (
                    session is None
                ):  # pragma: no cover - open_session either assigns or raises
                    raise RuntimeError("private curl session is unavailable")
                _reset_real_session_handle(session)
                pin_curl_options = curl_resolve_options(
                    target, addresses, disable_proxy=True
                )
                from curl_cffi.const import CurlOpt

                authoritative_curl_options = {
                    CurlOpt.NOSIGNAL: 1,
                    CurlOpt.FRESH_CONNECT: 1,
                    CurlOpt.FORBID_REUSE: 1,
                    **pin_curl_options,
                }
                expected_curl_options = deepcopy(authoritative_curl_options)
                try:
                    session.curl_options = authoritative_curl_options
                    effective_curl_options = session.curl_options
                except BaseException as exc:
                    if not isinstance(exc, Exception):
                        raise
                    raise DomainPolicyViolation(
                        "curl session cannot enforce pinned DNS"
                    ) from exc
                if not _curl_options_match_exactly(
                    effective_curl_options, expected_curl_options
                ):
                    raise DomainPolicyViolation(
                        "curl session cannot enforce pinned DNS"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("public request deadline exceeded")
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
                if response_too_large:
                    raise DomainPolicyViolation(
                        "public response exceeds size limit"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError("public request deadline exceeded")
                payload = _bounded_response_body(
                    response,
                    buffered,
                    self._max_response_bytes,
                )
                if time.monotonic() >= deadline:
                    raise TimeoutError("public request deadline exceeded")
                status_code = int(getattr(response, "status_code", 0) or 0)
                response_headers = _response_headers(response)
                location = response_headers.get("Location") or response_headers.get(
                    "location"
                )
                if (
                    status_code not in DomainPolicyEngine.REDIRECT_STATUS_CODES
                    or not location
                ):
                    result = PinnedResponse(
                        status_code=status_code,
                        url=target.url,
                        headers=response_headers,
                        body=payload,
                        redirect_chain=tuple(redirect_chain),
                    )
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
                rewrite_to_get = (status_code == 303 and current_method != "HEAD") or (
                    status_code in {301, 302} and current_method == "POST"
                )
                if rewrite_to_get:
                    current_method = "GET"
                if rewrite_to_get or status_code == 303:
                    current_body = None
                    request_headers = {
                        key: value
                        for key, value in request_headers.items()
                        if key.lower() not in _REDIRECT_BODY_AND_FRAMING_HEADERS
                    }
                redirect_response = response
                response = None
                _close_response(redirect_response)
                if origin_changed:
                    previous_session = session
                    session = None
                    _close_session(previous_session)
                target = next_target
                redirect_chain.append(target.url)
            raise DomainPolicyViolation("public redirect limit exceeded")
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            _close_resources(
                response,
                session,
                suppress_errors=primary_error is not None,
            )
