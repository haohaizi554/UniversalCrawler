"""Canonical, DNS-pinned curl transport for public network operations."""

from __future__ import annotations

import ipaddress
import math
import re
import time
import idna
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from inspect import getattr_static
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


@dataclass(frozen=True, slots=True)
class PinnedStreamResult:
    status_code: int
    url: str
    headers: Mapping[str, str]
    bytes_written: int
    total_response_bytes: int
    redirect_chain: tuple[str, ...] = ()


class PinnedTransportNetworkError(RuntimeError):
    """A transient curl/network failure after policy validation succeeded."""


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
            canonical = idna.encode(
                label,
                uts46=True,
                transitional=False,
                std3_rules=True,
            ).decode("ascii").lower()
        except (UnicodeError, ValueError, idna.IDNAError) as exc:
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


@dataclass(slots=True)
class _DirectCurlResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]

    def close(self) -> None:
        return None


class _DirectCurlStreamingSession:
    """Synchronous libcurl adapter with header-before-body backpressure."""

    def __init__(self) -> None:
        self.curl_options: dict[Any, Any] = {}
        self.curl: Any | None = None

    def request(self, method: str, url: str, **kwargs: Any) -> _DirectCurlResponse:
        from curl_cffi import Curl, CurlError
        from curl_cffi.const import CurlInfo, CurlOpt

        previous = self.curl
        self.curl = None
        if previous is not None:
            previous.close()
        curl = Curl()
        self.curl = curl
        curl.impersonate("chrome", default_headers=True)
        header_error: BaseException | None = None
        status_code = 0
        response_headers: dict[str, str] = {}
        response_started = False
        response_start_callback = kwargs.get("response_start_callback")
        header_callback = kwargs.get("header_callback")

        def collect_header(line: bytes) -> int:
            nonlocal header_error, status_code, response_headers, response_started
            try:
                if type(line) is not bytes:
                    raise DomainPolicyViolation("public response header is invalid")
                if callable(header_callback):
                    header_callback(line)
                if line.startswith(b"HTTP/"):
                    match = re.match(
                        rb"HTTP/[0-9]+(?:\.[0-9]+)?[ \t]+([0-9]{3})(?:[ \t]|\r?$)",
                        line,
                    )
                    if match is None:
                        raise DomainPolicyViolation("public response status is invalid")
                    status_code = int(match.group(1))
                    response_headers = {}
                    response_started = False
                elif line in {b"\r\n", b"\n"}:
                    if status_code >= 200 and not response_started:
                        response_started = True
                        if callable(response_start_callback):
                            response_start_callback(status_code, dict(response_headers))
                else:
                    name, separator, value = line.rstrip(b"\r\n").partition(b":")
                    if not separator:
                        raise DomainPolicyViolation("public response header is invalid")
                    decoded_name = name.decode("ascii", errors="strict").strip()
                    decoded_value = value.decode("latin-1", errors="strict").strip()
                    if _HEADER_NAME.fullmatch(decoded_name) is None:
                        raise DomainPolicyViolation("public response header is invalid")
                    if decoded_name in response_headers:
                        response_headers[decoded_name] += f", {decoded_value}"
                    else:
                        response_headers[decoded_name] = decoded_value
                return len(line)
            except BaseException as exc:
                header_error = exc
                return _CURL_WRITEFUNC_ERROR

        headers = kwargs.get("headers") or {}
        encoded_headers = [
            f"{key}: {value}".encode("latin-1", errors="strict")
            for key, value in headers.items()
        ]
        if not any(str(key).lower() == "accept-encoding" for key in headers):
            encoded_headers.append(b"Accept-Encoding: identity")
        curl.setopt(CurlOpt.URL, url.encode("utf-8"))
        curl.setopt(CurlOpt.FOLLOWLOCATION, 0)
        curl.setopt(CurlOpt.HTTPHEADER, encoded_headers)
        curl.setopt(CurlOpt.HEADERFUNCTION, collect_header)
        curl.setopt(CurlOpt.WRITEFUNCTION, kwargs["content_callback"])
        if method == "HEAD":
            curl.setopt(CurlOpt.NOBODY, 1)
        elif method == "GET":
            curl.setopt(CurlOpt.HTTPGET, 1)
        elif method == "POST":
            curl.setopt(CurlOpt.POST, 1)
        else:
            curl.setopt(CurlOpt.CUSTOMREQUEST, method.encode("ascii"))
        body = kwargs.get("data")
        if body is not None:
            curl.setopt(CurlOpt.POSTFIELDS, body)
        for option, value in self.curl_options.items():
            curl.setopt(option, value)
        try:
            curl.perform()
        except CurlError:
            if header_error is not None:
                raise header_error
            raise
        if header_error is not None:
            raise header_error
        status_code = int(curl.getinfo(CurlInfo.RESPONSE_CODE) or status_code)
        effective_url = curl.getinfo(CurlInfo.EFFECTIVE_URL) or url
        if isinstance(effective_url, bytes):
            effective_url = effective_url.decode("utf-8", errors="strict")
        return _DirectCurlResponse(status_code, str(effective_url), response_headers)

    def close(self) -> None:
        curl = self.curl
        self.curl = None
        if curl is not None:
            curl.close()


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


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            return value
    return None


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


