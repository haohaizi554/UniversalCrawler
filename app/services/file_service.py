"""本地媒体库的扫描、重命名与受约束删除逻辑。"""

import ctypes
import errno
import heapq
import os
import re
import shutil
import stat
import sys
import time
import unicodedata
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, NoReturn, TypeVar

from app.debug_logger import debug_logger
from app.exceptions import FileOperationError, MediaScanError
from app.models import VideoItem
from app.services.path_policy import (
    ApprovedChildPath,
    ApprovedRootGrant,
    ApprovedRootsLease,
    PathPolicy,
)
from app.utils import sanitize_filename

T = TypeVar("T")


class _RenameOutcome(Enum):
    COMPLETED = auto()
    NOT_COMPLETED = auto()
    UNKNOWN = auto()

@dataclass
class ScanResult:
    """媒体库扫描结果；truncated/original_count 用于前端提示大目录被截断。"""

    items: list[VideoItem]
    total_count: int
    video_count: int
    image_count: int
    truncated: bool = False
    original_count: int = 0


@dataclass(frozen=True)
class OrphanDirectorySweepResult:
    """受限恢复中单层目录的扫描结果；子目录交给持久化前沿继续遍历。"""

    removed_count: int
    children: tuple[tuple[Path, int], ...]
    scanned_entries: int
    truncated: bool = False
    error: str = ""


@dataclass(frozen=True)
class MediaDeleteMutationPlan:
    """Frozen paths that one ``delete_media`` call is allowed to mutate."""

    file_path: str
    temp_paths: tuple[str, ...]
    owned_directories: tuple[str, ...]

    @property
    def authorization_targets(self) -> tuple[str, ...]:
        return tuple(
            path
            for path in (self.file_path, *self.temp_paths, *self.owned_directories)
            if path
        )


class MediaDeleteStatus(str, Enum):
    """Durable outcome states for a delete that cannot return ordinary success."""

    OUTCOME_UNCERTAIN = "outcome_uncertain"
    COMMITTED_TARGET_REPLACED = "committed_target_replaced"
    COMMITTED_AUTHORITY_UNCERTAIN = "committed_authority_uncertain"


@dataclass(frozen=True)
class MediaDeleteReceipt:
    """Non-sensitive delete evidence that explicitly forbids blind retries."""

    target_name: str
    status: MediaDeleteStatus

    @property
    def committed(self) -> bool | None:
        if self.status is MediaDeleteStatus.OUTCOME_UNCERTAIN:
            return None
        return True

    @property
    def retry_safe(self) -> bool:
        return False


class MediaDeleteOutcomeError(FileOperationError):
    """A delete that must be reconciled instead of retried by path."""

    def __init__(self, message: str, receipt: MediaDeleteReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status={self.receipt.status.value!r}, "
            f"committed={self.receipt.committed!r})"
        )


class MediaRenameStatus(str, Enum):
    """Durable outcome states for a rename that cannot return ordinary success."""

    OUTCOME_UNCERTAIN = "outcome_uncertain"
    COMMITTED_TARGET_INVALID = "committed_target_invalid"
    COMMITTED_AUTHORITY_UNCERTAIN = "committed_authority_uncertain"


@dataclass(frozen=True)
class MediaRenameReceipt:
    """Non-sensitive rename outcome evidence for reconciliation by the caller."""

    source_name: str
    target_name: str
    status: MediaRenameStatus

    @property
    def committed(self) -> bool | None:
        if self.status is MediaRenameStatus.OUTCOME_UNCERTAIN:
            return None
        return True

    @property
    def retry_safe(self) -> bool:
        return False


class MediaRenameOutcomeError(FileOperationError):
    """A rename that must be reconciled instead of blindly retried or rolled back."""

    def __init__(self, message: str, receipt: MediaRenameReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status={self.receipt.status.value!r}, "
            f"committed={self.receipt.committed!r})"
        )


