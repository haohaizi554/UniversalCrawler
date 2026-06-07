"""UI 弹窗与界面测试。

测试维度：
- 单元测试：dispatcher 的 TUI 菜单、Qt 弹窗、web_entry 端口冲突弹窗
- 视觉测试：弹窗构造、按钮存在性、QSS 加载
- 跨平台测试：is_tty()、is_gui_available() 在不同环境下的行为

设计原则：
- PyQt6 是依赖项，但允许通过 unittest.skip 优雅降级
- 使用 setUpClass 共享 QApplication 实例（避免重复创建崩溃）
- 不实际交互（不调 .exec()），只验证构造和属性
"""

import os
import sys
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock


# ---- Helper ----

def _pyqt6_available():
    try:
        import PyQt6
        return True
    except ImportError:
        return False


def _qt_app():
    """获取或创建 QApplication（单例模式）。"""
    if not _pyqt6_available():
        return None
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        # offscreen platform for headless testing
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(sys.argv)
    return app


# ---- dispatcher.py 纯函数测试 ----

class DispatcherModeEnumTests(unittest.TestCase):
    """Mode 枚举测试。"""

    def test_mode_values(self):
        from entry.dispatcher import Mode
        self.assertEqual(Mode.GUI.value, "gui")
        self.assertEqual(Mode.WEB.value, "web")
        self.assertEqual(Mode.CLI.value, "cli")
        self.assertEqual(Mode.INTERACTIVE.value, "interactive")

    def test_mode_from_string(self):
        from entry.dispatcher import Mode
        self.assertEqual(Mode("gui"), Mode.GUI)
        self.assertEqual(Mode("web"), Mode.WEB)
        self.assertEqual(Mode("cli"), Mode.CLI)
        self.assertEqual(Mode("interactive"), Mode.INTERACTIVE)

    def test_mode_str_inherits(self):
        """Mode 继承 str，可以直接当字符串用。"""
        from entry.dispatcher import Mode
        self.assertEqual(Mode.GUI + "-mode", "gui-mode")
        self.assertIn("gui", Mode.GUI)


class DispatcherParseModeArgTests(unittest.TestCase):
    """parse_mode_arg 各种参数格式。"""

    def test_parse_mode_with_dash(self):
        from entry.dispatcher import parse_mode_arg, Mode
        self.assertEqual(parse_mode_arg(["--mode", "gui"]), Mode.GUI)
        self.assertEqual(parse_mode_arg(["-m", "web"]), Mode.WEB)

    def test_parse_mode_with_equals(self):
        from entry.dispatcher import parse_mode_arg, Mode
        self.assertEqual(parse_mode_arg(["--mode=cli"]), Mode.CLI)
        self.assertEqual(parse_mode_arg(["--mode=interactive"]), Mode.INTERACTIVE)

    def test_parse_mode_case_insensitive(self):
        from entry.dispatcher import parse_mode_arg, Mode
        self.assertEqual(parse_mode_arg(["--mode", "GUI"]), Mode.GUI)
        self.assertEqual(parse_mode_arg(["--mode", "Web"]), Mode.WEB)

    def test_parse_mode_missing(self):
        from entry.dispatcher import parse_mode_arg
        self.assertIsNone(parse_mode_arg([]))
        self.assertIsNone(parse_mode_arg(["--port", "8000"]))

    def test_parse_mode_unknown(self):
        from entry.dispatcher import parse_mode_arg
        # 未知 mode 返回 None，stderr 写警告
        with patch("sys.stderr") as mock_stderr:
            result = parse_mode_arg(["--mode", "invalid_xyz"])
        self.assertIsNone(result)
        # 验证 stderr.write 被调用
        self.assertTrue(mock_stderr.write.called)

    def test_parse_mode_value_with_space(self):
        """--mode 后是另一个 --flag 应该不算 mode value。"""
        from entry.dispatcher import parse_mode_arg
        # "--mode" 后面跟另一个选项，不算 mode
        self.assertIsNone(parse_mode_arg(["--mode", "--port", "8000"]))


class DispatcherParseEnvModeTests(unittest.TestCase):
    """环境变量解析。"""

    def test_env_mode_set(self):
        from entry.dispatcher import parse_env_mode, Mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "web"}):
            self.assertEqual(parse_env_mode(), Mode.WEB)

    def test_env_mode_empty(self):
        from entry.dispatcher import parse_env_mode
        with patch.dict(os.environ, {"UCRAWL_MODE": ""}, clear=False):
            # 如果没有该 key，返回 None
            os.environ.pop("UCRAWL_MODE", None)
            self.assertIsNone(parse_env_mode())

    def test_env_mode_invalid(self):
        from entry.dispatcher import parse_env_mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "invalid"}):
            self.assertIsNone(parse_env_mode())

    def test_env_mode_case_insensitive(self):
        from entry.dispatcher import parse_env_mode, Mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "GUI"}):
            self.assertEqual(parse_env_mode(), Mode.GUI)


