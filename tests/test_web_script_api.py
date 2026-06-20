import io
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

class ScriptApiParsingTests(unittest.TestCase):
    def test_parse_kv_args_auto_converts_types(self):
        from app.web.script_api import parse_kv_args

        parsed = parse_kv_args(["name=alice", "count=5", "ratio=2.5", "enabled=true", "raw=x-y", "invalid"])

        self.assertEqual(parsed["name"], "alice")
        self.assertEqual(parsed["count"], 5)
        self.assertEqual(parsed["ratio"], 2.5)
        self.assertTrue(parsed["enabled"])
        self.assertEqual(parsed["raw"], "x-y")
        self.assertNotIn("invalid", parsed)

    def test_parse_script_args_collects_repeated_script_arg(self):
        from app.web.script_api import parse_script_args

        args = parse_script_args(
            ["--script", "demo.py", "--script-arg", "a=1", "--script-arg", "b=true", "--script-strict"]
        )

        self.assertEqual(args.script, "demo.py")
        self.assertEqual(args.script_arg, ["a=1", "b=true"])
        self.assertTrue(args.script_strict)

class ScriptApiExecutionTests(unittest.TestCase):
    def test_run_injected_script_returns_one_when_file_missing(self):
        from app.web.script_api import run_injected_script

        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            rc = run_injected_script("missing-script.py", controller=object())

        self.assertEqual(rc, 1)
        self.assertIn("脚本不存在", stderr.getvalue())

    def test_run_injected_script_requires_main_function(self):
        from app.web.script_api import run_injected_script

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "no_main.py"
            script.write_text("VALUE = 1\n", encoding="utf-8")
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                rc = run_injected_script(str(script), controller=object())

        self.assertEqual(rc, 1)
        self.assertIn("必须定义 main", stderr.getvalue())

    def test_run_injected_script_returns_main_result(self):
        from app.web.script_api import run_injected_script

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok_main.py"
            script.write_text(
                textwrap.dedent(
                    """
                    def main(controller, **kwargs):
                        assert kwargs["count"] == 3
                        return 7
                    """
                ),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                rc = run_injected_script(str(script), controller=object(), count=3)

        self.assertEqual(rc, 7)
        self.assertIn("脚本返回: 7", stderr.getvalue())

    def test_run_injected_script_normalizes_non_int_return_to_zero(self):
        from app.web.script_api import run_injected_script

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "string_main.py"
            script.write_text(
                textwrap.dedent(
                    """
                    def main(controller, **kwargs):
                        return "done"
                    """
                ),
                encoding="utf-8",
            )

            rc = run_injected_script(str(script), controller=object())

        self.assertEqual(rc, 0)

class ScriptApiAsyncTests(unittest.TestCase):
    def test_inject_script_async_does_not_exit_when_not_strict(self):
        from app.web.script_api import inject_script_async

        with (
            patch("app.web.script_api.run_injected_script", return_value=2),
            patch("os._exit") as exit_mock,
        ):
            thread = inject_script_async("demo.py", controller=object(), strict=False)
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        exit_mock.assert_not_called()

    def test_inject_script_async_exits_when_strict_and_failed(self):
        from app.web.script_api import inject_script_async

        with (
            patch("app.web.script_api.run_injected_script", return_value=3),
            patch("os._exit") as exit_mock,
        ):
            thread = inject_script_async("demo.py", controller=object(), strict=True)
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        exit_mock.assert_called_once_with(3)

if __name__ == "__main__":
    unittest.main()
