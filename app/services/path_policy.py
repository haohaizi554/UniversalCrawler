from __future__ import annotations

import os
import stat
import threading
from contextlib import ExitStack, contextmanager
from contextvars import Context
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from shared.filesystem_directory_capability import (
    FilesystemDirectoryCapability,
    filesystem_child_directory_capability,
    filesystem_directory_capability,
    is_link_or_reparse,
)

ApprovedRootGrant = tuple[str, tuple[int, int]]
_MAX_APPROVED_ROOT_GRANTS = 64


def _attach_cleanup_note(primary: BaseException, message: str) -> None:
    try:
        add_note = object.__getattribute__(primary, "add_note")
    except BaseException:
        return
    if not callable(add_note):
        return
    try:
        add_note(message)
    except BaseException:
        return


def _close_preserving_primary(
    close,
    primary: BaseException | None,
    *,
    note: str,
) -> None:
    try:
        close()
    except BaseException:
        if primary is None:
            raise
        _attach_cleanup_note(primary, note)


def _preferred_cleanup_error(
    current: BaseException | None,
    candidate: BaseException | None,
) -> BaseException | None:
    """Keep the first control-flow failure, otherwise the first ordinary one."""

    if candidate is None:
        return current
    if current is None or (
        isinstance(current, Exception) and not isinstance(candidate, Exception)
    ):
        return candidate
    return current


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def _lexical_path(path: str) -> str:
    return os.path.abspath(os.path.normpath(os.path.expanduser(path)))


def _stored_grant_path(path: str) -> str:
    return os.path.normcase(_lexical_path(path))

def is_within_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


@dataclass(frozen=True)
class ApprovedChildPath:
    """One child name bound to a live approved parent-directory identity."""

    parent: FilesystemDirectoryCapability
    name: str
    absolute_path: str

    def stat(self) -> os.stat_result:
        return self.parent.stat_child(self.name)

    def unlink(self) -> None:
        self.parent.unlink_child(self.name)

    def rmdir(self) -> None:
        self.parent.rmdir_child(self.name)

    def rename_no_replace(self, target: "ApprovedChildPath") -> None:
        self.parent.rename_child_no_replace(
            self.name,
            target.parent,
            target.name,
        )


class ApprovedRootsLease:
    """A set of approved root identities held for one complete operation."""

    def __init__(
        self,
        roots: tuple[tuple[str, FilesystemDirectoryCapability], ...],
    ) -> None:
        self._roots = roots

    def assert_bound(self) -> None:
        for _root, capability in self._roots:
            capability.assert_bound()

    @contextmanager
    def bind_child(
        self,
        path: str | os.PathLike[str],
    ) -> Iterator[ApprovedChildPath]:
        # Keep the caller's lexical descendant path intact.  Resolving it with
        # realpath here would erase an existing in-root symlink/junction before
        # the handle-relative walk can reject that reparse component.
        candidate = _lexical_path(os.fspath(path))
        candidate_key = os.path.normcase(candidate)
        matches = tuple(
            entry for entry in self._roots if is_within_root(candidate_key, entry[0])
        )
        if not matches:
            raise PermissionError("目录未被当前会话授权访问")
        root, capability = max(matches, key=lambda entry: len(entry[0]))
        relative = os.path.relpath(candidate, root)
        parts = Path(relative).parts
        if not parts or relative in {"", os.curdir}:
            raise PermissionError("不能直接修改授权根目录")
        with ExitStack() as stack:
            parent = capability
            for component in parts[:-1]:
                parent = stack.enter_context(
                    filesystem_child_directory_capability(parent, component)
                )
            parent.assert_bound()
            yield ApprovedChildPath(
                parent=parent,
                name=parts[-1],
                absolute_path=candidate,
            )


