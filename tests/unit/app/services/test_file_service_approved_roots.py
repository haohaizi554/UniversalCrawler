from __future__ import annotations

import inspect
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services import file_service as file_service_module
from app.services.file_service import (
    MediaDeleteMutationPlan,
    MediaDeleteOutcomeError,
    MediaDeleteStatus,
    MediaLibraryService,
)
from app.services.path_policy import ApprovedChildPath, ApprovedRootsLease, PathPolicy


class _SwapAfterRootLeasePathPolicy(PathPolicy):
    def __init__(
        self,
        *,
        ancestor: Path,
        moved_ancestor: Path,
        replacement_relative_path: Path,
        replacement_payload: bytes,
    ) -> None:
        super().__init__()
        self._ancestor = ancestor
        self._moved_ancestor = moved_ancestor
        self._replacement_relative_path = replacement_relative_path
        self._replacement_payload = replacement_payload
        self.swap_attempted = False
        self.swapped = False

    @contextmanager
    def lease_approved_root_grants(self, approved_root_grants):
        with super().lease_approved_root_grants(approved_root_grants) as lease:
            self.swap_attempted = True
            try:
                self._ancestor.rename(self._moved_ancestor)
            except OSError:
                # A live Windows ancestry handle denies this replacement.
                pass
            else:
                replacement = self._ancestor / self._replacement_relative_path
                replacement.parent.mkdir(parents=True)
                replacement.write_bytes(self._replacement_payload)
                self.swapped = True
            yield lease


class _FinalChildSwapLease:
    def __init__(
        self,
        delegate,
        *,
        source: Path,
        moved_source: Path,
        outside: Path,
    ) -> None:
        self._delegate = delegate
        self._source = source
        self._moved_source = moved_source
        self._outside = outside
        self.swapped = False

    def assert_bound(self) -> None:
        self._delegate.assert_bound()

    @contextmanager
    def bind_child(self, path):
        with self._delegate.bind_child(path) as child:
            if not self.swapped and os.path.samefile(path, self._source):
                self._source.rename(self._moved_source)
                self._source.symlink_to(self._outside)
                self.swapped = True
            yield child


class _SwapFinalChildPathPolicy(PathPolicy):
    def __init__(self, *, source: Path, moved_source: Path, outside: Path) -> None:
        super().__init__()
        self._source = source
        self._moved_source = moved_source
        self._outside = outside
        self.lease: _FinalChildSwapLease | None = None

    @contextmanager
    def lease_approved_root_grants(self, approved_root_grants):
        with super().lease_approved_root_grants(approved_root_grants) as delegate:
            lease = _FinalChildSwapLease(
                delegate,
                source=self._source,
                moved_source=self._moved_source,
                outside=self._outside,
            )
            self.lease = lease
            yield lease


def _video(path: Path) -> VideoItem:
    item = VideoItem(url="", title=path.stem, source="local")
    item.local_path = os.fspath(path)
    return item


def _root_grant(path: Path) -> tuple[str, tuple[int, int]]:
    normalized = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    value = os.lstat(normalized)
    return normalized, (int(value.st_dev), int(value.st_ino))


def _service(policy: PathPolicy) -> MediaLibraryService:
    return MediaLibraryService(
        video_extensions=(".mp4",),
        image_extensions=(".jpg",),
        path_policy=policy,
    )


def test_authorized_delete_cannot_follow_an_approved_root_replacement(
    tmp_path: Path,
) -> None:
    ancestor = tmp_path / "session-ancestor"
    approved = ancestor / "approved"
    source = approved / "video.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"approved")
    moved_ancestor = tmp_path / "session-ancestor-before-swap"
    policy = _SwapAfterRootLeasePathPolicy(
        ancestor=ancestor,
        moved_ancestor=moved_ancestor,
        replacement_relative_path=Path("approved/video.mp4"),
        replacement_payload=b"attacker",
    )

    try:
        _service(policy).delete_media_authorized(
            _video(source),
            approved_root_grants=(_root_grant(approved),),
        )
    except (FileOperationError, OSError):
        pass

    assert policy.swap_attempted
    if policy.swapped:
        assert (ancestor / "approved/video.mp4").read_bytes() == b"attacker"
    else:
        assert not source.exists()


