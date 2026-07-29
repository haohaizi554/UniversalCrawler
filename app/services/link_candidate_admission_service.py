"""Owner-scoped admission of trusted link-parser candidates."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.core.tools.builtin.link_parser import (
    classify_link_url,
    link_candidate_id,
    link_format_hint,
    normalize_link_url,
    redacted_link_url,
)
from app.models import VideoItem
from app.services.path_policy import PathPolicy
from app.services.tool_runner_service import PrivateToolResult
from shared.execution_profile import ExecutionProfile


_MAX_SELECTED_CANDIDATES = 64
_SUPPORTED_DOWNLOAD_SOURCES = frozenset(
    {"bilibili", "douyin", "kuaishou", "missav", "xiaohongshu"}
)
_VIDEO_EXTENSIONS = frozenset(
    {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".ts", ".webm"}
)
_PUBLIC_CANDIDATE_KEYS = (
    "candidate_id",
    "display_url",
    "platform",
    "resource_kind",
    "format_hint",
    "expanded",
)
_PUBLIC_CANDIDATE_KEY_SET = frozenset(_PUBLIC_CANDIDATE_KEYS)
_PRIVATE_CANDIDATE_KEY_SET = frozenset(
    (*_PUBLIC_CANDIDATE_KEYS, "private_url")
)


class _PrivateResultLookup(Protocol):
    def lookup_private_result(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> PrivateToolResult | None: ...

    def _claim_private_candidates(
        self,
        run_id: str,
        candidate_ids: tuple[str, ...],
        *,
        execution_profile: ExecutionProfile,
    ) -> bool: ...

    def _release_private_candidates(
        self,
        run_id: str,
        candidate_ids: tuple[str, ...],
        *,
        execution_profile: ExecutionProfile,
    ) -> bool: ...


class _BatchDownloadManager(Protocol):
    def add_tasks(self, videos: Sequence[VideoItem], save_dir: str) -> int: ...

    def cancel_videos_and_wait(
        self,
        videos: Sequence[VideoItem],
        timeout_ms: int | None = None,
    ) -> Mapping[str, str | None]: ...


class LinkCandidateAdmissionError(ValueError):
    """Stable non-sensitive rejection returned by the trusted host boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        super().__init__(str(message))


