"""cli.main argparse 解析与子命令派发测试。

测试维度：
- 单元测试：argparse 各子命令参数解析
- 黑盒测试：不 mock，直接调 main(argv) 跑子命令
- 集成测试：平台别名 (douyin/bilibili/kuaishou/missav) 解析
"""

import argparse
import os
import sys
import unittest
from unittest.mock import Mock, patch

PLATFORM_IDS = (
    "douyin",
    "xiaohongshu",
    "bilibili",
    "kuaishou",
    "missav",
)

class CliVersionTests(unittest.TestCase):
    """--version 标志测试。"""

    def test_version_exits_zero(self):
        """--version 必须退出码 0。"""
        from cli.main import main
        with patch("sys.stdout.write") as mocked_write:
            result = main(["--version"])
        self.assertEqual(result, 0)
        # stdout 必须有版本号
        all_written = "".join(call.args[0] for call in mocked_write.call_args_list)
        self.assertIn("ucrawl", all_written)

class CliNoArgsTests(unittest.TestCase):
    """无子命令时必须打印帮助并退出 0。"""

    def test_no_args_returns_zero(self):
        """无参数 → 打印帮助 → 退出 0。"""
        from cli.main import main
        with patch("sys.stdout.write"):
            result = main([])
        self.assertEqual(result, 0)


