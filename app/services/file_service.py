"""服务模块，负责 `app/services/file_service.py` 对应的业务支撑能力。"""

import heapq
import os
import time
from dataclasses import dataclass

from app.exceptions import FileOperationError, MediaScanError
from app.models import VideoItem
from app.utils import sanitize_filename

#本地媒体文件管理服务
@dataclass
class ScanResult:
    
    items: list[VideoItem]
    total_count: int
    video_count: int
    image_count: int
    truncated: bool = False
    original_count: int = 0

class MediaLibraryService:
    """本地媒体库服务，负责扫描、重命名、删除。"""

    def __init__(self, video_extensions: tuple[str, ...], image_extensions: tuple[str, ...]):
        """初始化当前实例并准备运行所需的状态，供 `MediaLibraryService` 使用。"""
        self.video_extensions = tuple(ext.lower() for ext in video_extensions)
        self.image_extensions = tuple(ext.lower() for ext in image_extensions)
        self.all_media_extensions = self.video_extensions + self.image_extensions

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

    def delete_media(self, video: VideoItem) -> bool:
        """删除 `media` 对应的对象、文件或记录，供 `MediaLibraryService` 使用。"""
        file_path = video.local_path
        if not file_path or not os.path.exists(file_path):
            return False
        last_error: OSError | None = None
        for attempt in range(3):
            try:
                os.remove(file_path)
                return True
            except PermissionError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                break
            except OSError as exc:
                raise FileOperationError(str(exc)) from exc
        raise FileOperationError(str(last_error) if last_error else "删除文件失败")