class LinkCandidateAdmissionService:
    """Resolve a current-process parser result into pending download items."""

    def __init__(self, tool_runner_service: _PrivateResultLookup) -> None:
        self._tool_runner_service = tool_runner_service

    def prepare_items(
        self,
        tool_id: str,
        run_id: str,
        candidate_ids: Sequence[str],
        *,
        execution_profile: ExecutionProfile,
    ) -> tuple[VideoItem, ...]:
        normalized_run_id = str(run_id or "").strip()
        if str(tool_id or "").strip() != "link_parser" or not normalized_run_id:
            raise self._error("result_unavailable", "link result is unavailable")

        selected_ids = self._validate_selection(candidate_ids)
        private_result = self._tool_runner_service.lookup_private_result(
            normalized_run_id,
            execution_profile=execution_profile,
        )
        if (
            private_result is None
            or private_result.tool_id != "link_parser"
            or private_result.run_id != normalized_run_id
        ):
            raise self._error("result_unavailable", "link result is unavailable")

        candidates = self._validated_candidates(private_result)
        unknown = [candidate_id for candidate_id in selected_ids if candidate_id not in candidates]
        if unknown:
            raise self._error("unknown_candidate", "selected link is unavailable")

        return tuple(
            self._build_item(
                normalized_run_id,
                candidates[candidate_id],
            )
            for candidate_id in selected_ids
        )

    def admit_to_queue(
        self,
        tool_id: str,
        run_id: str,
        candidate_ids: Sequence[str],
        *,
        execution_profile: ExecutionProfile,
        download_manager: _BatchDownloadManager,
        save_directory: str | os.PathLike[str],
    ) -> tuple[VideoItem, ...]:
        """Validate and commit one owner-scoped selection as a single batch."""

        items = self.prepare_items(
            tool_id,
            run_id,
            candidate_ids,
            execution_profile=execution_profile,
        )
        authorized_save_directory = self._authorize_save_directory(
            save_directory,
            execution_profile,
        )
        add_tasks = getattr(download_manager, "add_tasks", None)
        cancel_videos_and_wait = getattr(
            download_manager,
            "cancel_videos_and_wait",
            None,
        )
        if not callable(add_tasks) or not callable(cancel_videos_and_wait):
            raise self._error(
                "queue_batch_unavailable",
                "download queue does not support atomic batch admission",
            )

        normalized_run_id = str(run_id).strip()
        selected_ids = tuple(str(item.meta["link_candidate_id"]) for item in items)
        try:
            claimed = self._tool_runner_service._claim_private_candidates(
                normalized_run_id,
                selected_ids,
                execution_profile=execution_profile,
            )
        except Exception:
            claimed = False
        if not claimed:
            raise self._error(
                "candidate_already_admitted",
                "selected link has already been admitted",
            )

        add_failed = False
        try:
            accepted_count = add_tasks(items, authorized_save_directory)
        except Exception:
            add_failed = True
            accepted_count = None

        if add_failed:
            if not self._rollback_and_release_claim(
                cancel_videos_and_wait,
                items,
                normalized_run_id,
                selected_ids,
                execution_profile,
            ):
                raise self._error(
                    "queue_rollback_failed",
                    "download queue rollback could not be confirmed",
                ) from None
            raise self._error(
                "queue_batch_rejected",
                "download queue rejected the selected links",
            )

        if type(accepted_count) is not int or accepted_count != len(items):
            if not self._rollback_and_release_claim(
                cancel_videos_and_wait,
                items,
                normalized_run_id,
                selected_ids,
                execution_profile,
            ):
                raise self._error(
                    "queue_rollback_failed",
                    "download queue rollback could not be confirmed",
                )
            raise self._error(
                "queue_batch_rejected",
                "download queue rejected the selected links",
            )
        return items

    @staticmethod
    def _authorize_save_directory(
        save_directory: str | os.PathLike[str],
        execution_profile: ExecutionProfile,
    ) -> str:
        approved_roots = tuple(str(Path(root)) for root in execution_profile.approved_roots)
        if not approved_roots:
            raise LinkCandidateAdmissionService._error(
                "save_directory_unauthorized",
                "download directory is not authorized",
            )
        try:
            return PathPolicy().resolve_existing_dir(
                os.fspath(save_directory),
                approved_roots,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            raise LinkCandidateAdmissionService._error(
                "save_directory_unauthorized",
                "download directory is not authorized",
            ) from None

    def _rollback_and_release_claim(
        self,
        cancel_videos_and_wait: Any,
        items: Sequence[VideoItem],
        run_id: str,
        candidate_ids: tuple[str, ...],
        execution_profile: ExecutionProfile,
    ) -> bool:
        video_ids = tuple(item.id for item in items)
        try:
            result = cancel_videos_and_wait(items)
        except Exception:
            return False
        if (
            not isinstance(result, Mapping)
            or set(result) != set(video_ids)
            or any(result.get(video_id) != "cancelled" for video_id in video_ids)
        ):
            return False
        try:
            return bool(
                self._tool_runner_service._release_private_candidates(
                    run_id,
                    candidate_ids,
                    execution_profile=execution_profile,
                )
            )
        except Exception:
            return False

    @staticmethod
    def _validate_selection(candidate_ids: Sequence[str]) -> tuple[str, ...]:
        if isinstance(candidate_ids, (str, bytes, bytearray)) or not isinstance(
            candidate_ids, Sequence
        ):
            raise LinkCandidateAdmissionService._error(
                "invalid_selection",
                "link selection is invalid",
            )
        try:
            selected_count = len(candidate_ids)
        except Exception:
            raise LinkCandidateAdmissionService._error(
                "invalid_selection",
                "link selection is invalid",
            ) from None
        if selected_count == 0:
            raise LinkCandidateAdmissionService._error(
                "selection_required",
                "at least one link must be selected",
            )
        if selected_count > _MAX_SELECTED_CANDIDATES:
            raise LinkCandidateAdmissionService._error(
                "selection_too_large",
                "too many links were selected",
            )
        try:
            selected = tuple(candidate_ids[index] for index in range(selected_count))
        except Exception:
            raise LinkCandidateAdmissionService._error(
                "invalid_selection",
                "link selection is invalid",
            ) from None
        if any(not LinkCandidateAdmissionService._is_candidate_id(value) for value in selected):
            raise LinkCandidateAdmissionService._error(
                "invalid_selection",
                "link selection is invalid",
            )
        if len(set(selected)) != len(selected):
            raise LinkCandidateAdmissionService._error(
                "duplicate_selection",
                "link selection contains duplicates",
            )
        return selected

    @classmethod
    def _validated_candidates(
        cls,
        private_result: PrivateToolResult,
    ) -> dict[str, Mapping[str, Any]]:
        raw_candidates = private_result.private_data.get("candidates")
        raw_public_rows = private_result.structured_data.get("links")
        if not cls._is_row_sequence(raw_candidates) or not cls._is_row_sequence(
            raw_public_rows
        ):
            raise cls._integrity_error()

        public_rows: dict[str, Mapping[str, Any]] = {}
        for raw_row in raw_public_rows:
            if (
                not isinstance(raw_row, Mapping)
                or set(raw_row) != _PUBLIC_CANDIDATE_KEY_SET
            ):
                raise cls._integrity_error()
            candidate_id = raw_row.get("candidate_id")
            if not cls._is_candidate_id(candidate_id) or candidate_id in public_rows:
                raise cls._integrity_error()
            public_rows[candidate_id] = raw_row

        candidates: dict[str, Mapping[str, Any]] = {}
        for raw_candidate in raw_candidates:
            if (
                not isinstance(raw_candidate, Mapping)
                or set(raw_candidate) != _PRIVATE_CANDIDATE_KEY_SET
            ):
                raise cls._integrity_error()
            candidate_id = raw_candidate.get("candidate_id")
            if not cls._is_candidate_id(candidate_id) or candidate_id in candidates:
                raise cls._integrity_error()
            private_url = raw_candidate.get("private_url")
            if not isinstance(private_url, str):
                raise cls._integrity_error()
            try:
                canonical_url = normalize_link_url(private_url)
            except ValueError:
                raise cls._integrity_error() from None
            if canonical_url != private_url or link_candidate_id(private_url) != candidate_id:
                raise cls._integrity_error()

            platform, resource_kind = classify_link_url(private_url)
            expected_public = {
                "candidate_id": candidate_id,
                "display_url": redacted_link_url(private_url),
                "platform": platform,
                "resource_kind": resource_kind,
                "format_hint": link_format_hint(private_url, resource_kind),
                "expanded": raw_candidate.get("expanded"),
            }
            if type(expected_public["expanded"]) is not bool:
                raise cls._integrity_error()
            if any(raw_candidate.get(key) != value for key, value in expected_public.items()):
                raise cls._integrity_error()
            public_row = public_rows.get(candidate_id)
            if public_row is None or any(
                public_row.get(key) != expected_public[key]
                for key in _PUBLIC_CANDIDATE_KEYS
            ):
                raise cls._integrity_error()
            candidates[candidate_id] = raw_candidate

        if set(candidates) != set(public_rows):
            raise cls._integrity_error()
        return candidates

    @classmethod
    def _build_item(
        cls,
        run_id: str,
        candidate: Mapping[str, Any],
    ) -> VideoItem:
        candidate_id = str(candidate["candidate_id"])
        private_url = str(candidate["private_url"])
        platform = str(candidate["platform"])
        resource_kind = str(candidate["resource_kind"])
        if resource_kind == "page":
            raise cls._error(
                "candidate_requires_crawl_resolution",
                "selected link must be resolved by its platform crawler",
            )
        if platform not in _SUPPORTED_DOWNLOAD_SOURCES:
            raise cls._error(
                "candidate_downloader_unavailable",
                "no downloader is available for the selected link",
            )
        if resource_kind == "playlist":
            if platform != "missav":
                raise cls._error(
                    "candidate_downloader_unavailable",
                    "no downloader is available for the selected link",
                )
        elif resource_kind == "media":
            path = urlsplit(private_url).path.lower()
            if not any(path.endswith(extension) for extension in _VIDEO_EXTENSIONS):
                raise cls._error(
                    "candidate_media_type_unsupported",
                    "selected media type is not supported for direct admission",
                )
        else:
            raise cls._integrity_error()

        trace_id = f"link_parser_{run_id}_{candidate_id[:12]}"
        return VideoItem(
            url=private_url,
            title=f"{platform}_{resource_kind}_{candidate_id[:12]}",
            source=platform,
            status="waiting",
            meta={
                "content_type": "video",
                "resource_kind": resource_kind,
                "format_hint": str(candidate["format_hint"]),
                "display_url": str(candidate["display_url"]),
                "expanded": bool(candidate["expanded"]),
                "link_candidate_id": candidate_id,
                "link_parser_run_id": run_id,
                "trace_id": trace_id,
                "_network_policy": "public",
            },
        )

    @staticmethod
    def _is_row_sequence(value: Any) -> bool:
        return isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        )

    @staticmethod
    def _is_candidate_id(value: Any) -> bool:
        return (
            type(value) is str
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _integrity_error() -> LinkCandidateAdmissionError:
        return LinkCandidateAdmissionService._error(
            "candidate_integrity_error",
            "link result failed integrity validation",
        )

    @staticmethod
    def _error(code: str, message: str) -> LinkCandidateAdmissionError:
        return LinkCandidateAdmissionError(code, message)


__all__ = [
    "LinkCandidateAdmissionError",
    "LinkCandidateAdmissionService",
]
