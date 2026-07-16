import unittest
import json
import logging
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

class RuntimeOptionsTests(unittest.TestCase):
    def test_direct_download_url_rejects_unresolvable_hosts(self):
        from shared.runtime_options import validate_direct_download_url

        with patch("shared.runtime_options.socket.getaddrinfo", side_effect=OSError("dns failed")):
            error = validate_direct_download_url("https://unresolvable.example/video.mp4")

        self.assertIn("无法解析", error)

    def test_direct_download_url_rejects_domains_resolving_to_private_ip(self):
        from shared.runtime_options import validate_direct_download_url

        with patch(
            "shared.runtime_options.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            error = validate_direct_download_url("https://public-looking.example/video.mp4")

        self.assertIn("本地或内网", error)

    def test_domain_policy_rejects_private_redirect_before_requests_follows_it(self):
        from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation

        policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))]
        )
        response = SimpleNamespace(
            status_code=302,
            url="https://public.example/video.mp4",
            headers={"Location": "http://127.0.0.1:8080/admin"},
        )

        with self.assertRaises(DomainPolicyViolation):
            policy.validate_redirect_response(response)

    def test_domain_policy_allows_relative_redirect_on_public_host(self):
        from shared.runtime_options import DomainPolicyEngine

        policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))]
        )
        response = SimpleNamespace(
            status_code=302,
            url="https://public.example/video.mp4",
            headers={"Location": "/cdn/video.mp4"},
        )

        self.assertIs(policy.validate_redirect_response(response), response)

    def test_domain_policy_rejects_credentials_and_non_global_cgnat(self):
        from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation

        credentials_policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))]
        )
        with self.assertRaises(DomainPolicyViolation):
            credentials_policy.require_public_url("https://user:password@public.example/video.mp4")

        cgnat_policy = DomainPolicyEngine(
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("100.64.0.10", 443))]
        )
        with self.assertRaises(DomainPolicyViolation):
            cgnat_policy.require_public_url("https://public-looking.example/video.mp4")

    def test_merge_convenience_params_sets_folder_name_and_use_subdir(self):
        from shared.runtime_options import merge_convenience_params

        config = {"author": "alice"}

        merged = merge_convenience_params({}, config, source="douyin")

        self.assertEqual(merged["folder_name"], "alice")
        self.assertTrue(merged["use_subdir"])

    def test_merge_convenience_params_converts_missav_proxy_and_overrides_top_level_fields(self):
        from shared.runtime_options import merge_convenience_params

        with patch("shared.runtime_options.build_missav_proxy_url", return_value="http://127.0.0.1:7890"):
            merged = merge_convenience_params(
                {
                    "proxy": "Clash (7890)",
                    "file_name": "demo",
                    "content_type": "video",
                },
                {},
                source="missav",
            )

        self.assertEqual(merged["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(merged["file_name"], "demo")
        self.assertEqual(merged["content_type"], "video")

    def test_merge_convenience_params_rejects_invalid_bool_type(self):
        from shared.runtime_options import merge_convenience_params

        with self.assertRaises(ValueError) as ctx:
            merge_convenience_params({"use_subdir": 1}, {}, source="douyin")

        self.assertIn("use_subdir 必须是布尔值", str(ctx.exception))

    def test_infer_content_type_from_url_ignores_query_string(self):
        from shared.runtime_options import infer_content_type_from_url

        self.assertEqual(infer_content_type_from_url("https://example.com/demo.mp4?token=1"), "video")
        self.assertEqual(infer_content_type_from_url("https://example.com/demo.JPG?token=1"), "image")
        self.assertEqual(infer_content_type_from_url("https://example.com/unknown.bin"), "")

    def test_get_platform_download_defaults_loads_cookie_and_bilibili_cookies_dict(self):
        from shared.runtime_options import get_platform_download_defaults

        with patch("shared.runtime_options._try_load_cookie", return_value="SESSDATA=abc"), patch(
            "shared.runtime_options._try_load_cookies_dict",
            return_value={"SESSDATA": "abc"},
        ):
            defaults = get_platform_download_defaults("bilibili")

        self.assertEqual(defaults["cookie"], "SESSDATA=abc")
        self.assertEqual(defaults["cookies"], {"SESSDATA": "abc"})
        self.assertEqual(defaults["referer"], "https://www.bilibili.com")

    def test_try_load_cookie_falls_back_to_manual_dict_serialization(self):
        from shared.runtime_options import _try_load_cookie

        old_cwd = os.getcwd()
        temp_dir = tempfile.mkdtemp()
        try:
            os.chdir(temp_dir)
            with open("dy_auth.json", "w", encoding="utf-8") as handle:
                json.dump({"sessionid": "abc", "msToken": "xyz"}, handle)
            with patch("app.services.auth_service.AuthService.build_cookie_string", side_effect=RuntimeError("boom")):
                cookie = _try_load_cookie("douyin")
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(cookie, "sessionid=abc; msToken=xyz")

    def test_try_load_cookies_dict_supports_cookie_list_shape(self):
        from shared.runtime_options import _try_load_cookies_dict

        old_cwd = os.getcwd()
        temp_dir = tempfile.mkdtemp()
        try:
            os.chdir(temp_dir)
            with open("bili_auth.json", "w", encoding="utf-8") as handle:
                json.dump(
                    [
                        {"name": "SESSDATA", "value": "abc"},
                        {"Name": "bili_jct", "Value": "token"},
                    ],
                    handle,
                )
            cookies = _try_load_cookies_dict("bilibili")
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(cookies, {"SESSDATA": "abc", "bili_jct": "token"})

    def test_get_default_save_dir_falls_back_when_cfg_unavailable(self):
        import shared.runtime_options as runtime_options

        with patch("app.config.cfg.get", side_effect=RuntimeError("broken")), patch(
            "app.config.constants.DEFAULT_DOWNLOAD_DIR",
            "downloads-fallback",
        ):
            save_dir = runtime_options.get_default_save_dir()

        self.assertEqual(save_dir, "downloads-fallback")

class RuntimeAdaptersTests(unittest.TestCase):
    def test_run_cli_search_builds_runner_and_returns_result(self):
        from shared.runtime_adapters import run_cli_search

        runner = Mock()
        runner.run.return_value = {"status": "ok", "items": []}

        with patch("shared.cli_runner_runtime.CLIRunner", return_value=runner) as runner_cls:
            result = run_cli_search(
                source="douyin",
                keyword="keyword",
                save_dir="downloads",
                selection_strategy="selection",
                config={"max_items": 20},
                timeout=3.0,
                download=False,
            )

        self.assertEqual(result, {"status": "ok", "items": []})
        runner_cls.assert_called_once_with(
            source="douyin",
            keyword="keyword",
            save_dir="downloads",
            selection_strategy="selection",
            config={"max_items": 20},
            verbose=False,
            log_to_stderr=False,
            timeout=3.0,
            download=False,
        )
        runner.run.assert_called_once()

    def test_build_sdk_returns_shared_sdk_instance(self):
        from shared.runtime_adapters import build_sdk

        sdk = Mock()
        with patch("shared.sdk_runtime.UcrawlSDK", return_value=sdk) as sdk_cls:
            built = build_sdk(save_dir="downloads")

        self.assertIs(built, sdk)
        sdk_cls.assert_called_once_with(save_dir="downloads")

class SharedSelectionRuntimeTests(unittest.TestCase):
    def test_parse_preloaded_choices_rejects_non_nested_sequence(self):
        from shared.selection_runtime import SelectionStrategyFactory

        with self.assertRaises(TypeError) as ctx:
            SelectionStrategyFactory.parse_preloaded_choices([1, 2, 3])

        self.assertIn("choices[0]", str(ctx.exception))

    def test_from_value_rejects_unknown_strategy_name(self):
        from shared.selection_runtime import SelectionStrategyFactory

        with self.assertRaises(ValueError) as ctx:
            SelectionStrategyFactory.from_value({"strategy": "mystery"})

        self.assertIn("无效选择策略", str(ctx.exception))

    def test_bridge_reports_error_and_respects_no_fallback_mode(self):
        from shared.selection_runtime import SelectionBridge

        errors = []

        class _BoomStrategy:
            strategy_name = "boom"

            def select(self, items, prompt=""):
                raise RuntimeError("boom")

        bridge = SelectionBridge(
            _BoomStrategy(),
            fallback_to_all=False,
            on_error=lambda exc, prompt, items: errors.append((str(exc), prompt, len(items))),
        )

        prompt, indices, cancelled = bridge.select([{"i": 0}, {"i": 1}])

        self.assertEqual(prompt, "二次选择 #1: 2 个候选")
        self.assertEqual(indices, [])
        self.assertFalse(cancelled)
        self.assertEqual(errors, [("boom", "二次选择 #1: 2 个候选", 2)])

    def test_bridge_strategy_error_defaults_to_empty_and_logs_warning(self):
        from shared.selection_runtime import SelectionBridge

        class _BoomStrategy:
            strategy_name = "boom"

            def select(self, items, prompt=""):
                raise RuntimeError("boom")

        with self.assertLogs("shared.selection_runtime", level=logging.WARNING) as captured:
            prompt, indices, cancelled = SelectionBridge(_BoomStrategy(), fallback_to_all=False).select([{"i": 0}, {"i": 1}])

        self.assertEqual(prompt, "二次选择 #1: 2 个候选")
        self.assertEqual(indices, [])
        self.assertFalse(cancelled)
        self.assertIn("返回空选择", captured.output[0])

    def test_from_value_returns_existing_selection_strategy_instance(self):
        from shared.selection_runtime import SelectionStrategyFactory

        strategy = SimpleNamespace(strategy_name="custom", select=lambda items, prompt="": [0])

        self.assertIs(SelectionStrategyFactory.from_value(strategy), strategy)

if __name__ == "__main__":
    unittest.main()