class ApprovedFileLease:
    """An already-open regular file plus every directory authority it needs."""

    def __init__(
        self,
        *,
        descriptor: int,
        stat_result: os.stat_result,
        authority_stack: ExitStack,
        authority_context: Context,
    ) -> None:
        self._descriptor = descriptor
        self.stat_result = stat_result
        self._authority_stack = authority_stack
        self._authority_context = authority_context
        self._close_lock = threading.Lock()
        self._closed = False

    @property
    def size(self) -> int:
        return int(self.stat_result.st_size)

    def iter_bytes(
        self,
        *,
        start: int = 0,
        length: int | None = None,
        chunk_size: int = 8192,
    ) -> Iterator[bytes]:
        os.lseek(self._descriptor, max(0, int(start)), os.SEEK_SET)
        remaining = None if length is None else max(0, int(length))
        while remaining is None or remaining > 0:
            read_size = chunk_size if remaining is None else min(chunk_size, remaining)
            data = os.read(self._descriptor, read_size)
            if not data:
                break
            if remaining is not None:
                remaining -= len(data)
            yield data

    def close(self, primary: BaseException | None = None) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        descriptor = self._descriptor
        self._descriptor = -1
        descriptor_error: BaseException | None = None
        try:
            os.close(descriptor)
        except BaseException as exc:
            descriptor_error = exc
            if primary is not None:
                _attach_cleanup_note(
                    primary,
                    "approved media descriptor cleanup failed",
                )
        authority_error: BaseException | None = None
        try:
            self._authority_context.run(self._authority_stack.close)
        except BaseException as exc:
            authority_error = exc
            if primary is not None:
                _attach_cleanup_note(
                    primary,
                    "approved media authority cleanup failed",
                )
        if primary is not None:
            return
        selected_error = _preferred_cleanup_error(
            descriptor_error,
            authority_error,
        )
        if selected_error is not None:
            if descriptor_error is not None and selected_error is not descriptor_error:
                _attach_cleanup_note(
                    selected_error,
                    "approved media descriptor cleanup also failed",
                )
            if authority_error is not None and selected_error is not authority_error:
                _attach_cleanup_note(
                    selected_error,
                    "approved media authority cleanup also failed",
                )
            raise selected_error

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:
            pass