def _capture_cleanup_error(
    resource: Any | None,
    close_resource: Callable[[Any], None],
) -> BaseException | None:
    if resource is None:
        return None
    try:
        close_resource(resource)
    except BaseException as exc:
        return exc
    return None


def _preferred_cleanup_error(
    current: BaseException | None,
    candidate: BaseException | None,
) -> BaseException | None:
    if candidate is None:
        return current
    if current is None or (
        isinstance(current, Exception) and not isinstance(candidate, Exception)
    ):
        return candidate
    return current


def _add_exception_note(error: BaseException, note: str) -> None:
    try:
        error.add_note(note)
    except BaseException:
        pass


def _safe_exception_category(error: BaseException) -> str:
    """Classify cleanup failures without invoking attacker-controlled metadata."""
    if isinstance(error, KeyboardInterrupt):
        return "KeyboardInterrupt"
    if isinstance(error, SystemExit):
        return "SystemExit"
    if isinstance(error, GeneratorExit):
        return "GeneratorExit"
    if isinstance(error, LookupError):
        return "LookupError"
    if isinstance(error, RuntimeError):
        return "RuntimeError"
    if isinstance(error, OSError):
        return "OSError"
    if isinstance(error, ValueError):
        return "ValueError"
    if isinstance(error, Exception):
        return "Exception"
    return "BaseException"


def _close_resources(
    response: Any | None,
    session: Any | None,
    *,
    suppress_errors: bool,
    primary_error: BaseException | None = None,
) -> None:
    selected_error: BaseException | None = None
    for resource_name, resource, close_resource in (
        ("response", response, _close_response),
        ("session", session, _close_session),
    ):
        exc = _capture_cleanup_error(resource, close_resource)
        if exc is not None:
            if primary_error is not None:
                _add_exception_note(
                    primary_error,
                    f"{resource_name} cleanup failed: "
                    f"{_safe_exception_category(exc)}",
                )
            selected_error = _preferred_cleanup_error(selected_error, exc)
    if selected_error is not None and not suppress_errors:
        raise selected_error


def _close_streaming_resource(
    resource: Any,
    close_resource: Callable[[Any], None],
    message: str,
) -> None:
    try:
        close_resource(resource)
    except BaseException as exc:
        if not isinstance(exc, Exception):
            raise
        raise PinnedTransportNetworkError(message) from exc


def _close_redirect_response(response: Any, session: Any) -> None:
    response_error = _capture_cleanup_error(response, _close_response)
    if response_error is None:
        return
    session_error = _capture_cleanup_error(session, _close_session)
    selected_error = _preferred_cleanup_error(response_error, session_error)
    if selected_error is None:  # pragma: no cover
        raise RuntimeError("redirect cleanup failed without an error")
    if not isinstance(selected_error, Exception):
        raise selected_error
    raise PinnedTransportNetworkError(
        "public redirect response cleanup failed"
    ) from selected_error


