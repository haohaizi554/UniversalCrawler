"""Lightweight process-wide monitoring for media-library directories."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable


DirectoryChangedCallback = Callable[[str], None]
DirectorySignature = tuple[int, int, int, int] | None
_UNSET = object()


def _normalize_directory(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        return os.path.normcase(os.path.abspath(os.path.expanduser(raw)))
    except (OSError, TypeError, ValueError):
        return os.path.normcase(raw)


def _directory_signature(path: str) -> DirectorySignature:
    """Read only directory metadata; file enumeration happens after a change."""

    try:
        stat_result = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        # A transient permission or network error must not look like a deletion.
        return (0, 0, 0, 0)
    return (
        int(getattr(stat_result, "st_mtime_ns", 0)),
        int(getattr(stat_result, "st_ctime_ns", 0)),
        int(getattr(stat_result, "st_size", 0)),
        int(getattr(stat_result, "st_ino", 0)),
    )


@dataclass
class _WatchRegistration:
    callback: DirectoryChangedCallback
    paths: tuple[str, ...] = ()
    signatures: dict[str, DirectorySignature | object] = field(default_factory=dict)


class MediaDirectoryWatchHandle:
    """Mutable subscription owned by one GUI or Web controller."""

    def __init__(self, monitor: "MediaDirectoryMonitor", registration_id: str) -> None:
        self._monitor = monitor
        self._registration_id = registration_id
        self._closed = False

    def replace_paths(self, paths: Iterable[str]) -> None:
        if not self._closed:
            self._monitor._replace_paths(self._registration_id, paths)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._monitor._remove(self._registration_id)


class MediaDirectoryMonitor:
    """Poll directory metadata in one shared thread and notify on entry changes.

    A process can own many Web sessions. Keeping one polling thread here avoids a
    thread per session, while each controller still owns and closes its handle.
    """

    def __init__(
        self,
        *,
        interval_seconds: float = 0.8,
        signature_provider: Callable[[str], DirectorySignature] = _directory_signature,
        auto_start: bool = True,
    ) -> None:
        self._interval_seconds = max(0.1, float(interval_seconds))
        self._signature_provider = signature_provider
        self._auto_start = bool(auto_start)
        self._lock = threading.RLock()
        self._wake_event = threading.Event()
        self._registrations: dict[str, _WatchRegistration] = {}
        self._thread: threading.Thread | None = None

    def watch(
        self,
        paths: Iterable[str],
        callback: DirectoryChangedCallback,
    ) -> MediaDirectoryWatchHandle:
        registration_id = uuid.uuid4().hex
        registration = _WatchRegistration(callback=callback)
        with self._lock:
            self._registrations[registration_id] = registration
            self._replace_paths_locked(registration, paths)
            if self._auto_start:
                self._ensure_thread_locked()
        self._wake_event.set()
        return MediaDirectoryWatchHandle(self, registration_id)

    def poll_once(self) -> None:
        """Run one deterministic polling pass; also used by focused unit tests."""

        with self._lock:
            registrations = {
                registration_id: tuple(registration.paths)
                for registration_id, registration in self._registrations.items()
            }
        unique_paths = {path for paths in registrations.values() for path in paths}
        signatures = {path: self._signature_provider(path) for path in unique_paths}
        callbacks: list[tuple[DirectoryChangedCallback, str]] = []

        with self._lock:
            for registration_id, paths in registrations.items():
                registration = self._registrations.get(registration_id)
                if registration is None:
                    continue
                for path in paths:
                    if path not in registration.signatures:
                        continue
                    previous = registration.signatures[path]
                    current = signatures[path]
                    registration.signatures[path] = current
                    if previous is _UNSET:
                        continue
                    if previous != current:
                        callbacks.append((registration.callback, path))

        for callback, path in callbacks:
            try:
                callback(path)
            except Exception:
                # Monitoring is advisory. A consumer failure must not kill the
                # one process-wide watcher used by every frontend session.
                continue

    def _replace_paths(self, registration_id: str, paths: Iterable[str]) -> None:
        with self._lock:
            registration = self._registrations.get(registration_id)
            if registration is None:
                return
            self._replace_paths_locked(registration, paths)
            if self._auto_start:
                self._ensure_thread_locked()
        self._wake_event.set()

    @staticmethod
    def _normalized_paths(paths: Iterable[str]) -> tuple[str, ...]:
        normalized = {_normalize_directory(path) for path in paths}
        normalized.discard("")
        return tuple(sorted(normalized))

    def _replace_paths_locked(self, registration: _WatchRegistration, paths: Iterable[str]) -> None:
        normalized = self._normalized_paths(paths)
        previous = registration.signatures
        registration.paths = normalized
        registration.signatures = {
            path: previous.get(path, _UNSET)
            for path in normalized
        }

    def _remove(self, registration_id: str) -> None:
        with self._lock:
            self._registrations.pop(registration_id, None)
        self._wake_event.set()

    def _ensure_thread_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="media-directory-monitor",
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._registrations:
                    self._thread = None
                    return
            self.poll_once()
            self._wake_event.wait(self._interval_seconds)
            self._wake_event.clear()


media_directory_monitor = MediaDirectoryMonitor()
