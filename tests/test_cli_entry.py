"""entry.cli_entry 透传到 cli.main:main 的薄入口测试。

测试维度：
- 单元测试：参数透传
- 集成测试：与 cli.main 的实际调用链
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

class CliEntryPassthroughTests(unittest.TestCase):
    """entry.cli_entry 必须做薄透传，不写任何业务逻辑。"""

    def test_main_is_callable(self):
        """cli_entry.main 必须是可调用对象。"""
        from entry.cli_entry import main
        self.assertTrue(callable(main))

    def test_main_passes_none_to_cli_main(self):
        """cli_entry.main(argv=None) 必须把 None 透传给 cli.main:main。"""
        from entry import cli_entry
        with patch("cli.main.main", return_value=0) as mocked:
            result = cli_entry.main(None)
        self.assertEqual(result, 0)
        mocked.assert_called_once_with(None)

    def test_main_passes_argv_list(self):
        """cli_entry.main(['search', '--source', 'douyin', '--keyword', 'kw']) 透传列表。"""
        from entry import cli_entry
        argv = ["search", "--source", "douyin", "--keyword", "kw"]
        with patch("cli.main.main", return_value=0) as mocked:
            result = cli_entry.main(argv)
        self.assertEqual(result, 0)
        mocked.assert_called_once_with(argv)

    def test_main_returns_exit_code(self):
        """cli_entry.main 必须原样透传 cli.main:main 的退出码。"""
        from entry import cli_entry
        for code in (0, 1, 2, 42, 99):
            with patch("cli.main.main", return_value=code):
                self.assertEqual(cli_entry.main([]), code)

    def test_main_when_cli_main_raises(self):
        """cli.main:main 抛异常时 cli_entry.main 必须传播（不吞异常）。"""
        from entry import cli_entry
        with patch("cli.main.main", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                cli_entry.main([])

    def test_main_does_not_modify_sys_path_idempotently(self):
        """多次调用 cli_entry.main 不会重复插入 sys.path。"""
        from entry import cli_entry
        import entry.cli_entry as mod
        root = str(mod._ROOT)
        original_count = sys.path.count(root)
        with patch("cli.main.main", return_value=0):
            for _ in range(5):
                cli_entry.main([])
        # sys.path.count 必须保持不变（不重复 insert）
        self.assertEqual(sys.path.count(root), original_count)

class CliEntrySysPathTests(unittest.TestCase):
    """验证 cli_entry 启动时正确注入项目根目录到 sys.path。"""

    def test_project_root_in_sys_path_after_import(self):
        """import entry.cli_entry 后项目根目录必须在 sys.path[0]（便于 cli.main 找到 cli 包）。"""
        # 重新导入确保 sys.path 注入逻辑执行
        import importlib
        import entry.cli_entry
        importlib.reload(entry.cli_entry)
        root = str(entry.cli_entry._ROOT)
        self.assertIn(root, sys.path)
        # _ROOT 必须是绝对路径
        self.assertTrue(os.path.isabs(root))

if __name__ == "__main__":
    unittest.main()