def test_authorized_rename_cannot_follow_an_approved_root_replacement(
    tmp_path: Path,
) -> None:
    ancestor = tmp_path / "session-ancestor"
    approved = ancestor / "approved"
    source = approved / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"approved")
    moved_ancestor = tmp_path / "session-ancestor-before-swap"
    policy = _SwapAfterRootLeasePathPolicy(
        ancestor=ancestor,
        moved_ancestor=moved_ancestor,
        replacement_relative_path=Path("approved/source.mp4"),
        replacement_payload=b"attacker",
    )

    try:
        _service(policy).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )
    except (FileOperationError, OSError):
        pass

    assert policy.swap_attempted
    if policy.swapped:
        replacement_root = ancestor / "approved"
        assert (replacement_root / "source.mp4").read_bytes() == b"attacker"
        assert not (replacement_root / "renamed.mp4").exists()
    else:
        assert not source.exists()
        assert (approved / "renamed.mp4").read_bytes() == b"approved"


def _require_file_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "symlink-probe-target"
    link = tmp_path / "symlink-probe"
    outside.write_bytes(b"probe")
    try:
        link.symlink_to(outside)
        link.unlink()
    except OSError as exc:
        import pytest

        pytest.skip(f"file symlink creation unavailable: {exc}")


def test_authorized_delete_rejects_a_final_child_symlink_swap(
    tmp_path: Path,
) -> None:
    _require_file_symlinks(tmp_path)
    approved = tmp_path / "approved"
    source = approved / "video.mp4"
    moved_source = approved / "video-before-swap.mp4"
    outside = tmp_path / "outside.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    outside.write_bytes(b"outside")
    policy = _SwapFinalChildPathPolicy(
        source=source,
        moved_source=moved_source,
        outside=outside,
    )

    with pytest.raises((FileOperationError, OSError)):
        _service(policy).delete_media_authorized(
            _video(source),
            approved_root_grants=(_root_grant(approved),),
        )

    assert policy.lease is not None and policy.lease.swapped
    assert source.is_symlink()
    assert outside.read_bytes() == b"outside"
    assert moved_source.read_bytes() == b"approved"


def test_authorized_rename_rejects_a_final_child_symlink_swap(
    tmp_path: Path,
) -> None:
    _require_file_symlinks(tmp_path)
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    moved_source = approved / "source-before-swap.mp4"
    outside = tmp_path / "outside.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    outside.write_bytes(b"outside")
    policy = _SwapFinalChildPathPolicy(
        source=source,
        moved_source=moved_source,
        outside=outside,
    )

    with pytest.raises((FileOperationError, OSError)):
        _service(policy).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    assert policy.lease is not None and policy.lease.swapped
    assert source.is_symlink()
    assert outside.read_bytes() == b"outside"
    assert moved_source.read_bytes() == b"approved"
    assert not (approved / "renamed.mp4").exists()


