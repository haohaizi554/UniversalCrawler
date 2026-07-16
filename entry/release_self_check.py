"""公开命令 ``ucrawl-test`` 使用的已安装发行版诊断。"""

from __future__ import annotations

import csv
import importlib
import importlib.metadata
from pathlib import PurePosixPath


def _distribution_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    try:
        distribution = importlib.metadata.distribution("ucrawl")
    except importlib.metadata.PackageNotFoundError as exc:
        return [("distribution metadata", False, str(exc))]

    version = distribution.version
    checks.append(("distribution metadata", bool(version), version or "missing version"))

    entry_points = {entry.name for entry in distribution.entry_points}
    required_entries = {
        "ucrawl",
        "ucrawl-auto",
        "ucrawl-gui",
        "ucrawl-test",
        "ucrawl-test-gui",
    }
    missing_entries = sorted(required_entries - entry_points)
    checks.append(
        (
            "public commands",
            not missing_entries,
            "ok" if not missing_entries else f"missing: {', '.join(missing_entries)}",
        )
    )

    packaged_files = {str(path).replace("\\", "/") for path in (distribution.files or ())}
    read_distribution_text = getattr(distribution, "read_text", None)
    if callable(read_distribution_text):
        record_text = read_distribution_text("RECORD") or ""
        packaged_files.update(
            row[0].replace("\\", "/")
            for row in csv.reader(record_text.splitlines())
            if row
        )
    checks.append(
        (
            "web assets",
            "app/web/static/index.html" in packaged_files,
            "app/web/static/index.html",
        )
    )
    missing_report_assets = []
    if "count_project.py" not in packaged_files:
        missing_report_assets.append("count_project.py")
    if not any(PurePosixPath(path).name == "analytics.ico" for path in packaged_files):
        missing_report_assets.append("analytics.ico")
    checks.append(
        (
            "report assets",
            not missing_report_assets,
            "ok" if not missing_report_assets else f"missing: {', '.join(missing_report_assets)}",
        )
    )
    tests_leaked = any(path == "tests" or path.startswith("tests/") for path in packaged_files)
    checks.append(("release contents", not tests_leaked, "tests excluded" if not tests_leaked else "tests leaked"))
    return checks


def _module_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    for module_name in (
        "shared.runtime_adapters",
        "shared.runtime_options",
        "shared.selection_base",
        "shared.settings_metadata",
        "entry.code_report_entry",
        "entry.dispatcher",
        "entry.test_entry",
        "count_project",
    ):
        try:
            importlib.import_module(module_name)
        except (ImportError, RuntimeError, OSError) as exc:
            checks.append((f"import {module_name}", False, str(exc)))
        else:
            checks.append((f"import {module_name}", True, "ok"))
    return checks


def run(*, verbose: bool = False, list_only: bool = False) -> int:
    """执行有界自检，确保缺少源码测试时仍能诊断已安装发行版。"""
    if list_only:
        print("installed  Installed release self-check")
        print("Full development suites are available from a source checkout.")
        return 0

    checks = [*_distribution_checks(), *_module_checks()]
    failed = [check for check in checks if not check[1]]
    print("UCrawl installed release self-check")
    for name, passed, detail in checks:
        if verbose or not passed:
            print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run(verbose=True))
