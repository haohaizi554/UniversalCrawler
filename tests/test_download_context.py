"""DownloadContext 与 VideoItem 下载上下文桥接测试。"""

from __future__ import annotations

import unittest

from app.models.download_context import DownloadContext
from app.models.video_item import VideoItem


class DownloadContextTests(unittest.TestCase):
    def test_from_meta_normalizes_numbers_booleans_and_filename_alias(self):
        context = DownloadContext.from_meta(
            {
                "trace_id": "trace-1",
                "file_name": "合集封面",
                "duration": "12.0",
                "size_mb": "3.5",
                "is_gallery": "true",
                "is_mix": "0",
                "use_subdir": "yes",
                "cookies": {"sid": "keep"},
                "images_data": [{"url": "https://example.com/1.jpg"}],
            }
        )

        self.assertEqual(context.trace_id, "trace-1")
        self.assertEqual(context.preferred_filename, "合集封面")
        self.assertEqual(context.duration, 12)
        self.assertEqual(context.size_mb, 3.5)
        self.assertTrue(context.is_gallery)
        self.assertFalse(context.is_mix)
        self.assertTrue(context.use_subdir)
        self.assertEqual(context.cookies, {"sid": "keep"})
        self.assertEqual(context.images_data, [{"url": "https://example.com/1.jpg"}])

    def test_to_meta_patch_omits_none_and_keeps_filename_aliases(self):
        context = DownloadContext(
            trace_id="trace-2",
            preferred_filename="下载文件名",
            cookies={"sid": "keep"},
            is_gallery=True,
            use_subdir=True,
        )

        patch = context.to_meta_patch()

        self.assertEqual(patch["trace_id"], "trace-2")
        self.assertEqual(patch["preferred_filename"], "下载文件名")
        self.assertEqual(patch["file_name"], "下载文件名")
        self.assertEqual(patch["cookies"], {"sid": "keep"})
        self.assertTrue(patch["is_gallery"])
        self.assertTrue(patch["use_subdir"])
        self.assertNotIn("audio_url", patch)

    def test_video_item_build_and_merge_download_context_round_trip(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta.update(
            {
                "trace_id": "trace-3",
                "download_strategy": "http",
                "use_subdir": False,
            }
        )

        context = item.build_download_context()
        merged = item.merge_download_context(context, download_strategy="ffmpeg", use_subdir=True)

        self.assertEqual(context.trace_id, "trace-3")
        self.assertEqual(merged.download_strategy, "ffmpeg")
        self.assertTrue(merged.use_subdir)
        self.assertEqual(item.meta["download_strategy"], "ffmpeg")
        self.assertTrue(item.meta["use_subdir"])


if __name__ == "__main__":
    unittest.main()
