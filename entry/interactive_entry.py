"""UCrawl 交互式引导入口（薄适配层）。

行业对齐：
- 在 `pyproject.toml` 的 `[project.scripts]` 中注册为 `ucrawl-i` 命令
- 透传到 `cli.commands.interactive.handle_interactive_command`

调用链：
    ucrawl-i (console_script) -> entry.interactive_entry:main() -> cli.commands.interactive
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

def main(argv: list[str] | None = None) -> int:
    """交互式引导入口。

    该模式不需要任何参数，会逐步引导用户输入：
    1. 选择平台
    2. 输入关键词
    3. 配置平台参数
    4. 选择保存目录
    5. 确认后执行

    同时支持与 search 命令对齐的参数（--run-timeout/--quiet/--config/二次选择等）。
    """
    from cli.commands.interactive import add_interactive_arguments, handle_interactive_command

    import argparse
    if argv is None:
        argv = sys.argv[1:]

    # 与 cli/commands/interactive.py 的 add_interactive_arguments 对齐：
    # 使用统一的参数定义，确保 ucrawl-i 命令支持所有 interactive 参数
    parser = argparse.ArgumentParser(prog="ucrawl-i", add_help=True)
    add_interactive_arguments(parser)
    args = parser.parse_args(argv)
    return handle_interactive_command(args)

if __name__ == "__main__":
    sys.exit(main())
