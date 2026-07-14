from __future__ import annotations

import builtins
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GitHubActionsWorkflowTests(unittest.TestCase):
    def test_python_workflow_has_layered_quality_gates(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read", source)
        self.assertIn("concurrency:", source)
        self.assertIn("cancel-in-progress: true", source)
        self.assertIn("quality:", source)
        self.assertIn("compatibility:", source)
        self.assertIn("security:", source)
        self.assertIn("core-tests:", source)
        self.assertIn("browser-tests:", source)
        self.assertIn("required-check:", source)
        self.assertIn("runs-on: ubuntu-latest", source)
        self.assertIn("runs-on: windows-latest", source)
        self.assertGreaterEqual(source.count("timeout-minutes:"), 4)
        self.assertIn("uses: actions/checkout@v6", source)
        self.assertIn("uses: actions/setup-python@v6", source)
        self.assertIn("cache: pip", source)
        self.assertIn("uses: actions/upload-artifact@v7", source)
        self.assertIn("python -m ruff check", source)
        self.assertIn("python -m mypy", source)
        self.assertIn("python -m bandit", source)
        self.assertIn("python -m pip_audit --local", source)
        self.assertIn("python -m build", source)
        self.assertIn("tests/architecture", source)
        self.assertIn("--ignore=tests/test_web_browser.py", source)
        self.assertIn("tests/test_web_browser.py", source)
        self.assertIn("--junitxml=", source)
        self.assertIn("python -X faulthandler -m pytest", source)
        self.assertNotIn("python -m unittest discover", source)
        self.assertNotIn("sudo apt-get", source)
        self.assertNotIn("xvfb-run", source)
        self.assertIn("QT_QPA_PLATFORM: offscreen", source)
        self.assertIn('PYTHONFAULTHANDLER: "1"', source)
        self.assertIn("python -m playwright install chromium", source)
        self.assertIn("python -m coverage run", source)
        self.assertIn("python -m coverage report --fail-under=", source)

    def test_python_workflow_covers_declared_python_compatibility(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        compatibility_block = source.split("  compatibility:", 1)[1].split("  security:", 1)[0]

        self.assertIn("strategy:", compatibility_block)
        self.assertIn("fail-fast: false", compatibility_block)
        self.assertIn('python-version: ["3.10", "3.11", "3.12", "3.13"]', compatibility_block)
        self.assertIn("python -m build", compatibility_block)
        self.assertIn("pip install --no-deps --force-reinstall", compatibility_block)
        self.assertIn("importlib.metadata", compatibility_block)
        self.assertIn("entry.test_entry --self-check", compatibility_block)

    def test_security_scanner_covers_protocol_signing_code(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        quality_block = source.split("  quality:", 1)[1].split("  compatibility:", 1)[0]

        self.assertNotIn("app/core/lib/douyin/encrypt", quality_block)

    def test_browser_job_caches_playwright_runtime(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        browser_block = source.split("  browser-tests:", 1)[1].split("  required-check:", 1)[0]

        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", browser_block)
        self.assertIn("uses: actions/cache@v5", browser_block)
        self.assertIn("playwright-${{ runner.os }}-chromium-", browser_block)

    def test_performance_benchmarks_run_without_coverage_instrumentation(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        core_block = source.split("  core-tests:", 1)[1].split("  browser-tests:", 1)[0]

        coverage_line = next(
            line for line in core_block.splitlines() if "coverage run" in line
        )
        self.assertIn("--ignore=tests/test_performance_benchmarks.py", coverage_line)
        self.assertIn(
            "python -X faulthandler -m pytest tests/test_performance_benchmarks.py -q",
            core_block,
        )

    def test_full_suite_is_visible_and_partitioned_without_coverage_gaps(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        core_block = source.split("  core-tests:", 1)[1].split("  browser-tests:", 1)[0]
        browser_block = source.split("  browser-tests:", 1)[1].split("  required-check:", 1)[0]
        coverage_line = next(
            line for line in core_block.splitlines() if "coverage run" in line
        )

        self.assertIn(
            "name: Full test suite / Core + performance (Windows, Python 3.13)",
            core_block,
        )
        self.assertIn("name: Full test suite / Browser (Chromium)", browser_block)
        self.assertIn("-m pytest tests -q", coverage_line)
        self.assertIn("--ignore=tests/test_web_browser.py", coverage_line)
        self.assertIn("--ignore=tests/test_performance_benchmarks.py", coverage_line)
        self.assertIn("pytest tests/test_performance_benchmarks.py", core_block)
        self.assertIn("pytest tests/test_web_browser.py", browser_block)

    def test_required_check_aggregates_all_blocking_jobs(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        required_block = source.split("  required-check:", 1)[1]

        for job in ("quality", "compatibility", "security", "core-tests", "browser-tests"):
            self.assertIn(f"      - {job}", required_block)

    def test_linux_quality_job_does_not_install_runtime_requirements(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")
        quality_block = source.split("  quality:", 1)[1].split("  compatibility:", 1)[0]

        self.assertIn("requirements-dev.txt", quality_block)
        self.assertNotIn("requirements.txt", quality_block.replace("requirements-dev.txt", ""))
        self.assertNotIn("playwright install", quality_block)

    def test_quality_fixtures_do_not_import_qt_workers_without_qt_runtime(self) -> None:
        from tests import conftest

        real_import = builtins.__import__

        def reject_qt_worker_imports(name, *args, **kwargs):
            if name.startswith(("app.services.frontend_state_service", "app.ui.viewmodels")):
                self.fail(f"quality-only test imported Qt worker module: {name}")
            return real_import(name, *args, **kwargs)

        with (
            mock.patch.object(conftest, "_qt_runtime_available", return_value=False),
            mock.patch("builtins.__import__", side_effect=reject_qt_worker_imports),
        ):
            self.assertEqual(conftest._background_worker_cleanup_targets(), ())

    def test_docker_workflow_uses_buildx_cache_and_bounded_execution(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "docker-build.yml"
        source = workflow.read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read", source)
        self.assertIn("concurrency:", source)
        self.assertIn("cancel-in-progress: true", source)
        self.assertIn("timeout-minutes:", source)
        self.assertIn("uses: actions/checkout@v6", source)
        self.assertIn("uses: docker/setup-buildx-action@v4", source)
        self.assertIn("uses: docker/build-push-action@v7", source)
        self.assertIn("cache-from: type=gha", source)
        self.assertIn("cache-to: type=gha,mode=max", source)

    def test_runtime_requirements_exclude_optional_report_and_fedora_tools(self) -> None:
        requirements = PROJECT_ROOT / "requirements.txt"
        lines = {
            line.strip().split("==", 1)[0].split("~=", 1)[0].split(">=", 1)[0].lower()
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        self.assertNotIn("the-new-hotness", lines)
        self.assertNotIn("beautifulreport", lines)
        self.assertIn("curl-cffi", lines)
        self.assertIn("pycryptodome", lines)
        self.assertIn("uvicorn", lines)
        self.assertIn("yt-dlp", lines)


if __name__ == "__main__":
    unittest.main()
