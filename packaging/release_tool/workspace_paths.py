"""发布构建工具使用的工作区路径与发布说明匹配规则。"""

from __future__ import annotations

import re
from pathlib import Path

from .versioning import normalize_version


_RELEASE_NOTES_DIRECTORY_NAMES = ("release", "releases")
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})


def release_notes_directories(project_root: Path) -> tuple[Path, ...]:
    """返回可用的发布说明目录，并兼容单复数目录名。"""

    docs_directory = Path(project_root).resolve() / "docs"
    candidates = tuple(
        docs_directory / name for name in _RELEASE_NOTES_DIRECTORY_NAMES
    )
    existing = tuple(path for path in candidates if path.is_dir())
    return existing or (candidates[0],)


def default_release_notes_directory(project_root: Path) -> Path:
    """返回文件选择器应默认打开的发布说明目录。"""

    return release_notes_directories(project_root)[0]


def installer_output_directory(project_root: Path) -> Path:
    """返回安装器构建脚本写入最终安装包的目录。"""

    return Path(project_root).resolve() / "dist" / "installer"


def find_release_notes_for_version(
    project_root: Path,
    version: str,
) -> Path | None:
    """按文件名中的完整版本号查找最合适的 Markdown 发布说明。"""

    try:
        normalized_version = normalize_version(version)
    except ValueError:
        return None

    version_pattern = re.compile(
        rf"(?<![0-9])v?{re.escape(normalized_version)}(?![0-9])",
        re.IGNORECASE,
    )
    matches: list[tuple[tuple[int, int, int, str], Path]] = []
    for directory_index, directory in enumerate(
        release_notes_directories(project_root)
    ):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in _MARKDOWN_SUFFIXES:
                continue
            stem = path.stem.casefold()
            if not version_pattern.search(stem):
                continue
            exact_rank = _release_notes_exact_rank(stem, normalized_version)
            relative_name = path.relative_to(directory).as_posix().casefold()
            rank = (
                exact_rank,
                directory_index,
                len(relative_name),
                relative_name,
            )
            matches.append((rank, path.resolve()))

    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def _release_notes_exact_rank(stem: str, normalized_version: str) -> int:
    canonical_stem = f"v{normalized_version}".casefold()
    bare_stem = normalized_version.casefold()
    if stem == canonical_stem:
        return 0
    if stem == bare_stem:
        return 1
    return 2


__all__ = [
    "default_release_notes_directory",
    "find_release_notes_for_version",
    "installer_output_directory",
    "release_notes_directories",
]
