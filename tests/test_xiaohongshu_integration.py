"""小红书平台接入回归测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.downloaders.xiaohongshu import XiaohongshuDownloader
from app.services.auth_service import AuthService
from app.spiders.xiaohongshu.client import XiaohongshuClient
from app.spiders.xiaohongshu.helpers import (
    build_search_id,
    parse_creator_info_from_url,
    parse_note_info_from_note_url,
)
from app.spiders.xiaohongshu.spider import XiaohongshuSpider
from app.spiders.xiaohongshu.task_builder import XiaohongshuTaskBuilder


class XiaohongshuHelperTests(unittest.TestCase):
    def test_build_search_id_returns_non_empty_token(self):
        token = build_search_id()
        self.assertTrue(token)
        self.assertIsInstance(token, str)

    def test_parse_note_info_from_note_url_extracts_id_and_tokens(self):
        info = parse_note_info_from_note_url(
            "https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8?xsec_token=demo-token&xsec_source=pc_search"
        )
        self.assertEqual(info.note_id, "66fad51c000000001b0224b8")
        self.assertEqual(info.xsec_token, "demo-token")
        self.assertEqual(info.xsec_source, "pc_search")

    def test_parse_creator_info_from_url_supports_raw_user_id(self):
        info = parse_creator_info_from_url("5eb8e1d400000000010075ae")
        self.assertEqual(info.user_id, "5eb8e1d400000000010075ae")
        self.assertEqual(info.xsec_token, "")
        self.assertEqual(info.xsec_source, "")


class XiaohongshuTaskBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = XiaohongshuTaskBuilder()

    def test_build_items_returns_video_item_for_video_note(self):
        items = self.builder.build_items(
            {
                "note_id": "note-1",
                "type": "video",
                "title": "视频笔记",
                "user": {"nickname": "作者"},
                "video_candidates": ["https://cdn.example.com/video.mp4"],
            },
            trace_id_factory=lambda suffix: f"{suffix}-trace",
            referer="https://www.xiaohongshu.com/explore/note-1",
            user_agent="ua-demo",
            cookie_str="a1=demo",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "xiaohongshu")
        self.assertEqual(items[0].meta["content_type"], "video")
        self.assertEqual(items[0].meta["folder_name"], "作者")

    def test_build_items_returns_gallery_item_for_image_note(self):
        items = self.builder.build_items(
            {
                "note_id": "note-2",
                "type": "normal",
                "title": "图文笔记",
                "user": {"nickname": "作者"},
                "images_data": [
                    {"image_url": "https://cdn.example.com/1.jpg"},
                    {"image_url": "https://cdn.example.com/2.webp"},
                ],
            },
            trace_id_factory=lambda suffix: f"{suffix}-trace",
            referer="https://www.xiaohongshu.com/explore/note-2",
            user_agent="ua-demo",
            cookie_str="a1=demo",
        )
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].meta["is_gallery"])
        self.assertEqual(items[0].meta["content_type"], "gallery")
        self.assertEqual(len(items[0].meta["images_data"]), 2)


class XiaohongshuAuthTests(unittest.TestCase):
    def test_self_info_payload_detects_logged_in_state(self):
        self.assertTrue(
            XiaohongshuClient._self_info_indicates_login(
                {"data": {"result": {"success": True}}}
            )
        )
        self.assertFalse(XiaohongshuClient._self_info_indicates_login({}))

    def test_saved_cookie_is_rejected_when_probe_confirms_guest(self):
        spider = XiaohongshuSpider("test", {})
        spider.auth_service = AuthService()
        with tempfile.TemporaryDirectory() as temp_dir:
            spider.auth_file = os.path.join(temp_dir, "xhs_auth.json")
            spider.auth_service.save_json_file(
                spider.auth_file,
                [{"name": "a1", "value": "guest-cookie"}],
            )
            with patch.object(spider, "_probe_cookie_login_status", return_value=False):
                cookie_str = spider._load_saved_cookie_string()
        self.assertEqual(cookie_str, "")
        self.assertFalse(os.path.exists(spider.auth_file))

    def test_logged_in_page_requires_profile_entry_or_session_change(self):
        spider = XiaohongshuSpider("test", {})
        spider.auth_service = AuthService()

        class _Locator:
            def __init__(self, count: int) -> None:
                self._count = count

            def count(self) -> int:
                return self._count

        class _Page:
            def __init__(self, count: int) -> None:
                self._count = count

            def locator(self, _selector: str):
                return _Locator(self._count)

        class _Context:
            def __init__(self, cookies):
                self._cookies = cookies

            def cookies(self):
                return self._cookies

        self.assertTrue(
            spider._page_shows_logged_in_state(
                _Page(1),
                context=_Context([{"name": "web_session", "value": "same"}]),
                baseline_web_session="same",
            )
        )
        self.assertTrue(
            spider._page_shows_logged_in_state(
                _Page(0),
                context=_Context([{"name": "web_session", "value": "changed"}]),
                baseline_web_session="guest",
            )
        )
        self.assertFalse(
            spider._page_shows_logged_in_state(
                _Page(0),
                context=_Context([{"name": "web_session", "value": "guest"}]),
                baseline_web_session="guest",
            )
        )


class XiaohongshuDownloaderTests(unittest.TestCase):
    @patch("app.core.downloaders.xiaohongshu.XiaohongshuDownloader._download_http_file")
    def test_gallery_download_expands_images_with_extensions(self, mocked_download_http_file):
        downloader = XiaohongshuDownloader()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "note.mp4")
            from app.models import VideoItem

            item = VideoItem(url="https://cdn.example.com/cover.jpg", title="图文", source="xiaohongshu")
            item.meta.update(
                {
                    "is_gallery": True,
                    "images_data": [
                        {"image_url": "https://cdn.example.com/1.jpg"},
                        {"image_url": "https://cdn.example.com/2.webp"},
                    ],
                    "cookie": "a1=demo",
                }
            )

            progresses: list[int] = []
            downloader.download(item, save_path, progresses.append, lambda: False)

        self.assertEqual(mocked_download_http_file.call_count, 2)
        first_path = mocked_download_http_file.call_args_list[0].kwargs["save_path"]
        second_path = mocked_download_http_file.call_args_list[1].kwargs["save_path"]
        self.assertTrue(first_path.endswith("_1.jpeg"))
        self.assertTrue(second_path.endswith("_2.webp"))
        self.assertEqual(progresses[-1], 100)


if __name__ == "__main__":
    unittest.main()
