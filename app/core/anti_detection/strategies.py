"""Anti-detection strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import cfg

from .models import AntiDetectionContext


@dataclass(frozen=True, slots=True)
class BrowserAntiDetectionStrategy:
    """Builds a browser/request runtime from shared config fields."""

    source: str
    default_user_agent: str
    referer: str
    viewport: dict[str, int] | None = None

    def build_context(self, config: dict | None) -> AntiDetectionContext:
        config = dict(config or {})
        user_agent = str(
            config.get("ua")
            or cfg.get(self.source, "user_agent", self.default_user_agent)
            or self.default_user_agent
        )
        proxy_raw = config.get("proxy")
        proxy_server = str(proxy_raw).strip() if proxy_raw else None
        return AntiDetectionContext(
            source=self.source,
            user_agent=user_agent,
            referer=self.referer,
            proxy_server=proxy_server or None,
            viewport=dict(self.viewport) if self.viewport else None,
        )
