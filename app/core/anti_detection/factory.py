"""Factory helpers for anti-detection runtime selection."""

from __future__ import annotations

from .models import AntiDetectionContext
from .strategies import BrowserAntiDetectionStrategy

def build_browser_anti_detection(
    source: str,
    config: dict | None,
    *,
    referer: str,
    default_user_agent: str,
    viewport: dict[str, int] | None = None,
) -> AntiDetectionContext:
    """Build a shared browser anti-detection context for browser-based spiders."""

    return BrowserAntiDetectionStrategy(
        source=source,
        default_user_agent=default_user_agent,
        referer=referer,
        viewport=viewport,
    ).build_context(config)
