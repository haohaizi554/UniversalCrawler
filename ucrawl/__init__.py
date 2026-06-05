"""ucrawl 顶层包：从 cli re-export，保持向后兼容。

推荐用法:
    from ucrawl import UcrawlSDK, search, list_platforms
    from ucrawl import RuleSelection, PipeSelection

旧用法 (仍然支持):
    from cli import UcrawlSDK
"""

from cli import (
    UcrawlSDK,
    CLIRunner,
    search,
    list_platforms,
    scan_directory,
    RuleSelection,
    InteractiveSelection,
    PipeSelection,
    AutoSelection,
    SelectionStrategy,
)

__version__ = "1.0.0"

__all__ = [
    "UcrawlSDK",
    "CLIRunner",
    "search",
    "list_platforms",
    "scan_directory",
    "RuleSelection",
    "InteractiveSelection",
    "PipeSelection",
    "AutoSelection",
    "SelectionStrategy",
]
