"""Persistent playback position index for local media previews."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.debug_logger import debug_logger
from app.utils.runtime_paths import resolve_user_file


@dataclass(slots=True)
class PlaybackPositionEntry:
    path: str
    position_ms: int
    duration_ms: int
    size: int
    mtime_ns: int
    updated_at: float


class PlaybackPositionService:
    """Store resume positions and prune entries that no longer match a file."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        file_path: str | os.PathLike[str] | None = None,
        *,
        max_entries: int = 1000,
        cleanup_on_load: bool = True,
    ) -> None:
        self.file_path = Path(file_path) if file_path is not None else resolve_user_file("playback_positions.json")
        self.max_entries = max(1, int(max_entries or 1000))
        self._lock = threading.RLock()
        self._entries: dict[str, PlaybackPositionEntry] = {}
        self._load()
        if cleanup_on_load:
            self.cleanup()

    def get(self, path: str | os.PathLike[str]) -> int:
        key = self.normalize_path(path)
        if not key:
            return 0
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return 0
            if not self._entry_matches_file(entry):
                self._entries.pop(key, None)
                self._write_locked()
                return 0
            return max(0, int(entry.position_ms or 0))

    def save(self, path: str | os.PathLike[str], position_ms: int, *, duration_ms: int = 0) -> None:
        key = self.normalize_path(path)
        if not key:
            return
        position_ms = max(0, int(position_ms or 0))
        duration_ms = max(0, int(duration_ms or 0))
        with self._lock:
            metadata = self._file_metadata(key)
            if metadata is None:
                self._entries.pop(key, None)
                self._write_locked()
                return
            if position_ms < 1000:
                return
            if duration_ms > 0 and position_ms >= max(0, duration_ms - 1500):
                self._entries.pop(key, None)
                self._write_locked()
                return
            self._entries[key] = PlaybackPositionEntry(
                path=key,
                position_ms=position_ms,
                duration_ms=duration_ms,
                size=metadata[0],
                mtime_ns=metadata[1],
                updated_at=time.time(),
            )
            self._prune_size_locked()
            self._write_locked()

    def delete(self, path: str | os.PathLike[str]) -> None:
        key = self.normalize_path(path)
        if not key:
            return
        with self._lock:
            if self._entries.pop(key, None) is not None:
                self._write_locked()

    def clear(self) -> None:
        with self._lock:
            if self._entries:
                self._entries.clear()
                self._write_locked()

    def cleanup(self) -> int:
        with self._lock:
            before = len(self._entries)
            self._entries = {
                key: entry
                for key, entry in self._entries.items()
                if self._entry_matches_file(entry)
            }
            self._prune_size_locked()
            removed = before - len(self._entries)
            if removed:
                self._write_locked()
            return removed

    def snapshot(self) -> dict[str, PlaybackPositionEntry]:
        with self._lock:
            return dict(self._entries)

    @staticmethod
    def normalize_path(path: str | os.PathLike[str]) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        try:
            expanded = os.path.expandvars(os.path.expanduser(raw))
            return os.path.normcase(os.path.abspath(expanded))
        except (OSError, TypeError, ValueError):
            return os.path.normcase(raw)

    def _load(self) -> None:
        with self._lock:
            self._entries = {}
            try:
                payload = json.loads(self.file_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                debug_logger.log_exception(
                    "PlaybackPositionService",
                    "load",
                    exc,
                    details={"file_path": str(self.file_path)},
                )
                return
            raw_entries = payload.get("entries") if isinstance(payload, dict) else {}
            if not isinstance(raw_entries, dict):
                return
            for raw_key, raw_entry in raw_entries.items():
                if not isinstance(raw_entry, dict):
                    continue
                key = self.normalize_path(raw_entry.get("path") or raw_key)
                if not key:
                    continue
                try:
                    self._entries[key] = PlaybackPositionEntry(
                        path=key,
                        position_ms=int(raw_entry.get("position_ms") or 0),
                        duration_ms=int(raw_entry.get("duration_ms") or 0),
                        size=int(raw_entry.get("size") or 0),
                        mtime_ns=int(raw_entry.get("mtime_ns") or 0),
                        updated_at=float(raw_entry.get("updated_at") or 0.0),
                    )
                except (TypeError, ValueError):
                    continue

    def _write_locked(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": self.SCHEMA_VERSION,
            "entries": {key: asdict(entry) for key, entry in self._entries.items()},
        }
        temp_path = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        try:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.file_path)
        except OSError as exc:
            debug_logger.log_exception(
                "PlaybackPositionService",
                "write",
                exc,
                details={"file_path": str(self.file_path)},
            )

    def _entry_matches_file(self, entry: PlaybackPositionEntry) -> bool:
        metadata = self._file_metadata(entry.path)
        if metadata is None:
            return False
        size, mtime_ns = metadata
        if entry.size and size != entry.size:
            return False
        if entry.mtime_ns and mtime_ns != entry.mtime_ns:
            return False
        return entry.position_ms >= 1000

    @staticmethod
    def _file_metadata(path: str) -> tuple[int, int] | None:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        if not Path(path).is_file():
            return None
        return int(stat.st_size), int(stat.st_mtime_ns)

    def _prune_size_locked(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        ordered = sorted(self._entries.items(), key=lambda item: item[1].updated_at, reverse=True)
        self._entries = dict(ordered[: self.max_entries])