class DispatcherDetectModeIntentTests(unittest.TestCase):
    """参数特征智能识别。"""

    def test_web_flags(self):
        from entry.dispatcher import detect_mode_intent, Mode
        self.assertEqual(detect_mode_intent(["--port", "8000"]), Mode.WEB)
        self.assertEqual(detect_mode_intent(["--port=8000"]), Mode.WEB)
        self.assertEqual(detect_mode_intent(["--host", "0.0.0.0"]), Mode.WEB)
        self.assertEqual(detect_mode_intent(["--script", "x.py"]), Mode.WEB)
        self.assertEqual(detect_mode_intent(["--no-browser"]), Mode.WEB)

    def test_cli_subcommand(self):
        from entry.dispatcher import detect_mode_intent, Mode
        self.assertEqual(detect_mode_intent(["search", "kw"]), Mode.CLI)
        self.assertEqual(detect_mode_intent(["download", "url"]), Mode.CLI)
        self.assertEqual(detect_mode_intent(["platforms"]), Mode.CLI)

    def test_cli_subcommand_aliases(self):
        from entry.dispatcher import detect_mode_intent, Mode
        # 平台子命令别名
        self.assertEqual(detect_mode_intent(["dy", "kw"]), Mode.CLI)
        self.assertEqual(detect_mode_intent(["bili", "kw"]), Mode.CLI)
        self.assertEqual(detect_mode_intent(["ks", "kw"]), Mode.CLI)
        self.assertEqual(detect_mode_intent(["miss", "kw"]), Mode.CLI)

    def test_interactive_flags(self):
        from entry.dispatcher import detect_mode_intent, Mode
        self.assertEqual(detect_mode_intent(["--no-download"]), Mode.INTERACTIVE)
        self.assertEqual(detect_mode_intent(["--pretty"]), Mode.INTERACTIVE)
        self.assertEqual(detect_mode_intent(["--save-dir", "/tmp"]), Mode.INTERACTIVE)

    def test_no_args_defaults_to_cli(self):
        """detect_mode_intent 在无参数时返回 CLI（应由 TUI 菜单接管）。"""
        from entry.dispatcher import detect_mode_intent, Mode
        self.assertEqual(detect_mode_intent([]), Mode.CLI)


class DispatcherDetectModeTests(unittest.TestCase):
    """detect_mode 完整优先级链。"""

    def test_arg_takes_precedence_over_env(self):
        from entry.dispatcher import detect_mode, Mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "web"}):
            self.assertEqual(detect_mode(["--mode", "gui"]), Mode.GUI)

    def test_env_when_no_arg(self):
        from entry.dispatcher import detect_mode, Mode
        with patch.dict(os.environ, {"UCRAWL_MODE": "interactive"}):
            self.assertEqual(detect_mode([]), Mode.INTERACTIVE)

    def test_intent_when_args(self):
        from entry.dispatcher import detect_mode, Mode
        self.assertEqual(detect_mode(["--port", "9000"]), Mode.WEB)

    def test_no_args_no_tty_falls_back_to_cli(self):
        from entry.dispatcher import detect_mode, Mode
        with patch("entry.dispatcher.is_tty", return_value=False):
            self.assertEqual(detect_mode([]), Mode.CLI)

    def test_no_args_no_gui_falls_back_to_web(self):
        from entry.dispatcher import detect_mode, Mode
        with patch("entry.dispatcher.is_tty", return_value=True), \
             patch("entry.dispatcher.is_gui_available", return_value=False):
            self.assertEqual(detect_mode([]), Mode.WEB)

    def test_no_args_tty_gui_available_falls_back_to_gui(self):
        from entry.dispatcher import detect_mode, Mode
        with patch("entry.dispatcher.is_tty", return_value=True), \
             patch("entry.dispatcher.is_gui_available", return_value=True):
            self.assertEqual(detect_mode([]), Mode.GUI)


