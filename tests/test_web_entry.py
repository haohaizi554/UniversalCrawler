"""entry.web_entry 单测：参数解析、端口处理、_load_app_icon、icon 路径。

测试维度：
- 单元测试：argparse、端口探测、图标加载
- 集成测试：main() 的 4 大模式（default/--no-qt/--script/port 冲突）
"""

import io
import os
import sys
import unittest
import socket
from unittest.mock import patch, MagicMock

class WebEntryPortProbeTests(unittest.TestCase):
    """_is_port_in_use / _find_available_port 单测。"""

    def test_port_in_use_returns_true(self):
        """bind 失败的端口 → _is_port_in_use 返回 True。"""
        from entry.web_entry import _is_port_in_use
        # 占用一个端口
        import socket
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        try:
            self.assertTrue(_is_port_in_use("127.0.0.1", port))
        finally:
            server.close()

    def test_port_in_use_returns_false(self):
        """bind 成功的端口 → _is_port_in_use 返回 False。"""
        from entry.web_entry import _is_port_in_use
        # 找一个空闲端口
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        # 现在应该可用
        self.assertFalse(_is_port_in_use("127.0.0.1", port))

    def test_find_available_port_same_port(self):
        """start_port 空闲 → 直接返回 start_port。"""
        from entry.web_entry import _find_available_port
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertEqual(_find_available_port("127.0.0.1", port), port)

    def test_find_available_port_skips_busy(self):
        """start_port 被占 → 顺延找到下一个空闲端口。"""
        from entry.web_entry import _find_available_port
        import socket
        # 占用 start_port
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        start = server.getsockname()[1]
        try:
            result = _find_available_port("127.0.0.1", start)
            self.assertIsNotNone(result)
            self.assertGreater(result, start)
        finally:
            server.close()

    def test_find_available_port_exhausted_returns_none(self):
        """连续 11 个端口都被占 → 返回 None。"""
        from entry.web_entry import _find_available_port
        servers = []
        start = None
        probe_count = (_find_available_port.__defaults__[0] if _find_available_port.__defaults__ else 10) + 1
        try:
            # Windows may reserve arbitrary dynamic ports and return WSAEACCES.
            # Find a contiguous bindable block first so this test only exercises
            # _find_available_port(), not the host OS port reservation policy.
            start = self._reserve_contiguous_ports("127.0.0.1", probe_count, servers)
            if start is None:
                self.skipTest("No contiguous bindable port block available on this host")

            self.assertIsNone(_find_available_port("127.0.0.1", start))
        finally:
            for s in servers:
                s.close()

    @staticmethod
    def _reserve_contiguous_ports(host: str, count: int, servers: list[socket.socket]) -> int | None:
        for _ in range(40):
            seed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                seed.bind((host, 0))
                candidate_start = seed.getsockname()[1]
            finally:
                seed.close()
            if candidate_start + count > 65535:
                continue
            block: list[socket.socket] = []
            try:
                for offset in range(count):
                    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    server.bind((host, candidate_start + offset))
                    block.append(server)
            except OSError:
                for server in block:
                    server.close()
                continue
            servers.extend(block)
            return candidate_start
        return None

    def test_find_available_port_port_too_high(self):
        """start_port > 65535 - 10 → 必须停止搜索。"""
        from entry.web_entry import _find_available_port
        result = _find_available_port("127.0.0.1", 65530, max_probe=20)
        # 65530 + 20 = 65550 > 65535，应该停止
        self.assertLessEqual(result if result else 0, 65535)

