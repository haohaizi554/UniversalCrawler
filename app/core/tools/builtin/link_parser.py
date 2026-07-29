"""Offline-first link extraction with an explicitly gated short-link resolver."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import idna

from app.core.tools.contracts import (
    ToolContext,
    ToolManifest,
    ToolRequirements,
    ToolRunResult,
)
from shared.network.pinned_transport import PinnedTransport
from shared.runtime_options import PUBLIC_DOMAIN_POLICY, DomainPolicyViolation


_MAX_TEXT_LENGTH = 100_000
_DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_TIMEOUT_SECONDS = 15.0
_DEFAULT_MAX_REDIRECTS = 5
_MAX_REDIRECTS = 10
_DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024
_DEFAULT_MAX_LINKS = 100
_MAX_LINKS = 500
_DEFAULT_MAX_EXPANSIONS = 10
_MAX_EXPANSIONS = 25
_DEFAULT_DEADLINE_SECONDS = 15.0
_MAX_DEADLINE_SECONDS = 30.0
_MAX_PERCENT_DECODE_ROUNDS = 8
_URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*:(?://)?[^\s<>\"'`]+")
_ASCII_DNS_LABEL_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
    re.IGNORECASE,
)
_SENTENCE_PUNCTUATION = ".,;:!?。，；：！？、"
_SHORT_LINK_HOSTS = frozenset(
    {
        "b23.tv",
        "bit.ly",
        "buff.ly",
        "dwz.cn",
        "is.gd",
        "ksurl.cn",
        "t.cn",
        "tinyurl.com",
        "v.douyin.com",
        "xhslink.com",
    }
)
_MEDIA_EXTENSIONS = frozenset(
    {
        ".aac",
        ".avi",
        ".avif",
        ".flac",
        ".flv",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".png",
        ".ts",
        ".wav",
        ".webm",
        ".webp",
    }
)
_MEDIA_FORMAT_HINTS = frozenset(
    extension.removeprefix(".").upper() for extension in _MEDIA_EXTENSIONS
)
LINK_FORMAT_HINTS = frozenset({"HLS", "PLATFORM"}).union(_MEDIA_FORMAT_HINTS)

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "title": "Text to parse",
            "minLength": 1,
            "maxLength": _MAX_TEXT_LENGTH,
        },
        "expand_short_links": {
            "type": "boolean",
            "title": "Expand short links",
            "default": False,
        },
        "timeout_seconds": {
            "type": "number",
            "minimum": 0.1,
            "maximum": _MAX_TIMEOUT_SECONDS,
            "default": _DEFAULT_TIMEOUT_SECONDS,
        },
        "max_redirects": {
            "type": "integer",
            "minimum": 0,
            "maximum": _MAX_REDIRECTS,
            "default": _DEFAULT_MAX_REDIRECTS,
        },
        "max_response_bytes": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_RESPONSE_BYTES,
            "default": _DEFAULT_MAX_RESPONSE_BYTES,
        },
        "max_links": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_LINKS,
            "default": _DEFAULT_MAX_LINKS,
        },
        "max_expansions": {
            "type": "integer",
            "minimum": 0,
            "maximum": _MAX_EXPANSIONS,
            "default": _DEFAULT_MAX_EXPANSIONS,
        },
        "deadline_seconds": {
            "type": "number",
            "minimum": 0.1,
            "maximum": _MAX_DEADLINE_SECONDS,
            "default": _DEFAULT_DEADLINE_SECONDS,
        },
    },
    "required": ["text"],
    "additionalProperties": False,
}


def _build_manifest() -> ToolManifest:
    return ToolManifest(
        id="link_parser",
        title="Link parser",
        summary="Extract and classify links without network access unless short-link expansion is enabled.",
        category="utility",
        input_schema=_INPUT_SCHEMA,
        permissions=("network",),
        supports_cancel=True,
        icon="link",
        sort_order=10,
        read_only=True,
    )


def _context_parameters(context: ToolContext) -> Mapping[str, Any]:
    value = getattr(context, "parameters", None)
    if isinstance(value, Mapping):
        return value
    return context if isinstance(context, Mapping) else {}


def _is_cancelled(context: ToolContext) -> bool:
    checker = getattr(context, "is_cancelled", None)
    if callable(checker):
        return bool(checker())
    checker = getattr(getattr(context, "cancellation", None), "is_cancelled", None)
    return bool(checker()) if callable(checker) else False


def _clean_candidate(value: str) -> str:
    candidate = value
    while candidate:
        last = candidate[-1]
        if last in _SENTENCE_PUNCTUATION and not (
            last == ":" and urlsplit(candidate).netloc.endswith(":")
        ):
            candidate = candidate[:-1]
            continue
        removed_parenthesis = False
        for opening, closing in (("(", ")"), ("（", "）")):
            if candidate.endswith(closing) and candidate.count(
                closing
            ) > candidate.count(opening):
                candidate = candidate[: -len(closing)]
                removed_parenthesis = True
                break
        if not removed_parenthesis:
            break
    return candidate


def normalize_link_hostname(value: str) -> str:
    """Return one unambiguous ASCII hostname or reject the candidate."""

    if not value or any(
        character.isspace()
        or unicodedata.category(character).startswith("C")
        for character in value
    ) or "%" in value:
        raise ValueError("URL host is invalid")

    if ":" in value:
        try:
            return ipaddress.IPv6Address(value).compressed
        except ipaddress.AddressValueError as exc:
            raise ValueError("URL host is invalid") from exc

    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        if all(character.isdigit() or character == "." for character in value):
            raise ValueError("URL host is invalid") from None

    hostname = value[:-1] if value.endswith(".") else value
    labels = hostname.split(".")
    if not hostname or any(not label for label in labels):
        raise ValueError("URL host is invalid")

    canonical_labels: list[str] = []
    for label in labels:
        try:
            canonical_label = idna.encode(
                label,
                uts46=True,
                transitional=False,
                std3_rules=True,
            ).decode("ascii").lower()
        except (idna.IDNAError, UnicodeError) as exc:
            raise ValueError("URL host is invalid") from exc
        if _ASCII_DNS_LABEL_PATTERN.fullmatch(canonical_label) is None:
            raise ValueError("URL host is invalid")
        if canonical_label.startswith("xn--"):
            try:
                decoded_label = idna.decode(
                    canonical_label,
                    uts46=True,
                    std3_rules=True,
                )
                round_trip = idna.encode(
                    decoded_label,
                    uts46=True,
                    transitional=False,
                    std3_rules=True,
                ).decode("ascii").lower()
            except (idna.IDNAError, UnicodeError) as exc:
                raise ValueError("URL host is invalid") from exc
            if round_trip != canonical_label:
                raise ValueError("URL host is invalid")
        canonical_labels.append(canonical_label)

    canonical_hostname = ".".join(canonical_labels)
    if len(canonical_hostname) > 253:
        raise ValueError("URL host is invalid")
    return canonical_hostname


def _validate_link_component(value: str) -> None:
    """Reject controls revealed by bounded repeated percent-decoding."""

    current = value
    for _round in range(_MAX_PERCENT_DECODE_ROUNDS):
        if any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or unicodedata.category(character).startswith("C")
            for character in current
        ):
            raise ValueError("URL path or query is invalid")
        try:
            decoded = unquote(current, encoding="utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("URL path or query is invalid") from exc
        if decoded == current:
            return
        current = decoded

    if any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or unicodedata.category(character).startswith("C")
        for character in current
    ):
        raise ValueError("URL path or query is invalid")
    try:
        still_decodable = unquote(current, encoding="utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("URL path or query is invalid") from exc
    if still_decodable != current:
        raise ValueError("URL path or query encoding is too deeply nested")


def normalize_link_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("URL is invalid")
    if any(character in value for character in "\r\n\t"):
        raise ValueError("URL path or query is invalid")
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ValueError("URL host is invalid") from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL credentials are not allowed")
    try:
        raw_host = parts.hostname or ""
    except ValueError as exc:
        raise ValueError("URL host is invalid") from exc
    if not raw_host:
        raise ValueError("URL host is required")
    host = normalize_link_hostname(raw_host)
    _validate_link_component(parts.path)
    _validate_link_component(parts.query)
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc
    if parts.netloc.endswith(":") or port == 0:
        raise ValueError("URL port is invalid")
    authority = f"[{host}]" if ":" in host else host
    if port is not None and (scheme, port) not in (("http", 80), ("https", 443)):
        authority = f"{authority}:{port}"
    return urlunsplit((scheme, authority, parts.path or "/", parts.query, ""))


def link_candidate_id(private_url: str) -> str:
    return hashlib.sha256(private_url.encode("utf-8")).hexdigest()


def redacted_link_url(private_url: str) -> str:
    parts = urlsplit(private_url)
    has_private_location = parts.path not in ("", "/") or bool(parts.query)
    path = "/[redacted]" if has_private_location else "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def classify_link_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com"):
        platform = "bilibili"
    elif host == "v.douyin.com" or host == "douyin.com" or host.endswith(".douyin.com"):
        platform = "douyin"
    elif (
        host == "xhslink.com"
        or host == "xiaohongshu.com"
        or host.endswith(".xiaohongshu.com")
    ):
        platform = "xiaohongshu"
    elif host == "ksurl.cn" or host == "kuaishou.com" or host.endswith(".kuaishou.com"):
        platform = "kuaishou"
    elif host == "missav.ai" or host.endswith(".missav.ai"):
        platform = "missav"
    elif host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        platform = "youtube"
    elif host == "tiktok.com" or host.endswith(".tiktok.com"):
        platform = "tiktok"
    else:
        platform = "generic"
    path = parts.path.lower()
    if path.endswith(".m3u8"):
        kind = "playlist"
    elif any(path.endswith(extension) for extension in _MEDIA_EXTENSIONS):
        kind = "media"
    else:
        kind = "page"
    return platform, kind


def link_format_hint(url: str, resource_kind: str | None = None) -> str:
    """Return a bounded public format hint derived from a canonical URL."""

    kind = resource_kind or classify_link_url(url)[1]
    if kind == "page":
        return "PLATFORM"
    if kind == "playlist":
        return "HLS"
    if kind == "media":
        path = urlsplit(url).path.lower()
        for extension in _MEDIA_EXTENSIONS:
            if path.endswith(extension):
                return extension.removeprefix(".").upper()
    raise ValueError("URL resource format is invalid")


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "links": len(rows),
        "platforms": dict(Counter(row["platform"] for row in rows)),
        "resource_kinds": dict(Counter(row["resource_kind"] for row in rows)),
        "formats": dict(Counter(row["format_hint"] for row in rows)),
    }


class LinkParserTool:
    """Parse text locally and resolve recognized short links only when opted in."""

    manifest = _build_manifest()

    def __init__(
        self, *, transport_factory: Callable[..., PinnedTransport] | None = None
    ) -> None:
        self._transport_factory = transport_factory or PinnedTransport

    @staticmethod
    def requirements_for(parameters: Mapping[str, Any]) -> ToolRequirements:
        if (
            isinstance(parameters, Mapping)
            and parameters.get("expand_short_links") is True
        ):
            return ToolRequirements(frozenset({"network"}))
        return ToolRequirements()

    def validate(self, context: ToolContext) -> list[str]:
        parameters = _context_parameters(context)
        if set(parameters) - set(_INPUT_SCHEMA["properties"]):
            return ["unsupported input field"]
        text = parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return ["text is required"]
        if len(text) > _MAX_TEXT_LENGTH:
            return ["text exceeds the maximum allowed length"]
        if type(parameters.get("expand_short_links", False)) is not bool:
            return ["expand_short_links must be a boolean"]
        option_error = self._validate_network_options(parameters)
        if option_error:
            return [option_error]
        for match in _URL_PATTERN.finditer(text):
            try:
                normalize_link_url(_clean_candidate(match.group(0)))
            except ValueError as exc:
                return [str(exc)]
        return []

    @staticmethod
    def _validate_network_options(parameters: Mapping[str, Any]) -> str:
        timeout = parameters.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
        ):
            return "timeout_seconds must be a finite number"
        if not 0.1 <= float(timeout) <= _MAX_TIMEOUT_SECONDS:
            return "timeout_seconds must be between 0.1 and 15"
        redirects = parameters.get("max_redirects", _DEFAULT_MAX_REDIRECTS)
        if type(redirects) is not int:
            return "max_redirects must be an integer"
        if not 0 <= redirects <= _MAX_REDIRECTS:
            return "max_redirects must be between 0 and 10"
        response_bytes = parameters.get(
            "max_response_bytes", _DEFAULT_MAX_RESPONSE_BYTES
        )
        if type(response_bytes) is not int:
            return "max_response_bytes must be an integer"
        if not 1 <= response_bytes <= _MAX_RESPONSE_BYTES:
            return "max_response_bytes must be between 1 and 65536"
        max_links = parameters.get("max_links", _DEFAULT_MAX_LINKS)
        if type(max_links) is not int:
            return "max_links must be an integer"
        if not 1 <= max_links <= _MAX_LINKS:
            return "max_links must be between 1 and 500"
        max_expansions = parameters.get("max_expansions", _DEFAULT_MAX_EXPANSIONS)
        if type(max_expansions) is not int:
            return "max_expansions must be an integer"
        if not 0 <= max_expansions <= _MAX_EXPANSIONS:
            return "max_expansions must be between 0 and 25"
        deadline = parameters.get("deadline_seconds", _DEFAULT_DEADLINE_SECONDS)
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            return "deadline_seconds must be a finite number"
        if not 0.1 <= float(deadline) <= _MAX_DEADLINE_SECONDS:
            return "deadline_seconds must be between 0.1 and 30"
        return ""

    def run(self, context: ToolContext) -> ToolRunResult:
        started_at = time.monotonic()
        if _is_cancelled(context):
            return ToolRunResult.cancelled()
        errors = self.validate(context)
        if errors:
            return ToolRunResult.failure(
                errors[0], data={"error_code": "invalid_input"}
            )
        parameters = _context_parameters(context)
        deadline = started_at + float(
            parameters.get("deadline_seconds", _DEFAULT_DEADLINE_SECONDS)
        )
        if time.monotonic() >= deadline:
            return self._deadline_result()
        rows: list[dict[str, Any]] = []
        private_candidates: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        seen_private_urls: set[str] = set()
        expand = parameters.get("expand_short_links") is True
        max_links = int(parameters.get("max_links", _DEFAULT_MAX_LINKS))
        max_expansions = int(parameters.get("max_expansions", _DEFAULT_MAX_EXPANSIONS))
        expansions = 0
        links_truncated = False
        expansions_truncated = False
        for match in _URL_PATTERN.finditer(str(parameters["text"])):
            if _is_cancelled(context):
                return ToolRunResult.cancelled()
            if time.monotonic() >= deadline:
                return self._deadline_result()
            source_url = normalize_link_url(_clean_candidate(match.group(0)))
            if source_url in seen_sources:
                continue
            seen_sources.add(source_url)
            if len(rows) >= max_links:
                links_truncated = True
                break
            private_url = source_url
            expanded = False
            if expand and self._is_short_link(private_url):
                if expansions < max_expansions:
                    expansions += 1
                    expanded_url = self._expand(
                        private_url,
                        parameters,
                        context,
                        deadline=deadline,
                    )
                    if isinstance(expanded_url, ToolRunResult):
                        return expanded_url
                    private_url = expanded_url
                    expanded = True
                else:
                    expansions_truncated = True
            if private_url in seen_private_urls:
                continue
            seen_private_urls.add(private_url)
            candidate_id = link_candidate_id(private_url)
            platform, resource_kind = classify_link_url(private_url)
            format_hint = link_format_hint(private_url, resource_kind)
            public_candidate = {
                "candidate_id": candidate_id,
                "display_url": redacted_link_url(private_url),
                "platform": platform,
                "resource_kind": resource_kind,
                "format_hint": format_hint,
                "expanded": expanded,
            }
            rows.append(public_candidate)
            private_candidates.append(
                {**public_candidate, "private_url": private_url}
            )
        return ToolRunResult.success(
            "links parsed",
            data={
                "links": rows,
                "counts": _counts(rows),
                "limits": {
                    "max_links": max_links,
                    "max_expansions": max_expansions,
                    "deadline_seconds": float(
                        parameters.get("deadline_seconds", _DEFAULT_DEADLINE_SECONDS)
                    ),
                    "links_truncated": links_truncated,
                    "expansions_truncated": expansions_truncated,
                },
            },
            private_data={"candidates": private_candidates},
        )

    @staticmethod
    def _is_short_link(url: str) -> bool:
        return (urlsplit(url).hostname or "").lower() in _SHORT_LINK_HOSTS

    @staticmethod
    def _deadline_result() -> ToolRunResult:
        return ToolRunResult.failure(
            "link parsing deadline exceeded",
            data={"error_code": "run_deadline_exceeded"},
        )

    def _expand(
        self,
        url: str,
        parameters: Mapping[str, Any],
        context: ToolContext,
        *,
        deadline: float,
    ) -> str | ToolRunResult:
        if _is_cancelled(context):
            return ToolRunResult.cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return self._deadline_result()
        transport = self._transport_factory(
            policy=PUBLIC_DOMAIN_POLICY,
            timeout=min(
                float(parameters.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)),
                remaining,
            ),
            max_response_bytes=int(
                parameters.get("max_response_bytes", _DEFAULT_MAX_RESPONSE_BYTES)
            ),
        )
        try:
            if _is_cancelled(context):
                return ToolRunResult.cancelled()
            response = transport.request(
                "GET",
                url,
                headers={"Accept": "text/plain, text/html;q=0.1"},
                max_redirects=int(
                    parameters.get("max_redirects", _DEFAULT_MAX_REDIRECTS)
                ),
            )
            if _is_cancelled(context):
                return ToolRunResult.cancelled()
            if time.monotonic() >= deadline:
                return self._deadline_result()
            status_code = int(getattr(response, "status_code", 0) or 0)
            if not 200 <= status_code < 300:
                return ToolRunResult.failure(
                    "short-link expansion returned an unsuccessful HTTP status",
                    data={"error_code": "short_link_http_status"},
                )
            return normalize_link_url(str(getattr(response, "url", "")))
        except DomainPolicyViolation:
            if _is_cancelled(context):
                return ToolRunResult.cancelled()
            if time.monotonic() >= deadline:
                return self._deadline_result()
            return ToolRunResult.failure(
                "short-link expansion was blocked by network policy",
                data={"error_code": "network_policy_blocked"},
            )
        except Exception:
            if _is_cancelled(context):
                return ToolRunResult.cancelled()
            if time.monotonic() >= deadline:
                return self._deadline_result()
            return ToolRunResult.failure(
                "short-link expansion failed",
                data={"error_code": "short_link_expansion_failed"},
            )


TOOL = LinkParserTool()
manifest = TOOL.manifest
