"""源码开发态的发布构建工具入口。"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    """启动发布构建面板；冻结安装包不开放此内部工程入口。"""

    if bool(getattr(sys, "frozen", False)):
        stream = getattr(sys, "stderr", None)
        if stream is not None:
            stream.write("error: 发布构建工具仅在源码开发态可用\n")
        return 2
    if argv:
        stream = getattr(sys, "stderr", None)
        if stream is not None:
            stream.write("error: 发布构建工具不接受额外命令行参数\n")
        return 2

    project_root = Path(__file__).resolve().parents[1]
    packaging_root = project_root / "packaging"
    packaging_path = str(packaging_root)
    if packaging_path not in sys.path:
        sys.path.insert(0, packaging_path)

    from release_tool.panel import launch_release_builder_panel

    return int(launch_release_builder_panel())


__all__ = ["main"]