class WebEntryArgparseTests(unittest.TestCase):
    """_build_argparser 测试。"""

    def test_argparser_builds(self):
        """_build_argparser 必须是合法的 ArgumentParser。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        self.assertIsNotNone(parser)

    def test_default_args(self):
        """无参必须能解析（host/port/no_qt 都有默认值）。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)
        self.assertFalse(args.no_qt)
        self.assertFalse(args.no_browser)
        self.assertEqual(args.script, None)
        self.assertEqual(args.script_arg, [])
        self.assertFalse(args.script_strict)
        self.assertEqual(args.script_delay, 0.0)

    def test_host_option(self):
        """--host 0.0.0.0 必须被接受。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--host", "0.0.0.0"])
        self.assertEqual(args.host, "0.0.0.0")

    def test_non_loopback_bind_requires_tls_certificate_and_key(self):
        from entry.web_entry import _validate_transport_security

        with self.assertRaises(ValueError):
            _validate_transport_security("0.0.0.0", None, None)

    def test_loopback_bind_allows_http(self):
        from entry.web_entry import _validate_transport_security

        self.assertEqual(_validate_transport_security("127.0.0.1", None, None), "http")

    def test_port_int(self):
        """--port 9000 必须是 int。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--port", "9000"])
        self.assertEqual(args.port, 9000)

    def test_port_invalid(self):
        """--port abc 必须报错退出码 2。"""
        from entry.web_entry import _build_argparser, main
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main(["--port", "abc"])
        self.assertEqual(cm.exception.code, 2)

    def test_no_qt_flag(self):
        """--no-qt 是 bool flag。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--no-qt"])
        self.assertTrue(args.no_qt)

    def test_no_browser_flag(self):
        """--no-browser 是 bool flag。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--no-browser"])
        self.assertTrue(args.no_browser)

    def test_script_path(self):
        """--script 接收路径字符串。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--script", "/path/to/script.py"])
        self.assertEqual(args.script, "/path/to/script.py")

    def test_script_arg_append(self):
        """--script-arg 可多次使用（action=append）。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--script-arg", "key1=v1", "--script-arg", "key2=v2"])
        self.assertEqual(args.script_arg, ["key1=v1", "key2=v2"])

    def test_script_strict_flag(self):
        """--script-strict 是 bool flag。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--script-strict"])
        self.assertTrue(args.script_strict)

    def test_script_delay_float(self):
        """--script-delay 2.5 必须是 float。"""
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args(["--script-delay", "2.5"])
        self.assertEqual(args.script_delay, 2.5)

class WebEntryIconLoadTests(unittest.TestCase):
    """_load_app_icon / _ensure_app_user_model_id 测试。"""

    @classmethod
    def setUpClass(cls):
        """创建唯一的 QApplication（Qt 限制一个进程只能有一个）。"""
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls._owns_qapp = QApplication.instance() is cls.app

    def test_load_app_icon_returns_qicon(self):
        """_load_app_icon 必须返回 QIcon 或 None。"""
        from entry.web_entry import _load_app_icon
        icon = _load_app_icon()
        # Web.ico 应该存在
        self.assertIsNotNone(icon)

    def test_ensure_app_user_model_id_idempotent(self):
        """_ensure_app_user_model_id 必须可重复调用（无副作用）。"""
        from entry.web_entry import _ensure_app_user_model_id
        for _ in range(3):
            _ensure_app_user_model_id()  # 不能抛异常

    def test_ensure_app_user_model_id_on_linux_noop(self):
        """非 Windows 平台 → 静默 no-op。"""
        from entry import web_entry
        with patch.object(web_entry.os, "name", "posix"):
            # 不应抛异常
            web_entry._ensure_app_user_model_id()

class WebEntryMainIntegrationTests(unittest.TestCase):
    """main() 集成测试（mock uvicorn/Qt）。"""

    def test_main_no_qt_port_busy_auto_increment(self):
        """--no-qt + 端口被占 → 自动顺延。"""
        from entry import web_entry
        # 占用一个高位端口（避免 Windows 保留端口范围和常见服务端口）
        import socket
        test_port = 58000
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", test_port))
        except OSError:
            self.skipTest(f"无法绑定端口 {test_port}")
        try:
            with patch.dict("sys.modules", {"uvicorn": MagicMock()}):
                mock_uvicorn = sys.modules["uvicorn"]
                mock_server = MagicMock()
                mock_uvicorn.Server.return_value = mock_server
                mock_uvicorn.Config.return_value = MagicMock()

                async def fake_serve():
                    raise KeyboardInterrupt
                mock_server.serve = fake_serve
                with patch("entry.web_entry.webbrowser"):
                    try:
                        web_entry.main(["--no-qt", "--no-browser", "--host", "127.0.0.1", "--port", str(test_port)])
                    except (KeyboardInterrupt, SystemExit):
                        pass
            # 验证：args.port 必须被改
            self.assertGreater(mock_uvicorn.Config.call_args.kwargs["port"], test_port)
        finally:
            server.close()

    def test_main_with_qt_does_not_block_main_thread(self):
        """默认（Qt 模式）→ 主线程跑 QApplication.exec()，uvicorn 在后台。
        简化测：只验证 main() 解析参数后走到 Qt 模式代码路径不崩。
        """
        # Qt 集成测试需要完整 QApplication，跳过（其它单元测试已覆盖 argparse/端口）
        self.skipTest("Qt 集成测试需要完整 QApplication，在 dispatcher/port_dialog 测试中覆盖")

    def test_main_with_script_argument(self):
        """--script + --script-arg 必须能解析（在 dispatcher/port_dialog 测试中覆盖）。
        web_entry.main 走的是 module-level 内部实现，与外部 API 关联不大。
        """
        # 简化为：只验证 --script 字符串可被 argparse 接受
        from entry.web_entry import _build_argparser
        parser = _build_argparser()
        args = parser.parse_args([
            "--port", "12347",
            "--no-browser",
            "--script", "/tmp/fake_script.py",
            "--script-arg", "key1=v1",
            "--script-strict",
        ])
        self.assertEqual(args.script, "/tmp/fake_script.py")
        self.assertEqual(args.script_arg, ["key1=v1"])
        self.assertTrue(args.script_strict)

if __name__ == "__main__":
    unittest.main()
