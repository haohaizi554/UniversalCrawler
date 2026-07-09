"""浏览器/请求反检测参数模型，集中描述 UA、语言、时区和代理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTOMATION_CONTROLLED_ARG = "--disable-blink-features=AutomationControlled"
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
DEFAULT_LOCALE = "zh-CN"
DEFAULT_TIMEZONE_ID = "Asia/Shanghai"

@dataclass(frozen=True, slots=True)
class AntiDetectionContext:
    """同一份上下文同时服务 Playwright 启动、context 创建和 HTTP 请求头。"""

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
        """生成 browser.launch 参数；代理属于进程级配置，必须放在这里。"""
        kwargs: dict[str, Any] = {"headless": headless}
        if self.proxy_server:
            kwargs["proxy"] = {"server": self.proxy_server}
        if self.launch_args:
            kwargs["args"] = list(self.launch_args)
        return kwargs

    def browser_context_kwargs(self) -> dict[str, Any]:
        """生成 browser.new_context 参数，统一控制页面可见的本地化特征。"""
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
        """生成 requests/aiohttp 可用的基础请求头，并允许平台追加特有字段。"""
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
