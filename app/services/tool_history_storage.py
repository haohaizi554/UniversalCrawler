"""Bounded no-follow storage for the tool history cache."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from shared.filesystem_directory_capability import (
    FilesystemDirectoryCapability,
    ensure_regular_directory,
    filesystem_directory_capability,
)


MAX_HISTORY_BYTES = 2 * 1024 * 1024


def bounded_history_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_bytes: int = MAX_HISTORY_BYTES,
) -> list[dict[str, Any]]:
    """Keep the newest deterministic suffix that fits the durable byte budget."""

    snapshot = [dict(row) for row in rows]
    if len(_encode_json(snapshot)) <= max_bytes:
        return snapshot
    low = 0
    high = len(snapshot)
    while low < high:
        start = (low + high) // 2
        if len(_encode_json(snapshot[start:])) <= max_bytes:
            high = start
        else:
            low = start + 1
    return snapshot[low:]


def persist_retry_delay(failures: int, delays: Sequence[float]) -> float:
    normalized = tuple(float(value) for value in delays)
    if not normalized:
        return 0.01
    index = min(max(1, int(failures)) - 1, len(normalized) - 1)
    return max(0.001, normalized[index])


def read_history_json(
    path: Path,
    *,
    cache_root: Path,
    max_bytes: int = MAX_HISTORY_BYTES,
) -> Any | None:
    """Read one bounded regular cache file without following links."""

    root, target = _approved_target(path, cache_root=cache_root, create_root=False)
    with filesystem_directory_capability(root) as capability:
        try:
            read_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
            descriptor = capability.open_child(target.name, read_flags)
        except FileNotFoundError:
            return None
        primary_error: BaseException | None = None
        try:
            opened = os.fstat(descriptor)
            _require_regular_stat(opened)
            if opened.st_size > max_bytes:
                raise ValueError("tool history exceeds the byte limit")
            payload = _read_bounded(descriptor, max_bytes=max_bytes)
            current = capability.stat_child(target.name)
            _require_regular_stat(current)
            if _file_identity(opened) != _file_identity(current):
                raise OSError("tool history file changed during read")
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            _close_descriptor(descriptor, primary_error)

    decoded = payload.decode("utf-8", errors="strict")
    value = json.loads(decoded, parse_constant=_reject_json_constant)
    if _contains_surrogate(value):
        raise ValueError("tool history contains malformed Unicode")
    return value


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    cache_root: Path,
    max_bytes: int = MAX_HISTORY_BYTES,
) -> None:
    """Atomically replace one direct child of a controlled cache root."""

    encoded = _encode_json(value)
    if len(encoded) > max_bytes:
        raise ValueError("tool history exceeds the byte limit")

    root, target = _approved_target(path, cache_root=cache_root, create_root=True)
    with filesystem_directory_capability(root) as capability:
        _require_regular_or_missing(capability, target.name)
        descriptor, temp_name = _create_temp_file(capability, target.name)
        primary_error: BaseException | None = None
        try:
            opened = os.fstat(descriptor)
            _require_regular_stat(opened)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)

            current_temp = capability.stat_child(temp_name)
            _require_regular_stat(current_temp)
            if _file_identity(opened) != _file_identity(current_temp):
                raise OSError("tool history temporary file changed during write")
            _require_regular_or_missing(capability, target.name)
            capability.replace_child(temp_name, capability, target.name)
            published = capability.stat_child(target.name)
            _require_regular_stat(published)
            if _file_identity(opened) != _file_identity(published):
                raise OSError("tool history publication changed generation")
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            # A failed path publication leaves ownership of ``temp_name``
            # uncertain.  Never unlink it by name: an attacker may already
            # have installed a later generation at that spelling.
            _close_descriptor(descriptor, primary_error)


def _approved_target(
    path: Path,
    *,
    cache_root: Path,
    create_root: bool,
) -> tuple[Path, Path]:
    root = _absolute_lexical(cache_root)
    target = _absolute_lexical(path)
    if os.path.normcase(os.fspath(target.parent)) != os.path.normcase(
        os.fspath(root)
    ):
        raise OSError("tool history path escapes the controlled cache root")
    ensure_regular_directory(root, create=create_root)
    return root, target


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _require_regular_or_missing(
    capability: FilesystemDirectoryCapability,
    name: str,
) -> None:
    try:
        value = capability.stat_child(name)
    except FileNotFoundError:
        return
    _require_regular_stat(value)


def _require_regular_stat(value: os.stat_result) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or _is_link_or_reparse(value)
        or value.st_nlink != 1
    ):
        raise OSError("tool history path is not a regular no-link file")


def _create_temp_file(
    capability: FilesystemDirectoryCapability,
    target_name: str,
) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for _attempt in range(8):
        temp_name = f".{target_name}.{secrets.token_hex(16)}.tmp"
        try:
            descriptor = capability.open_child(temp_name, flags, 0o600)
        except FileExistsError:
            continue
        return descriptor, temp_name
    raise OSError("tool history temporary file name collisions exceeded limit")


def _read_bounded(descriptor: int, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > max_bytes:
        raise ValueError("tool history exceeds the byte limit")
    return payload


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("tool history write made no progress")
        view = view[written:]


def _close_descriptor(
    descriptor: int,
    primary_error: BaseException | None,
) -> None:
    try:
        os.close(descriptor)
    except BaseException:
        if primary_error is None:
            raise
        _attach_note_best_effort(
            primary_error,
            "tool history descriptor cleanup failed",
        )


def _attach_note_best_effort(error: BaseException, note: str) -> None:
    try:
        add_note = getattr(error, "add_note", None)
    except BaseException:
        return
    if not callable(add_note):
        return
    try:
        add_note(note)
    except BaseException:
        return


def _file_identity(value: os.stat_result) -> tuple[int, int]:
    return int(value.st_dev), int(value.st_ino)


def _is_link_or_reparse(value: os.stat_result) -> bool:
    attributes = int(getattr(value, "st_file_attributes", 0) or 0)
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


def _encode_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
    ).encode("utf-8", errors="strict")


def _contains_surrogate(value: Any) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, Mapping):
        return any(
            _contains_surrogate(key) or _contains_surrogate(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_surrogate(item) for item in value)
    return False


__all__ = [
    "MAX_HISTORY_BYTES",
    "atomic_write_json",
    "bounded_history_snapshot",
    "persist_retry_delay",
    "read_history_json",
]