def test_authorized_rename_is_no_replace(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "target.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    target.write_bytes(b"existing")

    with pytest.raises(FileOperationError, match="已存在"):
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "target",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    assert source.read_bytes() == b"approved"
    assert target.read_bytes() == b"existing"


def test_authorized_rename_accepts_the_regular_source_at_linearization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    original = approved / "source-before-linearization.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"original")
    real_rename = ApprovedChildPath.rename_no_replace

    def replace_source_with_regular_successor(self, target_child) -> None:
        if os.path.normcase(self.absolute_path) == os.path.normcase(os.fspath(source)):
            source.rename(original)
            source.write_bytes(b"regular-successor")
        real_rename(self, target_child)

    monkeypatch.setattr(
        ApprovedChildPath,
        "rename_no_replace",
        replace_source_with_regular_successor,
    )

    result = _service(PathPolicy()).rename_media_authorized(
        _video(source),
        "renamed",
        os.fspath(approved),
        approved_root_grants=(_root_grant(approved),),
    )

    assert result == (os.fspath(source), os.fspath(target))
    assert original.read_bytes() == b"original"
    assert target.read_bytes() == b"regular-successor"


def test_authorized_rename_reports_a_committed_invalid_directory_successor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    original = approved / "source-before-linearization.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"original")
    real_rename = ApprovedChildPath.rename_no_replace

    def replace_source_with_directory(self, target_child) -> None:
        if os.path.normcase(self.absolute_path) == os.path.normcase(os.fspath(source)):
            source.rename(original)
            source.mkdir()
        real_rename(self, target_child)

    monkeypatch.setattr(
        ApprovedChildPath,
        "rename_no_replace",
        replace_source_with_directory,
    )

    with pytest.raises(file_service_module.MediaRenameOutcomeError) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is file_service_module.MediaRenameStatus.COMMITTED_TARGET_INVALID
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert original.read_bytes() == b"original"
    assert target.is_dir()


def test_authorized_rename_postchecks_the_authoritative_target_after_a_swap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    moved_target = approved / "renamed-before-postcheck.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    real_rename = ApprovedChildPath.rename_no_replace

    def swap_target_after_rename(self, target_child) -> None:
        real_rename(self, target_child)
        target.rename(moved_target)
        target.mkdir()

    monkeypatch.setattr(
        ApprovedChildPath,
        "rename_no_replace",
        swap_target_after_rename,
    )

    with pytest.raises(file_service_module.MediaRenameOutcomeError) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is file_service_module.MediaRenameStatus.COMMITTED_TARGET_INVALID
    assert receipt.committed is True
    assert moved_target.read_bytes() == b"approved"
    assert target.is_dir()


def test_authorized_rename_reports_uncertain_when_linearized_call_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    real_rename = ApprovedChildPath.rename_no_replace

    def raise_after_rename(self, target_child) -> None:
        real_rename(self, target_child)
        raise OSError("post-commit capability assertion failed")

    monkeypatch.setattr(ApprovedChildPath, "rename_no_replace", raise_after_rename)

    with pytest.raises(file_service_module.MediaRenameOutcomeError) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is file_service_module.MediaRenameStatus.OUTCOME_UNCERTAIN
    assert receipt.committed is None
    assert receipt.retry_safe is False
    assert target.read_bytes() == b"approved"


def test_authorized_rename_receipt_and_error_do_not_expose_absolute_roots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "private-session-root"
    source = approved / "source-\u202eexe.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    real_rename = ApprovedChildPath.rename_no_replace

    def raise_after_rename(self, target_child) -> None:
        real_rename(self, target_child)
        raise OSError(f"hostile path detail: {approved}")

    monkeypatch.setattr(ApprovedChildPath, "rename_no_replace", raise_after_rename)

    with pytest.raises(file_service_module.MediaRenameOutcomeError) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    private_root = os.fspath(approved)
    assert private_root not in str(exc_info.value)
    assert private_root not in repr(exc_info.value)
    assert private_root not in repr(exc_info.value.receipt)
    assert "\u202e" not in exc_info.value.receipt.source_name
    assert exc_info.value.receipt.source_name == "source-exe.mp4"
    assert exc_info.value.receipt.target_name == "renamed.mp4"


def test_authorized_rename_preserves_control_flow_over_uncertain_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class ControlFlowAbort(BaseException):
        def __str__(self) -> str:
            raise AssertionError("control-flow stringification must not run")

        def add_note(self, _note: str) -> None:
            raise RuntimeError("hostile add_note")

    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    primary = ControlFlowAbort()
    real_rename = ApprovedChildPath.rename_no_replace

    def abort_after_rename(self, target_child) -> None:
        real_rename(self, target_child)
        raise primary

    monkeypatch.setattr(ApprovedChildPath, "rename_no_replace", abort_after_rename)

    with pytest.raises(ControlFlowAbort) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    assert exc_info.value is primary
    assert target.read_bytes() == b"approved"


def test_authorized_rename_reports_committed_when_root_postcheck_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    real_rename = ApprovedChildPath.rename_no_replace
    real_assert_bound = ApprovedRootsLease.assert_bound
    committed = False

    def record_commit(self, target_child) -> None:
        nonlocal committed
        real_rename(self, target_child)
        committed = True

    def fail_after_commit(self) -> None:
        if committed:
            raise OSError("approved root identity changed after rename")
        real_assert_bound(self)

    monkeypatch.setattr(ApprovedChildPath, "rename_no_replace", record_commit)
    monkeypatch.setattr(ApprovedRootsLease, "assert_bound", fail_after_commit)

    with pytest.raises(file_service_module.MediaRenameOutcomeError) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is file_service_module.MediaRenameStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert target.read_bytes() == b"approved"


def test_authorized_rename_reports_committed_when_lease_exit_fails(
    tmp_path: Path,
) -> None:
    class ExitFailurePathPolicy(PathPolicy):
        @contextmanager
        def lease_approved_root_grants(self, approved_root_grants):
            with super().lease_approved_root_grants(approved_root_grants) as lease:
                yield lease
                raise OSError("lease exit authority check failed")

    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")

    with pytest.raises(file_service_module.MediaRenameOutcomeError) as exc_info:
        _service(ExitFailurePathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is file_service_module.MediaRenameStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert target.read_bytes() == b"approved"


def test_authorized_rename_preserves_postcommit_control_flow_with_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class PostCommitAbort(BaseException):
        def __str__(self) -> str:
            raise AssertionError("post-commit control flow must not be stringified")

        def add_note(self, _note: str) -> None:
            raise RuntimeError("hostile add_note")

    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "renamed.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    real_rename = ApprovedChildPath.rename_no_replace
    real_assert_bound = ApprovedRootsLease.assert_bound
    primary = PostCommitAbort()
    committed = False

    def record_commit(self, target_child) -> None:
        nonlocal committed
        real_rename(self, target_child)
        committed = True

    def abort_after_commit(self) -> None:
        if committed:
            raise primary
        real_assert_bound(self)

    monkeypatch.setattr(ApprovedChildPath, "rename_no_replace", record_commit)
    monkeypatch.setattr(ApprovedRootsLease, "assert_bound", abort_after_commit)

    with pytest.raises(PostCommitAbort) as exc_info:
        _service(PathPolicy()).rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(approved),
            approved_root_grants=(_root_grant(approved),),
        )

    assert exc_info.value is primary
    receipt = object.__getattribute__(primary, "media_rename_receipt")
    assert receipt.status is file_service_module.MediaRenameStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert target.read_bytes() == b"approved"


def test_authorized_delete_leaves_a_later_temp_generation(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    temp = approved / "video.mp4.downloading"
    original_temp = approved / "video-original.downloading"
    approved.mkdir()
    media.write_bytes(b"media")
    temp.write_bytes(b"original-temp")
    plan = MediaDeleteMutationPlan(
        file_path=os.fspath(media),
        temp_paths=(os.fspath(temp),),
        owned_directories=(),
    )
    temp.rename(original_temp)
    temp.write_bytes(b"later-temp")

    deleted = _service(PathPolicy()).delete_media_authorized(
        _video(media),
        mutation_plan=plan,
        approved_root_grants=(_root_grant(approved),),
    )

    assert deleted is True
    assert not media.exists()
    assert original_temp.read_bytes() == b"original-temp"
    assert temp.read_bytes() == b"later-temp"


def test_authorized_delete_leaves_a_later_owned_directory_generation(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    cleanup_directory = approved / "owned-gallery"
    original_directory = approved / "owned-gallery-original"
    approved.mkdir()
    media.write_bytes(b"media")
    cleanup_directory.mkdir()
    plan = MediaDeleteMutationPlan(
        file_path=os.fspath(media),
        temp_paths=(),
        owned_directories=(os.fspath(cleanup_directory),),
    )
    cleanup_directory.rename(original_directory)
    cleanup_directory.mkdir()

    deleted = _service(PathPolicy()).delete_media_authorized(
        _video(media),
        mutation_plan=plan,
        approved_root_grants=(_root_grant(approved),),
    )

    assert deleted is True
    assert not media.exists()
    assert original_directory.is_dir()
    assert cleanup_directory.is_dir()


def test_authorized_explicit_delete_keeps_current_path_semantics(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    original = approved / "video-before-delete.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    plan = MediaDeleteMutationPlan(
        file_path=os.fspath(media),
        temp_paths=(),
        owned_directories=(),
    )
    media.rename(original)
    media.write_bytes(b"current-path-successor")

    deleted = _service(PathPolicy()).delete_media_authorized(
        _video(media),
        mutation_plan=plan,
        approved_root_grants=(_root_grant(approved),),
    )

    assert deleted is True
    assert original.read_bytes() == b"original"
    assert not media.exists()


def test_authorized_delete_reports_an_unlink_error_as_non_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    real_unlink = ApprovedChildPath.unlink

    def unlink_then_fail(child: ApprovedChildPath) -> None:
        real_unlink(child)
        raise OSError("unlink result unavailable")

    monkeypatch.setattr(ApprovedChildPath, "unlink", unlink_then_fail)

    with pytest.raises(MediaDeleteOutcomeError) as exc_info:
        _service(PathPolicy()).delete_media_authorized(
            _video(media),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is MediaDeleteStatus.OUTCOME_UNCERTAIN
    assert receipt.committed is None
    assert receipt.retry_safe is False
    assert receipt.target_name == "video.mp4"
    assert os.fspath(approved) not in repr(exc_info.value)
    assert not media.exists()
    media.write_bytes(b"later-generation")
    assert media.read_bytes() == b"later-generation"


def test_authorized_delete_reports_a_postcommit_authority_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    unlinked = False
    real_unlink = ApprovedChildPath.unlink
    real_assert_bound = ApprovedRootsLease.assert_bound

    def record_unlink(child: ApprovedChildPath) -> None:
        nonlocal unlinked
        real_unlink(child)
        unlinked = True

    def fail_after_unlink(roots: ApprovedRootsLease) -> None:
        if unlinked:
            raise OSError("authority postcheck unavailable")
        real_assert_bound(roots)

    monkeypatch.setattr(ApprovedChildPath, "unlink", record_unlink)
    monkeypatch.setattr(ApprovedRootsLease, "assert_bound", fail_after_unlink)

    with pytest.raises(MediaDeleteOutcomeError) as exc_info:
        _service(PathPolicy()).delete_media_authorized(
            _video(media),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is MediaDeleteStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert not media.exists()


@pytest.mark.parametrize("exit_level", ("child", "root"))
def test_authorized_delete_reports_postcommit_context_exit_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_level: str,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    policy = PathPolicy()

    if exit_level == "child":
        real_bind_child = ApprovedRootsLease.bind_child

        @contextmanager
        def fail_child_exit(roots: ApprovedRootsLease, path):
            with real_bind_child(roots, path) as child:
                yield child
            raise OSError("child authority exit unavailable")

        monkeypatch.setattr(ApprovedRootsLease, "bind_child", fail_child_exit)
    else:
        real_lease = policy.lease_approved_root_grants

        @contextmanager
        def fail_root_exit(grants):
            with real_lease(grants) as roots:
                yield roots
            raise OSError("root authority exit unavailable")

        monkeypatch.setattr(policy, "lease_approved_root_grants", fail_root_exit)

    with pytest.raises(MediaDeleteOutcomeError) as exc_info:
        _service(policy).delete_media_authorized(
            _video(media),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is MediaDeleteStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert not media.exists()


def test_authorized_delete_preserves_root_exit_control_flow_with_a_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    policy = PathPolicy()
    primary = KeyboardInterrupt("root authority exit interrupted")
    real_lease = policy.lease_approved_root_grants

    @contextmanager
    def fail_root_exit(grants):
        with real_lease(grants) as roots:
            yield roots
        raise primary

    monkeypatch.setattr(policy, "lease_approved_root_grants", fail_root_exit)

    with pytest.raises(KeyboardInterrupt) as exc_info:
        _service(policy).delete_media_authorized(
            _video(media),
            approved_root_grants=(_root_grant(approved),),
        )

    assert exc_info.value is primary
    receipt = object.__getattribute__(primary, "media_delete_receipt")
    assert receipt.status is MediaDeleteStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert not media.exists()


def test_authorized_delete_reports_a_later_target_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    real_unlink = ApprovedChildPath.unlink

    def replace_after_unlink(child: ApprovedChildPath) -> None:
        real_unlink(child)
        Path(child.absolute_path).write_bytes(b"later-generation")

    monkeypatch.setattr(ApprovedChildPath, "unlink", replace_after_unlink)

    with pytest.raises(MediaDeleteOutcomeError) as exc_info:
        _service(PathPolicy()).delete_media_authorized(
            _video(media),
            approved_root_grants=(_root_grant(approved),),
        )

    receipt = exc_info.value.receipt
    assert receipt.status is MediaDeleteStatus.COMMITTED_TARGET_REPLACED
    assert receipt.committed is True
    assert receipt.retry_safe is False
    assert media.read_bytes() == b"later-generation"


def test_authorized_delete_preserves_postunlink_control_flow_with_a_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    media = approved / "video.mp4"
    approved.mkdir()
    media.write_bytes(b"original")
    primary = KeyboardInterrupt("unlink interrupted")
    real_unlink = ApprovedChildPath.unlink

    def unlink_then_abort(child: ApprovedChildPath) -> None:
        real_unlink(child)
        raise primary

    monkeypatch.setattr(ApprovedChildPath, "unlink", unlink_then_abort)

    with pytest.raises(KeyboardInterrupt) as exc_info:
        _service(PathPolicy()).delete_media_authorized(
            _video(media),
            approved_root_grants=(_root_grant(approved),),
        )

    assert exc_info.value is primary
    receipt = object.__getattribute__(primary, "media_delete_receipt")
    assert receipt.status is MediaDeleteStatus.OUTCOME_UNCERTAIN
    assert receipt.committed is None
    assert receipt.retry_safe is False
    assert not media.exists()


def test_authorized_mutations_reject_paths_outside_the_approved_root(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    source = outside / "source.mp4"
    approved.mkdir()
    outside.mkdir()
    source.write_bytes(b"outside")
    service = _service(PathPolicy())

    with pytest.raises(PermissionError):
        service.delete_media_authorized(
            _video(source),
            approved_root_grants=(_root_grant(approved),),
        )
    with pytest.raises(PermissionError):
        service.rename_media_authorized(
            _video(source),
            "renamed",
            os.fspath(outside),
            approved_root_grants=(_root_grant(approved),),
        )

    assert source.read_bytes() == b"outside"


def test_legacy_local_mutation_entrypoints_cannot_silently_accept_web_grants() -> None:
    assert "approved_root_grants" not in inspect.signature(
        MediaLibraryService.delete_media
    ).parameters
    assert "approved_root_grants" not in inspect.signature(
        MediaLibraryService.rename_media
    ).parameters
    assert "approved_root_grants" in inspect.signature(
        MediaLibraryService.delete_media_authorized
    ).parameters
    assert "approved_root_grants" in inspect.signature(
        MediaLibraryService.rename_media_authorized
    ).parameters


@pytest.mark.parametrize("operation", ("delete", "rename"))
def test_authorized_mutation_rejects_a_root_replaced_since_the_session_grant(
    tmp_path: Path,
    operation: str,
) -> None:
    ancestor = tmp_path / "ancestor"
    approved = ancestor / "approved"
    source = approved / "source.mp4"
    approved.mkdir(parents=True)
    source.write_bytes(b"approved")
    grant = _root_grant(approved)
    moved = tmp_path / "ancestor-at-grant"
    ancestor.rename(moved)
    attacker_source = ancestor / "approved/source.mp4"
    attacker_source.parent.mkdir(parents=True)
    attacker_source.write_bytes(b"attacker")
    service = _service(PathPolicy())

    with pytest.raises((PermissionError, FileOperationError, OSError)):
        if operation == "delete":
            service.delete_media_authorized(
                _video(source),
                approved_root_grants=(grant,),
            )
        else:
            service.rename_media_authorized(
                _video(source),
                "renamed",
                os.fspath(approved),
                approved_root_grants=(grant,),
            )

    assert attacker_source.read_bytes() == b"attacker"
    assert not (attacker_source.parent / "renamed.mp4").exists()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows case-insensitive aliases")
def test_authorized_rename_preserves_case_only_rename_support(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "Source.mp4"
    target = approved / "source.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")

    result = _service(PathPolicy()).rename_media_authorized(
        _video(source),
        "source",
        os.fspath(approved),
        approved_root_grants=(_root_grant(approved),),
    )

    assert result == (os.fspath(source), os.fspath(target))
    assert os.listdir(approved) == ["source.mp4"]
    assert target.read_bytes() == b"approved"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows case-insensitive aliases")
def test_authorized_rename_preserves_requested_uppercase_spelling(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    target = approved / "SOURCE.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")

    result = _service(PathPolicy()).rename_media_authorized(
        _video(source),
        "SOURCE",
        os.fspath(approved),
        approved_root_grants=(_root_grant(approved),),
    )

    assert result == (os.fspath(source), os.fspath(target))
    assert os.listdir(approved) == ["SOURCE.mp4"]
    assert target.read_bytes() == b"approved"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows directory leases")
def test_case_only_rename_holds_the_nested_parent_until_the_syscall(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approved = tmp_path / "approved"
    nested = approved / "nested"
    moved_nested = approved / "nested-before-swap"
    source = nested / "Source.mp4"
    target = nested / "source.mp4"
    nested.mkdir(parents=True)
    source.write_bytes(b"approved")
    real_rename = os.rename
    parent_move_blocked = False

    def rename_with_parent_swap_attempt(old, new) -> None:
        nonlocal parent_move_blocked
        if os.path.normcase(os.path.abspath(os.fspath(old))) == os.path.normcase(
            os.path.abspath(os.fspath(source))
        ):
            try:
                real_rename(nested, moved_nested)
            except OSError:
                parent_move_blocked = True
        real_rename(old, new)

    monkeypatch.setattr("app.services.file_service.os.rename", rename_with_parent_swap_attempt)

    result = _service(PathPolicy()).rename_media_authorized(
        _video(source),
        "source",
        os.fspath(nested),
        approved_root_grants=(_root_grant(approved),),
    )

    assert parent_move_blocked
    assert result == (os.fspath(source), os.fspath(target))
    assert target.read_bytes() == b"approved"


def test_authorized_rename_noop_still_requires_the_granted_root_generation(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    source = approved / "source.mp4"
    approved.mkdir()
    source.write_bytes(b"approved")
    grant = _root_grant(approved)
    moved = tmp_path / "approved-at-grant"
    approved.rename(moved)
    approved.mkdir()
    attacker_source = approved / source.name
    attacker_source.write_bytes(b"attacker")

    with pytest.raises((FileOperationError, OSError, PermissionError)):
        _service(PathPolicy()).rename_media_authorized(
            _video(attacker_source),
            attacker_source.stem,
            os.fspath(approved),
            approved_root_grants=(grant,),
        )

    assert attacker_source.read_bytes() == b"attacker"
