"""测试模块，覆盖 `tests/test_spider_helpers.py` 对应功能的行为与回归场景。"""

import asyncio
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from urllib.parse import quote

import requests
from playwright.sync_api import Error as PlaywrightError

from app.models import VideoItem
from app.debug_logger import get_debug_logger
from app.exceptions import InvalidCookieStateError, LoginCancelledError, LoginCheckError, SpiderParseError
from app.exceptions import StreamResolveError
from app.core.lib.douyin.interface.live import Live
from app.core.lib.douyin.interface.template import API, APITikTok, CHROME_VERSION
from app.services.auth_service import AuthService
from app.spiders.bilibili.spider import BiliAPI
from app.spiders.bilibili.spider import BilibiliSpider
from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.bilibili.task_builder import BilibiliTaskBuilder
from app.spiders.douyin.parser import DouyinItemParser
from app.spiders.douyin.spider import DouyinSpider
from app.spiders.douyin.task_builder import DouyinTaskBuilder
from app.spiders.kuaishou.spider import KuaishouSpider
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.spiders.missav.spider import MissAVSpider
from app.spiders.missav.task_builder import MissAVTaskBuilder
from app.spiders.missav.parser import MissAVParser
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

    @patch("traceback.print_exc")
    def test_douyin_parser_returns_none_for_invalid_payload_shape(self, _mocked_print_exc):
        """验证 `test_douyin_parser_returns_none_for_invalid_payload_shape` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        parser = DouyinItemParser()

        self.assertIsNone(parser.parse_aweme({"video": None}))

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

    def test_kuaishou_task_builder_builds_standard_download_meta(self):
        """验证 `test_kuaishou_task_builder_builds_standard_download_meta` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        builder = KuaishouTaskBuilder()
        meta = builder.build_download_meta("trace-1", "https://www.kuaishou.com/", "https://cdn.example.com/live.m3u8")

        self.assertEqual(meta["trace_id"], "trace-1")
        self.assertEqual(meta["referer"], "https://www.kuaishou.com/")
        self.assertEqual(meta["download_strategy"], "m3u8")

    def test_missav_task_builder_keeps_compat_alias(self):
        """验证 `test_missav_task_builder_keeps_compat_alias` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        builder = MissAVTaskBuilder()
        new_meta = builder.build_download_meta("trace-2", "https://missav.ai", "ua-demo", "http://127.0.0.1:7890")
        old_meta = builder.build_video_meta("trace-2", "https://missav.ai", "ua-demo", "http://127.0.0.1:7890")

        self.assertEqual(new_meta, old_meta)
        self.assertEqual(new_meta["ua"], "ua-demo")

    def test_bilibili_task_builder_reuses_standard_meta_layout(self):
        """验证 `test_bilibili_task_builder_reuses_standard_meta_layout` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        builder = BilibiliTaskBuilder(BilibiliParser())
        task = builder.build_single_task(
            {"bvid": "BV1xx", "cid": 123, "title": "演示标题"},
            referer="https://www.bilibili.com/video/BV1xx",
        )

        self.assertEqual(task["trace_id"], "bilibili_BV1xx_123")
        self.assertEqual(task["bvid"], "BV1xx")
        self.assertTrue(task["file_name"].endswith(".mp4"))

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
        self.assertIn("aid=123456", api.sess.get.call_args.args[0])

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
        self.assertIn("fnval=4048", api.sess.get.call_args_list[0].args[0])
        self.assertIn("fnval=80", api.sess.get.call_args_list[1].args[0])

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

    @patch("app.spiders.bilibili.spider.sync_playwright")
    def test_bilibili_scan_registers_playwright_browser_for_stop(self, mocked_sync_playwright):
        """扫描线程创建的 browser 必须暴露给 BaseSpider.stop()，便于强制打断。"""
        spider = self._make_bilibili_spider()
        spider.is_running = True
        spider.raw_bv_queue = Mock()
        browser = Mock()

        class FakePage:
            def goto(self, *_args, **_kwargs):
                self.asserted = spider._playwright_browser is browser

            def wait_for_load_state(self, *_args, **_kwargs):
                return None

            def evaluate(self, *_args, **_kwargs):
                return None

        page = FakePage()
        browser.new_page.return_value = page
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        mocked_sync_playwright.return_value.__enter__.return_value = playwright
        mocked_sync_playwright.return_value.__exit__.return_value = None

        spider._scan_with_browser_queue("https://www.bilibili.com/video/BV1demo", max_pages=0)

        self.assertTrue(getattr(page, "asserted", False))
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
        spider.is_running = False
        spider.log = Mock()
        spider.auth_service = Mock(spec=AuthService)
        process = Mock()
        process.is_alive.return_value = True
        mock_process.return_value = process

        with self.assertRaises(LoginCancelledError):
            spider._perform_scan_login()

        process.terminate.assert_called_once()
        process.join.assert_called_once_with(timeout=2)

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
        page.goto.assert_called_once_with("https://missav.ai/cn/search/ipx?page=2", timeout=3000)

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
        spider.raw_bv_queue = Mock()
        bv_set = {"BV1old"}

        new_count = spider._enqueue_new_bvids(
            [
                "https://www.bilibili.com/video/BV1old",
                "https://www.bilibili.com/video/BV1new",
                "https://www.bilibili.com/video/BV1new?p=2",
                "https://www.bilibili.com/read/cv123",
            ],
            bv_set,
        )

        self.assertEqual(new_count, 1)
        self.assertEqual(bv_set, {"BV1old", "BV1new"})
        spider.raw_bv_queue.put.assert_called_once_with("BV1new")

    def test_bilibili_scan_page_retries_after_empty_first_pass(self):
        """验证 `test_bilibili_scan_page_retries_after_empty_first_pass` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.is_running = True
        spider.raw_bv_queue = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            [],
            None,
            ["https://www.bilibili.com/video/BV1retry"],
        ]

        new_count = spider._scan_page_for_new_bvids(page, set())

        self.assertEqual(new_count, 1)
        page.evaluate.assert_any_call("window.scrollTo(0, document.body.scrollHeight)")
        spider.raw_bv_queue.put.assert_called_once_with("BV1retry")

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
    def test_bilibili_normalize_keyword_resolves_b23_short_link(self, mocked_get):
        """验证 `test_bilibili_normalize_keyword_resolves_b23_short_link` 对应场景是否符合预期，供 `SpiderHelperTests` 使用。"""
        spider = BilibiliSpider.__new__(BilibiliSpider)
        spider.log = Mock()
        mocked_get.return_value.url = "https://www.bilibili.com/video/BV1xx411c7mD"

        result = spider._normalize_keyword("【测试】-哔哩哔哩 https://b23.tv/demo123")

        self.assertEqual(result, "https://www.bilibili.com/video/BV1xx411c7mD")
        mocked_get.assert_called_once()

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
