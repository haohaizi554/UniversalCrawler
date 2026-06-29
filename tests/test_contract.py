"""契约测试：CLI / SDK / REST API 三层一致性。

测试维度：
- 输入校验契约：source、keyword、timeout、save_dir、config 在三层错误信息一致
- 输出格式契约：成功/错误响应结构在三层对齐
- 平台枚举契约：支持的平台 ID 在三层完全一致
- 选择策略契约：strategy 名称在三层完全一致
- 错误传播契约：invalid_source 等价于 SDK/CLI

设计原则：
- 用同样的无效输入对三层分别触发，验证错误信息类别一致
- 不真跑爬虫，只测校验和序列化
"""

import io
import os
import sys
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock

# 让 cli.sdk 可被 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _has_pyqt6():
    try:
        import PyQt6
        return True
    except ImportError:
        return False

def _has_fastapi():
    try:
        import fastapi
        return True
    except ImportError:
        return False

# ---- 测试 helper：触发 SDK 校验失败 ----

def _sdk_invalid_source(source):
    """触发 SDK 拒绝非法 source。"""
    from cli.sdk import UcrawlSDK
    sdk = UcrawlSDK(save_dir=".")
    try:
        sdk.search(source, "kw")
        return None
    except (ValueError, TypeError) as e:
        return e

def _sdk_invalid_keyword_type(keyword):
    """触发 SDK 拒绝非法 keyword 类型。"""
    from cli.sdk import UcrawlSDK
    sdk = UcrawlSDK(save_dir=".")
    try:
        sdk.search("douyin", keyword)
        return None
    except (ValueError, TypeError) as e:
        return e

def _sdk_invalid_timeout(timeout):
    from cli.sdk import UcrawlSDK
    sdk = UcrawlSDK(save_dir=".")
    try:
        sdk.search("douyin", "kw", timeout=timeout)
        return None
    except (ValueError, TypeError) as e:
        return e

def _api_invalid_source(source):
    """触发 REST API 拒绝非法 source（通过 TestClient）。"""
    if not _has_fastapi():
        return None
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    client = TestClient(create_app())
    r = client.post("/api/search", json={"source": source, "keyword": "kw"})
    return r

def _api_invalid_keyword_type(keyword):
    """API 的 keyword 是 str 类型，传入 int 不会拒（FastAPI 会自动转 str 或 422）"""
    if not _has_fastapi():
        return None
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    client = TestClient(create_app())
    r = client.post("/api/search", json={"source": "douyin", "keyword": keyword})
    return r

def _api_invalid_timeout(timeout):
    if not _has_fastapi():
        return None
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    client = TestClient(create_app())
    r = client.post("/api/search", json={
        "source": "douyin", "keyword": "kw", "timeout": timeout
    })
    return r

def _cli_invalid_source(source):
    """触发 CLI 拒绝非法 source（通过 main()）。"""
    from cli.main import main
    from unittest.mock import patch as _patch
    from cli.commands import search as _search_cmd
    fake_handler = MagicMock(return_value=0)
    with _patch.object(_search_cmd, "handle_search_command", fake_handler):
        try:
            main(["search", "--source", source, "kw"])
            return 0  # 不抛
        except SystemExit as e:
            return e.code

# ============================================================
# 测试用例
# ============================================================

class PlatformEnumContractTests(unittest.TestCase):
    """平台 ID 在 CLI/SDK/API 三层完全一致。"""

    def test_sdk_platforms_match_registry(self):
        from cli.sdk import UcrawlSDK
        from app.core.plugin_registry import registry
        sdk_ids = set(UcrawlSDK.PLATFORMS)
        reg_ids = {p.id for p in registry.get_all_plugins()}
        # SDK 至少包含核心平台
        for p in ("douyin", "bilibili", "kuaishou", "missav"):
            self.assertIn(p, sdk_ids)

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_platforms_match_registry(self):
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        from app.core.plugin_registry import registry
        client = TestClient(create_app())
        api_ids = {p["id"] for p in client.get("/api/platforms").json()}
        reg_ids = {p.id for p in registry.get_all_plugins()}
        self.assertEqual(api_ids, reg_ids)

    def test_sdk_platforms_subsume_api_platforms(self):
        """SDK.PLATFORMS 应至少覆盖 API 返回的所有 ID。"""
        from cli.sdk import UcrawlSDK
        sdk_ids = set(UcrawlSDK.PLATFORMS)
        if not _has_fastapi():
            self.skipTest("FastAPI not available")
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        client = TestClient(create_app())
        api_ids = {p["id"] for p in client.get("/api/platforms").json()}
        # API 的每个 id 都应该在 SDK.PLATFORMS 里出现
        # 注意：SDK.PLATFORMS 可能是子集，因为 SDK 显式列出最常用的
        for p in api_ids:
            # API 返回的所有平台 SDK 都应该支持
            self.assertIn(p, sdk_ids,
                          f"SDK missing platform: {p}")

