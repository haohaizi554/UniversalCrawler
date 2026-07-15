from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from app.config.settings import (
    CURRENT_FILENAME_TEMPLATE,
    DEFAULT_OPEN_MODE,
    accent_label,
    accent_options,
    download_concurrency_options,
    failed_record_retention_options,
    filename_template_label,
    filename_template_options,
    font_size_label,
    font_size_options,
    image_auto_advance_interval_options,
    language_label,
    language_options,
    log_retention_options,
    normalize_download_concurrency,
    normalize_ui_log_max_display_count,
    open_mode_label,
    open_mode_options,
    playback_player_label,
    playback_player_options,
    platform_count_options,
    platform_note_count_options,
    platform_page_count_options,
    proxy_app_options,
    request_timeout_options,
    retry_options,
    scale_options,
    speed_limit_options,
    ui_log_max_display_options,
)
from app.core.plugin_registry import registry
from app.debug_logger import debug_logger
from app.services.auth_service import AuthService

PLATFORM_AUTH_REQUIREMENTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "douyin": ("douyin_cookie_file", ("sessionid_ss",), "https://www.douyin.com/"),
    "bilibili": ("bilibili_cookie_file", ("SESSDATA",), "https://www.bilibili.com/"),
    "kuaishou": ("kuaishou_cookie_file", ("userId",), "https://www.kuaishou.com/"),
    "xiaohongshu": ("xiaohongshu_cookie_file", ("web_session", "a1"), "https://www.xiaohongshu.com/"),
}


def platform_auth_snapshot(plugin_id: str, auth_cfg: Mapping[str, Any]) -> dict[str, str]:
    requirement = PLATFORM_AUTH_REQUIREMENTS.get(str(plugin_id or "").strip().lower())
    if not requirement:
        return {
            "auth_status": "未认证",
            "auth_detail": "该平台暂无 Cookie 检测规则",
            "auth_cookie_file": "",
        }
    file_key, cookie_names, auth_url = requirement
    cookie_file = str(auth_cfg.get(file_key) or "")
    if not cookie_file:
        return {
            "auth_status": "未认证",
            "auth_detail": "未配置 Cookie 文件",
            "auth_cookie_file": "",
        }
    path = Path(cookie_file).expanduser()
    if not path.exists() or not path.is_file():
        return {
            "auth_status": "未认证",
            "auth_detail": "Cookie 文件不存在",
            "auth_cookie_file": str(path),
        }
    try:
        payload = AuthService().load_json_file(str(path))
        cookie_dict = AuthService.extract_cookie_dict_for_url(payload, auth_url)
    except Exception as exc:
        debug_logger.log_exception(
            "FrontendSettingsAdapter",
            "auth_cookie_status",
            exc,
            details={"plugin_id": plugin_id, "cookie_file": str(path)},
        )
        return {
            "auth_status": "未认证",
            "auth_detail": "Cookie 文件无法读取",
            "auth_cookie_file": str(path),
        }
    matched = [name for name in cookie_names if cookie_dict.get(name)]
    if matched:
        return {
            "auth_status": "已认证",
            "auth_detail": f"已检测到 {matched[0]}",
            "auth_cookie_file": str(path),
        }
    return {
        "auth_status": "未认证",
        "auth_detail": "Cookie 缺少关键登录字段",
        "auth_cookie_file": str(path),
    }


def count_label(value: Any, unit: str) -> str:
    number = str(value or "").strip()
    if number == "9999":
        return "max"
    if unit == "pages":
        return f"{number} 页" if number else ""
    if unit == "notes":
        return f"{number} 篇笔记" if number else ""
    return f"{number} 个视频" if number else ""


