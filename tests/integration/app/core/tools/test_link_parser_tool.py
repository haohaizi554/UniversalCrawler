from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from typing import Any
from urllib.parse import quote

import pytest

from app.core.tools.contracts import CancellationToken, ToolContext, ToolRunStatus


@dataclass(frozen=True)
class _Response:
    status_code: int
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    redirect_chain: tuple[str, ...] = ()


class _Transport:
    def __init__(
        self, response: _Response, cancellation: CancellationToken | None = None
    ) -> None:
        self.response = response
        self.cancellation = cancellation
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.cancellation is not None:
            self.cancellation.cancel()
        return self.response


class _BoundedBlockingTransport:
    def __init__(
        self,
        response: _Response,
        *,
        max_wait: float = 0.5,
        timeout_overrun: float = 0.0,
    ) -> None:
        self.response = response
        self.max_wait = max_wait
        self.timeout_overrun = timeout_overrun
        self.timeout_seconds = max_wait
        self.started = Event()
        self.release = Event()
        self.request_thread_name = ""

    def request(self, _method: str, _url: str, **_kwargs: Any) -> _Response:
        self.request_thread_name = threading.current_thread().name
        self.started.set()
        self.release.wait(
            min(self.timeout_seconds + self.timeout_overrun, self.max_wait)
        )
        return self.response


def _context(
    parameters: Mapping[str, Any], cancellation: CancellationToken | None = None
) -> ToolContext:
    return ToolContext(
        parameters=dict(parameters), cancellation=cancellation or CancellationToken()
    )


def _private_candidates(result: Any) -> Any:
    return result.private_data["candidates"]


def test_manifest_is_the_complete_input_schema_and_default_parse_is_offline() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    instantiated = False

    def transport_factory(**_kwargs: Any) -> object:
        nonlocal instantiated
        instantiated = True
        raise AssertionError("offline parsing must not create a network transport")

    tool = LinkParserTool(transport_factory=transport_factory)
    context = _context(
        {
            "text": "See HTTPS://www.douyin.com/video/123#share and https://cdn.example/a.mp4?x=1."
        }
    )

    assert tool.manifest.id == "link_parser"
    assert tool.manifest.input_schema["type"] == "object"
    assert tool.manifest.input_schema["additionalProperties"] is False
    assert set(tool.manifest.input_schema["properties"]) == {
        "text",
        "expand_short_links",
        "timeout_seconds",
        "max_redirects",
        "max_response_bytes",
        "max_links",
        "max_expansions",
        "deadline_seconds",
    }
    assert (
        tool.manifest.input_schema["properties"]["expand_short_links"]["default"]
        is False
    )
    assert tool.validate(context) == []

    result = tool.run(context)

    assert result.status is ToolRunStatus.SUCCEEDED
    assert instantiated is False
    assert result.data["counts"] == {
        "links": 2,
        "platforms": {"douyin": 1, "generic": 1},
        "resource_kinds": {"page": 1, "media": 1},
        "formats": {"PLATFORM": 1, "MP4": 1},
    }
    assert [
        (
            row["display_url"],
            row["platform"],
            row["resource_kind"],
            row["format_hint"],
            row["expanded"],
        )
        for row in result.data["links"]
    ] == [
        ("https://www.douyin.com/[redacted]", "douyin", "page", "PLATFORM", False),
        ("https://cdn.example/[redacted]", "generic", "media", "MP4", False),
    ]
    assert all(
        set(row)
        == {
            "candidate_id",
            "display_url",
            "platform",
            "resource_kind",
            "format_hint",
            "expanded",
        }
        for row in result.data["links"]
    )
    assert "private_candidates" not in result.data
    assert [row["private_url"] for row in _private_candidates(result)] == [
        "https://www.douyin.com/video/123",
        "https://cdn.example/a.mp4?x=1",
    ]
    assert [
        {
            key: row[key]
            for key in (
                "candidate_id",
                "display_url",
                "platform",
                "resource_kind",
                "format_hint",
                "expanded",
            )
        }
        for row in _private_candidates(result)
    ] == result.data["links"]