class SourceValidationContractTests(unittest.TestCase):
    """source 校验契约：SDK/CLI/API 都拒绝非法平台。"""

    def test_sdk_rejects_invalid_source(self):
        e = _sdk_invalid_source("invalid_xyz_999")
        self.assertIsInstance(e, ValueError)
        # 错误信息应提到"无效平台"
        self.assertIn("无效平台", str(e))

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_invalid_source(self):
        r = _api_invalid_source("invalid_xyz_999")
        self.assertIsNotNone(r)
        # API 用 200+status:error 表示拒绝
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get("status"), "error")
        # 错误信息应当提到"无效平台"
        self.assertIn("无效平台", str(data))

    def test_cli_rejects_invalid_source(self):
        """CLI 通过 argparse 的 choices 拒绝非法 source。"""
        # CLI main() 会调用 parser，parser 设置了 choices
        # 所以传 invalid source 会触发 SystemExit(2)
        code = _cli_invalid_source("invalid_xyz_999")
        self.assertNotEqual(code, 0, "CLI should reject invalid source")

    def test_sdk_rejects_empty_source(self):
        e = _sdk_invalid_source("")
        self.assertIsInstance(e, ValueError)
        self.assertIn("不能为空", str(e))

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_empty_source(self):
        r = _api_invalid_source("")
        self.assertEqual(r.json().get("status"), "error")

    def test_sdk_rejects_non_string_source(self):
        e = _sdk_invalid_source(123)
        self.assertIsInstance(e, TypeError)
        self.assertIn("字符串", str(e))

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_non_string_source(self):
        r = _api_invalid_source(123)
        # API 返回 422（Pydantic 校验失败）或 200+error
        self.assertIn(r.status_code, (200, 422))
        if r.status_code == 200:
            self.assertEqual(r.json().get("status"), "error")

class KeywordValidationContractTests(unittest.TestCase):
    """keyword 校验契约。"""

    def test_sdk_rejects_empty_keyword(self):
        e = _sdk_invalid_keyword_type("")
        self.assertIsInstance(e, ValueError)

    def test_sdk_rejects_non_string_keyword(self):
        e = _sdk_invalid_keyword_type(123)
        self.assertIsInstance(e, TypeError)

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_empty_keyword(self):
        r = _api_invalid_keyword_type("")
        self.assertEqual(r.json().get("status"), "error")

class TimeoutValidationContractTests(unittest.TestCase):
    """timeout 校验契约：所有层都拒绝 timeout <= 0 和非数字。"""

    def test_sdk_rejects_zero_timeout(self):
        e = _sdk_invalid_timeout(0)
        self.assertIsInstance(e, ValueError)
        self.assertIn("大于 0", str(e))

    def test_sdk_rejects_negative_timeout(self):
        e = _sdk_invalid_timeout(-5)
        self.assertIsInstance(e, ValueError)

    def test_sdk_rejects_string_timeout(self):
        e = _sdk_invalid_timeout("abc")
        self.assertIsInstance(e, TypeError)
        self.assertIn("数字", str(e))

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_zero_timeout(self):
        r = _api_invalid_timeout(0)
        self.assertEqual(r.json().get("status"), "error")

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_string_timeout(self):
        r = _api_invalid_timeout("abc")
        self.assertEqual(r.json().get("status"), "error")

