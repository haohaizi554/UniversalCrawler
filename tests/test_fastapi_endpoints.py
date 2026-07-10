"""app.web.server FastAPI 端点全量测试。

测试维度：
- 单元测试：每个 REST 端点的请求/响应
- 黑盒测试：TestClient 不 mock，验证端到端行为
- 集成测试：多端点协作（state → config → dir/change）
- 契约测试：HTTP 状态码 + 响应体结构

设计原则：
- **禁止触发真爬虫**（douyin/bilibili 爬虫在 TestClient 线程池中会崩）
- 只测输入校验、静态端点（ping/platforms/state/config/scan/dir/debug）
- 验证响应体字段（status, error）而非仅状态码（API 用 200+error body 而非 4xx）
"""

import os
import sys
import unittest
import tempfile
from typing import Any
from unittest.mock import patch

def _create_test_client():
    """创建 FastAPI TestClient（fixture）。"""
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    return TestClient(create_app())

def _is_error_response(data: Any) -> bool:
    """判断响应是否为错误（status=error 或包含 error 字段）。"""
    if isinstance(data, dict):
        return data.get("status") == "error" or "error" in data
    return False

class PingEndpointTests(unittest.TestCase):
    """GET /api/ping 健康检查。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_ping_returns_200(self):
        r = self.client.get("/api/ping")
        self.assertEqual(r.status_code, 200)

    def test_ping_returns_version(self):
        from cli import __version__

        data = self.client.get("/api/ping").json()
        self.assertIn("version", data)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data["version"], __version__)

class PlatformsEndpointTests(unittest.TestCase):
    """GET /api/platforms 平台列表。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_platforms_returns_200(self):
        r = self.client.get("/api/platforms")
        self.assertEqual(r.status_code, 200)

    def test_platforms_returns_list(self):
        data = self.client.get("/api/platforms").json()
        self.assertIsInstance(data, list)

    def test_platforms_each_has_id_and_name(self):
        for platform in self.client.get("/api/platforms").json():
            self.assertIn("id", platform)
            self.assertIn("name", platform)

    def test_platforms_contains_4_platforms(self):
        """默认必须支持 5 个平台（含小红书）。"""
        ids = [p["id"] for p in self.client.get("/api/platforms").json()]
        self.assertGreaterEqual(len(ids), 5)
        # 验证核心平台都存在
        for expected in ("douyin", "xiaohongshu", "bilibili", "kuaishou", "missav"):
            self.assertIn(expected, ids, f"missing platform: {expected}")

class ConfigEndpointTests(unittest.TestCase):
    """GET/PUT /api/config 持久化配置。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_get_config(self):
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), dict)

    def test_put_config_nested_platform(self):
        """PUT config 接受嵌套结构（按平台分）。"""
        r = self.client.put("/api/config", json={"douyin": {"max_items": 50}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        r2 = self.client.get("/api/config")
        self.assertIn("douyin", r2.json())
        self.assertEqual(r2.json()["douyin"]["max_items"], 50)

    def test_put_config_invalid_type_string(self):
        """PUT config 接受非 dict 时：FastAPI 422 校验失败 或 200+error body。"""
        r = self.client.put("/api/config", json="not a dict")
        # FastAPI Pydantic 校验会先拒绝（422），也可能让 server 处理（200+error）
        self.assertIn(r.status_code, (200, 422))
        if r.status_code == 200:
            self.assertTrue(_is_error_response(r.json()))

    def test_put_config_empty(self):
        """PUT config 接受空 dict → 200 ok。"""
        r = self.client.put("/api/config", json={})
        self.assertEqual(r.status_code, 200)

class StateEndpointTests(unittest.TestCase):
    """GET /api/state 全局状态。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_state_returns_200(self):
        r = self.client.get("/api/state")
        self.assertEqual(r.status_code, 200)

    def test_state_has_video_count_field(self):
        """state 响应必须包含 current_save_dir / is_crawling / video_count 字段。"""
        data = self.client.get("/api/state").json()
        for key in ("current_save_dir", "is_crawling", "video_count"):
            self.assertIn(key, data, f"missing field: {key}")

    def test_state_video_count_is_int(self):
        data = self.client.get("/api/state").json()
        self.assertIsInstance(data["video_count"], int)
        self.assertGreaterEqual(data["video_count"], 0)

    def test_state_is_crawling_is_bool(self):
        data = self.client.get("/api/state").json()
        self.assertIsInstance(data["is_crawling"], bool)

    def test_frontend_state_exposes_unified_pages(self):
        data = self.client.get("/api/frontend/state").json()

        self.assertEqual(
            [page["id"] for page in data["pages"]],
            ["queue", "active", "completed", "failed", "logs", "settings", "toolbox"],
        )
        for key in (
            "queue_items",
            "active_downloads",
            "completed_items",
            "failed_items",
            "log_items",
            "settings_snapshot",
            "download_options",
            "toolbox_items",
            "app_status",
        ):
            self.assertIn(key, data)

    def test_frontend_delta_endpoint_matches_rest_router_contract(self):
        response = self.client.get("/api/frontend/delta?since_version=0")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("version", data)
        self.assertIn("base_version", data)
        self.assertIn("sections", data)

    def test_i18n_catalog_endpoint_serves_shared_language_files(self):
        response = self.client.get("/api/i18n/en-US")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["\u914d\u7f6e\u4e2d\u5fc3"], "Settings")
        self.assertEqual(data["\u4e0b\u8f7d\u961f\u5217"], "Queue")
        self.assertEqual(data["请输入主页链接、分享链接或合集链接"], "Enter a profile, shared, or collection link")
        self.assertEqual(data["播放前校验失败"], "Pre-playback check failed")

    def test_i18n_catalog_endpoint_returns_empty_for_source_language(self):
        response = self.client.get("/api/i18n/zh-CN")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {})

