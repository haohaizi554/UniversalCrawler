"""跨前端共享的领域状态模型与标签转换工具。"""

from __future__ import annotations

from enum import Enum

class VideoStatus(str, Enum):
    """GUI、CLI 与 Web 共用的统一下载/媒体状态。"""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    LOCAL = "local"
    TIMED_OUT = "timed_out"

    @property
    def label(self) -> str:
        return VIDEO_STATUS_LABELS[self]

VIDEO_STATUS_LABELS: dict[VideoStatus, str] = {
    VideoStatus.PENDING: "⏳ 等待中",
    VideoStatus.DOWNLOADING: "⏳ 下载中...",
    VideoStatus.COMPLETED: "✅ 完成",
    VideoStatus.FAILED: "❌ 失败",
    VideoStatus.LOCAL: "✅ 本地",
    VideoStatus.TIMED_OUT: "❌ 超时",
}

VIDEO_STATUS_BY_LABEL: dict[str, VideoStatus] = {
    label: status for status, label in VIDEO_STATUS_LABELS.items()
}

class CrawlStatus(str, Enum):
    """统一的爬虫生命周期状态。"""

    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    FINISHED = "finished"
    FAILED = "failed"

def video_status_label(status: VideoStatus | str) -> str:
    """把枚举或旧版字符串状态转换为界面标签。"""
    if isinstance(status, VideoStatus):
        return status.label
    return VIDEO_STATUS_LABELS.get(VIDEO_STATUS_BY_LABEL.get(str(status), VideoStatus.PENDING), str(status))

def parse_video_status(status: VideoStatus | str) -> VideoStatus | None:
    """把枚举或旧版标签解析为统一的 VideoStatus。"""
    if isinstance(status, VideoStatus):
        return status
    raw = str(status)
    if raw in VIDEO_STATUS_BY_LABEL:
        return VIDEO_STATUS_BY_LABEL[raw]
    try:
        return VideoStatus(raw)
    except ValueError:
        return None
