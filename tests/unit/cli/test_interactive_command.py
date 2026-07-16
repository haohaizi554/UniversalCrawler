"""交互式引导命令回归测试。"""

from __future__ import annotations

import argparse
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

class InteractiveCommandTests(unittest.TestCase):
    """覆盖 interactive 子命令与 GUI 对齐的关键行为。"""

    def _make_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            save_dir=None,
            no_download=False,
            pretty=False,
            run_timeout=None,
            quiet=False,
            config=None,
            select_all=False,
            first=False,
            last=False,
            select=None,
            exclude=None,
            pipe=False,
            preload_choices=None,
            cookie=None,
            download_strategy=None,
            referer=None,
            ua=None,
            folder_name=None,
            use_subdir=None,
            file_name=None,
            content_type=None,
        )

    def test_interactive_persists_save_dir_and_runs_cli_runner_once(self):
        """交互式引导应写回保存目录，并直接复用 CLIRunner 搜索下载链路。"""
        from cli.commands.interactive import handle_interactive_command

        sdk = Mock()
        sdk.list_platforms.return_value = [
            {"id": "douyin", "name": "抖音", "search_placeholder": "输入关键词"},
        ]
        runner = Mock()
        runner.run.return_value = {
            "status": "ok",
            "elapsed": 1.2,
            "items": [
                {
                    "title": "测试视频",
                    "status": "✅ 完成",
                    "local_path": r"D:\Downloads\UCP\测试视频.mp4",
                    "content_type": "video",
                }
            ],
        }

        with patch("cli.commands.interactive.UcrawlSDK", return_value=sdk), patch(
            "cli.commands.interactive.CLIRunner",
            return_value=runner,
        ) as mock_runner_cls, patch(
            "cli.commands.interactive.get_default_save_dir",
            return_value=r"D:\Downloads\UCP",
        ), patch("cli.commands.interactive._is_temp_dir", return_value=False), patch(
            "cli.commands.interactive._load_cookie",
            return_value={"sessionid_ss": "cookie-value"},
        ), patch("cli.commands.interactive._check_cookie_valid", return_value=True), patch(
            "cli.commands.interactive._find_cookie_file",
            return_value=Path("dy_auth.json"),
        ), patch(
            "cli.commands.interactive.cfg.set"
        ) as mock_cfg_set, patch(
            "builtins.input",
            side_effect=["1", "测试关键词", "1", "", "y", ""],
        ):
            exit_code = handle_interactive_command(self._make_args())

        self.assertEqual(exit_code, 0)
        mock_cfg_set.assert_called_once_with("common", "save_directory", r"D:\Downloads\UCP")
        mock_runner_cls.assert_called_once()
        runner_kwargs = mock_runner_cls.call_args.kwargs
        self.assertEqual(runner_kwargs["source"], "douyin")
        self.assertEqual(runner_kwargs["keyword"], "测试关键词")
        self.assertEqual(runner_kwargs["save_dir"], r"D:\Downloads\UCP")
        self.assertTrue(runner_kwargs["download"])
        self.assertEqual(runner_kwargs["config"]["max_items"], 1)
        self.assertEqual(runner_kwargs["config"]["timeout"], 30)
        self.assertIsNone(runner_kwargs["timeout"])
        runner.run.assert_called_once()
        self.assertTrue(sdk.close.called)

    def test_confirmation_renders_the_normalized_runner_config(self):
        """确认页必须展示合并后的最终配置，不能确认一套、执行另一套。"""
        from cli.commands.interactive import handle_interactive_command

        args = self._make_args()
        args.config = '{"max_items": 7, "timeout": 90}'
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {"id": "douyin", "name": "抖音", "search_placeholder": "输入关键词"},
        ]
        runner = Mock()
        runner.run.return_value = {"status": "ok", "elapsed": 0.1, "items": []}
        output = io.StringIO()

        with patch("cli.commands.interactive.UcrawlSDK", return_value=sdk), patch(
            "cli.commands.interactive.CLIRunner", return_value=runner
        ) as runner_cls, patch(
            "cli.commands.interactive.get_default_save_dir", return_value=r"D:\Downloads\UCP"
        ), patch("cli.commands.interactive._is_temp_dir", return_value=False), patch(
            "cli.commands.interactive._load_cookie", return_value={"sessionid_ss": "cookie"}
        ), patch("cli.commands.interactive._check_cookie_valid", return_value=True), patch(
            "cli.commands.interactive._find_cookie_file", return_value=Path("dy_auth.json")
        ), patch("cli.commands.interactive.cfg.set"), patch(
            "builtins.input", side_effect=["1", "测试关键词", "1", "", "y", ""]
        ), patch("sys.stdout", output):
            exit_code = handle_interactive_command(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("视频数: 7", output.getvalue())
        self.assertEqual(runner_cls.call_args.kwargs["config"]["max_items"], 7)
        self.assertEqual(runner_cls.call_args.kwargs["config"]["timeout"], 90)

    def test_interactive_invalid_selection_rule_returns_error_without_runner(self):
        """TUI 的显式选择拼写错误必须结构化失败，而不是抛 traceback。"""
        from cli.commands.interactive import handle_interactive_command

        args = self._make_args()
        args.select = "frist"
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {"id": "douyin", "name": "抖音", "search_placeholder": "输入关键词"},
        ]
        error = io.StringIO()

        with patch("cli.commands.interactive.UcrawlSDK", return_value=sdk), patch(
            "cli.commands.interactive.CLIRunner"
        ) as runner_cls, patch(
            "cli.commands.interactive.get_default_save_dir", return_value=r"D:\Downloads\UCP"
        ), patch("cli.commands.interactive._is_temp_dir", return_value=False), patch(
            "cli.commands.interactive._load_cookie", return_value={"sessionid_ss": "cookie"}
        ), patch("cli.commands.interactive._check_cookie_valid", return_value=True), patch(
            "cli.commands.interactive._find_cookie_file", return_value=Path("dy_auth.json")
        ), patch("cli.commands.interactive.cfg.set"), patch(
            "builtins.input", side_effect=["1", "测试关键词", "1", "", "y"]
        ), patch("sys.stderr", error):
            result = handle_interactive_command(args)

        self.assertEqual(result, 1)
        self.assertIn("frist", error.getvalue())
        runner_cls.assert_not_called()

    def test_persist_save_dir_skips_temporary_directory(self):
        """系统临时目录只用于当前会话，不应写回全局配置。"""
        from cli.commands.interactive import _persist_save_dir

        with patch("cli.commands.interactive._is_temp_dir", return_value=True), patch(
            "cli.commands.interactive.cfg.set"
        ) as mock_cfg_set:
            _persist_save_dir(r"C:\Users\demo\AppData\Local\Temp\tmpabc123")

        mock_cfg_set.assert_not_called()

    def test_build_config_summary_lines_are_platform_specific(self):
        """不同平台的确认摘要应体现各自 GUI 配置语义。"""
        from cli.commands.interactive import _build_config_summary_lines

        douyin_lines = _build_config_summary_lines(
            "douyin",
            {"max_items": 5, "timeout": 30},
            "抖音",
            "测试关键词",
            r"D:\Downloads\UCP",
        )
        missav_lines = _build_config_summary_lines(
            "missav",
            {"individual_only": True, "priority": "中文字幕优先", "proxy": "http://127.0.0.1:7890"},
            "MissAV",
            "SSIS-001",
            r"D:\Downloads\UCP",
        )

        self.assertTrue(any("视频数" in line for line in douyin_lines))
        self.assertTrue(any("浏览器扫码" in line for line in douyin_lines))
        self.assertTrue(any("仅单体" in line for line in missav_lines))
        self.assertTrue(any("代理" in line for line in missav_lines))

    def test_download_summary_tolerates_null_titles(self):
        from cli.commands.interactive import _print_download_summary

        output = io.StringIO()
        with patch("sys.stdout", output):
            _print_download_summary(
                [{"title": None, "id": None, "status": "❌ 失败", "error": "network"}],
                elapsed=1.0,
                save_dir=r"D:\Downloads\UCP",
            )

        self.assertIn("未知", output.getvalue())

    def test_xiaohongshu_summary_hides_search_page_count(self):
        """小红书交互摘要只暴露目标数量，不再要求用户理解搜索页数。"""
        from cli.commands.interactive import _build_config_summary_lines

        lines = _build_config_summary_lines(
            "xiaohongshu",
            {"max_items": 20, "search_max_pages": 5},
            "小红书",
            "摄影",
            r"D:\Downloads\UCP",
        )

        self.assertTrue(any("笔记数" in line for line in lines))
        self.assertFalse(any("搜索页" in line for line in lines))

    def test_kuaishou_guide_mentions_share_link(self):
        """快手交互提示应与 GUI/WebUI 同步，明确支持分享链接。"""
        from cli.commands.interactive import _PLATFORM_GUIDE

        guide = _PLATFORM_GUIDE["kuaishou"]

        self.assertIn("分享链接", guide["input_label"])
        self.assertTrue(any("分享链接" in line for line in guide["examples"]))
        self.assertIn("分享链接", guide["empty_tip"])

    def test_interactive_xiaohongshu_skips_search_page_prompt(self):
        """小红书交互式配置只询问目标数量，不再额外询问搜索页数。"""
        from cli.commands.interactive import handle_interactive_command

        sdk = Mock()
        sdk.list_platforms.return_value = [
            {"id": "xiaohongshu", "name": "小红书", "search_placeholder": "输入关键词"},
        ]
        runner = Mock()
        runner.run.return_value = {"status": "ok", "elapsed": 0.8, "items": []}

        with patch("cli.commands.interactive.UcrawlSDK", return_value=sdk), patch(
            "cli.commands.interactive.CLIRunner",
            return_value=runner,
        ) as mock_runner_cls, patch(
            "cli.commands.interactive.get_default_save_dir",
            return_value=r"D:\Downloads\UCP",
        ), patch("cli.commands.interactive._is_temp_dir", return_value=False), patch(
            "cli.commands.interactive._load_cookie",
            return_value={"a1": "cookie-value"},
        ), patch("cli.commands.interactive._check_cookie_valid", return_value=True), patch(
            "cli.commands.interactive._find_cookie_file",
            return_value=Path("xhs_auth.json"),
        ), patch(
            "cli.commands.interactive.cfg.set"
        ), patch(
            "builtins.input",
            side_effect=["1", "摄影", "1", "", "y", ""],
        ):
            exit_code = handle_interactive_command(self._make_args())

        self.assertEqual(exit_code, 0)
        runner_kwargs = mock_runner_cls.call_args.kwargs
        self.assertEqual(runner_kwargs["source"], "xiaohongshu")
        self.assertEqual(runner_kwargs["config"]["max_items"], 1)
        self.assertEqual(runner_kwargs["config"]["search_max_pages"], 5)

    def test_prompt_post_run_action_supports_open_and_switch(self):
        """完成后动作支持先打开目录，再切换平台继续。"""
        from cli.commands.interactive import _prompt_post_run_action

        with patch("cli.commands.interactive.os.startfile") as mock_startfile, patch(
            "builtins.input",
            side_effect=["o", "p"],
        ):
            action = _prompt_post_run_action(r"D:\Downloads\UCP", allow_repeat=True)

        mock_startfile.assert_called_once_with(r"D:\Downloads\UCP")
        self.assertEqual(action, "switch")

    def test_choose_retries_until_valid_input(self):
        """菜单选择在输入非法值时应允许重试。"""
        from cli.commands.interactive import _choose

        with patch("builtins.input", side_effect=["abc", "9", "2"]):
            result = _choose("视频数量", ["1", "2", "5"], default_idx=0)

        self.assertEqual(result, 1)

    def test_interactive_respects_quiet_flag_when_building_sdk(self):
        """quiet 模式下应关闭 SDK verbose 输出。"""
        from cli.commands.interactive import handle_interactive_command

        args = self._make_args()
        args.quiet = True
        sdk = Mock()
        sdk.list_platforms.return_value = []

        with patch("cli.commands.interactive.UcrawlSDK", return_value=sdk) as sdk_cls, patch(
            "builtins.input",
            side_effect=[EOFError()],
        ):
            handle_interactive_command(args)

        sdk_cls.assert_called_once_with(verbose=False)

    def test_interactive_defaults_to_tty_selection_to_avoid_gui_crash(self):
        """未显式指定规则时，交互式引导默认使用 TTY 选择，避免 GUISelection native crash。"""
        from cli.commands.interactive import handle_interactive_command
        from shared.interactive_selection import InteractiveTTYSelection

        sdk = Mock()
        sdk.list_platforms.return_value = [
            {"id": "bilibili", "name": "Bilibili", "search_placeholder": "输入 BV 号"},
        ]
        runner = Mock()
        runner.run.return_value = {"status": "ok", "elapsed": 0.8, "items": []}

        fake_stdin = io.StringIO("a\n")
        fake_stdout = io.StringIO()

        with patch("cli.commands.interactive.UcrawlSDK", return_value=sdk), patch(
            "cli.commands.interactive.CLIRunner",
            return_value=runner,
        ) as mock_runner_cls, patch(
            "cli.commands.interactive.get_default_save_dir",
            return_value=r"D:\Downloads\UCP",
        ), patch("cli.commands.interactive._is_temp_dir", return_value=False), patch(
            "cli.commands.interactive._load_cookie",
            return_value={"SESSDATA": "cookie-value"},
        ), patch("cli.commands.interactive._check_cookie_valid", return_value=True), patch(
            "cli.commands.interactive._find_cookie_file",
            return_value=Path("bili_cookie.json"),
        ), patch(
            "cli.commands.interactive.cfg.set"
        ), patch(
            "builtins.input",
            side_effect=["1", "BV19nRWBtEnF", "1", "", "y", ""],
        ), patch("sys.stdin", fake_stdin), patch("sys.stderr", fake_stdout):
            exit_code = handle_interactive_command(self._make_args())

        self.assertEqual(exit_code, 0)
        selection = mock_runner_cls.call_args.kwargs["selection_strategy"]
        self.assertIsInstance(selection, InteractiveTTYSelection)

if __name__ == "__main__":
    unittest.main()
