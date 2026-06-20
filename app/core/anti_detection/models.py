"""Structured anti-detection runtime models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTOMATION_CONTROLLED_ARG = "--disable-blink-features=AutomationControlled"

@dataclass(frozen=True, slots=True)
class AntiDetectionContext:
    """Normalized anti-detection runtime for browser/request setup."""

    source: str
    user_agent: str
    referer: str
    proxy_server: str | None = None
    viewport: dict[str, int] | None = None
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
        return kwargs

    def request_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if self.referer:
            headers["Referer"] = self.referer
        for key, value in (extra_headers or {}).items():
            if value:
                headers[key] = value
        return headers
