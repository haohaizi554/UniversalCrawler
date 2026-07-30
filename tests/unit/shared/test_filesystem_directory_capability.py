from __future__ import annotations

import os

import pytest

import shared.filesystem_directory_capability as capability_module


def test_capability_closes_after_exit_identity_failure(tmp_path, monkeypatch):
    close_calls = 0

    class FailingCapability:
        def assert_bound(self) -> None:
            raise OSError("directory identity changed")

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    monkeypatch.setattr(
        capability_module,
        "_require_regular_directory_ancestry",
        lambda _path: None,
    )
    monkeypatch.setattr(
        capability_module,
        "_open_directory_capability",
        lambda _path: FailingCapability(),
    )

    with pytest.raises(OSError, match="identity changed"):
        with capability_module.filesystem_directory_capability(tmp_path):
            pass

    assert close_calls == 1


def test_windows_capability_close_prefers_control_flow_after_ordinary_failure(
    tmp_path,
    monkeypatch,
):
    ordinary = OSError("first handle close failed")
    control = KeyboardInterrupt("second handle close interrupted")
    closed: list[int] = []
    capability = capability_module.FilesystemDirectoryCapability(
        tmp_path,
        windows_handles=((101, 1), (202, 2)),
        identity=(0, 2),
    )

    def close_handle(handle: int) -> None:
        closed.append(handle)
        if handle == 202:
            raise ordinary
        raise control

    monkeypatch.setattr(capability_module, "_close_windows_handle", close_handle)

    with pytest.raises(KeyboardInterrupt) as exc_info:
        capability.close()

    assert exc_info.value is control
    assert closed == [202, 101]


def test_finish_capability_prefers_close_control_flow_over_identity_error():
    identity_error = OSError("directory identity changed")
    close_control = SystemExit("handle close interrupted")
    calls: list[str] = []

    class FailingCapability:
        def assert_bound(self) -> None:
            calls.append("assert")
            raise identity_error

        def close(self) -> None:
            calls.append("close")
            raise close_control

    with pytest.raises(SystemExit) as exc_info:
        capability_module._finish_capability(FailingCapability(), None)

    assert exc_info.value is close_control
    assert calls == ["assert", "close"]


def test_context_preserves_body_error_over_identity_and_close_control_flow(
    tmp_path,
    monkeypatch,
):
    primary = RuntimeError("body failed")
    calls: list[str] = []

    class FailingCapability:
        def assert_bound(self) -> None:
            calls.append("assert")
            raise KeyboardInterrupt("identity check interrupted")

        def close(self) -> None:
            calls.append("close")
            raise SystemExit("handle close interrupted")

    monkeypatch.setattr(
        capability_module,
        "_require_regular_directory_ancestry",
        lambda _path: None,
    )
    monkeypatch.setattr(
        capability_module,
        "_open_directory_capability",
        lambda _path: FailingCapability(),
    )

    with pytest.raises(RuntimeError) as exc_info:
        with capability_module.filesystem_directory_capability(tmp_path):
            raise primary

    assert exc_info.value is primary
    assert calls == ["assert", "close"]


@pytest.mark.parametrize(
    "name",
    (
        "manifest.json:stream",
        "manifest.json.",
        "manifest.json ",
        "CON",
        "con.json",
        "AUX.txt",
        "COM1.log",
        "LPT9",
        "CONIN$",
        "conin$.log",
        "CONOUT$",
        "conout$.json",
        "CLOCK$",
        "clock$.log",
        "COM¹",
        "com¹.log",
        "COM²",
        "com².log",
        "COM³",
        "com³.log",
        "LPT¹",
        "lpt¹.log",
        "LPT²",
        "lpt².log",
        "LPT³",
        "lpt³.log",
        "bad\x1fname",
    ),
)
def test_capability_rejects_windows_alias_child_names(tmp_path, name):
    with capability_module.filesystem_directory_capability(tmp_path) as capability:
        with pytest.raises(OSError, match="child name is invalid"):
            capability.stat_child(name)


def test_capability_rejects_hostile_non_string_name_without_coercion(tmp_path):
    class HostileName:
        def __bool__(self) -> bool:
            raise SystemExit("child-name truthiness must not run")

        def __str__(self) -> str:
            raise SystemExit("child-name stringification must not run")

    with capability_module.filesystem_directory_capability(tmp_path) as capability:
        with pytest.raises(OSError, match="child name is invalid"):
            capability.stat_child(HostileName())  # type: ignore[arg-type]


def test_capability_rejects_lone_surrogate_child_name(tmp_path):
    with capability_module.filesystem_directory_capability(tmp_path) as capability:
        with pytest.raises(OSError, match="child name is invalid"):
            capability.stat_child("bad\ud800name")


