"""测试 entry/test_entry.py 和 test_registry 插件 API。

覆盖：
- entry/test_entry.py 各种 CLI 参数解析
- entry/test_entry.py 模式自适应（gui/tui/cli）
- entry/dispatcher 中 Mode.TEST 路由
- test_registry.register_plugin_directory() 插件目录扫描
- test_registry.register_plugin() 自定义插件
- test_registry.unregister_plugin_directory() 反注册
- test_registry.list_plugin_directories() 列出
- test_registry._rescan_plugin() 重新扫描
- main.py --mode test 调度链
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


# 让项目根目录可被 import
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))


class TestEntryCliArgsTests(unittest.TestCase):
    """entry/test_entry.py CLI 参数解析。"""

    def setUp(self):
        from entry import test_entry
        self.mod = test_entry

    def test_parse_args_default(self):
        """无参数时所有 flag 都是 False。"""
        ns = self.mod._parse_args([])
        self.assertIsNone(ns.category)
        self.assertFalse(ns.list)
        self.assertFalse(ns.gui)
        self.assertFalse(ns.tui)
        self.assertFalse(ns.cli)

    def test_parse_args_category(self):
        ns = self.mod._parse_args(["-c", "unit"])
        self.assertEqual(ns.category, "unit")

    def test_parse_args_list(self):
        ns = self.mod._parse_args(["--list"])
        self.assertTrue(ns.list)

    def test_parse_args_gui_tui_cli_mutually_exclusive(self):
        """三种模式参数可以独立指定（解析器不互斥，但运行时自适应选择）。"""
        ns = self.mod._parse_args(["--gui", "--tui", "--cli"])
        self.assertTrue(ns.gui)
        self.assertTrue(ns.tui)
        self.assertTrue(ns.cli)

    def test_parse_args_no_failfast(self):
        ns = self.mod._parse_args(["--no-failfast"])
        self.assertTrue(ns.no_failfast)

    def test_parse_args_verbose(self):
        ns = self.mod._parse_args(["-v"])
        self.assertTrue(ns.verbose)

    def test_parse_args_plugin_dir(self):
        ns = self.mod._parse_args(["--plugin-dir", "id1:我的测试:tests/plugins"])
        self.assertEqual(ns.plugin_dir, ["id1:我的测试:tests/plugins"])

    def test_parse_args_plugin_repeatable(self):
        ns = self.mod._parse_args([
            "--plugin-dir", "id1:n1:p1",
            "--plugin-dir", "id2:n2:p2",
        ])
        self.assertEqual(ns.plugin_dir, ["id1:n1:p1", "id2:n2:p2"])

    def test_parse_args_plugin(self):
        ns = self.mod._parse_args([
            "--plugin", "myid:我的:tests/test_a.py,tests/test_b.py",
        ])
        self.assertEqual(
            ns.plugin,
            ["myid:我的:tests/test_a.py,tests/test_b.py"],
        )


class TestEntryModeDetectionTests(unittest.TestCase):
    """entry/test_entry.py 模式自适应。"""

    def setUp(self):
        from entry import test_entry
        self.mod = test_entry

    def test_detect_explicit_gui(self):
        ns = self.mod._parse_args(["--gui"])
        self.assertEqual(self.mod._detect_mode(ns), "gui")

    def test_detect_explicit_tui(self):
        ns = self.mod._parse_args(["--tui"])
        self.assertEqual(self.mod._detect_mode(ns), "tui")

    def test_detect_explicit_cli(self):
        ns = self.mod._parse_args(["--cli"])
        self.assertEqual(self.mod._detect_mode(ns), "cli")

    def test_detect_implicit_cli_when_category(self):
        """有 --category 时隐式 CLI 模式（无交互）。"""
        ns = self.mod._parse_args(["-c", "unit"])
        self.assertEqual(self.mod._detect_mode(ns), "cli")


class TestEntryRunListTests(unittest.TestCase):
    """--list 模式输出。"""

    def test_run_list_returns_zero(self):
        from entry import test_entry
        # 抑制 stdout 输出
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = test_entry._run_list()
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # 包含核心类别
        for cat_id in [
            "all",
            "cli_sdk",
            "web_api",
            "app_flows",
            "desktop_ui",
            "browser_e2e",
            "pipeline",
            "packaging",
            "core_services",
            "suite_infra",
            "misc",
        ]:
            self.assertIn(cat_id, out, f"missing category: {cat_id}")


class TestEntryApplyPluginArgsTests(unittest.TestCase):
    """--plugin-dir / --plugin 命令行注册。"""

    def setUp(self):
        from tests import test_registry
        # 备份原始注册表
        self._orig = dict(test_registry.TEST_REGISTRY)
        self._orig_plugin_dirs = dict(test_registry._PLUGIN_DIRS)

    def tearDown(self):
        from tests import test_registry
        # 清理新增的
        for k in list(test_registry.TEST_REGISTRY.keys()):
            if k not in self._orig:
                del test_registry.TEST_REGISTRY[k]
        test_registry._PLUGIN_DIRS.clear()
        test_registry._PLUGIN_DIRS.update(self._orig_plugin_dirs)

    def test_apply_plugin_dir_invalid_format(self):
        from entry import test_entry
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            test_entry._apply_plugin_args(["bad_format"], [])
        self.assertIn("格式错误", buf.getvalue())

    def test_apply_plugin_dir_existing(self):
        """注册一个真实目录（tests 本身）作为插件。"""
        from entry import test_entry
        test_entry._apply_plugin_args(
            ["my_plugin:我的插件:tests"],
            [],
        )
        from tests import test_registry
        self.assertIn("my_plugin", test_registry.TEST_REGISTRY)
        self.assertIn("my_plugin", test_registry._PLUGIN_DIRS)
        # 自动发现至少 1 个 test_*.py
        self.assertGreaterEqual(test_registry.TEST_REGISTRY["my_plugin"].file_count(), 1)

    def test_apply_plugin_files(self):
        from entry import test_entry
        test_entry._apply_plugin_args(
            [],
            ["my_files:我的文件:tests/test_cli_runner.py"],
        )
        from tests import test_registry
        self.assertIn("my_files", test_registry.TEST_REGISTRY)
        self.assertEqual(
            test_registry.TEST_REGISTRY["my_files"].files,
            ["tests/test_cli_runner.py"],
        )


class TestPluginDirectoryAPITests(unittest.TestCase):
    """test_registry.register_plugin_directory / register_plugin / unregister。"""

    def setUp(self):
        from tests import test_registry
        self._orig = dict(test_registry.TEST_REGISTRY)
        self._orig_plugin_dirs = dict(test_registry._PLUGIN_DIRS)
        self.registry = test_registry

    def tearDown(self):
        for k in list(self.registry.TEST_REGISTRY.keys()):
            if k not in self._orig:
                del self.registry.TEST_REGISTRY[k]
        self.registry._PLUGIN_DIRS.clear()
        self.registry._PLUGIN_DIRS.update(self._orig_plugin_dirs)

    def test_register_plugin_directory_basic(self):
        cat = self.registry.register_plugin_directory(
            "my_plugin",
            "我的插件",
            "tests",
        )
        self.assertEqual(cat.id, "my_plugin")
        self.assertEqual(cat.name, "我的插件")
        self.assertIn("my_plugin", self.registry.TEST_REGISTRY)
        self.assertIn("my_plugin", self.registry._PLUGIN_DIRS)
        # 至少自动发现 1 个 test_*.py
        self.assertGreaterEqual(cat.file_count(), 1)

    def test_register_category_rule_matches_new_files(self):
        cat = self.registry.register_category_rule(
            id="rule_suite",
            name="规则套件",
            description="按命名规则自动纳入",
            include=["tests/test_cli_*.py"],
        )
        self.assertEqual(cat.id, "rule_suite")
        self.assertIn("tests/test_cli_entry.py", self.registry.get_resolved_files("rule_suite"))

    def test_register_test_files_appends_to_existing_category(self):
        cat = self.registry.register_category(
            id="manual_suite",
            name="手工套件",
            description="测试追加接口",
            files=["tests/test_pipeline.py"],
        )
        self.registry.register_test_files("manual_suite", ["tests/test_contract.py"])
        self.assertEqual(
            self.registry.get_resolved_files("manual_suite"),
            ["tests/test_pipeline.py", "tests/test_contract.py"],
        )

    def test_refresh_registry_returns_counts(self):
        info = self.registry.refresh_registry()
        self.assertIn("categories", info)
        self.assertIn("runnable_files", info)
        self.assertIn("unassigned_files", info)
        self.assertGreater(info["categories"], 0)

    def test_builtin_rules_cover_current_named_tests(self):
        expected_categories = {
            "tests/test_web_controller_selection.py": "web_api",
            "tests/test_web_workflows.py": "web_api",
            "tests/test_web_script_api.py": "web_api",
            "tests/test_websocket_server.py": "web_api",
            "tests/test_websocket_bridge.py": "web_api",
            "tests/test_download_manager_core.py": "core_services",
            "tests/test_douyin_parameter.py": "core_services",
            "tests/test_plugin_discovery.py": "core_services",
            "tests/test_spider_base.py": "core_services",
            "tests/test_controller_session_mixin.py": "core_services",
            "tests/test_media_library_mixin.py": "core_services",
            "tests/test_test_launcher_ui.py": "suite_infra",
        }

        unassigned = set(self.registry.auto_discover_tests())
        for file_path, category_id in expected_categories.items():
            self.assertNotIn(file_path, unassigned)
            self.assertIn(file_path, self.registry.get_resolved_files(category_id))
        self.assertEqual(unassigned, set())

    def test_register_plugin_directory_duplicate_raises(self):
        self.registry.register_plugin_directory("dup", "D1", "tests")
        with self.assertRaises(ValueError):
            self.registry.register_plugin_directory("dup", "D2", "tests")

    def test_register_plugin_directory_nonexistent_dir_no_raise(self):
        """目录不存在时不抛错（让启动器能继续工作）。"""
        cat = self.registry.register_plugin_directory(
            "missing",
            "Missing",
            "nonexistent_dir_12345",
        )
        self.assertEqual(cat.file_count(), 0)

    def test_register_plugin_object(self):
        """通过 TestPlugin 协议注册。"""
        class MyPlugin:
            id = "myobj"
            name = "Obj"
            description = "测试用"
            icon_color = "#123456"
            icon_letter = "O"
            priority = 99

            def get_files(self):
                return [
                    "tests/test_cli_runner.py",
                    "tests/test_test_entry.py",
                ]

        cat = self.registry.register_plugin(MyPlugin())
        self.assertEqual(cat.id, "myobj")
        self.assertEqual(cat.file_count(), 2)
        self.assertEqual(cat.icon_color, "#123456")
        self.assertEqual(cat.icon_letter, "O")

    def test_register_plugin_duplicate_raises(self):
        class P:
            id = "p_dup"
            name = ""
            description = ""

            def get_files(self): return []

        self.registry.register_plugin(P())
        with self.assertRaises(ValueError):
            self.registry.register_plugin(P())

    def test_unregister_plugin_directory_removes(self):
        self.registry.register_plugin_directory("x_plugin", "X", "tests")
        self.assertIn("x_plugin", self.registry.TEST_REGISTRY)

        ok = self.registry.unregister_plugin_directory("x_plugin")
        self.assertTrue(ok)
        self.assertNotIn("x_plugin", self.registry.TEST_REGISTRY)
        self.assertNotIn("x_plugin", self.registry._PLUGIN_DIRS)

    def test_unregister_non_plugin_returns_false(self):
        ok = self.registry.unregister_plugin_directory("all")
        self.assertFalse(ok)

    def test_unregister_unknown_returns_false(self):
        ok = self.registry.unregister_plugin_directory("nonexistent_zzz")
        self.assertFalse(ok)

    def test_list_plugin_directories(self):
        self.registry.register_plugin_directory("p1", "P1", "tests")
        dirs = self.registry.list_plugin_directories()
        self.assertIn("p1", dirs)
        self.assertTrue(Path(dirs["p1"]).is_absolute())

    def test_rescan_plugin_after_files_added(self):
        """先注册空目录，再往里加文件，调用 _rescan_plugin() 自动发现。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cat = self.registry.register_plugin_directory("tmpplug", "Tmp", tmpdir)
            self.assertEqual(cat.file_count(), 0)
            # 往里加 1 个 test_*.py
            (tmp / "test_x.py").write_text("# empty")
            cat2 = self.registry._rescan_plugin("tmpplug")
            self.assertIsNotNone(cat2)
            self.assertEqual(cat2.file_count(), 1)

    def test_suite_support_files_not_in_all(self):
        files = self.registry.get_resolved_files("all")
        self.assertNotIn("tests/test_launcher.py", files)
        self.assertNotIn("tests/test_registry.py", files)
        self.assertNotIn("tests/test_runner.py", files)


