"""平台快捷子命令必须稳定映射到统一 search 命令。"""

from __future__ import annotations

import argparse

from cli.commands import _alias


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    _alias.add_platform_alias_subparser(parser.add_subparsers(dest="platform"))
    return parser


def test_platform_alias_parser_supplies_fixed_source() -> None:
    args = _parser().parse_args(["bilibili", "search", "测试关键词"])

    assert args.platform == "bilibili"
    assert args.source == "bilibili"
    assert args._platform_source == "bilibili"
    assert args.keyword == "测试关键词"


def test_platform_alias_without_search_subcommand_is_rejected() -> None:
    args = _parser().parse_args(["douyin"])

    assert _alias.handle_platform_alias(args) == 2


def test_platform_alias_delegates_to_shared_search_handler(monkeypatch) -> None:
    args = _parser().parse_args(["kuaishou", "search", "猫"])
    captured: list[argparse.Namespace] = []
    monkeypatch.setattr(
        _alias,
        "handle_search_command",
        lambda value: captured.append(value) or 7,
    )

    assert _alias.handle_platform_alias(args) == 7
    assert captured == [args]
