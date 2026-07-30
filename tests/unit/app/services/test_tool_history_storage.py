from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

import pytest

import app.services.tool_history_storage as storage


def _swappable_root(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Callable[[], bool]]:
    approved = tmp_path / "approved"
    approved.mkdir()
    original = tmp_path / "approved-before-swap"
    outside = tmp_path / "outside"
    outside.mkdir()
    probe = tmp_path / "directory-link-probe"
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    swapped = False

    def swap() -> bool:
        nonlocal swapped
        if swapped:
            return True
        try:
            approved.rename(original)
            approved.symlink_to(outside, target_is_directory=True)
        except OSError:
            return False
        swapped = True
        return True

    return approved, original, outside, swap


def _path_name(value: object) -> str:
    try:
        return Path(os.fspath(value)).name  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def test_history_read_never_returns_outside_data_after_root_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved, _original, outside, swap = _swappable_root(tmp_path)
    target = approved / "history.json"
    target.write_text(json.dumps([{"run_id": "approved"}]), encoding="utf-8")
    (outside / target.name).write_text(
        json.dumps([{"run_id": "outside-private"}]),
        encoding="utf-8",
    )
    outside_identity = (
        int((outside / target.name).stat().st_dev),
        int((outside / target.name).stat().st_ino),
    )
    real_open_child = storage.FilesystemDirectoryCapability.open_child
    attempted = False
    opened_through_outside = False

    def swap_before_open(
        capability: storage.FilesystemDirectoryCapability,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal attempted, opened_through_outside
        if not attempted and name == target.name:
            attempted = True
            swap()
        descriptor = real_open_child(capability, name, flags, mode)
        opened = os.fstat(descriptor)
        opened_through_outside = opened_through_outside or (
            int(opened.st_dev), int(opened.st_ino)
        ) == outside_identity
        return descriptor

    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        swap_before_open,
    )

    try:
        result = storage.read_history_json(target, cache_root=approved)
    except OSError:
        result = None

    assert attempted is True
    assert opened_through_outside is False
    assert result != [{"run_id": "outside-private"}]
    assert json.loads((outside / target.name).read_text(encoding="utf-8")) == [
        {"run_id": "outside-private"}
    ]


def test_history_read_never_opens_outside_data_after_ancestor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "ancestor"
    approved = ancestor / "approved"
    approved.mkdir(parents=True)
    target = approved / "history.json"
    target.write_text(json.dumps([{"run_id": "approved"}]), encoding="utf-8")
    original_ancestor = tmp_path / "ancestor-before-swap"
    outside_ancestor = tmp_path / "outside-ancestor"
    outside_approved = outside_ancestor / approved.name
    outside_approved.mkdir(parents=True)
    outside_target = outside_approved / target.name
    outside_target.write_text(
        json.dumps([{"run_id": "outside-private"}]),
        encoding="utf-8",
    )
    probe = tmp_path / "directory-link-probe"
    try:
        probe.symlink_to(outside_ancestor, target_is_directory=True)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")
    real_open_child = storage.FilesystemDirectoryCapability.open_child
    outside_identity = (
        int(outside_target.stat().st_dev),
        int(outside_target.stat().st_ino),
    )
    opened_outside = False
    attempted = False

    def swap_ancestor_before_open(
        capability: storage.FilesystemDirectoryCapability,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal attempted, opened_outside
        if not attempted and name == target.name:
            attempted = True
            try:
                ancestor.rename(original_ancestor)
                ancestor.symlink_to(outside_ancestor, target_is_directory=True)
            except OSError:
                pass
        descriptor = real_open_child(capability, name, flags, mode)
        opened = os.fstat(descriptor)
        opened_outside = opened_outside or (
            int(opened.st_dev), int(opened.st_ino)
        ) == outside_identity
        return descriptor

    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        swap_ancestor_before_open,
    )

    try:
        storage.read_history_json(target, cache_root=approved)
    except OSError:
        pass

    assert attempted is True
    assert opened_outside is False
    assert outside_target.read_text(encoding="utf-8") == json.dumps(
        [{"run_id": "outside-private"}]
    )


