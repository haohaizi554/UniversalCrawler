"""UCrawl CLI 入口（薄适配层）。

行业对齐：
- 在 `pyproject.toml` 的 `[project.scripts]` 中注册为 `ucrawl` 命令
- 不写任何业务逻辑，只做参数透传到 `cli.main:main`

调用链：
    ucrawl (console_script) -> entry.cli_entry:main() -> cli.main:main()
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

def main(argv: list[str] | None = None) -> int:
    """CLI 入口：透传到 cli.main。

    Args:
        argv: 命令行参数（None=使用 sys.argv[1:]）

    Returns:
        退出码
    """
    from cli.main import main as _cli_main
    return _cli_main(argv)

if __name__ == "__main__":
    sys.exit(main())
