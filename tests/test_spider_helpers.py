"""测试模块，覆盖 `tests/test_spider_helpers.py` 对应功能的行为与回归场景。"""

import asyncio
import os
import queue
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from urllib.parse import quote

import requests
from playwright.sync_api import Error as PlaywrightError

from app.config import DEFAULT_USER_AGENT
from app.models import VideoItem
from app.debug_logger import get_debug_logger
from app.exceptions import InvalidCookieStateError, LoginCancelledError, LoginCheckError, SpiderAuthError, SpiderParseError
from app.exceptions import StreamResolveError
from app.core.lib.douyin.interface.live import Live
from app.core.lib.douyin.interface.template import API, APITikTok, CHROME_VERSION
from app.services.auth_service import AuthService
from app.spiders.bilibili.spider import BiliAPI
from app.spiders.bilibili.spider import BilibiliSpider
from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.bilibili.task_builder import BilibiliTaskBuilder
from app.spiders import parser_cache
from app.utils.bilibili_wbi import BILIBILI_WBI_SIGNER, make_mixin_key, sign_wbi_params
from app.spiders.douyin.parser import DouyinItemParser
from app.spiders.douyin.spider import DouyinSpider
from app.spiders.douyin.task_builder import DouyinTaskBuilder
from app.spiders.kuaishou.spider import KuaishouSpider
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.spiders.missav.spider import MissAVSpider
from app.spiders.missav.task_builder import MissAVTaskBuilder
from app.spiders.missav.parser import MissAVParser
from app.spiders.xiaohongshu.spider import XiaohongshuSpider
from app.spiders.base import BaseSpider

