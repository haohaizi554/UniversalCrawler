from __future__ import annotations

import importlib
import os
import sys
import tomllib
from pathlib import Path

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


def _versioning_module():
    try:
        return importlib.import_module("release_tool.versioning")
    except ModuleNotFoundError as error:
        if error.name in {"release_tool", "release_tool.versioning"}:
            return None
        raise


def _require_versioning_module():
    module = _versioning_module()
    assert module is not None, "release_tool.versioning is missing"
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_version_fixture(tmp_path: Path, *, current: str) -> Path:
    root = tmp_path / "project"
    _write(root / "shared/version.py", f'__version__ = "{current}"\n')
    _write(
        root / "README.md",
        "\n".join(
            (
                f'<img alt="Version" src="https://img.shields.io/badge/Version-v{current}-7C3AED" />',
                f"当前版本号为 **v{current}**。",
                "",
            )
        ),
    )
    _write(
        root / "README_EN.md",
        "\n".join(
            (
                f'<img alt="Version" src="https://img.shields.io/badge/Version-v{current}-7C3AED" />',
                f"The current project version is **v{current}**.",
                "",
            )
        ),
    )
    _write(root / "docs/README.md", f"当前文档基线对应源码版本 `{current}`。\n")
    _write(root / "cli/skill/SKILL.md", f"---\nversion: {current}\n---\n")
    return root


def snapshot_allowlisted_files(root: Path) -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in (
            root / "shared/version.py",
            root / "README.md",
            root / "README_EN.md",
            root / "docs/README.md",
            root / "cli/skill/SKILL.md",
        )
    }


def test_pyproject_uses_shared_version_as_dynamic_metadata():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "shared.version.__version__"
    }


def test_project_meta_imports_the_canonical_version():
    source = (PROJECT_ROOT / "packaging/project_meta.py").read_text(encoding="utf-8")

    assert "from shared.version import __version__" in source
    assert "PACKAGE_VERSION = __version__" in source
    assert '_project_field("version")' not in source


def test_inno_setup_requires_an_injected_app_version():
    source = (PROJECT_ROOT / "packaging/installer.iss").read_text(encoding="utf-8")

    assert "#ifndef AppVersion" in source
    assert "#error AppVersion must be supplied by build_installer.py" in source
    assert '#define AppVersion "3.' not in source


def test_normalize_version_accepts_plain_or_prefixed_semver():
    versioning = _require_versioning_module()

    assert versioning.normalize_version("  v3.6.22 ") == "3.6.22"


@pytest.mark.parametrize("value", ("3.6", "03.6.22", "3.6.22rc1", ""))
def test_normalize_version_rejects_non_semver_values(value):
    versioning = _require_versioning_module()

    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        versioning.normalize_version(value)


def test_read_project_version_uses_the_canonical_module(tmp_path):
    versioning = _require_versioning_module()
    root = make_version_fixture(tmp_path, current="3.6.21")

    assert versioning.read_project_version(root) == "3.6.21"


def test_version_update_changes_only_the_allowlisted_current_version_projections(tmp_path):
    versioning = _require_versioning_module()
    root = make_version_fixture(tmp_path, current="3.6.21")
    historical = root / "docs/releases/v3.6.14.md"
    _write(historical, "v3.6.14")

    result = versioning.apply_version_update(versioning.plan_version_update("3.6.22", root))

    assert result.previous_version == "3.6.21"
    assert result.target_version == "3.6.22"
    assert historical.read_text(encoding="utf-8") == "v3.6.14"
    assert versioning.read_project_version(root) == "3.6.22"
    assert set(result.changed_files) == {
        root / "shared/version.py",
        root / "README.md",
        root / "README_EN.md",
        root / "docs/README.md",
        root / "cli/skill/SKILL.md",
    }


def test_version_update_rejects_a_projection_without_exactly_one_current_match(tmp_path):
    versioning = _require_versioning_module()
    root = make_version_fixture(tmp_path, current="3.6.21")
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace("当前版本号", "版本号"),
        encoding="utf-8",
    )

    with pytest.raises(versioning.VersionUpdateError, match="exactly one"):
        versioning.plan_version_update("3.6.22", root)


def test_version_update_rejects_a_projection_with_multiple_current_matches(tmp_path):
    versioning = _require_versioning_module()
    root = make_version_fixture(tmp_path, current="3.6.21")
    docs_index = root / "docs/README.md"
    docs_index.write_text(
        docs_index.read_text(encoding="utf-8")
        + "当前文档基线对应源码版本 `3.6.21`。\n",
        encoding="utf-8",
    )

    with pytest.raises(versioning.VersionUpdateError, match="exactly one"):
        versioning.plan_version_update("3.6.22", root)


def test_verify_version_contract_reports_projection_drift(tmp_path):
    versioning = _require_versioning_module()
    root = make_version_fixture(tmp_path, current="3.6.21")
    (root / "docs/README.md").write_text("当前文档基线对应源码版本 `3.6.20`。\n", encoding="utf-8")

    issues = versioning.verify_version_contract(root, "3.6.21")

    assert issues
    assert any("docs/README.md" in issue for issue in issues)


def test_version_update_rolls_back_every_file_when_replace_fails(tmp_path, monkeypatch):
    versioning = _require_versioning_module()
    root = make_version_fixture(tmp_path, current="3.6.21")
    before = snapshot_allowlisted_files(root)
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)

    with pytest.raises(versioning.VersionUpdateError, match="rolled back"):
        versioning.apply_version_update(versioning.plan_version_update("3.6.22", root))

    assert snapshot_allowlisted_files(root) == before
