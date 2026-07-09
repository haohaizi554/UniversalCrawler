from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.debug_logger import debug_logger
from app.ui.viewmodels.latest_worker import LatestRequestWorker


@dataclass(frozen=True)
class FrontendSnapshotRequest:
    sequence: int
    service: Any
    service_token: int
    mock: bool
    sections: frozenset[str] | None
    cached_snapshot: Mapping[str, Any] | None
    section_signatures: Mapping[str, str]
    use_delta: bool = False
    base_version: int = 0


@dataclass(frozen=True)
class FrontendSnapshotResult:
    sequence: int
    service_token: int
    snapshot: dict[str, Any]
    changed_sections: set[str] | None
    section_signatures: dict[str, str]
    skip_render: bool
    build_duration_ms: float
    page_item_rows: dict[str, dict[str, int]] = field(default_factory=dict)
    completed_item_ids: tuple[str, ...] = ()


def build_frontend_snapshot(request: FrontendSnapshotRequest) -> FrontendSnapshotResult:
    started = time.perf_counter()
    if request.use_delta and request.cached_snapshot:
        return _build_delta_snapshot(request, started)

    sections = request.sections
    cached = dict(request.cached_snapshot or {}) if request.cached_snapshot and sections else None
    snapshot = request.service.get_snapshot(mock=request.mock, sections=sections)
    changed_sections: set[str] | None

    if cached and sections:
        merged = dict(cached)
        merged.update(snapshot)
        snapshot = merged
        signatures = dict(request.section_signatures or {})
        changed_sections = _changed_sections(snapshot, sections, signatures)
        skip_render = not changed_sections
    elif sections:
        changed_sections = {section for section in sections if section in snapshot}
        signatures = _remember_section_signatures(
            snapshot,
            changed_sections,
            dict(request.section_signatures or {}),
        )
        skip_render = not changed_sections
    else:
        changed_sections = None
        signatures = _remember_section_signatures(snapshot, None, dict(request.section_signatures or {}))
        skip_render = False

    return _snapshot_result(
        sequence=request.sequence,
        service_token=request.service_token,
        snapshot=snapshot,
        changed_sections=changed_sections,
        section_signatures=signatures,
        skip_render=skip_render,
        started=started,
    )


def _build_delta_snapshot(request: FrontendSnapshotRequest, started: float) -> FrontendSnapshotResult:
    sections = request.sections
    cached = dict(request.cached_snapshot or {})
    base_version = _request_base_version(request, cached)
    delta = request.service.get_delta(base_version, sections=sections)
    version = _coerce_int(delta.get("version"), fallback=base_version)
    delta_sections = delta.get("sections") if isinstance(delta, Mapping) else {}
    if not isinstance(delta_sections, Mapping):
        delta_sections = {}

    if bool(delta.get("full")):
        snapshot = dict(delta_sections)
        if not snapshot:
            snapshot = request.service.get_snapshot(mock=request.mock, sections=None)
        snapshot["version"] = version
        signatures = _remember_section_signatures(snapshot, None, dict(request.section_signatures or {}))
        return _snapshot_result(
            sequence=request.sequence,
            service_token=request.service_token,
            snapshot=snapshot,
            changed_sections=None,
            section_signatures=signatures,
            skip_render=False,
            started=started,
        )

    snapshot = dict(cached)
    snapshot.update(dict(delta_sections))
    missing_explicit_sections = _missing_explicit_sections(sections, delta_sections)
    if missing_explicit_sections:
        explicit_snapshot = request.service.get_snapshot(mock=request.mock, sections=frozenset(missing_explicit_sections))
        snapshot.update({key: value for key, value in explicit_snapshot.items() if key in missing_explicit_sections})

    snapshot["version"] = version
    requested = _changed_section_candidates(delta, delta_sections, missing_explicit_sections)
    signatures = dict(request.section_signatures or {})
    changed_sections = _changed_sections(snapshot, frozenset(requested), signatures) if requested else set()
    return _snapshot_result(
        sequence=request.sequence,
        service_token=request.service_token,
        snapshot=snapshot,
        changed_sections=changed_sections,
        section_signatures=signatures,
        skip_render=not changed_sections,
        started=started,
    )


