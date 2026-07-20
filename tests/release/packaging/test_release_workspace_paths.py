from __future__ import annotations

import sys
from pathlib import Path

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))

from release_tool.workspace_paths import (
    default_release_notes_directory,
    find_release_notes_for_version,
    installer_output_directory,
)


def test_release_notes_match_existing_plural_project_directory(
    tmp_path: Path,
) -> None:
    notes_directory = tmp_path / "docs" / "releases"
    notes_directory.mkdir(parents=True)
    expected = notes_directory / "v3.6.21.md"
    expected.write_text("# v3.6.21", encoding="utf-8")

    assert default_release_notes_directory(tmp_path) == notes_directory
    assert find_release_notes_for_version(tmp_path, "3.6.21") == expected.resolve()
    assert find_release_notes_for_version(tmp_path, "v3.6.21") == expected.resolve()


def test_release_notes_match_uses_complete_version_boundaries(
    tmp_path: Path,
) -> None:
    notes_directory = tmp_path / "docs" / "release"
    notes_directory.mkdir(parents=True)
    wrong_prefix = notes_directory / "v3.6.210.md"
    expected = notes_directory / "release-v3.6.21-notes.md"
    wrong_prefix.write_text("# v3.6.210", encoding="utf-8")
    expected.write_text("# v3.6.21", encoding="utf-8")

    assert find_release_notes_for_version(tmp_path, "3.6.21") == expected.resolve()


def test_release_notes_match_prefers_canonical_exact_filename(
    tmp_path: Path,
) -> None:
    notes_directory = tmp_path / "docs" / "release"
    notes_directory.mkdir(parents=True)
    verbose = notes_directory / "release-v3.6.21-notes.md"
    canonical = notes_directory / "v3.6.21.md"
    verbose.write_text("# verbose", encoding="utf-8")
    canonical.write_text("# canonical", encoding="utf-8")

    assert find_release_notes_for_version(tmp_path, "3.6.21") == canonical.resolve()


def test_release_workspace_paths_return_empty_match_and_installer_directory(
    tmp_path: Path,
) -> None:
    assert find_release_notes_for_version(tmp_path, "3.6.21") is None
    assert find_release_notes_for_version(tmp_path, "not-a-version") is None
    assert installer_output_directory(tmp_path) == (
        tmp_path.resolve() / "dist" / "installer"
    )
