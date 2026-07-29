from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.services.tool_runner_service import PrivateToolResult
from shared.execution_profile import ExecutionProfile, local_execution_profile


class _Runner:
    def __init__(self, result: PrivateToolResult | None) -> None:
        self.result = result
        self.calls: list[tuple[str, ExecutionProfile]] = []
        self.claimed_candidates: set[tuple[str, str]] = set()

    def lookup_private_result(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> PrivateToolResult | None:
        self.calls.append((run_id, execution_profile))
        return self.result

    def _claim_private_candidates(
        self,
        run_id: str,
        candidate_ids: Sequence[str],
        *,
        execution_profile: ExecutionProfile,
    ) -> bool:
        del execution_profile
        keys = {(run_id, candidate_id) for candidate_id in candidate_ids}
        if keys & self.claimed_candidates:
            return False
        self.claimed_candidates.update(keys)
        return True

    def _release_private_candidates(
        self,
        run_id: str,
        candidate_ids: Sequence[str],
        *,
        execution_profile: ExecutionProfile,
    ) -> bool:
        del execution_profile
        keys = {(run_id, candidate_id) for candidate_id in candidate_ids}
        if not keys <= self.claimed_candidates:
            return False
        self.claimed_candidates.difference_update(keys)
        return True


class _BatchDownloadManager:
    def __init__(self, *, accepted_count: Any = None) -> None:
        self.accepted_count = accepted_count
        self.add_calls: list[tuple[tuple[Any, ...], str]] = []
        self.cancel_calls: list[tuple[str, ...]] = []
        self.raise_on_add = False
        self.raise_on_cancel = False
        self.cancel_status = "cancelled"
        self.add_error_message = "private queue failure"

    def add_tasks(self, videos: Sequence[Any], save_dir: str) -> Any:
        batch = tuple(videos)
        self.add_calls.append((batch, save_dir))
        if self.raise_on_add:
            raise RuntimeError(self.add_error_message)
        if self.accepted_count is None:
            return len(batch)
        return self.accepted_count

    def cancel_videos_and_wait(
        self,
        videos: Sequence[Any],
        timeout_ms: int | None = None,
    ) -> dict[str, str | None]:
        del timeout_ms
        normalized = tuple(video.id for video in videos)
        self.cancel_calls.append(normalized)
        if self.raise_on_cancel:
            raise RuntimeError("private rollback failure")
        return {video_id: self.cancel_status for video_id in normalized}


class _WaitFailureDownloadManager:
    def __init__(self) -> None:
        from app.core.download_manager_core import (
            DownloadManagerCore,
            PendingDownloadQueue,
        )

        self.core = DownloadManagerCore.__new__(DownloadManagerCore)
        self.core.queue = PendingDownloadQueue()
        self.core._workers_lock = threading.RLock()
        self.core._dispatching_tasks = []
        self.core.workers = []
        self.add_calls = 0

    def add_tasks(self, videos: Sequence[Any], save_dir: str) -> int:
        del save_dir
        self.add_calls += 1
        video = tuple(videos)[0]

        class WaitFailureWorker:
            def __init__(self, item: Any) -> None:
                self.video = item

            def stop(self) -> None:
                return None

            def wait(self, _timeout_ms: int) -> bool:
                raise RuntimeError("worker wait unavailable")

        self.core.workers = [WaitFailureWorker(video)]
        return 0

    def cancel_videos_and_wait(
        self,
        videos: Sequence[Any],
        timeout_ms: int | None = None,
    ) -> dict[str, str]:
        del timeout_ms
        return self.core.cancel_videos_and_wait(videos, timeout_ms=1)


class _OversizedSelection(Sequence[str]):
    def __len__(self) -> int:
        return 65

    def __getitem__(self, index: int) -> str:
        raise AssertionError(f"oversized selection must not be materialized: {index}")


class _BrokenLengthSelection(Sequence[str]):
    def __len__(self) -> int:
        raise AssertionError("hostile length")

    def __getitem__(self, index: int) -> str:
        raise AssertionError(f"hostile item: {index}")


class _BrokenItemSelection(Sequence[str]):
    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> str:
        raise AssertionError(f"hostile item: {index}")


class _HostileCandidateId(str):
    def __hash__(self) -> int:
        raise RuntimeError("hostile candidate hash")


def _profile(tmp_path: Path, owner_id: str = "desktop:link-lab") -> ExecutionProfile:
    return local_execution_profile(
        host_surface="test",
        owner_id=owner_id,
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )


def _candidate(
    private_url: str,
    *,
    platform: str = "bilibili",
    resource_kind: str = "media",
    candidate_id: str | None = None,
    display_url: str | None = None,
    format_hint: str | None = None,
) -> dict[str, Any]:
    parts = urlsplit(private_url)
    inferred_format = "PLATFORM"
    if resource_kind == "playlist":
        inferred_format = "HLS"
    elif resource_kind == "media":
        inferred_format = Path(parts.path).suffix.lstrip(".").upper()
    return {
        "candidate_id": candidate_id
        or hashlib.sha256(private_url.encode("utf-8")).hexdigest(),
        "private_url": private_url,
        "display_url": display_url
        or f"{parts.scheme}://{parts.netloc}/[redacted]",
        "platform": platform,
        "resource_kind": resource_kind,
        "format_hint": format_hint or inferred_format,
        "expanded": False,
    }


def _private_result(
    candidates: Sequence[Mapping[str, Any]],
    *,
    tool_id: str = "link_parser",
) -> PrivateToolResult:
    public_rows = [
        {
            key: value
            for key, value in candidate.items()
            if key != "private_url"
        }
        for candidate in candidates
    ]
    return PrivateToolResult(
        run_id="run-link-parser",
        tool_id=tool_id,
        output_paths=(),
        structured_data={"links": public_rows},
        private_data={"candidates": list(candidates)},
    )


def test_admission_builds_canonical_pending_items_from_private_candidates(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionService,
    )

    first = _candidate("https://www.bilibili.com/media/one.mp4?token=private")
    second = _candidate("https://www.douyin.com/media/two.mp4", platform="douyin")
    profile = _profile(tmp_path)
    runner = _Runner(_private_result([first, second]))
    service = LinkCandidateAdmissionService(runner)

    items = service.prepare_items(
        "link_parser",
        "run-link-parser",
        [second["candidate_id"], first["candidate_id"]],
        execution_profile=profile,
    )

    assert [item.url for item in items] == [second["private_url"], first["private_url"]]
    assert [item.source for item in items] == ["douyin", "bilibili"]
    assert all(item.status == "waiting" for item in items)
    assert all(item.meta["content_type"] == "video" for item in items)
    assert all(item.meta["_network_policy"] == "public" for item in items)
    assert [item.meta["link_candidate_id"] for item in items] == [
        second["candidate_id"],
        first["candidate_id"],
    ]
    assert all(item.meta["link_parser_run_id"] == "run-link-parser" for item in items)
    assert all(item.meta["trace_id"].startswith("link_parser_") for item in items)
    assert all("private" not in item.title for item in items)
    assert runner.calls == [("run-link-parser", profile)]


@pytest.mark.parametrize(
    ("candidates", "selection", "expected_code"),
    (
        (
            [_candidate("https://www.bilibili.com/video/BV1", resource_kind="page")],
            None,
            "candidate_requires_crawl_resolution",
        ),
        (
            [_candidate("https://cdn.example.com/video.mp4", platform="generic")],
            None,
            "candidate_downloader_unavailable",
        ),
        (
            [
                _candidate(
                    "https://www.bilibili.com/media/one.mp4",
                    candidate_id="0" * 64,
                )
            ],
            None,
            "candidate_integrity_error",
        ),
    ),
)
def test_admission_rejects_non_downloadable_or_tampered_candidates_atomically(
    tmp_path: Path,
    candidates: list[dict[str, Any]],
    selection: list[str] | None,
    expected_code: str,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    runner = _Runner(_private_result(candidates))
    service = LinkCandidateAdmissionService(runner)
    selected = selection or [candidate["candidate_id"] for candidate in candidates]

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            selected,
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == expected_code
    assert "https://" not in str(caught.value)


@pytest.mark.parametrize(
    ("result", "selection", "expected_code"),
    (
        (None, ["a" * 64], "result_unavailable"),
        (_private_result([], tool_id="file_verify"), ["a" * 64], "result_unavailable"),
        (_private_result([]), [], "selection_required"),
        (_private_result([]), ["a" * 64, "a" * 64], "duplicate_selection"),
        (_private_result([]), ["a" * 64], "unknown_candidate"),
    ),
)
def test_admission_rejects_unavailable_forged_or_duplicate_selection(
    tmp_path: Path,
    result: PrivateToolResult | None,
    selection: list[str],
    expected_code: str,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    service = LinkCandidateAdmissionService(_Runner(result))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            selection,
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == expected_code


def test_admission_rejects_duplicate_private_candidate_rows(tmp_path: Path) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    service = LinkCandidateAdmissionService(
        _Runner(_private_result([candidate, candidate]))
    )

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "candidate_integrity_error"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("display_url", "https://attacker.example/[redacted]"),
        ("platform", "douyin"),
        ("resource_kind", "page"),
        ("expanded", "false"),
    ),
)
def test_admission_rejects_tampered_candidate_projection_metadata(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    candidate[field] = value
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "candidate_integrity_error"


def test_admission_rejects_candidate_rows_with_undeclared_fields(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    candidate["unexpected_private_field"] = "must-not-cross-admission"
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "candidate_integrity_error"
    assert "must-not-cross-admission" not in str(caught.value)


@pytest.mark.parametrize(
    "private_url",
    (
        "https://user:private@www.bilibili.com/media/one.mp4",
        "https://www\u200b.bilibili.com/media/one.mp4",
        "https://xn--a.bilibili.com/media/one.mp4",
    ),
)
def test_admission_rejects_noncanonical_private_urls_without_disclosing_them(
    tmp_path: Path,
    private_url: str,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate(private_url)
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "candidate_integrity_error"
    assert private_url not in str(caught.value)
    assert "private" not in str(caught.value)


def test_admission_rejects_nonvideo_direct_media(tmp_path: Path) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/cover.jpg")
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "candidate_media_type_unsupported"


def test_admission_rejects_oversized_selection_before_candidate_lookup(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    selected = [f"{index:064x}" for index in range(65)]
    runner = _Runner(_private_result([]))
    service = LinkCandidateAdmissionService(runner)

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            selected,
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "selection_too_large"
    assert runner.calls == []


def test_admission_bounds_hostile_sequence_without_materializing_or_lookup(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    runner = _Runner(_private_result([]))
    service = LinkCandidateAdmissionService(runner)

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            _OversizedSelection(),
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "selection_too_large"
    assert runner.calls == []


@pytest.mark.parametrize(
    "selection",
    (_BrokenLengthSelection(), _BrokenItemSelection()),
)
def test_admission_contains_hostile_sequence_errors_before_private_lookup(
    tmp_path: Path,
    selection: Sequence[str],
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    runner = _Runner(_private_result([]))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        LinkCandidateAdmissionService(runner).prepare_items(
            "link_parser",
            "run-link-parser",
            selection,
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "invalid_selection"
    assert runner.calls == []


def test_admission_rejects_hostile_string_subclasses_before_private_lookup(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    runner = _Runner(_private_result([]))
    candidate_id = _HostileCandidateId("a" * 64)

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        LinkCandidateAdmissionService(runner).prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate_id],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "invalid_selection"
    assert runner.calls == []


def test_admission_commits_an_authorized_selection_with_one_batch_call(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionService,
    )

    first = _candidate("https://www.bilibili.com/media/one.mp4")
    second = _candidate("https://www.douyin.com/media/two.mp4", platform="douyin")
    service = LinkCandidateAdmissionService(
        _Runner(_private_result([first, second]))
    )
    manager = _BatchDownloadManager()

    items = service.admit_to_queue(
        "link_parser",
        "run-link-parser",
        [first["candidate_id"], second["candidate_id"]],
        execution_profile=_profile(tmp_path),
        download_manager=manager,
        save_directory=tmp_path,
    )

    assert len(items) == 2
    assert len(manager.add_calls) == 1
    assert manager.add_calls[0][0] == items
    assert Path(manager.add_calls[0][1]) == tmp_path.resolve()
    assert manager.cancel_calls == []


def test_admission_commits_to_the_real_pending_download_queue(tmp_path: Path) -> None:
    from app.core.download_manager_core import DownloadManagerCore, PendingDownloadQueue
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionService,
    )

    first = _candidate("https://www.bilibili.com/media/one.mp4")
    second = _candidate("https://www.douyin.com/media/two.mp4", platform="douyin")
    service = LinkCandidateAdmissionService(
        _Runner(_private_result([first, second]))
    )
    manager = DownloadManagerCore.__new__(DownloadManagerCore)
    manager.queue = PendingDownloadQueue()
    manager.video_only = False
    manager.is_running = True

    items = service.admit_to_queue(
        "link_parser",
        "run-link-parser",
        [first["candidate_id"], second["candidate_id"]],
        execution_profile=_profile(tmp_path),
        download_manager=manager,
        save_directory=tmp_path,
    )

    assert manager.queue.snapshot_video_ids() == {item.id for item in items}
    assert manager.queue.get_nowait()[0] is items[0]
    assert manager.queue.get_nowait()[0] is items[1]


def test_admission_rejects_repeated_confirmation_without_duplicate_queueing(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))
    manager = _BatchDownloadManager()
    kwargs = {
        "execution_profile": _profile(tmp_path),
        "download_manager": manager,
        "save_directory": tmp_path,
    }

    service.admit_to_queue(
        "link_parser",
        "run-link-parser",
        [candidate["candidate_id"]],
        **kwargs,
    )
    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            **kwargs,
        )

    assert caught.value.code == "candidate_already_admitted"
    assert len(manager.add_calls) == 1


def test_admission_claim_survives_service_rebuild_without_duplicate_queueing(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    runner = _Runner(_private_result([candidate]))
    manager = _BatchDownloadManager()
    profile = _profile(tmp_path)
    kwargs = {
        "execution_profile": profile,
        "download_manager": manager,
        "save_directory": tmp_path,
    }

    LinkCandidateAdmissionService(runner).admit_to_queue(
        "link_parser",
        "run-link-parser",
        [candidate["candidate_id"]],
        **kwargs,
    )
    with pytest.raises(LinkCandidateAdmissionError) as caught:
        LinkCandidateAdmissionService(runner).admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            **kwargs,
        )

    assert caught.value.code == "candidate_already_admitted"
    assert len(manager.add_calls) == 1


def test_admission_rejects_an_unauthorized_save_directory_before_queueing(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))
    manager = _BatchDownloadManager()

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(approved_root),
            download_manager=manager,
            save_directory=outside_root,
        )

    assert caught.value.code == "save_directory_unauthorized"
    assert manager.add_calls == []


def test_admission_rejects_a_tampered_format_preview(tmp_path: Path) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate(
        "https://www.bilibili.com/media/one.mp4",
        format_hint="MKV",
    )
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.prepare_items(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
        )

    assert caught.value.code == "candidate_integrity_error"


def test_admission_rolls_back_a_partial_batch_and_allows_a_clean_retry(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))
    manager = _BatchDownloadManager(accepted_count=0)
    kwargs = {
        "execution_profile": _profile(tmp_path),
        "download_manager": manager,
        "save_directory": tmp_path,
    }

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            **kwargs,
        )

    assert caught.value.code == "queue_batch_rejected"
    assert manager.cancel_calls == [
        tuple(item.id for item in manager.add_calls[0][0])
    ]

    manager.accepted_count = None
    items = service.admit_to_queue(
        "link_parser",
        "run-link-parser",
        [candidate["candidate_id"]],
        **kwargs,
    )
    assert len(items) == 1
    assert len(manager.add_calls) == 2


def test_admission_rejects_a_stringified_queue_count_and_rolls_back(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))
    manager = _BatchDownloadManager(accepted_count="1")

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
            download_manager=manager,
            save_directory=tmp_path,
        )

    assert caught.value.code == "queue_batch_rejected"
    assert len(manager.add_calls) == 1
    admitted_item = manager.add_calls[0][0][0]
    assert manager.cancel_calls == [(admitted_item.id,)]