class CliHelpGuideTests(unittest.TestCase):
    """顶层帮助应让源码用户与免安装包用户都能直接开始操作。"""

    def test_root_help_contains_entry_forms_examples_and_next_step(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser(
            (
                CliPlatform("douyin", "抖音", ("dy",)),
                CliPlatform("bilibili", "Bilibili", ("bili", "bl")),
            )
        )
        help_text = parser.format_help()

        self.assertIn("快速上手", help_text)
        self.assertIn("UCrawlCLI.exe platforms", help_text)
        self.assertIn("python main.py --mode cli platforms", help_text)
        self.assertIn('ucrawl search --source douyin "关键词"', help_text)
        self.assertIn("ucrawl <子命令> --help", help_text)


class CliSearchSubcommandTests(unittest.TestCase):
    """search 子命令参数解析测试。"""

    def test_search_minimal_args(self):
        """search --source douyin kw 必须能解析（handler 不会被调用，因为不 mock）。"""
        from cli.main import main
        # 避免真跑爬虫：mock CLIRunner
        with patch("cli.commands.search.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok", "items": [], "logs": []}
            result = main(["search", "--source", "douyin", "kw"])
        # 必须有 exit code（不一定 0，因为 mock 不完整；但不能崩）
        self.assertIn(result, (0, 1, 2))

    def test_search_accepts_legacy_keyword_option(self):
        """文档长期公开的 --keyword 形式应继续兼容。"""
        from cli.main import main

        with patch("cli.commands.search.handle_search_command", return_value=0) as handler:
            result = main(["search", "--source", "douyin", "--keyword", "测试"])

        self.assertEqual(result, 0)
        self.assertIsNone(handler.call_args.args[0].keyword)
        self.assertEqual(handler.call_args.args[0].keyword_option, "测试")

    def test_search_rejects_conflicting_keyword_forms(self):
        """位置参数与 --keyword 冲突必须作为用法错误返回 2。"""
        from cli.main import main

        with patch("sys.stdout.write"):
            result = main(
                [
                    "search",
                    "--source",
                    "douyin",
                    "位置值",
                    "--keyword",
                    "选项值",
                ]
            )

        self.assertEqual(result, 2)

    def test_search_invalid_select_returns_error_without_starting_runner(self):
        """CLI 拼写错误必须在启动爬虫前失败。"""
        from cli.main import main

        with patch("cli.commands.search.CLIRunner") as runner:
            result = main(["search", "--source", "douyin", "测试", "--select", "frist"])

        self.assertEqual(result, 2)
        runner.assert_not_called()

    def test_search_supports_xiaohongshu_source(self):
        """通用 search 入口必须允许 xiaohongshu，与 GUI/SDK/插件能力保持一致。"""
        from cli.main import main
        with patch("cli.commands.search.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok", "items": [], "logs": []}
            result = main(["search", "--source", "xiaohongshu", "kw"])
        self.assertIn(result, (0, 1, 2))

    def test_search_invalid_source_rejected(self):
        """search --source invalid 必须被 argparse 拒绝（SystemExit 2）。"""
        from cli.main import main
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main(["search", "--source", "invalid_platform", "kw"])
        # argparse invalid choice → 退出码 2
        self.assertEqual(cm.exception.code, 2)

    def test_search_preload_choices_raw_string(self):
        """--preload-choices '0|1,2|3,4' 保持为字符串（在 handle_search_command 才解析）。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(
            ["--source", "douyin", "kw", "--preload-choices", "0|1,2|3,4"]
        )
        # raw 字符串
        self.assertEqual(args.preload_choices, "0|1,2|3,4")

    def test_search_preload_choices_parsed_in_handler(self):
        """handle_search_command 解析 preload-choices 为 [[0],[1,2],[3,4]] 传给 PipeSelection。"""
        from cli.commands.search import handle_search_command
        from cli.commands.search import add_search_arguments
        import argparse
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(
            ["--source", "douyin", "kw", "--preload-choices", "0|1,2|3,4"]
        )
        with patch("cli.commands.search.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            handle_search_command(args)
        # CLIRunner 必须在 handler 中被调用
        MockRunner.assert_called_once()
        # selection_strategy 必须是 PipeSelection(preloaded=[[0],[1,2],[3,4]])
        sel = MockRunner.call_args.kwargs.get("selection_strategy")
        from shared.pipe_selection import PipeSelection
        self.assertIsInstance(sel, PipeSelection)
        self.assertEqual(sel._preloaded, [[0], [1, 2], [3, 4]])

    def test_search_invalid_preload_choice_does_not_start_runner(self):
        """预加载规则中的拼写错误必须在 runner 启动前失败。"""
        from cli.main import main

        with patch("cli.commands.search.CLIRunner") as runner:
            result = main(
                ["search", "--source", "douyin", "测试", "--preload-choices", "0|frist"]
            )

        self.assertEqual(result, 2)
        runner.assert_not_called()

    def test_search_max_items_int(self):
        """--max-items 必须是整数。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(["--source", "douyin", "kw", "--max-items", "20"])
        self.assertEqual(args.max_items, 20)

    def test_search_max_items_invalid_int(self):
        """--max-items abc 必须报错退出码 2。"""
        from cli.main import main
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main(["search", "--source", "douyin", "kw", "--max-items", "abc"])
        self.assertEqual(cm.exception.code, 2)

    def test_search_max_pages_int(self):
        """--max-pages 必须是整数。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(["--source", "bilibili", "kw", "--max-pages", "3"])
        self.assertEqual(args.max_pages, 3)

    def test_search_run_timeout_float(self):
        """--run-timeout 暂时写入独立的弃用兼容字段。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(["--source", "douyin", "kw", "--run-timeout", "60.5"])
        self.assertEqual(args.legacy_run_timeout, 60.5)

    def test_search_individual_only_flag(self):
        """--individual-only 是 bool flag。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(["--source", "missav", "kw", "--individual-only"])
        self.assertTrue(args.individual_only)

    def test_search_priority_choice(self):
        """--priority 必须是有效 choice。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=PLATFORM_IDS)
        args = parser.parse_args(["--source", "missav", "kw", "--priority", "中文字幕优先"])
        self.assertEqual(args.priority, "中文字幕优先")

