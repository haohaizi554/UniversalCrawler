import unittest

from app.core.downloaders.douyin import DouyinDownloader
from app.core.downloaders.registry import downloader_registry
from app.models import VideoItem

class DownloaderRegistryTests(unittest.TestCase):
    def test_builtin_registry_resolves_by_video_source(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        downloader_cls = downloader_registry.resolve(item)

        self.assertIs(downloader_cls, DouyinDownloader)

    def test_builtin_registry_lists_expected_sources(self):
        source_ids = {cls.source_id for cls in downloader_registry.all()}

        self.assertTrue({"douyin", "xiaohongshu", "kuaishou", "missav", "bilibili"}.issubset(source_ids))

