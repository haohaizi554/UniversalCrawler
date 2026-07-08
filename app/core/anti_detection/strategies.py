"""Anti-detection strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import cfg

from .models import DEFAULT_ACCEPT_LANGUAGE, DEFAULT_LOCALE, DEFAULT_TIMEZONE_ID, AntiDetectionContext
from app.utils.user_agents import resolve_user_agent

@dataclass(frozen=True, slots=True)
class BrowserAntiDetectionStrategy:
    """Builds a browser/request runtime from shared config fields."""

    source: str
    default_user_agent: str
    referer: str
    viewport: dict[str, int] | None = None

    def build_context(self, config: dict | None) -> AntiDetectionContext:
        config = dict(config or {})
        user_agent = resolve_user_agent(
            self.source,
            config,
            configured_user_agent=cfg.get(self.source, "user_agent", self.default_user_agent),
            default_user_agent=self.default_user_agent,
        )
        proxy_raw = config.get("proxy")
        proxy_server = str(proxy_raw).strip() if proxy_raw else None
        locale = str(config.get("locale") or config.get("language") or DEFAULT_LOCALE).strip()
        timezone_id = str(config.get("timezone_id") or config.get("timezone") or DEFAULT_TIMEZONE_ID).strip()
        accept_language = str(config.get("accept_language") or DEFAULT_ACCEPT_LANGUAGE).strip()
        return AntiDetectionContext(
            source=self.source,
            user_agent=user_agent,
            referer=self.referer,
            proxy_server=proxy_server or None,
            viewport=dict(self.viewport) if self.viewport else None,
            locale=locale or DEFAULT_LOCALE,
            timezone_id=timezone_id or DEFAULT_TIMEZONE_ID,
            accept_language=accept_language or DEFAULT_ACCEPT_LANGUAGE,
        )
