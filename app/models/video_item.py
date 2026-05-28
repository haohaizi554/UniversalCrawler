"""Shared media item model for spiders, UI and downloaders."""

from dataclasses import dataclass, field
from uuid import uuid4

from app.utils.filenames import build_media_filename


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
        """获取 `safe_filename` 对应的数据或状态，供 `VideoItem` 使用。"""
        return build_media_filename(self.title or f"{self.source}_{self.id}", self.source, extension, self.meta)

    def update_from_dict(self, data: dict):
        """更新 `from_dict` 对应的状态或数据内容，供 `VideoItem` 使用。"""
        for key, value in data.items():
            if key not in self.UPDATABLE_FIELDS:
                continue
            if key == "meta" and not isinstance(value, dict):
                continue
            setattr(self, key, value)