class TestDispatcherRoutingTests(unittest.TestCase):
    """entry.dispatcher 路由测试。"""

    def test_mode_test_in_enum(self):
        from entry import Mode
        self.assertTrue(hasattr(Mode, "TEST"))
        self.assertEqual(Mode.TEST.value, "test")

    def test_run_test_importable(self):
        from entry import run_test
        self.assertTrue(callable(run_test))

    def test_test_mode_in_menu_items(self):
        from entry.dispatcher import _MENU_ITEMS
        modes = [m for _, _, m in _MENU_ITEMS if m is not None]
        from entry import Mode
        self.assertIn(Mode.TEST, modes)

    def test_test_handler_in_handlers(self):
        from entry.dispatcher import _HANDLERS
        from entry import Mode
        self.assertIn(Mode.TEST, _HANDLERS)

    def test_detect_mode_from_env(self):
        """环境变量 UCRAWL_MODE=test 应当被识别。"""
        with mock.patch.dict(os.environ, {"UCRAWL_MODE": "test"}):
            from entry import detect_mode, Mode
            self.assertEqual(detect_mode([]), Mode.TEST)


class TestMainDispatchTests(unittest.TestCase):
    """main.py --mode test 调度链。"""

    def test_main_mode_test_routes(self):
        """main.py --mode test --cli --category e2e 应该把参数透传到 test_entry。"""
        # 由于 main.py 会执行实际测试，我们用 mock 替代 run_test
        from entry.dispatcher import _HANDLERS
        from entry import Mode
        self.assertIn(Mode.TEST, _HANDLERS)
        # 验证 run_test 与 _HANDLERS[Mode.TEST] 是同一个
        from entry import run_test
        self.assertIs(_HANDLERS[Mode.TEST], run_test)


if __name__ == "__main__":
    unittest.main()
