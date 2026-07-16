"""文件服务的扫描、删除与元数据操作测试。"""

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
