"""Token-bucket rate limiting profiles for crawler guardrails."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


RESILIENCE_PROFILES: dict[str, float] = {
    "douyin": 0.5,
    "bilibili": 1.0,
    "kuaishou": 0.5,
    "missav": 2.0,
    "xiaohongshu": 0.5,
}


@dataclass(frozen=True)
class RateLimitProfile:
    tokens_per_second: float
    burst: float = 1.0


class RateLimiter:
    """Thread-safe token bucket with optional interruptible waiting."""

    def __init__(
        self,
        tokens_per_second: float,
        *,
        burst: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tokens_per_second = float(tokens_per_second)
        if self.tokens_per_second <= 0:
            raise ValueError(f"tokens_per_second must be positive, got {tokens_per_second}")
        self.burst = max(1.0, float(burst))
        self._tokens = self.burst
        self._updated_at = monotonic()
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.RLock()

    @classmethod
    def for_platform(cls, platform: str) -> "RateLimiter":
        rate = RESILIENCE_PROFILES.get(str(platform or "").lower(), 1.0)
        return cls(rate, burst=max(1.0, rate))

    def acquire(
        self,
        tokens: float = 1.0,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        needed = max(0.01, float(tokens))
        while True:
            with self._lock:
                acquired, wait_seconds = self._refill_locked(needed)
                if acquired:
                    return True
            if cancel_check is not None and cancel_check():
                return False
            self._sleep(min(max(wait_seconds, 0.01), 0.25))

    def _refill_locked(self, needed: float) -> tuple[bool, float]:
        now = self._monotonic()
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(self.burst, self._tokens + elapsed * self.tokens_per_second)
        self._updated_at = now
        if self._tokens >= needed:
            self._tokens -= needed
            return True, 0.0
        return False, (needed - self._tokens) / self.tokens_per_second