def test_history_read_never_follows_target_replaced_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    target = approved / "history.json"
    target.write_text(json.dumps([{"run_id": "approved"}]), encoding="utf-8")
    original_target = approved / "history-before-swap.json"
    outside_target = tmp_path / "outside-private.json"
    outside_target.write_text(
        json.dumps([{"run_id": "outside-private"}]),
        encoding="utf-8",
    )
    probe = approved / "file-link-probe"
    try:
        probe.symlink_to(outside_target)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"file symlink creation unavailable: {exc}")
    real_open_child = storage.FilesystemDirectoryCapability.open_child
    outside_identity = (
        int(outside_target.stat().st_dev),
        int(outside_target.stat().st_ino),
    )
    opened_outside = False
    attempted = False

    def swap_target_before_open(
        capability: storage.FilesystemDirectoryCapability,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal attempted, opened_outside
        if not attempted and name == target.name:
            attempted = True
            target.rename(original_target)
            target.symlink_to(outside_target)
        descriptor = real_open_child(capability, name, flags, mode)
        opened = os.fstat(descriptor)
        opened_outside = opened_outside or (
            int(opened.st_dev), int(opened.st_ino)
        ) == outside_identity
        return descriptor

    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        swap_target_before_open,
    )

    try:
        storage.read_history_json(target, cache_root=approved)
    except OSError:
        pass

    assert attempted is True
    assert opened_outside is False
    assert outside_target.read_text(encoding="utf-8") == json.dumps(
        [{"run_id": "outside-private"}]
    )


def test_history_write_never_creates_temp_through_replaced_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved, _original, outside, swap = _swappable_root(tmp_path)
    target = approved / "history.json"
    real_open_child = storage.FilesystemDirectoryCapability.open_child
    attempted = False
    opened_through_outside = False

    def swap_before_temp_create(
        capability: storage.FilesystemDirectoryCapability,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal attempted, opened_through_outside
        should_swap = (
            not attempted
            and flags & os.O_CREAT
            and name.startswith(f".{target.name}.")
            and name.endswith(".tmp")
        )
        if should_swap:
            attempted = True
            swap()
        descriptor = real_open_child(capability, name, flags, mode)
        if should_swap:
            outside_temp = outside / name
            if outside_temp.exists():
                opened = os.fstat(descriptor)
                outside_value = outside_temp.stat()
                opened_through_outside = (
                    int(opened.st_dev), int(opened.st_ino)
                ) == (int(outside_value.st_dev), int(outside_value.st_ino))
        return descriptor

    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        swap_before_temp_create,
    )

    try:
        storage.atomic_write_json(
            target,
            [{"run_id": "approved"}],
            cache_root=approved,
        )
    except OSError:
        pass

    assert attempted is True
    assert opened_through_outside is False
    assert not (outside / target.name).exists()


def test_history_write_never_creates_temp_through_replaced_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "ancestor"
    approved = ancestor / "approved"
    approved.mkdir(parents=True)
    target = approved / "history.json"
    original_ancestor = tmp_path / "ancestor-before-swap"
    outside_ancestor = tmp_path / "outside-ancestor"
    outside_approved = outside_ancestor / approved.name
    outside_approved.mkdir(parents=True)
    probe = tmp_path / "directory-link-probe"
    try:
        probe.symlink_to(outside_ancestor, target_is_directory=True)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")
    real_open_child = storage.FilesystemDirectoryCapability.open_child
    attempted = False
    opened_through_outside = False

    def swap_ancestor_before_temp_create(
        capability: storage.FilesystemDirectoryCapability,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal attempted, opened_through_outside
        should_swap = (
            not attempted
            and flags & os.O_CREAT
            and name.startswith(f".{target.name}.")
            and name.endswith(".tmp")
        )
        if should_swap:
            attempted = True
            try:
                ancestor.rename(original_ancestor)
                ancestor.symlink_to(outside_ancestor, target_is_directory=True)
            except OSError:
                pass
        descriptor = real_open_child(capability, name, flags, mode)
        if should_swap:
            outside_temp = outside_approved / name
            if outside_temp.exists():
                opened = os.fstat(descriptor)
                outside_value = outside_temp.stat()
                opened_through_outside = (
                    int(opened.st_dev), int(opened.st_ino)
                ) == (int(outside_value.st_dev), int(outside_value.st_ino))
        return descriptor

    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        swap_ancestor_before_temp_create,
    )

    try:
        storage.atomic_write_json(
            target,
            [{"run_id": "approved"}],
            cache_root=approved,
        )
    except OSError:
        pass

    assert attempted is True
    assert opened_through_outside is False
    assert not (outside_approved / target.name).exists()


