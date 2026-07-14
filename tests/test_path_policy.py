from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.path_policy import PathPolicy, normalize_path


class PathPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PathPolicy()

    def test_resolvers_accept_valid_descendants_and_normalize_results(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir) / "approved"
            child = root / "nested"
            child.mkdir(parents=True)
            existing_file = child / "video.mp4"
            existing_file.write_bytes(b"video")
            target = child / "future.mp4"

            cases = (
                ("directory", self.policy.resolve_existing_dir, child),
                ("file", self.policy.resolve_existing_file, existing_file),
                ("target", self.policy.resolve_target_path, target),
            )
            for label, resolver, candidate in cases:
                with self.subTest(resolver=label):
                    self.assertEqual(
                        resolver(str(candidate), (str(root),)),
                        normalize_path(str(candidate)),
                    )

    def test_resolvers_reject_traversal_into_sibling_prefix(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            workspace = Path(temp_dir)
            root = workspace / "approved"
            sibling = workspace / "approved-backup"
            root.mkdir()
            sibling.mkdir()
            sibling_file = sibling / "video.mp4"
            sibling_file.write_bytes(b"video")

            cases = (
                ("directory", self.policy.resolve_existing_dir, root / ".." / sibling.name),
                ("file", self.policy.resolve_existing_file, root / ".." / sibling.name / sibling_file.name),
                ("target", self.policy.resolve_target_path, root / ".." / sibling.name / "future.mp4"),
            )
            for label, resolver, candidate in cases:
                with self.subTest(resolver=label):
                    with self.assertRaises(PermissionError):
                        resolver(str(candidate), (str(root),))

    def test_resolvers_reject_symlink_escape(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            workspace = Path(temp_dir)
            root = workspace / "approved"
            outside = workspace / "outside"
            root.mkdir()
            outside.mkdir()
            outside_file = outside / "video.mp4"
            outside_file.write_bytes(b"video")
            link = root / "linked-outside"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")

            cases = (
                ("directory", self.policy.resolve_existing_dir, link),
                ("file", self.policy.resolve_existing_file, link / outside_file.name),
                ("target", self.policy.resolve_target_path, link / "future.mp4"),
            )
            for label, resolver, candidate in cases:
                with self.subTest(resolver=label):
                    with self.assertRaises(PermissionError):
                        resolver(str(candidate), (str(root),))

    def test_resolvers_reject_missing_paths_and_parent(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir) / "approved"
            root.mkdir()
            cases = (
                ("directory", self.policy.resolve_existing_dir, root / "missing-directory"),
                ("file", self.policy.resolve_existing_file, root / "missing-file.mp4"),
                ("target-parent", self.policy.resolve_target_path, root / "missing-parent" / "future.mp4"),
            )
            for label, resolver, candidate in cases:
                with self.subTest(resolver=label):
                    with self.assertRaises(FileNotFoundError):
                        resolver(str(candidate), (str(root),))

    def test_empty_approved_roots_leave_existing_paths_unrestricted(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            existing_file = root / "video.mp4"
            existing_file.write_bytes(b"video")
            target = root / "future.mp4"

            root_cases = (None, (), [], ("",))
            resolver_cases = (
                ("directory", self.policy.resolve_existing_dir, root),
                ("file", self.policy.resolve_existing_file, existing_file),
                ("target", self.policy.resolve_target_path, target),
            )
            for approved_roots in root_cases:
                for label, resolver, candidate in resolver_cases:
                    with self.subTest(approved_roots=approved_roots, resolver=label):
                        self.assertEqual(
                            resolver(str(candidate), approved_roots),
                            normalize_path(str(candidate)),
                        )

    def test_commonpath_cross_drive_failure_is_treated_as_unauthorized(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            with patch(
                "app.services.path_policy.os.path.commonpath",
                side_effect=ValueError("Paths don't have the same drive"),
            ):
                with self.assertRaises(PermissionError):
                    self.policy.resolve_existing_dir(str(root), (str(root),))


if __name__ == "__main__":
    unittest.main()
