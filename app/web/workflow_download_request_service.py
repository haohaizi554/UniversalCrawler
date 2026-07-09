"""Request builder extracted from WebWorkflowService.direct_download."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from shared.runtime_options import validate_direct_download_url

ValidateConfigTypesFn = Callable[[dict], str | None]
MergeRuntimeConfigFn = Callable[[str, dict, dict], dict]

@dataclass(frozen=True, slots=True)
class DirectDownloadBuildFailure:
    error: str

@dataclass(frozen=True, slots=True)
class DirectDownloadRequest:
    url: str
    source: str
    title: str
    save_dir: str
    timeout: float
    config: dict

class WebDirectDownloadRequestBuilder:
    """Builds normalized direct-download requests from web payloads."""

    def __init__(
        self,
        *,
        validate_config_types: ValidateConfigTypesFn,
        merge_runtime_config: MergeRuntimeConfigFn,
    ) -> None:
        self._validate_config_types = validate_config_types
        self._merge_runtime_config = merge_runtime_config

    def build(
        self,
        payload: dict,
        *,
        current_save_dir: str,
    ) -> DirectDownloadRequest | DirectDownloadBuildFailure:
        url = payload.get("url", "")
        source = payload.get("source", "")
        title = payload.get("title")
        timeout = payload.get("timeout", 300)
        user_config = payload.get("config", {})

        if title is not None and not isinstance(title, str):
            return DirectDownloadBuildFailure("title 必须是字符串")
        title = title or url

        if not isinstance(url, str) or not isinstance(source, str):
            return DirectDownloadBuildFailure("url 和 source 必须是字符串")
        if not url or not source:
            return DirectDownloadBuildFailure("url 和 source 为必填参数")
        url = url.strip()
        url_error = validate_direct_download_url(url)
        if url_error:
            return DirectDownloadBuildFailure(url_error)

        from app.core.plugin_registry import registry

        plugin = registry.get_plugin(source)
        if not plugin:
            valid_ids = [p.id for p in registry.get_all_plugins()]
            return DirectDownloadBuildFailure(f"无效平台: {source}。支持: {valid_ids}")

        save_dir = payload.get("save_dir")
        if save_dir is not None and not isinstance(save_dir, str):
            return DirectDownloadBuildFailure("save_dir 必须是字符串或 null")
        if not isinstance(user_config, dict):
            return DirectDownloadBuildFailure("config 必须是 JSON 对象")
        config_err = self._validate_config_types(user_config)
        if config_err:
            return DirectDownloadBuildFailure(config_err)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            return DirectDownloadBuildFailure("timeout 必须是数字")
        if timeout <= 0:
            return DirectDownloadBuildFailure("timeout 必须大于 0")

        effective_save_dir = save_dir or current_save_dir
        try:
            # direct_download 顶层 timeout 是整体下载超时，不应被误写进下载 config。
            convenience_payload = dict(payload)
            convenience_payload.pop("timeout", None)
            merged_config = self._merge_runtime_config(source, user_config, convenience_payload)
        except ValueError as exc:
            return DirectDownloadBuildFailure(str(exc))

        return DirectDownloadRequest(
            url=url,
            source=source,
            title=title,
            save_dir=effective_save_dir,
            timeout=timeout,
            config=merged_config,
        )
