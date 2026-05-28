"""服务模块，负责 `app/services/file_service.py` 对应的业务支撑能力。"""

import os
from dataclasses import dataclass

from app.exceptions import FileOperationError, MediaScanError
from app.models import VideoItem
from app.utils import sanitize_filename


@dataclass
class ScanResult:
    """封装 `ScanResult` 在 `app/services/file_service.py` 中承担的核心逻辑。"""
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

            all_files = [
                f for f in os.listdir(directory)
                if f.lower().endswith(self.all_media_extensions)
            ]
            all_files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)

            original_count = len(all_files)
            truncated = original_count > max_scan_count
            if truncated:
                # UI 只展示最近一部分文件，避免首轮把超大目录全部塞进表格导致卡顿。
                all_files = all_files[:max_scan_count]

            items: list[VideoItem] = []
            video_count = 0
            image_count = 0

            for filename in all_files:
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
        """执行 `rename_media` 对应的业务逻辑，供 `MediaLibraryService` 使用。"""
        if not os.path.exists(video.local_path):
            raise FileOperationError("文件不存在，无法重命名")

        old_path = video.local_path
        ext = os.path.splitext(old_path)[1]
        safe_name = sanitize_filename(new_title) + ext
        new_path = os.path.join(save_dir, safe_name)

        if os.path.exists(new_path) and new_path.lower() != old_path.lower():
            # Windows 下文件名大小写不敏感，因此需要按 lower() 比较是否真的是同一路径。
            raise FileOperationError(f"文件名 '{safe_name}' 已存在")

        try:
            os.rename(old_path, new_path)
            return old_path, new_path
        except OSError as exc:
            raise FileOperationError(str(exc)) from exc

    def delete_media(self, video: VideoItem) -> bool:
        """删除 `media` 对应的对象、文件或记录，供 `MediaLibraryService` 使用。"""
        file_path = video.local_path
        if not file_path or not os.path.exists(file_path):
            return False
        try:
            os.remove(file_path)
            return True
        except OSError as exc:
            raise FileOperationError(str(exc)) from exc
