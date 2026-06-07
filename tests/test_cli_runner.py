"""cli.runner CLIRunner 单元 + 集成测试。

测试维度：
- 单元测试：参数初始化、_apply_video_state、_make_ask_user_selection
- 集成测试：monkey-patch spider 跑完整 run() 流程
"""

import os
import sys
import unittest
from types import MethodType
from unittest.mock import MagicMock, patch


class CLIRunnerInitTests(unittest.TestCase):
    """CLIRunner 初始化测试。"""

    def test_init_with_minimal_args(self):
        """最小参数初始化。"""
        from cli.runner import CLIRunner
        runner = CLIRunner(source="douyin", keyword="kw")
        self.assertEqual(runner.source, "douyin")
        self.assertEqual(runner.keyword, "kw")
        self.assertEqual(runner.videos, {})
        self.assertEqual(runner.logs, [])
        self.assertFalse(runner.finished)
        self.assertEqual(runner.selection_count, 0)
        self.assertIsNone(runner._spider)
        self.assertIsNone(runner._dl_manager)

    def test_init_with_all_args(self):
        """全参数初始化。"""
        from cli.runner import CLIRunner
        runner = CLIRunner(
            source="bilibili",
            keyword="BV1xxx",
            save_dir="/tmp/dl",
            config={"max_pages": 2},
            verbose=True,
            log_to_stderr=False,
            timeout=60.0,
            download=False,
        )
        self.assertEqual(runner.save_dir, "/tmp/dl")
        self.assertEqual(runner.config, {"max_pages": 2})
        self.assertTrue(runner.verbose)
        self.assertFalse(runner.log_to_stderr)
        self.assertEqual(runner.timeout, 60.0)
        self.assertFalse(runner.download)

    def test_init_default_save_dir(self):
        """save_dir 默认值。"""
        from cli.runner import CLIRunner
        runner = CLIRunner(source="douyin", keyword="kw")
        # save_dir 必须是字符串（默认或从 cfg 读取）
        self.assertIsInstance(runner.save_dir, str)

    def test_init_config_copy(self):
        """config 必须是副本（避免外部修改污染）。"""
        from cli.runner import CLIRunner
        original = {"max_items": 10}
        runner = CLIRunner(source="douyin", keyword="kw", config=original)
        original["max_items"] = 999
        # runner.config 必须是副本
        self.assertEqual(runner.config["max_items"], 10)

    def test_init_default_selection_strategy(self):
        """未指定 selection_strategy 时默认 AutoSelection。"""
        from cli.runner import CLIRunner
        from cli.selection import AutoSelection
        runner = CLIRunner(source="douyin", keyword="kw")
        self.assertIsInstance(runner.selection_strategy, AutoSelection)


class CLIRunnerApplyStateTests(unittest.TestCase):
    """_apply_video_state 测试。"""

    def setUp(self):
        from cli.runner import CLIRunner
        self.runner = CLIRunner(source="douyin", keyword="kw")
        # 注入假 video
        self.fake_item = MagicMock()
        self.fake_item.id = "v1"
        self.fake_item.status = ""
        self.fake_item.progress = 0
        self.runner.videos["v1"] = self.fake_item

    def test_apply_status(self):
        """_apply_video_state(status='...') 必须更新 status。"""
        item = self.runner._apply_video_state("v1", status="⏳ 下载中...")
        self.assertEqual(item.status, "⏳ 下载中...")

    def test_apply_progress(self):
        """_apply_video_state(progress=50) 必须更新 progress。"""
        item = self.runner._apply_video_state("v1", progress=50)
        self.assertEqual(item.progress, 50)

    def test_apply_both(self):
        """_apply_video_state(status=..., progress=...) 必须同时更新。"""
        item = self.runner._apply_video_state("v1", status="✅ 完成", progress=100)
        self.assertEqual(item.status, "✅ 完成")
        self.assertEqual(item.progress, 100)

    def test_apply_missing_vid_returns_none(self):
        """_apply_video_state('nonexistent', ...) 必须返回 None。"""
        result = self.runner._apply_video_state("nonexistent", status="x")
        self.assertIsNone(result)


class CLIRunnerAskUserSelectionTests(unittest.TestCase):
    """_make_ask_user_selection monkey-patch 测试。"""

    def setUp(self):
        from cli.runner import CLIRunner
        from cli.selection import RuleSelection
        self.runner = CLIRunner(
            source="douyin",
            keyword="kw",
            selection_strategy=RuleSelection(select="0,2"),
        )
        self.ask = self.runner._make_ask_user_selection()

    def test_ask_returns_indices_directly(self):
        """_make_ask_user_selection 必须直接返回 indices（不走 Qt 信号）。"""
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        result = self.ask(MagicMock(), items)
        self.assertEqual(result, [0, 2])

    def test_ask_increments_selection_count(self):
        """每次调用 ask_user_selection 必须 increment selection_count。"""
        before = self.runner.selection_count
        self.ask(MagicMock(), [{"i": 0}])
        self.assertEqual(self.runner.selection_count, before + 1)

    def test_ask_strategy_exception_defaults_to_all(self):
        """策略抛异常 → 默认全选。"""
        from cli.runner import CLIRunner
        from cli.selection import RuleSelection
        runner = CLIRunner(
            source="douyin",
            keyword="kw",
            selection_strategy=MagicMock(select=MagicMock(side_effect=RuntimeError("boom"))),
        )
        ask = runner._make_ask_user_selection()
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        result = ask(MagicMock(), items)
        self.assertEqual(result, [0, 1, 2])


