"""项目代码量统计报告的启动模式薄入口。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
)


def _has_option(argv: Sequence[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in argv)


def _option_value(argv: Sequence[str], option: str) -> str | None:
    for index, argument in enumerate(argv):
        if argument.startswith(f"{option}="):
            return argument.split("=", 1)[1]
        if argument == option and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _nearest_project_root(start: Path) -> Path | None:
    candidate = Path(start).expanduser().resolve()
    for directory in (candidate, *candidate.parents):
        if any((directory / marker).exists() for marker in PROJECT_MARKERS):
            return directory
    return None


def _discover_default_project_root() -> Path | None:
    """源码态优先当前仓库；安装/冻结态不把 site-packages 当成待统计项目。"""

    for candidate in (Path.cwd(), Path(__file__).resolve().parents[1]):
        if project_root := _nearest_project_root(candidate):
            return project_root
    return None


def _select_project_root() -> Path | None:
    """安装版没有显式 root 时让用户选择项目，避免扫描程序安装目录。"""

    try:
        from PyQt6.QtWidgets import QApplication, QFileDialog
    except ImportError:
        if not sys.stdin or not sys.stdin.isatty():
            return None
        selected = input("请输入要统计的项目目录（留空取消）：").strip()
        return Path(selected).expanduser().resolve() if selected else None

    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication([])
    selected = QFileDialog.getExistingDirectory(
        None,
        "选择要生成代码量报告的项目目录",
        str(Path.home()),
    )
    if owns_application:
        application.quit()
    return Path(selected).resolve() if selected else None


def main(argv: Sequence[str] | None = None) -> int:
    """统计显式或用户选择的源码项目，生成报告后交给默认浏览器打开。"""
    from count_project import main as run_report

    forwarded = list(argv) if argv is not None else []
    explicit_root = _option_value(forwarded, "--root")
    project_root = (
        Path(explicit_root).expanduser().resolve()
        if explicit_root
        else _discover_default_project_root() or _select_project_root()
    )
    if project_root is None:
        print("未选择项目目录，代码量报告已取消。", file=sys.stderr)
        return 2
    report_path = project_root / "code_report.html"

    if not _has_option(forwarded, "--root"):
        forwarded.extend(("--root", str(project_root)))
    if not _has_option(forwarded, "--html"):
        forwarded.extend(("--html", str(report_path)))
    if "--open" not in forwarded:
        forwarded.append("--open")

    return run_report(forwarded)
