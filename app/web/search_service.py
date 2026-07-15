"""Web 搜索路由服务。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Request

from app.web.api_result import error_result
from app.web.logging_utils import log_web_exception
from shared.runtime_options import merge_convenience_params

@dataclass(frozen=True, slots=True)
class SearchRouteRuntime:
    """描述搜索路由的运行时依赖。"""

    build_selection_strategy: Callable[[dict | None], Any]
    merge_default_config: Callable[[str, dict], dict]
    validate_config_types: Callable[[dict], str | None]
    run_cli_search: Callable[..., dict]

class WebSearchService:
    """承载 `/api/search` 的输入校验、参数归一与运行时委派。"""

    def __init__(
        self,
        *,
        get_request_context: Callable[[Request], Any],
        runtime_provider: Callable[[], SearchRouteRuntime],
    ) -> None:
        self._get_request_context = get_request_context
        self._runtime_provider = runtime_provider

    async def search(self, request: Request, body: dict) -> dict:
        runtime = self._runtime_provider()
        context = self._get_request_context(request)

        source = body.get("source", "")
        keyword = body.get("keyword", "")
        if not isinstance(source, str) or not isinstance(keyword, str):
            return error_result("source 和 keyword 必须是字符串")

        keyword = keyword.strip()
        if not source or not keyword:
            return error_result("source 和 keyword 为必填参数")

        from app.core.plugin_registry import registry

        if not registry.get_plugin(source):
            valid_ids = [plugin.id for plugin in registry.get_all_plugins()]
            return error_result(f"无效平台: {source}。支持: {valid_ids}")

        save_dir = body.get("save_dir")
        if save_dir is not None and not isinstance(save_dir, str):
            return error_result("save_dir 必须是字符串或 null")
        save_dir = save_dir or context.controller.current_save_dir
        try:
            save_dir = context.require_directory(save_dir)
        except PermissionError as exc:
            return error_result(str(exc), http_status=403)

        user_config = body.get("config", {})
        if not isinstance(user_config, dict):
            return error_result("config 必须是 JSON 对象")

        config_err = runtime.validate_config_types(user_config)
        if config_err:
            return error_result(config_err)

        selection_dict = body.get("selection")
        if selection_dict is not None and not isinstance(selection_dict, dict):
            return error_result("selection 必须是 JSON 对象或 null")

        strategy = runtime.build_selection_strategy(selection_dict)
        if strategy is None:
            valid_strategies = ["all", "first", "last", "rule", "preload", "interactive", "pipe"]
            return error_result(f"无效选择策略。支持: {valid_strategies}")

        timeout = body.get("run_timeout") or body.get("timeout")
        if timeout is not None:
            try:
                timeout = float(timeout)
            except (ValueError, TypeError):
                return error_result("timeout/run_timeout 必须是数字")
            if timeout <= 0:
                return error_result("timeout/run_timeout 必须大于 0")

        download_result = self._normalize_download_flag(body.get("download", True))
        if isinstance(download_result, dict):
            return download_result
        download = download_result

        merged_config = runtime.merge_default_config(source, user_config)
        try:
            merge_convenience_params(body, merged_config, source)
        except ValueError as exc:
            return error_result(str(exc))

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: runtime.run_cli_search(
                    source=source,
                    keyword=keyword,
                    save_dir=save_dir,
                    selection_strategy=strategy,
                    config=merged_config,
                    timeout=timeout,
                    download=download,
                ),
            )
        except Exception as exc:
            log_web_exception(
                "WebSearchService",
                "search",
                exc,
                context={"source": source, "keyword": keyword, "save_dir": save_dir},
                details={"download": download},
            )
            return error_result(str(exc), http_status=500)

    @staticmethod
    def _normalize_download_flag(download: Any) -> bool | dict:
        if download is None:
            return True
        if isinstance(download, str):
            return download.lower() not in ("false", "0", "no", "off")
        if isinstance(download, bool):
            return download
        if isinstance(download, (int, float, list, dict)):
            return error_result("download 必须是布尔值")
        return error_result("download 必须是布尔值")
