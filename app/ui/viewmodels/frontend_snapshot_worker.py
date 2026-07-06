from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.debug_logger import debug_logger


@dataclass(frozen=True)
class FrontendSnapshotRequest:
    sequence: int
    service: Any
    service_token: int
    mock: bool
    sections: frozenset[str] | None
    cached_snapshot: Mapping[str, Any] | None
    section_signatures: Mapping[str, str]


@dataclass(frozen=True)
class FrontendSnapshotResult:
    sequence: int
    service_token: int
    snapshot: dict[str, Any]
    changed_sections: set[str] | None
    section_signatures: dict[str, str]
    skip_render: bool
    build_duration_ms: float


def build_frontend_snapshot(request: FrontendSnapshotRequest) -> FrontendSnapshotResult:
    started = time.perf_counter()
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

    return FrontendSnapshotResult(
        sequence=request.sequence,
        service_token=request.service_token,
        snapshot=snapshot,
        changed_sections=changed_sections,
        section_signatures=signatures,
        skip_render=skip_render,
        build_duration_ms=(time.perf_counter() - started) * 1000,
    )


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
        self._on_result = on_result
        self._condition = threading.Condition()
        self._pending: FrontendSnapshotRequest | None = None
        self._shutdown = False
        self._thread = threading.Thread(target=self._run, name="frontend-snapshot-worker", daemon=True)
        self._thread.start()

    def submit(self, request: FrontendSnapshotRequest) -> None:
        with self._condition:
            if self._shutdown:
                return
            self._pending = request
            self._condition.notify()

    def shutdown(self) -> None:
        with self._condition:
            self._shutdown = True
            self._condition.notify()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._shutdown:
                    self._condition.wait()
                if self._shutdown:
                    return
                request = self._pending
                self._pending = None
            if request is None:
                continue
            try:
                result = build_frontend_snapshot(request)
            except Exception as exc:
                debug_logger.log_exception(
                    "FrontendSnapshotWorker",
                    "build_frontend_snapshot",
                    exc,
                    details={"sequence": request.sequence, "sections": sorted(request.sections or [])},
                )
                continue
            try:
                self._on_result(result)
            except RuntimeError:
                return
