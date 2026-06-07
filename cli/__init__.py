"""UCrawl CLI / SDK 入口。

提供 4 种调用方式：

1. **命令行工具** (安装后可用 `ucrawl` 命令)
   ```bash
   ucrawl search --source douyin --keyword "测试"
   ucrawl douyin search "测试" --max-items 20
   ```

2. **Python SDK** (import 即可用)
   ```python
   from ucrawl import UcrawlSDK
   sdk = UcrawlSDK(save_dir="downloads")
   result = sdk.search(source="douyin", keyword="测试")
   ```

3. **REST API 注入** (在 web 服务启动时执行)
   ```bash
   python web_main.py --script my_automation.py
   ```

4. **AI Skill 封装** (在 `cli/skill/SKILL.md` 中定义)
   让 Claude / LLM 可直接调用本工具。
"""

from cli.sdk import (
    UcrawlSDK,
    search,
    list_platforms,
    scan_directory,
    download_video,
)
from cli.runner import CLIRunner
from cli.selection import (
    SelectionStrategy,
    RuleSelection,
    InteractiveTTYSelection,
    GUISelection,
    PipeSelection,
    PipeOutput,
    AutoSelection,
    is_selection_strategy,
)

__all__ = [
    # SDK 类
    "UcrawlSDK",
    # 函数式 API
    "search",
    "list_platforms",
    "scan_directory",
    "download_video",
    # 核心执行器
    "CLIRunner",
    # 选择策略
    "SelectionStrategy",
    "RuleSelection",
    "InteractiveTTYSelection",
    "GUISelection",
    "PipeSelection",
    "PipeOutput",
    "AutoSelection",
    "is_selection_strategy",
]

__version__ = "1.0.0"