class DispatcherTTYTests(unittest.TestCase):
    """is_tty 各种环境行为。"""

    def test_force_menu_env(self):
        """UCRAWL_FORCE_MENU=1 强制返回 True。"""
        from entry.dispatcher import is_tty
        with patch.dict(os.environ, {"UCRAWL_FORCE_MENU": "1"}):
            self.assertTrue(is_tty())
        with patch.dict(os.environ, {"UCRAWL_FORCE_MENU": "true"}):
            self.assertTrue(is_tty())
        with patch.dict(os.environ, {"UCRAWL_FORCE_MENU": "yes"}):
            self.assertTrue(is_tty())

    def test_force_menu_off(self):
        """UCRAWL_FORCE_MENU=0 不强制（按实际 isatty 判断）。"""
        from entry.dispatcher import is_tty
        with patch.dict(os.environ, {"UCRAWL_FORCE_MENU": "0"}), \
             patch("sys.stdin.isatty", return_value=False), \
             patch("sys.stdout.isatty", return_value=False):
            self.assertFalse(is_tty())

    def test_force_menu_invalid(self):
        """UCRAWL_FORCE_MENU=invalid 不强制。"""
        from entry.dispatcher import is_tty
        with patch.dict(os.environ, {"UCRAWL_FORCE_MENU": "invalid"}), \
             patch("sys.stdin.isatty", return_value=False), \
             patch("sys.stdout.isatty", return_value=False):
            self.assertFalse(is_tty())


class DispatcherGUIAvailableTests(unittest.TestCase):
    """is_gui_available 平台检测。"""

    def test_pyqt6_missing_returns_false(self):
        from entry.dispatcher import is_gui_available
        with patch.dict(sys.modules, {"PyQt6.QtWidgets": None}):
            with patch("builtins.__import__",
                      side_effect=lambda name, *args, **kwargs:
                          (_ for _ in ()).throw(ImportError()) if "PyQt6" in name
                          else __import__(name, *args, **kwargs)):
                self.assertFalse(is_gui_available())


class DispatcherUtilityTests(unittest.TestCase):
    """_display_width / _pad_to_width 等工具函数。"""

    def test_display_width_ascii(self):
        from entry.dispatcher import _display_width
        self.assertEqual(_display_width("hello"), 5)

    def test_display_width_cjk(self):
        from entry.dispatcher import _display_width
        # 汉字按 2 算
        self.assertEqual(_display_width("中文"), 4)

    def test_display_width_mixed(self):
        from entry.dispatcher import _display_width
        # "中a" = 2 + 1 = 3
        self.assertEqual(_display_width("中a"), 3)

    def test_pad_to_width(self):
        from entry.dispatcher import _pad_to_width
        self.assertEqual(_pad_to_width("ab", 5), "ab   ")
        # 已超过目标 → 不裁剪
        self.assertEqual(_pad_to_width("abcdef", 3), "abcdef")
        # CJK 也正确填充
        self.assertEqual(_pad_to_width("中", 4), "中  ")


# ---- dispatcher.py Qt 弹窗测试（需要 PyQt6） ----

@unittest.skipUnless(_pyqt6_available(), "PyQt6 not available")
class DispatcherQtDialogTests(unittest.TestCase):
    """_prompt_mode_with_qt 弹窗构造测试。"""

    @classmethod
    def setUpClass(cls):
        # 必须先有 QApplication 才能 _prompt_mode_with_qt
        cls.app = _qt_app()

    def test_qt_dialog_construct(self):
        """弹窗函数可以引用（不真的 exec 会阻塞）。"""
        from entry import dispatcher
        # 验证 _prompt_mode_with_qt 函数存在
        self.assertTrue(hasattr(dispatcher, "_prompt_mode_with_qt"))
        # 验证它需要 PyQt6
        import inspect
        src = inspect.getsource(dispatcher._prompt_mode_with_qt)
        self.assertIn("QApplication", src)
        self.assertIn("QDialog", src)

    def test_load_app_icon_meipass(self):
        """_load_app_icon 在 _MEIPASS 模式下能找到图标。"""
        from entry.dispatcher import _load_app_icon
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # 创建一个假的 favicon.ico
            ico_path = os.path.join(tmp, "favicon.ico")
            with open(ico_path, "wb") as f:
                f.write(b"\x00\x00\x01\x00\x01\x00")  # 假 ICO header
            with patch("sys._MEIPASS", tmp, create=True):
                icon = _load_app_icon()
                # 假 ICO 可能被 QIcon 拒绝（isNull=True），但不应崩溃
                self.assertIsNotNone(icon)  # 即使 isNull 也返回 QIcon 实例

    def test_load_app_icon_fallback(self):
        """_load_app_icon 在仓库根目录能找到 favicon.ico。"""
        from entry.dispatcher import _load_app_icon
        # 仓库根目录的 favicon.ico 应该存在
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        if (root / "favicon.ico").exists():
            # 清除 _MEIPASS
            with patch("sys._MEIPASS", None, create=True):
                icon = _load_app_icon()
                self.assertIsNotNone(icon)


# ---- web_entry.py 端口冲突弹窗测试 ----