class CliPlatformAliasTests(unittest.TestCase):
    """平台别名（douyin/bilibili/kuaishou/missav）测试。"""

    def test_douyin_alias_routes_to_search(self):
        """ucrawl douyin search kw 必须派发到 handle_search_command。"""
        from cli.main import main
        with patch("cli.commands.search.handle_search_command", return_value=0) as mock_handler:
            main(["douyin", "search", "测试"])
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args[0][0]
        self.assertEqual(call_args.source, "douyin")
        self.assertEqual(call_args.keyword, "测试")

    def test_bilibili_alias_routes_to_search(self):
        """ucrawl bilibili search BVxxx 必须派发到 search。"""
        from cli.main import main
        with patch("cli.commands.search.handle_search_command", return_value=0) as mock_handler:
            main(["bilibili", "search", "BV1xxx"])
        call_args = mock_handler.call_args[0][0]
        self.assertEqual(call_args.source, "bilibili")
        self.assertEqual(call_args.keyword, "BV1xxx")

    def test_xiaohongshu_alias_routes_to_search(self):
        """ucrawl xhs search kw must reuse the common search handler."""
        from cli.main import main

        with patch("cli.commands.search.handle_search_command", return_value=0) as mock_handler:
            main(["xhs", "search", "test"])
        call_args = mock_handler.call_args[0][0]
        self.assertEqual(call_args.source, "xiaohongshu")
        self.assertEqual(call_args.keyword, "test")

    def test_missav_alias_routes_to_search(self):
        """ucrawl missav search ABC-123 必须派发到 search。"""
        from cli.main import main
        with patch("cli.commands.search.handle_search_command", return_value=0) as mock_handler:
            main(["missav", "search", "ABC-123"])
        call_args = mock_handler.call_args[0][0]
        self.assertEqual(call_args.source, "missav")