def test_admission_drops_sensitive_queue_exception_context_after_rollback(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    secret = "PRIVATE_SENTINEL"
    candidate = _candidate(
        f"https://www.bilibili.com/media/one.mp4?token={secret}"
    )
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))
    manager = _BatchDownloadManager()
    manager.raise_on_add = True
    manager.add_error_message = f"queue rejected {candidate['private_url']}"

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
            download_manager=manager,
            save_directory=tmp_path,
        )

    assert caught.value.code == "queue_batch_rejected"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in repr(caught.value)


def test_admission_reports_rollback_failure_without_private_queue_details(
    tmp_path: Path,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    service = LinkCandidateAdmissionService(_Runner(_private_result([candidate])))
    manager = _BatchDownloadManager()
    manager.raise_on_add = True
    manager.raise_on_cancel = True

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        service.admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=_profile(tmp_path),
            download_manager=manager,
            save_directory=tmp_path,
        )

    assert caught.value.code == "queue_rollback_failed"
    assert "private" not in str(caught.value)
    assert len(manager.add_calls) == 1
    assert len(manager.cancel_calls) == 1


@pytest.mark.parametrize("cancel_status", (None, "dispatching", "running", "timeout"))
def test_admission_keeps_claim_when_rollback_completion_is_unproven(
    tmp_path: Path,
    cancel_status: str | None,
) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    runner = _Runner(_private_result([candidate]))
    manager = _BatchDownloadManager(accepted_count=0)
    manager.cancel_status = cancel_status
    profile = _profile(tmp_path)

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        LinkCandidateAdmissionService(runner).admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=profile,
            download_manager=manager,
            save_directory=tmp_path,
        )

    assert caught.value.code == "queue_rollback_failed"
    assert ("run-link-parser", candidate["candidate_id"]) in runner.claimed_candidates

    manager.accepted_count = None
    with pytest.raises(LinkCandidateAdmissionError) as repeated:
        LinkCandidateAdmissionService(runner).admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=profile,
            download_manager=manager,
            save_directory=tmp_path,
        )

    assert repeated.value.code == "candidate_already_admitted"
    assert len(manager.add_calls) == 1


def test_admission_keeps_claim_when_worker_wait_raises(tmp_path: Path) -> None:
    from app.services.link_candidate_admission_service import (
        LinkCandidateAdmissionError,
        LinkCandidateAdmissionService,
    )

    candidate = _candidate("https://www.bilibili.com/media/one.mp4")
    runner = _Runner(_private_result([candidate]))
    manager = _WaitFailureDownloadManager()
    profile = _profile(tmp_path)

    with pytest.raises(LinkCandidateAdmissionError) as caught:
        LinkCandidateAdmissionService(runner).admit_to_queue(
            "link_parser",
            "run-link-parser",
            [candidate["candidate_id"]],
            execution_profile=profile,
            download_manager=manager,
            save_directory=tmp_path,
        )

    assert caught.value.code == "queue_rollback_failed"
    assert ("run-link-parser", candidate["candidate_id"]) in runner.claimed_candidates
    assert manager.add_calls == 1
