"""Direct unit tests for shared CLI command runtimes."""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import Mock

class SearchCommandRuntimeTests(unittest.TestCase):
    def _make_env(self):
        from shared.search_command_runtime import SearchCommandEnv

        return SearchCommandEnv(
            CLIRunner_cls=Mock(),
            selection_factory=Mock(),
            get_platform_defaults=Mock(return_value={"timeout": 10}),
            get_default_save_dir=Mock(return_value="downloads"),
            build_missav_proxy_url=Mock(side_effect=lambda value: f"normalized:{value}"),
            validate_config_types=Mock(return_value=None),
        )

    def _make_search_args(self, **overrides):
        defaults = dict(
            source="douyin",
            _platform=None,
            keyword="keyword",
            save_dir=None,
            max_items=None,
            max_pages=None,
            http_timeout=None,
            individual_only=False,
            priority=None,
            proxy=None,
            config=None,
            cookie=None,
            download_strategy=None,
            referer=None,
            ua=None,
            folder_name=None,
            use_subdir=None,
            file_name=None,
            content_type=None,
            select=None,
            exclude=None,
            select_all=False,
            first=False,
            last=False,
            interactive=False,
            pipe=False,
            preload_choices=None,
            quiet=False,
            command_timeout=None,
            legacy_run_timeout=None,
            no_download=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_build_config_merges_cli_overrides_and_folder_name(self):
        from shared.search_command_runtime import build_config

        env = self._make_env()
        args = self._make_search_args(
            config='{"author":"alice","timeout":30}',
            folder_name="custom-folder",
            file_name="demo",
            content_type="gallery",
        )

        config = build_config(args, env=env)

        self.assertEqual(config["timeout"], 30)
        self.assertEqual(config["folder_name"], "custom-folder")
        self.assertTrue(config["use_subdir"])
        self.assertEqual(config["file_name"], "demo")
        self.assertEqual(config["content_type"], "gallery")

    def test_build_config_normalizes_missav_proxy(self):
        from shared.search_command_runtime import build_config

        env = self._make_env()
        args = self._make_search_args(source="missav", proxy="Clash (7890)")

        config = build_config(args, env=env)

        self.assertEqual(config["proxy"], "normalized:Clash (7890)")
        env.build_missav_proxy_url.assert_called_once_with("Clash (7890)")

    def test_validate_args_rejects_non_object_config(self):
        from shared.search_command_runtime import validate_args

        env = self._make_env()
        args = self._make_search_args(config='["bad"]')

        error = validate_args(args, env=env)

        self.assertIn("JSON 对象", error)

    def test_run_search_command_uses_default_save_dir_and_download_flag(self):
        from shared.search_command_runtime import run_search_command

        env = self._make_env()
        runner = env.CLIRunner_cls.return_value
        runner.run.return_value = {"status": "ok", "items": []}
        env.selection_factory.from_cli_args.return_value = "selection"
        args = self._make_search_args(no_download=True)

        outcome, result = run_search_command(args, env=env)

        self.assertEqual(outcome, "ok")
        self.assertEqual(result["status"], "ok")
        runner_kwargs = env.CLIRunner_cls.call_args.kwargs
        self.assertEqual(runner_kwargs["save_dir"], "downloads")
        self.assertFalse(runner_kwargs["download"])
        self.assertEqual(runner_kwargs["selection_strategy"], "selection")

    def test_missing_search_source_is_usage_error_before_dependencies(self):
        from shared.search_command_runtime import run_search_command

        env = self._make_env()
        args = argparse.Namespace(keyword="query")

        outcome, result = run_search_command(args, env=env)

        self.assertEqual(outcome, "usage")
        self.assertIn("--source", result["error"])
        env.get_platform_defaults.assert_not_called()
        env.selection_factory.from_cli_args.assert_not_called()
        env.CLIRunner_cls.assert_not_called()

    def test_http_timeout_enters_config_and_command_timeout_enters_runner(self):
        from shared.search_command_runtime import (
            add_search_arguments,
            run_search_command,
        )

        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=("douyin",))
        args = parser.parse_args(
            [
                "--source",
                "douyin",
                "query",
                "--http-timeout",
                "12",
                "--timeout",
                "34",
            ]
        )
        env = self._make_env()
        runner = env.CLIRunner_cls.return_value
        runner.run.return_value = {"status": "ok", "items": []}
        env.selection_factory.from_cli_args.return_value = "selection"

        outcome, result = run_search_command(args, env=env)

        self.assertEqual(outcome, "ok")
        self.assertEqual(result["status"], "ok")
        runner_kwargs = env.CLIRunner_cls.call_args.kwargs
        self.assertEqual(runner_kwargs["config"]["timeout"], 12)
        self.assertEqual(runner_kwargs["timeout"], 34)

    def test_legacy_run_timeout_warns_and_conflicts_with_timeout(self):
        from shared.search_command_runtime import (
            add_search_arguments,
            resolve_command_timeout,
            run_search_command,
        )

        parser = argparse.ArgumentParser()
        add_search_arguments(parser, platform_ids=("douyin",))
        legacy = parser.parse_args(
            ["--source", "douyin", "query", "--run-timeout", "9"]
        )
        self.assertEqual(resolve_command_timeout(legacy), (9.0, True))

        conflict = parser.parse_args(
            [
                "--source",
                "douyin",
                "query",
                "--timeout",
                "8",
                "--run-timeout",
                "9",
            ]
        )
        env = self._make_env()
        outcome, _result = run_search_command(conflict, env=env)

        self.assertEqual(outcome, "usage")
        env.CLIRunner_cls.assert_not_called()