class CLIRunnerRunTests(unittest.TestCase):
    """CLIRunner.run() 端到端测试（mock spider + mock download）。"""

    def test_run_unknown_source(self):
        """未知平台 → 返回 status=error。"""
        from cli.runner import CLIRunner
        runner = CLIRunner(source="unknown_platform_xyz", keyword="kw")
        result = runner.run()
        self.assertEqual(result["status"], "error")
        self.assertIn("未知平台", result["error"])

    def test_run_with_mock_spider(self):
        """用 mock spider 跑完整流程。"""
        from cli.runner import CLIRunner
        from cli.selection import RuleSelection
        from app.core.plugin_registry import registry

        # 注册 mock plugin
        class MockPlugin:
            id = "mock_platform"
            name = "Mock Platform"

            def get_spider_class(self):
                class MockSpider:
                    def __init__(self, keyword, config):
                        from PyQt6.QtCore import QObject, pyqtSignal
                        # 必须派生自 QObject 才能用 pyqtSignal
                        # 这里直接 mock，不真创建信号
                        self.keyword = keyword
                        self.config = config
                        self.sig_log = MagicMock()
                        self.sig_item_found = MagicMock()
                        self.sig_select_tasks = MagicMock()
                        self.sig_finished = MagicMock()
                        self._resume_event = MagicMock()
                        self._resume_indices = None

                    def start(self):
                        """模拟立即完成。"""
                        self.sig_finished.emit()

                    def wait(self, timeout=None):
                        return True

                    def isRunning(self):
                        return False

                    def resume_from_ui(self, indices):
                        self._resume_indices = indices

                return MockSpider

        # 用 monkey-patch 注册 plugin
        real_get_plugin = registry.get_plugin
        def fake_get_plugin(pid):
            if pid == "mock_platform":
                return MockPlugin()
            return real_get_plugin(pid)
        real_get_all = registry.get_all_plugins
        def fake_get_all():
            class RealPluginProxy:
                def __init__(self, p):
                    self.p = p
                @property
                def id(self):
                    return self.p.id
            all_real = real_get_all()
            return list(all_real) + [RealPluginProxy(MockPlugin())]

        runner = CLIRunner(
            source="mock_platform",
            keyword="test",
            selection_strategy=RuleSelection(all_items=True),
            download=False,  # 不真下载
            verbose=False,
        )

        with patch.object(registry, "get_plugin", side_effect=fake_get_plugin), \
             patch.object(registry, "get_all_plugins", side_effect=fake_get_all):
            result = runner.run()

        # 验证：status=ok, 有 source/keyword/items
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "mock_platform")
        self.assertEqual(result["keyword"], "test")
        self.assertIn("items", result)
        self.assertIn("logs", result)
        self.assertIn("elapsed", result)

    def test_run_invalid_spider_constructor(self):
        """spider 构造抛异常 → 返回 status=error。"""
        from cli.runner import CLIRunner
        from cli.selection import RuleSelection
        from app.core.plugin_registry import registry

        class BrokenPlugin:
            id = "broken_platform"
            name = "Broken"

            def get_spider_class(self):
                class Broken:
                    def __init__(self, keyword, config):
                        raise RuntimeError("init failed")
                return Broken

        real_get_plugin = registry.get_plugin
        def fake_get_plugin(pid):
            if pid == "broken_platform":
                return BrokenPlugin()
            return real_get_plugin(pid)

        runner = CLIRunner(
            source="broken_platform",
            keyword="test",
            selection_strategy=RuleSelection(all_items=True),
        )
        with patch.object(registry, "get_plugin", side_effect=fake_get_plugin):
            result = runner.run()

        self.assertEqual(result["status"], "error")
        self.assertIn("创建爬虫失败", result["error"])


class CLIRunnerBuildResultTests(unittest.TestCase):
    """_build_result 测试。"""

    def test_build_result_has_required_keys(self):
        """_build_result 必须返回完整结构。"""
        from cli.runner import CLIRunner
        runner = CLIRunner(source="douyin", keyword="kw")
        runner.videos = {"v1": MagicMock(id="v1", status="✅ 完成", progress=100, local_path="", title="t", source="douyin", url="u", meta={})}
        runner.logs = ["log1"]
        runner.selection_count = 0
        import time
        result = runner._build_result("ok", time.time(), None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "douyin")
        self.assertEqual(result["keyword"], "kw")
        self.assertIn("items", result)
        self.assertIn("logs", result)
        self.assertEqual(result["logs"], ["log1"])
        self.assertIn("elapsed", result)


if __name__ == "__main__":
    unittest.main()