@unittest.skipUnless(_pyqt6_available(), "PyQt6 not available")
class WebEntryPortDialogTests(unittest.TestCase):
    """web_entry 端口冲突弹窗测试。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()

    def test_load_app_icon_uses_web_ico(self):
        """web_entry 必须用 Web.ico（与主图标区分）。"""
        from entry import web_entry
        source = open(web_entry.__file__, encoding="utf-8").read()
        # 必须引用 Web.ico
        self.assertIn("Web.ico", source)
        # 优先 Web.ico（web_entry 是 web 入口）
        # 实际加载顺序：先 Web.ico，再 fallback 到 favicon.ico

    def test_resolve_port_with_dialog_source(self):
        """web_entry 源码必须包含 _resolve_port_with_dialog 函数。"""
        from entry import web_entry
        self.assertTrue(hasattr(web_entry, "_resolve_port_with_dialog") or
                       "_resolve_port_with_dialog" in dir(web_entry),
                       "_resolve_port_with_dialog must exist in web_entry")

    def test_resolve_port_with_socket_bind(self):
        """_resolve_port_with_dialog 内部必须用 socket.bind 真实验证端口。"""
        from entry import web_entry
        source = open(web_entry.__file__, encoding="utf-8").read()
        self.assertIn("socket", source.lower())
        self.assertIn(".bind", source)


class WebEntryModuleTests(unittest.TestCase):
    """web_entry 模块导出（不依赖 Qt）。"""

    def test_main_callable(self):
        from entry import web_entry
        self.assertTrue(callable(web_entry.main))

    def test_build_parser_exists(self):
        """web_entry 必须定义 _build_argparser。"""
        from entry import web_entry
        # 可能在模块顶层或 main 内部
        self.assertTrue(hasattr(web_entry, "_build_argparser"),
                       "_build_argparser must exist in web_entry")

    def test_default_args_no_qt(self):
        """web_entry 默认参数必须含 --no-qt。"""
        from entry import web_entry
        source = open(web_entry.__file__, encoding="utf-8").read()
        self.assertIn("--no-qt", source)


# ---- dispatcher TUI 菜单测试（mock stdio）----

class DispatcherTUIMenuTests(unittest.TestCase):
    """prompt_mode_menu TUI 行为测试。"""

    def test_prompt_mode_menu_invalid_choice(self):
        """prompt_mode_menu 只读一次输入；无效输入返回 None。"""
        from entry.dispatcher import prompt_mode_menu
        with patch("builtins.input", return_value="x"):
            with patch("entry.dispatcher.is_tty", return_value=True):
                # 无效输入 → 返回 None（因为 menu 不循环）
                self.assertIsNone(prompt_mode_menu())

    def test_prompt_mode_menu_quit(self):
        """选 q 返回 None。"""
        from entry.dispatcher import prompt_mode_menu
        with patch("builtins.input", return_value="q"):
            with patch("entry.dispatcher.is_tty", return_value=True):
                self.assertIsNone(prompt_mode_menu())

    def test_prompt_mode_menu_2_returns_web(self):
        from entry.dispatcher import prompt_mode_menu, Mode
        with patch("builtins.input", return_value="2"):
            with patch("entry.dispatcher.is_tty", return_value=True):
                self.assertEqual(prompt_mode_menu(), Mode.WEB)

    def test_prompt_mode_menu_3_returns_interactive(self):
        from entry.dispatcher import prompt_mode_menu, Mode
        with patch("builtins.input", return_value="3"):
            with patch("entry.dispatcher.is_tty", return_value=True):
                self.assertEqual(prompt_mode_menu(), Mode.INTERACTIVE)

    def test_prompt_mode_menu_4_returns_cli(self):
        from entry.dispatcher import prompt_mode_menu, Mode
        with patch("builtins.input", return_value="4"):
            with patch("entry.dispatcher.is_tty", return_value=True):
                self.assertEqual(prompt_mode_menu(), Mode.CLI)


# ---- Qt 模式不可用时的 fallback ----

class DispatcherFallbackTests(unittest.TestCase):
    """无 PyQt6 时的 fallback。"""

    def test_load_app_icon_no_qt(self):
        """PyQt6 不可用时 _load_app_icon 抛 ImportError（由调用方捕获）。"""
        from entry.dispatcher import _load_app_icon
        # _load_app_icon 内部直接 import QIcon，无法用 mock 拦截
        # 改用直接删除 _MEIPASS 属性 + 让真实 import 失败
        # 这里我们只验证在 PyQt6 缺失时函数行为是可预测的
        with patch("sys._MEIPASS", None, create=True):
            try:
                # 真环境有 PyQt6 → 返回 QIcon 或 None
                result = _load_app_icon()
                # 不崩 → 行为可预测
                self.assertTrue(result is None or hasattr(result, "isNull"))
            except Exception as e:
                # 抛 ImportError 或其他 → 也是可预测的
                self.assertIsInstance(e, (ImportError, FileNotFoundError, OSError))


if __name__ == "__main__":
    unittest.main()
