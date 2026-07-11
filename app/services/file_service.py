"""服务模块，负责 `app/services/file_service.py` 对应的业务支撑能力。"""

import heapq
import os
import re
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.debug_logger import debug_logger
from app.exceptions import FileOperationError, MediaScanError
from app.models import VideoItem
from app.utils import sanitize_filename

# 本地媒体文件管理服务
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
    """Result of scanning exactly one directory during bounded recovery."""

    removed_count: int
    children: tuple[tuple[Path, int], ...]
    scanned_entries: int
    truncated: bool = False
    error: str = ""

class MediaLibraryService:
    """本地媒体库服务，负责扫描、重命名、删除。"""

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
        ".tmp",
        ".part",
        ".aria2",
        ".download",
        *BILIBILI_TEMP_SUFFIXES,
    )

    def __init__(self, video_extensions: tuple[str, ...], image_extensions: tuple[str, ...]):
        """初始化当前实例并准备运行所需的状态，供 `MediaLibraryService` 使用。"""
        self.video_extensions = tuple(ext.lower() for ext in video_extensions)
        self.image_extensions = tuple(ext.lower() for ext in image_extensions)
        self.all_media_extensions = self.video_extensions + self.image_extensions

    def _delete_file(self, file_path: str, *, required: bool) -> bool:
        """删除单个文件；required=True 时把失败传播给调用方，辅助临时文件则尽量清理。"""
        if not file_path or not os.path.exists(file_path):
            return False
        last_error: OSError | None = None
        for attempt in range(3):
            try:
                os.remove(file_path)
                return True
            except FileNotFoundError:
                return False
            except PermissionError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                break
            except OSError as exc:
                if required:
                    raise FileOperationError(str(exc)) from exc
                return False
        if required:
            raise FileOperationError(str(last_error) if last_error else "Failed to delete file")
        return False

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
        """Scan one directory only and return children for durable traversal."""
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
        """Bounded startup sweep for known temp names without walking arbitrary trees."""
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

    def rename_media(self, video: VideoItem, new_title: str, save_dir: str) -> tuple[str, str]:
        
        if not os.path.exists(video.local_path):
            raise FileOperationError("文件不存在，无法重命名")

        old_path = video.local_path
        ext = os.path.splitext(old_path)[1]
        safe_name = sanitize_filename(new_title) + ext
        new_path = os.path.join(save_dir, safe_name)

        if os.path.exists(new_path) and new_path.lower() != old_path.lower():
            # Windows 下文件名大小写不敏感，因此需要按 lower() 比较是否真的是同一路径。
            raise FileOperationError(f"文件名 '{safe_name}' 已存在")

        last_error: OSError | None = None
        for attempt in range(3):
            try:
                os.rename(old_path, new_path)
                return old_path, new_path
            except PermissionError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                break
            except OSError as exc:
                raise FileOperationError(str(exc)) from exc
        raise FileOperationError(str(last_error) if last_error else "重命名文件失败")

    @classmethod
    def _remove_owned_empty_subdirectory(
        cls,
        video: VideoItem,
        file_path: str,
        temp_paths: list[str],
    ) -> bool:
        """Remove an empty collection/gallery folder without walking upward."""
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
            return False

        expected_name = sanitize_filename(raw_folder_name)
        raw_save_directory = str(meta.get("save_directory") or "").strip()
        candidates: set[Path] = set()
        if raw_save_directory:
            candidates.add(Path(os.path.abspath(os.path.expanduser(raw_save_directory))))
        for raw_path in (file_path, *temp_paths):
            if raw_path:
                # abspath normalizes `..` without dereferencing symlinks. Using
                # Path.resolve here would turn a guarded link into its target
                # before the is_symlink check below.
                normalized_path = Path(os.path.abspath(os.path.expanduser(raw_path)))
                candidates.add(normalized_path.parent)

        removed = False
        for candidate in candidates:
            if os.path.normcase(candidate.name) != os.path.normcase(expected_name):
                continue
            try:
                if candidate.is_symlink():
                    continue
                # rmdir is intentionally non-recursive: any unrelated file or
                # nested directory keeps the collection folder intact.
                candidate.rmdir()
                removed = True
            except (FileNotFoundError, OSError):
                continue
        return removed

    def delete_media(self, video: VideoItem) -> bool:
        """删除媒体最终文件，并联动清理本任务可能留下的下载临时文件。"""
        file_path = video.local_path
        temp_paths = self._iter_download_temp_paths(video, file_path) + self._iter_bilibili_temp_paths(video, file_path)
        deleted = self._delete_file(file_path, required=True)
        for temp_path in temp_paths:
            deleted = self._delete_file(temp_path, required=False) or deleted
        deleted = self._remove_owned_empty_subdirectory(video, file_path, temp_paths) or deleted
        return deleted