class MediaLibraryService:
    """扫描和重命名媒体，并以任务归属及临时名白名单约束联动删除。"""

    # 下载器会把临时文件显式记录到 meta；删除媒体时优先相信这些“本任务拥有”的路径。
    TEMP_FILE_META_KEYS = ("download_temp_files", "temporary_files")
    BILIBILI_TEMP_SUFFIXES = ("_video.m4s", "_audio.m4s")
    HLS_TEMP_ROOT_NAME = ".ucp-nm3u8-tmp"
    HLS_TEMP_DIR_SUFFIXES = ("_curl_cffi_hls", "_playwright_hls")
    ORPHAN_SWEEP_MAX_DIRECTORIES = 2048
    ORPHAN_SWEEP_MAX_ENTRIES = 50000
    ORPHAN_SWEEP_TIME_BUDGET_SECONDS = 3.0
    # 分块下载的 .<最终文件名>.partN 允许被清理，但必须匹配隐藏分片格式，避免误删普通文件。
    _CHUNK_PART_RE = re.compile(r"^\..+\.part\d+$", re.IGNORECASE)
    _ORPHAN_MEDIA_TEMP_SUFFIXES = (
        ".mp4.tmp",
        ".mp4.part",
        ".mp4.download",
        ".m4s.tmp",
        ".m4s.part",
        ".m4s.download",
        ".ts.tmp",
        ".ts.part",
        ".ts.download",
    )
    _EXPLICIT_TEMP_SUFFIXES = (
        ".downloading",
        ".merging",
        ".tmp",
        ".part",
        ".aria2",
        ".download",
        *BILIBILI_TEMP_SUFFIXES,
    )

    def __init__(
        self,
        video_extensions: tuple[str, ...],
        image_extensions: tuple[str, ...],
        *,
        path_policy: PathPolicy | None = None,
    ) -> None:
        self.video_extensions = tuple(ext.lower() for ext in video_extensions)
        self.image_extensions = tuple(ext.lower() for ext in image_extensions)
        self.all_media_extensions = self.video_extensions + self.image_extensions
        self._path_policy = path_policy or PathPolicy()

    @staticmethod
    def _run_file_mutation_with_retry(
        operation: Callable[[], T],
        *,
        error_message: str,
        required: bool,
        missing_ok: bool = False,
    ) -> T | None:
        """按项目统一策略短暂重试 Windows 文件占用；必需操作最终失败时抛领域异常。"""
        last_error: OSError | None = None
        for attempt in range(3):
            try:
                return operation()
            except FileNotFoundError as exc:
                if missing_ok or not required:
                    return None
                raise FileOperationError(str(exc)) from exc
            except PermissionError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                break
            except OSError as exc:
                if required:
                    raise FileOperationError(str(exc)) from exc
                return None
        if required:
            raise FileOperationError(str(last_error) if last_error else error_message)
        return None

    def _delete_file(self, file_path: str, *, required: bool) -> bool:
        """删除单个文件；required=True 时把失败传播给调用方，辅助临时文件则尽量清理。"""
        if not file_path or not os.path.exists(file_path):
            return False
        result = self._run_file_mutation_with_retry(
            lambda: os.remove(file_path) is None,
            error_message="Failed to delete file",
            required=required,
            missing_ok=True,
        )
        return bool(result)

    @staticmethod
    def _normalized_abs(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    @classmethod
    def _looks_like_explicit_temp_path(cls, path: str) -> bool:
        """判断路径名是否像本项目下载器产生的临时文件，作为防误删第一道门。"""
        name = os.path.basename(str(path or "")).lower()
        if not name:
            return False
        return cls._is_safe_orphan_temp_file_name(name) or name.endswith(cls._EXPLICIT_TEMP_SUFFIXES)

    @classmethod
    def _is_safe_orphan_temp_file_name(cls, name: str) -> bool:
        lower_name = str(name or "").lower()
        if not lower_name:
            return False
        if lower_name.endswith(".downloading"):
            return True
        if lower_name.endswith(".merging"):
            return True
        if lower_name.endswith(cls.BILIBILI_TEMP_SUFFIXES):
            return True
        if lower_name.endswith(".aria2"):
            return True
        if lower_name.endswith(cls._ORPHAN_MEDIA_TEMP_SUFFIXES):
            return True
        return bool(cls._CHUNK_PART_RE.match(lower_name))

    @classmethod
    def _is_safe_orphan_temp_dir_name(cls, name: str) -> bool:
        lower_name = str(name or "").lower()
        return lower_name == cls.HLS_TEMP_ROOT_NAME or lower_name.endswith(cls.HLS_TEMP_DIR_SUFFIXES)

    @classmethod
    def _remove_temp_path(cls, path: str | os.PathLike[str]) -> bool:
        """删除已确认安全的临时路径；调用方必须先完成命名白名单判断。"""
        try:
            target = Path(path)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                return not target.exists()
            if target.exists():
                target.unlink()
                return True
        except OSError:
            return False
        return False

    def _iter_download_temp_paths(self, video: VideoItem, file_path: str) -> list[str]:
        """枚举普通/分块/外部工具下载的临时文件，限制在最终文件所在目录内。"""
        meta = video.meta if isinstance(video.meta, dict) else {}
        candidates: list[str] = []
        seen: set[str] = set()
        owned_dirs: set[str] = set()

        def add_candidate(path: object, *, require_owned_dir: bool = True) -> None:
            if not isinstance(path, str) or not path:
                return
            try:
                absolute = os.path.abspath(path)
                normalized = self._normalized_abs(absolute)
                directory = self._normalized_abs(os.path.dirname(absolute) or os.curdir)
            except (OSError, TypeError, ValueError):
                return
            if require_owned_dir and owned_dirs and directory not in owned_dirs:
                # meta 里的路径可能来自旧版本或外部输入，默认不跨目录删除。
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(absolute)

        if file_path:
            final_dir = os.path.abspath(os.path.dirname(file_path) or os.curdir)
            owned_dirs.add(self._normalized_abs(final_dir))
            name = os.path.basename(file_path)
            stem = os.path.splitext(name)[0]
            # 兼容不同下载器命名：有的拼在完整文件名后，有的拼在 stem 后。
            add_candidate(file_path + ".downloading")
            for suffix in (".tmp", ".part", ".aria2", ".download"):
                add_candidate(os.path.join(final_dir, f"{name}{suffix}"))
                if stem:
                    add_candidate(os.path.join(final_dir, f"{stem}{suffix}"))
            try:
                for entry in os.scandir(final_dir):
                    if not entry.is_file():
                        continue
                    entry_name = entry.name
                    if self._CHUNK_PART_RE.match(entry_name) and entry_name.startswith(f".{name}.part"):
                        add_candidate(entry.path)
                    elif stem and entry_name.startswith(stem) and self._looks_like_explicit_temp_path(entry_name):
                        add_candidate(entry.path)
            except OSError:
                pass

        for key in self.TEMP_FILE_META_KEYS:
            raw_paths = meta.get(key)
            iterable: Iterable[object]
            if isinstance(raw_paths, str):
                iterable = [raw_paths]
            elif isinstance(raw_paths, (list, tuple, set)):
                iterable = raw_paths
            else:
                continue
            for raw_path in iterable:
                if not isinstance(raw_path, str) or not self._looks_like_explicit_temp_path(raw_path):
                    continue
                # 有 final path 时仍要求同目录；没有 final path 的失败记录才允许直接使用 meta 路径。
                add_candidate(raw_path, require_owned_dir=bool(owned_dirs))

        return candidates

    def _iter_bilibili_temp_paths(self, video: VideoItem, file_path: str) -> list[str]:
        """按 Bilibili DASH 分流命名补齐 `_video.m4s`/`_audio.m4s` 兄弟文件。"""
        meta = video.meta if isinstance(video.meta, dict) else {}
        source = str(getattr(video, "source", "") or "").lower()
        has_bilibili_context = source == "bilibili" or any(meta.get(key) for key in ("bvid", "cid", "audio_url"))
        candidates: list[str] = []
        seen: set[str] = set()
        roots: list[tuple[str, str]] = []
        seen_roots: set[tuple[str, str]] = set()

        def temp_root_from_path(path: str) -> tuple[str, str] | None:
            path_text = str(path or "")
            lower_name = os.path.basename(path_text).lower()
            for suffix in self.BILIBILI_TEMP_SUFFIXES:
                if lower_name.endswith(suffix):
                    base_name = os.path.basename(path_text)[: -len(suffix)]
                    if base_name:
                        return os.path.abspath(os.path.dirname(path_text) or os.curdir), base_name
            return None

        def add_root(root: tuple[str, str] | None) -> None:
            if root is None:
                return
            directory, base_name = root
            normalized = (os.path.normcase(os.path.abspath(directory)), base_name)
            if normalized in seen_roots:
                return
            seen_roots.add(normalized)
            roots.append((os.path.abspath(directory), base_name))

        def add_candidate(path: object) -> None:
            if not isinstance(path, str) or not path:
                return
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized not in seen:
                seen.add(normalized)
                candidates.append(os.path.abspath(path))

        if file_path:
            temp_root = temp_root_from_path(file_path)
            if temp_root is not None:
                add_root(temp_root)
            else:
                final_dir = os.path.abspath(os.path.dirname(file_path) or os.curdir)
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                if base_name:
                    add_root((final_dir, base_name))

        for key in self.TEMP_FILE_META_KEYS:
            raw_paths = meta.get(key)
            iterable: Iterable[object]
            if isinstance(raw_paths, str):
                iterable = [raw_paths]
            elif isinstance(raw_paths, (list, tuple, set)):
                iterable = raw_paths
            else:
                continue
            for raw_path in iterable:
                if file_path or not isinstance(raw_path, str):
                    continue
                add_root(temp_root_from_path(raw_path))

        if has_bilibili_context:
            for directory, base_name in roots:
                for suffix in self.BILIBILI_TEMP_SUFFIXES:
                    add_candidate(os.path.join(directory, f"{base_name}{suffix}"))

        return candidates

    def scan_directory(self, directory: str, max_scan_count: int = 1000) -> ScanResult:
        """扫描目录并按最近修改时间返回媒体文件。"""
        try:
            if not os.path.exists(directory):
                # 启动时如果目录还不存在，直接创建一个空目录，避免首轮扫描报错。
                os.makedirs(directory, exist_ok=True)
                return ScanResult(items=[], total_count=0, video_count=0, image_count=0)

            media_entries: list[tuple[float, str]] = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    if not entry.name.lower().endswith(self.all_media_extensions):
                        continue
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    media_entries.append((stat.st_mtime, entry.name))

            original_count = len(media_entries)
            truncated = original_count > max_scan_count
            if truncated:
                # 大目录只保留最近更新的一部分文件，避免全量排序和前端渲染同时放大延迟。
                selected_entries = heapq.nlargest(max_scan_count, media_entries, key=lambda item: item[0])
            else:
                selected_entries = sorted(media_entries, key=lambda item: item[0], reverse=True)

            items: list[VideoItem] = []
            video_count = 0
            image_count = 0

            for _mtime, filename in selected_entries:
                title, ext = os.path.splitext(filename)
                ext = ext.lower()
                item = VideoItem(url="", title=title, source="local")
                item.status = "✅ 本地"
                item.progress = 100
                item.local_path = os.path.join(directory, filename)
                if ext in self.video_extensions:
                    item.meta["content_type"] = "video"
                    video_count += 1
                elif ext in self.image_extensions:
                    item.meta["content_type"] = "image"
                    image_count += 1
                items.append(item)

            return ScanResult(
                items=items,
                total_count=len(items),
                video_count=video_count,
                image_count=image_count,
                truncated=truncated,
                original_count=original_count,
            )
        except OSError as exc:
            raise MediaScanError(str(exc)) from exc

    @classmethod
    def sweep_orphan_download_temp_directory(
        cls,
        directory: str | os.PathLike[str],
        *,
        depth: int,
        max_depth: int = 2,
        entry_limit: int | None = None,
    ) -> OrphanDirectorySweepResult:
        """只扫描当前一层并返回子目录，使调用方可以持久化遍历进度。"""
        normalized_depth = max(0, min(int(depth or 0), 2))
        depth_limit = max(0, min(int(max_depth or 0), 2))
        limit = max(1, int(entry_limit or cls.ORPHAN_SWEEP_MAX_ENTRIES))
        try:
            current_path = Path(directory).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return OrphanDirectorySweepResult(0, (), 0, error=str(exc))
        if not current_path.is_dir():
            return OrphanDirectorySweepResult(0, (), 0)

        removed = 0
        scanned_entries = 0
        truncated = False
        children: list[tuple[Path, int]] = []
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if scanned_entries >= limit:
                        truncated = True
                        break
                    scanned_entries += 1
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if (
                                cls._is_safe_orphan_temp_file_name(entry.name)
                                and cls._remove_temp_path(entry.path)
                            ):
                                removed += 1
                            continue
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if cls._is_safe_orphan_temp_dir_name(entry.name):
                            if cls._remove_temp_path(entry.path):
                                removed += 1
                            continue
                        if normalized_depth < depth_limit:
                            children.append((Path(entry.path).resolve(strict=False), normalized_depth + 1))
                    except OSError:
                        continue
        except OSError as exc:
            return OrphanDirectorySweepResult(
                removed,
                tuple(sorted(children, key=lambda item: str(item[0]))),
                scanned_entries,
                truncated=truncated,
                error=str(exc),
            )
        return OrphanDirectorySweepResult(
            removed,
            tuple(sorted(children, key=lambda item: str(item[0]))),
            scanned_entries,
            truncated=truncated,
        )

    @classmethod
    def sweep_orphan_download_temp_artifacts(
        cls,
        directories: list[str | os.PathLike[str]],
        *,
        max_depth: int = 2,
    ) -> int:
        """启动时仅清理已知临时名，并用深度、条目数和时间预算限制目录遍历。"""
        removed = 0
        depth_limit = max(0, min(int(max_depth or 0), 2))
        scanned_directories = 0
        scanned_entries = 0
        started_at = time.monotonic()
        truncated = False
        for raw_dir in directories:
            if truncated:
                break
            try:
                root = Path(raw_dir).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            if not root.exists() or not root.is_dir():
                continue
            pending: list[tuple[Path, int]] = [(root, 0)]
            while pending:
                if (
                    scanned_directories >= cls.ORPHAN_SWEEP_MAX_DIRECTORIES
                    or scanned_entries >= cls.ORPHAN_SWEEP_MAX_ENTRIES
                    or time.monotonic() - started_at >= cls.ORPHAN_SWEEP_TIME_BUDGET_SECONDS
                ):
                    truncated = True
                    break
                current_path, depth = pending.pop()
                scanned_directories += 1
                result = cls.sweep_orphan_download_temp_directory(
                    current_path,
                    depth=depth,
                    max_depth=depth_limit,
                    entry_limit=cls.ORPHAN_SWEEP_MAX_ENTRIES - scanned_entries,
                )
                removed += result.removed_count
                scanned_entries += result.scanned_entries
                pending.extend(result.children)
                if result.truncated:
                    truncated = True
                    break
        if truncated:
            debug_logger.log(
                component="MediaLibraryService",
                action="bounded_orphan_temp_sweep",
                level="WARN",
                message="Stopped legacy temp cleanup at the production scan budget",
                status_code="DL_TEMP_SWEEP_BOUNDED",
                details={
                    "max_depth": depth_limit,
                    "scanned_directories": scanned_directories,
                    "scanned_entries": scanned_entries,
                    "removed_count": removed,
                },
            )
        return removed

    @staticmethod
    def _actual_directory_entry_name(path: str) -> str | None:
        absolute = os.path.abspath(os.path.normpath(path))
        parent = os.path.dirname(absolute) or os.curdir
        requested_name = os.path.basename(absolute)
        normalized_matches: list[str] = []
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    if entry.name == requested_name:
                        return entry.name
                    if entry.name.casefold() == requested_name.casefold():
                        normalized_matches.append(entry.name)
        except (OSError, TypeError, ValueError):
            return None
        return normalized_matches[0] if len(normalized_matches) == 1 else None

    @classmethod
    def _rename_target_state(cls, source_path: str, target_path: str) -> str:
        source_lexical = os.path.abspath(os.path.normpath(source_path))
        target_lexical = os.path.abspath(os.path.normpath(target_path))
        if source_lexical == target_lexical:
            return "same"
        try:
            target_exists = os.path.lexists(target_path)
        except (OSError, TypeError, ValueError):
            return "conflict"
        if not target_exists:
            return "available"
        try:
            if not os.path.samefile(source_path, target_path):
                return "conflict"
            if stat.S_ISLNK(os.lstat(source_path).st_mode) or stat.S_ISLNK(
                os.lstat(target_path).st_mode
            ):
                return "conflict"
            source_parent = os.path.dirname(source_lexical) or os.curdir
            target_parent = os.path.dirname(target_lexical) or os.curdir
            if not os.path.samefile(source_parent, target_parent):
                return "conflict"
        except (OSError, TypeError, ValueError):
            return "conflict"
        source_entry = cls._actual_directory_entry_name(source_path)
        target_entry = cls._actual_directory_entry_name(target_path)
        if source_entry is None or source_entry != target_entry:
            return "conflict"
        if os.path.basename(source_lexical) != os.path.basename(target_lexical):
            return "case_alias"
        return "same"

    @staticmethod
    def _regular_rename_source_stat(
        source_path: str,
        expected: os.stat_result | None = None,
    ) -> os.stat_result:
        try:
            current = os.lstat(source_path)
        except FileNotFoundError as exc:
            raise FileOperationError("文件不存在，无法重命名") from exc
        except OSError as exc:
            raise FileOperationError(str(exc)) from exc
        if not stat.S_ISREG(current.st_mode):
            raise FileOperationError("重命名源必须是普通媒体文件，不能是目录或符号链接")
        if expected is not None and not os.path.samestat(current, expected):
            raise FileOperationError("重命名源文件在重试期间发生变化")
        return current

    @staticmethod
    def _atomic_rename_no_replace(
        source_path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target_path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        """Use only native atomic rename variants that refuse an existing target."""

        source_path = os.fspath(source_path)
        target_path = os.fspath(target_path)
        for path in (source_path, target_path):
            nul = b"\0" if isinstance(path, bytes) else "\0"
            if nul in path:
                raise FileOperationError("重命名路径不能包含 NUL 字节")
        if os.name == "nt":
            os.rename(source_path, target_path)
            return
        if sys.platform.startswith(("linux", "freebsd")):
            function_name, flag = "renameat2", 1  # RENAME/AT_RENAME_NOREPLACE
        elif sys.platform == "darwin":
            function_name, flag = "renamex_np", 4  # RENAME_EXCL
        else:
            raise FileOperationError("当前平台不支持原子无覆盖重命名")
        try:
            function = getattr(ctypes.CDLL(None, use_errno=True), function_name)
        except (AttributeError, OSError) as exc:
            raise FileOperationError("当前平台不支持原子无覆盖重命名") from exc
        encoded_source = os.fsencode(source_path)
        encoded_target = os.fsencode(target_path)
        function.restype = ctypes.c_int
        if function_name == "renameat2":
            function.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            result = function(-100, encoded_source, -100, encoded_target, flag)
        else:
            function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
            result = function(encoded_source, encoded_target, flag)
        if result == 0:
            return
        error_code = ctypes.get_errno()
        if error_code in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(error_code, os.strerror(error_code), target_path)
        raise OSError(error_code, os.strerror(error_code), target_path)

    @staticmethod
    def _rename_outcome_after_error(
        source_path: str,
        target_path: str,
        source_stat: os.stat_result,
    ) -> _RenameOutcome:
        def _matches_frozen_regular(candidate: os.stat_result) -> bool:
            return stat.S_ISREG(candidate.st_mode) and os.path.samestat(
                candidate, source_stat
            )

        def _target_is_absent() -> bool:
            try:
                os.lstat(target_path)
            except FileNotFoundError:
                return True
            return False

        try:
            try:
                first_source = os.lstat(source_path)
            except FileNotFoundError:
                if not _matches_frozen_regular(os.lstat(target_path)):
                    return _RenameOutcome.UNKNOWN
                try:
                    os.lstat(source_path)
                except FileNotFoundError:
                    pass
                else:
                    return _RenameOutcome.UNKNOWN
                if _matches_frozen_regular(os.lstat(target_path)):
                    return _RenameOutcome.COMPLETED
                return _RenameOutcome.UNKNOWN
            if not _matches_frozen_regular(first_source) or not _target_is_absent():
                return _RenameOutcome.UNKNOWN
            second_source = os.lstat(source_path)
            if not _matches_frozen_regular(second_source) or not _target_is_absent():
                return _RenameOutcome.UNKNOWN
            return _RenameOutcome.NOT_COMPLETED
        except BaseException:
            return _RenameOutcome.UNKNOWN

    @staticmethod
    def _unknown_rename_error(primary: OSError | FileOperationError) -> FileOperationError:
        try:
            primary.add_note("重命名失败后的状态对账无法确认；保留原始异常")
        except BaseException:
            pass
        if isinstance(primary, FileOperationError):
            return primary
        try:
            message = str(primary)
        except BaseException:
            message = "重命名失败后的状态对账无法确认"
        return FileOperationError(message)

    def rename_media(
        self,
        video: VideoItem,
        new_title: str,
        save_dir: str,
    ) -> tuple[str, str]:
        old_path = video.local_path
        source_stat = self._regular_rename_source_stat(old_path)
        ext = os.path.splitext(old_path)[1]
        safe_name = sanitize_filename(new_title) + ext
        new_path = os.path.join(save_dir, safe_name)

        target_state = self._rename_target_state(old_path, new_path)
        if target_state == "same":
            return old_path, new_path
        if target_state == "conflict":
            raise FileOperationError(f"文件名 '{safe_name}' 已存在")

        def _native_rename() -> tuple[str, str]:
            self._regular_rename_source_stat(old_path, source_stat)
            current_state = self._rename_target_state(old_path, new_path)
            if current_state == "same":
                return old_path, new_path
            if current_state == "conflict":
                raise FileOperationError(f"文件名 '{safe_name}' 已存在")
            # This closes mutations inside preflight. An external actor may still
            # replace the source after this final probe, as at any successful syscall boundary.
            self._regular_rename_source_stat(old_path, source_stat)
            try:
                self._atomic_rename_no_replace(old_path, new_path)
            except FileExistsError as exc:
                raise FileOperationError(f"文件名 '{safe_name}' 已存在") from exc
            except (OSError, FileOperationError) as exc:
                outcome = self._rename_outcome_after_error(old_path, new_path, source_stat)
                if outcome is _RenameOutcome.COMPLETED:
                    return old_path, new_path
                if outcome is _RenameOutcome.UNKNOWN:
                    domain_error = self._unknown_rename_error(exc)
                    if domain_error is exc:
                        raise
                    raise domain_error from exc
                raise
            return old_path, new_path

        result = self._run_file_mutation_with_retry(
            _native_rename,
            error_message="重命名文件失败",
            required=True,
        )
        if result is None:
            raise FileOperationError("重命名文件失败")
        return result

    def rename_media_authorized(
        self,
        video: VideoItem,
        new_title: str,
        save_dir: str,
        *,
        approved_root_grants: Iterable[ApprovedRootGrant],
    ) -> tuple[str, str]:
        """Rename the path-linearized source and validate its authoritative target.

        Ordinary success keeps the legacy two-path tuple.  Any error that may
        follow an OS commit raises :class:`MediaRenameOutcomeError` with a
        non-retryable reconciliation receipt.
        """
        old_path = os.path.abspath(video.local_path)
        extension = os.path.splitext(old_path)[1]
        safe_name = sanitize_filename(new_title) + extension
        new_path = os.path.abspath(os.path.join(save_dir, safe_name))
        committed = False
        try:
            with self._path_policy.lease_approved_root_grants(
                approved_root_grants
            ) as roots:
                roots.assert_bound()
                with ExitStack() as stack:
                    source = stack.enter_context(roots.bind_child(old_path))
                    target = stack.enter_context(roots.bind_child(new_path))
                    source_stat = source.stat()
                    if not stat.S_ISREG(source_stat.st_mode):
                        raise FileOperationError(
                            "重命名源必须是普通媒体文件，不能是目录或符号链接"
                        )
                    if old_path == new_path:
                        return old_path, new_path
                    try:
                        target_stat = target.stat()
                    except FileNotFoundError:
                        target_stat = None
                    if target_stat is not None:
                        same_entry = os.path.samestat(source_stat, target_stat)
                        case_only_alias = (
                            os.name == "nt"
                            and same_entry
                            and source.parent.root == target.parent.root
                            and source.name.casefold() == target.name.casefold()
                        )
                        if not case_only_alias:
                            raise FileOperationError(f"文件名 '{safe_name}' 已存在")
                        roots.assert_bound()
                        try:
                            os.rename(source.absolute_path, target.absolute_path)
                        except FileExistsError as exc:
                            raise FileOperationError(
                                f"文件名 '{safe_name}' 已存在"
                            ) from exc
                        except BaseException as exc:
                            self._raise_authorized_rename_outcome(
                                old_path,
                                new_path,
                                MediaRenameStatus.OUTCOME_UNCERTAIN,
                                "授权媒体重命名结果不确定，需要状态对账",
                                cause=exc,
                            )
                    else:
                        try:
                            source.rename_no_replace(target)
                        except FileExistsError as exc:
                            raise FileOperationError(
                                f"文件名 '{safe_name}' 已存在"
                            ) from exc
                        except BaseException as exc:
                            self._raise_authorized_rename_outcome(
                                old_path,
                                new_path,
                                MediaRenameStatus.OUTCOME_UNCERTAIN,
                                "授权媒体重命名结果不确定，需要状态对账",
                                cause=exc,
                            )
                    committed = True
                    self._postcheck_authorized_rename(
                        roots,
                        target,
                        old_path,
                        new_path,
                    )
            return old_path, new_path
        except MediaRenameOutcomeError:
            raise
        except BaseException as exc:
            if committed:
                self._raise_authorized_rename_outcome(
                    old_path,
                    new_path,
                    MediaRenameStatus.COMMITTED_AUTHORITY_UNCERTAIN,
                    "媒体重命名已提交，但授权状态复核失败",
                    cause=exc,
                )
            raise

    @staticmethod
    def _safe_rename_receipt_name(path: str) -> str:
        name = os.path.basename(path)
        safe = "".join(
            character
            for character in name
            if not unicodedata.category(character).startswith("C")
        )
        return safe[:255] or "<media>"

    @classmethod
    def _rename_receipt(
        cls,
        old_path: str,
        new_path: str,
        status: MediaRenameStatus,
    ) -> MediaRenameReceipt:
        return MediaRenameReceipt(
            source_name=cls._safe_rename_receipt_name(old_path),
            target_name=cls._safe_rename_receipt_name(new_path),
            status=status,
        )

    @staticmethod
    def _attach_rename_receipt_best_effort(
        primary: BaseException,
        receipt: MediaRenameReceipt,
    ) -> None:
        try:
            object.__setattr__(primary, "media_rename_receipt", receipt)
        except BaseException:
            pass
        try:
            add_note = object.__getattribute__(primary, "add_note")
        except BaseException:
            return
        if not callable(add_note):
            return
        try:
            add_note(f"media rename outcome: {receipt.status.value}")
        except BaseException:
            return

    @classmethod
    def _raise_authorized_rename_outcome(
        cls,
        old_path: str,
        new_path: str,
        status: MediaRenameStatus,
        message: str,
        *,
        cause: BaseException,
    ) -> NoReturn:
        receipt = cls._rename_receipt(old_path, new_path, status)
        if not isinstance(cause, Exception):
            cls._attach_rename_receipt_best_effort(cause, receipt)
            raise cause
        raise MediaRenameOutcomeError(message, receipt) from cause

    @classmethod
    def _postcheck_authorized_rename(
        cls,
        roots: ApprovedRootsLease,
        target: ApprovedChildPath,
        old_path: str,
        new_path: str,
    ) -> None:
        try:
            roots.assert_bound()
            target_stat = target.stat()
            roots.assert_bound()
        except BaseException as exc:
            cls._raise_authorized_rename_outcome(
                old_path,
                new_path,
                MediaRenameStatus.COMMITTED_AUTHORITY_UNCERTAIN,
                "媒体重命名已提交，但目标授权状态无法确认",
                cause=exc,
            )
        if not stat.S_ISREG(target_stat.st_mode):
            receipt = cls._rename_receipt(
                old_path,
                new_path,
                MediaRenameStatus.COMMITTED_TARGET_INVALID,
            )
            raise MediaRenameOutcomeError(
                "媒体重命名已提交，但权威目标不是普通文件",
                receipt,
            )

    @classmethod
    def _owned_empty_subdirectory_candidates(
        cls,
        video: VideoItem,
        file_path: str,
        temp_paths: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Freeze every task-owned directory that ``delete_media`` may rmdir."""

        meta = video.meta if isinstance(getattr(video, "meta", None), dict) else {}
        raw_folder_name = str(meta.get("folder_name") or "").strip()
        owns_subdirectory = bool(
            raw_folder_name
            and (
                meta.get("use_subdir")
                or meta.get("is_mix")
                or meta.get("is_gallery")
                or str(meta.get("content_type") or "") == "gallery"
            )
        )
        if not owns_subdirectory:
            return ()

        expected_name = sanitize_filename(raw_folder_name)
        raw_save_directory = str(meta.get("save_directory") or "").strip()
        candidates: list[Path] = []
        seen: set[str] = set()

        def add_candidate(path: Path) -> None:
            normalized = os.path.normcase(os.path.abspath(os.fspath(path)))
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(path)

        if raw_save_directory:
            add_candidate(Path(os.path.abspath(os.path.expanduser(raw_save_directory))))
        for raw_path in (file_path, *temp_paths):
            if raw_path:
                normalized_path = Path(os.path.abspath(os.path.expanduser(raw_path)))
                add_candidate(normalized_path.parent)

        return tuple(
            os.fspath(candidate)
            for candidate in candidates
            if os.path.normcase(candidate.name) == os.path.normcase(expected_name)
        )

    @classmethod
    def _remove_owned_empty_subdirectories(cls, candidates: tuple[str, ...]) -> bool:
        """Remove only the frozen non-symlink directories from a mutation plan."""

        removed = False
        for raw_candidate in candidates:
            candidate = Path(raw_candidate)
            try:
                if candidate.is_symlink():
                    continue
                candidate.rmdir()
                removed = True
            except (FileNotFoundError, OSError):
                continue
        return removed

    def build_delete_media_plan(self, video: VideoItem) -> MediaDeleteMutationPlan:
        """Enumerate a read-only, reusable plan for every delete side effect."""

        raw_file_path = str(getattr(video, "local_path", "") or "")
        file_path = os.path.abspath(raw_file_path) if raw_file_path else ""
        raw_temp_paths = self._iter_download_temp_paths(
            video,
            file_path,
        ) + self._iter_bilibili_temp_paths(video, file_path)
        temp_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in raw_temp_paths:
            absolute = os.path.abspath(raw_path)
            normalized = self._normalized_abs(absolute)
            if normalized in seen:
                continue
            seen.add(normalized)
            temp_paths.append(absolute)
        frozen_temp_paths = tuple(temp_paths)
        return MediaDeleteMutationPlan(
            file_path=file_path,
            temp_paths=frozen_temp_paths,
            owned_directories=self._owned_empty_subdirectory_candidates(
                video,
                file_path,
                frozen_temp_paths,
            ),
        )

    def delete_media(
        self,
        video: VideoItem,
        *,
        mutation_plan: MediaDeleteMutationPlan | None = None,
    ) -> bool:
        """删除媒体最终文件，并联动清理本任务可能留下的下载临时文件。"""
        plan = mutation_plan or self.build_delete_media_plan(video)
        deleted = self._delete_file(plan.file_path, required=True)
        for temp_path in plan.temp_paths:
            deleted = self._delete_file(temp_path, required=False) or deleted
        deleted = self._remove_owned_empty_subdirectories(plan.owned_directories) or deleted
        return deleted

    @classmethod
    def _unlink_explicit_approved_file(
        cls,
        roots: ApprovedRootsLease,
        file_path: str,
    ) -> bool:
        """Delete the current regular file at an explicitly requested path.

        This intentionally has path-linearized semantics.  Derived temp and
        directory cleanup paths do not have an exact-generation token and must
        never use this helper.
        """
        if not file_path:
            return False
        entered_child = False
        committed = False
        try:
            with roots.bind_child(file_path) as child:
                entered_child = True
                try:
                    value = child.stat()
                except FileNotFoundError:
                    return False
                if not stat.S_ISREG(value.st_mode):
                    raise OSError("approved deletion target is not a regular file")
                try:
                    child.unlink()
                except BaseException as exc:
                    cls._raise_authorized_delete_outcome(
                        file_path,
                        MediaDeleteStatus.OUTCOME_UNCERTAIN,
                        "approved media delete outcome is uncertain and must be reconciled",
                        cause=exc,
                    )
                committed = True
                try:
                    roots.assert_bound()
                    try:
                        replacement = child.stat()
                    except FileNotFoundError:
                        replacement = None
                    roots.assert_bound()
                except BaseException as exc:
                    cls._raise_authorized_delete_outcome(
                        file_path,
                        MediaDeleteStatus.COMMITTED_AUTHORITY_UNCERTAIN,
                        "approved media delete committed but authority could not be revalidated",
                        cause=exc,
                    )
                if replacement is not None:
                    receipt = cls._delete_receipt(
                        file_path,
                        MediaDeleteStatus.COMMITTED_TARGET_REPLACED,
                    )
                    raise MediaDeleteOutcomeError(
                        "approved media delete committed but the path now names a later generation",
                        receipt,
                    )
                return True
        except MediaDeleteOutcomeError:
            raise
        except BaseException as exc:
            if committed:
                cls._raise_authorized_delete_outcome(
                    file_path,
                    MediaDeleteStatus.COMMITTED_AUTHORITY_UNCERTAIN,
                    "approved media delete committed but authority cleanup failed",
                    cause=exc,
                )
            if isinstance(exc, FileNotFoundError) and not entered_child:
                return False
            if isinstance(exc, PermissionError):
                raise
            if isinstance(exc, OSError):
                raise FileOperationError(
                    "approved media file could not be deleted safely"
                ) from exc
            raise

    @classmethod
    def _delete_receipt(
        cls,
        file_path: str,
        status: MediaDeleteStatus,
    ) -> MediaDeleteReceipt:
        return MediaDeleteReceipt(
            target_name=cls._safe_rename_receipt_name(file_path),
            status=status,
        )

    @staticmethod
    def _attach_delete_receipt_best_effort(
        primary: BaseException,
        receipt: MediaDeleteReceipt,
    ) -> None:
        try:
            object.__setattr__(primary, "media_delete_receipt", receipt)
        except BaseException:
            pass
        try:
            add_note = object.__getattribute__(primary, "add_note")
        except BaseException:
            return
        if not callable(add_note):
            return
        try:
            add_note(f"media delete outcome: {receipt.status.value}")
        except BaseException:
            return

    @classmethod
    def _raise_authorized_delete_outcome(
        cls,
        file_path: str,
        status: MediaDeleteStatus,
        message: str,
        *,
        cause: BaseException,
    ) -> NoReturn:
        receipt = cls._delete_receipt(file_path, status)
        if not isinstance(cause, Exception):
            cls._attach_delete_receipt_best_effort(cause, receipt)
            raise cause
        raise MediaDeleteOutcomeError(message, receipt) from cause

    def delete_media_authorized(
        self,
        video: VideoItem,
        *,
        mutation_plan: MediaDeleteMutationPlan | None = None,
        approved_root_grants: Iterable[ApprovedRootGrant],
    ) -> bool:
        """Delete the explicit current media path and retain derived cleanup.

        ``temp_paths`` and ``owned_directories`` are only names captured in a
        plan.  Without exact-generation authority they must be left to residue
        recovery so a later file or directory generation is never removed.
        """
        plan = mutation_plan or self.build_delete_media_plan(video)
        committed = False
        try:
            with self._path_policy.lease_approved_root_grants(
                approved_root_grants
            ) as roots:
                roots.assert_bound()
                deleted = self._unlink_explicit_approved_file(
                    roots,
                    plan.file_path,
                )
                committed = deleted
                # The plan freezes names, not filesystem generations.  Until the
                # shared capability can prove exact-generation deletion, a Web
                # request must leave temp files and owned directories for the
                # recovery/residue workflow instead of deleting a later successor.
                roots.assert_bound()
            return deleted
        except MediaDeleteOutcomeError:
            raise
        except BaseException as exc:
            if committed:
                self._raise_authorized_delete_outcome(
                    plan.file_path,
                    MediaDeleteStatus.COMMITTED_AUTHORITY_UNCERTAIN,
                    "approved media delete committed but root authority cleanup failed",
                    cause=exc,
                )
            raise