def _raise_candidate_rejection(candidate: Any, rejection: BaseException) -> None:
    cleanup_error = _capture_cleanup_error(candidate, _close_session)
    if cleanup_error is not None:
        if not isinstance(cleanup_error, Exception):
            _add_exception_note(
                cleanup_error,
                "candidate rejection pending: "
                f"{_safe_exception_category(rejection)}",
            )
            raise cleanup_error
        _add_exception_note(
            rejection,
            "session cleanup failed: "
            f"{_safe_exception_category(cleanup_error)}",
        )
    raise rejection


def _validate_session_candidate(
    candidate: Any,
    *,
    owns_real_session_factory: bool,
) -> None:
    from curl_cffi import requests as curl_requests

    if isinstance(candidate, curl_requests.Session) and not owns_real_session_factory:
        _raise_candidate_rejection(
            candidate,
            DomainPolicyViolation("real curl sessions must be transport owned"),
        )
    try:
        getattr_static(candidate, "curl_options")
    except AttributeError:
        _raise_candidate_rejection(
            candidate,
            DomainPolicyViolation("curl session cannot enforce pinned DNS"),
        )
    try:
        options = candidate.curl_options
    except BaseException as exc:
        _close_resources(
            None,
            candidate,
            suppress_errors=True,
            primary_error=exc,
        )
        raise
    if type(options) is not dict:
        _raise_candidate_rejection(
            candidate,
            DomainPolicyViolation("curl session cannot enforce pinned DNS"),
        )
    try:
        state_is_clean = _real_session_request_state_is_clean(candidate)
    except BaseException as exc:
        _close_resources(
            None,
            candidate,
            suppress_errors=True,
            primary_error=exc,
        )
        raise
    if not state_is_clean:
        _raise_candidate_rejection(
            candidate,
            DomainPolicyViolation("curl session contains inherited request state"),
        )


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
            _validate_session_candidate(
                candidate,
                owns_real_session_factory=self._owns_real_session_factory,
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
                try:
                    addresses = self._policy.resolve_public_addresses(target.url)
                except DomainPolicyViolation:
                    raise
                except OSError as exc:
                    raise PinnedTransportNetworkError(
                        "public name resolution failed"
                    ) from exc
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
                except (DomainPolicyViolation, PinnedTransportNetworkError):
                    raise
                except Exception as exc:
                    if response_too_large:
                        raise DomainPolicyViolation(
                            "public response exceeds size limit"
                        ) from exc
                    raise PinnedTransportNetworkError(
                        "public request failed"
                    ) from exc
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
                location = _header_value(response_headers, "location")
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
                try:
                    _close_redirect_response(redirect_response, session)
                except BaseException:
                    session = None
                    raise
                if origin_changed:
                    previous_session = session
                    session = None
                    _close_streaming_resource(
                        previous_session,
                        _close_session,
                        "public redirect session cleanup failed",
                    )
                target = next_target
                redirect_chain.append(target.url)
            raise DomainPolicyViolation("public redirect limit exceeded")
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                _close_resources(
                    response,
                    session,
                    suppress_errors=primary_error is not None,
                    primary_error=primary_error,
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                raise PinnedTransportNetworkError(
                    "public transport cleanup failed"
                ) from exc

    def request_to_sink(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        sink: Callable[[bytes], Any],
        response_validator: Callable[[int, Mapping[str, str]], Any] | None = None,
        body: bytes | None = None,
        accepted_statuses: Sequence[int] = (200, 206),
        max_redirects: int = 5,
        max_total_bytes: int | None = None,
    ) -> PinnedStreamResult:
        """Stream one bounded final response without materializing ``response.content``."""

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
        if not callable(sink):
            raise TypeError("sink must be callable")
        if response_validator is not None and not callable(response_validator):
            raise TypeError("response_validator must be callable or None")
        if type(max_redirects) is not int or max_redirects < 0:
            raise ValueError("max_redirects must be a non-negative integer")
        byte_limit = self._max_response_bytes if max_total_bytes is None else max_total_bytes
        if type(byte_limit) is not int or byte_limit <= 0:
            raise ValueError("max_total_bytes must be positive")
        if byte_limit > self._max_response_bytes:
            raise ValueError("max_total_bytes exceeds the transport response budget")
        try:
            accepted = frozenset(accepted_statuses)
        except TypeError as exc:
            raise ValueError("accepted_statuses must contain HTTP status codes") from exc
        if not accepted or any(
            type(status) is not int
            or status < 100
            or status > 599
            or status in DomainPolicyEngine.REDIRECT_STATUS_CODES
            for status in accepted
        ):
            raise ValueError("accepted_statuses must contain non-redirect HTTP status codes")

        request_headers = _copy_request_headers(headers)
        target = canonicalize_request_target(url)
        redirect_chain = [target.url]
        session: Any | None = None

        def open_session() -> None:
            nonlocal session
            try:
                candidate = (
                    _DirectCurlStreamingSession()
                    if self._owns_real_session_factory
                    else self._session_factory()
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                raise PinnedTransportNetworkError(
                    "public transport session could not be created"
                ) from exc
            _validate_session_candidate(
                candidate,
                owns_real_session_factory=self._owns_real_session_factory,
            )
            session = candidate

        deadline = time.monotonic() + self._timeout
        current_method = normalized_method
        current_body = body
        response: Any | None = None
        primary_error: BaseException | None = None
        total_response_bytes = 0
        bytes_written = 0

        try:
            for redirect_count in range(max_redirects + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PinnedTransportNetworkError("public request deadline exceeded")
                try:
                    addresses = self._policy.resolve_public_addresses(target.url)
                except DomainPolicyViolation:
                    raise
                except OSError as exc:
                    raise PinnedTransportNetworkError(
                        "public name resolution failed"
                    ) from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PinnedTransportNetworkError("public request deadline exceeded")
                if session is None:
                    open_session()
                if session is None:  # pragma: no cover
                    raise RuntimeError("private curl session is unavailable")
                _reset_real_session_handle(session)
                pin_curl_options = curl_resolve_options(
                    target, addresses, disable_proxy=True
                )
                from curl_cffi.const import CurlInfo, CurlOpt

                authoritative_curl_options = {
                    CurlOpt.NOSIGNAL: 1,
                    CurlOpt.FRESH_CONNECT: 1,
                    CurlOpt.FORBID_REUSE: 1,
                    CurlOpt.TIMEOUT_MS: max(1, math.ceil(remaining * 1000)),
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
                    raise PinnedTransportNetworkError("public request deadline exceeded")
                callback_status: int | None = None
                callback_error: BaseException | None = None
                response_start_error: BaseException | None = None
                validated_status: int | None = None
                response_too_large = False

                def collect_header(line: bytes) -> None:
                    nonlocal response_too_large, total_response_bytes
                    if type(line) is not bytes:
                        raise DomainPolicyViolation("public response header is invalid")
                    if total_response_bytes + len(line) > byte_limit:
                        response_too_large = True
                        raise DomainPolicyViolation(
                            "public response exceeds size limit"
                        )
                    total_response_bytes += len(line)

                def validate_response_start(
                    status_code: int,
                    response_headers: Mapping[str, str],
                ) -> None:
                    nonlocal response_start_error, validated_status
                    if status_code not in accepted or response_validator is None:
                        return
                    try:
                        response_validator(status_code, response_headers)
                        validated_status = status_code
                    except BaseException as exc:
                        response_start_error = exc
                        raise

                def collect(chunk: bytes) -> int:
                    nonlocal callback_status, callback_error
                    nonlocal response_too_large, total_response_bytes, bytes_written
                    try:
                        if time.monotonic() >= deadline:
                            raise PinnedTransportNetworkError(
                                "public request deadline exceeded"
                            )
                        if type(chunk) is not bytes:
                            raise DomainPolicyViolation("public response body is invalid")
                        try:
                            status_code = int(session.curl.getinfo(CurlInfo.RESPONSE_CODE))
                        except BaseException as exc:
                            if not isinstance(exc, Exception):
                                raise
                            raise DomainPolicyViolation(
                                "public response status is unavailable while streaming"
                            ) from exc
                        if status_code < 100 or status_code > 599:
                            raise DomainPolicyViolation(
                                "public response status is invalid while streaming"
                            )
                        if callback_status is None:
                            callback_status = status_code
                        elif callback_status != status_code:
                            raise DomainPolicyViolation(
                                "public response status changed while streaming"
                            )
                        if total_response_bytes + len(chunk) > byte_limit:
                            response_too_large = True
                            return _CURL_WRITEFUNC_ERROR
                        total_response_bytes += len(chunk)
                        if (
                            status_code in accepted
                            and status_code not in DomainPolicyEngine.REDIRECT_STATUS_CODES
                        ):
                            if (
                                response_validator is not None
                                and validated_status != status_code
                            ):
                                raise DomainPolicyViolation(
                                    "public response headers were not validated before body"
                                )
                            consumed = sink(chunk)
                            if consumed is not None and (
                                type(consumed) is not int or consumed != len(chunk)
                            ):
                                raise DomainPolicyViolation(
                                    "public response sink did not consume the full chunk"
                                )
                            bytes_written += len(chunk)
                        if time.monotonic() >= deadline:
                            raise PinnedTransportNetworkError(
                                "public request deadline exceeded"
                            )
                        return len(chunk)
                    except BaseException as exc:
                        callback_error = exc
                        return _CURL_WRITEFUNC_ERROR

                try:
                    response = session.request(
                        current_method,
                        target.url,
                        headers=request_headers,
                        data=current_body,
                        allow_redirects=False,
                        timeout=remaining,
                        header_callback=collect_header,
                        content_callback=collect,
                        response_start_callback=validate_response_start,
                    )
                except BaseException as exc:
                    if callback_error is not None:
                        raise callback_error
                    if response_start_error is not None:
                        raise response_start_error
                    if response_too_large:
                        raise DomainPolicyViolation(
                            "public response exceeds size limit"
                        ) from exc
                    if isinstance(exc, (DomainPolicyViolation, PinnedTransportNetworkError)):
                        raise
                    if not isinstance(exc, Exception):
                        raise
                    raise PinnedTransportNetworkError("public request failed") from exc
                if callback_error is not None:
                    raise callback_error
                if response_too_large:
                    raise DomainPolicyViolation("public response exceeds size limit")
                if time.monotonic() >= deadline:
                    raise PinnedTransportNetworkError("public request deadline exceeded")
                status_code = int(getattr(response, "status_code", 0) or 0)
                if callback_status is not None and callback_status != status_code:
                    raise DomainPolicyViolation(
                        "public response status does not match streamed body"
                    )
                response_headers = _response_headers(response)
                if (
                    response_validator is not None
                    and status_code in accepted
                    and validated_status != status_code
                ):
                    raise DomainPolicyViolation(
                        "public response headers were not validated before body"
                    )
                location = _header_value(response_headers, "location")
                if (
                    status_code not in DomainPolicyEngine.REDIRECT_STATUS_CODES
                    or not location
                ):
                    return PinnedStreamResult(
                        status_code=status_code,
                        url=target.url,
                        headers=response_headers,
                        bytes_written=bytes_written,
                        total_response_bytes=total_response_bytes,
                        redirect_chain=tuple(redirect_chain),
                    )
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
                try:
                    _close_redirect_response(redirect_response, session)
                except BaseException:
                    session = None
                    raise
                if origin_changed:
                    previous_session = session
                    session = None
                    _close_streaming_resource(
                        previous_session,
                        _close_session,
                        "public redirect session cleanup failed",
                    )
                target = next_target
                redirect_chain.append(target.url)
            raise DomainPolicyViolation("public redirect limit exceeded")
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                _close_resources(
                    response,
                    session,
                    suppress_errors=primary_error is not None,
                    primary_error=primary_error,
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                raise PinnedTransportNetworkError(
                    "public transport cleanup failed"
                ) from exc
