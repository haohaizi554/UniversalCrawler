"""ucrawl CLI 入口：供 AI/LLM 直接调用本 skill。

AI/LLM 调用方式：
1. 找到 SKILL.md 后，按其中的"方式 1：CLI"执行命令
2. 或直接 exec() 此脚本：`python ucrawl_skill.py --source douyin --keyword "测试"`
"""

import os
import sys

# 把项目根目录加入 sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from cli.main import main

if __name__ == "__main__":
    sys.exit(main())
