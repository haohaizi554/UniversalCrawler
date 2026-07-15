"""ucrawl 顶层包：从 cli 重新导出，保持向后兼容。

推荐用法:
    from ucrawl import UcrawlSDK, search, list_platforms
    from ucrawl import RuleSelection, PipeSelection

旧用法 (仍然支持):
    from cli import UcrawlSDK
"""

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

__version__ = "3.6.21"

__all__ = [
    "UcrawlSDK",
    "CLIRunner",
    "search",
    "list_platforms",
    "scan_directory",
    "download_video",
    "RuleSelection",
    "InteractiveTTYSelection",
    "GUISelection",
    "PipeSelection",
    "PipeOutput",
    "AutoSelection",
    "SelectionStrategy",
    "is_selection_strategy",
]