def platform_count_contract(plugin_id: str, section: Mapping[str, Any]) -> dict[str, Any]:
    plugin_key = str(plugin_id or "").strip().lower()
    if plugin_key == "bilibili":
        key = "max_pages"
        unit = "pages"
        options = platform_page_count_options()
    elif plugin_key == "xiaohongshu":
        key = "max_items"
        unit = "notes"
        options = platform_note_count_options()
    elif plugin_key in {"missav", "douyin", "kuaishou"}:
        key = "max_items"
        unit = "videos"
        options = platform_count_options()
    elif "max_items" in section:
        key = "max_items"
        unit = "videos"
        options = platform_count_options()
    elif "max_pages" in section:
        key = "max_pages"
        unit = "pages"
        options = platform_page_count_options()
    elif "search_max_pages" in section:
        key = "search_max_pages"
        unit = "pages"
        options = platform_page_count_options()
    else:
        return {"key": "", "unit": "", "value": 20, "options": []}

    value = section.get(key, 1 if unit == "pages" else 20)
    value_text = str(value)
    allowed_values = {str(option.get("value")) for option in options}
    if value_text not in allowed_values:
        value = 1 if unit == "pages" else 20
    return {"key": key, "unit": unit, "value": value, "options": options}


def platform_proxy_contract(plugin_id: str, section: Mapping[str, Any]) -> dict[str, Any]:
    plugin_key = str(plugin_id or "").strip().lower()
    if plugin_key != "missav":
        return {
            "proxy": "系统代理",
            "proxy_config_key": "",
            "proxy_editable": False,
            "proxy_options": proxy_app_options(),
            "proxy_custom_allowed": False,
            "proxy_custom_value": "",
            "proxy_custom_active": False,
        }

    proxy_app = str(section.get("proxy_app") or "系统代理").strip() or "系统代理"
    proxy_url = str(section.get("proxy_url") or "").strip()
    known_proxy_values = {str(option.get("value")) for option in proxy_app_options()}
    if proxy_app not in known_proxy_values:
        proxy_url = proxy_url or proxy_app
        proxy_app = "自定义"
    return {
        "proxy": proxy_app,
        "proxy_config_key": "proxy_app",
        "proxy_editable": True,
        "proxy_options": proxy_app_options(),
        "proxy_custom_allowed": True,
        "proxy_custom_value": proxy_url,
        "proxy_custom_active": proxy_app == "自定义",
    }


def platform_timeout_contract(section: Mapping[str, Any]) -> dict[str, Any]:
    key = "timeout" if "timeout" in section else ""
    value = section.get(key, 60) if key else 60
    options = request_timeout_options()
    value_text = str(value)
    if key and value_text and not any(str(option.get("value")) == value_text for option in options):
        options.insert(0, {"value": value_text, "label": f"{value_text} 秒"})
    return {
        "default_timeout": value,
        "timeout": value,
        "timeout_config_key": key,
        "timeout_editable": bool(key),
        "timeout_options": options if key else [],
    }



def build_download_options_snapshot(
    config_get,
    cache_get,
    manager: Any | None,
) -> dict[str, Any]:
    try:
        configured_concurrent = int(config_get("download", "max_concurrent", 3))
    except (TypeError, ValueError):
        configured_concurrent = 3
    try:
        effective_concurrent = int(getattr(manager, "max_concurrent", configured_concurrent) or configured_concurrent)
    except (TypeError, ValueError):
        effective_concurrent = configured_concurrent
    try:
        max_retries = int(config_get("download", "max_retries", 3))
    except (TypeError, ValueError):
        max_retries = 3
    auto_retry = bool(cache_get("download.auto_retry", True))
    image_respects_concurrency = bool(config_get("download", "image_respects_concurrency", False))
    if manager is not None and hasattr(manager, "image_respects_concurrency"):
        image_respects_concurrency = bool(manager.image_respects_concurrency)
    video_only = bool(config_get("download", "video_only", False))
    manager_video_only = getattr(manager, "video_only", None) if manager is not None else None
    if isinstance(manager_video_only, bool):
        video_only = manager_video_only
    return {
        "auto_retry": auto_retry,
        "max_retries": max(0, min(max_retries, 10)),
        "max_concurrent": normalize_download_concurrency(effective_concurrent),
        "video_only": video_only,
        "image_respects_concurrency": image_respects_concurrency,
    }


