"""cli.defaults 单测。

测试维度：
- 单元测试：平台默认配置、参数类型校验、MissAV 代理转换
"""

import unittest
from unittest.mock import patch

class PlatformDefaultsTests(unittest.TestCase):
    """get_platform_defaults 测试。"""

    def test_douyin_defaults(self):
        """douyin 默认包含 max_items 和 timeout。"""
        from cli.defaults import get_platform_defaults
        defaults = get_platform_defaults("douyin")
        self.assertIn("max_items", defaults)
        self.assertIn("timeout", defaults)
        self.assertIsInstance(defaults["max_items"], int)
        self.assertIsInstance(defaults["timeout"], int)
        self.assertGreater(defaults["max_items"], 0)
        self.assertGreaterEqual(defaults["timeout"], 30)

    def test_bilibili_defaults(self):
        """bilibili 默认包含 max_pages 和 max_items。"""
        from cli.defaults import get_platform_defaults
        defaults = get_platform_defaults("bilibili")
        self.assertIn("max_pages", defaults)
        self.assertIn("max_items", defaults)
        self.assertGreaterEqual(defaults["timeout"], 30)

    def test_kuaishou_defaults(self):
        """kuaishou 默认包含 max_items。"""
        from cli.defaults import get_platform_defaults
        defaults = get_platform_defaults("kuaishou")
        self.assertIn("max_items", defaults)
        self.assertGreaterEqual(defaults["timeout"], 30)

    def test_xiaohongshu_defaults_include_detail_interval(self):
        """xiaohongshu 默认包含更快的详情解析节奏配置。"""
        from cli.defaults import get_platform_defaults
        defaults = get_platform_defaults("xiaohongshu")
        self.assertIn("max_items", defaults)
        self.assertIn("search_max_pages", defaults)
        self.assertIn("detail_request_interval", defaults)
        self.assertEqual(defaults["detail_request_interval"], 0.0)

    def test_missav_defaults(self):
        """missav 默认包含 individual_only/priority/proxy。"""
        from cli.defaults import get_platform_defaults
        defaults = get_platform_defaults("missav")
        self.assertIn("individual_only", defaults)
        self.assertIn("priority", defaults)
        self.assertIn("proxy", defaults)
        self.assertIsInstance(defaults["individual_only"], bool)
        self.assertIsInstance(defaults["priority"], str)

    def test_unknown_platform_returns_empty(self):
        """未知平台 → 空 dict。"""
        from cli.defaults import get_platform_defaults
        defaults = get_platform_defaults("unknown_platform")
        self.assertEqual(defaults, {})

    def test_xiaohongshu_download_defaults_include_headers(self):
        """SDK 直下载小红书时，必须补齐与 GUI 一致的 ua/referer 默认值。"""
        from cli.defaults import get_platform_download_defaults

        with patch("cli.defaults._try_load_cookie", return_value=None):
            defaults = get_platform_download_defaults("xiaohongshu")

        self.assertIn("ua", defaults)
        self.assertEqual(defaults["referer"], "https://www.xiaohongshu.com/")