def test_open_preserves_identity_error_over_descriptor_close_failure(
    tmp_path,
    monkeypatch,
):
    class HostileCleanup(BaseException):
        pass

    primary = OSError("directory identity changed")
    cleanup = HostileCleanup("descriptor close failed")
    capability = capability_module.FilesystemDirectoryCapability(
        tmp_path,
        descriptor=91,
        identity=(0, 0),
    )
    checks = iter((None, primary))
    real_close = os.close

    def assert_bound() -> None:
        outcome = next(checks)
        if outcome is not None:
            raise outcome

    def close(descriptor: int) -> None:
        if descriptor == 73:
            raise cleanup
        real_close(descriptor)

    monkeypatch.setattr(capability, "assert_bound", assert_bound)
    monkeypatch.setattr(capability_module.os, "open", lambda *_a, **_k: 73)
    monkeypatch.setattr(capability_module.os, "close", close)

    with pytest.raises(OSError) as exc_info:
        capability.open_child("payload.bin", os.O_RDONLY)

    assert exc_info.value is primary
    if hasattr(BaseException, "add_note"):
        assert getattr(primary, "__notes__", []) == [
            "approved directory child descriptor cleanup failed"
        ]


def test_capability_rejects_ancestor_replacement_after_acquisition(tmp_path):
    ancestor = tmp_path / "ancestor"
    approved = ancestor / "approved"
    approved.mkdir(parents=True)
    (approved / "payload.bin").write_bytes(b"approved")
    moved_ancestor = tmp_path / "ancestor-before-swap"
    outside_ancestor = tmp_path / "outside-ancestor"
    outside_approved = outside_ancestor / approved.name
    outside_approved.mkdir(parents=True)
    outside_payload = outside_approved / "payload.bin"
    outside_payload.write_bytes(b"outside")
    probe = tmp_path / "directory-link-probe"
    try:
        probe.symlink_to(outside_ancestor, target_is_directory=True)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    with pytest.raises(OSError):
        with capability_module.filesystem_directory_capability(approved) as capability:
            ancestor.rename(moved_ancestor)
            ancestor.symlink_to(outside_ancestor, target_is_directory=True)
            descriptor = capability.open_child("payload.bin", os.O_WRONLY)
            try:
                os.write(descriptor, b"mutated")
            finally:
                os.close(descriptor)

    assert outside_payload.read_bytes() == b"outside"


def test_derived_child_capability_cannot_outlive_parent_authority(tmp_path):
    ancestor = tmp_path / "ancestor"
    approved = ancestor / "approved"
    child_path = approved / "child"
    child_path.mkdir(parents=True)
    (child_path / "payload.bin").write_bytes(b"approved")
    outside_ancestor = tmp_path / "outside-ancestor"
    outside_child = outside_ancestor / approved.name / child_path.name
    outside_child.mkdir(parents=True)
    outside_payload = outside_child / "payload.bin"
    outside_payload.write_bytes(b"outside")
    moved_ancestor = tmp_path / "ancestor-before-swap"
    probe = tmp_path / "directory-link-probe"
    try:
        probe.symlink_to(outside_ancestor, target_is_directory=True)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    parent = capability_module._open_directory_capability(approved)
    child = parent.open_directory_child(child_path.name)
    parent.close()
    try:
        with pytest.raises(OSError):
            ancestor.rename(moved_ancestor)
            ancestor.symlink_to(outside_ancestor, target_is_directory=True)
            child.open_child("payload.bin", os.O_WRONLY)
    finally:
        child.close()

    assert outside_payload.read_bytes() == b"outside"