@pytest.mark.parametrize(
    ("parameters", "expected_error"),
    [
        ({"text": "ftp://example.com/file"}, "only http and https URLs are supported"),
        (
            {"text": "https://user:secret@example.com/path"},
            "URL credentials are not allowed",
        ),
        (
            {"text": "https://www\u200b.bilibili.com/media/video.mp4"},
            "URL host is invalid",
        ),
        (
            {"text": "https://xn--a.bilibili.com/media/video.mp4"},
            "URL host is invalid",
        ),
        ({"text": "https:///missing-host"}, "URL host is required"),
        (
            {"text": "https://example.com", "timeout_seconds": 0},
            "timeout_seconds must be between 0.1 and 15",
        ),
        (
            {"text": "https://example.com", "max_redirects": True},
            "max_redirects must be an integer",
        ),
        (
            {"text": "https://example.com", "max_response_bytes": "1024"},
            "max_response_bytes must be an integer",
        ),
        (
            {"text": "https://example.com", "expand_short_links": 1},
            "expand_short_links must be a boolean",
        ),
        (
            {"text": "https://example.com", "max_links": 501},
            "max_links must be between 1 and 500",
        ),
        (
            {"text": "https://example.com", "max_expansions": 26},
            "max_expansions must be between 0 and 25",
        ),
        (
            {"text": "https://example.com", "deadline_seconds": 31},
            "deadline_seconds must be between 0.1 and 30",
        ),
    ],
)
def test_validate_rejects_unsafe_or_malformed_input(
    parameters: Mapping[str, Any], expected_error: str
) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    errors = LinkParserTool().validate(_context(parameters))

    assert errors == [expected_error]
    assert "secret" not in " ".join(errors)


def test_validation_rejects_oversized_text() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    tool = LinkParserTool()
    maximum = tool.manifest.input_schema["properties"]["text"]["maxLength"]

    assert tool.validate(_context({"text": "x" * (maximum + 1)})) == [
        "text exceeds the maximum allowed length"
    ]


