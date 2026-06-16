"""Shared domain state models and label helpers."""

from __future__ import annotations

from enum import Enum


class VideoStatus(str, Enum):
    """Canonical download/media states shared by GUI, CLI and Web."""

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
    """Canonical spider lifecycle states."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    FINISHED = "finished"
    FAILED = "failed"


def video_status_label(status: VideoStatus | str) -> str:
    """Convert enum or legacy string status to the UI label form."""
    if isinstance(status, VideoStatus):
        return status.label
    return VIDEO_STATUS_LABELS.get(VIDEO_STATUS_BY_LABEL.get(str(status), VideoStatus.PENDING), str(status))


def parse_video_status(status: VideoStatus | str) -> VideoStatus | None:
    """Parse enum or legacy label into a canonical VideoStatus."""
    if isinstance(status, VideoStatus):
        return status
    raw = str(status)
    if raw in VIDEO_STATUS_BY_LABEL:
        return VIDEO_STATUS_BY_LABEL[raw]
    try:
        return VideoStatus(raw)
    except ValueError:
        return None