def normalize_download_options_payload(
    payload: Mapping[str, Any],
    config_get,
    cache_get,
) -> dict[str, Any]:
    data = dict(payload or {})
    try:
        max_concurrent = int(data.get("max_concurrent", config_get("download", "max_concurrent", 3)))
    except (TypeError, ValueError):
        max_concurrent = 3
    try:
        max_retries = int(data.get("max_retries", config_get("download", "max_retries", 3)))
    except (TypeError, ValueError):
        max_retries = 3
    return {
        "auto_retry": bool(data.get("auto_retry", cache_get("download.auto_retry", True))),
        "max_retries": max(0, min(max_retries, 10)),
        "max_concurrent": normalize_download_concurrency(max_concurrent),
        "video_only": bool(data.get("video_only", config_get("download", "video_only", False))),
        "image_respects_concurrency": bool(
            data.get("image_respects_concurrency", config_get("download", "image_respects_concurrency", False))
        ),
    }


def apply_manager_concurrency(manager: Any | None, max_concurrent: Any) -> int:
    normalized = normalize_download_concurrency(max_concurrent)
    setter = getattr(manager, "set_max_concurrent", None)
    if callable(setter):
        try:
            normalized = int(setter(normalized))
        except (TypeError, ValueError):
            pass
    return normalize_download_concurrency(normalized)


def persist_download_options(
    config_set,
    cache_set,
    options: Mapping[str, Any],
    *,
    config_set_many=None,
) -> None:
    max_retries = options.get("max_retries", 3)
    try:
        max_retries = int(max_retries)
    except (TypeError, ValueError):
        max_retries = 3
    config_values = {
        "max_concurrent": normalize_download_concurrency(options.get("max_concurrent")),
        "max_retries": max(0, min(max_retries, 10)),
        "video_only": bool(options.get("video_only", False)),
        "image_respects_concurrency": bool(options.get("image_respects_concurrency", False)),
    }
    if callable(config_set_many):
        config_set_many("download", config_values)
    else:
        for key, value in config_values.items():
            config_set("download", key, value)
    cache_set("download.auto_retry", bool(options.get("auto_retry", True)), persist=False)


def platform_settings_rows(
    data: Mapping[str, Any],
    *,
    plugins: Iterable[Any] | None = None,
    auth_status_provider: Callable[[str, Mapping[str, Any]], Mapping[str, str]] | None = None,
) -> list[dict[str, Any]]:
    auth_cfg = data.get("auth", {})
    rows: list[dict[str, Any]] = []
    for plugin in plugins if plugins is not None else registry.get_all_plugins():
        section = data.get(plugin.id, {})
        count_contract = platform_count_contract(plugin.id, section)
        timeout_contract = platform_timeout_contract(section)
        proxy_contract = platform_proxy_contract(plugin.id, section)
        auth_state = (
            dict(auth_status_provider(plugin.id, auth_cfg))
            if callable(auth_status_provider)
            else platform_auth_snapshot(plugin.id, auth_cfg)
        )
        rows.append(
            {
                "id": plugin.id,
                "name": plugin.name,
                **auth_state,
                "default_count": count_contract["value"],
                "count_config_key": count_contract["key"],
                "count_unit": count_contract["unit"],
                "count_editable": bool(count_contract["key"]),
                "count_options": count_contract["options"],
                **timeout_contract,
                **proxy_contract,
            }
        )
    return rows


