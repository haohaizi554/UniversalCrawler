"""文件服务的扫描、删除与元数据操作测试。"""

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.file_service import MediaLibraryService

class MediaLibraryServiceTests(unittest.TestCase):
    """文件服务行为测试，重点覆盖 Windows 句柄重试和下载残留清理。"""

    def setUp(self):
        self.service = MediaLibraryService(
            video_extensions=(".mp4", ".webm"),
            image_extensions=(".jpg", ".png"),
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_scan_directory_detects_media_types(self):
        """验证 `test_scan_directory_detects_media_types` 对应场景是否符合预期，供 `MediaLibraryServiceTests` 使用。"""
        base = self.temp_dir.name
        with open(os.path.join(base, "video.mp4"), "wb") as fp:
            fp.write(b"test")
        with open(os.path.join(base, "image.jpg"), "wb") as fp:
            fp.write(b"test")
        with open(os.path.join(base, "ignore.txt"), "w", encoding="utf-8") as fp:
            fp.write("ignore")

        result = self.service.scan_directory(base)

        self.assertEqual(result.total_count, 2)
        self.assertEqual(result.video_count, 1)
        self.assertEqual(result.image_count, 1)

    def test_rename_and_delete_media(self):
        """验证 `test_rename_and_delete_media` 对应场景是否符合预期，供 `MediaLibraryServiceTests` 使用。"""
        base = self.temp_dir.name
        file_path = os.path.join(base, "old.mp4")
        with open(file_path, "wb") as fp:
            fp.write(b"test")

        item = VideoItem(url="", title="old", source="local")
        item.local_path = file_path

        _, new_path = self.service.rename_media(item, "new_name", base)
        self.assertTrue(os.path.exists(new_path))

        item.local_path = new_path
        deleted = self.service.delete_media(item)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(new_path))

    def test_scan_directory_creates_missing_directory(self):
        """验证 `test_scan_directory_creates_missing_directory` 对应场景是否符合预期，供 `MediaLibraryServiceTests` 使用。"""
        missing_dir = os.path.join(self.temp_dir.name, "missing")

        result = self.service.scan_directory(missing_dir)

        self.assertTrue(os.path.isdir(missing_dir))
        self.assertEqual(result.total_count, 0)
        self.assertEqual(result.items, [])

    def test_scan_directory_marks_result_as_truncated(self):
        """验证 `test_scan_directory_marks_result_as_truncated` 对应场景是否符合预期，供 `MediaLibraryServiceTests` 使用。"""
        base = self.temp_dir.name
        for index in range(3):
            with open(os.path.join(base, f"video-{index}.mp4"), "wb") as fp:
                fp.write(b"test")

        result = self.service.scan_directory(base, max_scan_count=2)

        self.assertEqual(result.total_count, 2)
        self.assertTrue(result.truncated)
        self.assertEqual(result.original_count, 3)

    def test_rename_media_rejects_conflicting_name(self):
        """验证 `test_rename_media_rejects_conflicting_name` 对应场景是否符合预期，供 `MediaLibraryServiceTests` 使用。"""
        base = self.temp_dir.name
        source_path = os.path.join(base, "old.mp4")
        with open(source_path, "wb") as fp:
            fp.write(b"test")
        with open(os.path.join(base, "taken.mp4"), "wb") as fp:
            fp.write(b"test")

        item = VideoItem(url="", title="old", source="local")
        item.local_path = source_path

        with self.assertRaisesRegex(FileOperationError, "已存在"):
            self.service.rename_media(item, "taken", base)

    def test_rename_media_rejects_case_only_name_owned_by_a_distinct_file(self):
        base = self.temp_dir.name
        source_path = os.path.join(base, "Foo.mp4")
        Path(source_path).write_bytes(b"source")
        item = VideoItem(url="", title="Foo", source="local")
        item.local_path = source_path

        with (
            patch("app.services.file_service.os.path.lexists", return_value=True),
            patch("app.services.file_service.os.path.samefile", return_value=False),
            patch("app.services.file_service.os.rename") as rename,
        ):
            with self.assertRaisesRegex(FileOperationError, "已存在"):
                self.service.rename_media(item, "foo", base)

        rename.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "requires Windows rename semantics")
    def test_rename_media_applies_a_case_only_change_to_the_directory_entry(self):
        base = self.temp_dir.name
        source_path = os.path.join(base, "Foo.mp4")
        target_path = os.path.join(base, "foo.mp4")
        Path(source_path).write_bytes(b"source")
        item = VideoItem(url="", title="Foo", source="local")
        item.local_path = source_path

        result = self.service.rename_media(item, "foo", base)

        self.assertEqual(result, (source_path, target_path))
        self.assertEqual(os.listdir(base), ["foo.mp4"])
        self.assertEqual(Path(target_path).read_bytes(), b"source")

    def test_rename_media_recognizes_a_unique_casefolded_directory_entry(self):
        base = self.temp_dir.name
        source_path = os.path.join(base, "Foo.mp4")
        target_path = os.path.join(base, "foo.mp4")
        Path(source_path).write_bytes(b"source")
        item = VideoItem(url="", title="Foo", source="local")
        item.local_path = source_path
        source_stat = os.lstat(source_path)

        with (
            patch("app.services.file_service.os.path.lexists", return_value=True),
            patch("app.services.file_service.os.path.samefile", return_value=True),
            patch("app.services.file_service.os.path.normcase", side_effect=lambda value: value),
            patch("app.services.file_service.os.lstat", return_value=source_stat),
            patch("app.services.file_service.os.rename") as rename,
        ):
            result = self.service.rename_media(item, "foo", base)

        self.assertEqual(result, (source_path, target_path))
        rename.assert_called_once_with(source_path, target_path)

    def test_rename_media_rejects_an_existing_hardlink_alias(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "alias.mp4"
        source_path.write_bytes(b"source")
        try:
            os.link(source_path, target_path)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"hard links are unavailable on this host: {exc}")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        with self.assertRaisesRegex(FileOperationError, "已存在"):
            self.service.rename_media(item, "alias", os.fspath(base))

        self.assertTrue(source_path.exists())
        self.assertTrue(target_path.exists())
        self.assertTrue(os.path.samefile(source_path, target_path))

    def test_rename_media_rejects_a_dangling_symlink_target(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        missing_path = base / "missing.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        try:
            target_path.symlink_to(missing_path)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links are unavailable on this host: {exc}")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        with patch("app.services.file_service.os.rename") as rename:
            with self.assertRaisesRegex(FileOperationError, "已存在"):
                self.service.rename_media(item, "target", os.fspath(base))

        rename.assert_not_called()
        self.assertEqual(source_path.read_bytes(), b"source")
        self.assertTrue(target_path.is_symlink())

    def test_rename_media_rejects_a_symlink_alias_to_the_source(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "alias.mp4"
        source_path.write_bytes(b"source")
        try:
            target_path.symlink_to(source_path)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links are unavailable on this host: {exc}")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        with self.assertRaisesRegex(FileOperationError, "已存在"):
            self.service.rename_media(item, "alias", os.fspath(base))

        self.assertTrue(source_path.exists())
        self.assertTrue(target_path.is_symlink())
        self.assertTrue(os.path.samefile(source_path, target_path))

    def test_rename_media_rechecks_a_target_that_appears_before_mutation(self):
        base = self.temp_dir.name
        source_path = os.path.join(base, "source.mp4")
        Path(source_path).write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = source_path

        with (
            patch(
                "app.services.file_service.os.path.lexists",
                side_effect=(False, True),
            ),
            patch("app.services.file_service.os.path.samefile", return_value=False),
            patch("app.services.file_service.os.rename") as rename,
        ):
            with self.assertRaisesRegex(FileOperationError, "已存在"):
                self.service.rename_media(item, "target", base)

        rename.assert_not_called()

    def test_rename_media_rechecks_source_after_target_preflight(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        target_checks = 0

        def replace_source_during_target_preflight(_source: str, _target: str) -> str:
            nonlocal target_checks
            target_checks += 1
            if target_checks == 2:
                source_path.unlink()
                source_path.write_bytes(b"replacement")
            return "available"

        with (
            patch.object(
                self.service,
                "_rename_target_state",
                side_effect=replace_source_during_target_preflight,
            ),
            patch.object(self.service, "_atomic_rename_no_replace") as atomic_rename,
        ):
            with self.assertRaisesRegex(FileOperationError, "源文件.*变化"):
                self.service.rename_media(item, "target", os.fspath(base))

        atomic_rename.assert_not_called()
        self.assertEqual(source_path.read_bytes(), b"replacement")
        self.assertFalse(target_path.exists())

    def test_rename_media_atomic_publish_refuses_a_racing_target_without_cleanup(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        def claim_target_then_fail(_source: str, target: str) -> None:
            Path(target).write_bytes(b"racer")
            raise FileExistsError("target claimed")

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=claim_target_then_fail,
            ) as atomic_rename,
            patch("app.services.file_service.os.link") as link,
            patch("app.services.file_service.os.unlink") as unlink,
        ):
            with self.assertRaisesRegex(FileOperationError, "已存在"):
                self.service.rename_media(item, "target", os.fspath(base))

        atomic_rename.assert_called_once_with(os.fspath(source_path), os.fspath(target_path))
        link.assert_not_called()
        unlink.assert_not_called()
        self.assertEqual(source_path.read_bytes(), b"source")
        self.assertEqual(target_path.read_bytes(), b"racer")

    def test_rename_media_atomic_publish_failure_never_runs_rollback_unlink(self):
        class PrimaryFailure(BaseException):
            pass

        class HostileCleanupFailure(BaseException):
            pass

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = PrimaryFailure("primary")

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=primary,
            ),
            patch(
                "app.services.file_service.os.unlink",
                side_effect=HostileCleanupFailure("secondary"),
            ) as unlink,
            patch("app.services.file_service.os.link") as link,
        ):
            with self.assertRaises(PrimaryFailure) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception, primary)
        link.assert_not_called()
        unlink.assert_not_called()
        self.assertEqual(source_path.read_bytes(), b"source")
        self.assertFalse(target_path.exists())

    def test_rename_media_accepts_native_error_after_the_frozen_source_was_moved(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = OSError(errno.EIO, "native wrapper failed after rename")

        def move_then_fail(source: str, target: str) -> None:
            os.rename(source, target)
            raise primary

        with patch.object(
            self.service,
            "_atomic_rename_no_replace",
            side_effect=move_then_fail,
        ):
            result = self.service.rename_media(item, "target", os.fspath(base))

        self.assertEqual(result, (os.fspath(source_path), os.fspath(target_path)))
        self.assertFalse(source_path.exists())
        self.assertEqual(target_path.read_bytes(), b"source")

    def test_rename_media_does_not_retry_when_move_probe_raises_base_exception(self):
        class ProbeFailure(BaseException):
            pass

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = PermissionError(errno.EACCES, "wrapper failed after move")
        moved = False
        real_lstat = os.lstat

        def move_then_fail(source: str, target: str) -> None:
            nonlocal moved
            os.rename(source, target)
            moved = True
            raise primary

        def fail_target_probe(path: str) -> os.stat_result:
            if moved and os.fspath(path) == os.fspath(target_path):
                raise ProbeFailure("secondary target probe failure")
            return real_lstat(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=move_then_fail,
            ) as atomic_rename,
            patch("app.services.file_service.os.lstat", side_effect=fail_target_probe),
            patch("app.services.file_service.time.sleep") as sleep,
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception.__cause__, primary)
        atomic_rename.assert_called_once()
        sleep.assert_not_called()
        self.assertFalse(source_path.exists())
        self.assertEqual(target_path.read_bytes(), b"source")

    def test_rename_media_rejects_target_replacement_between_completion_probes(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = OSError(errno.EIO, "native wrapper failed after rename")
        moved = False
        target_probes = 0
        real_lstat = os.lstat

        def move_then_fail(source: str, target: str) -> None:
            nonlocal moved
            os.rename(source, target)
            moved = True
            raise primary

        def replace_between_target_probes(path: str) -> os.stat_result:
            nonlocal target_probes
            if moved and os.fspath(path) == os.fspath(target_path):
                target_probes += 1
                if target_probes == 2:
                    target_path.unlink()
                    target_path.write_bytes(b"racer")
            return real_lstat(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=move_then_fail,
            ),
            patch(
                "app.services.file_service.os.lstat",
                side_effect=replace_between_target_probes,
            ),
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception.__cause__, primary)
        self.assertEqual(target_probes, 2)
        self.assertFalse(source_path.exists())
        self.assertEqual(target_path.read_bytes(), b"racer")

    def test_rename_media_preserves_native_error_for_all_unconfirmed_move_states(self):
        scenarios = (
            "source_present_target_missing",
            "source_missing_target_missing",
            "source_missing_target_different",
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                base = Path(self.temp_dir.name) / scenario
                base.mkdir()
                source_path = base / "source.mp4"
                target_path = base / "target.mp4"
                source_path.write_bytes(b"source")
                item = VideoItem(url="", title="source", source="local")
                item.local_path = os.fspath(source_path)
                primary = OSError(errno.EIO, f"primary-{scenario}")

                def fail_in_state(_source: str, _target: str) -> None:
                    if scenario != "source_present_target_missing":
                        source_path.unlink()
                    if scenario == "source_missing_target_different":
                        target_path.write_bytes(b"racer")
                    raise primary

                with patch.object(
                    self.service,
                    "_atomic_rename_no_replace",
                    side_effect=fail_in_state,
                ):
                    with self.assertRaises(FileOperationError) as captured:
                        self.service.rename_media(item, "target", os.fspath(base))

                self.assertIs(captured.exception.__cause__, primary)
                self.assertIn(f"primary-{scenario}", str(captured.exception))

    def test_rename_media_target_absence_probe_base_exception_cannot_replace_primary_error(self):
        class ProbeFailure(BaseException):
            pass

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = OSError(errno.EIO, "primary rename failure")
        native_failed = False
        real_lstat = os.lstat

        def fail_native(_source: str, _target: str) -> None:
            nonlocal native_failed
            native_failed = True
            raise primary

        def fail_reconciliation_probe(path: str) -> os.stat_result:
            if native_failed and os.fspath(path) != os.fspath(source_path):
                raise ProbeFailure("secondary target absence probe failure")
            return real_lstat(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=fail_native,
            ),
            patch(
                "app.services.file_service.os.lstat",
                side_effect=fail_reconciliation_probe,
            ),
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception.__cause__, primary)
        self.assertIn("状态对账", " ".join(getattr(primary, "__notes__", ())))

    def test_rename_media_target_stat_base_exception_cannot_replace_primary_error(self):
        class ProbeFailure(BaseException):
            pass

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = OSError(errno.EIO, "primary rename failure")
        native_failed = False
        real_lstat = os.lstat

        def fail_native(_source: str, _target: str) -> None:
            nonlocal native_failed
            native_failed = True
            raise primary

        def fail_target_stat(path: str) -> os.stat_result:
            if native_failed:
                raise ProbeFailure("secondary target stat failure")
            return real_lstat(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=fail_native,
            ),
            patch("app.services.file_service.os.path.lexists", return_value=False),
            patch("app.services.file_service.os.lstat", side_effect=fail_target_stat),
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception.__cause__, primary)
        self.assertIn("状态对账", " ".join(getattr(primary, "__notes__", ())))

    def test_rename_media_reconciliation_preserves_domain_error_identity(self):
        class ProbeFailure(BaseException):
            pass

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = FileOperationError("primary domain failure")
        native_failed = False
        real_lstat = os.lstat

        def fail_native(_source: str, _target: str) -> None:
            nonlocal native_failed
            native_failed = True
            raise primary

        def fail_reconciliation_probe(path: str) -> os.stat_result:
            if native_failed and os.fspath(path) != os.fspath(source_path):
                raise ProbeFailure("secondary probe failure")
            return real_lstat(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=fail_native,
            ),
            patch(
                "app.services.file_service.os.lstat",
                side_effect=fail_reconciliation_probe,
            ),
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception, primary)
        self.assertIn("状态对账", " ".join(getattr(primary, "__notes__", ())))

    def test_rename_media_reconciliation_tolerates_hostile_add_note(self):
        class ProbeFailure(BaseException):
            pass

        class HostilePrimary(OSError):
            def add_note(self, _note: str) -> None:
                raise ProbeFailure("hostile add_note")

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = HostilePrimary(errno.EIO, "primary rename failure")
        native_failed = False
        real_lstat = os.lstat

        def fail_native(_source: str, _target: str) -> None:
            nonlocal native_failed
            native_failed = True
            raise primary

        def fail_reconciliation_probe(path: str) -> os.stat_result:
            if native_failed and os.fspath(path) != os.fspath(source_path):
                raise ProbeFailure("secondary probe failure")
            return real_lstat(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=fail_native,
            ),
            patch(
                "app.services.file_service.os.lstat",
                side_effect=fail_reconciliation_probe,
            ),
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception.__cause__, primary)

    def test_rename_media_unknown_permission_state_survives_hostile_secondary_failures(self):
        class ProbeFailure(BaseException):
            pass

        class HostilePrimary(PermissionError):
            def add_note(self, _note: str) -> None:
                raise ProbeFailure("hostile add_note")

            def __str__(self) -> str:
                raise ProbeFailure("hostile primary stringification")

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        primary = HostilePrimary(errno.EACCES, "primary rename failure")
        native_failed = False
        real_lstat = os.lstat
        real_lexists = os.path.lexists

        def fail_native(_source: str, _target: str) -> None:
            nonlocal native_failed
            native_failed = True
            raise primary

        def fail_lstat_after_native(path: str) -> os.stat_result:
            if native_failed:
                raise ProbeFailure("secondary lstat failure")
            return real_lstat(path)

        def fail_lexists_after_native(path: str) -> bool:
            if native_failed:
                raise ProbeFailure("secondary lexists failure")
            return real_lexists(path)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=fail_native,
            ) as atomic_rename,
            patch(
                "app.services.file_service.os.lstat",
                side_effect=fail_lstat_after_native,
            ),
            patch(
                "app.services.file_service.os.path.lexists",
                side_effect=fail_lexists_after_native,
            ),
            patch("app.services.file_service.time.sleep") as sleep,
        ):
            with self.assertRaises(FileOperationError) as captured:
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertIs(captured.exception.__cause__, primary)
        atomic_rename.assert_called_once()
        sleep.assert_not_called()

    def test_rename_media_target_absence_probe_errors_are_unknown_and_never_retried(self):
        for probe_error in (
            PermissionError("target is inaccessible"),
            ValueError("target path cannot be inspected"),
        ):
            with self.subTest(probe_error=type(probe_error).__name__):
                base = Path(self.temp_dir.name) / type(probe_error).__name__
                base.mkdir()
                source_path = base / "source.mp4"
                target_path = base / "target.mp4"
                source_path.write_bytes(b"source")
                item = VideoItem(url="", title="source", source="local")
                item.local_path = os.fspath(source_path)
                primary = PermissionError(errno.EACCES, "primary rename failure")
                native_failed = False
                real_lstat = os.lstat

                def fail_native(_source: str, _target: str) -> None:
                    nonlocal native_failed
                    native_failed = True
                    raise primary

                def fail_target_probe(path: str) -> os.stat_result:
                    if native_failed and os.fspath(path) == os.fspath(target_path):
                        raise probe_error
                    return real_lstat(path)

                with (
                    patch.object(
                        self.service,
                        "_atomic_rename_no_replace",
                        side_effect=fail_native,
                    ) as atomic_rename,
                    patch(
                        "app.services.file_service.os.lstat",
                        side_effect=fail_target_probe,
                    ),
                    patch("app.services.file_service.time.sleep") as sleep,
                ):
                    with self.assertRaises(FileOperationError) as captured:
                        self.service.rename_media(item, "target", os.fspath(base))

                self.assertIs(captured.exception.__cause__, primary)
                atomic_rename.assert_called_once()
                sleep.assert_not_called()
                self.assertEqual(source_path.read_bytes(), b"source")
                self.assertFalse(target_path.exists())

    def test_rename_media_retries_only_after_proven_not_completed_state(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        events: list[str] = []
        attempts = 0
        real_source_stat = self.service._regular_rename_source_stat
        real_target_state = self.service._rename_target_state

        def checked_source(*args, **kwargs):
            events.append("source")
            return real_source_stat(*args, **kwargs)

        def checked_target(*args, **kwargs):
            events.append("target")
            return real_target_state(*args, **kwargs)

        def permission_then_move(source: str, target: str) -> None:
            nonlocal attempts
            attempts += 1
            events.append("syscall")
            if attempts == 1:
                raise PermissionError("source busy")
            os.rename(source, target)

        with (
            patch.object(
                self.service,
                "_regular_rename_source_stat",
                side_effect=checked_source,
            ),
            patch.object(
                self.service,
                "_rename_target_state",
                side_effect=checked_target,
            ),
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=permission_then_move,
            ),
            patch("app.services.file_service.time.sleep", return_value=None),
        ):
            result = self.service.rename_media(item, "target", os.fspath(base))

        syscall_indexes = [i for i, event in enumerate(events) if event == "syscall"]
        self.assertEqual(attempts, 2)
        self.assertTrue(all(events[index - 1] == "source" for index in syscall_indexes))
        self.assertEqual(result, (os.fspath(source_path), os.fspath(target_path)))
        self.assertFalse(source_path.exists())
        self.assertEqual(target_path.read_bytes(), b"source")

    def test_rename_media_native_success_has_no_post_publish_identity_window(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        frozen_source = os.lstat(source_path)

        def atomic_move(source: str, target: str) -> None:
            os.rename(source, target)

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=atomic_move,
            ) as atomic_rename,
            patch.object(
                self.service,
                "_rename_target_state",
                side_effect=("available", "available"),
            ),
            patch(
                "app.services.file_service.os.lstat",
                side_effect=(
                    frozen_source,
                    frozen_source,
                    frozen_source,
                    AssertionError("no identity check may run after the atomic move"),
                ),
            ) as lstat,
            patch("app.services.file_service.os.link") as link,
            patch("app.services.file_service.os.unlink") as unlink,
        ):
            result = self.service.rename_media(item, "target", os.fspath(base))

        self.assertEqual(result, (os.fspath(source_path), os.fspath(target_path)))
        atomic_rename.assert_called_once()
        self.assertEqual(lstat.call_count, 3)
        link.assert_not_called()
        unlink.assert_not_called()
        self.assertFalse(source_path.exists())
        self.assertEqual(target_path.read_bytes(), b"source")

    def test_rename_media_rechecks_frozen_source_before_native_retry(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)
        real_unlink = os.unlink
        attempts = {"count": 0}

        def busy_rename(_source: str, _target: str) -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise PermissionError("source busy")
            raise AssertionError("a replacement source must never be moved")

        def replace_source_during_retry(_delay: float) -> None:
            real_unlink(source_path)
            source_path.write_bytes(b"replacement")

        with (
            patch.object(
                self.service,
                "_atomic_rename_no_replace",
                side_effect=busy_rename,
            ),
            patch(
                "app.services.file_service.time.sleep",
                side_effect=replace_source_during_retry,
            ),
        ):
            with self.assertRaisesRegex(FileOperationError, "源文件.*变化"):
                self.service.rename_media(item, "target", os.fspath(base))

        self.assertEqual(attempts["count"], 1)
        self.assertEqual(source_path.read_bytes(), b"replacement")
        self.assertFalse(target_path.exists())

    def test_rename_media_is_idempotent_for_the_exact_regular_source_path(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.write_bytes(b"source")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        with patch.object(
            self.service,
            "_atomic_rename_no_replace",
        ) as atomic_rename:
            result = self.service.rename_media(item, "source", os.fspath(base))

        self.assertEqual(result, (os.fspath(source_path), os.fspath(source_path)))
        atomic_rename.assert_not_called()
        self.assertEqual(source_path.read_bytes(), b"source")

    def test_rename_media_rejects_a_directory_before_exact_path_noop(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        source_path.mkdir()
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        with patch.object(
            self.service,
            "_atomic_rename_no_replace",
        ) as atomic_rename:
            with self.assertRaisesRegex(FileOperationError, "普通媒体文件"):
                self.service.rename_media(item, "source", os.fspath(base))

        atomic_rename.assert_not_called()
        self.assertTrue(source_path.is_dir())

    def test_rename_media_rejects_a_valid_source_symlink_before_exact_path_noop(self):
        base = Path(self.temp_dir.name)
        real_source = base / "real.mp4"
        source_path = base / "source.mp4"
        real_source.write_bytes(b"source")
        try:
            source_path.symlink_to(real_source)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links are unavailable on this host: {exc}")
        item = VideoItem(url="", title="source", source="local")
        item.local_path = os.fspath(source_path)

        with patch.object(
            self.service,
            "_atomic_rename_no_replace",
        ) as atomic_rename:
            with self.assertRaisesRegex(FileOperationError, "普通媒体文件"):
                self.service.rename_media(item, "source", os.fspath(base))

        atomic_rename.assert_not_called()
        self.assertTrue(source_path.is_symlink())
        self.assertEqual(real_source.read_bytes(), b"source")

    def test_atomic_no_replace_uses_renameat2_on_supported_unix_platforms(self):
        class NativeRename:
            def __init__(self):
                self.calls = []

            def __call__(self, *args):
                self.calls.append(args)
                return 0

        for platform in ("linux", "freebsd16"):
            native_rename = NativeRename()
            library = type("Library", (), {"renameat2": native_rename})()
            with (
                self.subTest(platform=platform),
                patch("app.services.file_service.os.name", "posix"),
                patch("app.services.file_service.sys.platform", platform),
                patch("app.services.file_service.ctypes.CDLL", return_value=library),
            ):
                self.service._atomic_rename_no_replace("source.mp4", "target.mp4")

            self.assertEqual(
                native_rename.calls,
                [(-100, b"source.mp4", -100, b"target.mp4", 1)],
            )

    def test_atomic_no_replace_uses_rename_excl_on_darwin(self):
        class NativeRename:
            def __init__(self):
                self.calls = []

            def __call__(self, *args):
                self.calls.append(args)
                return 0

        native_rename = NativeRename()
        library = type("Library", (), {"renamex_np": native_rename})()
        with (
            patch("app.services.file_service.os.name", "posix"),
            patch("app.services.file_service.sys.platform", "darwin"),
            patch("app.services.file_service.ctypes.CDLL", return_value=library),
        ):
            self.service._atomic_rename_no_replace("source.mp4", "target.mp4")

        self.assertEqual(native_rename.calls, [(b"source.mp4", b"target.mp4", 4)])

    def test_atomic_no_replace_maps_native_eexist_to_file_exists(self):
        class NativeRename:
            def __call__(self, *_args):
                return -1

        library = type("Library", (), {"renameat2": NativeRename()})()
        with (
            patch("app.services.file_service.os.name", "posix"),
            patch("app.services.file_service.sys.platform", "linux"),
            patch("app.services.file_service.ctypes.CDLL", return_value=library),
            patch("app.services.file_service.ctypes.get_errno", return_value=errno.EEXIST),
        ):
            with self.assertRaises(FileExistsError):
                self.service._atomic_rename_no_replace("source.mp4", "target.mp4")

    def test_atomic_no_replace_rejects_text_and_bytes_nul_before_loading_native_symbol(self):
        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        path_pairs = (
            (os.fspath(source_path) + "\0suffix", os.fspath(target_path)),
            (os.fsencode(source_path) + b"\0suffix", os.fsencode(target_path)),
        )

        for source, target in path_pairs:
            with (
                self.subTest(path_type=type(source).__name__),
                patch("app.services.file_service.os.name", "posix"),
                patch("app.services.file_service.sys.platform", "linux"),
                patch("app.services.file_service.ctypes.CDLL") as load_library,
            ):
                with self.assertRaisesRegex(FileOperationError, "NUL"):
                    self.service._atomic_rename_no_replace(source, target)
                load_library.assert_not_called()

        self.assertEqual(source_path.read_bytes(), b"source")
        self.assertFalse(target_path.exists())

    def test_atomic_no_replace_rejects_pathlike_nul_before_loading_native_symbol(self):
        class BytesPathLike:
            def __init__(self, value: bytes):
                self.value = value

            def __fspath__(self) -> bytes:
                return self.value

        base = Path(self.temp_dir.name)
        source_path = base / "source.mp4"
        target_path = base / "target.mp4"
        source_path.write_bytes(b"source")
        path_pairs = (
            (Path(os.fspath(source_path) + "\0suffix"), target_path),
            (BytesPathLike(os.fsencode(source_path) + b"\0suffix"), target_path),
        )

        for source, target in path_pairs:
            with (
                self.subTest(path_type=type(source).__name__),
                patch("app.services.file_service.os.name", "posix"),
                patch("app.services.file_service.sys.platform", "linux"),
                patch("app.services.file_service.ctypes.CDLL") as load_library,
            ):
                with self.assertRaisesRegex(FileOperationError, "NUL"):
                    self.service._atomic_rename_no_replace(source, target)
                load_library.assert_not_called()

        self.assertEqual(source_path.read_bytes(), b"source")
        self.assertFalse(target_path.exists())

    def test_darwin_exclusive_conflict_never_falls_back_to_plain_rename(self):
        class NativeRename:
            def __call__(self, *_args):
                return -1

        library = type("Library", (), {"renamex_np": NativeRename()})()
        with (
            patch("app.services.file_service.os.name", "posix"),
            patch("app.services.file_service.sys.platform", "darwin"),
            patch("app.services.file_service.ctypes.CDLL", return_value=library),
            patch("app.services.file_service.ctypes.get_errno", return_value=errno.EEXIST),
            patch("app.services.file_service.os.rename") as plain_rename,
        ):
            with self.assertRaises(FileExistsError):
                self.service._atomic_rename_no_replace("Foo.mp4", "foo.mp4")

        plain_rename.assert_not_called()

    def test_atomic_no_replace_fails_closed_on_an_unsupported_platform(self):
        with (
            patch("app.services.file_service.os.name", "posix"),
            patch("app.services.file_service.sys.platform", "openbsd7"),
            patch("app.services.file_service.os.rename") as rename,
        ):
            with self.assertRaisesRegex(FileOperationError, "不支持原子无覆盖重命名"):
                self.service._atomic_rename_no_replace("source.mp4", "target.mp4")

        rename.assert_not_called()

    @patch("app.services.file_service.time.sleep", return_value=None)
    def test_rename_media_retries_briefly_after_permission_error(self, _mock_sleep):
        """Windows 释放播放器句柄存在瞬时延迟时，重命名也应进行短暂重试。"""
        base = self.temp_dir.name
        source_path = os.path.join(base, "old.mp4")
        with open(source_path, "wb") as fp:
            fp.write(b"test")
        item = VideoItem(url="", title="old", source="local")
        item.local_path = source_path

        real_rename = os.rename
        attempts = {"count": 0}
        target_path = os.path.join(base, "new_name.mp4")

        def flaky_rename(src, dst):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise PermissionError("文件被占用")
            return real_rename(src, dst)

        with patch("app.services.file_service.os.rename", side_effect=flaky_rename):
            old_path, new_path = self.service.rename_media(item, "new_name", base)

        self.assertEqual((old_path, new_path), (source_path, target_path))
        self.assertEqual(attempts["count"], 2)
        self.assertTrue(os.path.exists(target_path))

    def test_delete_media_returns_false_for_missing_path(self):
        """验证 `test_delete_media_returns_false_for_missing_path` 对应场景是否符合预期，供 `MediaLibraryServiceTests` 使用。"""
        item = VideoItem(url="", title="missing", source="local")
        item.local_path = os.path.join(self.temp_dir.name, "missing.mp4")

        self.assertFalse(self.service.delete_media(item))

    def test_delete_last_collection_resource_removes_only_the_owned_empty_folder(self):
        root = Path(self.temp_dir.name)
        collection = root / "Owned Collection"
        collection.mkdir()
        media_path = collection / "episode.mp4"
        media_path.write_bytes(b"media")
        item = VideoItem(url="", title="episode", source="bilibili")
        item.local_path = os.fspath(media_path)
        item.meta.update({"folder_name": "Owned Collection", "use_subdir": True})

        self.assertTrue(self.service.delete_media(item))

        self.assertFalse(collection.exists())
        self.assertTrue(root.exists())

    def test_delete_failed_collection_cache_removes_empty_owned_folder_without_final_path(self):
        root = Path(self.temp_dir.name)
        collection = root / "Failed Collection"
        collection.mkdir()
        cache_path = collection / "episode_audio.m4s"
        cache_path.write_bytes(b"partial")
        item = VideoItem(url="", title="episode", source="bilibili")
        item.meta.update(
            {
                "folder_name": "Failed Collection",
                "use_subdir": True,
                "download_temp_files": [os.fspath(cache_path)],
            }
        )

        self.assertTrue(self.service.delete_media(item))

        self.assertFalse(collection.exists())
        self.assertTrue(root.exists())

    def test_empty_collection_cleanup_does_not_follow_directory_symlink(self):
        root = Path(self.temp_dir.name)
        target = root / "target" / "Owned Collection"
        target.mkdir(parents=True)
        link = root / "Owned Collection"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable on this host")

        item = VideoItem(url="", title="episode", source="bilibili")
        item.local_path = os.fspath(link / "missing.mp4")
        item.meta.update({"folder_name": "Owned Collection", "use_subdir": True})

        self.assertFalse(self.service.delete_media(item))
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())

    def test_delete_media_removes_bilibili_temp_sidecars(self):
        """删除 B站最终文件时，应同步删除同 stem 的音视频分流缓存。"""
        base = self.temp_dir.name
        file_path = os.path.join(base, "demo.mp4")
        video_temp = os.path.join(base, "demo_video.m4s")
        audio_temp = os.path.join(base, "demo_audio.m4s")
        unrelated = os.path.join(base, "demo_cover.m4s")
        for path in (file_path, video_temp, audio_temp, unrelated):
            with open(path, "wb") as fp:
                fp.write(b"test")
        item = VideoItem(url="", title="demo", source="bilibili")
        item.local_path = file_path
        item.meta["download_temp_files"] = [video_temp, audio_temp]

        deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(file_path))
        self.assertFalse(os.path.exists(video_temp))
        self.assertFalse(os.path.exists(audio_temp))
        self.assertTrue(os.path.exists(unrelated))

    def test_delete_media_removes_generic_download_temp_artifacts(self):
        """删除普通下载结果时，应联动清理 `.downloading`、分片和 meta 显式临时文件。"""
        base = self.temp_dir.name
        file_path = os.path.join(base, "demo.mp4")
        http_temp = file_path + ".downloading"
        chunk_temp = os.path.join(base, ".demo.mp4.part0")
        explicit_temp = os.path.join(base, "demo.custom.tmp")
        unrelated = os.path.join(base, "demo_cover.m4s")
        for path in (file_path, http_temp, chunk_temp, explicit_temp, unrelated):
            with open(path, "wb") as fp:
                fp.write(b"test")
        item = VideoItem(url="", title="demo", source="douyin")
        item.local_path = file_path
        item.meta["download_temp_files"] = [explicit_temp]

        deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(file_path))
        self.assertFalse(os.path.exists(http_temp))
        self.assertFalse(os.path.exists(chunk_temp))
        self.assertFalse(os.path.exists(explicit_temp))
        self.assertTrue(os.path.exists(unrelated))

    def test_sweep_orphan_download_temp_artifacts_removes_safe_patterns(self):
        """启动清扫只处理下载器白名单临时命名，不能误删正常媒体或封面文件。"""
        base = self.temp_dir.name
        paths_to_remove = [
            os.path.join(base, "demo_video.m4s"),
            os.path.join(base, "demo_audio.m4s"),
            os.path.join(base, "demo.mp4.downloading"),
            os.path.join(base, "demo.mp4.merging"),
            os.path.join(base, ".demo.mp4.part0"),
        ]
        keep_paths = [
            os.path.join(base, "demo_cover.m4s"),
            os.path.join(base, "demo.mp4"),
        ]
        for path in paths_to_remove + keep_paths:
            with open(path, "wb") as fp:
                fp.write(b"test")

        removed = self.service.sweep_orphan_download_temp_artifacts([base])

        self.assertEqual(removed, len(paths_to_remove))
        for path in paths_to_remove:
            self.assertFalse(os.path.exists(path), path)
        for path in keep_paths:
            self.assertTrue(os.path.exists(path), path)

    def test_sweep_orphan_download_temp_artifacts_is_bounded_to_two_levels(self):
        """普通下载最多扫描两层合集目录，不能递归遍历任意用户目录。"""
        base = self.temp_dir.name
        collection_dir = os.path.join(base, "合集")
        season_dir = os.path.join(collection_dir, "分季")
        deep_dir = os.path.join(season_dir, "用户目录")
        os.mkdir(collection_dir)
        os.mkdir(season_dir)
        os.mkdir(deep_dir)
        nested_temp = os.path.join(collection_dir, "demo_audio.m4s")
        second_level_temp = os.path.join(season_dir, "demo.mp4.downloading")
        too_deep_temp = os.path.join(deep_dir, "keep.mp4.downloading")
        for path in (nested_temp, second_level_temp, too_deep_temp):
            with open(path, "wb") as fp:
                fp.write(b"test")

        removed = self.service.sweep_orphan_download_temp_artifacts([base])

        self.assertEqual(removed, 2)
        self.assertFalse(os.path.exists(nested_temp))
        self.assertFalse(os.path.exists(second_level_temp))
        self.assertTrue(os.path.exists(too_deep_temp))
        self.assertTrue(os.path.exists(collection_dir))
        self.assertTrue(os.path.exists(season_dir))
        self.assertTrue(os.path.exists(base))

    def test_single_directory_sweep_reports_children_without_recursing(self):
        base = Path(self.temp_dir.name)
        child = base / "collection"
        child.mkdir()
        root_temp = base / "root.mp4.downloading"
        child_temp = child / "child.mp4.downloading"
        root_temp.write_bytes(b"partial")
        child_temp.write_bytes(b"partial")

        result = self.service.sweep_orphan_download_temp_directory(
            base,
            depth=0,
            max_depth=2,
        )

        self.assertEqual(result.removed_count, 1)
        self.assertEqual(result.children, ((child.resolve(), 1),))
        self.assertFalse(root_temp.exists())
        self.assertTrue(child_temp.exists())

    def test_delete_media_removes_bilibili_temp_sidecars_when_final_missing(self):
        base = self.temp_dir.name
        file_path = os.path.join(base, "demo.mp4")
        video_temp = os.path.join(base, "demo_video.m4s")
        audio_temp = os.path.join(base, "demo_audio.m4s")
        for path in (video_temp, audio_temp):
            with open(path, "wb") as fp:
                fp.write(b"test")
        item = VideoItem(url="", title="demo", source="bilibili")
        item.local_path = file_path

        deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(video_temp))
        self.assertFalse(os.path.exists(audio_temp))

    def test_delete_media_removes_bilibili_sidecars_when_local_path_is_temp_stream(self):
        base = self.temp_dir.name
        video_temp = os.path.join(base, "demo_video.m4s")
        audio_temp = os.path.join(base, "demo_audio.m4s")
        for path in (video_temp, audio_temp):
            with open(path, "wb") as fp:
                fp.write(b"test")
        item = VideoItem(url="", title="demo", source="bilibili")
        item.local_path = video_temp

        deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(video_temp))
        self.assertFalse(os.path.exists(audio_temp))

    def test_delete_media_removes_bilibili_meta_temp_files_without_local_path(self):
        """失败记录没有最终 local_path 时，仍可依赖 meta 中的安全临时路径完成清理。"""
        base = self.temp_dir.name
        video_temp = os.path.join(base, "demo_video.m4s")
        audio_temp = os.path.join(base, "demo_audio.m4s")
        for path in (video_temp, audio_temp):
            with open(path, "wb") as fp:
                fp.write(b"test")
        item = VideoItem(url="", title="demo", source="bilibili")
        item.meta["download_temp_files"] = [video_temp, audio_temp]

        deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(video_temp))
        self.assertFalse(os.path.exists(audio_temp))

    def test_delete_media_ignores_unowned_temp_sidecar_path(self):
        """有最终路径时禁止跨目录删除 meta 临时文件，防止旧数据或外部输入误删用户文件。"""
        base = self.temp_dir.name
        outside_dir = os.path.join(base, "outside")
        os.mkdir(outside_dir)
        file_path = os.path.join(base, "demo.mp4")
        outside_temp = os.path.join(outside_dir, "demo_video.m4s")
        for path in (file_path, outside_temp):
            with open(path, "wb") as fp:
                fp.write(b"test")
        item = VideoItem(url="", title="demo", source="bilibili")
        item.local_path = file_path
        item.meta["download_temp_files"] = [outside_temp]

        deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(file_path))
        self.assertTrue(os.path.exists(outside_temp))

    @patch("app.services.file_service.time.sleep", return_value=None)
    def test_delete_media_retries_briefly_after_permission_error(self, _mock_sleep):
        """Windows 释放播放器句柄存在瞬时延迟时，删除应进行短暂重试。"""
        base = self.temp_dir.name
        file_path = os.path.join(base, "busy.mp4")
        with open(file_path, "wb") as fp:
            fp.write(b"test")
        item = VideoItem(url="", title="busy", source="local")
        item.local_path = file_path

        real_remove = os.remove
        attempts = {"count": 0}

        def flaky_remove(path):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise PermissionError("文件被占用")
            return real_remove(path)

        with patch("app.services.file_service.os.remove", side_effect=flaky_remove):
            deleted = self.service.delete_media(item)

        self.assertTrue(deleted)
        self.assertEqual(attempts["count"], 2)
        self.assertFalse(os.path.exists(file_path))

if __name__ == "__main__":
    unittest.main()
