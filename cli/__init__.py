"""UCrawl CLI / SDK 入口。

提供 4 种调用方式：

1. **命令行工具** (安装后可用 `ucrawl` 命令)
   ```bash
   ucrawl search --source douyin "测试"
   ucrawl douyin search "测试" --max-items 20
   ```

2. **Python SDK**（导入后即可用）
   ```python
   from ucrawl import UcrawlSDK
   sdk = UcrawlSDK(save_dir="downloads")
   result = sdk.search(source="douyin", keyword="测试")
   ```

3. **REST API 注入**（在 Web 服务启动时执行）
   ```bash
   ucrawl-web --script my_automation.py
   ```

4. **AI Skill 封装** (在 `cli/skill/SKILL.md` 中定义)
   让 Claude / LLM 可直接调用本工具。
"""

import sys

import app.ui.gui_selection_strategy as _gui_selection_module
from shared import cli_runner_runtime as _runner_module
from shared import interactive_selection as _interactive_module
from shared import pipe_selection as _pipe_module
from shared import runtime_options as _defaults_module
from shared import sdk_runtime as _sdk_module
from shared import selection_runtime as _selection_base_module

from shared.sdk_runtime import (
    UcrawlSDK,
    search,
    list_platforms,
    scan_directory,
    download_video,
)
from shared.cli_runner_runtime import CLIRunner
from shared.selection_base import SelectionStrategy, is_selection_strategy
from shared.selection_runtime import (
    RuleSelection,
    AutoSelection,
)
from shared.interactive_selection import InteractiveTTYSelection
from shared.pipe_selection import PipeOutput, PipeSelection
from app.ui.gui_selection_strategy import GUISelection

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

__version__ = "3.6.17"

# 这些别名只在公开包边界保留历史导入路径，并统一指向 shared 中的规范实现；
# 内部代码直接导入 shared 模块，避免继续维护重复适配文件。
_PUBLIC_MODULE_ALIASES = {
    "defaults": _defaults_module,
    "gui_selection": _gui_selection_module,
    "interactive": _interactive_module,
    "pipe": _pipe_module,
    "runner": _runner_module,
    "sdk": _sdk_module,
    "selection": sys.modules[__name__],
    "selection_base": _selection_base_module,
}
for _module_name, _module in _PUBLIC_MODULE_ALIASES.items():
    sys.modules.setdefault(f"{__name__}.{_module_name}", _module)
    setattr(sys.modules[__name__], _module_name, _module)
