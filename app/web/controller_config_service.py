"""Configuration persistence helpers for WebController."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import cfg

@dataclass(frozen=True, slots=True)
class ConfigWriteError:
    section: str
    key: str
    value: Any
    error: str

class WebControllerConfigService:
    """Owns config read/write side effects used by WebController."""

    WEB_CONFIG_ALLOWLIST = {
        "common": {"dark_theme", "theme", "last_source"},
        "download": {"local_scan_limit", "max_concurrent"},
        "douyin": {"max_items"},
        "xiaohongshu": {"max_items"},
        "kuaishou": {"max_items"},
        "bilibili": {"max_pages"},
        "missav": {"individual_only", "priority", "proxy_type", "proxy_port", "proxy_url"},
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
                try:
                    cfg.set(section, key, value)
                except Exception as exc:
                    errors.append(
                        ConfigWriteError(
                            section=str(section),
                            key=str(key),
                            value=value,
                            error=str(exc),
                        )
                    )
        return errors

    def update_single_config(self, section: str, key: str, value: Any) -> str | None:
        if not self.is_web_config_allowed(section, key):
            return "该配置项不允许通过 Web 修改"
        try:
            cfg.set(section, key, value)
        except Exception as exc:
            return str(exc)
        return None

    @classmethod
    def is_web_config_allowed(cls, section: str, key: str) -> bool:
        return key in cls.WEB_CONFIG_ALLOWLIST.get(section, set())
