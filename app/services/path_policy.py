from __future__ import annotations

import os
from typing import Iterable

def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))

def is_within_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False

class PathPolicy:
    """统一文件/目录的最终路径授权策略。"""

    def normalize_roots(self, approved_roots: Iterable[str] | None) -> tuple[str, ...]:
        return tuple(normalize_path(root) for root in approved_roots or () if isinstance(root, str) and root)

    def assert_within_approved_roots(self, path: str, approved_roots: Iterable[str] | None) -> str:
        normalized = normalize_path(path)
        normalized_roots = self.normalize_roots(approved_roots)
        if normalized_roots and not any(is_within_root(normalized, root) for root in normalized_roots):
            raise PermissionError("目录未被当前会话授权访问")
        return normalized

    def resolve_existing_dir(self, directory: str, approved_roots: Iterable[str] | None = None) -> str:
        normalized = normalize_path(directory)
        if not os.path.isdir(normalized):
            raise FileNotFoundError("目录不存在")
        return self.assert_within_approved_roots(normalized, approved_roots)

    def resolve_existing_file(self, file_path: str, approved_roots: Iterable[str] | None = None) -> str:
        normalized = normalize_path(file_path)
        if not os.path.isfile(normalized):
            raise FileNotFoundError("文件不存在")
        return self.assert_within_approved_roots(normalized, approved_roots)

    def resolve_target_path(self, target_path: str, approved_roots: Iterable[str] | None = None) -> str:
        normalized = normalize_path(target_path)
        parent_dir = os.path.dirname(normalized)
        if not os.path.isdir(parent_dir):
            raise FileNotFoundError("目标目录不存在")
        self.assert_within_approved_roots(parent_dir, approved_roots)
        return normalized
