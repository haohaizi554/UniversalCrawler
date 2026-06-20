"""Shared media item model for spiders, UI and downloaders."""

from dataclasses import dataclass, field
from uuid import uuid4

from app.models.download_context import DownloadContext
from app.utils.filenames import build_media_filename

#视频媒体项的数据模型定义，统一封装 “待下载 / 已下载的视频项” 的数据结构和基础操作
@dataclass
class VideoItem:
    """Represents one queued or downloaded media item."""

    UPDATABLE_FIELDS = {"url", "title", "source", "status", "progress", "local_path", "meta"}

    url: str
    title: str
    source: str
    id: str = field(init=False)
    status: str = "waiting"
    progress: int = 0
    local_path: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        # uuid4 避免高并发下时间戳+随机数方案的碰撞风险。
        """在数据类初始化后补充派生字段和规范化处理，供 `VideoItem` 使用。"""
        self.id = uuid4().hex
        if self.title:
            self.title = self.title.strip()

    def get_safe_filename(self, extension: str = ".mp4") -> str:
        
        return build_media_filename(self.title or f"{self.source}_{self.id}", self.source, extension, self.meta)

    def build_download_context(self) -> DownloadContext:
        """Build a normalized download context from this item's metadata."""
        return DownloadContext.from_meta(self.meta)

    def merge_download_context(self, context: DownloadContext | None = None, **overrides) -> DownloadContext:
        """Merge normalized download context values back into ``meta``."""
        base_patch = (context or self.build_download_context()).to_meta_patch()
        for key, value in overrides.items():
            if value is not None:
                base_patch[key] = value
        merged = DownloadContext.from_meta(base_patch)
        self.meta.update(merged.to_meta_patch())
        return merged

    def update_from_dict(self, data: dict):
        """更新 `from_dict` 对应的状态或数据内容，供 `VideoItem` 使用。"""
        for key, value in data.items():
            if key not in self.UPDATABLE_FIELDS:
                continue
            if key == "meta" and not isinstance(value, dict):
                continue
            setattr(self, key, value)

    def to_dict(self) -> dict:
        """统一序列化方法：CLI/SDK/Web/Skill 四层共用，确保字段完全一致。

        与 GUI ApplicationController 的最终状态对齐：
        - status: ⏳ 等待中 / ⏳ 下载中... / ✅ 完成 / ❌ 失败
        - progress: 0-100
        - local_path: 最终本地文件路径
        """
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "source": self.source,
            "status": self.status,
            "progress": self.progress,
            "local_path": self.local_path,
            "content_type": self.meta.get("content_type", "") if self.meta else "",
            "meta": dict(self.meta) if self.meta else {},
        }
