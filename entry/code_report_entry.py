"""项目代码量统计报告的启动模式薄入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


def _has_option(argv: Sequence[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in argv)


def main(argv: Sequence[str] | None = None) -> int:
    """统计当前源码仓库，生成报告后交给默认浏览器打开。"""
    from count_project import main as run_report

    project_root = Path(__file__).resolve().parents[1]
    report_path = project_root / "code_report.html"
    forwarded = list(argv) if argv is not None else []

    if not _has_option(forwarded, "--root"):
        forwarded.extend(("--root", str(project_root)))
    if not _has_option(forwarded, "--html"):
        forwarded.extend(("--html", str(report_path)))
    if "--open" not in forwarded:
        forwarded.append("--open")

    return run_report(forwarded)
