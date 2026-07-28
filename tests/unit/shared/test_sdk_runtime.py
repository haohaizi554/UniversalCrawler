"""Unit tests for shared.sdk_runtime.UcrawlSDK.

测试维度：
- 单元测试：参数校验、selection 解析、资源接口幂等
- 黑盒测试：不 mock CLIRunner，跑真实 SDK
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, MagicMock

class UcrawlSDKInitTests(unittest.TestCase):
    """UcrawlSDK 初始化测试。"""

    def test_init_with_defaults(self):
        """无参初始化必须能跑。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK()
        self.assertIsNotNone(sdk.save_dir)
        self.assertFalse(sdk.verbose)
        self.assertEqual(sdk.default_config, {})

    def test_init_with_save_dir(self):
        """显式 save_dir 必须被保存。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK(save_dir="/tmp/test_dl")
        self.assertEqual(sdk.save_dir, "/tmp/test_dl")

    def test_init_invalid_save_dir_type(self):
        """save_dir 非 str/None 必须抛 TypeError。"""
        from shared.sdk_runtime import UcrawlSDK
        with self.assertRaises(TypeError):
            UcrawlSDK(save_dir=123)

    def test_init_invalid_config_type(self):
        """config 非 dict/None 必须抛 TypeError。"""
        from shared.sdk_runtime import UcrawlSDK
        with self.assertRaises(TypeError):
            UcrawlSDK(config="not a dict")

    def test_context_manager(self):
        """with 语句必须正确 enter/exit。"""
        from shared.sdk_runtime import UcrawlSDK
        with UcrawlSDK() as sdk:
            self.assertIsNotNone(sdk)
        sdk.close()

class UcrawlSDKSelectionResolveTests(unittest.TestCase):
    """_resolve_selection 测试。"""

    def setUp(self):
        from shared.sdk_runtime import UcrawlSDK
        self.sdk = UcrawlSDK()

    def test_none_returns_auto(self):
        """selection=None → AutoSelection。"""
        from shared.selection_runtime import AutoSelection
        self.assertIsInstance(self.sdk._resolve_selection(None), AutoSelection)

    def test_str_all(self):
        """'all' → RuleSelection(all_items=True)。"""
        from shared.selection_runtime import RuleSelection
        s = self.sdk._resolve_selection("all")
        self.assertIsInstance(s, RuleSelection)
        self.assertTrue(s.all)

    def test_str_first(self):
        """'first' → RuleSelection(first=True)。"""
        from shared.selection_runtime import RuleSelection
        s = self.sdk._resolve_selection("first")
        self.assertTrue(s.first)

    def test_str_last(self):
        """'last' → RuleSelection(last=True)。"""
        from shared.selection_runtime import RuleSelection
        s = self.sdk._resolve_selection("last")
        self.assertTrue(s.last)

    def test_str_indices(self):
        """'0,2,5' → RuleSelection(select='0,2,5')。"""
        from shared.selection_runtime import RuleSelection
        s = self.sdk._resolve_selection("0,2,5")
        # RuleSelection.select 是方法，规则存储在 _select_rule 属性中
        self.assertEqual(s._select_rule, "0,2,5")

    def test_str_selection_typo_raises(self):
        """未知快捷词不能被当作索引规则并在运行时意外全选。"""
        with self.assertRaisesRegex(ValueError, "frist"):
            self.sdk._resolve_selection("frist")

    def test_str_interactive(self):
        """'interactive' → InteractiveTTYSelection。"""
        from shared.interactive_selection import InteractiveTTYSelection
        s = self.sdk._resolve_selection("interactive")
        self.assertIsInstance(s, InteractiveTTYSelection)

    def test_str_pipe(self):
        """'pipe' → PipeSelection。"""
        from shared.pipe_selection import PipeSelection
        s = self.sdk._resolve_selection("pipe")
        self.assertIsInstance(s, PipeSelection)

    def test_list_returns_preload(self):
        """list[int] → PipeSelection(preloaded_choices=[[...]])。"""
        from shared.pipe_selection import PipeSelection
        s = self.sdk._resolve_selection([0, 2, 5])
        self.assertIsInstance(s, PipeSelection)
        self.assertEqual(s._preloaded, [[0, 2, 5]])

    def test_dict_strategy_all(self):
        """{"strategy": "all"} → RuleSelection(all=True)。"""
        from shared.selection_runtime import RuleSelection
        s = self.sdk._resolve_selection({"strategy": "all"})
        self.assertIsInstance(s, RuleSelection)
        self.assertTrue(s.all)

    def test_dict_strategy_rule(self):
        """{"strategy": "rule", "select": "0,2"} → RuleSelection。"""
        from shared.selection_runtime import RuleSelection
        s = self.sdk._resolve_selection({"strategy": "rule", "select": "0,2"})
        # RuleSelection.select 是方法，规则存储在 _select_rule 属性中
        self.assertEqual(s._select_rule, "0,2")

    def test_dict_strategy_rule_invalid_select_type(self):
        """{"strategy": "rule", "select": 123} → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection({"strategy": "rule", "select": 123})

    def test_dict_strategy_preload(self):
        """{"strategy": "preload", "choices": [[0], [1, 2]]} → PipeSelection。"""
        from shared.pipe_selection import PipeSelection
        s = self.sdk._resolve_selection({"strategy": "preload", "choices": [[0], [1, 2]]})
        self.assertIsInstance(s, PipeSelection)
        self.assertEqual(s._preloaded, [[0], [1, 2]])

    def test_dict_strategy_preload_not_2d(self):
        """{"strategy": "preload", "choices": [1, 2]} → TypeError（必须二维）。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection({"strategy": "preload", "choices": [1, 2]})

    def test_dict_strategy_preload_rejects_non_integer_indices(self):
        """预加载二维数组中的字符串和 bool 不能延迟到运行时。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection({"strategy": "preload", "choices": [[0, "1"]]})
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection({"strategy": "preload", "choices": [[True]]})

    def test_dict_strategy_unknown_raises(self):
        """{"strategy": "unknown"} → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk._resolve_selection({"strategy": "unknown"})

    def test_invalid_type_raises(self):
        """selection=123 → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk._resolve_selection(123)