def build_settings_snapshot(
    data: Mapping[str, Any],
    download_options: Mapping[str, Any],
    *,
    plugins: Iterable[Any] | None = None,
    auth_status_provider: Callable[[str, Mapping[str, Any]], Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    common = data.get("common", {})
    download = data.get("download", {})
    playback = data.get("playback", {})
    logging_cfg = data.get("logging", {})
    appearance = data.get("appearance", {})
    filename_template = str(common.get("filename_template") or CURRENT_FILENAME_TEMPLATE)
    default_open_mode = str(common.get("default_open_mode") or DEFAULT_OPEN_MODE)
    default_player = str(playback.get("default_player") or DEFAULT_OPEN_MODE)
    accent = str(appearance.get("accent") or "blue")
    font_size = str(appearance.get("font_size") or "medium")
    language = str(appearance.get("language") or "zh-CN")
    return {
        "基础设置": {
            "download_directory": common.get("save_directory", ""),
            "last_source": common.get("last_source", ""),
            "filename_template": filename_template,
            "filename_template_label": filename_template_label(filename_template),
            "open_after_download": bool(common.get("open_after_download", False)),
            "default_open_mode": default_open_mode,
            "default_open_mode_label": open_mode_label(default_open_mode),
            "show_browser_window": bool(common.get("show_browser_window", True)),
            "_options": {
                "filename_template": filename_template_options(),
                "default_open_mode": open_mode_options(),
            },
        },
        "下载设置": {
            "max_concurrent": download_options["max_concurrent"],
            "request_timeout": download.get("request_timeout", 60),
            "max_retries": download_options["max_retries"],
            "resume_enabled": bool(download.get("resume_enabled", True)),
            "speed_limit_kb": int(download.get("speed_limit_kb", 0) or 0),
            "video_only": bool(download.get("video_only", False)),
            "image_respects_concurrency": download_options["image_respects_concurrency"],
            "_options": {
                "max_concurrent": download_concurrency_options(),
                "request_timeout": request_timeout_options(),
                "max_retries": retry_options(),
                "speed_limit_kb": speed_limit_options(),
            },
        },
        "平台设置": platform_settings_rows(data, plugins=plugins, auth_status_provider=auth_status_provider),
        "播放设置": {
            "default_player": default_player,
            "default_player_label": playback_player_label(default_player),
            "remember_position": bool(playback.get("remember_position", True)),
            "autoplay_next": bool(playback.get("autoplay_next", True)),
            "manual_image_switch": bool(playback.get("manual_image_switch", False)),
            "image_auto_advance_interval_seconds": int(playback.get("image_auto_advance_interval_seconds", 5) or 5),
            "_options": {
                "default_player": playback_player_options(),
                "image_auto_advance_interval_seconds": image_auto_advance_interval_options(),
            },
        },
        "日志设置": {
            "retention_days": int(logging_cfg.get("retention_days", 1) or 1),
            "failed_record_retention_days": int(logging_cfg.get("failed_record_retention_days", 7) or 7),
            "ui_log_max_display_count": normalize_ui_log_max_display_count(logging_cfg.get("ui_log_max_display_count", 300)),
            "auto_copy_trace_on_error": bool(logging_cfg.get("auto_copy_trace_on_error", True)),
            "_options": {
                "retention_days": log_retention_options(),
                "failed_record_retention_days": failed_record_retention_options(),
                "ui_log_max_display_count": ui_log_max_display_options(),
            },
        },
        "外观设置": {
            "follow_system": bool(appearance.get("follow_system", False)),
            "theme": common.get("theme", "light"),
            "accent": accent,
            "accent_label": accent_label(accent),
            "scale": appearance.get("scale", "100%"),
            "font_size": font_size,
            "font_size_label": font_size_label(font_size),
            "language": language,
            "language_label": language_label(language),
            "_options": {
                "theme": [{"value": "light", "label": "浅色"}, {"value": "dark", "label": "深色"}],
                "accent": accent_options(),
                "scale": scale_options(),
                "font_size": font_size_options(),
                "language": language_options(),
            },
        },
    }
