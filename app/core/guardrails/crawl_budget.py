"""爬虫护栏使用的请求预算计数器。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


class BudgetExhausted(RuntimeError):
    """抓取即将超过配置的请求预算时抛出。"""


class RateLimitCancelled(Exception):
    """限速器主动取消请求（区别于预算耗尽）。"""
    pass


@dataclass
class CrawlBudget:
    max_requests_per_platform: int = 1000
    max_total: int = 5000
    _per_platform: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _total: int = field(default=0, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def consume(self, platform: str, amount: int = 1) -> None:
        normalized_platform = str(platform or "unknown")
        normalized_amount = int(amount)
        if normalized_amount <= 0:
            raise ValueError(f"consume amount must be positive, got {amount}")
        with self._lock:
            next_total = self._total + normalized_amount
            if next_total > self.max_total:
                raise BudgetExhausted(
                    f"crawl budget exhausted: total {next_total}/{self.max_total}"
                )
            current_platform = self._per_platform.get(normalized_platform, 0)
            next_platform = current_platform + normalized_amount
            if next_platform > self.max_requests_per_platform:
                raise BudgetExhausted(
                    f"crawl budget exhausted for {normalized_platform}: "
                    f"{next_platform}/{self.max_requests_per_platform}"
                )
            self._total = next_total
            self._per_platform[normalized_platform] = next_platform

    def remaining(self, platform: str | None = None) -> int | dict[str, int]:
        with self._lock:
            total_remaining = max(0, self.max_total - self._total)
            if platform is not None:
                normalized_platform = str(platform or "unknown")
                platform_remaining = max(
                    0,
                    self.max_requests_per_platform - self._per_platform.get(normalized_platform, 0),
                )
                return min(total_remaining, platform_remaining)
            return {
                "total": total_remaining,
                "max_requests_per_platform": self.max_requests_per_platform,
                **{
                    name: max(0, self.max_requests_per_platform - used)
                    for name, used in self._per_platform.items()
                },
            }

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "max_requests_per_platform": self.max_requests_per_platform,
                "max_total": self.max_total,
                "total": self._total,
                "per_platform": dict(self._per_platform),
            }
