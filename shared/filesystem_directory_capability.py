"""Operation-scoped filesystem authority bound to one directory identity."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator


_ACTIVE_CAPABILITIES: ContextVar[
    dict[str, "FilesystemDirectoryCapability"]
] = ContextVar("filesystem_directory_capabilities", default={})


class FilesystemDirectoryCapability:
    """A live directory identity used for handle-relative child operations."""

    def __init__(
        self,
        root: Path,
        *,
        descriptor: int | None = None,
        windows_handles: tuple[tuple[int, int], ...] = (),
        identity: tuple[int, int],
        parent: "FilesystemDirectoryCapability | None" = None,
    ) -> None:
        self.root = root
        self._descriptor = descriptor
        self._windows_handles = windows_handles
        self._identity = identity
        self._parent = parent
        self._closed = False

    def assert_bound(self) -> None:
        self._assert_open()
        if self._parent is not None:
            self._parent.assert_bound()
        current = os.lstat(self.root)
        if not _safe_directory(current) or _stat_identity(current) != self._identity:
            raise OSError("approved directory identity changed during operation")
        if self._descriptor is not None:
            opened = os.fstat(self._descriptor)
            if not _safe_directory(opened) or _stat_identity(opened) != self._identity:
                raise OSError("approved directory handle identity changed")
        elif self._windows_handles:
            for index, (handle, expected_file_index) in enumerate(
                self._windows_handles
            ):
                information = _windows_handle_information(handle)
                if (
                    not information.is_directory
                    or information.is_reparse_point
                    or information.file_index != expected_file_index
                    or (
                        index == len(self._windows_handles) - 1
                        and information.file_index != self._identity[1]
                    )
                ):
                    raise OSError("approved directory handle identity changed")

    def stat_child(self, name: str) -> os.stat_result:
        child = _validated_child_name(name)
        self.assert_bound()
        if self._descriptor is not None:
            value = os.stat(
                child,
                dir_fd=self._descriptor,
                follow_symlinks=False,
            )
        else:
            value = os.lstat(self.root / child)
        self.assert_bound()
        if is_link_or_reparse(value):
            raise OSError("filesystem capability child is a link or reparse point")
        return value

    def open_child(self, name: str, flags: int, mode: int = 0o600) -> int:
        child = _validated_child_name(name)
        self.assert_bound()
        effective_flags = int(flags)
        effective_flags |= getattr(os, "O_BINARY", 0)
        effective_flags |= getattr(os, "O_NOINHERIT", 0)
        effective_flags |= getattr(os, "O_NOFOLLOW", 0)
        if self._descriptor is not None:
            descriptor = os.open(
                child,
                effective_flags,
                mode,
                dir_fd=self._descriptor,
            )
        else:
            descriptor = _open_windows_child_file(
                self.root / child,
                effective_flags,
            )
        try:
            self.assert_bound()
        except BaseException as exc:
            try:
                os.close(descriptor)
            except BaseException:
                _attach_note_best_effort(
                    exc,
                    "approved directory child descriptor cleanup failed",
                )
            raise
        return descriptor

    def mkdir_child(self, name: str, mode: int = 0o700) -> None:
        child = _validated_child_name(name)
        self.assert_bound()
        if self._descriptor is not None:
            os.mkdir(child, mode, dir_fd=self._descriptor)
        else:
            os.mkdir(self.root / child, mode)
        self.assert_bound()

    def open_directory_child(self, name: str) -> "FilesystemDirectoryCapability":
        """Derive a child-directory authority without re-resolving its parent."""

        child = _validated_child_name(name)
        before = self.stat_child(child)
        if not _safe_directory(before):
            raise OSError("filesystem capability child is not a regular directory")
        child_root = self.root / child
        if self._descriptor is not None:
            flags = os.O_RDONLY
            flags |= getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(child, flags, dir_fd=self._descriptor)
            try:
                opened = os.fstat(descriptor)
                after = os.stat(
                    child,
                    dir_fd=self._descriptor,
                    follow_symlinks=False,
                )
                identity = _stat_identity(opened)
                if (
                    not _safe_directory(opened)
                    or not _safe_directory(after)
                    or identity != _stat_identity(before)
                    or identity != _stat_identity(after)
                ):
                    raise OSError(
                        "child directory changed while deriving filesystem capability"
                    )
                self.assert_bound()
            except BaseException as exc:
                _close_descriptor_preserving_primary(descriptor, exc)
                raise
            return FilesystemDirectoryCapability(
                child_root,
                descriptor=descriptor,
                identity=identity,
                parent=self,
            )

        handle = _open_windows_directory_handle(child_root)
        try:
            information = _windows_handle_information(handle)
            after = os.lstat(child_root)
            identity = _stat_identity(after)
            if (
                not _safe_directory(after)
                or _stat_identity(before) != identity
                or not information.is_directory
                or information.is_reparse_point
                or information.file_index != identity[1]
            ):
                raise OSError(
                    "child directory changed while deriving filesystem capability"
                )
            self.assert_bound()
        except BaseException as exc:
            _close_windows_handle_preserving_primary(handle, exc)
            raise
        return FilesystemDirectoryCapability(
            child_root,
            windows_handles=((handle, information.file_index),),
            identity=identity,
            parent=self,
        )

    def unlink_child(self, name: str) -> None:
        child = _validated_child_name(name)
        self.stat_child(child)
        if self._descriptor is not None:
            os.unlink(child, dir_fd=self._descriptor)
        else:
            os.unlink(self.root / child)
        self.assert_bound()

    def rmdir_child(self, name: str) -> None:
        child = _validated_child_name(name)
        self.stat_child(child)
        if self._descriptor is not None:
            os.rmdir(child, dir_fd=self._descriptor)
        else:
            os.rmdir(self.root / child)
        self.assert_bound()

    def replace_child(
        self,
        source_name: str,
        target: "FilesystemDirectoryCapability",
        target_name: str,
    ) -> None:
        """Replace with the child present at the OS linearization point.

        This is a path operation, not an exact-generation publication.  A
        caller that trusted an earlier source must validate the target before
        it is consumed.
        """

        source_child = _validated_child_name(source_name)
        target_child = _validated_child_name(target_name)
        self.stat_child(source_child)
        try:
            target.stat_child(target_child)
        except FileNotFoundError:
            pass
        target.assert_bound()
        if self._descriptor is not None and target._descriptor is not None:
            os.replace(
                source_child,
                target_child,
                src_dir_fd=self._descriptor,
                dst_dir_fd=target._descriptor,
            )
        elif self._descriptor is None and target._descriptor is None:
            os.replace(
                self.root / source_child,
                target.root / target_child,
            )
        else:
            raise OSError("approved directory capabilities are incompatible")
        self.assert_bound()
        target.assert_bound()

    def rename_child_no_replace(
        self,
        source_name: str,
        target: "FilesystemDirectoryCapability",
        target_name: str,
    ) -> None:
        """Rename the child present at the OS linearization point.

        This is deliberately a path operation: callers that validated an earlier
        source generation must validate the authoritative target before use.
        """

        source_child = _validated_child_name(source_name)
        target_child = _validated_child_name(target_name)
        self.stat_child(source_child)
        try:
            target.stat_child(target_child)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(target.root / target_child)
        self.assert_bound()
        target.assert_bound()
        if self._descriptor is not None and target._descriptor is not None:
            _rename_posix_no_replace(
                self._descriptor,
                source_child,
                target._descriptor,
                target_child,
            )
        elif self._descriptor is None and target._descriptor is None:
            os.rename(
                self.root / source_child,
                target.root / target_child,
            )
        else:
            raise OSError("approved directory capabilities are incompatible")
        self.assert_bound()
        target.assert_bound()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._descriptor is not None:
            descriptor = self._descriptor
            self._descriptor = None
            os.close(descriptor)
        elif self._windows_handles:
            handles = self._windows_handles
            self._windows_handles = ()
            first_error: BaseException | None = None
            for handle, _file_index in reversed(handles):
                try:
                    _close_windows_handle(handle)
                except BaseException as exc:
                    first_error = _preferred_cleanup_error(first_error, exc)
            if first_error is not None:
                raise first_error

    def _assert_open(self) -> None:
        if self._closed:
            raise OSError("approved directory capability is closed")


@contextmanager
def filesystem_directory_capability(
    path: str | os.PathLike[str],
) -> Iterator[FilesystemDirectoryCapability]:
    """Bind one existing regular directory for a complete filesystem operation."""

    root = Path(os.path.abspath(os.fspath(path)))
    key = os.path.normcase(os.fspath(root))
    active = _ACTIVE_CAPABILITIES.get()
    existing = active.get(key)
    if existing is not None:
        existing.assert_bound()
        primary_error: BaseException | None = None
        try:
            yield existing
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            _assert_bound_preserving_primary(existing, primary_error)
        return

    _require_regular_directory_ancestry(root)
    capability = _open_directory_capability(root)
    token = _ACTIVE_CAPABILITIES.set({**active, key: capability})
    primary_error = None
    try:
        yield capability
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        _ACTIVE_CAPABILITIES.reset(token)
        _finish_capability(capability, primary_error)


@contextmanager
def filesystem_child_directory_capability(
    parent: FilesystemDirectoryCapability,
    name: str,
) -> Iterator[FilesystemDirectoryCapability]:
    """Register a handle-relative child authority for nested operations."""

    capability = parent.open_directory_child(name)
    key = os.path.normcase(os.fspath(capability.root))
    active = _ACTIVE_CAPABILITIES.get()
    token = _ACTIVE_CAPABILITIES.set({**active, key: capability})
    primary_error: BaseException | None = None
    try:
        yield capability
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        _ACTIVE_CAPABILITIES.reset(token)
        _finish_capability(capability, primary_error)


def ensure_regular_directory(
    path: str | os.PathLike[str],
    *,
    create: bool = False,
) -> Path:
    """Validate a directory chain and create missing components handle-relatively."""

    directory = Path(os.path.abspath(os.fspath(path)))
    chain: list[Path] = []
    current = directory
    while True:
        chain.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for candidate in reversed(chain):
        try:
            value = os.lstat(candidate)
        except FileNotFoundError:
            if not create:
                raise
            parent = candidate.parent
            with filesystem_directory_capability(parent) as capability:
                try:
                    capability.mkdir_child(candidate.name)
                except FileExistsError:
                    pass
                value = capability.stat_child(candidate.name)
        if not _safe_directory(value):
            raise OSError("directory ancestry is not a regular directory")
    return directory


def is_link_or_reparse(value: os.stat_result) -> bool:
    attributes = int(getattr(value, "st_file_attributes", 0) or 0)
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _open_directory_capability(root: Path) -> FilesystemDirectoryCapability:
    if os.name == "nt":
        handles, identity = _open_windows_directory_chain(root)
        return FilesystemDirectoryCapability(
            root,
            windows_handles=handles,
            identity=identity,
        )
    descriptor, identity = _open_posix_directory_chain(root)
    return FilesystemDirectoryCapability(
        root,
        descriptor=descriptor,
        identity=identity,
    )


def _open_posix_directory_chain(root: Path) -> tuple[int, tuple[int, int]]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    anchor = Path(root.anchor)
    descriptor: int | None = os.open(anchor, flags)
    try:
        assert descriptor is not None
        anchor_stat = os.fstat(descriptor)
        if not _safe_directory(anchor_stat):
            raise OSError("filesystem anchor is not a regular directory")
        for component in root.parts[1:]:
            child_descriptor = os.open(
                component,
                flags,
                dir_fd=descriptor,
            )
            try:
                opened = os.fstat(child_descriptor)
                linked = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                if (
                    not _safe_directory(opened)
                    or not _safe_directory(linked)
                    or _stat_identity(opened) != _stat_identity(linked)
                ):
                    raise OSError(
                        "directory changed while acquiring filesystem capability"
                    )
            except BaseException as exc:
                _close_descriptor_preserving_primary(child_descriptor, exc)
                raise
            previous_descriptor = descriptor
            descriptor = child_descriptor
            try:
                os.close(previous_descriptor)
            except BaseException as exc:
                _close_descriptor_preserving_primary(descriptor, exc)
                descriptor = None
                raise
        assert descriptor is not None
        opened = os.fstat(descriptor)
        after = os.lstat(root)
        identity = _stat_identity(opened)
        if (
            not _safe_directory(opened)
            or not _safe_directory(after)
            or _stat_identity(after) != identity
        ):
            raise OSError("approved directory changed while acquiring capability")
        return descriptor, identity
    except BaseException as exc:
        if descriptor is not None:
            _close_descriptor_preserving_primary(descriptor, exc)
        raise


def _rename_posix_no_replace(
    source_descriptor: int,
    source_name: str,
    target_descriptor: int,
    target_name: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        flags = 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        rename = getattr(libc, "renameatx_np", None)
        flags = 4  # RENAME_EXCL
    else:
        rename = None
        flags = 0
    if rename is None:
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace rename is unavailable on this platform",
        )
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = rename(
        source_descriptor,
        os.fsencode(source_name),
        target_descriptor,
        os.fsencode(target_name),
        flags,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _open_windows_directory_chain(
    root: Path,
) -> tuple[tuple[tuple[int, int], ...], tuple[int, int]]:
    chain: list[Path] = []
    current = root
    while True:
        chain.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    handles: list[tuple[int, int]] = []
    try:
        for candidate in reversed(chain):
            before = os.lstat(candidate)
            if not _safe_directory(before):
                raise OSError("approved directory is not a regular directory")
            handle = _open_windows_directory_handle(candidate)
            try:
                information = _windows_handle_information(handle)
                after = os.lstat(candidate)
                identity = _stat_identity(after)
                if (
                    not _safe_directory(after)
                    or _stat_identity(before) != identity
                    or not information.is_directory
                    or information.is_reparse_point
                    or information.file_index != identity[1]
                ):
                    raise OSError(
                        "directory changed while acquiring filesystem capability"
                    )
            except BaseException as exc:
                _close_windows_handle_preserving_primary(handle, exc)
                raise
            handles.append((handle, information.file_index))
        return tuple(handles), _stat_identity(os.lstat(root))
    except BaseException as exc:
        for handle, _file_index in reversed(handles):
            _close_windows_handle_preserving_primary(handle, exc)
        raise


def _require_regular_directory_ancestry(path: Path) -> None:
    chain: list[Path] = []
    current = path
    while True:
        chain.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for candidate in reversed(chain):
        value = os.lstat(candidate)
        if not _safe_directory(value):
            raise OSError("directory ancestry is not a regular directory")


def _safe_directory(value: os.stat_result) -> bool:
    return stat.S_ISDIR(value.st_mode) and not is_link_or_reparse(value)


def _stat_identity(value: os.stat_result) -> tuple[int, int]:
    return int(value.st_dev), int(value.st_ino)


def _validated_child_name(value: str) -> str:
    if type(value) is not str:
        raise OSError("filesystem capability child name is invalid")
    reserved_stem = value.split(".", 1)[0].rstrip(" .").upper()
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or value.endswith((".", " "))
        or any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
        or any(character in '<>"|?*' for character in value)
        or reserved_stem
        in {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
        or (
            len(reserved_stem) == 4
            and reserved_stem[:3] in {"COM", "LPT"}
            and reserved_stem[3] in "123456789¹²³"
        )
    ):
        raise OSError("filesystem capability child name is invalid")
    return value


def _assert_bound_preserving_primary(
    capability: FilesystemDirectoryCapability,
    primary_error: BaseException | None,
) -> None:
    try:
        capability.assert_bound()
    except BaseException:
        if primary_error is None:
            raise
        _attach_note_best_effort(
            primary_error,
            "approved directory identity changed while handling another failure",
        )


def _finish_capability(
    capability: FilesystemDirectoryCapability,
    primary_error: BaseException | None,
) -> None:
    identity_error: BaseException | None = None
    try:
        capability.assert_bound()
    except BaseException as exc:
        identity_error = exc
        if primary_error is not None:
            _attach_note_best_effort(
                primary_error,
                "approved directory identity changed while handling another failure",
            )
    close_error: BaseException | None = None
    try:
        capability.close()
    except BaseException as exc:
        close_error = exc
        if primary_error is not None:
            _attach_note_best_effort(
                primary_error,
                "approved directory capability cleanup failed",
            )
        elif identity_error is not None:
            _attach_note_best_effort(
                identity_error,
                "approved directory capability cleanup failed",
            )
    if primary_error is not None:
        return
    selected_error = _preferred_cleanup_error(identity_error, close_error)
    if selected_error is not None:
        raise selected_error


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


def _attach_note_best_effort(error: BaseException, note: str) -> None:
    try:
        add_note = object.__getattribute__(error, "add_note")
    except BaseException:
        return
    if not callable(add_note):
        return
    try:
        add_note(note)
    except BaseException:
        return


def _close_descriptor_preserving_primary(
    descriptor: int,
    primary_error: BaseException,
) -> None:
    try:
        os.close(descriptor)
    except BaseException:
        _attach_note_best_effort(
            primary_error,
            "filesystem child directory descriptor cleanup failed",
        )


def _close_windows_handle_preserving_primary(
    handle: int,
    primary_error: BaseException,
) -> None:
    try:
        _close_windows_handle(handle)
    except BaseException:
        _attach_note_best_effort(
            primary_error,
            "filesystem child directory handle cleanup failed",
        )


class _WindowsDirectoryInformation:
    __slots__ = ("file_index", "is_directory", "is_reparse_point")

    def __init__(
        self,
        *,
        file_index: int,
        attributes: int,
    ) -> None:
        self.file_index = file_index
        self.is_directory = bool(attributes & 0x10)
        self.is_reparse_point = bool(attributes & 0x400)


def _open_windows_child_file(path: Path, flags: int) -> int:
    import msvcrt

    access_mode = flags & getattr(os, "O_ACCMODE", 3)
    if access_mode == os.O_WRONLY:
        desired_access = 0x40000000  # GENERIC_WRITE
    elif access_mode == os.O_RDWR:
        desired_access = 0x80000000 | 0x40000000  # GENERIC_READ | GENERIC_WRITE
    else:
        desired_access = 0x80000000  # GENERIC_READ
    if flags & os.O_CREAT and flags & os.O_EXCL:
        disposition = 1  # CREATE_NEW
    elif flags & os.O_CREAT:
        disposition = 4  # OPEN_ALWAYS
    else:
        disposition = 3  # OPEN_EXISTING
    raw_handle = _create_windows_child_handle(
        path,
        desired_access,
        disposition,
    )
    try:
        information = _windows_handle_information(raw_handle)
        if information.is_directory or information.is_reparse_point:
            raise OSError(
                "filesystem capability child is a link or reparse point"
            )
        descriptor_flags = access_mode
        descriptor_flags |= getattr(os, "O_BINARY", 0)
        descriptor_flags |= flags & getattr(os, "O_APPEND", 0)
        descriptor = msvcrt.open_osfhandle(raw_handle, descriptor_flags)
        raw_handle = -1
        try:
            os.set_inheritable(descriptor, False)
            if flags & os.O_TRUNC:
                os.ftruncate(descriptor, 0)
        except BaseException as exc:
            _close_descriptor_preserving_primary(descriptor, exc)
            raise
        return descriptor
    except BaseException as exc:
        if raw_handle >= 0:
            _close_windows_handle_preserving_primary(raw_handle, exc)
        raise


def _create_windows_child_handle(
    path: Path,
    desired_access: int,
    disposition: int,
) -> int:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        os.fspath(path),
        desired_access,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        disposition,
        0x00200000 | 0x00000080,  # OPEN_REPARSE_POINT | NORMAL
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in {None, invalid_handle}:
        error_number = ctypes.get_last_error()
        if error_number in {80, 183}:  # FILE_EXISTS | ALREADY_EXISTS
            raise FileExistsError(
                error_number,
                "filesystem capability child already exists",
            )
        raise OSError(
            error_number,
            "filesystem capability child could not be opened",
        )
    return int(handle)


def _open_windows_directory_handle(path: Path) -> int:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        os.fspath(path),
        0x80000000,  # GENERIC_READ: deny rename/delete without blocking children.
        0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE.
        None,
        3,  # OPEN_EXISTING.
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT.
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in {None, invalid_handle}:
        raise OSError(
            ctypes.get_last_error(),
            "approved directory capability could not be acquired",
        )
    return int(handle)


def _windows_handle_information(handle: int) -> _WindowsDirectoryInformation:
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    information = ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise OSError(
            ctypes.get_last_error(),
            "approved directory handle could not be inspected",
        )
    return _WindowsDirectoryInformation(
        file_index=(
            (int(information.nFileIndexHigh) << 32)
            | int(information.nFileIndexLow)
        ),
        attributes=int(information.dwFileAttributes),
    )


def _close_windows_handle(handle: int) -> None:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise OSError(
            ctypes.get_last_error(),
            "approved directory capability cleanup failed",
        )


__all__ = [
    "FilesystemDirectoryCapability",
    "ensure_regular_directory",
    "filesystem_child_directory_capability",
    "filesystem_directory_capability",
    "is_link_or_reparse",
]
