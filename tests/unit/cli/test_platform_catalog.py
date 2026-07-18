"""CLI 平台目录必须完全由插件元数据生成。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cli.platform_catalog import load_cli_platforms, platform_ids


class _FakeRegistry:
    def __init__(self, plugins):
        self._plugins = list(plugins)

    def get_all_plugins(self):
        return list(self._plugins)


def _plugin(
    plugin_id: str,
    name: str,
    sort_order: int,
    aliases: tuple[str, ...] = (),
):
    return SimpleNamespace(
        id=plugin_id,
        name=name,
        sort_order=sort_order,
        aliases=aliases,
    )


def test_catalog_is_sorted_and_includes_external_plugin_aliases() -> None:
    catalog = load_cli_platforms(
        _FakeRegistry(
            [
                _plugin("third", "Third", 30, ("t3",)),
                _plugin("first", "First", 10, ("f1",)),
            ]
        )
    )

    assert platform_ids(catalog) == ("first", "third")
    assert catalog[1].aliases == ("t3",)


@pytest.mark.parametrize(
    "plugins",
    [
        [
            _plugin("one", "One", 1, ("shared",)),
            _plugin("two", "Two", 2, ("shared",)),
        ],
        [
            _plugin("one", "One", 1, ("two",)),
            _plugin("two", "Two", 2),
        ],
        [_plugin("Bad Name", "Bad", 1)],
    ],
)
def test_catalog_rejects_invalid_or_conflicting_command_names(plugins) -> None:
    with pytest.raises(ValueError):
        load_cli_platforms(_FakeRegistry(plugins))
