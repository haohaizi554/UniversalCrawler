"""shared.cli_runner_runtime.CLIRunner 单元 + 集成测试。

测试维度：
- 单元测试：参数初始化、_apply_video_state、_make_ask_user_selection
- 集成测试：monkey-patch spider 跑完整 run() 流程
"""

import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

class CLIRunnerInitTests(unittest.TestCase):
    """CLIRunner 初始化测试。"""

    def test_init_with_minimal_args(self):
        """最小参数初始化。"""
        from shared.cli_runner_runtime import CLIRunner
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
        from shared.cli_runner_runtime import CLIRunner
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
        from shared.cli_runner_runtime import CLIRunner
        runner = CLIRunner(source="douyin", keyword="kw")
        # save_dir 必须是字符串（默认或从 cfg 读取）
        self.assertIsInstance(runner.save_dir, str)

    def test_init_config_copy(self):
        """config 必须是副本（避免外部修改污染）。"""
        from shared.cli_runner_runtime import CLIRunner
        original = {"max_items": 10}
        runner = CLIRunner(source="douyin", keyword="kw", config=original)
        original["max_items"] = 999
        # runner.config 必须是副本
        self.assertEqual(runner.config["max_items"], 10)

    def test_init_default_selection_strategy(self):
        """未指定 selection_strategy 时默认 AutoSelection。"""
        from shared.cli_runner_runtime import CLIRunner
        from shared.selection_runtime import AutoSelection
        runner = CLIRunner(source="douyin", keyword="kw")
        self.assertIsInstance(runner.selection_strategy, AutoSelection)

