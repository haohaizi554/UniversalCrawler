"""爬虫请求预算、限速与数据清洁护栏。"""

from app.core.guardrails.crawl_budget import BudgetExhausted, CrawlBudget
from app.core.guardrails.pii_detection import sanitize
from app.core.guardrails.rate_limiter import RESILIENCE_PROFILES, RateLimiter

__all__ = [
    "BudgetExhausted",
    "CrawlBudget",
    "RateLimiter",
    "RESILIENCE_PROFILES",
    "sanitize",
]