class ValidateConfigTypesTests(unittest.TestCase):
    """validate_config_types 校验测试。"""

    def test_valid_max_items(self):
        """max_items=int 必须通过。"""
        from cli.defaults import validate_config_types
        self.assertIsNone(validate_config_types({"max_items": 20}))

    def test_invalid_max_items(self):
        """max_items=str 必须返回错误。"""
        from cli.defaults import validate_config_types
        err = validate_config_types({"max_items": "abc"})
        self.assertIsNotNone(err)
        self.assertIn("max_items", err)
        self.assertIn("整数", err)

    def test_valid_individual_only(self):
        """individual_only=bool 必须通过。"""
        from cli.defaults import validate_config_types
        self.assertIsNone(validate_config_types({"individual_only": True}))

    def test_invalid_individual_only(self):
        """individual_only=str 必须返回错误。"""
        from cli.defaults import validate_config_types
        err = validate_config_types({"individual_only": "yes"})
        self.assertIsNotNone(err)
        self.assertIn("individual_only", err)
        self.assertIn("布尔", err)

    def test_valid_priority(self):
        """priority=str 必须通过。"""
        from cli.defaults import validate_config_types
        self.assertIsNone(validate_config_types({"priority": "中文字幕优先"}))

    def test_invalid_priority(self):
        """priority=int 必须返回错误。"""
        from cli.defaults import validate_config_types
        err = validate_config_types({"priority": 123})
        self.assertIsNotNone(err)

    def test_none_value_skipped(self):
        """None 值必须跳过校验（与 argparse 行为一致）。"""
        from cli.defaults import validate_config_types
        self.assertIsNone(validate_config_types({"max_items": None, "priority": None}))

    def test_unknown_key_passes_through(self):
        """未知 key 必须透传（保持前向兼容）。"""
        from cli.defaults import validate_config_types
        self.assertIsNone(validate_config_types({"unknown_key": "anything"}))

    def test_empty_dict_passes(self):
        """空 dict 必须通过。"""
        from cli.defaults import validate_config_types
        self.assertIsNone(validate_config_types({}))

class MissAVProxyBuildTests(unittest.TestCase):
    """build_missav_proxy_url 测试。"""

    def test_clash_alias(self):
        """'Clash (7890)' → http://127.0.0.1:7890。"""
        from cli.defaults import build_missav_proxy_url
        self.assertEqual(
            build_missav_proxy_url("Clash (7890)"),
            "http://127.0.0.1:7890",
        )

    def test_v2rayn_alias(self):
        """'v2rayN (10809)' → http://127.0.0.1:10809。"""
        from cli.defaults import build_missav_proxy_url
        self.assertEqual(
            build_missav_proxy_url("v2rayN (10809)"),
            "http://127.0.0.1:10809",
        )

    def test_full_url_passthrough(self):
        """完整 http URL 必须原样返回。"""
        from cli.defaults import build_missav_proxy_url
        self.assertEqual(
            build_missav_proxy_url("http://proxy.example.com:8080"),
            "http://proxy.example.com:8080",
        )

    def test_host_port_gets_http_prefix(self):
        """host:port 形式 → 自动加 http:// 前缀。"""
        from cli.defaults import build_missav_proxy_url
        self.assertEqual(
            build_missav_proxy_url("127.0.0.1:7890"),
            "http://127.0.0.1:7890",
        )

    def test_strip_whitespace(self):
        """前后空白必须 strip。"""
        from cli.defaults import build_missav_proxy_url
        self.assertEqual(
            build_missav_proxy_url("  Clash (7890)  "),
            "http://127.0.0.1:7890",
        )

    def test_unknown_string_defaults_to_clash(self):
        """无法识别的字符串 → 兜底 Clash。"""
        from cli.defaults import build_missav_proxy_url
        self.assertEqual(
            build_missav_proxy_url("garbage"),
            "http://127.0.0.1:7890",
        )

class GetDefaultSaveDirTests(unittest.TestCase):
    """get_default_save_dir 测试。"""

    def test_default_save_dir_is_string(self):
        """返回必须是字符串。"""
        from cli.defaults import get_default_save_dir
        save_dir = get_default_save_dir()
        self.assertIsInstance(save_dir, str)
        self.assertGreater(len(save_dir), 0)

class FallbackConfigTests(unittest.TestCase):
    """_FALLBACK_CONFIG 兜底配置测试。"""

    def test_fallback_config_has_all_platforms(self):
        """兜底配置必须覆盖所有平台。"""
        from cli.defaults import _FALLBACK_CONFIG
        for platform in ("douyin", "xiaohongshu", "bilibili", "kuaishou", "missav"):
            self.assertIn(platform, _FALLBACK_CONFIG)

    def test_default_config_alias(self):
        """DEFAULT_CONFIG 必须是 _FALLBACK_CONFIG 的引用（向后兼容）。"""
        from cli.defaults import DEFAULT_CONFIG, _FALLBACK_CONFIG
        self.assertIs(DEFAULT_CONFIG, _FALLBACK_CONFIG)

if __name__ == "__main__":
    unittest.main()
