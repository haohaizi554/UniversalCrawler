"""Host-neutral platform metadata shared by SDK, Web, and CLI hosts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .base import BasePlugin

InteractiveValue = str | int | float | bool | None
AuthMode = Literal["cookie", "none", "unspecified"]


@dataclass(frozen=True, slots=True)
class InteractiveChoice:
    """One terminal-safe choice for a plugin runtime configuration field."""

    label: str
    value: InteractiveValue
    custom: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "custom": self.custom,
        }


@dataclass(frozen=True, slots=True)
class InteractiveField:
    """A plugin-owned configuration field that a host may render as choices."""

    key: str
    prompt: str
    summary_label: str
    choices: tuple[InteractiveChoice, ...]
    custom_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "summary_label": self.summary_label,
            "choices": [choice.to_dict() for choice in self.choices],
            "custom_prompt": self.custom_prompt,
        }


@dataclass(frozen=True, slots=True)
class PlatformAuthSpec:
    """Public authentication guidance without credentials or resolved paths."""

    mode: AuthMode = "unspecified"
    config_key: str = ""
    default_file: str = ""
    cookie_names: tuple[str, ...] = ()
    login_url: str = ""
    login_description: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if self.mode not in {"cookie", "none", "unspecified"}:
            raise ValueError(f"unsupported auth mode: {self.mode}")
        if self.mode == "cookie" and (
            not self.default_file or not self.cookie_names
        ):
            raise ValueError(
                "cookie auth requires default_file and cookie_names"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "config_key": self.config_key,
            "default_file": self.default_file,
            "cookie_names": list(self.cookie_names),
            "login_url": self.login_url,
            "login_description": self.login_description,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class PlatformInteractiveSpec:
    """Plugin-owned guide, fields, and authentication metadata."""

    input_label: str
    examples: tuple[str, ...] = ()
    empty_tip: str = ""
    result_tip: str = ""
    fields: tuple[InteractiveField, ...] = ()
    auth: PlatformAuthSpec = PlatformAuthSpec()

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_label": self.input_label,
            "examples": list(self.examples),
            "empty_tip": self.empty_tip,
            "result_tip": self.result_tip,
            "fields": [field.to_dict() for field in self.fields],
            "auth": self.auth.to_dict(),
        }


def generic_interactive_spec(
    name: str,
    search_placeholder: str,
) -> PlatformInteractiveSpec:
    """Build a safe guide for plugins that predate the richer manifest SPI."""

    return PlatformInteractiveSpec(
        input_label=search_placeholder or "输入关键词或链接",
        empty_tip="请检查输入、登录状态和插件配置。",
        result_tip=f"{name} 将使用插件提供的默认配置执行搜索与下载。",
    )


def plugin_manifest(plugin: BasePlugin) -> dict[str, Any]:
    """Project a plugin into the stable, JSON-safe public host manifest."""

    info: dict[str, Any] = {
        "id": str(plugin.id),
        "name": str(plugin.name),
        "aliases": list(getattr(plugin, "aliases", ())),
        "search_placeholder": str(plugin.get_search_placeholder()),
        "interactive": plugin.get_interactive_spec().to_dict(),
    }
    description = str(getattr(plugin, "description", "") or "")
    if description:
        info["description"] = description

    settings_builder = getattr(plugin, "settings_builder", None)
    if settings_builder is not None:
        try:
            info["settings"] = settings_builder.field_defs
        except (AttributeError, TypeError):
            pass
    return info


__all__ = [
    "AuthMode",
    "InteractiveChoice",
    "InteractiveField",
    "InteractiveValue",
    "PlatformAuthSpec",
    "PlatformInteractiveSpec",
    "generic_interactive_spec",
    "plugin_manifest",
]
