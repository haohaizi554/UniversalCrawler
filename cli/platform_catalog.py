"""把插件注册表投影为稳定、可校验的 CLI 平台目录。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_COMMAND_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class CliPlatform:
    """argparse 注册平台命令所需的最小元数据。"""

    id: str
    name: str
    aliases: tuple[str, ...] = ()


def load_cli_platforms(plugin_registry=None) -> tuple[CliPlatform, ...]:
    """读取插件快照，并拒绝非法或相互冲突的命令名称。"""

    if plugin_registry is None:
        from app.core.plugin_registry import registry

        plugin_registry = registry

    result: list[CliPlatform] = []
    claimed: dict[str, str] = {}
    plugins = sorted(
        plugin_registry.get_all_plugins(),
        key=lambda plugin: (getattr(plugin, "sort_order", 1000), plugin.id),
    )
    for plugin in plugins:
        platform_id = str(plugin.id).strip().lower()
        aliases = tuple(
            str(value).strip().lower()
            for value in getattr(plugin, "aliases", ())
        )
        names = (platform_id, *aliases)
        if any(
            not value or _COMMAND_NAME.fullmatch(value) is None
            for value in names
        ):
            raise ValueError(f"非法 CLI 平台名称: {names!r}")
        for value in names:
            previous = claimed.get(value)
            if previous is not None:
                raise ValueError(
                    f"CLI 平台名称冲突: {value} ({previous}, {platform_id})"
                )
            claimed[value] = platform_id
        result.append(
            CliPlatform(
                id=platform_id,
                name=str(plugin.name),
                aliases=aliases,
            )
        )
    return tuple(result)


def platform_ids(platforms: Iterable[CliPlatform]) -> tuple[str, ...]:
    """返回 argparse choices 使用的规范平台 ID。"""

    return tuple(platform.id for platform in platforms)
