"""Regression tests for the decomposed interactive CLI workflow."""

from __future__ import annotations

import argparse
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class InteractiveCommandTests(unittest.TestCase):
    def _make_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            save_dir=None,
            no_download=False,
            pretty=False,
            http_timeout=None,
            command_timeout=None,
            legacy_run_timeout=None,
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
            proxy=None,
            individual_only=None,
            priority=None,
        )

    def _run(
        self,
        args: argparse.Namespace,
        *,
        sdk: Mock,
        runner: Mock,
        inputs: list[object],
        cookie_data: dict | None = None,
        cookie_path: str = "auth.json",
    ):
        from cli.interactive.workflow import run_interactive

        sdk_cls = Mock(return_value=sdk)
        runner_cls = Mock(return_value=runner)
        if cookie_data is None:
            cookie_data = {"sessionid_ss": "cookie-value"}

        with patch(
            "cli.interactive.workflow.get_default_save_dir",
            return_value=r"D:\Downloads\UCP",
        ), patch(
            "cli.interactive.configuration.is_temp_dir",
            return_value=False,
        ), patch(
            "cli.interactive.configuration.load_cookie",
            return_value=cookie_data,
        ), patch(
            "cli.interactive.configuration.check_cookie_valid",
            return_value=True,
        ), patch(
            "cli.interactive.configuration.find_cookie_file",
            return_value=Path(cookie_path),
        ), patch(
            "cli.interactive.configuration.cfg.set"
        ) as cfg_set, patch(
            "builtins.input",
            side_effect=inputs,
        ):
            result = run_interactive(
                args,
                sdk_cls=sdk_cls,
                runner_cls=runner_cls,
            )

        return result, sdk_cls, runner_cls, cfg_set

    def test_unknown_plugin_gets_generic_guide(self):
        from cli.interactive.catalog import guide_for

        guide = guide_for(
            "external",
            {
                "id": "external",
                "name": "External",
                "search_placeholder": "输入外部资源",
            },
        )

        self.assertEqual(guide["input_label"], "输入外部资源")
        self.assertIn("External", guide["result_tip"])

    def test_command_module_is_a_thin_adapter(self):
        import cli.commands.interactive as module

        source = Path(module.__file__).read_text(encoding="utf-8")

        self.assertNotIn("def _load_cookie", source)
        self.assertNotIn("def _choose", source)
        self.assertNotIn("def _build_config_summary_lines", source)
        self.assertLess(len(source.splitlines()), 230)

    def test_interactive_persists_save_dir_and_runs_cli_runner_once(self):
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "douyin",
                "name": "抖音",
                "search_placeholder": "输入关键词",
            },
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

        result, _sdk_cls, runner_cls, cfg_set = self._run(
            self._make_args(),
            sdk=sdk,
            runner=runner,
            inputs=["1", "测试关键词", "1", "", "y", ""],
            cookie_path="dy_auth.json",
        )

        self.assertEqual(result, 0)
        cfg_set.assert_called_once_with(
            "common",
            "save_directory",
            r"D:\Downloads\UCP",
        )
        runner_cls.assert_called_once()
        runner_kwargs = runner_cls.call_args.kwargs
        self.assertEqual(runner_kwargs["source"], "douyin")
        self.assertEqual(runner_kwargs["keyword"], "测试关键词")
        self.assertEqual(runner_kwargs["save_dir"], r"D:\Downloads\UCP")
        self.assertTrue(runner_kwargs["download"])
        self.assertEqual(runner_kwargs["config"]["max_items"], 1)
        self.assertEqual(runner_kwargs["config"]["timeout"], 30)
        self.assertIsNone(runner_kwargs["timeout"])
        runner.run.assert_called_once()
        sdk.close.assert_called_once()

    def test_confirmation_renders_the_normalized_runner_config(self):
        args = self._make_args()
        args.config = '{"max_items": 7, "timeout": 90}'
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "douyin",
                "name": "抖音",
                "search_placeholder": "输入关键词",
            },
        ]
        runner = Mock()
        runner.run.return_value = {
            "status": "ok",
            "elapsed": 0.1,
            "items": [],
        }
        output = io.StringIO()

        with patch("sys.stdout", output):
            result, _sdk_cls, runner_cls, _cfg_set = self._run(
                args,
                sdk=sdk,
                runner=runner,
                inputs=["1", "测试关键词", "1", "", "y", ""],
                cookie_path="dy_auth.json",
            )

        self.assertEqual(result, 0)
        self.assertIn("视频数: 7", output.getvalue())
        self.assertEqual(
            runner_cls.call_args.kwargs["config"]["max_items"],
            7,
        )
        self.assertEqual(
            runner_cls.call_args.kwargs["config"]["timeout"],
            90,
        )

    def test_interactive_invalid_selection_rule_is_usage_error(self):
        args = self._make_args()
        args.select = "frist"
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "douyin",
                "name": "抖音",
                "search_placeholder": "输入关键词",
            },
        ]
        runner = Mock()
        error = io.StringIO()

        with patch("sys.stderr", error):
            result, _sdk_cls, runner_cls, _cfg_set = self._run(
                args,
                sdk=sdk,
                runner=runner,
                inputs=["1", "测试关键词", "1", "", "y"],
                cookie_path="dy_auth.json",
            )

        self.assertEqual(result, 2)
        self.assertIn("frist", error.getvalue())
        runner_cls.assert_not_called()

    def test_persist_save_dir_skips_temporary_directory(self):
        from cli.interactive.configuration import persist_save_dir

        with patch(
            "cli.interactive.configuration.is_temp_dir",
            return_value=True,
        ), patch(
            "cli.interactive.configuration.cfg.set"
        ) as cfg_set:
            persist_save_dir(
                r"C:\Users\demo\AppData\Local\Temp\tmpabc123"
            )

        cfg_set.assert_not_called()

    def test_build_config_summary_lines_are_platform_specific(self):
        from cli.interactive.configuration import build_config_summary_lines

        douyin_lines = build_config_summary_lines(
            "douyin",
            {"max_items": 5, "timeout": 30},
            "抖音",
            "测试关键词",
            r"D:\Downloads\UCP",
        )
        missav_lines = build_config_summary_lines(
            "missav",
            {
                "individual_only": True,
                "priority": "中文字幕优先",
                "proxy": "http://127.0.0.1:7890",
            },
            "MissAV",
            "SSIS-001",
            r"D:\Downloads\UCP",
        )

        self.assertTrue(any("视频数" in line for line in douyin_lines))
        self.assertTrue(any("浏览器扫码" in line for line in douyin_lines))
        self.assertTrue(any("仅单体" in line for line in missav_lines))
        self.assertTrue(any("代理" in line for line in missav_lines))

    def test_download_summary_tolerates_null_titles(self):
        from cli.interactive.prompts import print_download_summary

        output = io.StringIO()
        with patch("sys.stdout", output):
            print_download_summary(
                [
                    {
                        "title": None,
                        "id": None,
                        "status": "❌ 失败",
                        "error": "network",
                    }
                ],
                elapsed=1.0,
                save_dir=r"D:\Downloads\UCP",
            )

        self.assertIn("未知", output.getvalue())

    def test_xiaohongshu_summary_hides_search_page_count(self):
        from cli.interactive.configuration import build_config_summary_lines

        lines = build_config_summary_lines(
            "xiaohongshu",
            {"max_items": 20, "search_max_pages": 5},
            "小红书",
            "摄影",
            r"D:\Downloads\UCP",
        )

        self.assertTrue(any("笔记数" in line for line in lines))
        self.assertFalse(any("搜索页" in line for line in lines))

    def test_kuaishou_guide_mentions_share_link(self):
        from cli.interactive.catalog import guide_for

        guide = guide_for("kuaishou")

        self.assertIn("分享链接", guide["input_label"])
        self.assertTrue(
            any("分享链接" in line for line in guide["examples"])
        )
        self.assertIn("分享链接", guide["empty_tip"])

    def test_interactive_xiaohongshu_skips_search_page_prompt(self):
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "xiaohongshu",
                "name": "小红书",
                "search_placeholder": "输入关键词",
            },
        ]
        runner = Mock()
        runner.run.return_value = {
            "status": "ok",
            "elapsed": 0.8,
            "items": [],
        }

        result, _sdk_cls, runner_cls, _cfg_set = self._run(
            self._make_args(),
            sdk=sdk,
            runner=runner,
            inputs=["1", "摄影", "1", "", "y", ""],
            cookie_data={"a1": "cookie-value"},
            cookie_path="xhs_auth.json",
        )

        self.assertEqual(result, 0)
        runner_kwargs = runner_cls.call_args.kwargs
        self.assertEqual(runner_kwargs["source"], "xiaohongshu")
        self.assertEqual(runner_kwargs["config"]["max_items"], 1)
        self.assertEqual(
            runner_kwargs["config"]["search_max_pages"],
            5,
        )

    def test_prompt_post_run_action_supports_open_and_switch(self):
        from cli.interactive.prompts import prompt_post_run_action

        with patch(
            "cli.interactive.prompts.os.startfile"
        ) as startfile, patch(
            "builtins.input",
            side_effect=["o", "p"],
        ):
            action = prompt_post_run_action(
                r"D:\Downloads\UCP",
                allow_repeat=True,
            )

        startfile.assert_called_once_with(r"D:\Downloads\UCP")
        self.assertEqual(action, "switch")

    def test_choose_retries_until_valid_input(self):
        from cli.interactive.prompts import choose

        with patch("builtins.input", side_effect=["abc", "9", "2"]):
            result = choose(
                "视频数量",
                ["1", "2", "5"],
                default_idx=0,
            )

        self.assertEqual(result, 1)

    def test_print_examples_dims_each_example_from_the_supplied_guide(self):
        from cli.interactive.prompts import DIM, RESET, print_examples

        output = io.StringIO()
        with patch("sys.stdout", output):
            print_examples({"examples": ["example input"]})

        self.assertIn(f"    {DIM}example input{RESET}", output.getvalue())

    def test_interactive_respects_quiet_flag_when_building_sdk(self):
        from cli.interactive.workflow import run_interactive

        args = self._make_args()
        args.quiet = True
        sdk = Mock()
        sdk.list_platforms.return_value = []
        sdk_cls = Mock(return_value=sdk)

        result = run_interactive(
            args,
            sdk_cls=sdk_cls,
            runner_cls=Mock(),
        )

        self.assertEqual(result, 1)
        sdk_cls.assert_called_once_with(verbose=False)
        sdk.close.assert_called_once()

    def test_interactive_defaults_to_tty_selection(self):
        from shared.interactive_selection import InteractiveTTYSelection

        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "bilibili",
                "name": "Bilibili",
                "search_placeholder": "输入 BV 号",
            },
        ]
        runner = Mock()
        runner.run.return_value = {
            "status": "ok",
            "elapsed": 0.8,
            "items": [],
        }

        result, _sdk_cls, runner_cls, _cfg_set = self._run(
            self._make_args(),
            sdk=sdk,
            runner=runner,
            inputs=["1", "BV19nRWBtEnF", "1", "", "y", ""],
            cookie_data={"SESSDATA": "cookie-value"},
            cookie_path="bili_cookie.json",
        )

        self.assertEqual(result, 0)
        selection = runner_cls.call_args.kwargs["selection_strategy"]
        self.assertIsInstance(selection, InteractiveTTYSelection)

    def test_http_and_command_timeouts_have_distinct_destinations(self):
        args = self._make_args()
        args.http_timeout = 12.5
        args.command_timeout = 34.0
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "douyin",
                "name": "抖音",
                "search_placeholder": "输入关键词",
            },
        ]
        runner = Mock()
        runner.run.return_value = {
            "status": "ok",
            "elapsed": 0.1,
            "items": [],
        }

        result, _sdk_cls, runner_cls, _cfg_set = self._run(
            args,
            sdk=sdk,
            runner=runner,
            inputs=["1", "测试", "1", "", "y", ""],
            cookie_path="dy_auth.json",
        )

        self.assertEqual(result, 0)
        kwargs = runner_cls.call_args.kwargs
        self.assertEqual(kwargs["config"]["timeout"], 12.5)
        self.assertEqual(kwargs["timeout"], 34.0)

    def test_interactive_input_cancellation_returns_130(self):
        sdk = Mock()
        sdk.list_platforms.return_value = [
            {
                "id": "douyin",
                "name": "抖音",
                "search_placeholder": "输入关键词",
            },
        ]
        runner = Mock()

        result, _sdk_cls, runner_cls, _cfg_set = self._run(
            self._make_args(),
            sdk=sdk,
            runner=runner,
            inputs=[EOFError()],
            cookie_path="dy_auth.json",
        )

        self.assertEqual(result, 130)
        runner_cls.assert_not_called()
        sdk.close.assert_called_once()

    def test_interactive_maps_structured_runner_statuses(self):
        for status, expected in (
            ("error", 1),
            ("timeout", 124),
            ("cancelled", 130),
        ):
            with self.subTest(status=status):
                sdk = Mock()
                sdk.list_platforms.return_value = [
                    {
                        "id": "douyin",
                        "name": "抖音",
                        "search_placeholder": "输入关键词",
                    },
                ]
                runner = Mock()
                runner.run.return_value = {
                    "status": status,
                    "error": status,
                }

                result, _sdk_cls, _runner_cls, _cfg_set = self._run(
                    self._make_args(),
                    sdk=sdk,
                    runner=runner,
                    inputs=["1", "测试", "1", "", "y"],
                    cookie_path="dy_auth.json",
                )

                self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