class CLIRunnerApplyStateTests(unittest.TestCase):
    """_apply_video_state 测试。"""

    def setUp(self):
        from shared.cli_runner_runtime import CLIRunner
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

    def test_reconcile_download_states_marks_existing_file_complete(self):
        """若文件已真实落盘，CLI 汇总前应兜底校正为完成。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "done.mp4")
            with open(target, "wb") as f:
                f.write(b"ok")

            self.fake_item.status = "⏳ 等待中"
            self.fake_item.progress = 0
            self.fake_item.local_path = target

            self.runner._reconcile_download_states()

            self.assertEqual(self.fake_item.status, "✅ 完成")
            self.assertEqual(self.fake_item.progress, 100)

    def test_on_task_progress_renders_bar_for_large_transfer(self):
        """大文件下载时 CLI 必须输出可感知进度条。"""
        self.fake_item.title = "超大视频"
        self.fake_item.meta = {"size_mb": 256}
        self.runner.log_to_stderr = True
        fake_stderr = io.StringIO()

        with patch("sys.stderr", fake_stderr):
            self.runner._on_task_progress("v1", 35)

        output = fake_stderr.getvalue()
        self.assertIn("超大视频", output)
        self.assertIn("35%", output)
        self.assertIn("[", output)

class CLIRunnerAskUserSelectionTests(unittest.TestCase):
    """_make_ask_user_selection monkey-patch 测试。"""

    def setUp(self):
        from shared.cli_runner_runtime import CLIRunner
        from shared.selection_runtime import RuleSelection
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
        from shared.cli_runner_runtime import CLIRunner
        runner = CLIRunner(
            source="douyin",
            keyword="kw",
            selection_strategy=MagicMock(select=MagicMock(side_effect=RuntimeError("boom"))),
        )
        ask = runner._make_ask_user_selection()
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        result = ask(MagicMock(), items)
        self.assertEqual(result, [0, 1, 2])

    def test_patch_spider_only_installs_selection_bridge(self):
        """Signal ownership belongs to SpiderSession; the runner only patches selection."""
        from shared.cli_runner_runtime import CLIRunner

        runner = CLIRunner(source="douyin", keyword="kw")
        spider = MagicMock()
        spider.sig_log = MagicMock()
        spider.sig_item_found = MagicMock()
        spider.sig_select_tasks = MagicMock()
        spider.sig_finished = MagicMock()

        runner._patch_spider(spider)

        self.assertTrue(callable(spider.ask_user_selection))
        spider.sig_item_found.connect.assert_not_called()
        spider.sig_log.connect.assert_not_called()

    def test_connect_download_signals_binds_callbacks_directly(self):
        """下载链去 Qt 化后，CLI 应直接绑定纯 Python 回调。"""
        from shared.cli_runner_runtime import CLIRunner

        runner = CLIRunner(source="douyin", keyword="kw")
        runner._dl_manager = MagicMock()

        runner._connect_download_signals()

        runner._dl_manager.task_started.connect.assert_called_once_with(runner._on_task_started)
        runner._dl_manager.task_progress.connect.assert_called_once_with(runner._on_task_progress)
        runner._dl_manager.task_finished.connect.assert_called_once_with(runner._on_task_finished)
        runner._dl_manager.task_error.connect.assert_called_once_with(runner._on_task_error)

class CLIRunnerRunTests(unittest.TestCase):
    """CLIRunner.run() 端到端测试（mock spider + mock download）。"""

    def test_run_unknown_source(self):
        """未知平台 → 返回 status=error。"""
        from shared.cli_runner_runtime import CLIRunner
        runner = CLIRunner(source="unknown_platform_xyz", keyword="kw")
        result = runner.run()
        self.assertEqual(result["status"], "error")
        self.assertIn("未知平台", result["error"])

    def test_run_with_mock_spider(self):
        """用 mock spider 跑完整流程。"""
        from shared.cli_runner_runtime import CLIRunner
        from shared.selection_runtime import RuleSelection
        from app.core.plugin_registry import registry

        # 注册 mock plugin
        class MockPlugin:
            id = "mock_platform"
            name = "Mock Platform"

            def get_spider_class(self):
                class MockSpider:
                    def __init__(self, keyword, config):
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
        from shared.cli_runner_runtime import CLIRunner
        from shared.selection_runtime import RuleSelection
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

    def test_wait_spider_polls_until_worker_finishes(self):
        """等待 spider 时应轮询纯 Python 线程状态直到结束。"""
        from shared.cli_runner_runtime import CLIRunner

        runner = CLIRunner(source="douyin", keyword="kw", verbose=False)

        class FakeSpider:
            def __init__(self):
                self.calls = 0

            def isRunning(self):
                self.calls += 1
                return self.calls < 3

        # 假 spider 只在被轮询时推进状态；冻结时钟可避免 CI 调度暂停被误当成业务超时。
        with patch("shared.cli_runner_runtime.time.monotonic", return_value=0.0), patch(
            "shared.cli_runner_runtime.time.sleep"
        ):
            finished = runner._wait_spider(FakeSpider(), timeout=1.0)

        self.assertTrue(finished)

    def test_run_non_timeout_path_does_not_block_on_spider_wait(self):
        """无 timeout 时 run() 应通过事件泵等待，而不是直接阻塞 wait()。"""
        from shared.cli_runner_runtime import CLIRunner
        from app.core.plugin_registry import registry

        class DummySignal:
            def __init__(self):
                self._handlers = []

            def connect(self, handler, *_args):
                self._handlers.append(handler)

            def emit(self, *args, **kwargs):
                for handler in list(self._handlers):
                    handler(*args, **kwargs)

        class MockPlugin:
            id = "mock_non_blocking_platform"
            name = "Mock Non Blocking"

            def get_spider_class(self):
                class MockSpider:
                    def __init__(self, keyword, config):
                        self.keyword = keyword
                        self.config = config
                        self.sig_log = DummySignal()
                        self.sig_item_found = DummySignal()
                        self.sig_select_tasks = DummySignal()
                        self.sig_finished = DummySignal()
                        self._running_checks = 0

                    def start(self):
                        self.sig_finished.emit()

                    def wait(self, timeout=None):
                        raise AssertionError("run() 不应在无 timeout 路径直接调用 spider.wait()")

                    def isRunning(self):
                        self._running_checks += 1
                        return self._running_checks == 1

                return MockSpider

        real_get_plugin = registry.get_plugin

        def fake_get_plugin(pid):
            if pid == "mock_non_blocking_platform":
                return MockPlugin()
            return real_get_plugin(pid)

        runner = CLIRunner(
            source="mock_non_blocking_platform",
            keyword="test",
            download=False,
            verbose=False,
        )

        with patch.object(registry, "get_plugin", side_effect=fake_get_plugin):
            result = runner.run()

        self.assertEqual(result["status"], "ok")

class CLIRunnerBuildResultTests(unittest.TestCase):
    """_build_result 测试。"""

    def test_build_result_has_required_keys(self):
        """_build_result 必须返回完整结构。"""
        from shared.cli_runner_runtime import CLIRunner
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