class UcrawlSDKSearchValidationTests(unittest.TestCase):
    """search() 参数校验测试（不真跑爬虫）。"""

    def setUp(self):
        from shared.sdk_runtime import UcrawlSDK
        self.sdk = UcrawlSDK()

    def test_search_invalid_source_type(self):
        """source 非 str → TypeError。"""
        with patch("shared.sdk_runtime.CLIRunner"):
            with self.assertRaises(TypeError):
                self.sdk.search(123, "kw")

    def test_search_invalid_keyword_type(self):
        """keyword 非 str → TypeError。"""
        with patch("shared.sdk_runtime.CLIRunner"):
            with self.assertRaises(TypeError):
                self.sdk.search("douyin", 123)

    def test_search_empty_source(self):
        """source='' → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("", "kw")

    def test_search_empty_keyword(self):
        """keyword='' → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("douyin", "")

    def test_search_unknown_platform(self):
        """source='unknown' → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("unknown_platform", "kw")

    def test_search_invalid_timeout_type(self):
        """timeout='abc' → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", timeout="abc")

    def test_search_bool_timeout_is_not_numeric(self):
        """bool 是 int 的子类，但不能作为超时值进入范围校验。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", run_timeout=True)

    def test_search_negative_timeout(self):
        """timeout=0 → ValueError。"""
        with self.assertRaises(ValueError):
            self.sdk.search("douyin", "kw", timeout=0)
        with self.assertRaises(ValueError):
            self.sdk.search("douyin", "kw", timeout=-1)

    def test_search_invalid_download_type(self):
        """download='yes' → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", download="yes")

    def test_search_invalid_save_dir_type(self):
        """save_dir=123 → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", save_dir=123)

    def test_search_invalid_config_max_items(self):
        """max_items='abc' → TypeError。"""
        with self.assertRaises(TypeError):
            self.sdk.search("douyin", "kw", max_items="abc")

class UcrawlSDKSearchFunctionalTests(unittest.TestCase):
    """search() 实际功能测试（mock CLIRunner）。"""

    def test_search_returns_runner_result(self):
        """search() 必须原样返回 CLIRunner.run() 的结果。"""
        from shared.sdk_runtime import UcrawlSDK
        from shared.selection_runtime import RuleSelection
        sdk = UcrawlSDK()
        expected = {"status": "ok", "items": [], "logs": []}
        with patch("shared.sdk_runtime.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = expected
            result = sdk.search("douyin", "kw")
        self.assertEqual(result, expected)

    def test_search_reaches_real_runner_init_with_one_sdk_profile(self):
        from shared.cli_runner_runtime import CLIRunner
        from shared.sdk_runtime import UcrawlSDK, compose_runtime_config

        sdk = UcrawlSDK(save_dir="sdk-downloads")
        with patch(
            "shared.sdk_runtime.compose_runtime_config",
            wraps=compose_runtime_config,
        ) as compose_config, patch.object(
            CLIRunner,
            "run",
            autospec=True,
            return_value={"status": "ok", "items": []},
        ) as run:
            result = sdk.search("douyin", "cats", download=False)

        self.assertEqual(result["status"], "ok")
        runner = run.call_args.args[0]
        profile = runner.execution_profile
        self.assertIs(compose_config.call_args.kwargs["execution_profile"], profile)
        self.assertEqual(profile.host_surface, "sdk")
        self.assertTrue(profile.owner_id)
        self.assertEqual(
            profile.approved_roots,
            frozenset({Path("sdk-downloads").resolve()}),
        )

    def test_search_merges_default_config(self):
        """SDK 的 default_config 必须合并到 CLIRunner 的 config。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK(config={"max_items": 99, "timeout": 5})
        with patch("shared.sdk_runtime.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            sdk.search("douyin", "kw", max_items=10)
        # CLIRunner 必须被调用，config 含 max_items=10（本次覆盖了全局默认）
        runner_config = MockRunner.call_args.kwargs["config"]
        self.assertEqual(runner_config["max_items"], 10)
        self.assertEqual(runner_config["timeout"], 5)

    def test_search_skips_none_config_values(self):
        """None 值的 config key 必须被过滤（不覆盖默认值）。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK()
        with patch("shared.sdk_runtime.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            sdk.search("douyin", "kw", max_items=None)
        # max_items=None 被过滤 → config 不含 max_items
        runner_config = MockRunner.call_args.kwargs["config"]
        self.assertNotIn("max_items", runner_config)

    def test_search_missav_proxy_normalized(self):
        """missav 平台的 proxy 字段必须用 build_missav_proxy_url 转换。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK()
        with patch("shared.sdk_runtime.CLIRunner") as MockRunner:
            instance = MockRunner.return_value
            instance.run.return_value = {"status": "ok"}
            sdk.search("missav", "ABC", proxy="Clash (7890)")
        runner_config = MockRunner.call_args.kwargs["config"]
        self.assertEqual(runner_config["proxy"], "http://127.0.0.1:7890")

class UcrawlSDKCloseTests(unittest.TestCase):
    """close() 资源清理测试。"""

    def test_close_idempotent(self):
        """close() 必须幂等（多次调用不报错）。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK()
        sdk.close()
        sdk.close()  # 不应该抛异常

    def test_close_keeps_compatibility_interface(self):
        """close() 保留兼容接口且可重复调用。"""
        from shared.sdk_runtime import UcrawlSDK
        sdk = UcrawlSDK()
        sdk.close()
        sdk.close()

    def test_default_profile_has_stable_private_owner_and_local_tool_grants(self):
        """Changing the SDK owner per instance would orphan durable history."""
        from shared.execution_profile import DEFAULT_LOCAL_TOOL_PERMISSIONS
        from shared.sdk_runtime import UcrawlSDK

        with tempfile.TemporaryDirectory() as temp_dir:
            first_root = Path(temp_dir, "first")
            alias_of_first = first_root / ".." / "first"
            second_root = Path(temp_dir, "second")

            first = UcrawlSDK(save_dir=str(first_root))
            same = UcrawlSDK(save_dir=str(alias_of_first))
            different = UcrawlSDK(save_dir=str(second_root))

            self.assertEqual(
                first.execution_profile.owner_id,
                same.execution_profile.owner_id,
            )
            self.assertNotEqual(
                first.execution_profile.owner_id,
                different.execution_profile.owner_id,
            )
            self.assertNotIn(
                str(first_root.resolve()).casefold(),
                first.execution_profile.owner_id.casefold(),
            )
            canonical_text = os.path.normcase(
                os.path.normpath(str(first_root.expanduser().resolve()))
            )
            expected_digest = hashlib.sha256(
                canonical_text.encode("utf-8", errors="surrogatepass")
            ).hexdigest()
            self.assertEqual(
                first.execution_profile.owner_id,
                f"sdk:local:{expected_digest}",
            )
            self.assertRegex(
                first.execution_profile.owner_id,
                r"^sdk:local:[0-9a-f]{64}$",
            )
            self.assertEqual(
                first.execution_profile.tool_permissions,
                DEFAULT_LOCAL_TOOL_PERMISSIONS,
            )
            self.assertFalse(first.execution_profile.allow_external_plugins)

    def test_default_profile_owner_is_stable_across_process_restarts(self):
        """A process-derived owner would lose durable history after restart."""
        with tempfile.TemporaryDirectory() as temp_dir:
            save_root = str(Path(temp_dir, "durable-root"))
            script = (
                "import sys; "
                "from shared.sdk_runtime import UcrawlSDK; "
                "sdk = UcrawlSDK(save_dir=sys.argv[1]); "
                "print(sdk.execution_profile.owner_id); "
                "assert sdk.close() is True"
            )
            command = [sys.executable, "-c", script, save_root]
            first = subprocess.check_output(command, text=True).strip()
            second = subprocess.check_output(command, text=True).strip()

            self.assertEqual(first, second)
            self.assertNotIn(str(Path(save_root).resolve()).casefold(), first.casefold())

    def test_explicit_profile_is_preserved_and_call_save_dir_keeps_initial_owner(self):
        """An explicit host grant and the initial owner must not be silently replaced."""
        from shared.execution_profile import (
            DEFAULT_LOCAL_TOOL_PERMISSIONS,
            local_execution_profile,
        )
        from shared.sdk_runtime import UcrawlSDK

        with tempfile.TemporaryDirectory() as temp_dir:
            initial = Path(temp_dir, "initial")
            per_call = Path(temp_dir, "per-call")
            explicit = local_execution_profile(
                host_surface="sdk",
                owner_id="sdk:explicit",
                approved_roots=(initial,),
                tool_permissions=DEFAULT_LOCAL_TOOL_PERMISSIONS,
                allow_external_plugins=False,
            )
            supplied = UcrawlSDK(save_dir=str(initial), execution_profile=explicit)
            implicit = UcrawlSDK(save_dir=str(initial))

            self.assertIs(supplied.execution_profile, explicit)
            self.assertIs(supplied._execution_profile_for_save_dir(str(per_call)), explicit)
            derived = implicit._execution_profile_for_save_dir(str(per_call))
            self.assertEqual(derived.owner_id, implicit.execution_profile.owner_id)
            self.assertEqual(derived.approved_roots, frozenset({per_call.resolve()}))

    def test_tools_property_reentrant_construction_fails_fast_without_self_deadlock(self):
        """A facade constructor must not wait on its own reentrant ``sdk.tools`` call."""
        from shared.sdk_runtime import UcrawlSDK

        sdk = UcrawlSDK()
        factory_entered = threading.Event()
        access_finished = threading.Event()
        outcomes = {}

        class Facade:
            def close(self) -> bool:
                return True

        facade = Facade()

        def create_facade(*, execution_profile):
            self.assertIs(execution_profile, sdk.execution_profile)
            factory_entered.set()
            try:
                _ = sdk.tools
            except BaseException as error:
                outcomes["reentrant_error"] = error
            return facade

        def access_tools() -> None:
            try:
                outcomes["facade"] = sdk.tools
            except BaseException as error:
                outcomes["outer_error"] = error
            finally:
                access_finished.set()

        with patch("ucrawl.tools.ToolsAPI", side_effect=create_facade):
            worker = threading.Thread(target=access_tools, daemon=True)
            worker.start()
            self.assertTrue(factory_entered.wait(2.0))
            self.assertTrue(
                access_finished.wait(1.0),
                "same-thread sdk.tools reentrancy deadlocked facade construction",
            )

        self.assertIs(outcomes.get("facade"), facade)
        self.assertNotIn("outer_error", outcomes)
        self.assertIsInstance(outcomes.get("reentrant_error"), RuntimeError)
        self.assertTrue(sdk.close())

    def test_close_reentrant_during_tools_construction_fails_fast_without_sealing_sdk(self):
        """A facade constructor must not wait on its own reentrant ``sdk.close`` call."""
        from shared.sdk_runtime import UcrawlSDK

        sdk = UcrawlSDK()
        factory_entered = threading.Event()
        access_finished = threading.Event()
        outcomes = {}

        class Facade:
            def close(self) -> bool:
                return True

        facade = Facade()

        def create_facade(*, execution_profile):
            self.assertIs(execution_profile, sdk.execution_profile)
            factory_entered.set()
            try:
                sdk.close()
            except BaseException as error:
                outcomes["reentrant_error"] = error
            return facade

        def access_tools() -> None:
            try:
                outcomes["facade"] = sdk.tools
            except BaseException as error:
                outcomes["outer_error"] = error
            finally:
                access_finished.set()

        with patch("ucrawl.tools.ToolsAPI", side_effect=create_facade):
            worker = threading.Thread(target=access_tools, daemon=True)
            worker.start()
            self.assertTrue(factory_entered.wait(2.0))
            self.assertTrue(
                access_finished.wait(1.0),
                "same-thread sdk.close reentrancy deadlocked facade construction",
            )

        self.assertIs(outcomes.get("facade"), facade)
        self.assertNotIn("outer_error", outcomes)
        self.assertIsInstance(outcomes.get("reentrant_error"), RuntimeError)
        self.assertTrue(sdk.close())

    def test_tools_property_creates_one_facade_under_concurrent_access(self):
        """Removing creation serialization would leak duplicate runner pools."""
        from shared.sdk_runtime import UcrawlSDK

        sdk = UcrawlSDK()
        factory_entered = threading.Event()
        release_factory = threading.Event()
        factory_calls = 0

        class Facade:
            def close(self) -> bool:
                return True

        facade = Facade()

        def create_facade(*, execution_profile):
            nonlocal factory_calls
            self.assertIs(execution_profile, sdk.execution_profile)
            factory_calls += 1
            factory_entered.set()
            self.assertTrue(release_factory.wait(2.0))
            return facade

        with patch("ucrawl.tools.ToolsAPI", side_effect=create_facade):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(lambda: sdk.tools)
                self.assertTrue(factory_entered.wait(2.0))
                second = pool.submit(lambda: sdk.tools)
                release_factory.set()
                self.assertIs(first.result(timeout=2.0), facade)
                self.assertIs(second.result(timeout=2.0), facade)

        self.assertEqual(factory_calls, 1)
        self.assertTrue(sdk.close())

    def test_close_false_and_exception_retain_same_facade_for_retry(self):
        """Detaching before successful shutdown would make failed cleanup unrecoverable."""
        from shared.sdk_runtime import UcrawlSDK

        class RetriableFacade:
            def __init__(self):
                self.calls = 0

            def close(self) -> bool:
                self.calls += 1
                if self.calls == 1:
                    return False
                if self.calls == 2:
                    raise RuntimeError("cleanup unavailable")
                return True

        facade = RetriableFacade()
        sdk = UcrawlSDK()
        sdk._tools_api = facade

        self.assertFalse(sdk.close())
        self.assertIs(sdk._tools_api, facade)
        with self.assertRaisesRegex(RuntimeError, "UcrawlSDK is closed"):
            _ = sdk.tools
        with self.assertRaisesRegex(RuntimeError, "cleanup unavailable"):
            sdk.close()
        self.assertIs(sdk._tools_api, facade)
        self.assertTrue(sdk.close())
        self.assertIsNone(sdk._tools_api)

    def test_concurrent_close_waits_for_the_single_successful_shutdown(self):
        """A second close must not race the same facade shutdown."""
        from shared.sdk_runtime import UcrawlSDK

        close_entered = threading.Event()
        release_close = threading.Event()
        second_started = threading.Event()

        class BlockingFacade:
            calls = 0

            def close(self) -> bool:
                self.calls += 1
                close_entered.set()
                self.assert_release()
                return True

            @staticmethod
            def assert_release() -> None:
                if not release_close.wait(2.0):
                    raise AssertionError("test did not release facade close")

        facade = BlockingFacade()
        sdk = UcrawlSDK()
        sdk._tools_api = facade

        def close_second() -> bool:
            second_started.set()
            return sdk.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(sdk.close)
            self.assertTrue(close_entered.wait(2.0))
            second = pool.submit(close_second)
            self.assertTrue(second_started.wait(2.0))
            self.assertFalse(second.done())
            release_close.set()
            self.assertTrue(first.result(timeout=2.0))
            self.assertTrue(second.result(timeout=2.0))

        self.assertEqual(facade.calls, 1)

    def test_context_cleanup_failure_does_not_replace_body_exception(self):
        """Cleanup errors are secondary when the context body already failed."""
        from shared.sdk_runtime import UcrawlSDK

        class FailingFacade:
            def close(self) -> bool:
                raise RuntimeError("cleanup unavailable")

        sdk = UcrawlSDK()
        sdk._tools_api = FailingFacade()

        with self.assertRaisesRegex(ValueError, "body failed") as raised:
            with sdk:
                raise ValueError("body failed")

        self.assertTrue(
            any(
                "cleanup unavailable" in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )

    def test_context_cleanup_annotation_cannot_replace_hostile_body_exception(self):
        """Annotation lookup and cleanup formatting remain secondary failures."""
        from shared.sdk_runtime import UcrawlSDK

        class HostileBodyError(ValueError):
            def __getattribute__(self, name):
                if name == "add_note":
                    raise RuntimeError("annotation lookup failed")
                return super().__getattribute__(name)

        class UnprintableCleanupError(RuntimeError):
            def __str__(self) -> str:
                raise RuntimeError("cleanup formatting failed")

        class FailingFacade:
            def close(self) -> bool:
                raise UnprintableCleanupError()

        sdk = UcrawlSDK()
        sdk._tools_api = FailingFacade()
        body_error = HostileBodyError("body failed")

        with self.assertRaises(HostileBodyError) as raised:
            with sdk:
                raise body_error

        self.assertIs(raised.exception, body_error)

    def test_context_cleanup_metadata_cannot_replace_body_exception(self):
        """Hostile cleanup text and type metadata must remain secondary."""
        from shared.sdk_runtime import UcrawlSDK

        class HostileExceptionType(type):
            def __getattribute__(cls, name):
                if name == "__name__":
                    raise RuntimeError("cleanup type-name lookup failed")
                return super().__getattribute__(name)

        class HostileCleanupError(
            RuntimeError,
            metaclass=HostileExceptionType,
        ):
            def __str__(self) -> str:
                raise RuntimeError("cleanup formatting failed")

        class FailingFacade:
            def close(self) -> bool:
                raise HostileCleanupError()

        sdk = UcrawlSDK()
        sdk._tools_api = FailingFacade()
        body_error = ValueError("body failed")

        try:
            with sdk:
                raise body_error
        except BaseException as raised:
            same_body = raised is body_error
            notes = (
                tuple(getattr(raised, "__notes__", ()))
                if same_body
                else ()
            )
            raised.__traceback__ = None
            raised.__context__ = None
            raised.__cause__ = None
        else:  # pragma: no cover - the body always raises
            self.fail("context body exception was suppressed")

        self.assertTrue(same_body, "cleanup replaced the context body exception")
        self.assertIn(
            "UcrawlSDK cleanup failed with unknown error",
            notes,
        )

    def test_context_cleanup_state_recording_cannot_replace_body_exception(self):
        """A hostile SDK state target must not make cleanup replace the body error."""
        from shared.sdk_runtime import UcrawlSDK

        class HostileCleanupStateSDK(UcrawlSDK):
            def __setattr__(self, name, value):
                if name == "_last_cleanup_error" and getattr(
                    self,
                    "_reject_cleanup_state",
                    False,
                ):
                    raise RuntimeError("cleanup state recording failed")
                super().__setattr__(name, value)

        class FailingFacade:
            def close(self) -> bool:
                raise RuntimeError("cleanup unavailable")

        sdk = HostileCleanupStateSDK()
        sdk._tools_api = FailingFacade()
        sdk._reject_cleanup_state = True
        body_error = ValueError("body failed")

        with self.assertRaises(ValueError) as raised:
            with sdk:
                raise body_error

        self.assertIs(raised.exception, body_error)
        self.assertTrue(
            any(
                "cleanup unavailable" in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )

if __name__ == "__main__":
    unittest.main()
