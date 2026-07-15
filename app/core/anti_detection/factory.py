"""根据运行配置创建反检测策略。"""

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
    """构建 browser spider 共用的反检测上下文；调用方不需要关心策略类细节。"""

    return BrowserAntiDetectionStrategy(
        source=source,
        default_user_agent=default_user_agent,
        referer=referer,
        viewport=viewport,
    ).build_context(config)