def test_history_cleanup_does_not_unlink_replaced_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    target = approved / "history.json"
    real_open = storage.os.open
    real_replace = storage.os.replace
    replacement_path: Path | None = None
    attacker_bytes = b"attacker replacement"

    def replace_temp_then_fail(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal replacement_path
        source_name = _path_name(source)
        if (
            replacement_path is None
            and source_name.startswith(f".{target.name}.")
            and _path_name(destination) == target.name
        ):
            source_dir_fd = kwargs.get("src_dir_fd")
            quarantine_name = f"quarantined-{source_name}"
            if source_dir_fd is not None:
                real_replace(
                    source,
                    quarantine_name,
                    src_dir_fd=source_dir_fd,
                    dst_dir_fd=source_dir_fd,
                )
                descriptor = real_open(
                    source,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=source_dir_fd,
                )
                replacement_path = approved / source_name
            else:
                source_path = Path(os.fspath(source))  # type: ignore[arg-type]
                real_replace(source_path, source_path.with_name(quarantine_name))
                descriptor = real_open(
                    source_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                replacement_path = source_path
            try:
                os.write(descriptor, attacker_bytes)
            finally:
                os.close(descriptor)
            raise OSError("injected replace failure")
        real_replace(source, destination, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(storage.os, "replace", replace_temp_then_fail)

    with pytest.raises(OSError, match="injected replace failure"):
        storage.atomic_write_json(
            target,
            [{"run_id": "approved"}],
            cache_root=approved,
        )

    assert replacement_path is not None
    assert replacement_path.exists(), "cleanup deleted an unowned replacement"
    assert replacement_path.read_bytes() == attacker_bytes
    assert not target.exists()


def test_history_write_preserves_body_error_over_close_control_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    target = approved / "history.json"
    primary = RuntimeError("history write failed")
    cleanup = KeyboardInterrupt("descriptor close interrupted")
    temp_descriptor: int | None = None
    cleanup_raised = False
    real_open_child = storage.FilesystemDirectoryCapability.open_child
    real_close = storage.os.close

    def capture_temp_descriptor(
        capability: storage.FilesystemDirectoryCapability,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal temp_descriptor
        descriptor = real_open_child(capability, name, flags, mode)
        if flags & os.O_CREAT:
            temp_descriptor = descriptor
        return descriptor

    def fail_write(_descriptor: int, _payload: bytes) -> None:
        raise primary

    def close_then_interrupt(descriptor: int) -> None:
        nonlocal cleanup_raised
        real_close(descriptor)
        if descriptor == temp_descriptor and not cleanup_raised:
            cleanup_raised = True
            raise cleanup

    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        capture_temp_descriptor,
    )
    monkeypatch.setattr(storage, "_write_all", fail_write)
    monkeypatch.setattr(storage.os, "close", close_then_interrupt)

    with pytest.raises(RuntimeError) as exc_info:
        storage.atomic_write_json(
            target,
            [{"run_id": "approved"}],
            cache_root=approved,
        )

    assert exc_info.value is primary
    assert cleanup_raised is True


def test_history_read_opens_special_files_nonblocking_before_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    target = approved / "history.json"
    target.write_bytes(b"[]")
    nonblocking = 1 << 29
    observed_flags: list[int] = []

    def reject_open(
        _capability: storage.FilesystemDirectoryCapability,
        _name: str,
        flags: int,
        _mode: int = 0o600,
    ) -> int:
        observed_flags.append(flags)
        raise OSError("stop after inspecting open flags")

    monkeypatch.setattr(storage.os, "O_NONBLOCK", nonblocking, raising=False)
    monkeypatch.setattr(
        storage.FilesystemDirectoryCapability,
        "open_child",
        reject_open,
    )

    with pytest.raises(OSError, match="stop after inspecting open flags"):
        storage.read_history_json(target, cache_root=approved)

    assert observed_flags == [os.O_RDONLY | nonblocking]
