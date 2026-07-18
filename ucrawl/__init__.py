"""UCrawl 的 Python SDK 公共入口。

推荐用法:
    from ucrawl import UcrawlSDK, search, list_platforms
    from ucrawl import RuleSelection, PipeSelection
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
from shared.version import __version__

__all__ = [
    "UcrawlSDK",
    "CLIRunner",
    "search",
    "list_platforms",
    "scan_directory",
    "download_video",
    "RuleSelection",
    "InteractiveTTYSelection",
    "PipeSelection",
    "PipeOutput",
    "AutoSelection",
    "SelectionStrategy",
    "is_selection_strategy",
]
