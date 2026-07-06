from __future__ import annotations

import unittest
import warnings
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _line_count(path: Path) -> int:
    return sum(1 for _line in path.open("r", encoding="utf-8-sig"))


def _oversized_files(root: str, limit: int) -> list[tuple[str, int]]:
    root_path = PROJECT_ROOT / root
    oversized: list[tuple[str, int]] = []
    for path in sorted(root_path.rglob("*.py")):
        count = _line_count(path)
        if count > limit:
            oversized.append((path.relative_to(PROJECT_ROOT).as_posix(), count))
    return oversized


def _warn_oversized(scope: str, files: list[tuple[str, int]], limit: int) -> None:
    if not files:
        return
    formatted = ", ".join(f"{path}={count}" for path, count in files)
    warnings.warn(
        f"{scope} files over {limit} lines: {formatted}",
        UserWarning,
        stacklevel=2,
    )


class FileSizeLimitArchitectureTests(unittest.TestCase):
    def test_app_files_report_files_over_1500_lines_without_failing(self) -> None:
        oversized = _oversized_files("app", 1500)

        _warn_oversized("app", oversized, 1500)

        self.assertIsInstance(oversized, list)

    def test_ui_files_report_files_over_800_lines_without_failing(self) -> None:
        oversized = _oversized_files("app/ui", 800)

        _warn_oversized("app/ui", oversized, 800)

        self.assertIsInstance(oversized, list)


if __name__ == "__main__":
    unittest.main()
