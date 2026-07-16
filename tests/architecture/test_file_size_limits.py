from __future__ import annotations

import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP_LIMIT = 1500
DEFAULT_UI_LIMIT = 800

# These are migration ceilings, not exemptions. A legacy module may shrink below
# its ceiling, but it must never grow past it while it is being decomposed.
LEGACY_FILE_LIMITS = {
    "app/core/downloaders/m3u8.py": 2050,
    "app/core/lib/douyin/extract/extractor.py": 1700,
    "app/services/frontend_state_service.py": 2700,
    "app/spiders/bilibili/spider.py": 1900,
    "app/ui/components/media_preview_panel.py": 1500,
    "app/ui/layout/window_chrome_controller.py": 900,
    "app/ui/main_window.py": 3000,
    "app/ui/pages/active_downloads_page.py": 1300,
    "app/ui/pages/log_center_page.py": 1700,
    "app/ui/pages/settings_page.py": 1650,
    "app/ui/styles/themes.py": 1400,
}


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig") as source:
        return sum(1 for _line in source)


def _budget_for(relative_path: str) -> int:
    legacy_limit = LEGACY_FILE_LIMITS.get(relative_path)
    if legacy_limit is not None:
        return legacy_limit
    if relative_path.startswith("app/ui/"):
        return DEFAULT_UI_LIMIT
    return DEFAULT_APP_LIMIT


def _budget_violations() -> list[tuple[str, int, int]]:
    violations: list[tuple[str, int, int]] = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        count = _line_count(path)
        limit = _budget_for(relative_path)
        if count > limit:
            violations.append((relative_path, count, limit))
    return violations


class FileSizeLimitArchitectureTests(unittest.TestCase):
    def test_production_files_stay_within_enforced_budgets(self) -> None:
        violations = _budget_violations()
        formatted = "\n".join(
            f"  {path}: {count} lines (budget {limit})"
            for path, count, limit in violations
        )

        self.assertEqual(
            violations,
            [],
            "Production file size budgets were exceeded:\n" + formatted,
        )

    def test_new_ui_files_use_the_stricter_budget(self) -> None:
        self.assertEqual(_budget_for("app/ui/pages/new_page.py"), DEFAULT_UI_LIMIT)

    def test_new_non_ui_files_use_the_app_budget(self) -> None:
        self.assertEqual(_budget_for("app/services/new_service.py"), DEFAULT_APP_LIMIT)


if __name__ == "__main__":
    unittest.main()
