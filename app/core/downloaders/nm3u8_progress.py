"""N_m3u8DL-RE console progress parsing utilities."""

from __future__ import annotations

import re
import threading
import time


class _Nm3u8OutputProgress:
    """Parse N_m3u8DL-RE console progress into UI-friendly telemetry."""

    _PERCENT_RE = re.compile(r"(?P<percent>\d+(?:\.\d+)?)%")
    _SPEED_RE = re.compile(
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>B|KB|KiB|MB|MiB|GB|GiB|TB|TiB)(?:ps|/s)",
        re.IGNORECASE,
    )
    _UNIT_FACTORS = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024**2,
        "MIB": 1024**2,
        "GB": 1024**3,
        "GIB": 1024**3,
        "TB": 1024**4,
        "TIB": 1024**4,
    }

    def __init__(self, *, default_progress: int = 50) -> None:
        self._lock = threading.Lock()
        self._progress = max(0, min(100, int(default_progress)))
        self._speed_bps = 0
        self._synthetic_bytes = 0.0
        self._last_at = time.monotonic()

    def feed(self, text: str) -> None:
        if not text:
            return
        now = time.monotonic()
        with self._lock:
            self._advance_locked(now)
            percent_match = None
            for percent_match in self._PERCENT_RE.finditer(text):
                pass
            if percent_match is not None:
                try:
                    percent = float(percent_match.group("percent"))
                except (TypeError, ValueError):
                    percent = -1.0
                if percent >= 0:
                    self._progress = max(0, min(95, int(percent)))

            speed_match = None
            for speed_match in self._SPEED_RE.finditer(text):
                pass
            if speed_match is not None:
                self._speed_bps = self._parse_speed_match(speed_match)

    def snapshot(self) -> tuple[int, int]:
        now = time.monotonic()
        with self._lock:
            self._advance_locked(now)
            return self._progress, int(self._synthetic_bytes)

    def _advance_locked(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_at)
        if self._speed_bps > 0 and elapsed > 0:
            self._synthetic_bytes += self._speed_bps * elapsed
        self._last_at = now

    @classmethod
    def _parse_speed_match(cls, match: re.Match[str]) -> int:
        try:
            value = float(match.group("value"))
        except (TypeError, ValueError):
            return 0
        unit = str(match.group("unit") or "B").upper()
        return max(0, int(value * cls._UNIT_FACTORS.get(unit, 1)))

