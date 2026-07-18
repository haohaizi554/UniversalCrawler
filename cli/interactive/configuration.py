"""Cookie, persistence, and runtime configuration helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import cfg
from app.utils.runtime_paths import is_temporary_path
from shared.runtime_options import (
    build_missav_proxy_url,
    validate_config_types,
)

_AUTH_FILE_MAP = {
    "douyin": "dy_auth.json",
    "xiaohongshu": "xhs_auth.json",
    "bilibili": "bili_auth.json",
    "kuaishou": "ks_auth.json",
    "missav": None,
}

_REQUIRED_COOKIE_KEY = {
    "douyin": "sessionid_ss",
    "xiaohongshu": "a1",
    "bilibili": "SESSDATA",
    "kuaishou": "kuaishou.server.web_st",
}

_LOGIN_DESC = {
    "douyin": "抖音将自动弹出浏览器窗口，请扫码登录",
    "xiaohongshu": "小红书将自动拉起浏览器以获取 Cookie，必要时请在页面中手动登录",
    "bilibili": "B站将自动弹出浏览器窗口，请扫码登录",
    "kuaishou": "快手将自动弹出浏览器窗口，请手动登录",
}


def auth_file_name(platform_id: str) -> str | None:
    """Return the local authentication filename, if the platform needs one."""

    return _AUTH_FILE_MAP.get(platform_id)


def required_cookie_key(platform_id: str) -> str:
    """Return the minimum local Cookie key used by the preflight check."""

    return _REQUIRED_COOKIE_KEY.get(platform_id, "")


def login_description(platform_id: str) -> str:
    """Return the platform-specific fallback login guidance."""

    return _LOGIN_DESC.get(platform_id, "将自动弹出浏览器窗口登录")


def find_cookie_file(platform_id: str) -> Path | None:
    """Return the first non-empty compatible Cookie JSON path."""

    auth_name = _AUTH_FILE_MAP.get(platform_id)
    if auth_name is None:
        return None

    candidates = [
        Path(auth_name),
        Path.home() / ".ucrawl" / auth_name,
        Path(__file__).resolve().parent.parent.parent / auth_name,
    ]
    try:
        from app.utils.runtime_paths import user_data_root

        candidates.append(user_data_root() / auth_name)
    except Exception:
        pass

    for path in candidates:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def load_cookie(platform_id: str) -> dict | list | None:
    """Read a non-empty dict/list Cookie JSON document."""

    path = find_cookie_file(platform_id)
    if path is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, (dict, list)) and data else None


def build_cookie_string(cookie_data) -> str:
    """Delegate supported Cookie shapes to the shared authentication service."""

    from app.services.auth_service import AuthService

    return AuthService.build_cookie_string(cookie_data)


def check_cookie_valid(platform_id: str, cookie_data) -> bool:
    """Check the locally required key without making a network request."""

    required = _REQUIRED_COOKIE_KEY.get(platform_id)
    if not required:
        return True
    return required in build_cookie_string(cookie_data)


def is_temp_dir(path: str) -> bool:
    """Return whether a path belongs to the operating-system temp area."""

    return is_temporary_path(path)


def persist_save_dir(save_dir: str) -> None:
    """Persist a confirmed, non-temporary interactive download directory."""

    if not save_dir or is_temp_dir(save_dir):
        return
    try:
        cfg.set("common", "save_directory", save_dir)
    except Exception:
        pass


def build_config_summary_lines(
    platform_id: str,
    config: dict,
    platform_name: str,
    keyword: str,
    save_dir: str,
) -> list[str]:
    """Build the platform-specific confirmation summary."""

    lines = [
        f"  平台:   {platform_name}",
        f"  关键词: {keyword}",
        f"  保存到: {save_dir}",
    ]
    if platform_id == "douyin":
        lines.append(f"  视频数: {config.get('max_items', 20)}")
        lines.append("  登录:   浏览器扫码")
    elif platform_id == "xiaohongshu":
        lines.append(f"  笔记数: {config.get('max_items', 20)}")
        lines.append("  登录:   浏览器 Cookie / 手动登录")
    elif platform_id == "bilibili":
        lines.append(f"  页数:   {config.get('max_pages', 1)}")
        lines.append("  登录:   浏览器扫码")
    elif platform_id == "kuaishou":
        lines.append(f"  视频数: {config.get('max_items', 20)}")
        lines.append("  登录:   浏览器手动登录")
    elif platform_id == "missav":
        lines.append(f"  偏好:   {config.get('priority', '')}")
        lines.append(f"  仅单体: {'是' if config.get('individual_only') else '否'}")
        lines.append(f"  代理:   {config.get('proxy', '')}")
    return lines


def finalize_interactive_config(
    args,
    platform_id: str,
    config: dict,
) -> dict:
    """Apply all non-interactive overrides before confirmation."""

    finalized = dict(config)
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            parsed = json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--config JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("--config 必须是 JSON 对象")
        config_err = validate_config_types(parsed)
        if config_err:
            raise ValueError(config_err)
        finalized.update(
            {key: value for key, value in parsed.items() if value is not None}
        )

    value_overrides = {
        "cookie": "cookie",
        "download_strategy": "download_strategy",
        "referer": "referer",
        "ua": "ua",
        "folder_name": "folder_name",
        "file_name": "file_name",
        "content_type": "content_type",
        "proxy": "proxy",
        "priority": "priority",
    }
    for arg_name, config_name in value_overrides.items():
        value = getattr(args, arg_name, None)
        if value:
            finalized[config_name] = value

    if getattr(args, "use_subdir", None):
        finalized["use_subdir"] = True
    if finalized.get("folder_name") and not finalized.get("use_subdir"):
        finalized["use_subdir"] = True
    if getattr(args, "individual_only", None):
        finalized["individual_only"] = True
    if platform_id == "missav" and finalized.get("proxy") is not None:
        finalized["proxy"] = build_missav_proxy_url(finalized["proxy"])
    return finalized
