r"""最直接测试：模拟 dispatcher 完整流程（用户输入 5）。

注意：此脚本仅用于手动复现 bug，**不会**在 import 或 pytest 自动发现时执行。
所有可执行代码均在 `if __name__ == "__main__":` 守卫内。
"""
import os
import sys
import traceback
import io
from pathlib import Path


def main():
    """手动复现入口。"""
    import builtins

    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

    print("=" * 70)
    print("直接复现: dispatcher.prompt_mode_menu() → run_test() → test_entry.main()")
    print("=" * 70)

    # 替换 stdin 为 StringIO("5\n")
    real_stdin = sys.stdin
    real_stdout = sys.stdout

    # 模拟 PowerShell 终端：让 isatty() 返回 True
    real_isatty = sys.stdin.isatty
    def fake_isatty():
        return True
    sys.stdin.isatty = fake_isatty
    sys.stdout.isatty = fake_isatty

    # 替换 input() 为读 StringIO
    fake_input_buffer = io.StringIO("5\n")
    real_input = builtins.input
    def fake_input(prompt=""):
        if prompt:
            sys.stdout.write(prompt)
        return fake_input_buffer.readline().rstrip("\n")
    builtins.input = fake_input

    # 替换 sys.exit
    real_exit = sys.exit
    def fake_exit(code=0):
        raise SystemExit(code)
    sys.exit = fake_exit

    try:
        # 跑 dispatcher
        print("[Step 1] 调 entry.run() — 模拟 'python main.py'")
        from entry import dispatcher
        rc = dispatcher.run([])
        print(f"\n[Step 1 完成] entry.run() 返回 {rc}")
    except SystemExit as e:
        print(f"\n[Step 1] SystemExit: code={e.code}")
    except Exception as e:
        print(f"\n[Step 1 异常] {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        sys.stdin = real_stdin
        sys.stdout = real_stdout
        sys.stdin.isatty = real_isatty
        builtins.input = real_input
        sys.exit = real_exit


if __name__ == "__main__":
    main()
