"""ucrawl CLI 入口：供 AI/LLM 直接调用本 skill。

AI/LLM 调用方式：
1. 找到 SKILL.md 后，按其中的"方式 1：CLI"执行命令
2. 或直接 exec() 此脚本：`python ucrawl_skill.py --source douyin --keyword "测试"`
"""

import sys
from pathlib import Path

# 把项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root = str(PROJECT_ROOT)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from cli.main import main  # noqa: E402 - sys.path bootstrap must precede the import.

if __name__ == "__main__":
    sys.exit(main())