class SpiderHelperTests(unittest.TestCase):
    
    def test_bili_api_snapshots_cookies_under_session_lock(self):
        api = BiliAPI.__new__(BiliAPI)
        api.sess = requests.Session()
        api._session_lock = threading.RLock()
        api.sess.cookies.set("SESSDATA", "abc", domain=".bilibili.com")

        with api._session_guard():
            snapshot = api.snapshot_cookies()

        self.assertEqual(snapshot, {"SESSDATA": "abc"})

    def test_bili_api_get_video_info_records_nonzero_api_error(self):
        api = self._make_bili_api()
        response = Mock(status_code=200)
        response.json.return_value = {"code": 62002, "message": "稿件不可见", "ttl": 1}
        api.sess.get.return_value = response

        result = api.get_video_info("BV19nRWBtEnF")

        self.assertIsNone(result)
        self.assertEqual(
            api.consume_video_info_error("BV19nRWBtEnF"),
            {"code": 62002, "message": "稿件不可见", "http_status": 200},
        )

    def test_base_spider_configured_timeout_migrates_legacy_short_values(self):
        spider = BaseSpider.__new__(BaseSpider)
        spider.config = {"timeout": 10}

        self.assertEqual(spider._configured_timeout_seconds(default=60), 60)
        self.assertEqual(spider._configured_timeout_ms(default=60), 60000)

    def test_builtin_spiders_mark_not_running_before_finish_signal(self):
        for spider_cls in (BilibiliSpider, DouyinSpider, KuaishouSpider, MissAVSpider, XiaohongshuSpider):
            with self.subTest(spider=spider_cls.__name__):
                names = set(spider_cls.run.__code__.co_names)
                self.assertIn("_emit_finished", names)
                self.assertNotIn("sig_finished", names)

    def _make_douyin_spider(self, keyword: str) -> DouyinSpider:
        """提供 `_make_douyin_spider` 对应的内部辅助逻辑，供 `SpiderHelperTests` 使用。"""
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.keyword = keyword
        spider.config = {}
        spider.is_running = True
        spider.log = Mock()
        spider.debug_state = Mock()
        spider._process_user = AsyncMock()
        spider._process_user_search = AsyncMock()
        spider._process_search = AsyncMock()
        spider._process_mix = AsyncMock()
        spider._process_detail = AsyncMock()
        return spider

    def _make_bili_api(self) -> BiliAPI:
        """提供 `_make_bili_api` 对应的内部辅助逻辑，供 `SpiderHelperTests` 使用。"""
        BILIBILI_WBI_SIGNER.set_keys(
            "7cd084941338484aae1ad9425b84077c",
            "4932caff0ff746eab6f01bf08b70ac45",
        )
        api = BiliAPI.__new__(BiliAPI)
        api.sess = Mock()
        api.cookie_path = "bili_auth.json"
        api.parser = BilibiliParser()
        api.auth_service = Mock(spec=AuthService)
        return api

    def _make_bilibili_spider(self) -> BilibiliSpider:
        """提供 `_make_bilibili_spider` 对应的内部辅助逻辑，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.config = {}
        spider.log = Mock()
        spider.debug_state = Mock()
        spider.emit_video = Mock()
        spider.api = Mock()
        spider.api.sess = SimpleNamespace(cookies=[])
        return spider

    def _make_kuaishou_capture_spider(self) -> KuaishouSpider:
        """提供 `_make_kuaishou_capture_spider` 对应的内部辅助逻辑，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = True
        spider._selected_indices = [0]
        spider._lock = threading.Lock()
        spider.parser = Mock()
        spider.parser.extract_all_possible_ids.return_value = {"cache-1"}
        spider.task_builder = Mock()
        spider.task_builder.build_download_meta.return_value = {"trace_id": "ks-trace-1"}
        spider.new_trace_id = Mock(return_value="ks-trace-1")
        spider.config = {}
        spider.emit_video = Mock()
        spider.log = Mock()
        spider.debug_state = Mock()
        return spider

    def _make_kuaishou_capture_page(self):
        """提供 `_make_kuaishou_capture_page` 对应的内部辅助逻辑，供 `SpiderHelperTests` 使用。"""
        class FakeLocator:
            
            def __init__(self, visible=True):
                """初始化当前实例并准备运行所需的状态，供 `FakeLocator` 使用。"""
                self._visible = visible
                self.first = self

            def is_visible(self):
                
                return self._visible

            def scroll_into_view_if_needed(self):
                
                return None

            def click(self):
                
                return None

        class FakeKeyboard:
            
            def __init__(self, trigger_response):
                """初始化当前实例并准备运行所需的状态，供 `FakeKeyboard` 使用。"""
                self._trigger_response = trigger_response

            def press(self, _key):
                
                self._trigger_response()

        class FakePage:
            
            def __init__(self):
                """初始化当前实例并准备运行所需的状态，供 `FakePage` 使用。"""
                self.url = "https://www.kuaishou.com/profile/demo"
                self.response_handler = None
                self.context = SimpleNamespace(pages=[self])
                self.mouse = SimpleNamespace(click=lambda *_args, **_kwargs: None)
                self.keyboard = FakeKeyboard(self._trigger_response)

            def on(self, event, handler):
                
                if event == "response":
                    self.response_handler = handler

            def evaluate(self, _script):
                
                return None

            def wait_for_timeout(self, _ms):
                
                return None

            def locator(self, selector):
                
                if selector == ".photo-card, .video-card":
                    return FakeLocator(True)
                if selector == ".close-icon":
                    return FakeLocator(False)
                raise AssertionError(f"unexpected selector: {selector}")

            def _trigger_response(self):
                """提供 `_trigger_response` 对应的内部辅助逻辑，供 `FakePage` 使用。"""
                if not self.response_handler:
                    return
                response = SimpleNamespace(
                    url="https://video.example.com/live.mp4?clientCacheKey=cache-1",
                    headers={"content-type": "video/mp4", "content-length": "6000"},
                    request=SimpleNamespace(resource_type="media"),
                )
                self.response_handler(response)

        return FakePage()

    def test_bilibili_parser_parses_video_info_response(self):
        """验证 `test_bilibili_parser_parses_video_info_response` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = BilibiliParser()
        result = parser.parse_video_info_response(
            {
                "bvid": "BV1xx",
                "title": "demo",
                "owner": {"name": "tester"},
                "pages": [{"part": "P1", "cid": 123, "page": 1}],
            }
        )
        self.assertEqual(result["bvid"], "BV1xx")
        self.assertEqual(len(result["episodes"]), 1)

    def test_spider_parser_cache_persists_structured_results(self):
        class FakeCacheService:
            def __init__(self, **_kwargs):
                self.values = {}
                self.set_calls = []

            def get(self, key, default=None):
                return self.values.get(key, default)

            def set(self, key, value, *, ttl_seconds=None, persist=False):
                self.values[key] = value
                self.set_calls.append(
                    {"key": key, "value": value, "ttl_seconds": ttl_seconds, "persist": persist}
                )

        cache = FakeCacheService()
        parser_cache._PARSER_CACHE_SERVICE = None
        payload = {
            "bvid": "BVcache",
            "title": "demo",
            "owner": {"name": "tester"},
            "pages": [{"part": "P1", "cid": 123, "page": 1}],
        }

        try:
            with patch("app.spiders.parser_cache.CacheService", return_value=cache):
                parser = BilibiliParser()
                first = parser.parse_video_info_response(payload)
                with patch.object(parser, "_parse_video_info_response_uncached") as uncached:
                    second = parser.parse_video_info_response(payload)

            self.assertEqual(first, second)
            self.assertEqual(len(cache.set_calls), 1)
            self.assertTrue(cache.set_calls[0]["persist"])
            uncached.assert_not_called()
        finally:
            parser_cache._PARSER_CACHE_SERVICE = None

    def test_bilibili_wbi_signer_matches_media_crawler_algorithm(self):
        img_key = "7cd084941338484aae1ad9425b84077c"
        sub_key = "4932caff0ff746eab6f01bf08b70ac45"

        signed = sign_wbi_params(
            {"foo": "114", "bar": "514", "baz": "1919810"},
            img_key,
            sub_key,
            now=1700000000,
        )

        self.assertEqual(make_mixin_key(img_key, sub_key), "ea1db124af3c7062474693fa704f4ff8")
        self.assertEqual(signed["wts"], "1700000000")
        self.assertEqual(signed["w_rid"], "efcb2ff452f5bc617792e9bc1c092c4f")

    def test_bilibili_parser_rejects_incomplete_video_info(self):
        """验证 `test_bilibili_parser_rejects_incomplete_video_info` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = BilibiliParser()

        with self.assertRaises(SpiderParseError):
            parser.parse_video_info_response({"title": "demo"})

    def test_bilibili_parser_parses_ugc_season_sections(self):
        """验证 `test_bilibili_parser_parses_ugc_season_sections` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = BilibiliParser()

        result = parser.parse_video_info_response(
            {
                "bvid": "BV1base",
                "title": "合集标题",
                "owner": {"name": "up"},
                "ugc_season": {
                    "id": 2024,
                    "title": "合集",
                    "sections": [
                        {
                            "episodes": [
                                {"title": "P1", "bvid": "BV1ep1", "cid": 101},
                                {"title": "P2", "bvid": "BV1ep2", "cid": 102},
                            ]
                        },
                        {"episodes": [{"title": "P3", "bvid": "BV1ep3", "cid": 103}]},
                    ],
                },
            }
        )

        self.assertTrue(result["is_season"])
        self.assertEqual(result["season_id"], 2024)
        self.assertEqual([episode["page_num"] for episode in result["episodes"]], [1, 2, 3])
        self.assertEqual(result["episodes"][2]["bvid"], "BV1ep3")

    def test_bilibili_parser_parse_play_url_response_handles_audio_and_quality(self):
        """验证 `test_bilibili_parser_parse_play_url_response_handles_audio_and_quality` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = BilibiliParser()

        result = parser.parse_play_url_response(
            {
                "code": 0,
                "data": {
                    "dash": {
                        "video": [{"baseUrl": "https://cdn.example.com/video.m4s", "id": 80}],
                        "audio": [{"baseUrl": "https://cdn.example.com/audio.m4s"}],
                    }
                },
            }
        )

        self.assertEqual(
            result,
            ("https://cdn.example.com/video.m4s", "https://cdn.example.com/audio.m4s", 80),
        )

    def test_bilibili_spider_formats_second_stage_choice_with_parent_context(self):
        """第二层候选必须带父级标题，避免终端只显示裸 `[01] 标题`。"""
        title = BilibiliSpider._format_episode_choice(
            "sunny77小合集",
            {"page_num": 3, "title": "我的好利来女友"},
            2,
        )
        self.assertEqual(title, "sunny77小合集 · P03 · 我的好利来女友")

    def test_bilibili_parser_parse_play_url_response_allows_missing_audio(self):
        """验证 `test_bilibili_parser_parse_play_url_response_allows_missing_audio` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = BilibiliParser()

        result = parser.parse_play_url_response(
            {
                "code": 0,
                "data": {
                    "dash": {
                        "video": [{"baseUrl": "https://cdn.example.com/video.m4s", "id": 64}],
                        "audio": [],
                    }
                },
            }
        )

        self.assertEqual(result, ("https://cdn.example.com/video.m4s", None, 64))

    def test_bilibili_parser_parse_play_url_response_raises_on_incomplete_payload(self):
        """验证 `test_bilibili_parser_parse_play_url_response_raises_on_incomplete_payload` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = BilibiliParser()

        with self.assertRaises(SpiderParseError):
            parser.parse_play_url_response({"code": 0, "data": {"dash": {"video": [{}]}}})

    def test_bilibili_parser_clean_name_replaces_invalid_characters(self):
        """验证 `test_bilibili_parser_clean_name_replaces_invalid_characters` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        self.assertEqual(BilibiliParser.clean_name('bad:/name?*"<>|'), "bad__name______")

    def test_douyin_parser_returns_video_item_for_standard_aweme(self):
        """验证 `test_douyin_parser_returns_video_item_for_standard_aweme` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = DouyinItemParser()

        item = parser.parse_aweme(
            {
                "aweme_id": "1001",
                "desc": "测试视频",
                "create_time": 1700000000,
                "author": {"nickname": "作者A"},
                "video": {
                    "duration": 12345,
                    "play_addr": {"url_list": ["https://cdn.example.com/low.mp4", "https://cdn.example.com/high.mp4"]},
                },
            }
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://cdn.example.com/high.mp4")
        self.assertEqual(item.meta["content_type"], "video")
        self.assertEqual(item.meta["duration"], 12)
        self.assertEqual(item.meta["folder_name"], "作者A")

    def test_douyin_parser_prefers_best_bit_rate_url_over_play_addr(self):
        parser = DouyinItemParser()

        item = parser.parse_aweme(
            {
                "aweme_id": "1001",
                "desc": "bitrate video",
                "author": {"nickname": "author"},
                "video": {
                    "duration": 12345,
                    "play_addr": {"url_list": ["https://cdn.example.com/fallback.mp4"]},
                    "bit_rate": [
                        {
                            "FPS": 30,
                            "bit_rate": 1000,
                            "play_addr": {
                                "data_size": 10,
                                "height": 720,
                                "width": 1280,
                                "url_list": [
                                    "https://cdn.example.com/low-first.mp4",
                                    "https://cdn.example.com/low-last.mp4",
                                ],
                            },
                        },
                        {
                            "FPS": 60,
                            "bit_rate": 5000,
                            "play_addr": {
                                "data_size": 20,
                                "height": 1080,
                                "width": 1920,
                                "url_list": [
                                    "https://cdn.example.com/high-first.mp4",
                                    "https://cdn.example.com/high-last.mp4",
                                ],
                            },
                        },
                    ],
                },
            }
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://cdn.example.com/high-last.mp4")

    def test_douyin_parser_returns_gallery_item_for_live_photo_aweme(self):
        """验证 `test_douyin_parser_returns_gallery_item_for_live_photo_aweme` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = DouyinItemParser()

        item = parser.parse_aweme(
            {
                "aweme_id": "1002",
                "desc": "实况图集",
                "author": {"nickname": "作者B"},
                "images": [
                    {
                        "clip_type": 2,
                        "url_list": ["https://cdn.example.com/cover.jpg", "https://cdn.example.com/cover~noop.jpg"],
                    },
                    {
                        "clip_type": 3,
                        "url_list": ["https://cdn.example.com/photo.webp"],
                        "video": {
                            "play_addr_h264": {
                                "url_list": ["https://cdn.example.com/live-low.mp4", "https://cdn.example.com/live-high.mp4"]
                            }
                        },
                    },
                ],
            }
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.meta["content_type"], "gallery")
        self.assertTrue(item.meta["has_live_photo"])
        self.assertEqual(item.meta["media_label"], "实况")
        self.assertEqual(item.url, "https://cdn.example.com/cover~noop.jpg")
        self.assertEqual(item.meta["images_data"][1]["live_video_url"], "https://cdn.example.com/live-high.mp4")

    def test_douyin_parser_filters_mp3_and_returns_none_without_gallery(self):
        """验证 `test_douyin_parser_filters_mp3_and_returns_none_without_gallery` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = DouyinItemParser()

        item = parser.parse_aweme(
            {
                "aweme_id": "1003",
                "desc": "音频资源",
                "video": {"play_addr": {"url_list": ["https://cdn.example.com/demo.mp3"]}},
            }
        )

        self.assertIsNone(item)

    @patch("app.spiders.douyin.parser.debug_logger.log_exception")
    def test_douyin_parser_returns_none_for_invalid_payload_shape(self, mocked_log_exception):
        """验证 `test_douyin_parser_returns_none_for_invalid_payload_shape` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = DouyinItemParser()

        self.assertIsNone(parser.parse_aweme({"video": None}))
        mocked_log_exception.assert_called_once()
        self.assertEqual(mocked_log_exception.call_args.args[:2], ("DouyinItemParser", "parse_aweme"))

    def test_douyin_parser_summarize_aweme_extracts_core_fields(self):
        """验证 `test_douyin_parser_summarize_aweme_extracts_core_fields` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = DouyinItemParser()

        summary = parser.summarize_aweme(
            {
                "aweme_id": "1004",
                "desc": "摘要测试",
                "aweme_type": 68,
                "author": {"nickname": "作者C"},
                "video": {"play_addr": {"url_list": ["https://cdn.example.com/demo.mp4"]}, "duration": 9876},
                "images": [{"clip_type": 3}, {"clip_type": 2}],
            }
        )

        self.assertEqual(summary["aweme_id"], "1004")
        self.assertEqual(summary["author"], "作者C")
        self.assertTrue(summary["has_video"])
        self.assertEqual(summary["duration_ms"], 9876)
        self.assertEqual(summary["image_count"], 2)
        self.assertTrue(summary["has_live_photo"])

    def test_douyin_task_builder_splits_gallery(self):
        """验证 `test_douyin_task_builder_splits_gallery` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        item = VideoItem(url="https://example.com/1.jpg", title="demo", source="douyin")
        item.meta = {
            "trace_id": "dy-1",
            "is_gallery": True,
            "images_data": [
                {"image_url": "https://example.com/1.jpg", "live_video_url": "", "clip_type": 2},
                {"image_url": "", "live_video_url": "https://example.com/2.mp4", "clip_type": 3},
            ],
        }
        builder = DouyinTaskBuilder()
        result = builder.build_items(item, lambda prefix: f"{prefix}-new")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].meta["content_type"], "image")
        self.assertEqual(result[1].meta["content_type"], "video")

    def test_douyin_normalize_user_search_items_flattens_nested_lists(self):
        """验证 `test_douyin_normalize_user_search_items_flattens_nested_lists` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = DouyinSpider.__new__(DouyinSpider)

        result = spider._normalize_user_search_items(
            [
                [{"user_info": {"nickname": "A"}}],
                {"user_info": {"nickname": "B"}},
                "ignored",
            ]
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["user_info"]["nickname"], "A")
        self.assertEqual(result[1]["user_info"]["nickname"], "B")

    @patch("app.spiders.douyin.spider.debug_logger.log_exception")
    @patch("app.core.lib.douyin.interface.search.Search")
    def test_douyin_user_search_exception_is_structured_log(self, mock_search_class, mocked_log_exception):
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.log = Mock()
        search = Mock()
        search.run = AsyncMock(side_effect=RuntimeError("search boom"))
        mock_search_class.return_value = search

        asyncio.run(spider._process_user_search(SimpleNamespace(), "testuser"))

        mocked_log_exception.assert_called_once()
        self.assertEqual(mocked_log_exception.call_args.args[:2], ("DouyinSpider", "user_search"))
        self.assertEqual(mocked_log_exception.call_args.kwargs["details"], {"user_id": "testuser"})

    def test_kuaishou_parser_extracts_cache_key(self):
        """验证 `test_kuaishou_parser_extracts_cache_key` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = KuaishouParser()
        ids = parser.extract_all_possible_ids("https://example.com/video.mp4?clientCacheKey=abc123.mp4")
        self.assertIn("abc123", ids)

    def test_missav_parser_injects_individual_filter(self):
        """验证 `test_missav_parser_injects_individual_filter` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = MissAVParser()
        url = parser.inject_url_params("https://missav.ai/cn/search/ipx-001", individual_only=True)
        self.assertIn("individual", url)

    def test_missav_normalize_keyword_extracts_url_from_share_text(self):
        spider = MissAVSpider.__new__(MissAVSpider)

        normalized = spider._normalize_keyword(
            "复制分享打开 MissAV https://missav.ai/cn/start-581-chinese-subtitle，马上看"
        )

        self.assertEqual(normalized, "https://missav.ai/cn/start-581-chinese-subtitle")

    def test_missav_normalize_keyword_adds_scheme_for_bare_url(self):
        spider = MissAVSpider.__new__(MissAVSpider)

        normalized = spider._normalize_keyword("www.missav.ai/cn/ipx-001。")

        self.assertEqual(normalized, "https://www.missav.ai/cn/ipx-001")

    def test_missav_normalize_keyword_preserves_plain_keyword(self):
        spider = MissAVSpider.__new__(MissAVSpider)

        self.assertEqual(spider._normalize_keyword("ipx-001"), "ipx-001")

    def test_kuaishou_task_builder_builds_standard_download_meta(self):
        """验证 `test_kuaishou_task_builder_builds_standard_download_meta` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        builder = KuaishouTaskBuilder()
        meta = builder.build_download_meta("trace-1", "https://www.kuaishou.com/", "https://cdn.example.com/live.m3u8")

        self.assertEqual(meta["trace_id"], "trace-1")
        self.assertEqual(meta["referer"], "https://www.kuaishou.com/")
        self.assertEqual(meta["download_strategy"], "m3u8")

    def test_missav_hls_playlist_detector_requires_extm3u(self):
        self.assertTrue(MissAVSpider._looks_like_hls_playlist("#EXTM3U\n#EXT-X-VERSION:3"))
        self.assertFalse(MissAVSpider._looks_like_hls_playlist(""))
        self.assertFalse(MissAVSpider._looks_like_hls_playlist("Forbidden"))

    def test_missav_page_and_player_wait_budgets_are_not_too_short(self):
        self.assertGreaterEqual(MissAVSpider.GRID_READY_TIMEOUT_MS, 30000)
        self.assertGreaterEqual(MissAVSpider.PLAYER_READY_TIMEOUT_MS, 30000)
        self.assertGreaterEqual(MissAVSpider.M3U8_SNIFF_SECONDS, 45)

    def test_missav_task_builder_keeps_compat_alias(self):
        """验证 `test_missav_task_builder_keeps_compat_alias` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        builder = MissAVTaskBuilder()
        headers = {"Cookie": "sid=abc", "Origin": "https://missav.ai"}
        storage_state = {"cookies": [{"name": "sid", "value": "abc", "domain": "surrit.com"}], "origins": []}
        playlist_cache = {"https://surrit.com/demo/playlist.m3u8": "#EXTM3U"}
        new_meta = builder.build_download_meta(
            "trace-2",
            "https://missav.ai",
            "ua-demo",
            "http://127.0.0.1:7890",
            headers=headers,
            cookie="sid=abc",
            include_cookies=True,
            use_browser_headers=True,
            browser_storage_state=storage_state,
            playlist_cache=playlist_cache,
        )
        old_meta = builder.build_video_meta(
            "trace-2",
            "https://missav.ai",
            "ua-demo",
            "http://127.0.0.1:7890",
            headers=headers,
            cookie="sid=abc",
            include_cookies=True,
            use_browser_headers=True,
            browser_storage_state=storage_state,
            playlist_cache=playlist_cache,
        )

        self.assertEqual(new_meta, old_meta)
        self.assertEqual(new_meta["ua"], "ua-demo")
        self.assertEqual(new_meta["headers"], headers)
        self.assertEqual(new_meta["cookie"], "sid=abc")
        self.assertEqual(new_meta["m3u8_thread_count"], 16)
        self.assertTrue(new_meta["missav_include_cookies"])
        self.assertTrue(new_meta["missav_use_browser_headers"])
        self.assertEqual(new_meta["browser_storage_state"], storage_state)
        self.assertEqual(new_meta["playlist_cache"], playlist_cache)

    def test_bilibili_task_builder_reuses_standard_meta_layout(self):
        """验证 `test_bilibili_task_builder_reuses_standard_meta_layout` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        builder = BilibiliTaskBuilder(BilibiliParser())
        task = builder.build_single_task(
            {"bvid": "BV1xx", "cid": 123, "title": "正片"},
            referer="https://www.bilibili.com/video/BV1xx",
            video_title="演示主标题",
        )

        self.assertEqual(task["trace_id"], "bilibili_BV1xx_123")
        self.assertEqual(task["bvid"], "BV1xx")
        self.assertEqual(task["file_name"], "演示主标题.mp4")

    def test_bilibili_task_builder_single_task_falls_back_to_part_title(self):
        builder = BilibiliTaskBuilder(BilibiliParser())
        task = builder.build_single_task(
            {"bvid": "BV1xx", "cid": 123, "title": "分P标题"},
            referer="https://www.bilibili.com/video/BV1xx",
        )
        self.assertEqual(task["file_name"], "分P标题.mp4")

    def test_bilibili_task_builder_episode_task_uses_page_prefix_and_folder(self):
        builder = BilibiliTaskBuilder(BilibiliParser())
        task = builder.build_episode_task(
            {"title": "合集主标题", "season_title": "合集主标题"},
            {"bvid": "BV1xx", "cid": 123, "title": "第二话", "page_num": 2},
            1,
        )
        self.assertEqual(task["folder_name"], "合集主标题")
        self.assertEqual(task["file_name"], "P02_第二话.mp4")

    def test_bili_api_get_video_info_supports_legacy_aid_lookup(self):
        api = self._make_bili_api()
        response = Mock(status_code=200)
        response.json.return_value = {
            "code": 0,
            "data": {
                "bvid": "BVfromAid",
                "title": "demo",
                "owner": {"name": "up"},
                "pages": [{"part": "P1", "cid": 123, "page": 1}],
            },
        }
        api.sess.get.return_value = response

        result = api.get_video_info(None, trace_id="trace-aid", aid=123456)

        self.assertEqual(result["bvid"], "BVfromAid")
        self.assertEqual(api.sess.get.call_args.args[0], "https://api.bilibili.com/x/web-interface/view")
        params = api.sess.get.call_args.kwargs["params"]
        self.assertEqual(params["aid"], "123456")
        self.assertIn("wts", params)
        self.assertIn("w_rid", params)

    def test_bili_api_get_video_info_retries_unsigned_when_signed_detail_fails(self):
        api = self._make_bili_api()
        signed_response = Mock(status_code=200)
        signed_response.json.return_value = {"code": -400, "message": "invalid signature"}
        unsigned_response = Mock(status_code=200)
        unsigned_response.json.return_value = {
            "code": 0,
            "data": {
                "bvid": "BVunsigned",
                "title": "demo",
                "owner": {"name": "up"},
                "pages": [{"part": "P1", "cid": 123, "page": 1}],
            },
        }
        api.sess.get.side_effect = [signed_response, unsigned_response]

        result = api.get_video_info("BVunsigned", trace_id="trace-detail")

        self.assertEqual(result["bvid"], "BVunsigned")
        first_params = api.sess.get.call_args_list[0].kwargs["params"]
        second_params = api.sess.get.call_args_list[1].kwargs["params"]
        self.assertEqual(first_params["bvid"], "BVunsigned")
        self.assertIn("wts", first_params)
        self.assertIn("w_rid", first_params)
        self.assertEqual(second_params, {"bvid": "BVunsigned"})

    def test_bili_api_load_cookies_rejects_invalid_payload_shape(self):
        """验证 `test_bili_api_load_cookies_rejects_invalid_payload_shape` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        api = BiliAPI.__new__(BiliAPI)
        api.sess = Mock()
        api.cookie_path = "bili_auth.json"
        api.parser = BilibiliParser()
        api.auth_service = Mock(spec=AuthService)
        api.auth_service.load_json_file.return_value = {"cookies": "bad-shape"}
        api.auth_service.extract_cookie_dict.return_value = {}

        with self.assertRaises(InvalidCookieStateError):
            api.load_cookies()

    def test_bili_api_check_login_raises_login_check_error_on_request_failure(self):
        """验证 `test_bili_api_check_login_raises_login_check_error_on_request_failure` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        api = BiliAPI.__new__(BiliAPI)
        api.sess = Mock()
        api.cookie_path = "bili_auth.json"
        api.parser = BilibiliParser()
        api.auth_service = Mock(spec=AuthService)
        api.sess.get.side_effect = requests.RequestException("boom")

        with self.assertRaises(LoginCheckError):
            api.check_login()

    def test_bili_api_get_play_url_falls_back_to_legacy_fnval_mode(self):
        """验证 `test_bili_api_get_play_url_falls_back_to_legacy_fnval_mode` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        api = self._make_bili_api()
        first_response = Mock(status_code=200)
        first_response.json.return_value = {"code": 0, "data": {}}
        second_response = Mock(status_code=200)
        second_response.json.return_value = {
            "code": 0,
            "data": {
                "dash": {
                    "video": [{"baseUrl": "https://video.example.com/v.mp4", "id": 80}],
                    "audio": [{"baseUrl": "https://video.example.com/a.m4a"}],
                }
            },
        }
        api.sess.get.side_effect = [first_response, second_response]

        video_url, audio_url, quality_id = api.get_play_url("BV1demo", 123)

        self.assertEqual(video_url, "https://video.example.com/v.mp4")
        self.assertEqual(audio_url, "https://video.example.com/a.m4a")
        self.assertEqual(quality_id, 80)
        first_params = api.sess.get.call_args_list[0].kwargs["params"]
        second_params = api.sess.get.call_args_list[1].kwargs["params"]
        self.assertEqual(first_params["fnval"], "4048")
        self.assertEqual(second_params["fnval"], "80")
        self.assertIn("w_rid", first_params)
        self.assertIn("w_rid", second_params)

    def test_bili_api_get_play_url_raises_when_both_modes_fail(self):
        """验证 `test_bili_api_get_play_url_raises_when_both_modes_fail` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        api = self._make_bili_api()
        first_response = Mock(status_code=200)
        first_response.json.return_value = {"code": -404, "message": "not found"}
        second_response = Mock(status_code=200)
        second_response.json.return_value = {"code": -500, "message": "failed"}
        api.sess.get.side_effect = [first_response, second_response]

        with self.assertRaises(StreamResolveError):
            api.get_play_url("BV1demo", 123)

    def test_bilibili_spider_overrides_base_run(self):
        """BilibiliSpider 必须实现自己的 run，而不是回落到 BaseSpider.run。"""
        self.assertIsNot(BilibiliSpider.run, BaseSpider.run)

    def test_bilibili_join_worker_thread_uses_timeout_and_warns_on_hang(self):
        """后台线程未退出时，join 必须带超时并记录告警，避免 stop 卡死。"""
        spider = self._make_bilibili_spider()
        worker = Mock()
        worker.is_alive.return_value = True

        spider._join_worker_thread(worker, "browser", timeout=1.0)

        worker.join.assert_called_once_with(timeout=1.0)
        spider.log.assert_called_once()
        self.assertIn("browser 线程未在 1s 内退出", spider.log.call_args.args[0])

    def test_bilibili_run_finally_joins_worker_threads(self):
        import inspect

        source = inspect.getsource(BilibiliSpider.run)
        self.assertIn("_join_worker_thread(self._browser_thread", source)
        self.assertIn("_join_worker_thread(self._api_pool_thread", source)

    def test_bilibili_pipeline_does_not_depend_on_queue_empty_for_shutdown(self):
        import inspect

        run_source = inspect.getsource(BilibiliSpider.run)
        api_worker_source = inspect.getsource(BilibiliSpider._worker_api_pool)

        self.assertNotIn("parsed_info_queue.empty()", run_source)
        self.assertNotIn("raw_bv_queue.empty()", api_worker_source)

    @patch("app.spiders.bilibili.spider.BiliAPI")
    def test_bilibili_run_reports_stopped_instead_of_no_valid_videos(self, mocked_api_cls):
        spider = BilibiliSpider("BV19nRWBtEnF", {})
        spider.log = Mock()
        spider.debug_state = Mock()
        spider.sig_finished = Mock()
        api = Mock()
        api.check_login.return_value = True
        mocked_api_cls.return_value = api

        def producer():
            spider.is_running = False
            spider.browser_finished.set()

        def api_worker():
            spider.api_pool_finished.set()

        spider._producer_browser_task = producer
        spider._worker_api_pool = api_worker

        spider.run()

        messages = [str(call.args[0]) for call in spider.log.call_args_list]
        self.assertTrue(any("爬虫已停止" in message for message in messages))
        self.assertFalse(any("未找到任何有效视频" in message for message in messages))

    def test_bilibili_api_worker_logs_empty_api_result(self):
        spider = self._make_bilibili_spider()
        spider.raw_bv_queue = queue.Queue()
        spider.raw_bv_queue.put("BV19nRWBtEnF")
        spider.parsed_info_queue = queue.Queue()
        spider.browser_finished = threading.Event()
        spider.browser_finished.set()
        spider.api_pool_finished = threading.Event()
        spider.api.get_video_info.return_value = None

        spider._worker_api_pool()

        self.assertTrue(spider.api_pool_finished.is_set())
        self.assertTrue(spider.parsed_info_queue.empty())
        self.assertTrue(any("BV19nRWBtEnF" in str(call.args[0]) for call in spider.log.call_args_list))

    def test_bilibili_api_worker_logs_nonzero_api_code(self):
        spider = self._make_bilibili_spider()
        spider.raw_bv_queue = queue.Queue()
        spider.raw_bv_queue.put("BV19nRWBtEnF")
        spider.parsed_info_queue = queue.Queue()
        spider.browser_finished = threading.Event()
        spider.browser_finished.set()
        spider.api_pool_finished = threading.Event()
        spider.api.get_video_info.return_value = None
        spider.api.consume_video_info_error.return_value = {"code": 62002, "message": "稿件不可见"}

        spider._worker_api_pool()

        messages = [str(call.args[0]) for call in spider.log.call_args_list]
        self.assertTrue(any("code=62002" in message and "稿件不可见" in message for message in messages))

    @patch("app.spiders.bilibili.spider.sync_playwright")
    def test_bilibili_scan_registers_playwright_browser_for_stop(self, mocked_sync_playwright):
        """扫描线程创建的 browser 必须暴露给 BaseSpider.stop()，便于强制打断。"""
        spider = self._make_bilibili_spider()
        spider.config = {"timeout": 90}
        spider.is_running = True
        spider.raw_bv_queue = Mock()
        browser = Mock()

        class FakePage:
            def goto(self, *_args, **kwargs):
                self.asserted = spider._playwright_browser is browser
                self.goto_timeout = kwargs.get("timeout")

            def wait_for_load_state(self, *_args, **_kwargs):
                return None

            def evaluate(self, *_args, **_kwargs):
                return None

        page = FakePage()
        context = Mock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        mocked_sync_playwright.return_value.__enter__.return_value = playwright
        mocked_sync_playwright.return_value.__exit__.return_value = None

        spider._scan_with_browser_queue("https://www.bilibili.com/video/BV1demo", max_pages=0)

        self.assertTrue(getattr(page, "asserted", False))
        self.assertEqual(page.goto_timeout, 90000)
        context.add_init_script.assert_called_once()
        browser.close.assert_called_once()
        self.assertIsNone(spider._playwright_browser)

    @patch("app.spiders.bilibili.spider.sync_playwright")
    def test_bilibili_login_scan_cancel_message_is_readable(self, mocked_sync_playwright):
        spider = self._make_bilibili_spider()
        spider.config = {"timeout": 90}
        spider.is_running = True
        spider.interruptible_playwright_goto = Mock(return_value=False)
        browser = Mock()
        context = Mock()
        page = Mock()
        browser.new_context.return_value = context
        context.new_page.return_value = page
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        mocked_sync_playwright.return_value.__enter__.return_value = playwright
        mocked_sync_playwright.return_value.__exit__.return_value = None

        with self.assertRaises(LoginCancelledError) as raised:
            spider._perform_login_scan("bili_auth.json")

        self.assertIn("用户在登录过程中终止任务", str(raised.exception))
        browser.close.assert_called_once()
        self.assertIsNone(spider._playwright_browser)

    def test_base_spider_debug_state_accepts_level(self):
        """BaseSpider.debug_state 必须兼容 level 参数，避免单条失败把线程打崩。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        logger = get_debug_logger()

        with patch.object(logger, "log") as mocked_log:
            BaseSpider.debug_state(
                spider,
                action="resolve_stream_failed",
                message="日志级别兼容验证",
                status_code="TEST",
                context={"trace_id": "trace-1"},
                details={"error": "boom"},
                level="ERROR",
            )

        mocked_log.assert_called_once()
        self.assertEqual(mocked_log.call_args.kwargs["level"], "ERROR")
        self.assertEqual(mocked_log.call_args.kwargs["trace_id"], "trace-1")

    @patch("app.spiders.bilibili.spider.time.sleep", return_value=None)
    def test_bilibili_process_download_task_continues_after_parse_error(self, _mock_sleep):
        """单条取流解析失败后，后续任务仍必须继续提交。"""
        spider = self._make_bilibili_spider()
        first_task = {
            "trace_id": "trace-1",
            "bvid": "BV1fail",
            "cid": 101,
            "file_name": "P01_失败.mp4",
            "referer": "https://www.bilibili.com/video/BV1fail",
        }
        second_task = {
            "trace_id": "trace-2",
            "bvid": "BV1ok",
            "cid": 102,
            "file_name": "P02_成功.mp4",
            "referer": "https://www.bilibili.com/video/BV1ok",
        }
        spider.api.get_play_url.side_effect = [
            SpiderParseError("payload malformed"),
            ("https://video.example.com/v.mp4", "https://video.example.com/a.m4a", 80),
        ]

        first_result = spider._process_download_task(first_task)
        second_result = spider._process_download_task(second_task)

        self.assertFalse(first_result)
        self.assertTrue(second_result)
        self.assertEqual(spider.api.get_play_url.call_count, 2)
        spider.emit_video.assert_called_once()
        spider.log.assert_any_call("   ❌ 获取流失败: payload malformed")
        spider.log.assert_any_call("   ✨ 获取成功 [1080P]")

    def test_bilibili_process_download_tasks_async_batches_ready_items(self):
        spider = self._make_bilibili_spider()
        spider.config = {"api_workers": 2}
        spider.emit_videos = Mock(return_value=2)
        spider._worker_api_for_thread = Mock(return_value=Mock())

        def resolve(task, api=None):
            del api
            item = VideoItem(
                url=f"https://video.example.com/{task['bvid']}.mp4",
                title=task["file_name"].removesuffix(".mp4"),
                source="bilibili",
            )
            item.meta["trace_id"] = task["trace_id"]
            return item

        spider._resolve_download_item = Mock(side_effect=resolve)
        tasks = [
            {
                "trace_id": "trace-1",
                "bvid": "BV1",
                "cid": 101,
                "file_name": "P01_示例.mp4",
                "referer": "https://www.bilibili.com/video/BV1",
            },
            {
                "trace_id": "trace-2",
                "bvid": "BV2",
                "cid": 102,
                "file_name": "P02_示例.mp4",
                "referer": "https://www.bilibili.com/video/BV2",
            },
        ]

        success_count, failure_count = spider._process_download_tasks_async(tasks)

        self.assertEqual((success_count, failure_count), (2, 0))
        self.assertEqual(spider._resolve_download_item.call_count, 2)
        spider.emit_videos.assert_called_once()
        spider.emit_video.assert_not_called()

    @patch("app.spiders.douyin.spider.os.path.exists", return_value=True)
    def test_douyin_load_or_login_falls_back_to_scan_when_local_cookie_invalid(self, _mock_exists):
        """验证 `test_douyin_load_or_login_falls_back_to_scan_when_local_cookie_invalid` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.auth_file = "dy_auth.json"
        spider.auth_service = Mock(spec=AuthService)
        spider.auth_service.load_json_file.return_value = [{"name": "sid_guard", "value": "1"}]
        spider.auth_service.build_cookie_string.return_value = ""
        spider._perform_scan_login = Mock(return_value="fresh_cookie")
        spider.log = Mock()

        result = spider._load_or_login()

        self.assertEqual(result, "fresh_cookie")
        spider._perform_scan_login.assert_called_once()

    @patch("app.spiders.douyin.spider.Process")
    @patch("app.spiders.douyin.spider.Queue")
    def test_douyin_scan_login_raises_cancelled_error_when_stopped(self, _mock_queue, mock_process):
        """验证 `test_douyin_scan_login_raises_cancelled_error_when_stopped` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.auth_file = "dy_auth.json"
        spider.config = {"timeout": 90}
        spider.is_running = False
        spider.log = Mock()
        spider.auth_service = Mock(spec=AuthService)
        process = Mock()
        process.is_alive.return_value = True
        mock_process.return_value = process

        with self.assertRaises(LoginCancelledError):
            spider._perform_scan_login()

        self.assertEqual(mock_process.call_args.kwargs["args"][-1], 90000)
        process.terminate.assert_called_once()
        process.join.assert_called_once_with(timeout=2)

    @patch("app.spiders.douyin.spider.Process")
    @patch("app.spiders.douyin.spider.Queue")
    def test_douyin_scan_login_reads_result_without_empty_probe(self, mock_queue, mock_process):
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.auth_file = "dy_auth.json"
        spider.config = {"timeout": 90}
        spider.is_running = True
        spider.log = Mock()
        spider.auth_service = Mock(spec=AuthService)
        spider.auth_service.load_json_file.return_value = [{"name": "sessionid_ss", "value": "1"}]
        spider.auth_service.build_cookie_string.return_value = "sessionid_ss=1"
        process = Mock()
        process.is_alive.return_value = False
        process.exitcode = 0
        mock_process.return_value = process
        result_queue = Mock()
        result_queue.get.return_value = "success"
        mock_queue.return_value = result_queue

        result = spider._perform_scan_login()

        self.assertEqual(result, "sessionid_ss=1")
        result_queue.empty.assert_not_called()
        result_queue.get.assert_called_once_with(timeout=2)
        result_queue.close.assert_called_once()
        result_queue.join_thread.assert_called_once()

    @patch("app.spiders.douyin.spider.Process")
    @patch("app.spiders.douyin.spider.Queue")
    def test_douyin_scan_login_reports_exitcode_when_queue_has_no_result(self, mock_queue, mock_process):
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.auth_file = "dy_auth.json"
        spider.config = {"timeout": 90}
        spider.is_running = True
        spider.log = Mock()
        spider.auth_service = Mock(spec=AuthService)
        process = Mock()
        process.is_alive.return_value = False
        process.exitcode = 7
        mock_process.return_value = process
        result_queue = Mock()
        result_queue.get.side_effect = queue.Empty
        mock_queue.return_value = result_queue

        with self.assertRaises(SpiderAuthError) as raised:
            spider._perform_scan_login()

        self.assertIn("无返回结果", str(raised.exception))
        self.assertIn("exitcode=7", str(raised.exception))
        result_queue.empty.assert_not_called()
        result_queue.get.assert_called_once_with(timeout=2)
        result_queue.close.assert_called_once()
        result_queue.join_thread.assert_called_once()

    def test_kuaishou_ensure_login_returns_false_when_cancelled(self):
        """验证 `test_kuaishou_ensure_login_returns_false_when_cancelled` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = False
        spider.auth_service = Mock(spec=AuthService)
        spider._wait_for_manual_login = Mock(return_value=False)
        spider._goto_with_retry = Mock(return_value=False)
        spider._refresh_logged_in_state = Mock(return_value=False)
        spider._user_cookie_values = Mock(return_value=set())
        spider.log = Mock()
        page = Mock()
        spider._is_logged_in = Mock(return_value=False)
        context = Mock()

        result = spider._ensure_login(page, context, "ks_auth.json")

        self.assertFalse(result)
        spider._wait_for_manual_login.assert_called_once_with(page, context, "ks_auth.json")

    @patch("app.spiders.kuaishou.spider.os.path.exists", return_value=True)
    def test_kuaishou_invalid_cookie_keeps_page_for_manual_login(self, _mock_exists):
        """验证 `test_kuaishou_invalid_cookie_keeps_page_for_manual_login` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = False
        spider.auth_service = Mock(spec=AuthService)
        spider._wait_for_manual_login = Mock(return_value=False)
        spider._open_login_entry = Mock()
        spider._is_logged_in = Mock(return_value=False)
        spider._goto_with_retry = Mock(return_value=False)
        spider._refresh_logged_in_state = Mock(return_value=False)
        spider._user_cookie_values = Mock(return_value=set())
        spider.log = Mock()
        page = Mock()
        context = Mock()

        spider._ensure_login(page, context, "ks_auth.json")

        spider._open_login_entry.assert_called_once_with(page)
        spider.log.assert_any_call("⚠️ 本地 Cookie 已加载，但当前页面未识别为已登录，可能已失效")

    def test_kuaishou_silent_login_check_defers_manual_login_until_visible_session(self):
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = True
        spider.auth_service = Mock(spec=AuthService)
        spider._wait_for_manual_login = Mock(return_value=False)
        spider._open_login_entry = Mock()
        spider._is_logged_in = Mock(return_value=False)
        spider._goto_with_retry = Mock(return_value=False)
        spider._refresh_logged_in_state = Mock(return_value=False)
        spider._user_cookie_values = Mock(return_value=set())
        spider.log = Mock()
        page = Mock()
        context = Mock()

        result = spider._ensure_login(page, context, "ks_auth.json", allow_manual_login=False)

        self.assertFalse(result)
        spider._open_login_entry.assert_not_called()
        spider._wait_for_manual_login.assert_not_called()

    def test_kuaishou_manual_login_timeout_returns_false_even_when_running(self):
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = True
        spider.auth_service = Mock(spec=AuthService)
        spider._wait_for_manual_login = Mock(return_value=False)
        spider._open_login_entry = Mock()
        spider._is_logged_in = Mock(return_value=False)
        spider._goto_with_retry = Mock(return_value=False)
        spider._refresh_logged_in_state = Mock(return_value=False)
        spider._user_cookie_values = Mock(return_value=set())
        spider.log = Mock()
        page = Mock()
        context = Mock()

        result = spider._ensure_login(page, context, "ks_auth.json")

        self.assertFalse(result)
        spider._open_login_entry.assert_called_once_with(page)
        spider._wait_for_manual_login.assert_called_once_with(page, context, "ks_auth.json")

    def test_kuaishou_open_login_entry_stays_on_current_site_when_button_missing(self):
        """验证 `test_kuaishou_open_login_entry_stays_on_current_site_when_button_missing` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.log = Mock()
        page = Mock()
        locator = page.locator.return_value.first
        locator.is_visible.side_effect = PlaywrightError("missing")

        spider._open_login_entry(page)

        page.goto.assert_not_called()
        spider.log.assert_any_call("📱 未能自动弹出登录框，请直接在当前快手页面手动登录")

    def test_kuaishou_navigate_to_target_page_url_encodes_keyword(self):
        """验证 `test_kuaishou_navigate_to_target_page_url_encodes_keyword` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.keyword = "测试 主播&1"
        spider.log = Mock()
        spider._search_keyword_via_site = Mock(return_value=None)
        page = Mock()
        context = Mock()
        context.pages = [page]

        result = spider._navigate_to_target_page(page, context)

        self.assertIsNone(result)
        spider._search_keyword_via_site.assert_called_once_with(page, "测试 主播&1")

    def test_kuaishou_navigate_searches_site_for_plain_id(self):
        """验证 `test_kuaishou_navigate_searches_site_for_plain_id` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.keyword = "4753241670"
        spider.log = Mock()
        page = Mock()
        context = Mock()
        expected_page = Mock()
        spider._search_user_via_site = Mock(return_value=expected_page)

        result = spider._navigate_to_target_page(page, context)

        self.assertIs(result, expected_page)
        spider._search_user_via_site.assert_called_once_with(page, context, "4753241670")

    @patch("app.spiders.kuaishou.spider.requests.get")
    def test_kuaishou_normalize_keyword_extracts_url_from_share_text(self, mocked_get):
        """分享文案中的短链应先抽取 URL，再展开为真实详情链接。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.log = Mock()
        response = Mock()
        response.url = "https://www.kuaishou.com/short-video/3xj8abcde"
        mocked_get.return_value = response

        normalized = spider._normalize_keyword("复制这条消息，打开快手查看作品 https://v.kuaishou.com/abc123/ ")

        self.assertEqual(normalized, "https://www.kuaishou.com/short-video/3xj8abcde")
        mocked_get.assert_called_once()

    @patch("app.spiders.kuaishou.spider.requests.get")
    def test_kuaishou_try_direct_share_download_emits_without_browser(self, mocked_get):
        """分享详情链接应优先走 HTTP 直连，不依赖浏览器捕获媒体流。"""
        spider = self._make_kuaishou_capture_spider()
        spider.keyword = "https://www.kuaishou.com/short-video/3xj8abcde"
        response = Mock()
        response.url = spider.keyword
        response.text = (
            '<script>window.__APOLLO_STATE__='
            '{"defaultClient":{"VisionVideoDetailPhoto:3xj8abcde":'
            '{"caption":"分享作品","photoUrl":"https://cdn.example.com/video.mp4"}}};'
            "</script>"
        )
        response.raise_for_status = Mock()
        mocked_get.return_value = response

        result = spider._try_direct_share_download()

        self.assertTrue(result)
        spider.emit_video.assert_called_once_with(
            url="https://cdn.example.com/video.mp4",
            title="分享作品",
            source="kuaishou",
            meta={"trace_id": "ks-trace-1"},
        )

    @patch("app.spiders.kuaishou.spider.requests.get")
    def test_kuaishou_fetch_share_detail_uses_task_timeout(self, mocked_get):
        spider = self._make_kuaishou_capture_spider()
        spider.config = {"timeout": 90}
        response = Mock()
        response.url = "https://www.kuaishou.com/short-video/3xj8abcde"
        response.text = ""
        response.raise_for_status = Mock()
        mocked_get.return_value = response

        spider._fetch_share_detail_via_http(response.url)

        self.assertEqual(mocked_get.call_args.kwargs["timeout"], 90)

    def test_kuaishou_run_skips_playwright_when_direct_share_download_succeeds(self):
        """HTTP 直连成功时，run 不应再打开浏览器。"""
        spider = self._make_kuaishou_capture_spider()
        spider.keyword = "https://www.kuaishou.com/short-video/3xj8abcde"
        spider._normalize_keyword = Mock(return_value=spider.keyword)
        spider._try_direct_share_download = Mock(return_value=True)
        spider.sig_finished = Mock()

        with patch("app.spiders.kuaishou.spider.sync_playwright") as mocked_playwright:
            spider.run()

        spider._try_direct_share_download.assert_called_once()
        spider.sig_finished.emit.assert_called_once()
        mocked_playwright.assert_not_called()

    def test_kuaishou_capture_single_detail_page_emits_video_from_dom_media(self):
        """快手分享详情页应可直接解析单条作品并提交下载任务。"""
        spider = self._make_kuaishou_capture_spider()
        page = Mock()
        page.url = "https://www.kuaishou.com/short-video/3xj8abcde"
        page.on = Mock()
        page.evaluate.return_value = "https://cdn.example.com/video.mp4"
        spider._extract_detail_title = Mock(return_value="分享作品")

        result = spider._capture_single_detail_page(page)

        self.assertTrue(result)
        page.on.assert_called_once()
        spider.emit_video.assert_called_once_with(
            url="https://cdn.example.com/video.mp4",
            title="分享作品",
            source="kuaishou",
            meta={"trace_id": "ks-trace-1"},
        )

    def test_kuaishou_silent_run_opens_login_then_retries_headless(self):
        spider = self._make_kuaishou_capture_spider()
        spider.keyword = "demo"
        spider._normalize_keyword = Mock(side_effect=lambda value: value)
        spider._try_direct_share_download = Mock(return_value=False)
        spider._browser_headless = Mock(return_value=True)
        spider._run_browser_session = Mock(side_effect=["login_required", "completed"])
        spider._run_login_window_session = Mock(return_value=True)
        spider._entry_url_for_login = Mock(return_value=None)
        spider._tracked_playwright_browser = Mock(return_value=None)
        spider._clear_playwright_browser = Mock()
        spider._emit_finished = Mock()
        playwright = Mock()

        with patch("app.spiders.kuaishou.spider.sync_playwright") as mocked_playwright:
            mocked_playwright.return_value.__enter__.return_value = playwright
            spider.run()

        self.assertEqual(spider._run_browser_session.call_count, 2)
        first_session = spider._run_browser_session.call_args_list[0]
        retry_session = spider._run_browser_session.call_args_list[1]
        login_session = spider._run_login_window_session.call_args
        self.assertIs(first_session.args[0], playwright)
        self.assertIs(retry_session.args[0], playwright)
        self.assertIs(login_session.args[0], playwright)
        self.assertEqual(first_session.args[1], login_session.args[1])
        self.assertEqual(retry_session.args[1], first_session.args[1])
        self.assertEqual(login_session.args[2], None)
        self.assertEqual(first_session.kwargs, {"headless": True, "allow_manual_login": False})
        self.assertEqual(retry_session.kwargs, {"headless": True, "allow_manual_login": False})
        spider._emit_finished.assert_called_once()

    def test_kuaishou_capture_single_detail_page_returns_false_when_not_detail_url(self):
        """非单条详情页不应误走分享直下逻辑。"""
        spider = self._make_kuaishou_capture_spider()
        page = Mock()
        page.url = "https://www.kuaishou.com/profile/3xj8abcde"

        self.assertFalse(spider._capture_single_detail_page(page))
        spider.emit_video.assert_not_called()

    def test_kuaishou_open_profile_from_search_results_prefers_name_click(self):
        """验证 `test_kuaishou_open_profile_from_search_results_prefers_name_click` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.log = Mock()
        spider._switch_search_to_user_tab = Mock()
        spider._has_video_list = Mock(return_value=True)
        page = Mock()
        name_link = Mock()
        name_link.is_visible.return_value = True
        page.locator.return_value.first = name_link
        context = Mock()
        context.pages = [page]

        result = spider._open_profile_from_search_results(page, context, "4753241670")

        self.assertIs(result, page)
        spider._switch_search_to_user_tab.assert_called_once_with(page)
        name_link.click.assert_called_once()

    def test_kuaishou_ensure_login_uses_direct_entry_url_when_keyword_is_profile_link(self):
        """验证 `test_kuaishou_ensure_login_uses_direct_entry_url_when_keyword_is_profile_link` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider._goto_with_retry = Mock(return_value=True)
        spider._is_logged_in = Mock(return_value=True)
        spider._refresh_logged_in_state = Mock(return_value=False)
        spider._user_cookie_values = Mock(return_value={"uid"})
        spider.log = Mock()
        page = Mock()
        context = Mock()

        result = spider._ensure_login(page, context, "ks_auth.json", entry_url="https://www.kuaishou.com/profile/3xmu5?source=SEARCH")

        self.assertTrue(result)
        spider._goto_with_retry.assert_called_once_with(
            page,
            "https://www.kuaishou.com/profile/3xmu5?source=SEARCH",
            description="页面访问",
        )

    def test_kuaishou_loaded_cookie_refreshes_before_manual_login(self):
        """验证 `test_kuaishou_loaded_cookie_refreshes_before_manual_login` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider._goto_with_retry = Mock(return_value=True)
        spider._is_logged_in = Mock(return_value=False)
        spider._user_cookie_values = Mock(return_value={"uid"})
        spider._refresh_logged_in_state = Mock(return_value=True)
        spider._wait_for_manual_login = Mock()
        spider._open_login_entry = Mock()
        spider.log = Mock()
        page = Mock()
        context = Mock()

        result = spider._ensure_login(page, context, "ks_auth.json")

        self.assertTrue(result)
        spider._refresh_logged_in_state.assert_called_once_with(page, "https://www.kuaishou.com/")
        spider._open_login_entry.assert_not_called()
        spider._wait_for_manual_login.assert_not_called()

    def test_kuaishou_max_items_limit_uses_config_value(self):
        """验证 `test_kuaishou_max_items_limit_uses_config_value` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.config = {"max_items": 10}

        self.assertEqual(spider._max_items_limit(), 10)

    def test_kuaishou_goto_with_retry_uses_task_timeout(self):
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.config = {"timeout": 90}
        spider.interruptible_playwright_goto = Mock(return_value=True)
        spider.interruptible_page_wait = Mock(return_value=True)
        page = Mock()

        self.assertTrue(spider._goto_with_retry(page, "https://www.kuaishou.com/", description="test"))
        self.assertEqual(spider.interruptible_playwright_goto.call_args.kwargs["timeout"], 90000)

    def test_kuaishou_refresh_logged_in_state_uses_task_timeout(self):
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.config = {"timeout": 90}
        spider.interruptible_page_wait = Mock(return_value=True)
        spider.interruptible_playwright_reload = Mock(return_value=True)
        spider._is_logged_in = Mock(return_value=True)
        page = Mock()

        self.assertTrue(spider._refresh_logged_in_state(page, "https://www.kuaishou.com/"))
        spider.interruptible_playwright_reload.assert_called_once_with(
            page,
            wait_until="domcontentloaded",
            timeout=90000,
        )

    def test_kuaishou_refresh_logged_in_state_fallback_goto_uses_task_timeout(self):
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.config = {"timeout": 90}
        spider.interruptible_page_wait = Mock(return_value=True)
        spider.interruptible_playwright_reload = Mock(return_value=True)
        spider.interruptible_playwright_goto = Mock(return_value=True)
        spider._is_logged_in = Mock(side_effect=[False, True])
        page = Mock()

        self.assertTrue(spider._refresh_logged_in_state(page, "https://www.kuaishou.com/profile/demo"))
        spider.interruptible_playwright_goto.assert_called_once_with(
            page,
            "https://www.kuaishou.com/profile/demo",
            timeout=90000,
            wait_until="domcontentloaded",
        )

    def test_kuaishou_capture_scroll_budget_uses_double_window(self):
        """验证 `test_kuaishou_capture_scroll_budget_uses_double_window` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)

        self.assertEqual(spider._capture_scroll_budget([{"index": 0}] * 11), 22)

    def test_kuaishou_wait_for_manual_login_requires_new_cookie_or_visible_login_state(self):
        """验证 `test_kuaishou_wait_for_manual_login_requires_new_cookie_or_visible_login_state` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = True
        spider.auth_service = Mock(spec=AuthService)
        spider._user_cookie_values = Mock(side_effect=[{"old"}, {"old"}, {"old"}])
        spider._is_logged_in = Mock(side_effect=[False, True])
        page = Mock()
        context = Mock()

        result = spider._wait_for_manual_login(page, context, "ks_auth.json")

        self.assertTrue(result)
        spider.auth_service.save_json_file.assert_called_once()

    def test_kuaishou_resolve_active_page_returns_last_open_page(self):
        """验证 `test_kuaishou_resolve_active_page_returns_last_open_page` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = KuaishouSpider.__new__(KuaishouSpider)
        page = Mock()
        page.is_closed.return_value = True
        open_page = Mock()
        open_page.is_closed.return_value = False
        context = Mock()
        context.pages = [page, open_page]

        result = spider._resolve_active_page(page, context)

        self.assertIs(result, open_page)
        open_page.bring_to_front.assert_called_once()

    def test_kuaishou_capture_pipeline_emits_download_for_matched_stream(self):
        """验证 `test_kuaishou_capture_pipeline_emits_download_for_matched_stream` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_kuaishou_capture_spider()
        page = self._make_kuaishou_capture_page()
        spider._resolve_active_page = Mock(side_effect=lambda current, _context: current)

        spider._run_capture_pipeline(
            page,
            items_for_dialog=[{"title": "示例视频", "index": 0}],
            target_fingerprints_map={0: {"cache-1"}},
        )

        spider.emit_video.assert_called_once_with(
            url="https://video.example.com/live.mp4?clientCacheKey=cache-1",
            title="示例视频",
            source="kuaishou",
            meta={"trace_id": "ks-trace-1"},
        )
        spider.task_builder.build_download_meta.assert_called_once_with(
            "ks-trace-1",
            "https://www.kuaishou.com/profile/demo",
            "https://video.example.com/live.mp4?clientCacheKey=cache-1",
            DEFAULT_USER_AGENT,
        )

    def test_douyin_trim_items_applies_config_limit(self):
        """验证 `test_douyin_trim_items_applies_config_limit` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = DouyinSpider.__new__(DouyinSpider)
        spider.config = {"max_items": 2}
        spider.log = Mock()
        items = [
            VideoItem(url="https://example.com/1", title="1", source="douyin"),
            VideoItem(url="https://example.com/2", title="2", source="douyin"),
            VideoItem(url="https://example.com/3", title="3", source="douyin"),
        ]

        result = spider._trim_items(items, "测试")

        self.assertEqual(len(result), 2)
        spider.log.assert_called_once()

    def test_missav_scan_pages_collects_valid_items_and_builds_next_page_url(self):
        """验证 `test_missav_scan_pages_collects_valid_items_and_builds_next_page_url` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = MissAVSpider.__new__(MissAVSpider)
        spider.is_running = True
        spider.config = {"timeout": 90}
        spider.log = Mock()
        page = Mock()
        page.url = "https://missav.ai/cn/search/ipx"
        page.evaluate.side_effect = [
            [
                {"url": "https://missav.ai/cn/abc-123", "title": "A"},
                {"url": "https://missav.ai/cn/contact", "title": "ignored"},
                {"url": "https://missav.ai/en/abc-123", "title": "ignored"},
            ],
            [],
        ]
        page.query_selector.side_effect = [object(), None]
        collected = {}

        spider._scan_pages(page, collected)

        self.assertEqual(collected, {"https://missav.ai/cn/abc-123": "A"})
        page.goto.assert_called_once_with("https://missav.ai/cn/search/ipx?page=2", timeout=90000)

    def test_missav_scan_pages_stops_at_configured_max_items(self):
        spider = MissAVSpider.__new__(MissAVSpider)
        spider.is_running = True
        spider.config = {"max_items": 1}
        spider.log = Mock()
        page = Mock()
        page.url = "https://missav.ai/cn/search/ipx"
        page.evaluate.return_value = [
            {"url": "https://missav.ai/cn/abc-123", "title": "A"},
            {"url": "https://missav.ai/cn/def-456", "title": "B"},
        ]
        collected = {}

        spider._scan_pages(page, collected)

        self.assertEqual(list(collected), ["https://missav.ai/cn/abc-123"])
        page.query_selector.assert_not_called()

    def test_missav_download_headers_merge_browser_request_and_context_cookie(self):
        spider = MissAVSpider.__new__(MissAVSpider)
        spider.config = {}
        context = Mock()
        context.cookies.return_value = [
            {"name": "session", "value": "abc"},
            {"name": "cf_clearance", "value": "token"},
        ]

        headers = spider._download_headers_for_context(
            context,
            "https://missav.ai/cn/abc-123",
            "ua-demo",
            stream_url="https://surrit.com/stream/playlist.m3u8",
            request_headers={
                "accept": "*/*",
                "accept-encoding": "gzip, br",
                "sec-fetch-site": "cross-site",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "origin": "https://missav.ai",
                "referer": "https://missav.ai/cn/abc-123",
                ":authority": "surrit.com",
            },
        )

        self.assertEqual(headers["User-Agent"], "ua-demo")
        self.assertEqual(headers["Referer"], "https://missav.ai/cn/abc-123")
        self.assertEqual(headers["Accept"], "*/*")
        self.assertEqual(headers["Accept-Encoding"], "gzip, br")
        self.assertEqual(headers["Cache-Control"], "no-cache")
        self.assertEqual(headers["Priority"], "u=1, i")
        self.assertEqual(headers["Sec-Fetch-Dest"], "empty")
        self.assertEqual(headers["Sec-Fetch-Mode"], "cors")
        self.assertEqual(headers["Sec-Fetch-Site"], "cross-site")
        self.assertEqual(headers["Origin"], "https://missav.ai")
        self.assertEqual(headers["Range"], "bytes=0-")
        self.assertEqual(headers["Cookie"], "session=abc; cf_clearance=token")
        self.assertNotIn(":authority", headers)
        context.cookies.assert_called_once_with(["https://surrit.com/stream/playlist.m3u8"])

    def test_missav_download_headers_fallback_adds_cross_site_defaults_and_cookie(self):
        spider = MissAVSpider.__new__(MissAVSpider)
        context = Mock()
        context.cookies.return_value = [{"name": "__cf_bm", "value": "token"}]

        headers = spider._download_headers_for_context(
            context,
            "https://missav.ai/cn/abc-123",
            "ua-demo",
            stream_url="https://surrit.com/stream/playlist.m3u8",
            request_headers={},
        )

        self.assertEqual(headers["Origin"], "https://missav.ai")
        self.assertEqual(headers["Sec-Fetch-Mode"], "cors")
        self.assertEqual(headers["Sec-Fetch-Site"], "cross-site")
        self.assertEqual(headers["Cookie"], "__cf_bm=token")
        context.cookies.assert_called_once_with(["https://surrit.com/stream/playlist.m3u8"])

    def test_missav_headers_from_request_sanitizes_browser_headers(self):
        spider = MissAVSpider.__new__(MissAVSpider)
        request = Mock()
        request.all_headers.return_value = {
            "user-agent": "ua-real",
            "sec-ch-ua": '"Chromium";v="126"',
            "accept-encoding": "gzip, deflate, br, zstd",
            "host": "surrit.com",
            "connection": "keep-alive",
        }

        headers = spider._headers_from_request(request)

        self.assertEqual(headers["User-Agent"], "ua-real")
        self.assertEqual(headers["Sec-Ch-Ua"], '"Chromium";v="126"')
        self.assertEqual(headers["Accept-Encoding"], "gzip, deflate, br, zstd")
        self.assertNotIn("Host", headers)
        self.assertNotIn("Connection", headers)

    def test_missav_proxy_helpers_normalize_browser_system_proxy(self):
        self.assertEqual(
            MissAVSpider._proxy_from_proxy_server_string("http=127.0.0.1:8080;https=127.0.0.1:7890"),
            "http://127.0.0.1:7890",
        )
        self.assertEqual(
            MissAVSpider._proxy_from_proxy_server_string("socks=127.0.0.1:1080"),
            "socks5://127.0.0.1:1080",
        )
        self.assertEqual(MissAVSpider._normalize_proxy_server("Clash (7890)"), "http://127.0.0.1:7890")
        self.assertEqual(MissAVSpider._normalize_proxy_server("127.0.0.1:7890"), "http://127.0.0.1:7890")
        self.assertIsNone(MissAVSpider._normalize_proxy_server("系统代理"))

    def test_missav_effective_proxy_prefers_config_then_environment(self):
        spider = MissAVSpider.__new__(MissAVSpider)
        spider.config = {"proxy": "127.0.0.1:9001"}
        self.assertEqual(spider._effective_proxy_server(), "http://127.0.0.1:9001")

        spider.config = {}
        with patch.dict(os.environ, {"HTTPS_PROXY": "127.0.0.1:7890"}, clear=True):
            self.assertEqual(spider._effective_proxy_server(), "http://127.0.0.1:7890")
            self.assertIsNone(spider._effective_proxy_server("直连"))

    def test_non_proxy_spiders_ignore_environment_proxy_by_default(self):
        for spider_cls in (BaseSpider, BilibiliSpider, DouyinSpider, KuaishouSpider, XiaohongshuSpider):
            with self.subTest(spider=spider_cls.__name__):
                spider = spider_cls.__new__(spider_cls)
                spider.config = {}
                with patch.dict(os.environ, {"HTTPS_PROXY": "127.0.0.1:7890"}, clear=True):
                    self.assertIsNone(spider._effective_proxy_server())
                self.assertEqual(spider._effective_proxy_server("127.0.0.1:9001"), "http://127.0.0.1:9001")

    def test_xiaohongshu_proxy_only_uses_explicit_config(self):
        spider = XiaohongshuSpider.__new__(XiaohongshuSpider)
        spider.config = {}
        with patch.dict(os.environ, {"HTTPS_PROXY": "127.0.0.1:7890"}, clear=True):
            self.assertIsNone(spider._proxy())

        spider.config = {"proxy": "127.0.0.1:9001"}
        self.assertEqual(spider._proxy(), "http://127.0.0.1:9001")

    def test_missav_scan_pages_logs_page_errors(self):
        """验证 `test_missav_scan_pages_logs_page_errors` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = MissAVSpider.__new__(MissAVSpider)
        spider.is_running = True
        spider.log = Mock()
        page = Mock()
        page.url = "https://missav.ai/cn/search/ipx"
        page.wait_for_selector.side_effect = PlaywrightError("boom")

        spider._scan_pages(page, {})

        self.assertTrue(any("页面扫描异常" in str(call.args[0]) for call in spider.log.call_args_list))

    def test_douyin_api_browser_versions_share_extracted_chrome_version(self):
        """验证 `test_douyin_api_browser_versions_share_extracted_chrome_version` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        self.assertEqual(API.params["browser_version"], CHROME_VERSION)
        self.assertEqual(API.params["engine_version"], CHROME_VERSION)
        self.assertEqual(APITikTok.params["browser_version"], CHROME_VERSION)

        live = Live.__new__(Live)
        live.set_referer = Mock()
        live.web_rid = "123456"
        live.request_data = AsyncMock(return_value={"ok": True})

        asyncio.run(live.with_web_rid())

        request_params = live.request_data.await_args.args[1]
        self.assertEqual(request_params["browser_version"], CHROME_VERSION)

    def test_bilibili_search_page_url_updates_page_and_offset(self):
        """验证 `test_bilibili_search_page_url_updates_page_and_offset` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        next_url = spider._build_search_page_url(
            "https://search.bilibili.com/all?keyword=test&page=1&o=0&from_source=webtop_search",
            5,
        )
        self.assertIn("page=5", next_url)
        self.assertIn("o=120", next_url)
        self.assertIn("keyword=test", next_url)

    def test_bilibili_search_page_url_adds_pagination_when_missing(self):
        """验证 `test_bilibili_search_page_url_adds_pagination_when_missing` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        next_url = spider._build_search_page_url(
            "https://search.bilibili.com/all?keyword=test",
            2,
        )
        self.assertIn("page=2", next_url)
        self.assertIn("o=30", next_url)
        self.assertIn("keyword=test", next_url)

    def test_bilibili_enqueue_new_bvids_filters_duplicates(self):
        """验证 `test_bilibili_enqueue_new_bvids_filters_duplicates` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.config = {"max_items": 10}
        spider.raw_bv_queue = Mock()
        bv_set = {"BV1xx411old0"}

        new_count = spider._enqueue_new_bvids(
            [
                "https://www.bilibili.com/video/BV1xx411old0",
                "https://www.bilibili.com/video/BV1xx411new0",
                "https://www.bilibili.com/video/BV1xx411new0?p=2",
                "https://www.bilibili.com/read/cv123",
            ],
            bv_set,
        )

        self.assertEqual(new_count, 1)
        self.assertEqual(bv_set, {"BV1xx411old0", "BV1xx411new0"})
        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411new0")

    def test_bilibili_max_items_limit_uses_config_value(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.config = {"max_items": 10}

        self.assertEqual(spider._max_items_limit(), 10)

    def test_bilibili_effective_scan_pages_respects_page_limit_over_item_budget(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.config = {"max_pages": 1, "max_items": 9999}

        self.assertEqual(spider._effective_scan_pages(), 1)

    def test_bilibili_effective_scan_pages_supports_max_label(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.config = {"max_pages": "max", "max_items": 1}

        self.assertEqual(spider._effective_scan_pages(), 9999)

    def test_bilibili_enqueue_new_bvids_stops_at_configured_max_items(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.config = {"max_items": 1}
        spider.raw_bv_queue = Mock()
        bv_set = set()

        new_count = spider._enqueue_new_bvids(
            [
                "https://www.bilibili.com/video/BV1xx411new0",
                "https://www.bilibili.com/video/BV1xx411new1",
            ],
            bv_set,
        )

        self.assertEqual(new_count, 1)
        self.assertEqual(bv_set, {"BV1xx411new0"})
        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411new0")

    def test_bilibili_scan_page_retries_after_empty_first_pass(self):
        """验证 `test_bilibili_scan_page_retries_after_empty_first_pass` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.config = {"max_items": 10}
        spider.raw_bv_queue = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            [],
            None,
            ["https://www.bilibili.com/video/BV1xx411try0"],
        ]

        new_count = spider._scan_page_for_new_bvids(page, set())

        self.assertEqual(new_count, 1)
        page.evaluate.assert_any_call("window.scrollTo(0, document.body.scrollHeight)")
        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411try0")

    def test_bilibili_scan_page_can_collect_without_requeueing_after_api_pool_finished(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.config = {"max_items": 10}
        spider.raw_bv_queue = Mock()
        page = Mock()
        page.evaluate.return_value = ["https://www.bilibili.com/video/BV1xx411try0"]

        new_count = spider._scan_page_for_new_bvids(page, set(), enqueue=False)

        self.assertEqual(new_count, 1)
        spider.raw_bv_queue.put.assert_not_called()

    def test_bilibili_static_search_candidates_enqueue_alternatives_for_collection_bv(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.config = {"timeout": 60}
        spider.raw_bv_queue = Mock()
        spider.log = Mock()
        response = Mock(status_code=200)
        response.text = """
            <a href="/video/BV19nRWBtEnF">unavailable representative</a>
            <a href="/video/BV1xgDNBUEXg">first playable</a>
            <script>{"bvid":"BV1QY411b7Kf","jump_url":"//www.bilibili.com/video/BV1xgDNBUEXg"}</script>
        """

        with patch("app.spiders.bilibili.spider.requests.get", return_value=response) as mocked_get:
            count = spider._scan_static_bilibili_candidates(
                "https://search.bilibili.com/all?keyword=BV19nRWBtEnF%20%E5%90%88%E9%9B%86",
                max_pages=1,
                bv_set={"BV19nRWBtEnF"},
                enqueue=True,
            )

        self.assertEqual(count, 2)
        mocked_get.assert_called_once()
        spider.raw_bv_queue.put.assert_any_call("BV1xgDNBUEXg")
        spider.raw_bv_queue.put.assert_any_call("BV1QY411b7Kf")
        self.assertEqual(spider.raw_bv_queue.put.call_count, 2)

    def test_bilibili_static_search_candidates_respects_max_items(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.config = {"timeout": 60, "max_items": 1}
        spider.raw_bv_queue = Mock()
        spider.log = Mock()
        response = Mock(status_code=200)
        response.text = """
            <a href="/video/BV1xgDNBUEXg">first playable</a>
            <a href="/video/BV1QY411b7Kf">second playable</a>
        """

        with patch("app.spiders.bilibili.spider.requests.get", return_value=response):
            count = spider._scan_static_bilibili_candidates(
                "https://search.bilibili.com/all?keyword=BV19nRWBtEnF",
                max_pages=1,
                bv_set=set(),
                enqueue=True,
            )

        self.assertEqual(count, 1)
        spider.raw_bv_queue.put.assert_called_once_with("BV1xgDNBUEXg")

    def test_bilibili_static_search_candidates_can_collect_without_queueing(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.config = {"timeout": 60}
        spider.raw_bv_queue = Mock()
        spider.log = Mock()
        response = Mock(status_code=200)
        response.text = '<a href="/video/BV1xgDNBUEXg">first playable</a>'

        with patch("app.spiders.bilibili.spider.requests.get", return_value=response):
            count = spider._scan_static_bilibili_candidates(
                "https://search.bilibili.com/all?keyword=BV19nRWBtEnF",
                max_pages=1,
                bv_set=set(),
                enqueue=False,
            )

        self.assertEqual(count, 1)
        spider.raw_bv_queue.put.assert_not_called()

    def test_bilibili_plain_keyword_search_does_not_use_static_shortcut(self):
        self.assertFalse(
            BilibiliSpider._should_use_static_search_shortcut(
                "https://search.bilibili.com/all?keyword=SomeUploader"
            )
        )
        self.assertTrue(
            BilibiliSpider._should_use_static_search_shortcut(
                "https://search.bilibili.com/all?keyword=BV19nRWBtEnF"
            )
        )
        self.assertTrue(
            BilibiliSpider._should_use_static_search_shortcut(
                f"https://search.bilibili.com/all?keyword={quote('BV19nRWBtEnF 合集')}"
            )
        )

    def test_bilibili_search_up_card_resolves_to_space_video_tab(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        page = Mock()
        page.evaluate.return_value = {
            "href": "//space.bilibili.com/1513751793?from=search",
            "name": "Demo UP",
        }

        target, name = spider._extract_search_up_space_video_url(page)

        self.assertEqual(target, "https://space.bilibili.com/1513751793/video")
        self.assertEqual(name, "Demo UP")

    def test_bilibili_extract_video_hrefs_does_not_scan_full_html_as_plain_text(self):
        import inspect

        source = inspect.getsource(BilibiliSpider._extract_video_hrefs)

        self.assertNotIn("addBvid(document.documentElement.innerHTML)", source)
        self.assertNotIn("if (typeof value === 'string') {\n                    addBvid(value);", source)
        self.assertIn("addSemanticBvids(document.documentElement.innerHTML)", source)
        self.assertIn("addBvidFromSemanticString(keyHint, value)", source)
        self.assertIn("initialState.error", source)

    def test_bilibili_error_page_is_detected_before_redirect(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        page = Mock()
        page.evaluate.return_value = True

        self.assertTrue(spider._is_bilibili_error_page(page))

    def test_bilibili_page_snapshot_detects_ready_candidates(self):
        state = BilibiliSpider._classify_bilibili_page_snapshot(
            {
                "ready_state": "complete",
                "candidate_count": 2,
                "body_text": "空间主人还没投过视频",
            }
        )

        self.assertEqual(state.kind, "ready")
        self.assertFalse(state.terminal)

    def test_bilibili_page_snapshot_detects_loaded_empty_space(self):
        state = BilibiliSpider._classify_bilibili_page_snapshot(
            {
                "ready_state": "complete",
                "candidate_count": 0,
                "body_text": "空间主人还没投过视频，这里什么也没有...",
                "url": "https://space.bilibili.com/272654283/upload/video",
            }
        )

        self.assertEqual(state.kind, "empty")
        self.assertTrue(state.terminal)

    def test_bilibili_page_snapshot_detects_risk_control(self):
        state = BilibiliSpider._classify_bilibili_page_snapshot(
            {
                "ready_state": "interactive",
                "candidate_count": 0,
                "body_text": "系统检测到您的账号或网络环境存在异常，请完成安全验证",
                "risk_marker_count": 1,
            }
        )

        self.assertEqual(state.kind, "risk")
        self.assertTrue(state.terminal)

    def test_bilibili_page_snapshot_detects_contradictory_empty_with_video_count_as_risk(self):
        state = BilibiliSpider._classify_bilibili_page_snapshot(
            {
                "ready_state": "complete",
                "candidate_count": 0,
                "body_text": "投稿 999+\n视频\n1059\n空间主人还没投过视频，这里什么也没有...",
                "url": "https://space.bilibili.com/272654283/upload/video",
            }
        )

        self.assertEqual(state.kind, "risk")
        self.assertTrue(state.terminal)
        self.assertIn("非零视频计数", state.reason)

    def test_bilibili_page_snapshot_detects_not_loaded(self):
        state = BilibiliSpider._classify_bilibili_page_snapshot(
            {"ready_state": "loading", "candidate_count": 0, "body_text": ""}
        )

        self.assertEqual(state.kind, "not_loaded")
        self.assertFalse(state.terminal)

    def test_bilibili_wait_stops_immediately_on_terminal_empty_page(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider._interrupt_requested = False

        page = Mock()
        page.evaluate.return_value = {
            "ready_state": "complete",
            "candidate_count": 0,
            "body_text": "空间主人还没投过视频，这里什么也没有...",
            "url": "https://space.bilibili.com/272654283/upload/video",
        }

        state = spider._wait_for_bilibili_candidates(page, timeout_ms=60000)

        self.assertEqual(state.kind, "empty")
        page.wait_for_timeout.assert_not_called()

    def test_bilibili_api_failure_browser_fallback_adds_new_valid_bv_to_selection(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.keyword = "BV19nRWBtEnF"
        spider.log = Mock()
        spider._scan_with_browser_queue = Mock(return_value=["BV1xx411c7mD"])
        spider.api = Mock()
        spider.api.get_video_info.return_value = {
            "bvid": "BV1xx411c7mD",
            "title": "fallback video",
            "owner": "owner",
            "is_season": False,
            "season_id": None,
            "season_title": "",
            "episodes": [{"title": "fallback video", "bvid": "BV1xx411c7mD", "cid": 123, "page_num": 1}],
        }
        display_items = []
        cached_data = {}

        valid_idx = spider._try_api_failure_browser_fallback(
            [{"raw_id": "BV19nRWBtEnF", "code": 62002, "message": "稿件不可见"}],
            display_items,
            cached_data,
            set(),
            set(),
            0,
            max_pages=1,
        )

        self.assertEqual(valid_idx, 1)
        self.assertEqual(display_items[0]["index"], 0)
        self.assertEqual(cached_data[0]["type"], "single")
        spider._scan_with_browser_queue.assert_any_call(
            "https://www.bilibili.com/video/BV19nRWBtEnF",
            max_pages=1,
            enqueue=False,
            exclude_bvids={"BV19nRWBtEnF"},
            is_search=False,
            is_space=False,
        )
        spider.api.get_video_info.assert_called_once_with("BV1xx411c7mD", trace_id="bilibili_fallback_BV1xx411c7mD")

    def test_bilibili_api_failure_fallback_does_not_retry_same_failed_bv(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.keyword = "BV19nRWBtEnF合集BV号"
        spider.log = Mock()
        spider._scan_with_browser_queue = Mock(return_value=[])
        spider.api = Mock()
        display_items = []
        cached_data = {}

        valid_idx = spider._try_api_failure_browser_fallback(
            [{"raw_id": "BV19nRWBtEnF", "code": 62002, "message": "稿件不可见"}],
            display_items,
            cached_data,
            set(),
            set(),
            0,
            max_pages=1,
        )

        self.assertEqual(valid_idx, 0)
        spider.api.get_video_info.assert_not_called()
        self.assertTrue(
            any("did not find additional BV candidates" in str(call.args[0]) for call in spider.log.call_args_list)
        )

    def test_bilibili_chinese_collection_bv_hint_keeps_direct_bv_and_search_fallbacks(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)

        route = spider._classify_input("BV19nRWBtEnF合集BV号")

        self.assertEqual(route.kind, "bvid_with_fallback")
        self.assertEqual(route.value, "BV19nRWBtEnF")
        fallback_urls = route.scan_kwargs["fallback_urls"]
        self.assertIn("https://www.bilibili.com/video/BV19nRWBtEnF", fallback_urls)
        self.assertTrue(any("keyword=BV19nRWBtEnF" in url for url in fallback_urls))
        self.assertTrue(any("BV19nRWBtEnF%20%E5%90%88%E9%9B%86" in url for url in fallback_urls))
        self.assertTrue(any("keyword=BV19nRWBtEnF" in url and "%E5%90%88%E9%9B%86" in url for url in fallback_urls))

    def test_bilibili_producer_routes_uid_to_space_scan(self):
        """验证 `test_bilibili_producer_routes_uid_to_space_scan` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "1513751793"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider._scan_with_browser_queue.assert_called_once_with(
            "https://space.bilibili.com/1513751793/video",
            max_pages=5,
            is_search=False,
            is_space=True,
        )
        spider.browser_finished.set.assert_called_once()

    def test_bilibili_short_numeric_input_routes_to_keyword_search(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)

        route = spider._classify_input("1")

        self.assertEqual(route.kind, "keyword")
        self.assertIn("keyword=1", route.value)
        self.assertEqual(route.scan_kwargs, {"is_search": True, "is_space": False})

    def test_bilibili_producer_queues_single_bv_without_browser_scan(self):
        """验证 `test_bilibili_producer_queues_single_bv_without_browser_scan` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "BV1xx411c7mD"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411c7mD")
        spider._scan_with_browser_queue.assert_not_called()
        spider.browser_finished.set.assert_called_once()

    def test_bilibili_producer_routes_space_home_link_to_video_tab(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://space.bilibili.com/1513751793?spm_id_from=333.337.0.0"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider._scan_with_browser_queue.assert_called_once_with(
            "https://space.bilibili.com/1513751793/video",
            max_pages=5,
            is_search=False,
            is_space=True,
        )
        spider.raw_bv_queue.put.assert_not_called()

    def test_bilibili_producer_routes_plain_video_url_to_bv_queue(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://www.bilibili.com/video/BV1xx411c7mD?p=2&vd_source=demo"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411c7mD")
        spider._scan_with_browser_queue.assert_not_called()

    def test_bilibili_producer_routes_collection_video_url_to_scan(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://www.bilibili.com/video/BV1xx411c7mD?list=ML123"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider._scan_with_browser_queue.assert_called_once_with(
            "https://www.bilibili.com/video/BV1xx411c7mD?list=ML123",
            max_pages=5,
            is_search=False,
            is_space=False,
        )
        spider.raw_bv_queue.put.assert_not_called()

    def test_bilibili_producer_routes_ugc_season_bv_url_to_api_queue_and_scan_fallback(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://www.bilibili.com/video/BV1xx411c7mD?spm_id_from=333.788.videopod.sections&vd_source=demo"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411c7mD")
        spider._scan_with_browser_queue.assert_called_once_with(
            "https://www.bilibili.com/video/BV1xx411c7mD?spm_id_from=333.788.videopod.sections&vd_source=demo",
            max_pages=5,
            exclude_bvids={"BV1xx411c7mD"},
            is_search=False,
            is_space=False,
        )

    def test_bilibili_producer_routes_ugc_season_id_bv_url_to_api_queue_and_scan_fallback(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://www.bilibili.com/video/BV1xx411c7mD?ugc_season_id=123456&section_id=789"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411c7mD")
        spider._scan_with_browser_queue.assert_called_once_with(
            "https://www.bilibili.com/video/BV1xx411c7mD?ugc_season_id=123456&section_id=789",
            max_pages=5,
            exclude_bvids={"BV1xx411c7mD"},
            is_search=False,
            is_space=False,
        )

    def test_bilibili_producer_routes_space_collection_url_to_scan(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://space.bilibili.com/1513751793/channel/collectiondetail?sid=123456"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider._scan_with_browser_queue.assert_called_once_with(
            "https://space.bilibili.com/1513751793/channel/collectiondetail?sid=123456",
            max_pages=5,
            is_search=False,
            is_space=False,
        )

    def test_bilibili_classify_share_text_with_embedded_bvid(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("【测试标题】快来看看 BV1xx411c7mD 吧")
        self.assertEqual(route.kind, "bvid")
        self.assertEqual(route.value, "BV1xx411c7mD")

    def test_bilibili_classify_bvid_adjacent_to_chinese_text(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("BV19nRWBtEnF合集BV号")
        self.assertEqual(route.kind, "bvid_with_fallback")
        self.assertEqual(route.value, "BV19nRWBtEnF")
        self.assertEqual(route.scan_kwargs["is_search"], False)
        self.assertEqual(route.scan_kwargs["is_space"], False)
        self.assertEqual(route.scan_kwargs["fallback_url"], "https://www.bilibili.com/video/BV19nRWBtEnF")
        self.assertIn("keyword=BV19nRWBtEnF", route.scan_kwargs["fallback_urls"][0])
        self.assertIn("search.bilibili.com", route.scan_kwargs["fallback_urls"][1])
        self.assertEqual(route.scan_kwargs["fallback_urls"][-1], "https://www.bilibili.com/video/BV19nRWBtEnF")

    def test_bilibili_classify_bvid_embedded_in_chinese_text(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("这是一个合集BV19nRWBtEnF合集BV号")
        self.assertEqual(route.kind, "bvid_with_fallback")
        self.assertEqual(route.value, "BV19nRWBtEnF")
        self.assertEqual(route.scan_kwargs["is_search"], False)
        self.assertEqual(route.scan_kwargs["is_space"], False)
        self.assertEqual(route.scan_kwargs["fallback_url"], "https://www.bilibili.com/video/BV19nRWBtEnF")
        self.assertIn("keyword=BV19nRWBtEnF", route.scan_kwargs["fallback_urls"][0])
        self.assertIn("search.bilibili.com", route.scan_kwargs["fallback_urls"][1])
        self.assertEqual(route.scan_kwargs["fallback_urls"][-1], "https://www.bilibili.com/video/BV19nRWBtEnF")

    def test_bilibili_classify_single_bvid_with_chinese_collection_hint(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("BV19nRWBtEnF合集")

        self.assertEqual(route.kind, "bvid_with_fallback")
        self.assertEqual(route.value, "BV19nRWBtEnF")
        self.assertIn("keyword=BV19nRWBtEnF", route.scan_kwargs["fallback_urls"][0])
        self.assertEqual(route.scan_kwargs["fallback_urls"][-1], "https://www.bilibili.com/video/BV19nRWBtEnF")

    def test_bilibili_producer_routes_collection_bv_hint_to_direct_and_fallback_scan(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "BV19nRWBtEnF合集BV号"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with("BV19nRWBtEnF")
        self.assertEqual(spider._scan_with_browser_queue.call_count, 4)
        self.assertIn("keyword=BV19nRWBtEnF", spider._scan_with_browser_queue.call_args_list[0].args[0])
        self.assertTrue(spider._scan_with_browser_queue.call_args_list[0].kwargs["is_search"])
        self.assertIn("BV19nRWBtEnF%20%E5%90%88%E9%9B%86", spider._scan_with_browser_queue.call_args_list[1].args[0])
        self.assertTrue(spider._scan_with_browser_queue.call_args_list[1].kwargs["is_search"])
        self.assertIn("search.bilibili.com", spider._scan_with_browser_queue.call_args_list[2].args[0])
        self.assertTrue(spider._scan_with_browser_queue.call_args_list[2].kwargs["is_search"])
        self.assertEqual(spider._scan_with_browser_queue.call_args_list[3].args[0], "https://www.bilibili.com/video/BV19nRWBtEnF")
        self.assertFalse(spider._scan_with_browser_queue.call_args_list[3].kwargs["is_search"])

    def test_bilibili_logs_api_failure_summary_when_no_valid_items(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.api_failure_queue = queue.Queue()
        spider.log = Mock()

        spider._record_api_failure(
            "BV19nRWBtEnF",
            {"code": 62002, "message": "稿件不可见", "http_status": 200},
        )
        spider._log_api_failure_summary()

        spider.log.assert_called_once()
        summary = spider.log.call_args.args[0]
        self.assertIn("BV19nRWBtEnF", summary)
        self.assertIn("code=62002", summary)
        self.assertIn("稿件不可见", summary)

    def test_bilibili_classify_plain_av_number(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("av123456")
        self.assertEqual(route.kind, "aid")
        self.assertEqual(route.value, "123456")

    def test_bilibili_classify_uid_label(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("UID:1513751793")
        self.assertEqual(route.kind, "scan")
        self.assertEqual(route.value, "https://space.bilibili.com/1513751793/video")

    def test_bilibili_classify_short_uid_label_still_routes_to_space(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        route = spider._classify_input("UID:1")
        self.assertEqual(route.kind, "scan")
        self.assertEqual(route.value, "https://space.bilibili.com/1/video")

    def test_bilibili_producer_routes_search_url_to_search_scan(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://search.bilibili.com/all?keyword=test"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider._scan_with_browser_queue.assert_called_once_with(
            "https://search.bilibili.com/all?keyword=test",
            max_pages=5,
            is_search=True,
            is_space=False,
        )

    def test_bilibili_producer_routes_av_url_to_aid_queue(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "https://www.bilibili.com/video/av123456"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with({"aid": "123456"})
        spider._scan_with_browser_queue.assert_not_called()

    def test_bilibili_producer_builds_search_url_from_keyword(self):
        """验证 `test_bilibili_producer_builds_search_url_from_keyword` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "测试关键字"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()

        spider._producer_browser_task()

        spider._scan_with_browser_queue.assert_called_once_with(
            f"https://search.bilibili.com/all?keyword={quote('测试关键字')}",
            5,
            is_search=True,
            is_space=False,
        )
        spider.browser_finished.set.assert_called_once()

    @patch("app.spiders.bilibili.spider.requests.get")
    def test_bilibili_producer_routes_resolved_b23_short_link_to_bv_queue(self, mocked_get):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.keyword = "share https://b23.tv/demo123"
        spider.config = {"max_pages": 5}
        spider.raw_bv_queue = Mock()
        spider._scan_with_browser_queue = Mock()
        spider.browser_finished = Mock()
        spider.log = Mock()
        mocked_get.return_value.url = "https://www.bilibili.com/video/BV1xx411c7mD?share_source=copy_web"

        spider._producer_browser_task()

        spider.raw_bv_queue.put.assert_called_once_with("BV1xx411c7mD")
        spider._scan_with_browser_queue.assert_not_called()

    @patch("app.spiders.bilibili.spider.requests.get")
    def test_bilibili_normalize_keyword_resolves_b23_short_link(self, mocked_get):
        """验证 `test_bilibili_normalize_keyword_resolves_b23_short_link` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.log = Mock()
        mocked_get.return_value.url = "https://www.bilibili.com/video/BV1xx411c7mD"

        result = spider._normalize_keyword("【测试】-哔哩哔哩 https://b23.tv/demo123")

        self.assertEqual(result, "https://www.bilibili.com/video/BV1xx411c7mD")
        mocked_get.assert_called_once()

    @patch("app.spiders.bilibili.spider.requests.get")
    def test_bilibili_short_link_resolution_uses_task_timeout(self, mocked_get):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.config = {"timeout": 90}
        spider.log = Mock()
        mocked_get.return_value.url = "https://www.bilibili.com/video/BV1xx411c7mD"

        spider._resolve_short_share_url("https://b23.tv/demo123")

        self.assertEqual(mocked_get.call_args.kwargs["timeout"], 90)

    @patch("app.spiders.xiaohongshu.spider.requests.get")
    def test_xiaohongshu_short_link_resolution_uses_task_timeout(self, mocked_get):
        spider = XiaohongshuSpider.__new__(XiaohongshuSpider)
        spider.config = {"timeout": 90}
        spider.log = Mock()
        spider._proxy = Mock(return_value=None)
        spider._user_agent = Mock(return_value="ua-demo")
        mocked_get.return_value.url = "https://www.xiaohongshu.com/explore/abc"

        spider._resolve_short_share_url("https://xhslink.com/demo")

        self.assertEqual(mocked_get.call_args.kwargs["timeout"], 90)

    def test_bilibili_normalize_keyword_extracts_first_url_from_share_text(self):
        """验证 `test_bilibili_normalize_keyword_extracts_first_url_from_share_text` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)

        result = spider._extract_first_url("【迪士尼的童话，明码标价！-哔哩哔哩】 https://b23.tv/ehZzrqJ")

        self.assertEqual(result, "https://b23.tv/ehZzrqJ")

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_rejects_numeric_uid(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_rejects_numeric_uid` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("123456")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        mock_parameter.return_value = params
        mock_link_extractor.return_value = Mock()

        asyncio.run(spider._async_main("sessionid_ss=1"))

        spider._process_user_search.assert_not_awaited()
        spider._process_search.assert_not_awaited()
        self.assertTrue(any("纯数字 UID" in str(call.args[0]) for call in spider.log.call_args_list))

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_routes_alnum_to_user_search(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_routes_alnum_to_user_search` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("testuser123")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        mock_parameter.return_value = params
        mock_link_extractor.return_value = Mock()

        asyncio.run(spider._async_main("sessionid_ss=1"))

        spider._process_user_search.assert_awaited_once_with(params, "testuser123")
        spider._process_search.assert_not_awaited()

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_routes_keyword_to_search(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_routes_keyword_to_search` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("测试 关键词")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        mock_parameter.return_value = params
        mock_link_extractor.return_value = Mock()

        asyncio.run(spider._async_main("sessionid_ss=1"))

        spider._process_search.assert_awaited_once_with(params, "测试 关键词")
        spider._process_user_search.assert_not_awaited()

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_routes_user_link_to_process_user(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_routes_user_link_to_process_user` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("https://www.douyin.com/user/MS4wLjABAAAAxxx")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        extractor = Mock()
        extractor.run = AsyncMock(return_value=["sec_uid_1"])
        mock_parameter.return_value = params
        mock_link_extractor.return_value = extractor

        asyncio.run(spider._async_main("sessionid_ss=1"))

        extractor.run.assert_awaited_once_with("https://www.douyin.com/user/MS4wLjABAAAAxxx", type_="user")
        spider._process_user.assert_awaited_once_with(params, "sec_uid_1")

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_routes_collection_link_to_mix(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_routes_collection_link_to_mix` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("https://www.douyin.com/collection/7480000000000000001")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        extractor = Mock()
        extractor.requester = Mock()
        extractor.requester.run = AsyncMock(return_value="mix-page")
        extractor.mix.return_value = (True, ["7480000000000000001"])
        mock_parameter.return_value = params
        mock_link_extractor.return_value = extractor

        asyncio.run(spider._async_main("sessionid_ss=1"))

        extractor.requester.run.assert_awaited_once_with("https://www.douyin.com/collection/7480000000000000001")
        extractor.mix.assert_called_once_with("mix-page")
        spider._process_mix.assert_awaited_once_with(params, "7480000000000000001")
        spider._process_detail.assert_not_awaited()

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_modal_link_prefers_detail(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_modal_link_prefers_detail` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("https://www.douyin.com/discover?modal_id=7480000000000000001")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        extractor = Mock()
        extractor.run = AsyncMock(return_value=["aweme_1"])
        mock_parameter.return_value = params
        mock_link_extractor.return_value = extractor

        asyncio.run(spider._async_main("sessionid_ss=1"))

        extractor.run.assert_awaited_once_with(
            "https://www.douyin.com/discover?modal_id=7480000000000000001",
            type_="detail",
        )
        spider._process_detail.assert_awaited_once_with(params, ["aweme_1"])
        spider._process_mix.assert_not_awaited()

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_modal_link_falls_back_to_mix(self, mock_parameter, mock_link_extractor):
        """验证 `test_douyin_async_main_modal_link_falls_back_to_mix` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = self._make_douyin_spider("https://www.douyin.com/discover?modal_id=7480000000000000001")
        params = Mock(chunk=1024 * 1024, max_retry=3)
        params.update_params = AsyncMock()
        extractor = Mock()
        extractor.run = AsyncMock(return_value=None)
        mock_parameter.return_value = params
        mock_link_extractor.return_value = extractor

        asyncio.run(spider._async_main("sessionid_ss=1"))

        extractor.run.assert_awaited_once_with(
            "https://www.douyin.com/discover?modal_id=7480000000000000001",
            type_="detail",
        )
        spider._process_mix.assert_awaited_once_with(params, "7480000000000000001")
        spider._process_detail.assert_not_awaited()

if __name__ == "__main__":
    unittest.main()
