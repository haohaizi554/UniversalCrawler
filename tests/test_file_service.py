import os
import tempfile
import unittest

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
        missing_dir = os.path.join(self.temp_dir.name, "missing")

        result = self.service.scan_directory(missing_dir)

        self.assertTrue(os.path.isdir(missing_dir))
        self.assertEqual(result.total_count, 0)
        self.assertEqual(result.items, [])

    def test_scan_directory_marks_result_as_truncated(self):
        base = self.temp_dir.name
        for index in range(3):
            with open(os.path.join(base, f"video-{index}.mp4"), "wb") as fp:
                fp.write(b"test")

        result = self.service.scan_directory(base, max_scan_count=2)

        self.assertEqual(result.total_count, 2)
        self.assertTrue(result.truncated)
        self.assertEqual(result.original_count, 3)

    def test_rename_media_rejects_conflicting_name(self):
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

    def test_delete_media_returns_false_for_missing_path(self):
        item = VideoItem(url="", title="missing", source="local")
        item.local_path = os.path.join(self.temp_dir.name, "missing.mp4")

        self.assertFalse(self.service.delete_media(item))


if __name__ == "__main__":
    unittest.main()