def _final_file_symlink(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    link = approved / "payload.bin"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation unavailable: {exc}")
    return approved, link, outside


def test_capability_stat_rejects_final_file_symlink(tmp_path):
    approved, link, outside = _final_file_symlink(tmp_path)

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(OSError, match="reparse|link"):
            capability.stat_child(link.name)

    assert outside.read_bytes() == b"outside"


def test_capability_open_rejects_final_file_symlink(tmp_path):
    approved, link, outside = _final_file_symlink(tmp_path)
    descriptor: int | None = None

    try:
        with capability_module.filesystem_directory_capability(approved) as capability:
            with pytest.raises(OSError):
                descriptor = capability.open_child(
                    link.name,
                    os.O_WRONLY | os.O_TRUNC,
                )
    finally:
        if descriptor is not None:
            os.close(descriptor)

    assert outside.read_bytes() == b"outside"


def test_capability_open_rejects_file_replaced_by_symlink_after_stat(
    tmp_path,
    monkeypatch,
):
    approved = tmp_path / "approved"
    approved.mkdir()
    payload = approved / "payload.bin"
    payload.write_bytes(b"approved")
    original = approved / "payload-before-swap.bin"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    replacement = approved / "replacement-link"
    try:
        replacement.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation unavailable: {exc}")
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            payload.replace(original)
            replacement.replace(payload)

    if os.name == "nt":
        real_create = capability_module._create_windows_child_handle

        def create_then_swap(*args, **kwargs):
            swap()
            return real_create(*args, **kwargs)

        monkeypatch.setattr(
            capability_module,
            "_create_windows_child_handle",
            create_then_swap,
        )
    else:
        real_open = capability_module.os.open

        def open_then_swap(*args, **kwargs):
            swap()
            return real_open(*args, **kwargs)

        monkeypatch.setattr(capability_module.os, "open", open_then_swap)

    descriptor: int | None = None
    try:
        with capability_module.filesystem_directory_capability(approved) as capability:
            with pytest.raises(OSError):
                descriptor = capability.open_child(
                    payload.name,
                    os.O_WRONLY | os.O_TRUNC,
                )
    finally:
        if descriptor is not None:
            os.close(descriptor)

    assert payload.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_capability_unlink_rejects_final_file_symlink(tmp_path):
    approved, link, outside = _final_file_symlink(tmp_path)

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(OSError, match="reparse|link"):
            capability.unlink_child(link.name)

    assert link.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_capability_replace_rejects_final_target_symlink(tmp_path):
    approved, link, outside = _final_file_symlink(tmp_path)
    source = approved / "source.bin"
    source.write_bytes(b"approved")

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(OSError, match="reparse|link"):
            capability.replace_child(source.name, capability, link.name)

    assert source.read_bytes() == b"approved"
    assert link.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_capability_replace_child_linearizes_at_the_os_source_name(
    tmp_path,
    monkeypatch,
):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "source.bin"
    original = approved / "source-original.bin"
    target = approved / "target.bin"
    source.write_bytes(b"verified")
    real_replace = capability_module.os.replace
    swapped = False

    def replace_source_then_publish(source_path, target_path, *args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            real_replace(source, original)
            source.write_bytes(b"later generation")
        return real_replace(source_path, target_path, *args, **kwargs)

    monkeypatch.setattr(capability_module.os, "replace", replace_source_then_publish)

    with capability_module.filesystem_directory_capability(approved) as capability:
        capability.replace_child(source.name, capability, target.name)

    assert original.read_bytes() == b"verified"
    assert not source.exists()
    assert target.read_bytes() == b"later generation"


def test_capability_stat_rejects_final_directory_reparse(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside-directory"
    outside.mkdir()
    link = approved / "directory-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(OSError, match="reparse|link"):
            capability.stat_child(link.name)


@pytest.mark.parametrize("preexisting", (False, True))
def test_capability_create_truncate_uses_verified_handle(tmp_path, preexisting):
    approved = tmp_path / "approved"
    approved.mkdir()
    target = approved / "payload.bin"
    if preexisting:
        target.write_bytes(b"old content")

    with capability_module.filesystem_directory_capability(approved) as capability:
        descriptor = capability.open_child(
            target.name,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        )
        try:
            os.write(descriptor, b"new")
        finally:
            os.close(descriptor)

    assert target.read_bytes() == b"new"


@pytest.mark.skipif(os.name != "nt", reason="Windows CreateFileW contract")
def test_windows_child_open_rejects_mocked_reparse_and_closes_handle(
    tmp_path,
    monkeypatch,
):
    closed: list[int] = []
    monkeypatch.setattr(
        capability_module,
        "_create_windows_child_handle",
        lambda *_args, **_kwargs: 501,
    )
    monkeypatch.setattr(
        capability_module,
        "_windows_handle_information",
        lambda _handle: capability_module._WindowsDirectoryInformation(
            file_index=7,
            attributes=0x400,
        ),
    )
    monkeypatch.setattr(
        capability_module,
        "_close_windows_handle",
        lambda handle: closed.append(handle),
    )

    with pytest.raises(OSError, match="reparse"):
        capability_module._open_windows_child_file(
            tmp_path / "payload.bin",
            os.O_RDONLY,
        )

    assert closed == [501]


def test_capability_rename_child_no_replace_moves_regular_file(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "source.bin"
    target = approved / "target.bin"
    source.write_bytes(b"approved")

    with capability_module.filesystem_directory_capability(approved) as capability:
        capability.rename_child_no_replace(source.name, capability, target.name)

    assert not source.exists()
    assert target.read_bytes() == b"approved"


def test_capability_rename_child_no_replace_refuses_existing_target(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "source.bin"
    target = approved / "target.bin"
    source.write_bytes(b"approved")
    target.write_bytes(b"existing")

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(FileExistsError):
            capability.rename_child_no_replace(source.name, capability, target.name)

    assert source.read_bytes() == b"approved"
    assert target.read_bytes() == b"existing"


def test_capability_rename_child_no_replace_rejects_reparse_target(tmp_path):
    approved, target, outside = _final_file_symlink(tmp_path)
    source = approved / "source.bin"
    source.write_bytes(b"approved")

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(OSError, match="reparse|link"):
            capability.rename_child_no_replace(source.name, capability, target.name)

    assert source.read_bytes() == b"approved"
    assert target.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_capability_rename_child_no_replace_wins_target_creation_race(
    tmp_path,
    monkeypatch,
):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "source.bin"
    target = approved / "target.bin"
    source.write_bytes(b"approved")

    if os.name == "nt":
        real_rename = capability_module.os.rename

        def create_target_then_rename(*args, **kwargs):
            target.write_bytes(b"racer")
            return real_rename(*args, **kwargs)

        monkeypatch.setattr(capability_module.os, "rename", create_target_then_rename)
    else:
        real_rename = capability_module._rename_posix_no_replace

        def create_target_then_rename(*args, **kwargs):
            target.write_bytes(b"racer")
            return real_rename(*args, **kwargs)

        monkeypatch.setattr(
            capability_module,
            "_rename_posix_no_replace",
            create_target_then_rename,
        )

    with capability_module.filesystem_directory_capability(approved) as capability:
        with pytest.raises(FileExistsError):
            capability.rename_child_no_replace(source.name, capability, target.name)

    assert source.read_bytes() == b"approved"
    assert target.read_bytes() == b"racer"


def test_capability_rename_child_no_replace_linearizes_at_the_os_source_name(
    tmp_path,
    monkeypatch,
):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "source.bin"
    original = approved / "source-original.bin"
    target = approved / "target.bin"
    source.write_bytes(b"verified")
    swapped = False

    if os.name == "nt":
        real_rename = capability_module.os.rename

        def replace_source_then_rename(source_path, target_path, *args, **kwargs):
            nonlocal swapped
            if not swapped:
                swapped = True
                real_rename(source, original)
                source.write_bytes(b"later generation")
            return real_rename(source_path, target_path, *args, **kwargs)

        monkeypatch.setattr(
            capability_module.os,
            "rename",
            replace_source_then_rename,
        )
    else:
        real_rename = capability_module._rename_posix_no_replace

        def replace_source_then_rename(*args, **kwargs):
            nonlocal swapped
            if not swapped:
                swapped = True
                source.rename(original)
                source.write_bytes(b"later generation")
            return real_rename(*args, **kwargs)

        monkeypatch.setattr(
            capability_module,
            "_rename_posix_no_replace",
            replace_source_then_rename,
        )

    with capability_module.filesystem_directory_capability(approved) as capability:
        capability.rename_child_no_replace(source.name, capability, target.name)

    assert original.read_bytes() == b"verified"
    assert not source.exists()
    assert target.read_bytes() == b"later generation"


def test_posix_chain_preserves_acquisition_error_over_close_failure(
    tmp_path,
    monkeypatch,
):
    class HostileCleanup(BaseException):
        pass

    primary = OSError("directory identity lookup failed")
    cleanup = HostileCleanup("descriptor cleanup failed")
    real_close = os.close
    monkeypatch.setattr(capability_module.os, "open", lambda *_a, **_k: 881)
    monkeypatch.setattr(
        capability_module.os,
        "fstat",
        lambda _descriptor: (_ for _ in ()).throw(primary),
    )

    def close(descriptor: int) -> None:
        if descriptor == 881:
            raise cleanup
        real_close(descriptor)

    monkeypatch.setattr(capability_module.os, "close", close)

    with pytest.raises(OSError) as exc_info:
        capability_module._open_posix_directory_chain(tmp_path)

    assert exc_info.value is primary


def test_windows_chain_preserves_acquisition_error_over_handle_close_failure(
    tmp_path,
    monkeypatch,
):
    class HostileCleanup(BaseException):
        pass

    primary = OSError("directory handle inspection failed")
    cleanup = HostileCleanup("handle cleanup failed")
    monkeypatch.setattr(
        capability_module,
        "_open_windows_directory_handle",
        lambda _path: 991,
    )
    monkeypatch.setattr(
        capability_module,
        "_windows_handle_information",
        lambda _handle: (_ for _ in ()).throw(primary),
    )
    monkeypatch.setattr(
        capability_module,
        "_close_windows_handle",
        lambda _handle: (_ for _ in ()).throw(cleanup),
    )

    with pytest.raises(OSError) as exc_info:
        capability_module._open_windows_directory_chain(tmp_path)

    assert exc_info.value is primary
