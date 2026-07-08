"""小红书平台接入回归测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
import requests
from types import MethodType
from unittest.mock import Mock, patch

from app.core.downloaders.xiaohongshu import XiaohongshuDownloader
from app.services.auth_service import AuthService
from app.spiders.xiaohongshu.client import XiaohongshuClient
from app.spiders.xiaohongshu.helpers import (
    build_search_id,
    CreatorLookupInfo,
    CreatorUrlInfo,
    extract_first_url,
    extract_video_candidates,
    parse_creator_lookup_input,
    parse_creator_info_from_url,
    parse_note_info_from_note_url,
)
from app.spiders.xiaohongshu import sign as xhs_sign_module
from app.spiders.xiaohongshu.sign import (
    XHS_CRC32_TABLE,
    XiaohongshuLocalSignatureError,
    _build_sign_string,
    _minimal_fingerprint,
    _signed_crc32,
    sign_with_local_algorithm,
    sign_xiaohongshu_headers,
)
from app.spiders.xiaohongshu.spider import XiaohongshuSpider
from app.spiders.xiaohongshu.task_builder import XiaohongshuTaskBuilder

class XiaohongshuHelperTests(unittest.TestCase):
    def test_build_search_id_returns_non_empty_token(self):
        token = build_search_id()
        self.assertTrue(token)
        self.assertIsInstance(token, str)

    def test_local_xhs_signer_generates_headers_without_xhshow(self):
        with patch("app.spiders.xiaohongshu.sign.sign_with_xhshow", side_effect=AssertionError("xhshow should be fallback only")):
            headers = sign_xiaohongshu_headers(
                uri="/api/sns/web/v1/search/notes",
                data={"keyword": "穿搭", "page": 1, "page_size": 20},
                cookie_str="a1=demo-a1; web_session=demo-session",
                method="POST",
            )

        self.assertTrue(headers["X-S"].startswith("XYS_"))
        self.assertTrue(headers["X-T"].isdigit())
        self.assertTrue(headers["x-S-Common"])
        self.assertEqual(len(headers["X-B3-Traceid"]), 16)

    def test_xhs_signer_falls_back_to_xhshow_only_after_local_failure(self):
        fallback_headers = {
            "X-S": "XYS_fallback",
            "X-T": "1700000000000",
            "x-S-Common": "fallback-common",
            "X-B3-Traceid": "abcdef0123456789",
        }
        with patch(
            "app.spiders.xiaohongshu.sign.sign_with_local_algorithm",
            side_effect=XiaohongshuLocalSignatureError("local failed"),
        ) as mocked_local, patch(
            "app.spiders.xiaohongshu.sign.sign_with_xhshow",
            return_value=fallback_headers,
        ) as mocked_xhshow:
            headers = sign_xiaohongshu_headers(
                uri="/api/sns/web/v1/user_posted",
                data={"num": 20},
                cookie_str="a1=demo-a1",
                method="GET",
            )

        self.assertEqual(headers, fallback_headers)
        mocked_local.assert_called_once()
        mocked_xhshow.assert_called_once()

    def test_xhs_signer_does_not_fallback_on_programming_errors(self):
        with patch(
            "app.spiders.xiaohongshu.sign.sign_with_local_algorithm",
            side_effect=TypeError("programming bug"),
        ) as mocked_local, patch("app.spiders.xiaohongshu.sign.sign_with_xhshow") as mocked_xhshow:
            with self.assertRaises(TypeError):
                sign_xiaohongshu_headers(
                    uri="/api/sns/web/v1/user_posted",
                    data={"num": 20},
                    cookie_str="a1=demo-a1",
                    method="GET",
                )

        mocked_local.assert_called_once()
        mocked_xhshow.assert_not_called()

    def test_local_xhs_crc32_uses_precomputed_table(self):
        table_id = id(xhs_sign_module.XHS_CRC32_TABLE)
        self.assertEqual(len(XHS_CRC32_TABLE), 256)
        self.assertEqual(_signed_crc32("demo-b1"), _signed_crc32("demo-b1"))
        self.assertEqual(id(xhs_sign_module.XHS_CRC32_TABLE), table_id)

    def test_local_xhs_fingerprint_is_stable_per_cookie_not_global(self):
        fp_a = _minimal_fingerprint({"a1": "account-a", "web_session": "session-a"})
        fp_a_repeat = _minimal_fingerprint({"a1": "account-a", "web_session": "session-a"})
        fp_b = _minimal_fingerprint({"a1": "account-b", "web_session": "session-b"})

        self.assertEqual(fp_a["x36"], fp_a_repeat["x36"])
        self.assertEqual(fp_a["x43"], fp_a_repeat["x43"])
        self.assertNotEqual(fp_a["x43"], fp_b["x43"])

    def test_local_xhs_get_sign_string_preserves_query_params(self):
        content = _build_sign_string(
            "/api/sns/web/v1/user_posted",
            {"image_formats": "jpg,webp,avif", "cursor": "", "num": 20},
            "GET",
        )
        self.assertEqual(
            content,
            "/api/sns/web/v1/user_posted?image_formats=jpg,webp,avif&cursor=&num=20",
        )

    def test_local_xhs_signer_supports_fixed_timestamp(self):
        headers = sign_with_local_algorithm(
            uri="/api/sns/web/v1/feed",
            data={"source_note_id": "note-1"},
            cookie_str="a1=demo-a1",
            method="POST",
            timestamp=1700000000.123,
        )
        self.assertEqual(headers["X-T"], "1700000000123")
        self.assertTrue(headers["X-S"].startswith("XYS_"))

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

    def test_extract_first_url_from_share_text(self):
        text = "66 小明发布了一篇小红书笔记，快来看吧！ https://xhslink.com/a/AbCdEF，复制本条信息打开小红书"
        self.assertEqual(extract_first_url(text), "https://xhslink.com/a/AbCdEF")

    def test_parse_creator_lookup_input_supports_prefixed_account(self):
        info = parse_creator_lookup_input("小红书号: test_creator")
        self.assertIsNotNone(info)
        self.assertEqual(info.keyword, "test_creator")

    def test_parse_creator_lookup_input_supports_at_handle(self):
        info = parse_creator_lookup_input("@test_creator")
        self.assertIsNotNone(info)
        self.assertEqual(info.keyword, "test_creator")

    def test_parse_creator_lookup_input_supports_numeric_handle(self):
        info = parse_creator_lookup_input("742635074")
        self.assertIsNotNone(info)
        self.assertEqual(info.keyword, "742635074")

    def test_extract_video_candidates_prefers_backup_no_watermark_url(self):
        candidates = extract_video_candidates(
            {
                "type": "video",
                "note_id": "note-3",
                "video": {
                    "media": {
                        "stream": {
                            "h264": [
                                {
                                    "master_url": "http://sns-video-v6.xhscdn.com/stream/1/110/259/demo_259.mp4",
                                    "backup_url": "http://sns-bak-v1.xhscdn.com/stream/1/110/259/demo_259.mp4",
                                },
                                {
                                    "master_url": "http://sns-video-v6.xhscdn.com/stream/1/110/114/demo_114.mp4",
                                    "backup_url": "http://sns-bak-v1.xhscdn.com/stream/1/110/114/demo_114.mp4",
                                },
                            ]
                        }
                    }
                },
            }
        )
        self.assertEqual(candidates[0], "http://sns-bak-v1.xhscdn.com/stream/1/110/114/demo_114.mp4")

    def test_extract_video_candidates_keeps_origin_key_only_as_fallback(self):
        candidates = extract_video_candidates(
            {
                "type": "video",
                "note_id": "note-4",
                "video": {
                    "consumer": {"origin_video_key": "stream/origin/demo.mp4"},
                    "media": {
                        "stream": {
                            "h264": [
                                {
                                    "master_url": "http://sns-video-v6.xhscdn.com/stream/1/110/114/demo_114.mp4",
                                    "backup_url": "http://sns-bak-v1.xhscdn.com/stream/1/110/114/demo_114.mp4",
                                }
                            ]
                        }
                    },
                },
            }
        )
        self.assertEqual(candidates[0], "http://sns-bak-v1.xhscdn.com/stream/1/110/114/demo_114.mp4")
        self.assertEqual(candidates[-1], "http://sns-video-bd.xhscdn.com/stream/origin/demo.mp4")

    def test_build_items_falls_back_to_note_id_when_title_sanitizes_to_untitled(self):
        builder = XiaohongshuTaskBuilder()
        items = builder.build_items(
            {
                "note_id": "note-fallback",
                "type": "normal",
                "title": "...",
                "desc": "...",
                "user": {"nickname": "作者"},
                "images_data": [{"image_url": "https://cdn.example.com/1.jpg"}],
            },
            trace_id_factory=lambda suffix: f"{suffix}-trace",
            referer="https://www.xiaohongshu.com/explore/note-fallback",
            user_agent="ua-demo",
            cookie_str="a1=demo",
        )
        self.assertEqual(items[0].title, "note-fallback_1")

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
        self.assertNotIn("folder_name", items[0].meta)
        self.assertNotIn("use_subdir", items[0].meta)

    def test_build_items_returns_one_item_per_image_note_entry(self):
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
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "图文笔记_1")
        self.assertEqual(items[1].title, "图文笔记_2")
        self.assertEqual(items[0].meta["content_type"], "image")
        self.assertEqual(items[1].meta["content_type"], "image")
        self.assertEqual(items[0].meta["image_index"], 1)
        self.assertEqual(items[1].meta["image_index"], 2)
        self.assertEqual(items[0].meta["image_total"], 2)
        self.assertNotIn("folder_name", items[0].meta)
        self.assertNotIn("use_subdir", items[0].meta)
        self.assertEqual(items[0].url, "https://cdn.example.com/1.jpg")
        self.assertEqual(items[1].url, "https://cdn.example.com/2.webp")

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

    @patch("app.spiders.xiaohongshu.spider.requests.get")
    def test_normalize_keyword_resolves_share_short_url(self, mocked_get):
        spider = XiaohongshuSpider("test", {})
        mocked_get.return_value.url = (
            "https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8"
            "?xsec_token=demo-token&xsec_source=pc_search"
        )
        normalized = spider._normalize_keyword(
            "复制这条信息，打开【小红书】App查看精彩内容！ https://xhslink.com/a/demo，"
        )
        self.assertEqual(
            normalized,
            "https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8"
            "?xsec_token=demo-token&xsec_source=pc_search",
        )

    def test_classify_input_preserves_plain_text_keyword(self):
        spider = XiaohongshuSpider("穿搭关键词", {})
        self.assertEqual(spider._classify_input("穿搭关键词"), ("keyword", "穿搭关键词"))

    def test_classify_input_supports_creator_lookup_mode(self):
        spider = XiaohongshuSpider("@test_creator", {})
        self.assertEqual(spider._classify_input("@test_creator"), ("creator_lookup", "test_creator"))

    def test_classify_input_supports_numeric_creator_lookup_mode(self):
        spider = XiaohongshuSpider("742635074", {})
        self.assertEqual(spider._classify_input("742635074"), ("creator_lookup", "742635074"))

    def test_classify_input_supports_creator_id_mode(self):
        spider = XiaohongshuSpider("5eb8e1d400000000010075ae", {})
        self.assertEqual(
            spider._classify_input("5eb8e1d400000000010075ae"),
            ("creator_id", "5eb8e1d400000000010075ae"),
        )

    def test_extract_creator_search_candidates_accepts_common_user_payload(self):
        spider = XiaohongshuSpider("test", {})
        candidates = spider._extract_creator_search_candidates(
            {
                "items": [
                    {
                        "user": {
                            "user_id": "5eb8e1d400000000010075ae",
                            "xsec_token": "demo-token",
                            "xsec_source": "pc_search",
                        }
                    }
                ]
            }
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].user_id, "5eb8e1d400000000010075ae")
        self.assertEqual(candidates[0].xsec_token, "demo-token")

    def test_extract_search_ref_supports_note_card_shape(self):
        spider = XiaohongshuSpider("test", {})
        ref = spider._extract_search_ref(
            {
                "model_type": "note",
                "note_card": {
                    "note_id": "66fad51c000000001b0224b8",
                    "xsec_token": "token-from-note-card",
                },
                "xsec_source": "pc_search",
            }
        )
        self.assertEqual(
            ref,
            {
                "note_id": "66fad51c000000001b0224b8",
                "xsec_source": "pc_search",
                "xsec_token": "token-from-note-card",
                "title": "",
                "author": "",
                "note_type": "",
            },
        )

    def test_extract_search_ref_supports_note_info_shape(self):
        spider = XiaohongshuSpider("test", {})
        ref = spider._extract_search_ref(
            {
                "model_type": "note",
                "note_info": {
                    "note_id": "66fad51c000000001b0224b9",
                    "xsec_token": "token-from-note-info",
                },
                "xsec_source": "pc_search",
            }
        )
        self.assertEqual(
            ref,
            {
                "note_id": "66fad51c000000001b0224b9",
                "xsec_source": "pc_search",
                "xsec_token": "token-from-note-info",
                "title": "",
                "author": "",
                "note_type": "",
            },
        )

    def test_collect_search_refs_keeps_search_page_size_stable_when_limit_is_one(self):
        spider = XiaohongshuSpider("美女", {"max_items": 1})
        mocked_client = Mock()
        mocked_client.search_notes.return_value = {
            "items": [
                {
                    "id": "note-1",
                    "xsec_source": "pc_search",
                    "xsec_token": "token-1",
                }
            ],
            "has_more": False,
        }

        refs = spider._collect_search_refs(mocked_client, "美女")

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["note_id"], "note-1")
        mocked_client.search_notes.assert_called_once()
        self.assertEqual(mocked_client.search_notes.call_args.kwargs["page_size"], 20)

    def test_collect_creator_refs_logs_final_candidate_count_when_limit_is_reached(self):
        spider = XiaohongshuSpider("主页", {"max_items": 2})
        mocked_client = Mock()
        mocked_client.get_creator_notes.return_value = {
            "notes": [
                {"note_id": "note-1", "xsec_source": "pc_feed", "xsec_token": "token-1"},
                {"note_id": "note-2", "xsec_source": "pc_feed", "xsec_token": "token-2"},
            ],
            "has_more": False,
        }

        with patch.object(spider, "log") as mocked_log:
            refs = spider._collect_creator_refs(
                mocked_client,
                CreatorUrlInfo(user_id="user-1", xsec_token="token", xsec_source="pc_feed"),
            )

        self.assertEqual(len(refs), 2)
        mocked_log.assert_any_call("📚 主页候选累计 2/2")

    def test_handle_multi_refs_logs_processed_detail_progress(self):
        spider = XiaohongshuSpider("主页", {"stream_downloads": False})
        refs = [
            {"note_id": "note-1", "xsec_source": "pc_feed", "xsec_token": "token-1"},
            {"note_id": "note-2", "xsec_source": "pc_feed", "xsec_token": "token-2"},
        ]

        def fetch_detail(_client, ref):
            if ref["note_id"] == "note-2":
                return {"note_id": "note-2"}
            return None

        with patch.object(spider, "_fetch_note_detail", side_effect=fetch_detail), patch.object(
            spider,
            "_pause_between_detail_requests",
        ) as mocked_pause, patch.object(
            spider,
            "_emit_note_items",
            return_value=1,
        ), patch.object(spider, "log") as mocked_log:
            spider._handle_multi_refs_streaming(Mock(), refs, "a1=demo")

        self.assertTrue(
            any(
                "2/2" in str(call.args[0]) and "1" in str(call.args[0])
                for call in mocked_log.call_args_list
            )
        )
        mocked_pause.assert_not_called()

    def test_handle_multi_refs_waits_for_user_selection_by_default(self):
        spider = XiaohongshuSpider("主页", {})
        self.assertFalse(spider._should_stream_download_items())
        refs = [
            {"note_id": "note-1", "xsec_source": "pc_feed", "xsec_token": "token-1"},
            {"note_id": "note-2", "xsec_source": "pc_feed", "xsec_token": "token-2"},
        ]

        events = []

        def fetch_detail(_client, ref):
            events.append(f"fetch:{ref['note_id']}")
            return {"note_id": ref["note_id"]}

        def ask_selection(items):
            events.append("select")
            self.assertEqual([item["note_id"] for item in items], ["note-1", "note-2"])
            return [0, 1]

        with patch.object(spider, "_fetch_note_detail", side_effect=fetch_detail), patch.object(
            spider,
            "_emit_note_items",
            return_value=1,
        ) as mocked_emit, patch.object(spider, "ask_user_selection", side_effect=ask_selection) as mocked_selection:
            spider._handle_multi_refs(Mock(), refs, "a1=demo")

        self.assertEqual(mocked_emit.call_count, 2)
        mocked_selection.assert_called_once()
        self.assertEqual(events[0], "select")
        self.assertCountEqual(events[1:], ["fetch:note-1", "fetch:note-2"])

    def test_handle_multi_refs_streams_items_only_when_explicitly_enabled(self):
        spider = XiaohongshuSpider("主页", {"stream_downloads": True})
        self.assertTrue(spider._should_stream_download_items())
        refs = [
            {"note_id": "note-1", "xsec_source": "pc_feed", "xsec_token": "token-1"},
            {"note_id": "note-2", "xsec_source": "pc_feed", "xsec_token": "token-2"},
        ]

        def fetch_detail(_client, ref):
            return {"note_id": ref["note_id"]}

        with patch.object(spider, "_fetch_note_detail", side_effect=fetch_detail), patch.object(
            spider,
            "_emit_note_items",
            return_value=1,
        ) as mocked_emit, patch.object(spider, "ask_user_selection") as mocked_selection:
            spider._handle_multi_refs(Mock(), refs, "a1=demo")

        self.assertEqual(mocked_emit.call_count, 2)
        mocked_selection.assert_not_called()

    def test_handle_multi_refs_keeps_manual_selection_when_stream_disabled(self):
        spider = XiaohongshuSpider("主页", {"stream_downloads": False})
        refs = [
            {"note_id": "note-1", "xsec_source": "pc_feed", "xsec_token": "token-1"},
            {"note_id": "note-2", "xsec_source": "pc_feed", "xsec_token": "token-2"},
        ]

        fetched_refs = []

        def fetch_detail(_client, ref):
            fetched_refs.append(ref["note_id"])
            return {"note_id": ref["note_id"]}

        with patch.object(spider, "_fetch_note_detail", side_effect=fetch_detail), patch.object(
            spider, "ask_user_selection", return_value=[1]
        ) as mocked_selection, patch.object(
            spider,
            "_emit_note_items",
            return_value=1,
        ) as mocked_emit:
            spider._handle_multi_refs(Mock(), refs, "a1=demo")

        mocked_selection.assert_called_once()
        mocked_emit.assert_called_once()
        self.assertEqual(mocked_emit.call_args.args[0]["note_id"], "note-2")
        self.assertEqual(fetched_refs, ["note-2"])

    def test_stream_default_does_not_override_patched_selection_strategy(self):
        spider = XiaohongshuSpider("主页", {})

        def ask_user_selection_sync(_self, _items):
            return [0]

        spider.ask_user_selection = MethodType(ask_user_selection_sync, spider)

        self.assertFalse(spider._should_stream_download_items())

    def test_detail_worker_count_is_capped_for_fast_batches(self):
        self.assertEqual(XiaohongshuSpider._detail_worker_count(100), 8)
        self.assertEqual(XiaohongshuSpider._detail_worker_count(3), 3)

    def test_fetch_note_detail_falls_back_to_html_when_feed_returns_empty(self):
        spider = XiaohongshuSpider("主页", {})
        mocked_client = Mock()
        mocked_client.get_note_detail.return_value = {}
        mocked_client.get_note_detail_from_html.return_value = {"note_id": "note-1", "type": "video"}

        with patch.object(spider.parser, "normalize_note", return_value={"note_id": "note-1", "type": "video"}) as mocked_normalize:
            detail = spider._fetch_note_detail(
                mocked_client,
                {"note_id": "note-1", "xsec_source": "pc_search", "xsec_token": "token-1"},
            )

        self.assertEqual(detail, {"note_id": "note-1", "type": "video"})
        mocked_client.get_note_detail_from_html.assert_called_once_with(
            note_id="note-1",
            xsec_source="pc_search",
            xsec_token="token-1",
        )
        mocked_normalize.assert_called_once()

    def test_fetch_note_detail_triggers_cooldown_on_461(self):
        spider = XiaohongshuSpider("主页", {})
        mocked_client = Mock()
        response = Mock(status_code=461)
        http_error = requests.HTTPError("status code 461")
        http_error.response = response
        mocked_client.get_note_detail.side_effect = http_error

        with patch.object(spider, "_pause_between_requests") as mocked_pause, patch.object(spider, "log") as mocked_log:
            detail = spider._fetch_note_detail(
                mocked_client,
                {"note_id": "note-1", "xsec_source": "pc_search", "xsec_token": "token-1"},
            )

        self.assertIsNone(detail)
        mocked_pause.assert_called_once_with(multiplier=4.0)
        mocked_log.assert_any_call("⏳ 小红书返回 461，触发限流冷却后继续")

    @patch.object(XiaohongshuSpider, "_collect_search_refs")
    @patch.object(XiaohongshuSpider, "_handle_multi_refs")
    @patch.object(XiaohongshuSpider, "_lookup_creator_by_keyword", return_value=None)
    @patch.object(XiaohongshuSpider, "_ensure_cookie_string", return_value="a1=demo")
    @patch.object(XiaohongshuSpider, "_build_client")
    def test_creator_lookup_falls_back_to_keyword_search(
        self,
        mocked_build_client,
        _mocked_ensure_cookie,
        _mocked_lookup,
        mocked_handle_multi_refs,
        mocked_collect_search_refs,
    ):
        spider = XiaohongshuSpider("@test_creator", {})
        mocked_build_client.return_value.check_cookie_ready.return_value = True
        mocked_build_client.return_value.probe_login_status.return_value = True
        mocked_collect_search_refs.return_value = [{"note_id": "note-1", "xsec_source": "pc_search", "xsec_token": ""}]

        spider.run()

        mocked_collect_search_refs.assert_called_once_with(mocked_build_client.return_value, "test_creator")
        mocked_handle_multi_refs.assert_called_once()

    @patch.object(XiaohongshuSpider, "_handle_note_url")
    @patch.object(XiaohongshuSpider, "_ensure_cookie_string", return_value="a1=demo")
    @patch.object(XiaohongshuSpider, "_build_client")
    def test_run_routes_note_url_to_note_handler(self, mocked_build_client, _mocked_ensure_cookie, mocked_handle_note_url):
        spider = XiaohongshuSpider(
            "https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8?xsec_token=demo-token&xsec_source=pc_search",
            {},
        )
        mocked_build_client.return_value.check_cookie_ready.return_value = True
        mocked_build_client.return_value.probe_login_status.return_value = True

        spider.run()

        mocked_handle_note_url.assert_called_once()
        note_info = mocked_handle_note_url.call_args.args[1]
        self.assertEqual(note_info.note_id, "66fad51c000000001b0224b8")
        self.assertEqual(note_info.xsec_token, "demo-token")
        self.assertEqual(mocked_handle_note_url.call_args.kwargs["referer"], spider.keyword)

    @patch.object(XiaohongshuSpider, "_collect_creator_refs")
    @patch.object(XiaohongshuSpider, "_handle_multi_refs")
    @patch.object(XiaohongshuSpider, "_ensure_cookie_string", return_value="a1=demo")
    @patch.object(XiaohongshuSpider, "_build_client")
    def test_run_routes_creator_id_to_creator_collection(
        self,
        mocked_build_client,
        _mocked_ensure_cookie,
        mocked_handle_multi_refs,
        mocked_collect_creator_refs,
    ):
        spider = XiaohongshuSpider("5eb8e1d400000000010075ae", {})
        mocked_build_client.return_value.check_cookie_ready.return_value = True
        mocked_build_client.return_value.probe_login_status.return_value = True
        mocked_collect_creator_refs.return_value = [{"note_id": "note-1", "xsec_source": "pc_feed", "xsec_token": ""}]

        spider.run()

        mocked_collect_creator_refs.assert_called_once()
        creator = mocked_collect_creator_refs.call_args.args[1]
        self.assertEqual(creator.user_id, "5eb8e1d400000000010075ae")
        mocked_handle_multi_refs.assert_called_once_with(
            mocked_build_client.return_value,
            mocked_collect_creator_refs.return_value,
            "a1=demo",
        )

    def test_extract_creator_candidates_from_note_search_prefers_relevant_author(self):
        spider = XiaohongshuSpider("@test_creator", {})
        candidates = spider._extract_creator_candidates_from_note_search(
            {
                "items": [
                    {
                        "xsec_source": "pc_search",
                        "note_card": {
                            "display_title": "test_creator 今日更新",
                            "user": {
                                "user_id": "5eb8e1d400000000010075ae",
                                "nickname": "test_creator",
                                "xsec_token": "token-a",
                            },
                        },
                    },
                    {
                        "xsec_source": "pc_search",
                        "note_card": {
                            "display_title": "其他作者",
                            "user": {
                                "user_id": "5eb8e1d400000000010075af",
                                "nickname": "other",
                                "xsec_token": "token-b",
                            },
                        },
                    },
                ]
            },
            "test_creator",
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].user_id, "5eb8e1d400000000010075ae")
        self.assertEqual(candidates[0].note_hint, "test_creator 今日更新")

    @patch.object(XiaohongshuSpider, "_lookup_creator_by_browser_search")
    def test_lookup_creator_by_keyword_falls_back_to_browser_search_when_note_search_empty(self, mocked_browser_lookup):
        spider = XiaohongshuSpider("@test_creator", {})
        mocked_browser_lookup.return_value = CreatorUrlInfo(
            user_id="5eb8e1d400000000010075ae",
            xsec_token="token",
            xsec_source="pc_search",
        )
        mocked_client = Mock()
        mocked_client.search_notes.return_value = {"items": [], "has_more": False}

        result = spider._lookup_creator_by_keyword(mocked_client, CreatorLookupInfo(keyword="test_creator"))

        self.assertIsNotNone(result)
        self.assertEqual(result.user_id, "5eb8e1d400000000010075ae")
        mocked_browser_lookup.assert_called_once()

    def test_browser_entrypoints_use_configured_timeout(self):
        bootstrap_code = XiaohongshuSpider._bootstrap_cookie_string.__code__
        lookup_code = XiaohongshuSpider._lookup_creator_by_browser_search.__code__

        self.assertIn("_configured_timeout_ms", bootstrap_code.co_names)
        self.assertIn("_configured_timeout_ms", lookup_code.co_names)
        self.assertIn(60, bootstrap_code.co_consts)
        self.assertIn(60, lookup_code.co_consts)

class XiaohongshuDownloaderTests(unittest.TestCase):
    @patch("app.core.downloaders.xiaohongshu.XiaohongshuDownloader._download_with_strategy_fallback")
    def test_video_download_passes_headers_and_cookie_to_strategy(self, mocked_download_with_strategy_fallback):
        downloader = XiaohongshuDownloader()
        from app.models import VideoItem

        item = VideoItem(url="https://cdn.example.com/video.mp4", title="视频", source="xiaohongshu")
        item.meta.update(
            {
                "referer": "https://www.xiaohongshu.com/explore/demo",
                "ua": "ua-demo",
                "cookie": "a1=demo",
            }
        )

        downloader.download(item, "D:/downloads/demo.mp4", lambda _value: None, lambda: False)

        headers = mocked_download_with_strategy_fallback.call_args.kwargs["headers"]
        self.assertEqual(headers["Referer"], "https://www.xiaohongshu.com/explore/demo")
        self.assertEqual(headers["User-Agent"], "ua-demo")
        self.assertEqual(headers["Cookie"], "a1=demo")

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
        saved_paths = [call.kwargs["save_path"] for call in mocked_download_http_file.call_args_list]
        first_path = next(path for path in saved_paths if path.endswith("_1.jpeg"))
        self.assertTrue(any(path.endswith("_2.webp") for path in saved_paths))
        self.assertEqual(item.local_path, first_path)
        self.assertEqual(progresses[-1], 100)

    @patch("app.core.downloaders.xiaohongshu.XiaohongshuDownloader._download_http_file")
    def test_gallery_download_reports_aggregate_byte_progress(self, mocked_download_http_file):
        def fake_download_http_file(**kwargs):
            callback = kwargs["progress_callback"]
            callback(50, bytes_downloaded=512, bytes_total=1024)
            callback(100, bytes_downloaded=1024, bytes_total=1024)

        mocked_download_http_file.side_effect = fake_download_http_file
        downloader = XiaohongshuDownloader()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "note.mp4")
            from app.models import VideoItem

            item = VideoItem(url="https://cdn.example.com/cover.jpg", title="gallery-byte", source="xiaohongshu")
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
            events = []

            def progress_callback(value, **kwargs):
                events.append((value, kwargs))

            downloader.download(item, save_path, progress_callback, lambda: False)

        byte_events = [kwargs for _value, kwargs in events if kwargs.get("bytes_downloaded")]
        self.assertTrue(byte_events)
        self.assertEqual(max(event["bytes_downloaded"] for event in byte_events), 2048)
        self.assertEqual(max(event["bytes_total"] for event in byte_events), 2048)
        self.assertEqual(events[-1][0], 100)

    @patch("app.core.downloaders.xiaohongshu.XiaohongshuDownloader._download_http_file")
    def test_gallery_progress_callback_failure_does_not_stop_downloads(self, mocked_download_http_file):
        downloader = XiaohongshuDownloader()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "note.mp4")
            from app.models import VideoItem

            item = VideoItem(url="https://cdn.example.com/cover.jpg", title="gallery", source="xiaohongshu")
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

            def progress_callback(_value):
                raise RuntimeError("ui callback failed")

            downloader.download(item, save_path, progress_callback, lambda: False)

        self.assertEqual(mocked_download_http_file.call_count, 2)

    @patch("app.core.downloaders.xiaohongshu.XiaohongshuDownloader._download_http_file")
    def test_gallery_download_uses_safe_stem_from_save_path(self, mocked_download_http_file):
        downloader = XiaohongshuDownloader()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "163_40kg   淡颜系高马尾.jpeg")
            from app.models import VideoItem

            item = VideoItem(url="https://cdn.example.com/cover.jpg", title="163/40kg   淡颜系高马尾", source="xiaohongshu")
            item.meta.update(
                {
                    "is_gallery": True,
                    "images_data": [{"image_url": "https://cdn.example.com/1.jpg"}],
                    "cookie": "a1=demo",
                }
            )

            downloader.download(item, save_path, lambda _value: None, lambda: False)

        first_path = mocked_download_http_file.call_args_list[0].kwargs["save_path"]
        self.assertTrue(first_path.endswith("163_40kg   淡颜系高马尾_1.jpeg"))

    def test_gallery_worker_count_scales_for_image_batches(self):
        def fake_get(section, key, default=None):
            if (section, key) == ("download", "max_concurrent"):
                return 5
            if (section, key) == ("download", "image_respects_concurrency"):
                return False
            return default

        with patch("app.core.downloaders.xiaohongshu.cfg.get", side_effect=fake_get):
            self.assertEqual(XiaohongshuDownloader._gallery_image_worker_count(100), 10)
            self.assertEqual(XiaohongshuDownloader._gallery_image_worker_count(4), 4)

    def test_gallery_worker_count_can_follow_regular_concurrency(self):
        def fake_get(section, key, default=None):
            if (section, key) == ("download", "max_concurrent"):
                return 3
            if (section, key) == ("download", "image_respects_concurrency"):
                return True
            return default

        with patch("app.core.downloaders.xiaohongshu.cfg.get", side_effect=fake_get):
            self.assertEqual(XiaohongshuDownloader._gallery_image_worker_count(100), 3)
            self.assertEqual(XiaohongshuDownloader._gallery_image_worker_count(2), 2)

if __name__ == "__main__":
    unittest.main()
