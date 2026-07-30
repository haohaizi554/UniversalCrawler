from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

import app.services.updater_owned_generation as generation_module
import shared.filesystem_directory_capability as capability_module
from app.services.updater_owned_generation import (
    GenerationCollisionError,
    GenerationIntegrityError,
    GenerationPublishUncertainError,
    OwnedGeneration,
    PublishStatus,
)
from shared.filesystem_directory_capability import filesystem_directory_capability


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _create_generation(capability):
    try:
        return OwnedGeneration.create(capability)
    except OSError as exc:
        if exc.errno == errno.ENOTSUP:
            pytest.skip("exact owned generations are unavailable on this platform")
        raise


def test_owned_generation_publishes_full_digest_target_and_holds_lease(
    tmp_path: Path,
) -> None:
    payload = b"signed installer payload"
    digest = _digest(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload[:7])
        generation.write(payload[7:])
        source_stat = os.fstat(generation.fileno())
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        with pytest.raises(OSError, match="not writable"):
            generation.fileno()
        lease = generation.publish_content_addressed("installer.exe")

        assert lease.name == f"{digest}-installer.exe"
        assert not hasattr(lease, "path")
        assert lease.size == len(payload)
        assert lease.sha256 == digest
        assert lease.receipt.status is PublishStatus.COMMITTED
        lease_stat = os.fstat(lease.fileno())
        assert (lease_stat.st_dev, lease_stat.st_ino) == (
            source_stat.st_dev,
            source_stat.st_ino,
        )
        with pytest.raises(OSError):
            os.write(lease.fileno(), b"must be read-only")
        os.lseek(lease.fileno(), 0, os.SEEK_SET)
        assert os.read(lease.fileno(), len(payload) + 1) == payload
        published_path = tmp_path / lease.name
        descriptor = lease.fileno()
        lease.close()
        lease.close()
        with pytest.raises(OSError):
            os.fstat(descriptor)
        assert published_path.read_bytes() == payload