def test_normalization_deduplicates_only_identical_queryless_links() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    result = LinkParserTool().run(
        _context(
            {
                "text": (
                    "HTTPS://Example.COM:443/item#presented "
                    "https://example.com/item "
                    "https://example.com/item?identity=one "
                    "https://example.com/item?identity=two"
                )
            }
        )
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert [row["private_url"] for row in _private_candidates(result)] == [
        "https://example.com/item",
        "https://example.com/item?identity=one",
        "https://example.com/item?identity=two",
    ]
    assert [row["display_url"] for row in result.data["links"]] == [
        "https://example.com/[redacted]",
        "https://example.com/[redacted]",
        "https://example.com/[redacted]",
    ]
    assert result.output_paths == ()


def test_normalization_canonicalizes_valid_unicode_host_to_ascii_idna() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    result = LinkParserTool().run(
        _context({"text": "https://b\u00fccher.example/media/video.mp4"})
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert _private_candidates(result)[0]["private_url"] == (
        "https://xn--bcher-kva.example/media/video.mp4"
    )
    assert result.data["links"][0]["display_url"] == (
        "https://xn--bcher-kva.example/[redacted]"
    )


def test_normalization_uses_nontransitional_idna2008_for_sharp_s() -> None:
    from app.core.tools.builtin.link_parser import normalize_link_url

    assert normalize_link_url("https://fa\u00df.de/media/video.mp4") == (
        "https://xn--fa-hia.de/media/video.mp4"
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://example.com/media/zero\u200bwidth.mp4",
        "https://example.com/media/video.mp4?token=hidden\u2060value",
        "https://example.com/media/video.mp4?token=delete\x7fvalue",
        "https://example.com/media/%00video.mp4",
        "https://example.com/media/video.mp4?token=%1Fvalue",
        "https://example.com/media/video.mp4?token=%7fvalue",
        "https://example.com/media/%E2%80%8Bvideo.mp4",
        "https://example.com/media/video.mp4?token=%E2%81%A0value",
        "https://example.com/media/%25E2%2580%258Bvideo.mp4",
        "https://example.com/media/video.mp4?token=%2500value",
        "http://[fe80::1%25eth0]/media/video.mp4",
    ),
)
def test_normalization_rejects_invisible_components_and_ipv6_zone_ids(
    url: str,
) -> None:
    from app.core.tools.builtin.link_parser import normalize_link_url

    with pytest.raises(ValueError):
        normalize_link_url(url)


def test_normalization_fails_closed_when_percent_encoding_exceeds_decode_bound() -> None:
    from app.core.tools.builtin.link_parser import normalize_link_url

    nested_control = "%00"
    for _round in range(9):
        nested_control = quote(nested_control, safe="")

    with pytest.raises(ValueError, match="too deeply nested"):
        normalize_link_url(f"https://example.com/media/{nested_control}video.mp4")


def test_candidate_id_is_deterministic_for_the_full_canonical_private_url() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    first = LinkParserTool().run(
        _context({"text": "HTTPS://EXAMPLE.com:443/item?token=top-secret&x=1#share"})
    )
    second = LinkParserTool().run(
        _context({"text": "https://example.com/item?token=top-secret&x=1"})
    )

    expected = "d0dba376a88c3b4701d856bc19d8b04e147e98f480d992d580c2eb713a832225"
    assert first.data["links"][0]["candidate_id"] == expected
    assert second.data["links"][0]["candidate_id"] == expected
    assert _private_candidates(first)[0]["candidate_id"] == expected


def test_frontend_safe_rows_redact_query_values_from_display_fields() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    secret = "frontend-must-never-see-this"
    result = LinkParserTool().run(
        _context({"text": f"https://example.com/watch?token={secret}&quality=1080"})
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert secret not in str(result.data["links"])
    assert result.data["links"][0]["display_url"] == (
        "https://example.com/[redacted]"
    )
    assert "private_candidates" not in result.data
    assert secret not in json.dumps(result.to_dict(), ensure_ascii=False)
    assert _private_candidates(result)[0]["private_url"].endswith(
        f"?token={secret}&quality=1080"
    )


def test_frontend_safe_rows_redact_path_tokens_from_public_result() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    secret = "path-token-must-never-reach-the-frontend"
    result = LinkParserTool().run(
        _context({"text": f"https://example.com/invite/{secret}"})
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert result.data["links"][0]["display_url"] == (
        "https://example.com/[redacted]"
    )
    assert secret not in json.dumps(result.data, ensure_ascii=False)
    assert secret not in json.dumps(result.to_dict(), ensure_ascii=False)
    assert _private_candidates(result)[0]["private_url"].endswith(f"/{secret}")


def test_empty_and_root_paths_share_one_canonical_url_and_candidate_id() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    result = LinkParserTool().run(
        _context({"text": "https://example.com https://example.com/"})
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert len(result.data["links"]) == 1
    assert _private_candidates(result)[0]["private_url"] == "https://example.com/"
    separate = LinkParserTool().run(_context({"text": "https://example.com/"}))
    assert result.data["links"][0]["candidate_id"] == (
        separate.data["links"][0]["candidate_id"]
    )


def test_validation_rejects_non_http_url_schemes_without_returning_the_source() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    result = LinkParserTool().run(_context({"text": "mailto:secret@example.com"}))

    assert result.status is ToolRunStatus.FAILED
    assert result.message == "only http and https URLs are supported"
    assert "secret@example.com" not in str(result.to_dict())


def test_network_permission_is_declared_only_for_explicit_expansion() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    tool = LinkParserTool()

    assert tool.manifest.permissions == ("network",)
    assert (
        tool.requirements_for({"text": "https://short.example/a"}).permissions
        == frozenset()
    )
    assert tool.requirements_for(
        {"text": "https://short.example/a", "expand_short_links": True}
    ).permissions == frozenset({"network"})


def test_explicit_short_link_expansion_uses_bounded_public_transport() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool
    from shared.runtime_options import PUBLIC_DOMAIN_POLICY

    transport = _Transport(
        _Response(
            status_code=200,
            url="https://www.bilibili.com/video/BV1abc",
            redirect_chain=(
                "https://b23.tv/abc",
                "https://www.bilibili.com/video/BV1abc",
            ),
        )
    )
    factory_kwargs: dict[str, Any] = {}

    def transport_factory(**kwargs: Any) -> _Transport:
        factory_kwargs.update(kwargs)
        return transport

    tool = LinkParserTool(transport_factory=transport_factory)

    result = tool.run(
        _context(
            {
                "text": "https://b23.tv/abc",
                "expand_short_links": True,
                "timeout_seconds": 2,
                "max_redirects": 3,
                "max_response_bytes": 2048,
            }
        )
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert factory_kwargs == {
        "policy": PUBLIC_DOMAIN_POLICY,
        "timeout": 2.0,
        "max_response_bytes": 2048,
    }
    assert transport.calls == [
        {
            "method": "GET",
            "url": "https://b23.tv/abc",
            "headers": {"Accept": "text/plain, text/html;q=0.1"},
            "max_redirects": 3,
        }
    ]
    assert result.data["links"] == [
        {
            "candidate_id": result.data["links"][0]["candidate_id"],
            "display_url": "https://www.bilibili.com/[redacted]",
            "platform": "bilibili",
            "resource_kind": "page",
            "format_hint": "PLATFORM",
            "expanded": True,
        }
    ]
    assert result.data["counts"]["links"] == 1


@pytest.mark.parametrize("status_code", [300, 302, 399, 404, 500])
def test_terminal_non_2xx_status_is_an_expansion_failure(status_code: int) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    transport = _Transport(
        _Response(status_code=status_code, url="https://example.com/missing")
    )
    tool = LinkParserTool(transport_factory=lambda **_kwargs: transport)

    result = tool.run(
        _context({"text": "https://b23.tv/missing", "expand_short_links": True})
    )

    assert result.status is ToolRunStatus.FAILED
    assert result.data["error_code"] == "short_link_http_status"
    assert "expanded" not in result.data


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:",
        "https://example.com:0/path",
        "https://example.com:65536/path",
    ],
)
def test_validation_rejects_empty_zero_and_out_of_range_ports(url: str) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    assert LinkParserTool().validate(_context({"text": url})) == ["URL port is invalid"]


def test_parser_strips_sentence_punctuation_and_only_unbalanced_closing_parentheses() -> (
    None
):
    from app.core.tools.builtin.link_parser import LinkParserTool

    result = LinkParserTool().run(
        _context(
            {
                "text": (
                    "(https://example.com/a_(b)). "
                    "https://example.com/c）。 "
                    "https://example.com/d， https://example.com/e!"
                )
            }
        )
    )

    assert [row["private_url"] for row in _private_candidates(result)] == [
        "https://example.com/a_(b)",
        "https://example.com/c",
        "https://example.com/d",
        "https://example.com/e",
    ]


def test_max_links_bounds_structured_rows_and_reports_truncation() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    result = LinkParserTool().run(
        _context(
            {
                "text": " ".join(f"https://example.com/{index}" for index in range(5)),
                "max_links": 2,
            }
        )
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert len(result.data["links"]) == 2
    assert len(_private_candidates(result)) == 2
    assert result.data["limits"]["links_truncated"] is True


def test_max_expansions_bounds_network_calls_and_keeps_remaining_links() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    transport = _Transport(
        _Response(status_code=200, url="https://www.bilibili.com/video/BV1final")
    )
    tool = LinkParserTool(transport_factory=lambda **_kwargs: transport)
    result = tool.run(
        _context(
            {
                "text": "https://b23.tv/one https://b23.tv/two https://b23.tv/three",
                "expand_short_links": True,
                "max_expansions": 1,
            }
        )
    )

    assert result.status is ToolRunStatus.SUCCEEDED
    assert len(transport.calls) == 1
    assert [row["expanded"] for row in result.data["links"]] == [True, False, False]
    assert result.data["limits"]["expansions_truncated"] is True


def test_whole_run_deadline_bounds_a_blocking_transport() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    transport = _BoundedBlockingTransport(
        _Response(status_code=200, url="https://www.bilibili.com/video/BV1late"),
        timeout_overrun=0.02,
    )

    def transport_factory(**kwargs: Any) -> _BoundedBlockingTransport:
        transport.timeout_seconds = float(kwargs["timeout"])
        return transport

    tool = LinkParserTool(transport_factory=transport_factory)
    started_at = perf_counter()
    try:
        result = tool.run(
            _context(
                {
                    "text": "https://b23.tv/late",
                    "expand_short_links": True,
                    "deadline_seconds": 0.1,
                }
            )
        )
    finally:
        transport.release.set()

    assert perf_counter() - started_at < 1.0
    assert result.status is ToolRunStatus.FAILED
    assert result.data["error_code"] == "run_deadline_exceeded"


def test_cancellation_before_and_during_expansion_returns_canonical_result() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    cancelled = CancellationToken()
    cancelled.cancel()
    tool = LinkParserTool()
    before_result = tool.run(_context({"text": "https://example.com"}, cancelled))
    assert before_result.status is ToolRunStatus.CANCELLED
    assert before_result.message == "tool run cancelled"

    during = CancellationToken()
    transport = _Transport(
        _Response(status_code=200, url="https://example.com/final"), during
    )
    tool = LinkParserTool(transport_factory=lambda **_kwargs: transport)
    during_result = tool.run(
        _context({"text": "https://b23.tv/abc", "expand_short_links": True}, during)
    )
    assert during_result.status is ToolRunStatus.CANCELLED
    assert during_result.message == "tool run cancelled"


def test_expansion_request_stays_on_the_calling_worker_thread() -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool

    transport = _BoundedBlockingTransport(
        _Response(status_code=200, url="https://example.com/final")
    )

    def transport_factory(**kwargs: Any) -> _BoundedBlockingTransport:
        transport.timeout_seconds = float(kwargs["timeout"])
        return transport

    tool = LinkParserTool(transport_factory=transport_factory)
    results: list[Any] = []
    worker = Thread(
        target=lambda: results.append(
            tool.run(
                _context(
                    {
                        "text": "https://b23.tv/blocking",
                        "expand_short_links": True,
                        "deadline_seconds": 1,
                    }
                )
            )
        ),
        name="test-link-tool-worker",
        daemon=True,
    )
    worker.start()
    assert transport.started.wait(0.5)
    try:
        assert transport.request_thread_name == "test-link-tool-worker"
        assert not any(
            thread.name.startswith("link-parser") for thread in threading.enumerate()
        )
    finally:
        transport.release.set()
        worker.join(1.0)
    assert not worker.is_alive()
    assert results[0].status is ToolRunStatus.SUCCEEDED


def test_tool_runner_allows_offline_parse_without_network_grant(tmp_path: Path) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool
    from app.core.tools.registry import ToolRegistry
    from app.services.tool_runner_service import ToolRunnerService
    from shared.execution_profile import local_execution_profile

    def forbidden_transport(**_kwargs: Any) -> object:
        raise AssertionError("offline ToolRunnerService run attempted network access")

    registry = ToolRegistry(
        tools=[], include_builtins=False, include_entry_points=False
    )
    registry._register(
        LinkParserTool(transport_factory=forbidden_transport), provenance="builtin"
    )
    history_path = tmp_path / "history.json"
    events: list[tuple[str, dict[str, Any]]] = []
    service = ToolRunnerService(
        registry=registry,
        history_path=history_path,
        event_callback=lambda topic, payload: events.append((topic, payload)),
    )
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:link-parser-offline",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )
    secret = "runner-private-query"
    try:
        started = service.run(
            "link_parser",
            {"text": f"https://example.com/a?token={secret}"},
            execution_profile=profile,
        )
        assert started["status"] == "queued"
        assert service.wait_for_idle(timeout=2.0)
        assert service.history(execution_profile=profile)[0]["status"] == "succeeded"
        private = service.lookup_private_result(
            started["run_id"], execution_profile=profile
        )
        assert private is not None
        assert len(private.structured_data["links"]) == 1
        assert private.structured_data["links"][0]["candidate_id"] == (
            private.private_data["candidates"][0]["candidate_id"]
        )
        assert private.structured_data["links"][0]["display_url"] == (
            "https://example.com/[redacted]"
        )
        assert private.private_data["candidates"][0]["private_url"].endswith(
            f"?token={secret}"
        )
        record_text = json.dumps(
            service._records[started["run_id"]].to_dict(), ensure_ascii=False
        )
        assert secret not in record_text
        assert all(payload == {} for _topic, payload in events)
    finally:
        assert service.shutdown(wait=True)
    assert secret not in history_path.read_text(encoding="utf-8")


def test_link_candidate_admission_uses_the_real_owner_scoped_runner_result(
    tmp_path: Path,
) -> None:
    from app.core.download_manager_core import DownloadManagerCore, PendingDownloadQueue
    from app.core.tools.builtin.link_parser import LinkParserTool
    from app.core.tools.registry import ToolRegistry
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )
    from app.services.tool_runner_service import ToolRunnerService
    from shared.execution_profile import local_execution_profile

    registry = ToolRegistry(
        tools=[], include_builtins=False, include_entry_points=False
    )
    registry._register(LinkParserTool(), provenance="builtin")
    service = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "admission-history.json",
        max_workers=1,
    )
    owner = local_execution_profile(
        host_surface="test",
        owner_id="test:link-admission-owner",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )
    other_owner = local_execution_profile(
        host_surface="test",
        owner_id="test:link-admission-other",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )
    secret = "owner-private-query"
    try:
        started = service.run(
            "link_parser",
            {
                "text": (
                    "https://www.bilibili.com/media/video.mp4"
                    f"?token={secret}"
                )
            },
            execution_profile=owner,
        )
        assert service.wait_for_idle(timeout=2.0)
        private = service.lookup_private_result(
            started["run_id"], execution_profile=owner
        )
        assert private is not None
        candidate_id = private.structured_data["links"][0]["candidate_id"]
        admission = LinkCandidateAdmissionService(service)

        items = admission.prepare_items(
            "link_parser",
            started["run_id"],
            [candidate_id],
            execution_profile=owner,
        )

        assert len(items) == 1
        assert items[0].url.endswith(f"?token={secret}")
        assert items[0].meta["format_hint"] == "MP4"
        assert secret not in items[0].title
        assert secret not in items[0].meta["display_url"]

        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager.video_only = False
        manager.is_running = True
        admitted_items = admission.admit_to_queue(
            "link_parser",
            started["run_id"],
            [candidate_id],
            execution_profile=owner,
            download_manager=manager,
            save_directory=tmp_path,
        )

        assert admitted_items[0].meta["link_candidate_id"] == candidate_id
        assert admitted_items[0].url == items[0].url
        assert manager.queue.snapshot_video_ids() == {admitted_items[0].id}
        queued_item, queued_directory = manager.queue.get_nowait()
        assert queued_item is admitted_items[0]
        assert Path(queued_directory) == tmp_path.resolve()

        with pytest.raises(LinkCandidateAdmissionError) as repeated:
            LinkCandidateAdmissionService(service).admit_to_queue(
                "link_parser",
                started["run_id"],
                [candidate_id],
                execution_profile=owner,
                download_manager=manager,
                save_directory=tmp_path,
            )
        assert repeated.value.code == "candidate_already_admitted"
        assert manager.queue.empty()

        with pytest.raises(LinkCandidateAdmissionError) as caught:
            admission.prepare_items(
                "link_parser",
                started["run_id"],
                [candidate_id],
                execution_profile=other_owner,
            )
        assert caught.value.code == "result_unavailable"
    finally:
        assert service.shutdown(wait=True)


def test_tool_runner_redacts_link_text_when_validation_fails(tmp_path: Path) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool
    from app.core.tools.registry import ToolRegistry
    from app.services.tool_runner_service import ToolRunnerService
    from shared.execution_profile import local_execution_profile

    registry = ToolRegistry(
        tools=[], include_builtins=False, include_entry_points=False
    )
    registry._register(LinkParserTool(), provenance="builtin")
    service = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "history.json",
    )
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:link-parser-invalid",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )
    secret = "validation-secret"
    try:
        response = service.run(
            "link_parser",
            {
                "text": f"https://example.com/p/{secret}?token={secret}",
                "timeout_seconds": 0,
            },
            execution_profile=profile,
        )
    finally:
        assert service.shutdown(wait=True)

    assert response["status"] == "error"
    assert response["parameters"]["text"] == "[redacted]"
    assert secret not in json.dumps(response, ensure_ascii=False)


def test_tool_runner_forbids_expansion_without_network_grant(tmp_path: Path) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool
    from app.core.tools.registry import ToolRegistry
    from app.services.tool_runner_service import ToolRunnerService
    from shared.execution_profile import local_execution_profile

    registry = ToolRegistry(
        tools=[], include_builtins=False, include_entry_points=False
    )
    registry._register(LinkParserTool(), provenance="builtin")
    service = ToolRunnerService(
        registry=registry, history_path=tmp_path / "history.json"
    )
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:link-parser-denied",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )
    try:
        result = service.run(
            "link_parser",
            {"text": "https://b23.tv/no-grant", "expand_short_links": True},
            execution_profile=profile,
        )
        assert result == {
            "status": "forbidden",
            "code": "tool_permission_denied",
            "message": "tool permissions are not granted",
            "tool_id": "link_parser",
        }
        assert service.history(execution_profile=profile) == []
    finally:
        service.shutdown(wait=True)


def test_tool_runner_cancellation_waits_for_bounded_expansion_worker(
    tmp_path: Path,
) -> None:
    from app.core.tools.builtin.link_parser import LinkParserTool
    from app.core.tools.registry import ToolRegistry
    from app.services.tool_runner_service import ToolRunnerService
    from shared.execution_profile import local_execution_profile

    transport = _BoundedBlockingTransport(
        _Response(status_code=200, url="https://www.bilibili.com/video/BV1cancel"),
        max_wait=0.4,
    )

    def transport_factory(**kwargs: Any) -> _BoundedBlockingTransport:
        transport.timeout_seconds = float(kwargs["timeout"])
        return transport

    registry = ToolRegistry(
        tools=[], include_builtins=False, include_entry_points=False
    )
    registry._register(
        LinkParserTool(transport_factory=transport_factory), provenance="builtin"
    )
    service = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "cancel-history.json",
        max_workers=1,
    )
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:link-parser-cancel",
        approved_roots=(tmp_path,),
        tool_permissions=("network",),
        allow_external_plugins=False,
    )
    started = service.run(
        "link_parser",
        {
            "text": "https://b23.tv/cancel",
            "expand_short_links": True,
            "timeout_seconds": 1,
            "deadline_seconds": 1,
        },
        execution_profile=profile,
    )
    assert started["status"] == "queued"
    assert transport.started.wait(0.5)
    try:
        cancellation = service.cancel(started["run_id"], execution_profile=profile)
        assert cancellation["status"] in {"cancelling", "cancelled"}
        assert service.wait_for_idle(timeout=2.0)
        terminal = service.wait_for_run(
            started["run_id"], execution_profile=profile, timeout=0.5
        )
        assert terminal["status"] == "cancelled"
        assert transport.request_thread_name.startswith("tool-runner")
        assert not any(
            thread.name.startswith("link-parser") for thread in threading.enumerate()
        )
    finally:
        transport.release.set()
        assert service.shutdown(wait=True)