class PathPolicy:
    """统一文件/目录的最终路径授权策略。

    允许根目录参数（``approved_roots``，调用侧也可能称 ``allowed_roots``）为
    ``None`` 或空集合时，当前实现不施加根目录限制。这种调用方式只能供受信本地
    调用使用，不能作为不可信路径输入的授权边界。
    """

    def normalize_roots(self, approved_roots: Iterable[str] | None) -> tuple[str, ...]:
        return tuple(normalize_path(root) for root in approved_roots or () if isinstance(root, str) and root)

    @staticmethod
    def capture_approved_root_grant(
        approved_root: str | os.PathLike[str],
    ) -> ApprovedRootGrant:
        raw_root = os.fspath(approved_root)
        if not raw_root:
            raise PermissionError("授权根目录路径不能为空")
        # Preserve the selected root's lexical identity so the capability can
        # reject a symlink/junction in the root or any of its ancestors.
        root = _stored_grant_path(raw_root)
        with filesystem_directory_capability(root) as capability:
            value = os.lstat(root)
            if not stat.S_ISDIR(value.st_mode) or is_link_or_reparse(value):
                raise PermissionError("授权根目录不是普通目录")
            capability.assert_bound()
            return root, (int(value.st_dev), int(value.st_ino))

    @staticmethod
    def _validated_root_grants(
        approved_root_grants: Iterable[ApprovedRootGrant] | None,
    ) -> tuple[ApprovedRootGrant, ...]:
        grants: list[ApprovedRootGrant] = []
        seen: dict[str, tuple[int, int]] = {}
        source = () if approved_root_grants is None else approved_root_grants
        iterator = iter(source)
        for _index in range(_MAX_APPROVED_ROOT_GRANTS + 1):
            try:
                raw_grant = next(iterator)
            except StopIteration:
                break
            if _index >= _MAX_APPROVED_ROOT_GRANTS:
                raise PermissionError("授权根目录数量超过安全上限")
            if type(raw_grant) is not tuple or len(raw_grant) != 2:
                raise PermissionError("授权根目录身份无效")
            raw_path, raw_identity = raw_grant
            if (
                type(raw_path) is not str
                or not raw_path
                or type(raw_identity) is not tuple
                or len(raw_identity) != 2
                or any(type(part) is not int for part in raw_identity)
            ):
                raise PermissionError("授权根目录身份无效")
            root = _stored_grant_path(raw_path)
            identity = int(raw_identity[0]), int(raw_identity[1])
            previous = seen.get(root)
            if previous is not None and previous != identity:
                raise PermissionError("授权根目录身份冲突")
            if previous is None:
                seen[root] = identity
                grants.append((root, identity))
        return tuple(grants)

    @contextmanager
    def lease_approved_root_grants(
        self,
        approved_root_grants: Iterable[ApprovedRootGrant] | None,
    ) -> Iterator[ApprovedRootsLease]:
        grants = self._validated_root_grants(approved_root_grants)
        if not grants:
            raise PermissionError("目录未被当前会话授权访问")
        with ExitStack() as stack:
            capabilities: list[tuple[str, FilesystemDirectoryCapability]] = []
            for root, expected_identity in grants:
                try:
                    capability = stack.enter_context(
                        filesystem_directory_capability(root)
                    )
                    current = os.lstat(root)
                except OSError as exc:
                    raise PermissionError(
                        "授权根目录身份已失效，请重新授权该目录"
                    ) from exc
                current_identity = int(current.st_dev), int(current.st_ino)
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or is_link_or_reparse(current)
                    or current_identity != expected_identity
                ):
                    raise PermissionError(
                        "授权根目录身份已变化，请重新授权该目录"
                    )
                capability.assert_bound()
                capabilities.append((root, capability))
            yield ApprovedRootsLease(tuple(capabilities))

    def open_approved_file(
        self,
        file_path: str | os.PathLike[str],
        approved_root_grants: Iterable[ApprovedRootGrant] | None,
    ) -> ApprovedFileLease:
        authority_context = Context()
        return authority_context.run(
            self._open_approved_file_in_context,
            file_path,
            approved_root_grants,
            authority_context,
        )

    def _open_approved_file_in_context(
        self,
        file_path: str | os.PathLike[str],
        approved_root_grants: Iterable[ApprovedRootGrant] | None,
        authority_context: Context,
    ) -> ApprovedFileLease:
        authority_stack = ExitStack()
        descriptor: int | None = None
        primary: BaseException | None = None
        try:
            roots = authority_stack.enter_context(
                self.lease_approved_root_grants(approved_root_grants)
            )
            child = authority_stack.enter_context(roots.bind_child(file_path))
            before = child.stat()
            if not stat.S_ISREG(before.st_mode) or is_link_or_reparse(before):
                raise OSError("approved media path is not a regular file")
            descriptor = child.parent.open_child(
                child.name,
                os.O_RDONLY | getattr(os, "O_NONBLOCK", 0),
            )
            opened = os.fstat(descriptor)
            after = child.stat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or is_link_or_reparse(opened)
                or not os.path.samestat(before, opened)
                or not os.path.samestat(opened, after)
            ):
                raise OSError("approved media file identity changed while opening")
            return ApprovedFileLease(
                descriptor=descriptor,
                stat_result=opened,
                authority_stack=authority_stack.pop_all(),
                authority_context=authority_context,
            )
        except BaseException as exc:
            primary = exc
            raise
        finally:
            if descriptor is not None and primary is not None:
                _close_preserving_primary(
                    lambda: os.close(descriptor),
                    primary,
                    note="approved media descriptor cleanup failed",
                )
            _close_preserving_primary(
                authority_stack.close,
                primary,
                note="approved media authority cleanup failed",
            )

    def assert_within_approved_roots(self, path: str, approved_roots: Iterable[str] | None) -> str:
        normalized = normalize_path(path)
        normalized_roots = self.normalize_roots(approved_roots)
        if normalized_roots and not any(is_within_root(normalized, root) for root in normalized_roots):
            raise PermissionError("目录未被当前会话授权访问")
        return normalized

    def resolve_existing_dir(self, directory: str, approved_roots: Iterable[str] | None = None) -> str:
        normalized = normalize_path(directory)
        if not os.path.isdir(normalized):
            raise FileNotFoundError("目录不存在")
        return self.assert_within_approved_roots(normalized, approved_roots)

    def resolve_existing_file(self, file_path: str, approved_roots: Iterable[str] | None = None) -> str:
        normalized = normalize_path(file_path)
        if not os.path.isfile(normalized):
            raise FileNotFoundError("文件不存在")
        return self.assert_within_approved_roots(normalized, approved_roots)

    def resolve_target_path(self, target_path: str, approved_roots: Iterable[str] | None = None) -> str:
        normalized = normalize_path(target_path)
        parent_dir = os.path.dirname(normalized)
        if not os.path.isdir(parent_dir):
            raise FileNotFoundError("目标目录不存在")
        self.assert_within_approved_roots(parent_dir, approved_roots)
        return normalized