class DownloadCommandRuntimeTests(unittest.TestCase):
    def _make_env(self):
        from shared.download_command_runtime import DownloadCommandEnv

        return DownloadCommandEnv(
            UcrawlSDK_cls=Mock(),
            get_default_save_dir=Mock(return_value="downloads"),
            build_missav_proxy_url=Mock(side_effect=lambda value: f"normalized:{value}"),
            validate_config_types=Mock(return_value=None),
            get_plugin=Mock(return_value=object()),
            list_platform_ids=Mock(return_value=["douyin", "missav"]),
        )

    def _make_download_args(self, **overrides):
        defaults = dict(
            title="video-title",
            save_dir=None,
            url="https://example.com/video",
            source="douyin",
            command_timeout=300.0,
            config=None,
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
            quiet=False,
            pretty=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_download_timeout_uses_command_timeout_destination(self):
        from shared.download_command_runtime import add_download_arguments

        parser = argparse.ArgumentParser()
        add_download_arguments(parser, platform_ids=("douyin",))
        args = parser.parse_args(
            [
                "https://example.test/video.mp4",
                "--source",
                "douyin",
                "--timeout",
                "45",
            ]
        )

        self.assertEqual(args.command_timeout, 45)
        self.assertFalse(hasattr(args, "timeout"))

    def test_parse_user_config_rejects_invalid_json(self):
        from shared.download_command_runtime import parse_user_config

        env = self._make_env()
        args = self._make_download_args(config='{"timeout":}')

        config, error = parse_user_config(args, env=env)

        self.assertIsNone(config)
        self.assertIn("JSON 解析失败", error)

    def test_build_config_applies_author_folder_fallback_and_proxy_normalization(self):
        from shared.download_command_runtime import build_config

        env = self._make_env()
        args = self._make_download_args(
            source="missav",
            config='{"author":"alice"}',
            proxy="Clash (7890)",
        )

        config, error = build_config(args, source="missav", env=env)

        self.assertIsNone(error)
        self.assertEqual(config["folder_name"], "alice")
        self.assertTrue(config["use_subdir"])
        self.assertEqual(config["proxy"], "normalized:Clash (7890)")
        env.build_missav_proxy_url.assert_called_once_with("Clash (7890)")

    def test_run_download_command_rejects_missing_url_before_sdk_construction(self):
        from shared.download_command_runtime import run_download_command

        env = self._make_env()
        args = self._make_download_args(url=None)

        outcome, result, error = run_download_command(args, env=env)

        self.assertEqual(outcome, "usage")
        self.assertIsNone(result)
        self.assertIn("URL", error)
        env.UcrawlSDK_cls.assert_not_called()

    def test_download_passes_positional_url_and_optional_title_to_sdk(self):
        from shared.download_command_runtime import run_download_command

        env = self._make_env()
        sdk = env.UcrawlSDK_cls.return_value
        sdk.download_video.return_value = {"status": "ok"}
        args = self._make_download_args()
        args.title = "Demo"

        outcome, result, error = run_download_command(args, env=env)

        self.assertEqual(outcome, "ok")
        self.assertEqual(result, {"status": "ok"})
        self.assertIsNone(error)
        self.assertEqual(
            sdk.download_video.call_args.kwargs["url"],
            "https://example.com/video",
        )
        self.assertEqual(sdk.download_video.call_args.kwargs["title"], "Demo")

    def test_download_validation_is_usage_error_before_sdk_construction(self):
        from shared.download_command_runtime import run_download_command

        env = self._make_env()
        args = self._make_download_args(url=" ")
        args.title = ""

        outcome, result, error = run_download_command(args, env=env)

        self.assertEqual(outcome, "usage")
        self.assertIsNone(result)
        self.assertIn("URL", error)
        env.UcrawlSDK_cls.assert_not_called()

    def test_run_download_command_closes_sdk_and_surfaces_type_error(self):
        from shared.download_command_runtime import run_download_command

        env = self._make_env()
        sdk = env.UcrawlSDK_cls.return_value
        sdk.download_video.side_effect = TypeError("bad timeout")
        args = self._make_download_args()

        outcome, result, error = run_download_command(args, env=env)

        self.assertEqual(outcome, "usage")
        self.assertIsNone(result)
        self.assertIn("bad timeout", error)
        sdk.close.assert_called_once()

class SDKRuntimeTests(unittest.TestCase):
    def test_discover_platform_ids_falls_back_when_registry_errors(self):
        import shared.sdk_runtime as runtime

        with unittest.mock.patch("builtins.__import__", side_effect=ImportError("boom")):
            platforms = runtime._discover_platform_ids()

        self.assertIn("douyin", platforms)
        self.assertIn("missav", platforms)

if __name__ == "__main__":
    unittest.main()
