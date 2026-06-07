"""cli.sdk UcrawlSDK 单测。

测试维度：
- 单元测试：参数校验、selection 解析、QApplication 管理
- 黑盒测试：不 mock CLIRunner，跑真实 SDK
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class UcrawlSDKInitTests(unittest.TestCase):
    """UcrawlSDK 初始化测试。"""

    def test_init_with_defaults(self):
        """无参初始化必须能跑。"""
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK()
        self.assertIsNotNone(sdk.save_dir)
        self.assertFalse(sdk.verbose)
        self.assertEqual(sdk.default_config, {})

    def test_init_with_save_dir(self):
        """显式 save_dir 必须被保存。"""
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir="/tmp/test_dl")
        self.assertEqual(sdk.save_dir, "/tmp/test_dl")

    def test_init_invalid_save_dir_type(self):
        """save_dir 非 str/None 必须抛 TypeError。"""
        from cli.sdk import UcrawlSDK
        with self.assertRaises(TypeError):
            UcrawlSDK(save_dir=123)

    def test_init_invalid_config_type(self):
        """config 非 dict/None 必须抛 TypeError。"""
        from cli.sdk import UcrawlSDK
        with self.assertRaises(TypeError):
            UcrawlSDK(config="not a dict")

    def test_context_manager(self):
        """with 语句必须正确 enter/exit。"""
        from cli.sdk import UcrawlSDK
        with UcrawlSDK() as sdk:
            self.assertIsNotNone(sdk)
        # exit 后 _owns_qt_app 必须清空
        self.assertFalse(sdk._owns_qt_app)


class UcrawlSDKSelectionResolveTests(unittest.TestCase):
    """_resolve_selection 测试。"""

    def setUp(self):
        from cli.sdk import UcrawlSDK
        self.sdk = UcrawlSDK()

    def test_none_returns_auto(self):
        """selection=None → AutoSelection。"""
        from cli.selection import AutoSelection
        self.assertIsInstance(self.sdk._resolve_selection(None), AutoSelection)

    def test_str_all(self):
        """'all' → RuleSelection(all_items=True)。"""
        from cli.selection import RuleSelection
        s = self.sdk._resolve_selection("all")
        self.assertIsInstance(s, RuleSelection)
        self.assertTrue(s.all)

    def test_str_first(self):
        """'first' → RuleSelection(first=True)。"""
        from cli.selection import RuleSelection
        s = self.sdk._resolve_selection("first")
        self.assertTrue(s.first)

    def test_str_last(self):
        """'last' → RuleSelection(last=True)。"""
        from cli.selection import RuleSelection
        s = self.sdk._resolve_selection("last")
        self.assertTrue(s.last)

    def test_str_indices(self):
        """'0,2,5' → RuleSelection(select='0,2,5')。"""
        from cli.selection import RuleSelection
        s = self.sdk._resolve_selection("0,2,5")
        # RuleSelection.select 是方法，规则存储在 _select_rule 属性中
        self.assertEqual(s._select_rule, "0,2,5")

    def test_str_interactive(self):
        """'interactive' → InteractiveTTYSelection。"""
        from cli.selection import InteractiveTTYSelection
        s = self.sdk._resolve_selection("interactive")
        self.assertIsInstance(s, InteractiveTTYSelection)

    def test_str_pipe(self):
        """'pipe' → PipeSelection。"""
        from cli.selection import PipeSelection
        s = self.sdk._resolve_selection("pipe")
        self.assertIsInstance(s, PipeSelection)

    def test_list_returns_preload(self):
        """list[int] → PipeSelection(preloaded_choices=[[...]])。"""
        from cli.selection import PipeSelection
        s = self.sdk._resolve_selection([0, 2, 5])
        self.assertIsInstance(s, PipeSelection)
        self.assertEqual(s._preloaded, [[0, 2, 5]])

    def test_dict_strategy_all(self):
        """{"strategy": "all"} → RuleSelection(all=True)。"""
        from cli.selection import RuleSelection
        s = self.sdk._resolve_selection({"strategy": "all"})
        self.assertIsInstance(s, RuleSelection)
        self.assertTrue(s.all)

    def test_dict_strategy_rule(self):
        """{"strategy": "rule", "select": "0,2"} → RuleSelection。"""
        from cli.selection import RuleSelection
        s = self.sdk._resolve_selection({"strategy": "rule", "select": "0,2"})
        # RuleSelection.select 是方法，规则存储在 _select_rule 属性中
        self.assertEqual(s._select_rule, "0,2")

    def test_dict_strategy_rule_invalid_select_type(self):
        """{"strategy": "rule", "select": 123} → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection({"strategy": "rule", "select": 123})

    def test_dict_strategy_preload(self):
        """{"strategy": "preload", "choices": [[0], [1, 2]]} → PipeSelection。"""
        from cli.selection import PipeSelection
        s = self.sdk._resolve_selection({"strategy": "preload", "choices": [[0], [1, 2]]})
        self.assertIsInstance(s, PipeSelection)
        self.assertEqual(s._preloaded, [[0], [1, 2]])

    def test_dict_strategy_preload_not_2d(self):
        """{"strategy": "preload", "choices": [1, 2]} → TypeError（必须二维）。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection({"strategy": "preload", "choices": [1, 2]})

    def test_dict_strategy_unknown_raises(self):
        """{"strategy": "unknown"} → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk._resolve_selection({"strategy": "unknown"})

    def test_invalid_type_raises(self):
        """selection=123 → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection(123)


class UcrawlSDKSearchValidationTests(unittest.TestCase):
    """search() 参数校验测试（不真跑爬虫）。"""

    def setUp(self):
        from cli.sdk import UcrawlSDK
        self.sdk = UcrawlSDK()

    def test_search_invalid_source_type(self):
        """source 非 str → TypeError。"""
        with patch("cli.runner.CLIRunner") as mock:
            with self.assertRaises(TypeError):
                self.sdk.search(123, "kw")

    def test_search_invalid_keyword_type(self):
        """keyword 非 str → TypeError。"""
        with patch("cli.runner.CLIRunner") as mock:
            with self.assertRaises(TypeError):
                self.sdk.search("douyin", 123)

    def test_search_empty_source(self):
        """source='' → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("", "kw")

    def test_search_empty_keyword(self):
        """keyword='' → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("douyin", "")

    def test_search_unknown_platform(self):
        """source='unknown' → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("unknown_platform", "kw")

    def test_search_invalid_timeout_type(self):
        """timeout='abc' → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", timeout="abc")

    def test_search_negative_timeout(self):
        """timeout=0 → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("douyin", "kw", timeout=0)
        with self.assertRaises(ValueError):
            self.sdk.search("douyin", "kw", timeout=-1)

    def test_search_invalid_download_type(self):
        """download='yes' → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", download="yes")

    def test_search_invalid_save_dir_type(self):
        """save_dir=123 → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", save_dir=123)

    def test_search_invalid_config_max_items(self):
        """max_items='abc' → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", max_items="abc")


class UcrawlSDKSearchFunctionalTests(unittest.TestCase):
    """search() 实际功能测试（mock CLIRunner）。"""

    def test_search_returns_runner_result(self):
        """search() 必须原样返回 CLIRunner.run() 的结果。"""
        from cli.sdk import UcrawlSDK
        from cli.selection import RuleSelection
        sdk = UcrawlSDK()
        expected = {"status": "ok", "items": [], "logs": []}
        with patch("cli.runner.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = expected
            result = sdk.search("douyin", "kw")
        self.assertEqual(result, expected)

    def test_search_merges_default_config(self):
        """SDK 的 default_config 必须合并到 CLIRunner 的 config。"""
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(config={"max_items": 99, "timeout": 5})
        with patch("cli.runner.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            sdk.search("douyin", "kw", max_items=10)
        # CLIRunner 必须被调用，config 含 max_items=10（本次覆盖了全局默认）
        runner_config = MockRunner.call_args.kwargs["config"]
        self.assertEqual(runner_config["max_items"], 10)
        self.assertEqual(runner_config["timeout"], 5)

    def test_search_skips_none_config_values(self):
        """None 值的 config key 必须被过滤（不覆盖默认值）。"""
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK()
        with patch("cli.runner.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            sdk.search("douyin", "kw", max_items=None)
        # max_items=None 被过滤 → config 不含 max_items
        runner_config = MockRunner.call_args.kwargs["config"]
        self.assertNotIn("max_items", runner_config)

    def test_search_missav_proxy_normalized(self):
        """missav 平台的 proxy 字段必须用 build_missav_proxy_url 转换。"""
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK()
        with patch("cli.runner.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            sdk.search("missav", "ABC", proxy="Clash (7890)")
        runner_config = MockRunner.call_args.kwargs["config"]
        self.assertEqual(runner_config["proxy"], "http://127.0.0.1:7890")


class UcrawlSDKCloseTests(unittest.TestCase):
    """close() 资源清理测试。"""

    def test_close_idempotent(self):
        """close() 必须幂等（多次调用不报错）。"""
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK()
        sdk.close()
        sdk.close()  # 不应该抛异常

    def test_close_does_not_kill_external_qt_app(self):
        """close() 不得关闭外部已存在的 QApplication。"""
        from PyQt6.QtWidgets import QApplication
        import sys
        # 创建外部 QApplication
        external_app = QApplication.instance() or QApplication(sys.argv)
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK()
        # SDK 创建后 _owns_qt_app=False（因为 QApplication 早就存在）
        self.assertFalse(sdk._owns_qt_app)
        sdk.close()  # 不应该 quit 外部 app


if __name__ == "__main__":
    unittest.main()
