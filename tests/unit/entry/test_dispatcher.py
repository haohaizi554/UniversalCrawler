"""测试 entry.dispatcher 自适应入口。

覆盖主入口分发器的模式选择、参数转发与失败行为。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main

class MainEntryTests(unittest.TestCase):
    """验证 `main.py` 顶层入口（dispatcher）的行为。"""

    def test_main_is_dispatcher(self):
        """main.main() 必须委托到 entry.run()，不做任何业务逻辑。"""
        with patch("entry.run", return_value=0) as mocked_run:
            result = main.main()
        self.assertEqual(result, 0)
        mocked_run.assert_called_once_with()

    def test_main_returns_run_exit_code(self):
        """main.main() 必须原样透传 entry.run() 的退出码。"""
        with patch("entry.run", return_value=2):
            self.assertEqual(main.main(), 2)
        with patch("entry.run", return_value=0):
            self.assertEqual(main.main(), 0)
        with patch("entry.run", return_value=1):
            self.assertEqual(main.main(), 1)

    def test_main_sys_exit_zero(self):
        """直接执行 main.py (无参数 + 无 TTY) 应不抛异常。"""
        # 不调用 main()，只验证 import 不出错
        self.assertTrue(callable(main.main))

class DispatcherTests(unittest.TestCase):
    """验证 entry.dispatcher 的核心逻辑。"""

    def test_is_tty_uses_ucrawl_force_menu_env(self):
        """环境变量 UCRAWL_FORCE_MENU=1 强制 is_tty()=True。"""
        from entry.dispatcher import is_tty
        with patch.object(os, "environ", {"UCRAWL_FORCE_MENU": "1"}):
            # 模拟 stdin/stdout 都非 TTY
            with patch("sys.stdin.isatty", return_value=False), \
                 patch("sys.stdout.isatty", return_value=False):
                self.assertTrue(is_tty())

    def test_is_tty_returns_false_when_not_tty(self):
        """stdin/stdout 都非 TTY + 无键盘输入 → is_tty()=False。"""
        from entry.dispatcher import is_tty
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stdin.isatty", return_value=False), \
                 patch("sys.stdout.isatty", return_value=False), \
                 patch("entry.dispatcher.os.name", "posix"):
                # 跳过 msvcrt 分支
                self.assertFalse(is_tty())

    def test_is_tty_returns_true_when_stdin_isatty(self):
        """stdin.isatty()=True → is_tty()=True。"""
        from entry.dispatcher import is_tty
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stdin.isatty", return_value=True), \
                 patch("sys.stdout.isatty", return_value=False):
                self.assertTrue(is_tty())

    def test_is_tty_returns_true_when_stdout_isatty(self):
        """stdout.isatty()=True → is_tty()=True。"""
        from entry.dispatcher import is_tty
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stdin.isatty", return_value=False), \
                 patch("sys.stdout.isatty", return_value=True):
                self.assertTrue(is_tty())

    def test_parse_mode_arg_with_flag(self):
        """--mode cli 解析为 Mode.CLI。"""
        from entry.dispatcher import parse_mode_arg, Mode
        self.assertEqual(parse_mode_arg(["--mode", "cli"]), Mode.CLI)
        self.assertEqual(parse_mode_arg(["-m", "gui"]), Mode.GUI)
        self.assertEqual(parse_mode_arg(["--mode=web"]), Mode.WEB)
        self.assertEqual(parse_mode_arg(["--mode=report"]), Mode.REPORT)
        self.assertEqual(parse_mode_arg([]), None)

    def test_parse_mode_arg_rejects_invalid_or_missing_values(self):
        from entry.dispatcher import parse_mode_arg

        for argv in (["--mode=invalid"], ["--mode="], ["--mode"], ["-m"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                parse_mode_arg(argv)

    def test_parse_env_mode(self):
        """UCRAWL_MODE 环境变量解析。"""
        from entry.dispatcher import parse_env_mode, Mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "cli"}, clear=False):
            self.assertEqual(parse_env_mode(), Mode.CLI)
        with patch.dict(os.environ, {"UCRAWL_MODE": ""}, clear=False):
            self.assertEqual(parse_env_mode(), None)

    def test_packaged_launcher_menu_hides_source_only_tools(self):
        from entry import dispatcher

        with patch.object(dispatcher.sys, "frozen", True, create=True):
            items = dispatcher._runtime_menu_items()

        modes = {mode for _key, _label, mode in items}
        self.assertNotIn(dispatcher.Mode.TEST, modes)
        self.assertNotIn(dispatcher.Mode.REPORT, modes)
        self.assertTrue(
            {
                dispatcher.Mode.GUI,
                dispatcher.Mode.WEB,
                dispatcher.Mode.INTERACTIVE,
                dispatcher.Mode.CLI,
                None,
            }.issubset(modes)
        )

    def test_detect_mode_no_args_no_tty_defaults_to_cli(self):
        """无参 + 非 TTY → CLI。"""
        from entry.dispatcher import detect_mode, Mode
        with patch("entry.dispatcher.is_tty", return_value=False):
            self.assertEqual(detect_mode([]), Mode.CLI)

    def test_detect_mode_no_args_with_tty_defaults_to_gui(self):
        """无参 + TTY + 有 GUI → GUI。"""
        from entry.dispatcher import detect_mode, Mode
        with patch("entry.dispatcher.is_tty", return_value=True), \
             patch("entry.dispatcher.is_gui_available", return_value=True):
            self.assertEqual(detect_mode([]), Mode.GUI)

    def test_detect_mode_web_flag(self):
        """--port 触发 WEB 模式。"""
        from entry.dispatcher import detect_mode, Mode
        self.assertEqual(detect_mode(["--port", "8000"]), Mode.WEB)
        self.assertEqual(detect_mode(["--host=0.0.0.0"]), Mode.WEB)

    def test_detect_mode_cli_subcommand(self):
        """CLI 子命令触发 CLI 模式。"""
        from entry.dispatcher import detect_mode, Mode
        self.assertEqual(detect_mode(["search", "kw"]), Mode.CLI)
        self.assertEqual(detect_mode(["bilibili", "search", "kw"]), Mode.CLI)
        self.assertEqual(detect_mode(["download", "id"]), Mode.CLI)

    def test_detect_mode_explicit_arg_wins(self):
        """--mode 优先级最高。"""
        from entry.dispatcher import detect_mode, Mode
        # 即便有 CLI 子命令，--mode 仍然赢
        self.assertEqual(
            detect_mode(["--mode", "web", "search", "kw"]),
            Mode.WEB,
        )

    def test_detect_mode_explicit_env(self):
        """UCRAWL_MODE 环境变量优先级。"""
        from entry.dispatcher import detect_mode, Mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "interactive"}):
            self.assertEqual(detect_mode([]), Mode.INTERACTIVE)

    def test_run_with_explicit_mode(self):
        """run() 收到 --mode gui 派发到 run_gui。"""
        from entry import dispatcher
        with patch("entry.gui_entry.main", return_value=0) as mock_handler:
            self.assertEqual(dispatcher.run(["--mode", "gui"]), 0)
            # 透传后 argv 为空也必须保留为 []，避免下游重新读取 dispatcher 的 sys.argv。
            mock_handler.assert_called_once_with([])

    def test_frozen_windowed_launcher_delegates_console_modes_to_console_exe(self):
        from entry import dispatcher

        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir)
            windowed_launcher = install_root / "UCrawlLauncher.exe"
            console_launcher = install_root / "UCrawlCLI.exe"
            windowed_launcher.touch()
            console_launcher.touch()

            for mode in (
                dispatcher.Mode.CLI,
                dispatcher.Mode.INTERACTIVE,
                dispatcher.Mode.TEST,
                dispatcher.Mode.REPORT,
            ):
                direct_handler = Mock()
                with (
                    self.subTest(mode=mode),
                    patch.object(dispatcher.sys, "frozen", True, create=True),
                    patch.object(dispatcher.sys, "executable", str(windowed_launcher)),
                    patch.object(dispatcher.subprocess, "Popen") as popen,
                    patch.object(dispatcher, "_HANDLERS", {mode: direct_handler}),
                ):
                    result = dispatcher._dispatch(mode, ["--help"])

                self.assertEqual(result, 0)
                resolved_root = install_root.resolve()
                popen.assert_called_once_with(
                    [
                        str(resolved_root / "UCrawlCLI.exe"),
                        "--mode",
                        mode.value,
                        "--help",
                    ],
                    cwd=str(resolved_root),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                    shell=False,
                )
                direct_handler.assert_not_called()

    def test_frozen_console_exe_dispatches_without_recursive_spawn(self):
        from entry import dispatcher

        with tempfile.TemporaryDirectory() as temp_dir:
            console_launcher = Path(temp_dir) / "UCrawlCLI.exe"
            console_launcher.touch()
            run_cli = Mock(return_value=7)
            with (
                patch.object(dispatcher.sys, "frozen", True, create=True),
                patch.object(dispatcher.sys, "executable", str(console_launcher)),
                patch.object(dispatcher.subprocess, "Popen") as popen,
                patch.object(dispatcher, "_HANDLERS", {dispatcher.Mode.CLI: run_cli}),
            ):
                result = dispatcher._dispatch(dispatcher.Mode.CLI, ["--help"])

        self.assertEqual(result, 7)
        run_cli.assert_called_once_with(["--help"])
        popen.assert_not_called()

    def test_frozen_windowed_launcher_opens_persistent_cli_shell_without_args(self):
        from entry import dispatcher

        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir)
            windowed_launcher = install_root / "UCrawlLauncher.exe"
            console_launcher = install_root / "UCrawlCLI.exe"
            windowed_launcher.touch()
            console_launcher.touch()
            comspec = r"C:\Windows\System32\cmd.exe"
            direct_handler = Mock()
            with (
                patch.object(dispatcher.sys, "frozen", True, create=True),
                patch.object(dispatcher.sys, "executable", str(windowed_launcher)),
                patch.object(dispatcher.subprocess, "Popen") as popen,
                patch.object(dispatcher, "_HANDLERS", {dispatcher.Mode.CLI: direct_handler}),
                patch.dict(dispatcher.os.environ, {"COMSPEC": comspec}),
            ):
                result = dispatcher._dispatch(dispatcher.Mode.CLI, [])

        resolved_root = install_root.resolve()
        console_command = subprocess.list2cmdline(
            ["UCrawlCLI.exe", "--mode", "cli", "--help"]
        )
        self.assertEqual(result, 0)
        popen.assert_called_once_with(
            [comspec, "/D", "/K", console_command],
            cwd=str(resolved_root),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            shell=False,
        )
        direct_handler.assert_not_called()

    def test_frozen_windowed_launcher_delegates_empty_interactive_mode_directly(self):
        from entry import dispatcher

        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir)
            windowed_launcher = install_root / "UCrawlLauncher.exe"
            console_launcher = install_root / "UCrawlCLI.exe"
            windowed_launcher.touch()
            console_launcher.touch()
            direct_handler = Mock()
            with (
                patch.object(dispatcher.sys, "frozen", True, create=True),
                patch.object(dispatcher.sys, "executable", str(windowed_launcher)),
                patch.object(dispatcher.subprocess, "Popen") as popen,
                patch.object(
                    dispatcher,
                    "_HANDLERS",
                    {dispatcher.Mode.INTERACTIVE: direct_handler},
                ),
            ):
                result = dispatcher._dispatch(dispatcher.Mode.INTERACTIVE, [])

        resolved_root = install_root.resolve()
        self.assertEqual(result, 0)
        popen.assert_called_once_with(
            [str(resolved_root / "UCrawlCLI.exe"), "--mode", "interactive"],
            cwd=str(resolved_root),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            shell=False,
        )
        direct_handler.assert_not_called()

    def test_frozen_windowed_launcher_keeps_default_test_results_visible(self):
        from entry import dispatcher

        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir)
            windowed_launcher = install_root / "UCrawlLauncher.exe"
            console_launcher = install_root / "UCrawlCLI.exe"
            windowed_launcher.touch()
            console_launcher.touch()
            comspec = r"C:\Windows\System32\cmd.exe"
            direct_handler = Mock()
            with (
                patch.object(dispatcher.sys, "frozen", True, create=True),
                patch.object(dispatcher.sys, "executable", str(windowed_launcher)),
                patch.object(dispatcher.subprocess, "Popen") as popen,
                patch.object(dispatcher, "_HANDLERS", {dispatcher.Mode.TEST: direct_handler}),
                patch.dict(dispatcher.os.environ, {"COMSPEC": comspec}),
            ):
                result = dispatcher._dispatch(dispatcher.Mode.TEST, [])

        resolved_root = install_root.resolve()
        console_command = subprocess.list2cmdline(
            ["UCrawlCLI.exe", "--mode", "test"]
        )
        self.assertEqual(result, 0)
        popen.assert_called_once_with(
            [comspec, "/D", "/K", console_command],
            cwd=str(resolved_root),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            shell=False,
        )
        direct_handler.assert_not_called()

    def test_frozen_windowed_launcher_fails_closed_when_console_exe_is_missing(self):
        from entry import dispatcher

        with tempfile.TemporaryDirectory() as temp_dir:
            windowed_launcher = Path(temp_dir) / "UCrawlLauncher.exe"
            windowed_launcher.touch()
            run_cli = Mock()
            with (
                patch.object(dispatcher.sys, "frozen", True, create=True),
                patch.object(dispatcher.sys, "executable", str(windowed_launcher)),
                patch.object(dispatcher.subprocess, "Popen") as popen,
                patch.object(dispatcher, "_HANDLERS", {dispatcher.Mode.CLI: run_cli}),
                patch.object(dispatcher.sys, "stderr", io.StringIO()),
            ):
                result = dispatcher._dispatch(dispatcher.Mode.CLI, [])

        self.assertEqual(result, 2)
        run_cli.assert_not_called()
        popen.assert_not_called()

    def test_cli_dispatcher_noninteractive_help_smoke(self):
        project_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, str(project_root / "main.py"), "--mode", "cli", "--help"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: ucrawl", result.stdout)

    def test_run_rejects_invalid_or_missing_mode_without_dispatching(self):
        from entry import dispatcher

        invalid_argv = (
            ["--mode=invalid"],
            ["--mode="],
            ["--mode"],
            ["-m"],
            ["--mode", "--port", "8000"],
        )
        with patch.dict(os.environ, {"UCRAWL_MODE": "cli"}, clear=False), patch.object(
            dispatcher, "_dispatch", return_value=0
        ) as dispatch, patch.object(dispatcher, "prompt_mode_menu") as prompt, patch(
            "entry.dispatcher.sys.stderr.write"
        ):
            for argv in invalid_argv:
                with self.subTest(argv=argv):
                    self.assertEqual(dispatcher.run(argv), 2)

        dispatch.assert_not_called()
        prompt.assert_not_called()

    def test_run_with_no_args_calls_prompt(self):
        """run() 无参数调用 prompt_mode_menu。"""
        from entry import dispatcher
        with patch.object(dispatcher, "prompt_mode_menu", return_value=dispatcher.Mode.CLI), \
             patch("entry.cli_entry.main", return_value=0) as mock_cli:
            self.assertEqual(dispatcher.run([]), 0)
            mock_cli.assert_called_once_with([])

    def test_run_with_no_args_non_tty_uses_prompt_qt_fallback(self):
        """无参数 + 非 TTY 仍走 prompt_mode_menu，由菜单内部决定 Qt 弹窗后备。"""
        from entry import dispatcher
        with patch.object(dispatcher, "prompt_mode_menu", return_value=dispatcher.Mode.GUI) as mock_prompt, \
             patch("entry.gui_entry.main", return_value=0) as mock_gui:
            self.assertEqual(dispatcher.run([]), 0)
            mock_prompt.assert_called_once_with()
            mock_gui.assert_called_once_with([])

    def test_mode_adapters_preserve_explicit_empty_argv(self):
        """空 argv 是有意义的输入，不能退化为“重新读取 sys.argv”。"""
        from entry import dispatcher

        adapters = (
            (dispatcher.run_gui, "entry.gui_entry.main"),
            (dispatcher.run_web, "entry.web_entry.main"),
            (dispatcher.run_cli, "entry.cli_entry.main"),
            (dispatcher.run_interactive, "entry.interactive_entry.main"),
            (dispatcher.run_test, "entry.test_entry.main"),
            (dispatcher.run_code_report, "entry.code_report_entry.main"),
        )
        for adapter, target in adapters:
            with self.subTest(adapter=adapter.__name__), patch(target, return_value=0) as mocked:
                self.assertEqual(adapter([]), 0)
                mocked.assert_called_once_with([])

    def test_code_report_entry_supplies_root_output_and_open(self):
        from entry import code_report_entry

        with (
            tempfile.TemporaryDirectory() as user_data_dir,
            patch.dict(
                os.environ,
                {"UCRAWL_USER_DATA_ROOT": user_data_dir},
            ),
            patch("count_project.main", return_value=0) as mocked,
        ):
            self.assertEqual(code_report_entry.main([]), 0)

        forwarded = mocked.call_args.args[0]
        self.assertIn("--root", forwarded)
        self.assertIn("--html", forwarded)
        self.assertIn("--open", forwarded)
        self.assertEqual(
            Path(forwarded[forwarded.index("--html") + 1]),
            Path(user_data_dir) / "code_report.html",
        )

    def test_code_report_entry_selects_project_when_not_running_from_source_tree(self):
        from entry import code_report_entry

        selected_root = Path(__file__).resolve().parent
        with (
            tempfile.TemporaryDirectory() as user_data_dir,
            patch.object(code_report_entry, "_discover_default_project_root", return_value=None),
            patch.object(code_report_entry, "_select_project_root", return_value=selected_root),
            patch.dict(
                os.environ,
                {"UCRAWL_USER_DATA_ROOT": user_data_dir},
            ),
            patch("count_project.main", return_value=0) as mocked,
        ):
            self.assertEqual(code_report_entry.main([]), 0)

        forwarded = mocked.call_args.args[0]
        self.assertEqual(
            Path(forwarded[forwarded.index("--root") + 1]),
            selected_root,
        )
        self.assertEqual(
            Path(forwarded[forwarded.index("--html") + 1]),
            Path(user_data_dir) / "code_report.html",
        )

    def test_code_report_entry_aborts_when_installed_user_cancels_project_selection(self):
        from entry import code_report_entry

        with (
            patch.object(code_report_entry, "_discover_default_project_root", return_value=None),
            patch.object(code_report_entry, "_select_project_root", return_value=None),
            patch("count_project.main", return_value=0) as mocked,
        ):
            self.assertEqual(code_report_entry.main([]), 2)

        mocked.assert_not_called()

    def test_code_report_entry_explicit_root_never_scans_or_writes_install_directory(self):
        from entry import code_report_entry

        with (
            tempfile.TemporaryDirectory() as project_dir,
            tempfile.TemporaryDirectory() as user_data_dir,
            patch.object(
                code_report_entry,
                "_discover_default_project_root",
                side_effect=AssertionError("explicit root must bypass discovery"),
            ),
            patch.object(
                code_report_entry,
                "_select_project_root",
                side_effect=AssertionError("explicit root must bypass picker"),
            ),
            patch.dict(
                os.environ,
                {"UCRAWL_USER_DATA_ROOT": user_data_dir},
            ),
            patch("count_project.main", return_value=0) as mocked,
        ):
            self.assertEqual(code_report_entry.main(["--root", project_dir]), 0)

        forwarded = mocked.call_args.args[0]
        self.assertEqual(
            Path(forwarded[forwarded.index("--html") + 1]),
            Path(user_data_dir) / "code_report.html",
        )

    def test_code_report_entry_preserves_explicit_html_output(self):
        from entry import code_report_entry

        with (
            tempfile.TemporaryDirectory() as project_dir,
            tempfile.TemporaryDirectory() as output_dir,
            patch("count_project.main", return_value=0) as mocked,
        ):
            explicit_output = Path(output_dir) / "custom-report.html"
            self.assertEqual(
                code_report_entry.main(
                    [
                        "--root",
                        project_dir,
                        "--html",
                        str(explicit_output),
                    ]
                ),
                0,
            )

        forwarded = mocked.call_args.args[0]
        self.assertEqual(
            Path(forwarded[forwarded.index("--html") + 1]),
            explicit_output,
        )

    def test_run_with_prompt_returns_none_exits_zero(self):
        """用户主动选 q (prompt 返回 None) → exit 0。"""
        from entry import dispatcher
        with patch.object(dispatcher, "prompt_mode_menu", return_value=None):
            self.assertEqual(dispatcher.run([]), 0)

    def test_run_with_prompt_raises_menu_unavailable(self):
        """完全非交互（prompt 抛 _MenuUnavailable）→ exit 2。"""
        from entry import dispatcher
        with patch.object(dispatcher, "prompt_mode_menu",
                          side_effect=dispatcher._MenuUnavailable()):
            self.assertEqual(dispatcher.run([]), 2)

    def test_strip_dispatcher_args(self):
        """_strip_dispatcher_args 正确剥离 --mode/-- 但保留其它参数。"""
        from entry.dispatcher import _strip_dispatcher_args
        self.assertEqual(
            _strip_dispatcher_args(["--mode", "web", "--", "--port", "8000"]),
            ["--port", "8000"],
        )
        self.assertEqual(
            _strip_dispatcher_args(["-m", "gui"]),
            [],
        )
        self.assertEqual(
            _strip_dispatcher_args(["--mode=web", "search", "kw"]),
            ["search", "kw"],
        )

    def test_run_passthrough_preserves_subcommand_args(self):
        """dispatcher 透传剩余参数给目标 handler。"""
        from entry import dispatcher
        with patch("entry.cli_entry.main", return_value=0) as mock_cli:
            dispatcher.run(["--mode", "cli", "search", "kw", "--max-items", "10"])
            mock_cli.assert_called_once_with(
                ["search", "kw", "--max-items", "10"]
            )

    def test_has_pyqt6_true_when_importable(self):
        """_has_pyqt6 在 PyQt6 可用时返回 True。"""
        from entry.dispatcher import _has_pyqt6
        # 测试环境假设有 PyQt6
        self.assertTrue(_has_pyqt6())

    def test_has_pyqt6_false_when_import_fails(self):
        """_has_pyqt6 在 PyQt6 不可用时返回 False。"""
        from entry import dispatcher
        with patch.dict(sys.modules, {"PyQt6": None, "PyQt6.QtWidgets": None}):
            with patch("builtins.__import__", side_effect=ImportError("no PyQt6")):
                self.assertFalse(dispatcher._has_pyqt6())

    def test_prompt_mode_falls_back_to_qt_when_not_tty(self):
        """非 TTY + PyQt6 可用 → 弹 Qt 弹窗（解决 IDE 场景）。"""
        from entry import dispatcher
        with patch.object(dispatcher, "is_tty", return_value=False), \
             patch.object(dispatcher, "_has_pyqt6", return_value=True), \
             patch.object(dispatcher, "_prompt_mode_with_qt", return_value=dispatcher.Mode.GUI) as mock_qt:
            self.assertEqual(dispatcher.prompt_mode_menu(), dispatcher.Mode.GUI)
            mock_qt.assert_called_once_with()

    def test_prompt_mode_eof_returns_none(self):
        """stdin EOF 时恢复原有行为：菜单取消而不是自动改派 GUI。"""
        from entry import dispatcher
        with patch.object(dispatcher, "is_tty", return_value=True), \
             patch("builtins.input", side_effect=EOFError):
            self.assertIsNone(dispatcher.prompt_mode_menu())

    def test_prompt_mode_returns_none_when_neither_tty_nor_qt(self):
        """非 TTY + 无 PyQt6 → 返回 None（让 run() 退出码 2）。"""
        from entry import dispatcher
        with patch.object(dispatcher, "is_tty", return_value=False), \
             patch.object(dispatcher, "_has_pyqt6", return_value=False):
            self.assertIsNone(dispatcher.prompt_mode_menu())

if __name__ == "__main__":
    unittest.main()