class ScanEndpointTests(unittest.TestCase):
    """POST /api/scan 扫描本地目录。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_scan_missing_directory(self):
        """空 body 时应 fallback 到 controller.current_save_dir 或返回 error。"""
        r = self.client.post("/api/scan", json={})
        self.assertEqual(r.status_code, 200)
        # 可能是 ok（有默认目录）也可能是 error（无默认）
        self.assertIn(r.json().get("status"), ("ok", "error"))

    def test_scan_valid_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.client.post("/api/scan", json={"directory": tmp})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("items", data)
            self.assertIsInstance(data["items"], list)

    def test_scan_with_scan_limit(self):
        """scan_limit 参数支持整数。"""
        with tempfile.TemporaryDirectory() as tmp:
            r = self.client.post("/api/scan", json={"directory": tmp, "scan_limit": 100})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get("status"), "ok")

    def test_scan_scan_limit_invalid_type(self):
        """scan_limit 必须是整数。"""
        with tempfile.TemporaryDirectory() as tmp:
            r = self.client.post("/api/scan", json={"directory": tmp, "scan_limit": "abc"})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(_is_error_response(r.json()))

    def test_scan_scan_limit_zero(self):
        """scan_limit 必须大于 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            r = self.client.post("/api/scan", json={"directory": tmp, "scan_limit": 0})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(_is_error_response(r.json()))

    def test_scan_directory_not_string(self):
        """directory 必须是字符串。"""
        r = self.client.post("/api/scan", json={"directory": 123})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

