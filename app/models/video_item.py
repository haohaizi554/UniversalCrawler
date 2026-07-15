"""定义采集器、UI 与下载器共享的媒体项模型。"""

import threading
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from app.models.download_context import DownloadContext
from app.utils.filenames import build_media_filename

@dataclass
class VideoItem:
    """表示一个待下载或已完成的媒体项。"""

    UPDATABLE_FIELDS = {"url", "title", "source", "status", "progress", "local_path", "meta"}

    url: str
    title: str
    source: str
    id: str = field(init=False)
    status: str = "waiting"
    progress: int = 0
    local_path: str = ""
    meta: dict = field(default_factory=dict)
    _meta_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

    def __post_init__(self):
        # uuid4 避免高并发下时间戳+随机数方案的碰撞风险。
        self.id = uuid4().hex
        if self.title:
            self.title = self.title.strip()

    def get_safe_filename(self, extension: str = ".mp4") -> str:
        
        return build_media_filename(self.title or f"{self.source}_{self.id}", self.source, extension, self.meta)

    def build_download_context(self) -> DownloadContext:
        """在 meta 锁内构建规范化下载上下文。"""
        with self.meta_guard():
            return DownloadContext.from_meta(self.meta)

    def meta_guard(self) -> threading.RLock:
        """返回 worker 写入与 UI 快照共用的 meta 锁，避免读取半更新状态。"""
        return self._meta_lock

    def __deepcopy__(self, memo: dict) -> "VideoItem":
        """复制数据但不共享 meta 锁，避免快照反向阻塞原对象。"""
        existing = memo.get(id(self))
        if existing is not None:
            return existing
        with self.meta_guard():
            copied = type(self)(
                url=deepcopy(self.url, memo),
                title=deepcopy(self.title, memo),
                source=deepcopy(self.source, memo),
            )
            memo[id(self)] = copied
            copied.id = deepcopy(self.id, memo)
            copied.status = deepcopy(self.status, memo)
            copied.progress = deepcopy(self.progress, memo)
            copied.local_path = deepcopy(self.local_path, memo)
            copied.meta = deepcopy(self.meta, memo)
            return copied

    def merge_download_context(self, context: DownloadContext | None = None, **overrides) -> DownloadContext:
        """把规范化下载上下文合并回 ``meta``。"""
        with self.meta_guard():
            base_patch = (context or DownloadContext.from_meta(self.meta)).to_meta_patch()
            for key, value in overrides.items():
                if value is not None:
                    base_patch[key] = value
            merged = DownloadContext.from_meta(base_patch)
            self.meta.update(merged.to_meta_patch())
        return merged

    def update_from_dict(self, data: dict):
        """只接收白名单字段，避免外部 payload 写入任意属性。"""
        with self.meta_guard():
            for key, value in data.items():
                if key not in self.UPDATABLE_FIELDS:
                    continue
                if key == "meta" and not isinstance(value, dict):
                    continue
                setattr(self, key, value)

    def to_dict(self) -> dict:
        """在同一 meta 锁内生成跨入口快照，避免并发更新产生混合状态。"""
        with self.meta_guard():
            meta_snapshot = dict(self.meta) if self.meta else {}
            return {
                "id": self.id,
                "url": self.url,
                "title": self.title,
                "source": self.source,
                "status": self.status,
                "progress": self.progress,
                "local_path": self.local_path,
                "content_type": meta_snapshot.get("content_type", ""),
                "meta": meta_snapshot,
            }
