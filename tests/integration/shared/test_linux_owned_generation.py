from __future__ import annotations

import errno
import hashlib
import os
import sys
from pathlib import Path

import pytest

import shared.filesystem_directory_capability as capability_module
from app.services.updater_owned_generation import OwnedGeneration
from shared.filesystem_directory_capability import filesystem_directory_capability


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux O_TMPFILE/linkat integration contract",
)


def _create_linux_generation(capability) -> OwnedGeneration:
    try:
        return OwnedGeneration.create(capability)
    except OSError as exc:
        if exc.errno == errno.ENOTSUP:
            pytest.fail(
                "Linux exact-generation gate returned ENOTSUP; "
                "Ubuntu CI must exercise O_TMPFILE publication"
            )
        raise


def _publish_and_assert_exact_chain(
    tmp_path: Path,
    payload: bytes,
) -> tuple[int, int]:
    digest = hashlib.sha256(payload).hexdigest()
    with filesystem_directory_capability(tmp_path) as capability:
        generation = _create_linux_generation(capability)
        generation.write(payload)
        source_stat = os.fstat(generation.fileno())
        generation.finalize(
            expected_size=len(payload),
            expected_sha256=digest,
        )
        with generation.publish_content_addressed("installer.bin") as lease:
            target_stat = os.stat(tmp_path / lease.name, follow_symlinks=False)
            lease_stat = os.fstat(lease.fileno())
            expected_identity = (source_stat.st_dev, source_stat.st_ino)
            assert (target_stat.st_dev, target_stat.st_ino) == expected_identity
            assert (lease_stat.st_dev, lease_stat.st_ino) == expected_identity
            assert os.read(lease.fileno(), len(payload) + 1) == payload
            with pytest.raises(OSError):
                os.write(lease.fileno(), b"read-only lease")
            assert not hasattr(lease, "path")
    return expected_identity


def test_linux_actual_otmpfile_publish_reopens_same_inode_read_only(
    tmp_path: Path,
) -> None:
    _publish_and_assert_exact_chain(tmp_path, b"linux exact generation")


def test_linux_actual_publish_falls_back_from_empty_path_to_procfd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_linkat = capability_module._call_linkat
    calls: list[tuple[int, bytes, int, bytes, int]] = []

    def deny_empty_path_once(
        source_directory: int,
        source_name: bytes,
        target_directory: int,
        target_name: bytes,
        flags: int,
    ) -> None:
        calls.append(
            (
                source_directory,
                source_name,
                target_directory,
                target_name,
                flags,
            )
        )
        if len(calls) == 1:
            assert flags == capability_module._AT_EMPTY_PATH
            raise OSError(errno.EPERM, "AT_EMPTY_PATH denied")
        real_linkat(
            source_directory,
            source_name,
            target_directory,
            target_name,
            flags,
        )

    monkeypatch.setattr(capability_module, "_call_linkat", deny_empty_path_once)

    _publish_and_assert_exact_chain(tmp_path, b"linux procfd fallback generation")

    assert len(calls) == 2
    assert calls[0][1] == b""
    assert calls[0][4] == capability_module._AT_EMPTY_PATH
    assert calls[1][0] == capability_module._AT_FDCWD
    assert calls[1][1].startswith(b"/proc/self/fd/")
    assert calls[1][4] == capability_module._AT_SYMLINK_FOLLOW