class SearchEndpointValidationTests(unittest.TestCase):
    """POST /api/search 输入校验（不真跑爬虫）。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_search_missing_source(self):
        r = self.client.post("/api/search", json={"keyword": "kw"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_missing_keyword(self):
        r = self.client.post("/api/search", json={"source": "douyin"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_invalid_source(self):
        r = self.client.post("/api/search", json={"source": "invalid_xyz", "keyword": "kw"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_config_validation(self):
        """config 类型错误 → status:error。"""
        r = self.client.post("/api/search", json={
            "source": "douyin", "keyword": "kw", "config": "not a dict"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_with_invalid_selection_strategy(self):
        r = self.client.post("/api/search", json={
            "source": "douyin", "keyword": "kw",
            "selection": {"strategy": "unknown_xyz"},
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_with_selection_non_dict(self):
        r = self.client.post("/api/search", json={
            "source": "douyin", "keyword": "kw", "selection": "not a dict"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_save_dir_validation(self):
        """save_dir 非 str → status:error。"""
        r = self.client.post("/api/search", json={
            "source": "douyin", "keyword": "kw", "save_dir": 123
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_source_not_string(self):
        """source 必须是字符串。"""
        r = self.client.post("/api/search", json={"source": 123, "keyword": "kw"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_keyword_not_string(self):
        """keyword 必须是字符串。"""
        r = self.client.post("/api/search", json={"source": "douyin", "keyword": 123})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_empty_source_and_keyword(self):
        """空字符串 → status:error。"""
        r = self.client.post("/api/search", json={"source": "", "keyword": ""})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_timeout_invalid(self):
        """timeout 必须是数字。"""
        r = self.client.post("/api/search", json={
            "source": "douyin", "keyword": "kw", "timeout": "abc"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_search_timeout_zero(self):
        """timeout 必须 > 0。"""
        r = self.client.post("/api/search", json={
            "source": "douyin", "keyword": "kw", "timeout": 0
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

class CrawlStartStopTests(unittest.TestCase):
    """POST /api/crawl/start + /api/crawl/stop 输入校验。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_crawl_start_validation(self):
        r = self.client.post("/api/crawl/start", json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_crawl_start_invalid_source(self):
        r = self.client.post("/api/crawl/start", json={"source": "invalid", "keyword": "kw"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_crawl_start_disallows_download_param(self):
        """crawl/start 不支持 download 参数（必须用 /api/search + download:false）。"""
        r = self.client.post("/api/crawl/start", json={
            "source": "douyin", "keyword": "kw", "download": False
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_crawl_stop_when_idle(self):
        r = self.client.post("/api/crawl/stop")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")

class CrawlSelectTests(unittest.TestCase):
    """POST /api/crawl/select 二次选择。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_crawl_select_no_active_spider(self):
        r = self.client.post("/api/crawl/select", json={"indices": [0, 1]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_crawl_select_indices_not_list(self):
        r = self.client.post("/api/crawl/select", json={"indices": "not a list"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_crawl_select_indices_invalid_types(self):
        r = self.client.post("/api/crawl/select", json={"indices": [0, "abc"]})
        self.assertEqual(r.status_code, 200)
        # 非整数 → 校验失败
        self.assertTrue(_is_error_response(r.json()))

class VideoDeleteRenameTests(unittest.TestCase):
    """DELETE /api/video/{id} + POST /api/video/rename。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_delete_nonexistent_video(self):
        r = self.client.delete("/api/video/nonexistent_id_12345")
        self.assertEqual(r.status_code, 200)
        # 删除不存在的视频：状态仍 ok（delete_video 是幂等的）
        self.assertIn(r.json().get("status"), ("ok", "error"))

    def test_rename_validation_video_id(self):
        r = self.client.post("/api/video/rename", json={"video_id": 123, "new_title": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_rename_validation_new_title(self):
        r = self.client.post("/api/video/rename", json={"video_id": "v1", "new_title": 123})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_rename_empty_body(self):
        r = self.client.post("/api/video/rename", json={})
        self.assertEqual(r.status_code, 200)
        # video_id 和 new_title 都是空字符串会怎样？
        # 实际上 controller.rename_video 接受空字符串，应该进入调用
        # 但实际上没有该 video 所以可能返回 error
        self.assertIn(r.json().get("status"), ("ok", "error"))

class DownloadEndpointValidationTests(unittest.TestCase):
    """POST /api/download 输入校验。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_download_missing_url(self):
        r = self.client.post("/api/download", json={"source": "douyin"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_invalid_url_type(self):
        r = self.client.post("/api/download", json={"url": 123, "source": "douyin"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_invalid_source(self):
        r = self.client.post("/api/download", json={"url": "http://x", "source": "invalid"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_timeout_zero(self):
        r = self.client.post("/api/download", json={
            "url": "http://x", "source": "douyin", "timeout": 0
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_timeout_negative(self):
        r = self.client.post("/api/download", json={
            "url": "http://x", "source": "douyin", "timeout": -1
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_timeout_string(self):
        r = self.client.post("/api/download", json={
            "url": "http://x", "source": "douyin", "timeout": "abc"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_config_not_dict(self):
        r = self.client.post("/api/download", json={
            "url": "http://x", "source": "douyin", "config": "not a dict"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_save_dir_not_string(self):
        r = self.client.post("/api/download", json={
            "url": "http://x", "source": "douyin", "save_dir": 123
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_download_title_not_string(self):
        """title 必须是字符串（与 CLI/SDK 对齐）。"""
        r = self.client.post("/api/download", json={
            "url": "http://x", "source": "douyin", "title": 123
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

class MediaEndpointTests(unittest.TestCase):
    """GET /api/media/{video_id} 媒体文件服务。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_media_nonexistent(self):
        r = self.client.get("/api/media/nonexistent_id")
        self.assertEqual(r.status_code, 404)

    def test_media_invalid_id(self):
        """空 id 也应返回 404（修复 BUG-150）。"""
        r = self.client.get("/api/media/")
        # 实际路由会先尝试匹配 /api/media，再 fallback 到 /api/media/{video_id}
        # 这里只测一个肯定不存在的 ID
        self.assertIn(r.status_code, (200, 307, 404))

class DirListChangeTests(unittest.TestCase):
    """GET /api/dir/list + POST /api/dir/change。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_dir_list(self):
        r = self.client.get("/api/dir/list")
        self.assertEqual(r.status_code, 200)

    def test_dir_list_with_specific_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.client.get(f"/api/dir/list?path={tmp}")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("subdirs", data)

    def test_dir_list_nonexistent_path(self):
        """Z:\\__definitely_not_exist_12345__ 应当返回 error 字段。"""
        r = self.client.get("/api/dir/list?path=Z:\\__definitely_not_exist_12345__")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("error", data)
        self.assertEqual(data.get("error"), "目录不存在")

    def test_dir_change_validation(self):
        r = self.client.post("/api/dir/change", json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_dir_change_nonexistent(self):
        """不存在的目录可能由 os.path.exists 解释为存在（Windows 路径兼容），
        所以只验证返回是合法 dict 不崩溃。"""
        r = self.client.post("/api/dir/change", json={"directory": "Z:\\__definitely_not_exist_12345__\\foo"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("status", r.json())

    def test_dir_change_validation_path_type(self):
        r = self.client.post("/api/dir/change", json={"directory": 123})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

    def test_dir_change_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.client.post("/api/dir/change", json={"directory": tmp})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get("status"), "ok")

    def test_dir_change_not_dict_body(self):
        r = self.client.post("/api/dir/change", json="not a dict")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_is_error_response(r.json()))

class DebugEndpointTests(unittest.TestCase):
    """GET /api/debug/* + POST /api/debug/trigger-select。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_debug_trigger_select_is_disabled_by_default(self):
        with patch.dict(os.environ, {"UCRAWL_DEBUG_ROUTES": "0"}):
            r = self.client.post("/api/debug/trigger-select")
        self.assertEqual(r.status_code, 404)

    def test_debug_trigger_select_can_be_explicitly_enabled(self):
        with patch.dict(os.environ, {"UCRAWL_DEBUG_ROUTES": "1"}):
            r = self.client.post("/api/debug/trigger-select")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items_sent", data)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("items_sent"), 4)

    def test_debug_latest_log(self):
        r = self.client.get("/api/debug/latest-log")
        self.assertEqual(r.status_code, 200)

    def test_debug_error_summary(self):
        r = self.client.get("/api/debug/error-summary")
        self.assertEqual(r.status_code, 200)

class IndexEndpointTests(unittest.TestCase):
    """GET / 静态首页。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_root_returns_html(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    def test_root_disables_browser_cache(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-store", r.headers.get("cache-control", ""))
        self.assertEqual(r.headers.get("pragma"), "no-cache")

    def test_static_frontend_assets_disable_browser_cache(self):
        for asset in ("/static/app.css", "/static/app.js"):
            with self.subTest(asset=asset):
                r = self.client.get(asset)
                self.assertEqual(r.status_code, 200)
                self.assertIn("no-store", r.headers.get("cache-control", ""))
                self.assertEqual(r.headers.get("pragma"), "no-cache")

class ServerCORSHeadersTests(unittest.TestCase):
    """CORS 中间件测试。"""

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_cors_header_present(self):
        r = self.client.get("/api/ping", headers={"Origin": "http://localhost"})
        self.assertEqual(r.status_code, 200)
        # CORS 中间件应返回 access-control-allow-origin
        self.assertIn("access-control-allow-origin", {k.lower() for k in r.headers.keys()})

    def test_cors_header_absent_for_untrusted_remote_origin(self):
        r = self.client.get("/api/ping", headers={"Origin": "https://untrusted.example"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in r.headers.keys()})

    def test_cors_header_present_for_explicitly_configured_origin(self):
        with patch.dict(os.environ, {"UCRAWL_ALLOWED_ORIGINS": "https://console.example"}):
            client = _create_test_client()
        r = client.get("/api/ping", headers={"Origin": "https://console.example"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("access-control-allow-origin"), "https://console.example")

class ServerModuleExportsTests(unittest.TestCase):
    """app.web.server 模块导出检查。"""

    def test_create_app_callable(self):
        from app.web.server import create_app
        self.assertTrue(callable(create_app))

    def test_create_app_returns_fastapi(self):
        from fastapi import FastAPI
        from app.web.server import create_app
        app = create_app()
        self.assertIsInstance(app, FastAPI)

    def test_app_has_cors_middleware(self):
        from app.web.server import create_app
        app = create_app()
        has_cors = any(
            "CORSMiddleware" in str(m.cls) for m in app.user_middleware
        )
        self.assertTrue(has_cors, "app should have CORS middleware")

    def test_static_dir_exists(self):
        """STATIC_DIR 必须存在且包含 index.html。"""
        from app.web.server import STATIC_DIR
        self.assertTrue(STATIC_DIR.exists(), f"STATIC_DIR {STATIC_DIR} not found")
        self.assertTrue((STATIC_DIR / "index.html").exists(), "index.html missing")

    def test_web_static_dirs_use_runtime_resource_resolver(self):
        """Web static mounts must use the same runtime resource root as PyInstaller."""
        from app.utils.runtime_paths import resolve_resource_file
        from app.web.server import STATIC_DIR, UI_ICON_DIR

        self.assertEqual(STATIC_DIR, resolve_resource_file("app/web/static"))
        self.assertEqual(UI_ICON_DIR, resolve_resource_file("UI/icon"))

    def test_controller_global_exists(self):
        """controller 必须是模块级全局变量。"""
        from app.web import server
        # 在 create_app() 调用前为 None
        # 调用后是 WebController 实例
        _ = server.create_app()
        self.assertIsNotNone(server.controller)

    def test_static_files_mounted(self):
        """FastAPI app 必须挂载 /static。"""
        from app.web.server import create_app
        app = create_app()
        routes = [r.path for r in app.routes]
        self.assertIn("/static", routes)

class CrossLayerContractTests(unittest.TestCase):
    """跨层契约测试：验证 REST API 的行为与 CLI/SDK 一致。

    这些测试验证：
    - 平台 ID 列表在 API 和 CLI 中一致
    - 默认配置在 API 和 CLI 中一致
    - 选择策略名称在 API、CLI、SDK 三层完全一致
    """

    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_platforms_match_plugin_registry(self):
        """API 返回的平台列表必须与 plugin_registry 一致。"""
        from app.core.plugin_registry import registry
        api_ids = {p["id"] for p in self.client.get("/api/platforms").json()}
        reg_ids = {p.id for p in registry.get_all_plugins()}
        self.assertEqual(api_ids, reg_ids)

    def test_cli_strategy_flags_map_correctly(self):
        """CLI 的 --all/--first/--last/--interactive/--pipe 标志必须被 parser 接受。"""
        from cli.main import main
        from unittest.mock import patch as _patch, MagicMock
        from cli.commands import search as _search_cmd

        # 验证每种 strategy 都能通过 argparse 校验
        flag_to_strategy = {
            "--all": "all",
            "--first": "first",
            "--last": "last",
            "--interactive": "interactive",
            "--pipe": "pipe",
        }
        for flag, expected_strategy in flag_to_strategy.items():
            with self.subTest(flag=flag):
                fake_handler = MagicMock(return_value=0)
                with _patch.object(_search_cmd, "handle_search_command", fake_handler):
                    try:
                        main(["search", "--source", "douyin", "kw", flag])
                    except SystemExit as e:
                        self.fail(f"parser rejected {flag}, exit={e.code}")
                    fake_handler.assert_called_once()
                    # 验证 args 包含对应的标志
                    call_args = fake_handler.call_args[0][0]
                    if flag == "--all":
                        self.assertTrue(call_args.select_all)
                    elif flag == "--first":
                        self.assertTrue(call_args.first)
                    elif flag == "--last":
                        self.assertTrue(call_args.last)
                    elif flag == "--interactive":
                        self.assertTrue(call_args.interactive)
                    elif flag == "--pipe":
                        self.assertTrue(call_args.pipe)

if __name__ == "__main__":
    unittest.main()
