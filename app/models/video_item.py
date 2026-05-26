"""Shared media item model for spiders, UI and downloaders."""

import random
import time
from dataclasses import dataclass, field

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
        # Use timestamp plus randomness to keep IDs unique under concurrency.
        self.id = f"{int(time.time() * 1000)}_{random.randint(100, 999)}"
        if self.title:
            self.title = self.title.strip()

    def get_safe_filename(self, extension: str = ".mp4") -> str:
        return build_media_filename(self.title or f"{self.source}_{self.id}", self.source, extension, self.meta)

    def update_from_dict(self, data: dict):
        for key, value in data.items():
            if key not in self.UPDATABLE_FIELDS:
                continue
            if key == "meta" and not isinstance(value, dict):
                continue
            setattr(self, key, value)
