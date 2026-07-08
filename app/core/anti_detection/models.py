"""Structured anti-detection runtime models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTOMATION_CONTROLLED_ARG = "--disable-blink-features=AutomationControlled"
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
DEFAULT_LOCALE = "zh-CN"
DEFAULT_TIMEZONE_ID = "Asia/Shanghai"

@dataclass(frozen=True, slots=True)
class AntiDetectionContext:
    """Normalized anti-detection runtime for browser/request setup."""

    source: str
    user_agent: str
    referer: str
    proxy_server: str | None = None
    viewport: dict[str, int] | None = None
    locale: str = DEFAULT_LOCALE
    timezone_id: str = DEFAULT_TIMEZONE_ID
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE
    launch_args: tuple[str, ...] = (AUTOMATION_CONTROLLED_ARG,)

    def browser_launch_kwargs(self, *, headless: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"headless": headless}
        if self.proxy_server:
            kwargs["proxy"] = {"server": self.proxy_server}
        if self.launch_args:
            kwargs["args"] = list(self.launch_args)
        return kwargs

    def browser_context_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.user_agent:
            kwargs["user_agent"] = self.user_agent
        if self.viewport:
            kwargs["viewport"] = dict(self.viewport)
        if self.locale:
            kwargs["locale"] = self.locale
        if self.timezone_id:
            kwargs["timezone_id"] = self.timezone_id
        if self.accept_language:
            kwargs["extra_http_headers"] = {"Accept-Language": self.accept_language}
        return kwargs

    def request_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if self.referer:
            headers["Referer"] = self.referer
        if self.accept_language:
            headers["Accept-Language"] = self.accept_language
        for key, value in (extra_headers or {}).items():
            if value:
                headers[key] = value
        return headers

    def apply_to_context(self, context: Any) -> None:
        """Apply bundled stealth scripts to a Playwright browser context."""
        from .stealth import apply_stealth_to_context

        apply_stealth_to_context(context)
