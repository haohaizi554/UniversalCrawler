from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from contextvars import Context
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.path_policy import ApprovedFileLease, PathPolicy, normalize_path
from shared.filesystem_directory_capability import FilesystemDirectoryCapability


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

    def test_root_grant_rejects_a_later_same_path_directory_generation(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            workspace = Path(temp_dir)
            approved = workspace / "approved"
            approved.mkdir()
            grant = self.policy.capture_approved_root_grant(approved)
            moved = workspace / "approved-at-grant"
            approved.rename(moved)
            approved.mkdir()

            with self.assertRaisesRegex(PermissionError, "身份已变化"):
                with self.policy.lease_approved_root_grants((grant,)):
                    pass

    def test_root_grant_api_rejects_legacy_string_roots(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            with self.assertRaisesRegex(PermissionError, "身份无效"):
                with self.policy.lease_approved_root_grants((temp_dir,)):
                    pass

    def test_root_grant_rejects_a_symlinked_root(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            workspace = Path(temp_dir)
            target = workspace / "target"
            target.mkdir()
            linked_root = workspace / "linked-root"
            try:
                linked_root.symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")

            with self.assertRaises((OSError, PermissionError)):
                self.policy.capture_approved_root_grant(linked_root)

    def test_root_grant_rejects_an_empty_path_instead_of_approving_cwd(self) -> None:
        with self.assertRaises(PermissionError):
            self.policy.capture_approved_root_grant("")

        current = os.lstat(Path.cwd())
        forged_grant = ("", (int(current.st_dev), int(current.st_ino)))
        with self.assertRaises(PermissionError):
            with self.policy.lease_approved_root_grants((forged_grant,)):
                pass

    def test_root_grant_iteration_is_bounded(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            grant = self.policy.capture_approved_root_grant(root)
            yielded = 0

            def unbounded_grants():
                nonlocal yielded
                while True:
                    yielded += 1
                    yield grant

            with self.assertRaisesRegex(PermissionError, "数量超过"):
                with self.policy.lease_approved_root_grants(unbounded_grants()):
                    pass

            self.assertEqual(yielded, 65)

    def test_grant_binding_rejects_an_existing_final_symlink_inside_root(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir) / "approved"
            root.mkdir()
            target = root / "target.mp4"
            target.write_bytes(b"target")
            link = root / "link.mp4"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            grant = self.policy.capture_approved_root_grant(root)

            with self.policy.lease_approved_root_grants((grant,)) as roots:
                with self.assertRaises(OSError):
                    with roots.bind_child(link) as child:
                        child.stat()

            self.assertEqual(target.read_bytes(), b"target")

    def test_grant_binding_rejects_an_existing_nested_symlink_inside_root(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir) / "approved"
            target_directory = root / "target-directory"
            target_directory.mkdir(parents=True)
            target = target_directory / "target.mp4"
            target.write_bytes(b"target")
            linked_directory = root / "linked-directory"
            try:
                linked_directory.symlink_to(target_directory, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            grant = self.policy.capture_approved_root_grant(root)

            with self.policy.lease_approved_root_grants((grant,)) as roots:
                with self.assertRaises(OSError):
                    with roots.bind_child(linked_directory / target.name):
                        pass

            self.assertEqual(target.read_bytes(), b"target")

    def test_file_lease_cleanup_prefers_the_first_control_flow_error(self) -> None:
        cases = (
            (
                OSError("descriptor-close"),
                KeyboardInterrupt("authority-close"),
                "authority",
            ),
            (
                KeyboardInterrupt("descriptor-close"),
                SystemExit("authority-close"),
                "descriptor",
            ),
            (
                OSError("descriptor-close"),
                RuntimeError("authority-close"),
                "descriptor",
            ),
            (
                None,
                RuntimeError("authority-close"),
                "authority",
            ),
        )
        for descriptor_error, authority_error, expected in cases:
            with self.subTest(
                descriptor=type(descriptor_error).__name__,
                authority=type(authority_error).__name__,
            ):
                authority_stack = ExitStack()
                authority_stack.callback(lambda error=authority_error: (_ for _ in ()).throw(error))
                lease = ApprovedFileLease(
                    descriptor=123,
                    stat_result=os.stat_result((0,) * 10),
                    authority_stack=authority_stack,
                    authority_context=Context(),
                )
                selected = (
                    descriptor_error if expected == "descriptor" else authority_error
                )
                with patch(
                    "app.services.path_policy.os.close",
                    side_effect=descriptor_error,
                ):
                    with self.assertRaises(type(selected)) as raised:
                        lease.close()
                self.assertIs(raised.exception, selected)

    def test_file_lease_cleanup_never_overrides_an_existing_primary(self) -> None:
        primary = RuntimeError("body failed")
        authority_stack = ExitStack()
        authority_stack.callback(
            lambda: (_ for _ in ()).throw(KeyboardInterrupt("authority-close"))
        )
        lease = ApprovedFileLease(
            descriptor=123,
            stat_result=os.stat_result((0,) * 10),
            authority_stack=authority_stack,
            authority_context=Context(),
        )

        with patch(
            "app.services.path_policy.os.close",
            side_effect=OSError("descriptor-close"),
        ):
            lease.close(primary)

        self.assertGreaterEqual(len(getattr(primary, "__notes__", ())), 2)

    @unittest.skipUnless(
        getattr(os, "O_NONBLOCK", 0),
        "platform has no non-blocking descriptor flag",
    )
    def test_approved_file_open_is_nonblocking_before_file_type_validation(
        self,
    ) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir) / "approved"
            media = root / "video.mp4"
            root.mkdir()
            media.write_bytes(b"video")
            grant = self.policy.capture_approved_root_grant(root)
            real_open_child = FilesystemDirectoryCapability.open_child
            observed_flags: list[int] = []

            def record_open_flags(
                capability: FilesystemDirectoryCapability,
                name: str,
                flags: int,
                mode: int = 0o600,
            ) -> int:
                observed_flags.append(flags)
                return real_open_child(capability, name, flags, mode)

            with patch.object(
                FilesystemDirectoryCapability,
                "open_child",
                record_open_flags,
            ):
                lease = self.policy.open_approved_file(media, (grant,))
                lease.close()

            self.assertTrue(observed_flags)
            self.assertTrue(observed_flags[-1] & os.O_NONBLOCK)


if __name__ == "__main__":
    unittest.main()
