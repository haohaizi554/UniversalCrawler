"""Explicit download-time context derived from VideoItem.meta."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class DownloadContext:
    """Normalized download context for strategy, worker and downloader flows."""

    trace_id: str | None = None
    download_strategy: str | None = None
    proxy: str | None = None
    ua: str | None = None
    referer: str | None = None
    cookie: str | None = None
    cookies: dict[str, str] = field(default_factory=dict)
    content_type: str | None = None
    media_label: str | None = None
    folder_name: str | None = None
    preferred_filename: str | None = None
    aweme_id: str | None = None
    bvid: str | None = None
    cid: str | None = None
    audio_url: str | None = None
    images_data: list[dict[str, str]] = field(default_factory=list)
    duration: int | float | None = None
    size_mb: int | float | None = None
    is_gallery: bool = False
    is_mix: bool = False
    use_subdir: bool = False

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"", "0", "false", "no", "off", "none", "null"}:
                return False
            if normalized in {"1", "true", "yes", "on"}:
                return True
        return bool(value)

    @staticmethod
    def _as_number(value: Any) -> int | float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            try:
                parsed = float(normalized)
            except ValueError:
                return None
            return int(parsed) if parsed.is_integer() else parsed
        return None

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any] | None) -> "DownloadContext":
        payload = dict(meta or {})
        cookies = payload.get("cookies")
        images_data = payload.get("images_data")
        return cls(
            trace_id=payload.get("trace_id"),
            download_strategy=payload.get("download_strategy"),
            proxy=payload.get("proxy"),
            ua=payload.get("ua"),
            referer=payload.get("referer"),
            cookie=payload.get("cookie"),
            cookies=dict(cookies) if isinstance(cookies, Mapping) else {},
            content_type=payload.get("content_type"),
            media_label=payload.get("media_label"),
            folder_name=payload.get("folder_name"),
            preferred_filename=payload.get("preferred_filename") or payload.get("file_name"),
            aweme_id=payload.get("aweme_id"),
            bvid=payload.get("bvid"),
            cid=payload.get("cid"),
            audio_url=payload.get("audio_url"),
            images_data=list(images_data) if isinstance(images_data, list) else [],
            duration=cls._as_number(payload.get("duration")),
            size_mb=cls._as_number(payload.get("size_mb")),
            is_gallery=cls._as_bool(payload.get("is_gallery", False)),
            is_mix=cls._as_bool(payload.get("is_mix", False)),
            use_subdir=cls._as_bool(payload.get("use_subdir", False)),
        )

    @property
    def explicit_strategy(self) -> str:
        return str(self.download_strategy or "").strip().lower()

    def to_meta_patch(self) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "is_gallery": self.is_gallery,
            "is_mix": self.is_mix,
            "use_subdir": self.use_subdir,
        }
        optional_fields = {
            "trace_id": self.trace_id,
            "download_strategy": self.download_strategy,
            "proxy": self.proxy,
            "ua": self.ua,
            "referer": self.referer,
            "cookie": self.cookie,
            "content_type": self.content_type,
            "media_label": self.media_label,
            "folder_name": self.folder_name,
            "preferred_filename": self.preferred_filename,
            "aweme_id": self.aweme_id,
            "bvid": self.bvid,
            "cid": self.cid,
            "audio_url": self.audio_url,
            "duration": self.duration,
            "size_mb": self.size_mb,
        }
        for key, value in optional_fields.items():
            if value is not None:
                patch[key] = value
        if self.preferred_filename is not None:
            patch["file_name"] = self.preferred_filename
        if self.cookies:
            patch["cookies"] = dict(self.cookies)
        if self.images_data:
            patch["images_data"] = list(self.images_data)
        return patch
