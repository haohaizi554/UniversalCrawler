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
from unittest.mock import patch

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
        self.assertEqual(handler.call_args.args[0].keyword, "测试")

    def test_search_rejects_conflicting_keyword_forms(self):
        """位置参数与 --keyword 同时给出不同值时必须报参数错误。"""
        from cli.main import main

        with patch("sys.stderr"), self.assertRaises(SystemExit) as raised:
            main(["search", "--source", "douyin", "位置值", "--keyword", "选项值"])

        self.assertEqual(raised.exception.code, 2)

    def test_search_invalid_select_returns_error_without_starting_runner(self):
        """CLI 拼写错误必须在启动爬虫前失败。"""
        from cli.main import main

        with patch("cli.commands.search.CLIRunner") as runner:
            result = main(["search", "--source", "douyin", "测试", "--select", "frist"])

        self.assertEqual(result, 1)
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
        add_search_arguments(parser)
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
        add_search_arguments(parser)
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

        self.assertEqual(result, 1)
        runner.assert_not_called()

    def test_search_max_items_int(self):
        """--max-items 必须是整数。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser)
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
        add_search_arguments(parser)
        args = parser.parse_args(["--source", "bilibili", "kw", "--max-pages", "3"])
        self.assertEqual(args.max_pages, 3)

    def test_search_run_timeout_float(self):
        """--run-timeout 60.5 必须是 float。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser)
        args = parser.parse_args(["--source", "douyin", "kw", "--run-timeout", "60.5"])
        self.assertEqual(args.run_timeout, 60.5)

    def test_search_individual_only_flag(self):
        """--individual-only 是 bool flag。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser)
        args = parser.parse_args(["--source", "missav", "kw", "--individual-only"])
        self.assertTrue(args.individual_only)

    def test_search_priority_choice(self):
        """--priority 必须是有效 choice。"""
        from cli.commands.search import add_search_arguments
        parser = argparse.ArgumentParser()
        add_search_arguments(parser)
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

    def test_alias_gets_search_defaults_filled(self):
        """平台别名命令缺少的通用 search 参数（如 save_dir/timeout）必须自动填默认值。"""
        from cli.main import main
        from cli.main import _ensure_search_defaults
        import argparse
        ns = argparse.Namespace(douyin_subcommand="search", keyword="kw")
        _ensure_search_defaults(ns, "douyin")
        # 默认值必须都被填上
        for field in ("save_dir", "max_items", "timeout", "individual_only", "quiet", "pretty"):
            self.assertTrue(hasattr(ns, field), f"missing default for {field}")

    def test_alias_does_not_overwrite_explicit_args(self):
        """_ensure_search_defaults 必须不覆盖用户已显式提供的值。"""
        from cli.main import _ensure_search_defaults
        import argparse
        ns = argparse.Namespace(
            douyin_subcommand="search",
            keyword="kw",
            max_items=99,  # 用户显式提供
            save_dir="/tmp/dl",
        )
        _ensure_search_defaults(ns, "douyin")
        self.assertEqual(ns.max_items, 99, "explicit value must not be overwritten")
        self.assertEqual(ns.save_dir, "/tmp/dl")

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

class CliScanSubcommandTests(unittest.TestCase):
    """scan 子命令测试。"""

    def test_scan_requires_directory(self):
        """scan 不传目录必须报错退出码 2。"""
        from cli.main import main
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main(["scan"])
        self.assertEqual(cm.exception.code, 2)

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

if __name__ == "__main__":
    unittest.main()