def test_matching_collision_reuses_descriptor_verified_target(tmp_path: Path) -> None:
    payload = b"already published payload"
    digest = _digest(payload)
    target = tmp_path / f"{digest}-installer.exe"
    target.write_bytes(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        with generation.publish_content_addressed("installer.exe") as lease:
            assert lease.receipt.status is PublishStatus.EXISTING_VERIFIED
            os.lseek(lease.fileno(), 0, os.SEEK_SET)
            assert os.read(lease.fileno(), len(payload) + 1) == payload


def test_matching_collision_cleanup_failure_does_not_override_verified_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"already published payload"
    digest = _digest(payload)
    target = tmp_path / f"{digest}-installer.exe"
    target.write_bytes(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_discard = generation._native.discard_after_known_no_commit

        def discard_then_fail() -> None:
            real_discard()
            raise OSError("source cleanup failed after collision")

        monkeypatch.setattr(
            generation._native,
            "discard_after_known_no_commit",
            discard_then_fail,
        )
        with generation.publish_content_addressed("installer.exe") as lease:
            assert lease.receipt.status is PublishStatus.EXISTING_VERIFIED
            assert any(
                value.startswith("collision-source-cleanup:")
                for value in lease.receipt.diagnostics
            )


def test_matching_collision_cleanup_control_flow_is_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"already published payload"
    digest = _digest(payload)
    target = tmp_path / f"{digest}-installer.exe"
    target.write_bytes(payload)
    control = SystemExit("source cleanup interrupted")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_discard = generation._native.discard_after_known_no_commit

        def discard_then_interrupt() -> None:
            real_discard()
            raise control

        monkeypatch.setattr(
            generation._native,
            "discard_after_known_no_commit",
            discard_then_interrupt,
        )
        with pytest.raises(SystemExit) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value is control
    assert target.read_bytes() == payload


def test_collision_receipt_control_flow_closes_verified_target_descriptor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"already published payload"
    digest = _digest(payload)
    target = tmp_path / f"{digest}-installer.exe"
    target.write_bytes(payload)
    control = KeyboardInterrupt("receipt creation interrupted")
    opened: list[int] = []

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_open = capability.open_owned_generation_lease

        def capture_open(name: str) -> int:
            descriptor = real_open(name)
            opened.append(descriptor)
            return descriptor

        monkeypatch.setattr(capability, "open_owned_generation_lease", capture_open)
        monkeypatch.setattr(
            capability,
            "verified_existing_receipt",
            lambda *_args: (_ for _ in ()).throw(control),
        )

        with pytest.raises(KeyboardInterrupt) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value is control
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_collision_rewind_control_flow_closes_verified_target_descriptor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"already published payload"
    digest = _digest(payload)
    target = tmp_path / f"{digest}-installer.exe"
    target.write_bytes(payload)
    control = SystemExit("rewind interrupted")
    opened: list[int] = []

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_open = capability.open_owned_generation_lease
        real_lseek = generation_module.os.lseek
        target_lseek_calls = 0

        def capture_open(name: str) -> int:
            descriptor = real_open(name)
            opened.append(descriptor)
            return descriptor

        def interrupt_second_lseek(
            descriptor: int,
            offset: int,
            whence: int,
        ) -> int:
            nonlocal target_lseek_calls
            if descriptor in opened:
                target_lseek_calls += 1
                if target_lseek_calls == 2:
                    raise control
            return real_lseek(descriptor, offset, whence)

        monkeypatch.setattr(capability, "open_owned_generation_lease", capture_open)
        monkeypatch.setattr(
            generation_module.os,
            "lseek",
            interrupt_second_lseek,
        )

        with pytest.raises(SystemExit) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value is control
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_wrong_collision_fails_closed_and_preserves_existing_target(
    tmp_path: Path,
) -> None:
    payload = b"expected payload"
    digest = _digest(payload)
    target = tmp_path / f"{digest}-installer.exe"
    target.write_bytes(b"attacker payload")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)

        with pytest.raises(GenerationCollisionError):
            generation.publish_content_addressed("installer.exe")

    assert target.read_bytes() == b"attacker payload"


def test_collision_reparse_is_never_reused(tmp_path: Path) -> None:
    payload = b"expected payload"
    digest = _digest(payload)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(payload)
    target = tmp_path / f"{digest}-installer.exe"
    try:
        target.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation unavailable: {exc}")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        with pytest.raises(GenerationCollisionError):
            generation.publish_content_addressed("installer.exe")

    assert target.is_symlink()
    assert outside.read_bytes() == payload


def test_finalize_rejects_wrong_digest_before_publish(tmp_path: Path) -> None:
    payload = b"expected payload"

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        with pytest.raises(GenerationIntegrityError):
            generation.finalize(
                expected_size=len(payload),
                expected_sha256="0" * 64,
            )
        generation.close()

    assert not list(tmp_path.glob("*-installer.exe"))


def test_write_baseexception_permanently_fails_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = KeyboardInterrupt("write interrupted")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        monkeypatch.setattr(
            generation_module.os,
            "write",
            lambda *_args: (_ for _ in ()).throw(control),
        )

        with pytest.raises(KeyboardInterrupt) as exc_info:
            generation.write(b"payload")

        assert exc_info.value is control
        with pytest.raises(OSError, match="not writable"):
            generation.fileno()
        with pytest.raises(OSError, match="cannot be finalized"):
            generation.finalize(
                expected_size=0,
                expected_sha256=hashlib.sha256(b"").hexdigest(),
            )
        generation.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows source-handle sharing contract")
def test_windows_owned_source_name_cannot_be_replaced_before_publish(
    tmp_path: Path,
) -> None:
    payload = b"owned payload"
    digest = _digest(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        stage_name = generation.stage_name_for_testing
        assert stage_name is not None
        with pytest.raises(OSError):
            os.replace(tmp_path / stage_name, tmp_path / "successor.bin")
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        with generation.publish_content_addressed("installer.exe"):
            pass


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-handle sharing contract")
@pytest.mark.parametrize("swap_level", ("root", "ancestor"))
def test_windows_capability_blocks_root_or_ancestor_swap_during_publish(
    tmp_path: Path,
    swap_level: str,
) -> None:
    ancestor = tmp_path / "ancestor"
    approved = ancestor / "approved"
    outside = tmp_path / "outside"
    approved.mkdir(parents=True)
    outside.mkdir()
    payload = b"pinned directory publication"
    digest = _digest(payload)

    with filesystem_directory_capability(approved) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        attacked = approved if swap_level == "root" else ancestor
        with pytest.raises(OSError):
            attacked.replace(attacked.with_name(f"{attacked.name}-swapped"))
        with generation.publish_content_addressed("installer.exe") as lease:
            assert approved / lease.name == approved / f"{digest}-installer.exe"
            os.lseek(lease.fileno(), 0, os.SEEK_SET)
            assert os.read(lease.fileno(), len(payload) + 1) == payload

    assert not list(outside.iterdir())


def test_ambiguous_publish_with_exact_target_returns_uncertain_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"committed despite native error"
    digest = _digest(payload)
    target_name = f"{digest}-installer.exe"

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        stage_name = generation.stage_name_for_testing

        def commit_then_fail(_source, name: str):
            _source._begin_publish()
            assert name == target_name
            (tmp_path / name).write_bytes(payload)
            raise OSError(errno.EIO, "ambiguous native publish")

        monkeypatch.setattr(
            capability,
            "publish_owned_generation_no_replace",
            commit_then_fail,
        )

        with generation.publish_content_addressed("installer.exe") as lease:
            assert lease.receipt.status is PublishStatus.COMMITTED_AUTHORITY_UNCERTAIN
            assert (tmp_path / lease.name).read_bytes() == payload
        if os.name == "nt":
            assert stage_name is not None
            assert (tmp_path / stage_name).read_bytes() == payload


def test_ambiguous_receipt_control_flow_closes_verified_target_descriptor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"committed despite native error"
    digest = _digest(payload)
    control = SystemExit("uncertain receipt interrupted")
    opened: list[int] = []

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_open = capability.open_owned_generation_lease

        def commit_then_fail(source, name: str) -> None:
            source._begin_publish()
            (tmp_path / name).write_bytes(payload)
            raise OSError(errno.EIO, "ambiguous native publish")

        def capture_open(name: str) -> int:
            descriptor = real_open(name)
            opened.append(descriptor)
            return descriptor

        monkeypatch.setattr(
            capability,
            "publish_owned_generation_no_replace",
            commit_then_fail,
        )
        monkeypatch.setattr(capability, "open_owned_generation_lease", capture_open)
        monkeypatch.setattr(
            capability,
            "uncertain_committed_receipt",
            lambda *_args: (_ for _ in ()).throw(control),
        )

        with pytest.raises(SystemExit) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value is control
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


@pytest.mark.skipif(os.name != "nt", reason="Windows same-HANDLE commit proof")
def test_windows_ambiguous_native_success_is_confirmed_on_same_source_handle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"native commit with ambiguous return"
    digest = _digest(payload)
    target_name = f"{digest}-installer.exe"

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        stage_name = generation.stage_name_for_testing

        def commit_then_report_error(source, name: str) -> None:
            source._begin_publish()
            capability_module._publish_windows_descriptor_no_replace(
                source.fileno(),
                tmp_path / name,
            )
            raise OSError(errno.EIO, "ambiguous return after native commit")

        monkeypatch.setattr(
            capability,
            "publish_owned_generation_no_replace",
            commit_then_report_error,
        )

        with generation.publish_content_addressed("installer.exe") as lease:
            assert lease.name == target_name
            assert lease.receipt.status is PublishStatus.COMMITTED_AUTHORITY_UNCERTAIN
            os.lseek(lease.fileno(), 0, os.SEEK_SET)
            assert os.read(lease.fileno(), len(payload) + 1) == payload
        assert (tmp_path / lease.name).read_bytes() == payload

    assert stage_name is not None
    assert not (tmp_path / stage_name).exists()


def test_post_commit_descriptor_rewind_failure_is_non_retryable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"published before descriptor rewind fails"
    digest = _digest(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_lseek = generation_module.os.lseek
        real_open = capability.open_owned_generation_lease
        opened: list[int] = []
        target_lseek_calls = 0

        def capture_open(name: str) -> int:
            descriptor = real_open(name)
            opened.append(descriptor)
            return descriptor

        def fail_second_lseek(descriptor: int, offset: int, whence: int) -> int:
            nonlocal target_lseek_calls
            if descriptor in opened:
                target_lseek_calls += 1
                if target_lseek_calls == 2:
                    raise OSError(errno.EIO, "post-commit rewind failed")
            return real_lseek(descriptor, offset, whence)

        monkeypatch.setattr(capability, "open_owned_generation_lease", capture_open)
        monkeypatch.setattr(generation_module.os, "lseek", fail_second_lseek)
        with pytest.raises(GenerationPublishUncertainError) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value.receipt.status is PublishStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
    target = tmp_path / f"{digest}-installer.exe"
    assert target.read_bytes() == payload


def test_post_commit_lease_construction_control_flow_closes_read_only_descriptor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"published before lease construction is interrupted"
    digest = _digest(payload)
    control = KeyboardInterrupt("lease construction interrupted")
    opened: list[int] = []

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        real_open = capability.open_owned_generation_lease

        def capture_open(name: str) -> int:
            descriptor = real_open(name)
            opened.append(descriptor)
            return descriptor

        monkeypatch.setattr(capability, "open_owned_generation_lease", capture_open)
        monkeypatch.setattr(
            generation_module,
            "PublishedLease",
            lambda **_kwargs: (_ for _ in ()).throw(control),
        )

        with pytest.raises(KeyboardInterrupt) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value is control
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_post_commit_reopen_rejects_same_bytes_from_a_different_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"same bytes but different file object"
    digest = _digest(payload)
    attacker = tmp_path / "attacker.bin"
    attacker.write_bytes(payload)
    opened: list[int] = []

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        source_descriptor = generation.fileno()
        source_stat = os.fstat(source_descriptor)
        attacker_stat = attacker.stat()
        assert (source_stat.st_dev, source_stat.st_ino) != (
            attacker_stat.st_dev,
            attacker_stat.st_ino,
        )
        generation.finalize(expected_size=len(payload), expected_sha256=digest)

        def open_attacker_instead(_target_name: str) -> int:
            descriptor = os.open(attacker, os.O_RDONLY)
            opened.append(descriptor)
            return descriptor

        monkeypatch.setattr(
            capability,
            "open_owned_generation_lease",
            open_attacker_instead,
        )

        with pytest.raises(GenerationPublishUncertainError) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value.receipt.status is PublishStatus.COMMITTED_AUTHORITY_UNCERTAIN
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
    with pytest.raises(OSError):
        os.fstat(source_descriptor)


def test_ambiguous_publish_without_exact_target_is_non_retryable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"outcome unknown"
    digest = _digest(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        def fail_during_native_publish(source, _name: str) -> None:
            source._begin_publish()
            raise OSError(errno.EIO, "ambiguous native publish")

        monkeypatch.setattr(
            capability,
            "publish_owned_generation_no_replace",
            fail_during_native_publish,
        )
        monkeypatch.setattr(
            capability,
            "unlink_child",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("ambiguous cleanup used a pathname")
            ),
        )

        with pytest.raises(GenerationPublishUncertainError) as exc_info:
            generation.publish_content_addressed("installer.exe")

        assert exc_info.value.receipt.status is PublishStatus.OUTCOME_UNKNOWN


def test_pre_publish_authority_failure_is_not_mislabeled_as_ambiguous(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"precondition failure"
    digest = _digest(payload)
    primary = OSError("root authority changed before publication")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        stage_name = generation.stage_name_for_testing
        monkeypatch.setattr(
            capability,
            "publish_owned_generation_no_replace",
            lambda *_args: (_ for _ in ()).throw(primary),
        )

        with pytest.raises(OSError) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value is primary
    if os.name == "nt":
        assert stage_name is not None
        assert not (tmp_path / stage_name).exists()


def test_ambiguous_publish_never_stringifies_hostile_native_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class HostileNativeError(OSError):
        def __str__(self) -> str:
            raise SystemExit("native error must not be stringified")

    payload = b"outcome unknown"
    digest = _digest(payload)
    native_error = HostileNativeError(errno.EIO)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        def fail_during_native_publish(source, _name: str) -> None:
            source._begin_publish()
            raise native_error

        monkeypatch.setattr(
            capability,
            "publish_owned_generation_no_replace",
            fail_during_native_publish,
        )

        with pytest.raises(GenerationPublishUncertainError) as exc_info:
            generation.publish_content_addressed("installer.exe")

    assert exc_info.value.__cause__ is native_error
    assert any(
        value.startswith("native-publish:")
        and value.endswith("HostileNativeError")
        for value in exc_info.value.receipt.diagnostics
    )


def test_generation_context_preserves_body_error_over_cleanup_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = RuntimeError("body failed")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        real_close = generation._native.close

        def close_then_fail() -> None:
            real_close()
            raise OSError("cleanup failed")

        monkeypatch.setattr(generation._native, "close", close_then_fail)
        with pytest.raises(RuntimeError) as exc_info:
            with generation:
                raise primary

    assert exc_info.value is primary


def test_generation_context_prefers_cleanup_control_flow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = KeyboardInterrupt("cleanup interrupted")

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        real_close = generation._native.close

        def close_then_interrupt() -> None:
            real_close()
            raise control

        monkeypatch.setattr(generation._native, "close", close_then_interrupt)
        with pytest.raises(KeyboardInterrupt) as exc_info:
            with generation:
                raise RuntimeError("body failed")

    assert exc_info.value is control


@pytest.mark.parametrize(
    "label",
    (
        "../installer.exe",
        "subdir/installer.exe",
        "CON",
        "bad\ud800.exe",
        "installer-\u202eexe.bin",
    ),
)
def test_content_address_label_rejects_path_and_reserved_names(
    tmp_path: Path,
    label: str,
) -> None:
    payload = b"expected payload"
    digest = _digest(payload)

    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_generation(capability)
        generation.write(payload)
        generation.finalize(expected_size=len(payload), expected_sha256=digest)
        with pytest.raises(OSError, match="label is invalid"):
            generation.publish_content_addressed(label)
        generation.close()