def _snapshot_result(
    *,
    sequence: int,
    service_token: int,
    snapshot: dict[str, Any],
    changed_sections: set[str] | None,
    section_signatures: dict[str, str],
    skip_render: bool,
    started: float,
) -> FrontendSnapshotResult:
    page_item_rows, completed_item_ids = _page_item_indexes(snapshot)
    return FrontendSnapshotResult(
        sequence=sequence,
        service_token=service_token,
        snapshot=snapshot,
        changed_sections=changed_sections,
        section_signatures=section_signatures,
        skip_render=skip_render,
        build_duration_ms=(time.perf_counter() - started) * 1000,
        page_item_rows=page_item_rows,
        completed_item_ids=completed_item_ids,
    )


_PAGE_SECTION_KEYS = {
    "queue": "queue_items",
    "active": "active_downloads",
    "completed": "completed_items",
    "failed": "failed_items",
}


def _page_item_indexes(snapshot: Mapping[str, Any]) -> tuple[dict[str, dict[str, int]], tuple[str, ...]]:
    page_item_rows: dict[str, dict[str, int]] = {page_id: {} for page_id in _PAGE_SECTION_KEYS}
    completed_item_ids: list[str] = []
    for page_id, section in _PAGE_SECTION_KEYS.items():
        rows = page_item_rows[page_id]
        items = snapshot.get(section) if isinstance(snapshot, Mapping) else ()
        if not isinstance(items, list | tuple):
            continue
        for row, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            rows.setdefault(item_id, row)
            if page_id == "completed":
                completed_item_ids.append(item_id)
    return page_item_rows, tuple(completed_item_ids)


def _request_base_version(request: FrontendSnapshotRequest, cached_snapshot: Mapping[str, Any]) -> int:
    explicit = _coerce_int(request.base_version, fallback=0)
    if explicit > 0:
        return explicit
    return _coerce_int(cached_snapshot.get("version"), fallback=0)


def _coerce_int(value: Any, *, fallback: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return fallback


def _missing_explicit_sections(
    sections: frozenset[str] | None,
    delta_sections: Mapping[str, Any],
) -> set[str]:
    if not sections:
        return set()
    return {section for section in sections if section not in delta_sections}


def _changed_section_candidates(
    delta: Mapping[str, Any],
    delta_sections: Mapping[str, Any],
    missing_explicit_sections: set[str],
) -> set[str]:
    changed = {
        str(section)
        for section in (delta.get("changed_sections") or [])
        if section
    }
    changed.update(str(section) for section in delta_sections.keys() if section)
    changed.update(missing_explicit_sections)
    return changed


def _section_signature(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        payload = repr(value)
    return hashlib.blake2b(payload.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _changed_sections(snapshot: Mapping[str, Any], sections: frozenset[str], signatures: dict[str, str]) -> set[str]:
    changed: set[str] = set()
    for section in sections:
        signature = _section_signature(snapshot.get(section))
        if signatures.get(section) != signature:
            changed.add(section)
        signatures[section] = signature
    return changed


def _remember_section_signatures(
    snapshot: Mapping[str, Any],
    sections: set[str] | None,
    signatures: dict[str, str],
) -> dict[str, str]:
    keys = set(snapshot.keys()) if sections is None else set(sections)
    keys.discard("version")
    for section in keys:
        signatures[section] = _section_signature(snapshot.get(section))
    return signatures


class FrontendSnapshotWorker:
    """Latest-state-wins worker for GUI snapshot construction and diffing."""

    def __init__(self, on_result: Callable[[FrontendSnapshotResult], None]) -> None:
        self._worker = LatestRequestWorker(
            name="frontend-snapshot-worker",
            on_result=on_result,
            process=self._process,
        )

    def submit(self, request: FrontendSnapshotRequest) -> None:
        self._worker.submit(request)

    def shutdown(self) -> None:
        self._worker.shutdown()

    @staticmethod
    def _process(request: FrontendSnapshotRequest) -> FrontendSnapshotResult | None:
        try:
            return build_frontend_snapshot(request)
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendSnapshotWorker",
                "build_frontend_snapshot",
                exc,
                details={"sequence": request.sequence, "sections": sorted(request.sections or [])},
            )
            return None
