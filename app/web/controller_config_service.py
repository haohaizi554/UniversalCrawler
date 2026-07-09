"""Configuration persistence helpers for WebController."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.config import cfg

@dataclass(frozen=True, slots=True)
class ConfigWriteError:
    section: str
    key: str
    value: Any
    error: str

class WebControllerConfigService:
    """Owns config read/write side effects used by WebController."""

    def __init__(self, action_handler: Callable[[str, Mapping[str, Any]], dict[str, Any]] | None = None) -> None:
        self._action_handler = action_handler

    WEB_CONFIG_ALLOWLIST = {
        "common": {
            "dark_theme",
            "theme",
            "last_source",
            "save_directory",
            "filename_template",
            "open_after_download",
            "default_open_mode",
            "show_browser_window",
        },
        "download": {
            "local_scan_limit",
            "max_concurrent",
            "max_retries",
            "request_timeout",
            "resume_enabled",
            "speed_limit_kb",
            "video_only",
            "image_respects_concurrency",
        },
        "playback": {
            "default_player",
            "remember_position",
            "autoplay_next",
            "manual_image_switch",
            "image_auto_advance_interval_seconds",
        },
        "logging": {
            "retention_days",
            "failed_record_retention_days",
            "ui_log_max_display_count",
            "auto_copy_trace_on_error",
        },
        "appearance": {"follow_system", "accent", "scale", "font_size", "language"},
        "douyin": {"max_items"},
        "xiaohongshu": {"max_items"},
        "kuaishou": {"max_items"},
        "bilibili": {"max_pages", "max_items"},
        "missav": {"individual_only", "priority", "proxy_type", "proxy_app", "proxy_port", "proxy_url"},
    }

    def get_config(self) -> dict:
        return cfg.data

    def set_save_directory(self, directory: str) -> str | None:
        try:
            cfg.set("common", "save_directory", directory)
        except Exception as exc:
            return str(exc)
        return None

    def update_config(self, updates: dict) -> list[ConfigWriteError]:
        errors: list[ConfigWriteError] = []
        for section, values in updates.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if not self.is_web_config_allowed(str(section), str(key)):
                    errors.append(
                        ConfigWriteError(
                            section=str(section),
                            key=str(key),
                            value=value,
                            error="该配置项不允许通过 Web 修改",
                        )
                    )
                    continue
                error = self.update_single_config(str(section), str(key), value)
                if error:
                    errors.append(
                        ConfigWriteError(
                            section=str(section),
                            key=str(key),
                            value=value,
                            error=error,
                        )
                    )
        return errors

    def update_single_config(self, section: str, key: str, value: Any) -> str | None:
        if not self.is_web_config_allowed(section, key):
            return "该配置项不允许通过 Web 修改"
        if self._action_handler is not None:
            result = self._action_handler(
                "update_setting",
                {"section": section, "key": key, "value": value},
            )
            if isinstance(result, Mapping) and result.get("status") == "ok":
                return None
            return str((result or {}).get("message") or "配置更新失败")
        try:
            cfg.set(section, key, value)
        except Exception as exc:
            return str(exc)
        return None

    @classmethod
    def is_web_config_allowed(cls, section: str, key: str) -> bool:
        return key in cls.WEB_CONFIG_ALLOWLIST.get(section, set())
