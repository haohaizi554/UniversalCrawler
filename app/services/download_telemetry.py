"""Per-video download speed / ETA telemetry for GUI, Web and future analytics."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from app.models import VideoItem

@dataclass(frozen=True)
class DownloadProgressSnapshot:
    """Immutable snapshot of one video's live download metrics."""

    video_id: str
    progress: int
    speed_bps: int
    speed: str
    bytes_downloaded: int
    bytes_total: int
    eta_seconds: int | None
    eta: str
    remaining_time: str
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class DownloadTelemetryService:
    """Track per-video throughput and ETA from progress callbacks."""

    MIN_SAMPLE_INTERVAL_SECONDS = 0.2

    def __init__(self) -> None:
        self._last_sample: dict[str, tuple[int, float, int]] = {}

    def clear(self, video_id: str) -> None:
        self._last_sample.pop(video_id, None)

    @staticmethod
    def format_speed(bps: int) -> str:
        if bps <= 0:
            return "0 B/s"
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        value = float(bps)
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        if index == 0:
            return f"{int(value)} {units[index]}"
        return f"{value:.1f} {units[index]}"

    @staticmethod
    def format_duration(seconds: int | None) -> str:
        if seconds is None or seconds < 0:
            return "--"
        if seconds >= 3600:
            hours, rem = divmod(seconds, 3600)
            minutes, secs = divmod(rem, 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        minutes, secs = divmod(max(0, seconds), 60)
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def resolve_bytes_total(video: VideoItem, *, progress: int, bytes_downloaded: int) -> int:
        meta = video.meta or {}
        size_bytes = int(meta.get("size_bytes", 0) or 0)
        if size_bytes > 0:
            return size_bytes
        size_mb = float(meta.get("size_mb", 0) or 0)
        if size_mb > 0:
            return int(size_mb * 1024 * 1024)
        if 0 < progress < 100 and bytes_downloaded > 0:
            return int(bytes_downloaded * 100 / progress)
        return 0

    @staticmethod
    def resolve_bytes_downloaded(video: VideoItem, *, progress: int, bytes_total: int) -> int:
        meta = video.meta or {}
        explicit = int(meta.get("bytes_downloaded", 0) or 0)
        if explicit > 0:
            return explicit
        if bytes_total > 0 and progress > 0:
            return int(bytes_total * progress / 100)
        path = video.local_path
        if path:
            try:
                import os

                if os.path.exists(path):
                    return os.path.getsize(path)
            except OSError:
                pass
        return 0

    def record(
        self,
        video: VideoItem,
        *,
        progress: int,
        bytes_downloaded: int | None = None,
        bytes_total: int | None = None,
        now: float | None = None,
    ) -> DownloadProgressSnapshot:
        now = time.monotonic() if now is None else now
        normalized_progress = max(0, min(100, int(progress)))
        if bytes_total is None:
            bytes_total = self.resolve_bytes_total(
                video,
                progress=normalized_progress,
                bytes_downloaded=bytes_downloaded or 0,
            )
        if bytes_downloaded is None:
            bytes_downloaded = self.resolve_bytes_downloaded(
                video,
                progress=normalized_progress,
                bytes_total=bytes_total,
            )

        speed_bps = 0
        last = self._last_sample.get(video.id)
        force_sample = normalized_progress >= 100
        if last is not None:
            last_bytes, last_at, last_bps = last
            elapsed = now - last_at
            if (elapsed >= self.MIN_SAMPLE_INTERVAL_SECONDS or force_sample) and elapsed > 0 and bytes_downloaded >= last_bytes:
                speed_bps = max(0, int((bytes_downloaded - last_bytes) / elapsed))
            elif elapsed < self.MIN_SAMPLE_INTERVAL_SECONDS:
                speed_bps = last_bps

        if speed_bps <= 0 and last is not None:
            speed_bps = last[2]

        if last is None or now - last[1] >= self.MIN_SAMPLE_INTERVAL_SECONDS or force_sample:
            self._last_sample[video.id] = (bytes_downloaded, now, speed_bps)

        eta_seconds: int | None = None
        if speed_bps > 0 and bytes_total > bytes_downloaded:
            eta_seconds = int((bytes_total - bytes_downloaded) / speed_bps)
        elif normalized_progress >= 100:
            eta_seconds = 0

        eta_label = self.format_duration(eta_seconds)
        snapshot = DownloadProgressSnapshot(
            video_id=video.id,
            progress=normalized_progress,
            speed_bps=speed_bps,
            speed=self.format_speed(speed_bps),
            bytes_downloaded=bytes_downloaded,
            bytes_total=bytes_total,
            eta_seconds=eta_seconds,
            eta=eta_label,
            remaining_time=eta_label,
            updated_at=now,
        )
        self.apply_to_meta(video, snapshot)
        return snapshot

    @staticmethod
    def apply_to_meta(video: VideoItem, snapshot: DownloadProgressSnapshot) -> None:
        meta = video.meta
        meta["speed_bps"] = snapshot.speed_bps
        meta["speed"] = snapshot.speed
        meta["eta"] = snapshot.eta
        meta["remaining_time"] = snapshot.remaining_time
        meta["bytes_downloaded"] = snapshot.bytes_downloaded
        meta["bytes_total"] = snapshot.bytes_total
        meta["eta_seconds"] = snapshot.eta_seconds
        meta["telemetry_updated_at"] = snapshot.updated_at
        trend = list(meta.get("speed_trend") or [])
        trend.append(snapshot.speed_bps)
        meta["speed_trend"] = trend[-60:]

    def lookup(self, video_id: str) -> DownloadProgressSnapshot | None:
        last = self._last_sample.get(video_id)
        if last is None:
            return None
        bytes_downloaded, updated_at, speed_bps = last
        return DownloadProgressSnapshot(
            video_id=video_id,
            progress=0,
            speed_bps=speed_bps,
            speed=self.format_speed(speed_bps),
            bytes_downloaded=bytes_downloaded,
            bytes_total=0,
            eta_seconds=None,
            eta="--",
            remaining_time="--",
            updated_at=updated_at,
        )

_DEFAULT_TELEMETRY = DownloadTelemetryService()

def get_download_telemetry_service() -> DownloadTelemetryService:
    return _DEFAULT_TELEMETRY
