"""Launch request builder extracted from WebWorkflowService."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from shared.selection_runtime import SelectionStrategyFactory
from shared.spider_session_runtime import SpiderLaunchRequest


BuildSelectionStrategyFn = Callable[[dict | None], Any]
MergeDefaultConfigFn = Callable[[str, dict], dict]
ValidateConfigTypesFn = Callable[[dict], str | None]
MergeConvenienceParamsFn = Callable[[dict, dict, str], Any]


@dataclass(frozen=True, slots=True)
class LaunchBuildFailure:
    error: str
    requires_crawl_state_reset: bool = True


class WebWorkflowLaunchBuilder:
    """Builds SpiderLaunchRequest from web payload with validation."""

    def __init__(
        self,
        *,
        build_selection_strategy: BuildSelectionStrategyFn,
        merge_default_config: MergeDefaultConfigFn,
        validate_config_types: ValidateConfigTypesFn,
        merge_convenience_params: MergeConvenienceParamsFn,
    ) -> None:
        self._build_selection_strategy = build_selection_strategy
        self._merge_default_config = merge_default_config
        self._validate_config_types = validate_config_types
        self._merge_convenience_params = merge_convenience_params

    def build(self, payload: dict) -> SpiderLaunchRequest | LaunchBuildFailure:
        source = payload.get("source", "")
        keyword = payload.get("keyword", "")
        if "download" in payload:
            return LaunchBuildFailure(
                "此端点始终触发下载，不支持 download 参数。如需只搜索不下载，请使用 POST /api/search 并传 download: false"
            )
        if not isinstance(source, str) or not isinstance(keyword, str):
            return LaunchBuildFailure("source 和 keyword 必须是字符串")
        keyword = keyword.strip()
        if not source or not keyword:
            return LaunchBuildFailure("source 和 keyword 为必填参数")

        from app.core.plugin_registry import registry

        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            return LaunchBuildFailure(f"无效平台: {source}。支持: {valid_ids}")

        user_config = payload.get("config", {})
        if not isinstance(user_config, dict):
            return LaunchBuildFailure("config 必须是 JSON 对象")
        config_err = self._validate_config_types(user_config)
        if config_err:
            return LaunchBuildFailure(config_err)

        selection_dict = payload.get("selection")
        if selection_dict is not None and not isinstance(selection_dict, dict):
            return LaunchBuildFailure("selection 必须是 JSON 对象或 null")
        strategy = None
        if selection_dict is not None:
            strategy = self._build_selection_strategy(selection_dict)
            if strategy is None:
                valid_strategies = SelectionStrategyFactory.available_strategy_names()
                return LaunchBuildFailure(f"无效选择策略。支持: {valid_strategies}")

        merged_config = self._merge_default_config(source, user_config)
        try:
            self._merge_convenience_params(payload, merged_config, source)
        except ValueError as exc:
            return LaunchBuildFailure(str(exc))

        save_dir = payload.get("save_dir")
        if save_dir is not None and not isinstance(save_dir, str):
            return LaunchBuildFailure("save_dir 必须是字符串或 null")

        return SpiderLaunchRequest(
            source_id=source,
            keyword=keyword,
            config=merged_config,
            save_dir=save_dir or None,
            selection_strategy=strategy,
        )
