"""Configuration persistence helpers for WebController."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.config import cfg
from app.config.settings import get_setting_default, normalize_download_directory_input
from app.exceptions import ConfigValidationError
from app.web.session_runtime import is_within_root, normalize_directory

DIRECTORY_NOT_AUTHORIZED_MESSAGE = "目录未被当前会话授权访问"

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
        # 这里必须覆盖平台设置快照中所有标记为 editable 的字段；否则 GUI 可改、
        # Web 设置页也能展示，但 PUT /api/config 会在最后一层把同一个字段拒掉。
        "douyin": {"max_items", "timeout"},
        "xiaohongshu": {"max_items", "timeout"},
        "kuaishou": {"max_items", "timeout"},
        "bilibili": {"max_pages", "max_items", "timeout"},
        "missav": {
            "max_items",
            "timeout",
            "individual_only",
            "priority",
            "proxy_type",
            "proxy_app",
            "proxy_port",
            "proxy_url",
        },
    }

    @staticmethod
    def handler_accepts_approved_roots(handler: Callable[..., Any]) -> bool:
        try:
            parameters = inspect.signature(handler).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.name == "approved_roots"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    @staticmethod
    def _normalized_roots(approved_roots: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if approved_roots is None:
            return None
        return tuple(normalize_directory(root) for root in approved_roots if str(root or "").strip())

    @classmethod
    def authorize_path(cls, path: Any, approved_roots: tuple[str, ...] | None) -> str:
        normalized = normalize_directory(str(path or ""))
        roots = cls._normalized_roots(approved_roots)
        if roots is not None and not any(is_within_root(normalized, root) for root in roots):
            raise PermissionError(DIRECTORY_NOT_AUTHORIZED_MESSAGE)
        return normalized

    @classmethod
    def authorize_save_directory(cls, value: Any, approved_roots: tuple[str, ...] | None) -> str:
        normalized = normalize_download_directory_input(value, create=False)
        cls.authorize_path(normalized, approved_roots)
        return normalized

    @staticmethod
    def frontend_action_save_directory(action: str, payload: Mapping[str, Any]) -> tuple[str, Any] | None:
        normalized_action = str(action or "")
        key = str(payload.get("key") or payload.get("name") or "").strip()
        if normalized_action == "change_directory":
            return "directory", payload.get("directory")
        if normalized_action == "update_basic_setting" and key in {"download_directory", "save_directory"}:
            return "value", payload.get("value", payload.get("directory"))
        section = str(payload.get("section") or payload.get("group") or "").strip()
        if normalized_action == "update_setting" and section in {"basic", "common"} and key in {
            "download_directory",
            "save_directory",
        }:
            return "value", payload.get("value")
        return None

    @classmethod
    def validate_config_value(cls, section: str, key: str, value: Any) -> Any:
        """Reject ambiguous boolean values at the Web trust boundary."""
        normalized_section = "common" if section == "basic" else str(section or "").strip()
        normalized_key = "save_directory" if key == "download_directory" else str(key or "").strip()
        if normalized_section == "appearance" and normalized_key == "theme":
            normalized_section = "common"
        try:
            default = get_setting_default(normalized_section, normalized_key)
        except ConfigValidationError:
            return value
        if isinstance(default, bool) and not isinstance(value, bool):
            raise ValueError(f"{normalized_section}.{normalized_key} 必须是布尔值")
        return value

    @staticmethod
    def _validate_boolean_field(payload: Mapping[str, Any], key: str, *, default: bool) -> None:
        value = payload.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{key} 必须是布尔值")

    @classmethod
    def authorize_frontend_action_payload(
        cls,
        action: str,
        payload: Mapping[str, Any],
        approved_roots: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        normalized_payload = dict(payload or {})
        normalized_action = str(action or "").strip()
        if normalized_action == "update_setting":
            section = str(normalized_payload.get("section") or normalized_payload.get("group") or "").strip()
            key = str(normalized_payload.get("key") or normalized_payload.get("name") or "").strip()
            allowlist_section = "common" if section == "basic" else section
            allowlist_key = "save_directory" if key == "download_directory" else key
            if allowlist_section == "appearance" and allowlist_key == "theme":
                allowlist_section = "common"
            if not cls.is_web_config_allowed(allowlist_section, allowlist_key):
                raise ConfigValidationError("该配置项不允许通过 Web 修改")
            cls.validate_config_value(allowlist_section, allowlist_key, normalized_payload.get("value"))
        elif normalized_action == "update_basic_setting":
            key = str(normalized_payload.get("key") or normalized_payload.get("name") or "").strip()
            allowlist_key = "save_directory" if key == "download_directory" else key
            if not cls.is_web_config_allowed("common", allowlist_key):
                raise ConfigValidationError("该配置项不允许通过 Web 修改")
            cls.validate_config_value("common", allowlist_key, normalized_payload.get("value"))
            if allowlist_key == "theme" and "manual" in normalized_payload:
                cls._validate_boolean_field(normalized_payload, "manual", default=True)
        elif normalized_action == "update_download_options":
            allowed = {
                "auto_retry",
                "max_retries",
                "max_concurrent",
                "video_only",
                "image_respects_concurrency",
            }
            if any(str(key) not in allowed for key in normalized_payload):
                raise ConfigValidationError("该配置项不允许通过 Web 修改")
            for key in ("auto_retry", "video_only", "image_respects_concurrency"):
                if key in normalized_payload:
                    cls._validate_boolean_field(normalized_payload, key, default=False)
        elif normalized_action == "refresh_platform_auth_status":
            cls._validate_boolean_field(normalized_payload, "force", default=False)
        elif normalized_action == "register_file_associations":
            cls._validate_boolean_field(normalized_payload, "include_video", default=True)
            cls._validate_boolean_field(normalized_payload, "include_image", default=True)
        directory_request = cls.frontend_action_save_directory(action, normalized_payload)
        if directory_request is None:
            return normalized_payload
        field, value = directory_request
        normalized_payload[field] = cls.authorize_save_directory(value, approved_roots)
        return normalized_payload

    def get_config(self) -> dict:
        return cfg.data

    def set_save_directory(self, directory: str) -> str | None:
        try:
            cfg.set("common", "save_directory", directory)
        except Exception as exc:
            return str(exc)
        return None

    def update_config(
        self,
        updates: dict,
        approved_roots: tuple[str, ...] | None = None,
    ) -> list[ConfigWriteError]:
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
                error = self.update_single_config(
                    str(section),
                    str(key),
                    value,
                    approved_roots=approved_roots,
                )
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

    def update_single_config(
        self,
        section: str,
        key: str,
        value: Any,
        *,
        approved_roots: tuple[str, ...] | None = None,
    ) -> str | None:
        if not self.is_web_config_allowed(section, key):
            return "该配置项不允许通过 Web 修改"
        try:
            value = self.validate_config_value(section, key, value)
            if section == "common" and key == "save_directory":
                value = self.authorize_save_directory(value, approved_roots)
        except (ConfigValidationError, PermissionError, ValueError) as exc:
            return str(exc)
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