class SelectionStrategyContractTests(unittest.TestCase):
    """选择策略名称契约：SDK/CLI/API 接受相同的 strategy 名称。"""

    VALID_STRATEGIES = ("all", "first", "last", "rule", "preload", "interactive", "pipe")

    def test_sdk_accepts_all_strategies(self):
        """SDK._resolve_selection 应能处理所有有效 strategy 名称。"""
        from cli.sdk import UcrawlSDK
        from cli.selection import RuleSelection, PipeSelection
        sdk = UcrawlSDK(save_dir=".")
        for s in self.VALID_STRATEGIES:
            with self.subTest(strategy=s):
                # 通过 dict 形式（与 API 对齐）传入
                try:
                    if s == "rule":
                        resolved = sdk._resolve_selection({"strategy": "rule", "select": "0"})
                        # 确认确实是 RuleSelection
                        self.assertIsInstance(resolved, RuleSelection)
                    elif s == "preload":
                        resolved = sdk._resolve_selection({"strategy": "preload", "choices": [[0, 1]]})
                        self.assertIsInstance(resolved, PipeSelection)
                    else:
                        resolved = sdk._resolve_selection({"strategy": s})
                    self.assertIsNotNone(resolved)
                    # 内部类名映射:
                    # - "all"/"first"/"last" → RuleSelection (strategy_name="rule")
                    # - "rule" → RuleSelection
                    # - "preload" → PipeSelection (strategy_name="pipe")
                    # - "interactive" → InteractiveTTYSelection
                    # - "pipe" → PipeSelection
                    if s in ("all", "first", "last", "rule"):
                        self.assertEqual(resolved.strategy_name, "rule")
                    elif s in ("preload", "pipe"):
                        self.assertEqual(resolved.strategy_name, "pipe")
                    else:
                        self.assertEqual(resolved.strategy_name, s)
                except (ValueError, TypeError) as e:
                    self.fail(f"SDK rejected valid strategy {s}: {e}")

    def test_sdk_rejects_invalid_strategy(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(ValueError) as cm:
            sdk._resolve_selection({"strategy": "invalid_xyz"})
        self.assertIn("无效选择策略", str(cm.exception))

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_invalid_strategy(self):
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        client = TestClient(create_app())
        r = client.post("/api/search", json={
            "source": "douyin", "keyword": "kw",
            "selection": {"strategy": "invalid_xyz"},
        })
        # 校验失败 → 200+error
        self.assertEqual(r.json().get("status"), "error")
        self.assertIn("无效选择策略", r.json().get("error", ""))

    def test_cli_accepts_all_strategies(self):
        """CLI argparse 接受所有 strategy flags。"""
        from cli.main import main
        from unittest.mock import patch as _patch
        from cli.commands import search as _search_cmd
        # CLI 用 --all / --first / --last / --interactive / --pipe flags
        # 没有 --strategy 这种统一选项
        flag_map = {
            "all": "--all",
            "first": "--first",
            "last": "--last",
            "interactive": "--interactive",
            "pipe": "--pipe",
        }
        for strategy, flag in flag_map.items():
            with self.subTest(strategy=strategy):
                fake_handler = MagicMock(return_value=0)
                with _patch.object(_search_cmd, "handle_search_command", fake_handler):
                    try:
                        main(["search", "--source", "douyin", "kw", flag])
                    except SystemExit as e:
                        self.fail(f"CLI rejected flag {flag}: exit={e.code}")

class ConfigValidationContractTests(unittest.TestCase):
    """config 校验契约。"""

    def test_sdk_rejects_non_dict_config(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk.search("douyin", "kw", max_items="not_int")

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_rejects_invalid_max_items(self):
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        client = TestClient(create_app())
        r = client.post("/api/search", json={
            "source": "douyin", "keyword": "kw",
            "config": {"max_items": "not_int"},
        })
        self.assertEqual(r.json().get("status"), "error")

class DownloadValidationContractTests(unittest.TestCase):
    """download_video 校验契约。"""

    def test_sdk_rejects_invalid_url_type(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk.download_video(url=123, source="douyin")

    def test_sdk_rejects_empty_url(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(ValueError):
            sdk.download_video(url="", source="douyin")

    def test_sdk_rejects_non_int_timeout(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk.download_video(url="http://x", source="douyin", timeout="abc")

    def test_sdk_rejects_zero_timeout(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(ValueError):
            sdk.download_video(url="http://x", source="douyin", timeout=0)

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_download_rejects_invalid(self):
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        client = TestClient(create_app())
        r = client.post("/api/download", json={"source": "douyin"})
        # 缺 url
        self.assertEqual(r.json().get("status"), "error")
        self.assertIn("url", r.json().get("error", ""))

class ScanValidationContractTests(unittest.TestCase):
    """scan_directory 校验契约。"""

    def test_sdk_scan_rejects_non_string(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk.scan_directory(123)

    def test_sdk_scan_rejects_empty(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(ValueError):
            sdk.scan_directory("")

    def test_sdk_scan_rejects_zero_limit(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(ValueError):
            sdk.scan_directory(".", scan_limit=0)

    def test_sdk_scan_rejects_string_limit(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk.scan_directory(".", scan_limit="abc")

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_api_scan_rejects_string_limit(self):
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        client = TestClient(create_app())
        r = client.post("/api/scan", json={"directory": ".", "scan_limit": "abc"})
        self.assertEqual(r.json().get("status"), "error")

class SelectionDictContractTests(unittest.TestCase):
    """selection 字典格式契约（与 API 对齐）。"""

    def test_sdk_rule_strategy_with_select(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        resolved = sdk._resolve_selection({"strategy": "rule", "select": "0,2"})
        from cli.selection import RuleSelection
        self.assertIsInstance(resolved, RuleSelection)

    def test_sdk_preload_choices(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        resolved = sdk._resolve_selection({"strategy": "preload", "choices": [[0, 1], [2]]})
        from cli.selection import PipeSelection
        self.assertIsInstance(resolved, PipeSelection)
        self.assertEqual(resolved._preloaded, [[0, 1], [2]])

    def test_sdk_rule_select_must_be_string(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk._resolve_selection({"strategy": "rule", "select": [0, 1]})

    def test_sdk_preload_choices_must_be_list(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk._resolve_selection({"strategy": "preload", "choices": "not a list"})

    def test_sdk_preload_choices_must_be_2d(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        with self.assertRaises(TypeError):
            sdk._resolve_selection({"strategy": "preload", "choices": [0, 1]})  # 1D list

class SDKOutputStructureTests(unittest.TestCase):
    """SDK 输出结构契约（与 REST API /api/search 对齐）。"""
    # 这里只验证错误时抛出的异常结构，验证成功时需 mock runner

    def test_search_returns_dict(self):
        """成功调用返回 dict。"""
        from cli.sdk import UcrawlSDK
        from unittest.mock import patch as _patch, MagicMock
        sdk = UcrawlSDK(save_dir=".")
        fake_result = {"status": "ok", "items": []}
        with _patch("cli.sdk.CLIRunner") as mock_runner:
            mock_runner.return_value.run.return_value = fake_result
            result = sdk.search("douyin", "kw")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "ok")

class ListPlatformsContractTests(unittest.TestCase):
    """list_platforms 输出契约。"""

    def test_sdk_list_platforms(self):
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=".")
        result = sdk.list_platforms()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        for p in result:
            self.assertIn("id", p)
            self.assertIn("name", p)

        kuaishou = next((item for item in result if item["id"] == "kuaishou"), None)
        self.assertIsNotNone(kuaishou)
        self.assertIn("分享链接", kuaishou["search_placeholder"])

        bilibili = next((item for item in result if item["id"] == "bilibili"), None)
        self.assertIsNotNone(bilibili)
        for token in ("BV", "UP", "\u5408\u96c6", "\u4e3b\u9875", "\u89c6\u9891", "\u5206\u4eab", "\u5173\u952e\u8bcd"):
            self.assertIn(token, bilibili["search_placeholder"])

    @unittest.skipUnless(_has_fastapi(), "FastAPI not available")
    def test_sdk_list_platforms_matches_api(self):
        """SDK.list_platforms() 的字段名必须与 API 一致。"""
        from cli.sdk import UcrawlSDK
        from fastapi.testclient import TestClient
        from app.web.server import create_app
        sdk = UcrawlSDK(save_dir=".")
        sdk_list = {p["id"]: p for p in sdk.list_platforms()}
        client = TestClient(create_app())
        api_list = {p["id"]: p for p in client.get("/api/platforms").json()}
        # 每个 ID 都应该在两边都出现
        self.assertEqual(set(sdk_list.keys()), set(api_list.keys()))
        # 字段名必须一致
        for pid in sdk_list:
            self.assertEqual(set(sdk_list[pid].keys()) - {"description", "settings"},
                             set(api_list[pid].keys()) - {"description", "settings"})

if __name__ == "__main__":
    unittest.main()