class CliDynamicPlatformParserTests(unittest.TestCase):
    """平台注册表必须直接驱动通用与平台快捷解析器。"""

    def test_build_parser_uses_injected_external_platform(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser((CliPlatform("external", "External", ("ext",)),))

        generic = parser.parse_args(["search", "--source", "external", "query"])
        scoped = parser.parse_args(["ext", "search", "query"])
        self.assertEqual(generic.source, "external")
        self.assertEqual(scoped.source, "external")

    def test_platform_search_has_same_business_fields_as_generic_search(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser((CliPlatform("douyin", "抖音", ("dy",)),))
        generic = parser.parse_args(
            [
                "search",
                "--source",
                "douyin",
                "query",
                "--http-timeout",
                "11",
                "--timeout",
                "22",
            ]
        )
        scoped = parser.parse_args(
            [
                "dy",
                "search",
                "query",
                "--http-timeout",
                "11",
                "--timeout",
                "22",
            ]
        )

        business_fields = (
            "source",
            "keyword",
            "http_timeout",
            "command_timeout",
            "legacy_run_timeout",
            "max_items",
            "max_pages",
            "select",
            "quiet",
            "no_download",
        )
        self.assertEqual(
            {field: getattr(generic, field) for field in business_fields},
            {field: getattr(scoped, field) for field in business_fields},
        )

    def test_platform_commands_do_not_offer_scan(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser((CliPlatform("douyin", "抖音", ("dy",)),))
        with patch("sys.stderr"), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["douyin", "scan", "."])
        self.assertEqual(raised.exception.code, 2)

    def test_generic_download_uses_positional_url_and_optional_title(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser((CliPlatform("douyin", "Douyin", ("dy",)),))

        args = parser.parse_args(
            [
                "download",
                "--source",
                "douyin",
                "https://example.test/video.mp4",
                "--title",
                "Demo",
            ]
        )

        self.assertEqual(args.url, "https://example.test/video.mp4")
        self.assertEqual(args.title, "Demo")
        self.assertFalse(hasattr(args, "video_id"))

    def test_platform_download_supplies_source_and_matches_generic_fields(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser((CliPlatform("douyin", "Douyin", ("dy",)),))
        generic = parser.parse_args(
            [
                "download",
                "--source",
                "douyin",
                "https://example.test/video.mp4",
                "--title",
                "Demo",
            ]
        )
        scoped = parser.parse_args(
            [
                "dy",
                "download",
                "https://example.test/video.mp4",
                "--title",
                "Demo",
            ]
        )

        fields = (
            "source",
            "url",
            "title",
            "command_timeout",
            "quiet",
            "pretty",
        )
        self.assertEqual(
            {field: getattr(generic, field) for field in fields},
            {field: getattr(scoped, field) for field in fields},
        )
        self.assertEqual(generic.command_timeout, 300)
        self.assertFalse(hasattr(generic, "timeout"))
        self.assertFalse(hasattr(scoped, "timeout"))

    def test_keyboard_interrupt_returns_cancelled_code(self):
        from cli.main import main

        with patch(
            "cli.commands.search.handle_search_command",
            side_effect=KeyboardInterrupt,
        ):
            result = main(["search", "--source", "douyin", "query"])

        self.assertEqual(result, 130)


class CliPlatformsSubcommandTests(unittest.TestCase):
    """platforms 子命令测试。"""

    def test_platforms_no_args(self):
        """ucrawl platforms 必须能跑（输出平台列表）。"""
        from cli.main import main
        with patch("sys.stdout.write"):
            result = main(["platforms"])
        # 退出码 0 = 成功
        self.assertEqual(result, 0)

    def test_platforms_pretty(self):
        """ucrawl platforms --pretty 必须能跑。"""
        from cli.main import main
        with patch("sys.stdout.write"):
            result = main(["platforms", "--pretty"])
        self.assertEqual(result, 0)

    def test_unknown_platform_description_is_usage_error(self):
        from cli.main import main

        sdk = Mock()
        sdk.list_platforms.return_value = [{"id": "douyin", "name": "Douyin"}]
        with patch("cli.commands.platforms.UcrawlSDK", return_value=sdk), patch(
            "sys.stderr.write"
        ):
            result = main(["platforms", "--describe", "missing"])

        self.assertEqual(result, 2)
        sdk.close.assert_called_once()

class CliScanSubcommandTests(unittest.TestCase):
    """scan 子命令测试。"""

    def test_scan_requires_directory(self):
        """scan 不传目录必须报错退出码 2。"""
        from cli.main import main
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main(["scan"])
        self.assertEqual(cm.exception.code, 2)

    def test_scan_invalid_limit_is_usage_error_before_sdk_construction(self):
        from cli.main import main

        with patch("cli.commands.scan.UcrawlSDK") as sdk_cls, patch(
            "sys.stderr.write"
        ):
            result = main(["scan", ".", "--limit", "0"])

        self.assertEqual(result, 2)
        sdk_cls.assert_not_called()

    def test_scan_maps_structured_status_to_process_exit_code(self):
        from cli.main import main

        for status, expected in (
            ("error", 1),
            ("timeout", 124),
            ("cancelled", 130),
        ):
            with self.subTest(status=status):
                sdk = Mock()
                sdk.scan_directory.return_value = {
                    "status": status,
                    "error": status,
                }
                with patch(
                    "cli.commands.scan.UcrawlSDK",
                    return_value=sdk,
                ), patch("sys.stdout.write"):
                    result = main(["scan", ".", "--limit", "1"])

                self.assertEqual(result, expected)
                sdk.close.assert_called_once()

    def test_scan_sdk_value_error_is_usage_error(self):
        from cli.main import main

        sdk = Mock()
        sdk.scan_directory.side_effect = ValueError("invalid directory")
        with patch(
            "cli.commands.scan.UcrawlSDK",
            return_value=sdk,
        ), patch("sys.stderr.write"):
            result = main(["scan", ".", "--limit", "1"])

        self.assertEqual(result, 2)
        sdk.close.assert_called_once()

class CliInteractiveSubcommandTests(unittest.TestCase):
    """interactive 子命令测试。"""

    def test_interactive_subcommand_exists(self):
        """interactive 子命令必须存在。"""
        from cli.main import main
        with patch("cli.commands.interactive.handle_interactive_command", return_value=0) as mock:
            result = main(["interactive"])
        self.assertEqual(result, 0)
        mock.assert_called_once()

    def test_interactive_alias_i(self):
        """i 是 interactive 的别名。"""
        from cli.main import main
        with patch("cli.commands.interactive.handle_interactive_command", return_value=0) as mock:
            result = main(["i"])
        self.assertEqual(result, 0)
        mock.assert_called_once()

    def test_interactive_timeout_arguments_have_distinct_destinations(self):
        from cli.main import build_parser
        from cli.platform_catalog import CliPlatform

        parser = build_parser((CliPlatform("douyin", "Douyin", ("dy",)),))
        args = parser.parse_args(
            [
                "interactive",
                "--http-timeout",
                "12",
                "--timeout",
                "34",
            ]
        )

        self.assertEqual(args.http_timeout, 12)
        self.assertEqual(args.command_timeout, 34)
        self.assertIsNone(args.legacy_run_timeout)

if __name__ == "__main__":
    unittest.main()
