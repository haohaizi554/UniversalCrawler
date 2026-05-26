import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import quote

import requests
from playwright.sync_api import Error as PlaywrightError

from app.models import VideoItem
from app.exceptions import InvalidCookieStateError, LoginCancelledError, LoginCheckError, SpiderParseError
from app.core.lib.douyin.interface.live import Live
from app.core.lib.douyin.interface.template import API, APITikTok, CHROME_VERSION
from app.services.auth_service import AuthService
from app.spiders.bilibili.spider import BiliAPI
from app.spiders.bilibili.spider import BilibiliSpider
from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.bilibili.task_builder import BilibiliTaskBuilder
from app.spiders.douyin.spider import DouyinSpider
from app.spiders.douyin.task_builder import DouyinTaskBuilder
from app.spiders.kuaishou.spider import KuaishouSpider
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.spiders.missav.task_builder import MissAVTaskBuilder
from app.spiders.missav.parser import MissAVParser


class SpiderHelperTests(unittest.TestCase):
    def _make_douyin_spider(self, keyword: str) -> DouyinSpider:
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

    def test_bilibili_parser_parses_video_info_response(self):
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
        parser = BilibiliParser()

        with self.assertRaises(SpiderParseError):
            parser.parse_video_info_response({"title": "demo"})

    def test_douyin_task_builder_splits_gallery(self):
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

    def test_kuaishou_parser_extracts_cache_key(self):
        parser = KuaishouParser()
        ids = parser.extract_all_possible_ids("https://example.com/video.mp4?clientCacheKey=abc123.mp4")
        self.assertIn("abc123", ids)

    def test_missav_parser_injects_individual_filter(self):
        parser = MissAVParser()
        url = parser.inject_url_params("https://missav.ai/cn/search/ipx-001", individual_only=True)
        self.assertIn("individual", url)

    def test_kuaishou_task_builder_builds_standard_download_meta(self):
        builder = KuaishouTaskBuilder()
        meta = builder.build_download_meta("trace-1", "https://www.kuaishou.com/", "https://cdn.example.com/live.m3u8")

        self.assertEqual(meta["trace_id"], "trace-1")
        self.assertEqual(meta["referer"], "https://www.kuaishou.com/")
        self.assertEqual(meta["download_strategy"], "m3u8")

    def test_missav_task_builder_keeps_compat_alias(self):
        builder = MissAVTaskBuilder()
        new_meta = builder.build_download_meta("trace-2", "https://missav.ai", "ua-demo", "http://127.0.0.1:7890")
        old_meta = builder.build_video_meta("trace-2", "https://missav.ai", "ua-demo", "http://127.0.0.1:7890")

        self.assertEqual(new_meta, old_meta)
        self.assertEqual(new_meta["ua"], "ua-demo")

    def test_bilibili_task_builder_reuses_standard_meta_layout(self):
        builder = BilibiliTaskBuilder(BilibiliParser())
        task = builder.build_single_task(
            {"bvid": "BV1xx", "cid": 123, "title": "演示标题"},
            referer="https://www.bilibili.com/video/BV1xx",
        )

        self.assertEqual(task["trace_id"], "bili-BV1xx-123")
        self.assertEqual(task["bvid"], "BV1xx")
        self.assertTrue(task["file_name"].endswith(".mp4"))

    def test_bili_api_load_cookies_rejects_invalid_payload_shape(self):
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
        api = BiliAPI.__new__(BiliAPI)
        api.sess = Mock()
        api.cookie_path = "bili_auth.json"
        api.parser = BilibiliParser()
        api.auth_service = Mock(spec=AuthService)
        api.sess.get.side_effect = requests.RequestException("boom")

        with self.assertRaises(LoginCheckError):
            api.check_login()

    @patch("app.spiders.douyin.spider.os.path.exists", return_value=True)
    def test_douyin_load_or_login_falls_back_to_scan_when_local_cookie_invalid(self, _mock_exists):
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
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.is_running = False
        spider.auth_service = Mock(spec=AuthService)
        spider.auth_service.wait_for_cookie_and_persist.return_value = False
        spider.log = Mock()
        page = Mock()
        page.wait_for_selector.side_effect = PlaywrightError("not logged in")
        page.locator.return_value.first.click.side_effect = PlaywrightError("no login button")
        context = Mock()

        result = spider._ensure_login(page, context, "ks_auth.json")

        self.assertFalse(result)
        spider.auth_service.wait_for_cookie_and_persist.assert_called_once()

    def test_kuaishou_navigate_to_target_page_url_encodes_keyword(self):
        spider = KuaishouSpider.__new__(KuaishouSpider)
        spider.keyword = "测试 主播&1"
        spider.log = Mock()
        page = Mock()
        user_card = page.locator.return_value.first
        user_card.is_visible.return_value = False
        context = Mock()
        context.pages = [page]

        result = spider._navigate_to_target_page(page, context)

        self.assertIsNone(result)
        page.goto.assert_called_once_with(
            "https://www.kuaishou.com/search/author?source=NewReco&searchKey=%E6%B5%8B%E8%AF%95%20%E4%B8%BB%E6%92%AD%261"
        )

    def test_douyin_api_browser_versions_share_extracted_chrome_version(self):
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
        spider = BilibiliSpider.__new__(BilibiliSpider)
        next_url = spider._build_search_page_url(
            "https://search.bilibili.com/all?keyword=test&page=1&o=0&from_source=webtop_search",
            5,
        )
        self.assertIn("page=5", next_url)
        self.assertIn("o=120", next_url)
        self.assertIn("keyword=test", next_url)

    def test_bilibili_search_page_url_adds_pagination_when_missing(self):
        spider = BilibiliSpider.__new__(BilibiliSpider)
        next_url = spider._build_search_page_url(
            "https://search.bilibili.com/all?keyword=test",
            2,
        )
        self.assertIn("page=2", next_url)
        self.assertIn("o=30", next_url)
        self.assertIn("keyword=test", next_url)

    def test_bilibili_enqueue_new_bvids_filters_duplicates(self):
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

    @patch("app.spiders.bilibili.spider.time.sleep", return_value=None)
    def test_bilibili_scan_page_retries_after_empty_first_pass(self, _mock_sleep):
        spider = BilibiliSpider.__new__(BilibiliSpider)
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
            max_pages=9999,
            is_search=False,
            is_space=True,
        )
        spider.browser_finished.set.assert_called_once()

    def test_bilibili_producer_queues_single_bv_without_browser_scan(self):
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

    def test_bilibili_producer_builds_search_url_from_keyword(self):
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

    @patch("app.spiders.douyin.spider.LinkExtractor")
    @patch("app.spiders.douyin.spider.Parameter")
    def test_douyin_async_main_rejects_numeric_uid(self, mock_parameter, mock_link_extractor):
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
