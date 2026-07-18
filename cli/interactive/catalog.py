"""Normalize plugin-owned copy for the interactive terminal guide."""

from __future__ import annotations


def guide_for(
    platform_id: str,
    platform_info: dict | None = None,
) -> dict:
    """Return a defensive guide for current and pre-manifest plugins."""

    info = platform_info or {}
    name = str(info.get("name") or platform_id)
    default = {
        "input_label": str(
            info.get("search_placeholder") or "输入关键词或链接"
        ),
        "examples": [],
        "empty_tip": "请检查输入、登录状态和插件配置。",
        "result_tip": (
            f"{name} 将使用插件提供的默认配置执行搜索与下载。"
        ),
        "fields": [],
        "auth": {"mode": "unspecified"},
    }

    raw = info.get("interactive")
    if not isinstance(raw, dict):
        return default

    guide = dict(default)
    for key in ("input_label", "empty_tip", "result_tip"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            guide[key] = value

    examples = raw.get("examples")
    if isinstance(examples, list):
        guide["examples"] = [
            str(value)
            for value in examples
            if str(value).strip()
        ]

    fields = raw.get("fields")
    if isinstance(fields, list):
        guide["fields"] = [
            dict(value)
            for value in fields
            if isinstance(value, dict)
            and isinstance(value.get("key"), str)
            and isinstance(value.get("choices"), list)
        ]

    auth = raw.get("auth")
    if isinstance(auth, dict):
        guide["auth"] = dict(auth)
    return guide
