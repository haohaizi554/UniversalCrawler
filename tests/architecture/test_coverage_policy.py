"""覆盖率策略必须在本地与 CI 使用同一份可审计配置。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.toml_compat import loads


pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _coverage_config() -> dict:
    pyproject = loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["coverage"]


def test_coverage_run_policy_tracks_core_production_packages_and_branches() -> None:
    run = _coverage_config()["run"]

    assert run["branch"] is True
    assert set(run["source"]) == {"app", "cli", "entry", "shared"}
    assert "app/core/lib/*" in run["omit"]


def test_coverage_report_policy_is_visible_and_prevents_regression() -> None:
    report = _coverage_config()["report"]

    assert report["show_missing"] is True
    assert report["precision"] >= 1
    assert report["fail_under"] >= 75


def test_ci_uses_the_same_coverage_floor() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml").read_text(
        encoding="utf-8"
    )

    assert _coverage_config()["report"]["fail_under"] >= 75
    assert "python -m coverage report" in workflow
    assert "coverage report --fail-under" not in workflow


def test_coverage_policy_imports_when_stdlib_tomllib_is_unavailable() -> None:
    script = r"""
import builtins
import runpy
import sys

try:
    import tomli as backend
except ModuleNotFoundError:
    import tomllib as backend

import pytest  # Load pytest before simulating Python 3.10.

sys.modules["tomli"] = backend
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "tomllib":
        raise ModuleNotFoundError("simulated Python 3.10")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
runpy.run_path(sys.argv[1], run_name="coverage_policy_compat_probe")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, __file__],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
