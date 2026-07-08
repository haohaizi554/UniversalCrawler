"""测试模块，覆盖 `tests/test_file_service.py` 对应功能的行为与回归场景。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.file_service import MediaLibraryService

class MediaLibraryServiceTests(unittest.TestCase):
    
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

    def test_delete_media_removes_bilibili_temp_sidecars(self):
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
