"""Lightweight local media metadata probing for completed downloads."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.downloaders.external import ExternalToolRunner, FFmpegExternalTool, build_hidden_startupinfo
from app.debug_logger import debug_logger


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    duration: str = ""
    resolution: str = ""
    format: str = ""
    content_type: str = ""


@dataclass(frozen=True, slots=True)
class _CacheKey:
    path: str
    size: int
    mtime_ns: int


class MediaMetadataService:
    """Probe media metadata without blocking UI render paths."""

    DURATION_RE = re.compile(r"Duration:\s*(?P<clock>\d{2}:\d{2}:\d{2})(?:\.\d+)?")
    RESOLUTION_RE = re.compile(r"Video:.*?,\s*(?P<w>\d{2,5})x(?P<h>\d{2,5})(?:[,\s\[])")
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    EMPTY_RETRY_SECONDS = 5.0

    def __init__(
        self,
        *,
        ffprobe_resolver: Callable[[], str | None] | None = None,
        ffmpeg_resolver: Callable[[], str | None] | None = None,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        max_workers: int = 2,
    ) -> None:
        self._ffprobe_resolver = ffprobe_resolver or (
            lambda: ExternalToolRunner.resolve_executable("ffprobe.exe", "ffprobe", ["-version"])
        )
        self._ffmpeg_resolver = ffmpeg_resolver or FFmpegExternalTool.resolve_executable
        self._runner = runner or subprocess.run
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[_CacheKey, MediaMetadata]] = {}
        self._empty_cache: dict[str, tuple[_CacheKey, float]] = {}
        self._inflight: set[str] = set()
        self._shutdown = False
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers or 1)),
            thread_name_prefix="media-metadata-probe",
        )

    def cached(self, path: str | Path) -> MediaMetadata | None:
        key = self._cache_key(path)
        if key is None:
            return None
        with self._lock:
            cached = self._cache.get(key.path)
            if cached and cached[0] == key and self._has_useful_metadata(cached[1]):
                return cached[1]
        return None

    def ensure_probe(self, path: str | Path, callback: Callable[[MediaMetadata], None]) -> bool:
        key = self._cache_key(path)
        if key is None:
            return False
        with self._lock:
            if self._shutdown:
                return False
            cached = self._cache.get(key.path)
            if cached and cached[0] == key and self._has_useful_metadata(cached[1]):
                return False
            empty_cached = self._empty_cache.get(key.path)
            if empty_cached and empty_cached[0] == key and time.monotonic() - empty_cached[1] < self.EMPTY_RETRY_SECONDS:
                return False
            if key.path in self._inflight:
                return True
            self._inflight.add(key.path)

        def worker() -> None:
            try:
                try:
                    metadata = self.probe(key.path)
                except Exception as exc:  # pragma: no cover - defensive worker isolation
                    debug_logger.log_exception(
                        "MediaMetadataService",
                        "probe_worker_error",
                        exc,
                        context={"path": key.path},
                    )
                    metadata = MediaMetadata(format=Path(key.path).suffix.lstrip(".").upper(), content_type=self._content_type_for_path(key.path))
                should_callback = False
                with self._lock:
                    if not self._shutdown:
                        if self._has_useful_metadata(metadata):
                            self._cache[key.path] = (key, metadata)
                            self._empty_cache.pop(key.path, None)
                        else:
                            self._cache.pop(key.path, None)
                            self._empty_cache[key.path] = (key, time.monotonic())
                        should_callback = True
                if should_callback:
                    try:
                        callback(metadata)
                    except Exception as exc:
                        debug_logger.log_exception(
                            "MediaMetadataService",
                            "probe_callback_error",
                            exc,
                            context={"path": key.path},
                        )
            finally:
                with self._lock:
                    self._inflight.discard(key.path)

        try:
            self._executor.submit(worker)
        except RuntimeError as exc:
            with self._lock:
                self._inflight.discard(key.path)
            debug_logger.log_exception(
                "MediaMetadataService",
                "probe_submit_error",
                exc,
                context={"path": key.path},
            )
            return False
        return True

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._inflight.clear()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def is_probe_deferred(self, path: str | Path) -> bool:
        """Return true when a missing result is still being retried or throttled."""

        key = self._cache_key(path)
        if key is None:
            return False
        with self._lock:
            if key.path in self._inflight:
                return True
            empty_cached = self._empty_cache.get(key.path)
            return bool(
                empty_cached
                and empty_cached[0] == key
                and time.monotonic() - empty_cached[1] < self.EMPTY_RETRY_SECONDS
            )

    def probe(self, path: str | Path) -> MediaMetadata:
        path_text = str(path)
        metadata = self._probe_ffprobe(path_text)
        if self._is_complete_metadata(metadata):
            return metadata
        ffmpeg_metadata = self._probe_ffmpeg(path_text)
        metadata = self._merge_metadata(metadata, ffmpeg_metadata)
        if self._is_complete_metadata(metadata):
            return metadata
        image_metadata = self._probe_image_header(path_text)
        metadata = self._merge_metadata(metadata, image_metadata)
        if self._is_complete_metadata(metadata):
            return metadata
        shell_metadata = self._probe_windows_shell(path_text)
        metadata = self._merge_metadata(metadata, shell_metadata)
        if self._has_useful_metadata(metadata):
            return metadata
        debug_logger.log(
            component="MediaMetadataService",
            action="probe_empty",
            level="WARN",
            message="Local media metadata probe finished without usable duration or resolution",
            details={"path": path_text},
        )
        suffix = Path(path_text).suffix.lstrip(".").upper()
        return MediaMetadata(format=suffix, content_type=self._content_type_for_path(path_text))

    def _probe_ffprobe(self, path: str) -> MediaMetadata | None:
        executable = self._ffprobe_resolver()
        if not executable:
            return None
        try:
            completed = self._runner(
                [
                    executable,
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                startupinfo=build_hidden_startupinfo(),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return None
        return self.from_ffprobe_payload(payload, path=path)

    def _probe_ffmpeg(self, path: str) -> MediaMetadata | None:
        executable = self._ffmpeg_resolver()
        if not executable:
            return None
        try:
            completed = self._runner(
                [executable, "-i", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                startupinfo=build_hidden_startupinfo(),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return self.from_ffmpeg_output(completed.stderr or completed.stdout or "", path=path)

    @classmethod
    def from_ffprobe_payload(cls, payload: dict, *, path: str = "") -> MediaMetadata:
        streams = list(payload.get("streams") or [])
        video = cls._primary_video_stream(streams)
        image = cls._content_type_for_path(path) == "image"
        duration_value = (payload.get("format") or {}).get("duration") or video.get("duration")
        duration = cls.format_duration(duration_value)
        width = cls._as_int(video.get("width"))
        height = cls._as_int(video.get("height"))
        rotation = abs(cls._stream_rotation(video)) % 180
        if width and height and rotation == 90:
            width, height = height, width
        resolution = f"{width} x {height}" if width and height else ""
        suffix = Path(path).suffix.lstrip(".").upper()
        format_name = suffix or str((payload.get("format") or {}).get("format_name") or "").split(",")[0].upper()
        return MediaMetadata(
            duration="" if image else duration,
            resolution=resolution,
            format=format_name,
            content_type="image" if image else "video",
        )

    @classmethod
    def from_ffmpeg_output(cls, output: str, *, path: str = "") -> MediaMetadata:
        duration_match = cls.DURATION_RE.search(output or "")
        resolution_match = cls.RESOLUTION_RE.search(output or "")
        resolution = ""
        if resolution_match:
            resolution = f"{resolution_match.group('w')} x {resolution_match.group('h')}"
        return MediaMetadata(
            duration=duration_match.group("clock") if duration_match else "",
            resolution=resolution,
            format=Path(path).suffix.lstrip(".").upper(),
            content_type=cls._content_type_for_path(path),
        )

    def _probe_image_header(self, path: str) -> MediaMetadata | None:
        if self._content_type_for_path(path) != "image":
            return None
        try:
            data = Path(path).read_bytes()[:65536]
        except OSError:
            return None
        size = self._image_size_from_header(data)
        suffix = Path(path).suffix.lstrip(".").upper()
        return MediaMetadata(
            resolution=f"{size[0]} x {size[1]}" if size else "",
            format=suffix,
            content_type="image",
        )

    def _probe_windows_shell(self, path: str) -> MediaMetadata | None:
        if sys.platform != "win32":
            return None
        path_literal = str(path).replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop';"
            f"$p='{path_literal}';"
            "$shell=New-Object -ComObject Shell.Application;"
            "$folder=$shell.Namespace((Split-Path -LiteralPath $p -Parent));"
            "if($null -eq $folder){ throw 'folder not found' };"
            "$item=$folder.ParseName((Split-Path -LiteralPath $p -Leaf));"
            "if($null -eq $item){ throw 'item not found' };"
            "$props=[ordered]@{"
            "Duration=$item.ExtendedProperty('System.Media.Duration');"
            "Width=$item.ExtendedProperty('System.Video.FrameWidth');"
            "Height=$item.ExtendedProperty('System.Video.FrameHeight');"
            "ImageWidth=$item.ExtendedProperty('System.Image.HorizontalSize');"
            "ImageHeight=$item.ExtendedProperty('System.Image.VerticalSize')"
            "};"
            "$props | ConvertTo-Json -Compress"
        )
        try:
            completed = self._runner(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                startupinfo=build_hidden_startupinfo(),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return None
        return self.from_windows_shell_payload(payload, path=path)

    @classmethod
    def from_windows_shell_payload(cls, payload: dict, *, path: str = "") -> MediaMetadata:
        width = cls._as_int(payload.get("Width") or payload.get("width") or payload.get("ImageWidth"))
        height = cls._as_int(payload.get("Height") or payload.get("height") or payload.get("ImageHeight"))
        return MediaMetadata(
            duration=cls._format_windows_duration(payload.get("Duration") or payload.get("duration")),
            resolution=f"{width} x {height}" if width and height else "",
            format=Path(path).suffix.lstrip(".").upper(),
            content_type=cls._content_type_for_path(path),
        )

    @classmethod
    def _primary_video_stream(cls, streams: list[dict]) -> dict:
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        if not videos:
            return {}
        real_videos = [stream for stream in videos if not cls._is_attached_picture(stream)]
        candidates = real_videos or videos
        return next((stream for stream in candidates if cls._as_int(stream.get("width")) and cls._as_int(stream.get("height"))), candidates[0])

    @staticmethod
    def _is_attached_picture(stream: dict) -> bool:
        disposition = stream.get("disposition") or {}
        if str(disposition.get("attached_pic") or "0") not in {"", "0", "False", "false"}:
            return True
        tags = stream.get("tags") or {}
        return "attached pic" in " ".join(str(value).lower() for value in tags.values())

    @classmethod
    def _stream_rotation(cls, stream: dict) -> int:
        tags = stream.get("tags") or {}
        for key in ("rotate", "rotation"):
            value = cls._as_rotation(tags.get(key))
            if value is not None:
                return value
        for side_data in stream.get("side_data_list") or []:
            for key in ("rotation", "rotate"):
                value = cls._as_rotation(side_data.get(key))
                if value is not None:
                    return value
        return 0

    @staticmethod
    def _as_rotation(value) -> int | None:
        try:
            return int(round(float(str(value).strip())))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _image_size_from_header(cls, data: bytes) -> tuple[int, int] | None:
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:2] == b"\xff\xd8":
            return cls._jpeg_size(data)
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return cls._webp_size(data)
        return None

    @staticmethod
    def _jpeg_size(data: bytes) -> tuple[int, int] | None:
        index = 2
        sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                return None
            segment_length = int.from_bytes(data[index:index + 2], "big")
            if segment_length < 2 or index + segment_length > len(data):
                return None
            if marker in sof_markers and segment_length >= 7:
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return width, height
            index += segment_length
        return None

    @staticmethod
    def _webp_size(data: bytes) -> tuple[int, int] | None:
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return width, height
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height
        if chunk == b"VP8 " and len(data) >= 30:
            frame = data[20:]
            sync = frame.find(b"\x9d\x01\x2a")
            if sync >= 0 and sync + 7 < len(frame):
                width = int.from_bytes(frame[sync + 3:sync + 5], "little") & 0x3FFF
                height = int.from_bytes(frame[sync + 5:sync + 7], "little") & 0x3FFF
                return width, height
        return None

    @staticmethod
    def _has_useful_metadata(metadata: MediaMetadata | None) -> bool:
        if metadata is None:
            return False
        if metadata.content_type == "image":
            return bool(metadata.resolution)
        return bool(metadata.duration or metadata.resolution)

    @staticmethod
    def _is_complete_metadata(metadata: MediaMetadata | None) -> bool:
        if metadata is None:
            return False
        if metadata.content_type == "image":
            return bool(metadata.resolution)
        return bool(metadata.duration and metadata.resolution)

    @staticmethod
    def _merge_metadata(primary: MediaMetadata | None, fallback: MediaMetadata | None) -> MediaMetadata | None:
        if primary is None:
            return fallback
        if fallback is None:
            return primary
        return MediaMetadata(
            duration=primary.duration or fallback.duration,
            resolution=primary.resolution or fallback.resolution,
            format=primary.format or fallback.format,
            content_type=primary.content_type or fallback.content_type,
        )

    @staticmethod
    def format_duration(value) -> str:
        try:
            seconds = int(float(value or 0))
        except (TypeError, ValueError):
            return ""
        if seconds <= 0:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{secs:02}"

    @classmethod
    def _format_windows_duration(cls, value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        clock_match = re.match(r"^(?:(?P<days>\d+)\.)?(?P<hours>\d{1,2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})", text)
        if clock_match:
            days = int(clock_match.group("days") or 0)
            hours = int(clock_match.group("hours")) + days * 24
            minutes = int(clock_match.group("minutes"))
            seconds = int(clock_match.group("seconds"))
            return f"{hours:02}:{minutes:02}:{seconds:02}"
        try:
            number = float(text)
        except ValueError:
            return ""
        seconds = number / 10_000_000 if number > 1_000_000 else number
        return cls.format_duration(seconds)

    @classmethod
    def _content_type_for_path(cls, path: str) -> str:
        return "image" if Path(path).suffix.lower() in cls.IMAGE_EXTENSIONS else "video"

    @staticmethod
    def _as_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _cache_key(path: str | Path) -> _CacheKey | None:
        candidate = Path(path)
        try:
            stat = candidate.stat()
        except OSError:
            return None
        return _CacheKey(str(candidate), int(stat.st_size), int(stat.st_mtime_ns))
