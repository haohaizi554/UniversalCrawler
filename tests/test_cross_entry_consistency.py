import argparse
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

def _create_test_client():
    from fastapi.testclient import TestClient
    from app.web.server import create_app, SESSION_TOKEN_HEADER

    client = TestClient(create_app())
    # 建立 session 并获取 token
    client.get("/api/ping")
    cookie_name = client.app.state.web_session_cookie_name
    session_id = client.cookies.get(cookie_name)
    context = client.app.state.web_session_registry.get_or_create(session_id)
    client._ucrawl_session_token = context.csrf_token
    client._ucrawl_token_header = SESSION_TOKEN_HEADER
    client._ucrawl_session_context = context
    # 授权 "downloads" 目录，使 API 请求中的 save_dir 通过目录权限校验
    context.approve_directory("downloads")
    return client

def _auth_headers(client):
    return {client._ucrawl_token_header: client._ucrawl_session_token}

def _normalize_selection(strategy) -> dict:
    return {
        "strategy_name": getattr(strategy, "strategy_name", ""),
        "preloaded": getattr(strategy, "_preloaded", None),
        "select_rule": getattr(strategy, "_select_rule", None),
        "all": getattr(strategy, "all", None),
        "first": getattr(strategy, "first", None),
        "last": getattr(strategy, "last", None),
    }

class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)

class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

class _FakeDownloadManager:
    last_video = None
    last_save_dir = None

    def __init__(self, max_concurrent=3):
        self.task_started = _FakeSignal()
        self.task_progress = _FakeSignal()
        self.task_finished = _FakeSignal()
        self.task_error = _FakeSignal()
        self.queue = SimpleNamespace(qsize=lambda: 0)
        self.workers = {}
        self._workers_lock = _NullLock()

    def add_task(self, item, save_dir):
        type(self).last_video = item
        type(self).last_save_dir = save_dir
        item.local_path = f"{save_dir}/demo.mp4"
        self.task_started.emit(item.id)
        self.task_progress.emit(item.id, 100)
        self.task_finished.emit(item.id)

    def stop_all(self):
        return None

class SearchEntryConsistencyTests(unittest.TestCase):
    def _cli_search_runner_kwargs(self):
        from cli.commands.search import add_search_arguments, handle_search_command

        parser = argparse.ArgumentParser()
        add_search_arguments(parser)
        args = parser.parse_args(
            [
                "--source",
                "missav",
                "ABC-123",
                "--save-dir",
                "downloads",
                "--config",
                '{"author":"alice"}',
                "--proxy",
                "Clash (7890)",
                "--run-timeout",
                "60",
                "--preload-choices",
                "0|1,2",
                "--no-download",
            ]
        )

        runner_cls = Mock()
        runner_cls.return_value.run.return_value = {"status": "ok"}
        with patch("cli.commands.search.CLIRunner", runner_cls), patch(
            "cli.commands.search.get_platform_defaults",
            return_value={"timeout": 10},
        ), patch(
            "cli.commands.search.build_missav_proxy_url",
            return_value="http://127.0.0.1:7890",
        ), patch(
            "cli.commands.search.validate_config_types",
            return_value=None,
        ), patch(
            "cli.commands.search.runtime.emit_result"
        ):
            exit_code = handle_search_command(args)

        self.assertEqual(exit_code, 0)
        return runner_cls.call_args.kwargs

    def _sdk_search_runner_kwargs(self):
        import cli.sdk as sdk_module

        runner_cls = Mock()
        runner_cls.__module__ = "unittest.mock"
        runner_cls.return_value.run.return_value = {"status": "ok"}

        with patch.object(sdk_module, "CLIRunner", runner_cls), patch(
            "shared.sdk_runtime.get_platform_defaults",
            return_value={"timeout": 10},
        ), patch(
            "shared.sdk_runtime.build_missav_proxy_url",
            return_value="http://127.0.0.1:7890",
        ), patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="missav")],
        ):
            sdk = sdk_module.UcrawlSDK(save_dir="downloads")
            result = sdk.search(
                "missav",
                "ABC-123",
                selection={"strategy": "preload", "choices": [[0], [1, 2]]},
                run_timeout=60,
                download=False,
                proxy="Clash (7890)",
                author="alice",
            )

        self.assertEqual(result["status"], "ok")
        return runner_cls.call_args.kwargs

    def _api_search_runner_kwargs(self):
        with patch(
            "app.web.workflows.merge_default_config",
            return_value={"timeout": 10, "author": "alice"},
        ), patch(
            "shared.runtime_options.build_missav_proxy_url",
            return_value="http://127.0.0.1:7890",
        ), patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="missav")],
        ), patch(
            "app.web.server.run_cli_search",
            return_value={"status": "ok"},
        ) as run_search:
            client = _create_test_client()
            response = client.post(
                "/api/search",
                json={
                    "source": "missav",
                    "keyword": "ABC-123",
                    "save_dir": "downloads",
                    "config": {"author": "alice"},
                    "proxy": "Clash (7890)",
                    "run_timeout": 60,
                    "selection": {"strategy": "preload", "choices": [[0], [1, 2]]},
                    "download": False,
                },
                headers=_auth_headers(client),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        return run_search.call_args.kwargs

    def test_search_normalization_matches_across_cli_sdk_and_api(self):
        cli_kwargs = self._cli_search_runner_kwargs()
        sdk_kwargs = self._sdk_search_runner_kwargs()
        api_kwargs = self._api_search_runner_kwargs()

        expected_config = {
            "timeout": 10,
            "author": "alice",
            "proxy": "http://127.0.0.1:7890",
            "folder_name": "alice",
            "use_subdir": True,
        }

        for kwargs in (cli_kwargs, sdk_kwargs, api_kwargs):
            self.assertEqual(kwargs["source"], "missav")
            self.assertEqual(kwargs["keyword"], "ABC-123")
            # API 端 require_directory 会将相对路径解析为绝对路径，统一用 abspath 比较
            # Windows 路径不区分大小写，用 normcase 规范化后比较
            self.assertEqual(
                os.path.normcase(os.path.abspath(kwargs["save_dir"])),
                os.path.normcase(os.path.abspath("downloads")),
            )
            self.assertEqual(kwargs["timeout"], 60.0)
            self.assertFalse(kwargs["download"])
            self.assertEqual(kwargs["config"], expected_config)

        expected_selection = {
            "strategy_name": "pipe",
            "preloaded": [[0], [1, 2]],
            "select_rule": None,
            "all": None,
            "first": None,
            "last": None,
        }
        self.assertEqual(_normalize_selection(cli_kwargs["selection_strategy"]), expected_selection)
        self.assertEqual(_normalize_selection(sdk_kwargs["selection_strategy"]), expected_selection)
        self.assertEqual(_normalize_selection(api_kwargs["selection_strategy"]), expected_selection)

class DownloadEntryConsistencyTests(unittest.TestCase):
    def _cli_download_config(self):
        from cli.commands.download import add_download_arguments, handle_download_command

        parser = argparse.ArgumentParser()
        add_download_arguments(parser)
        args = parser.parse_args(
            [
                "Demo",
                "--url",
                "https://example.com/video.mp4",
                "--source",
                "missav",
                "--save-dir",
                "downloads",
                "--timeout",
                "45",
                "--config",
                '{"author":"alice"}',
                "--proxy",
                "Clash (7890)",
                "--file-name",
                "demo",
            ]
        )

        sdk = Mock()
        sdk.download_video.return_value = {"status": "ok"}
        with patch("cli.commands.download.UcrawlSDK", return_value=sdk), patch(
            "cli.commands.download.build_missav_proxy_url",
            return_value="http://127.0.0.1:7890",
        ), patch(
            "cli.commands.download.validate_config_types",
            return_value=None,
        ), patch(
            "cli.commands.download.registry.get_plugin",
            return_value=object(),
        ), patch(
            "cli.commands.download.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="missav")],
        ), patch(
            "cli.commands.download.runtime.emit_result"
        ), patch(
            "cli.commands.download.sys.stderr.write"
        ):
            exit_code = handle_download_command(args)

        self.assertEqual(exit_code, 0)
        return sdk.download_video.call_args.kwargs["config"]

    def _api_download_config(self):
        fake_sdk = Mock()
        fake_sdk.download_video.return_value = {
            "status": "ok",
            "title": "Demo",
            "local_path": "downloads/demo.mp4",
            "meta": {},
        }

        with patch(
            "app.web.workflows.get_platform_defaults",
            return_value={"author": "alice"},
        ), patch(
            "app.web.workflows.validate_config_types",
            return_value=None,
        ), patch(
            "shared.runtime_options.build_missav_proxy_url",
            return_value="http://127.0.0.1:7890",
        ), patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="missav")],
        ), patch(
            "app.web.workflows.build_sdk",
            return_value=fake_sdk,
        ):
            client = _create_test_client()
            response = client.post(
                "/api/download",
                json={
                    "url": "https://example.com/video.mp4",
                    "source": "missav",
                    "title": "Demo",
                    "save_dir": "downloads",
                    "timeout": 45,
                    "config": {"author": "alice"},
                    "proxy": "Clash (7890)",
                    "file_name": "demo",
                },
                headers=_auth_headers(client),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        return fake_sdk.download_video.call_args.kwargs["config"]

    def test_download_config_matches_between_cli_and_api(self):
        cli_config = self._cli_download_config()
        api_config = self._api_download_config()
        expected_config = {
            "author": "alice",
            "proxy": "http://127.0.0.1:7890",
            "folder_name": "alice",
            "use_subdir": True,
            "file_name": "demo",
        }

        self.assertEqual(cli_config, expected_config)
        self.assertEqual(api_config, expected_config)

    def test_sdk_download_applies_same_bridge_to_internal_meta(self):
        import cli.sdk as sdk_module

        with patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="missav")],
        ), patch(
            "shared.sdk_runtime.get_platform_defaults",
            return_value={},
        ), patch(
            "shared.sdk_runtime.get_platform_download_defaults",
            return_value={},
        ), patch(
            "shared.sdk_runtime.build_missav_proxy_url",
            return_value="http://127.0.0.1:7890",
        ), patch(
            "app.core.download_manager.DownloadManager",
            _FakeDownloadManager,
        ):
            sdk = sdk_module.UcrawlSDK(save_dir="downloads")
            result = sdk.download_video(
                url="https://example.com/video.mp4",
                source="missav",
                title="Demo",
                save_dir="downloads",
                timeout=1,
                config={"author": "alice", "proxy": "Clash (7890)", "file_name": "demo"},
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content_type"], "video")
        self.assertEqual(result["meta"]["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(result["meta"]["author"], "alice")
        self.assertEqual(result["meta"]["folder_name"], "alice")
        self.assertTrue(result["meta"]["use_subdir"])
        self.assertEqual(result["meta"]["file_name"], "demo")

    def test_sdk_download_timeout_exposes_shutdown_summary(self):
        import cli.sdk as sdk_module

        class _SlowDownloadManager:
            def __init__(self, max_concurrent=3):
                self.task_started = _FakeSignal()
                self.task_progress = _FakeSignal()
                self.task_finished = _FakeSignal()
                self.task_error = _FakeSignal()
                self.queue = SimpleNamespace(qsize=lambda: 1)
                self.workers = {}
                self._workers_lock = _NullLock()

            def add_task(self, item, save_dir):
                item.local_path = f"{save_dir}/partial.mp4"
                self.task_started.emit(item.id)

            def stop_all(self):
                self.task_error.emit("unknown", "用户已停止")
                return {
                    "queued_tasks_cleared": 1,
                    "workers_requested": 1,
                    "unfinished_workers": ["worker-1"],
                    "all_workers_stopped": False,
                    "dispatcher_stopped": False,
                }

        with patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="douyin")],
        ), patch(
            "shared.sdk_runtime.get_platform_defaults",
            return_value={},
        ), patch(
            "shared.sdk_runtime.get_platform_download_defaults",
            return_value={},
        ), patch(
            "app.core.download_manager.DownloadManager",
            _SlowDownloadManager,
        ):
            sdk = sdk_module.UcrawlSDK(save_dir="downloads")
            result = sdk.download_video(
                url="https://example.com/video.mp4",
                source="douyin",
                title="Demo",
                save_dir="downloads",
                timeout=0.01,
            )

        self.assertEqual(result["status"], "timeout")
        self.assertIn("下载超时", result["error"])
        self.assertIn("后台任务仍在停止中", result["error"])
        self.assertEqual(result["local_path"], "downloads/partial.mp4")
        self.assertEqual(result["shutdown"]["unfinished_workers"], ["worker-1"])
        self.assertFalse(result["shutdown"]["all_workers_stopped"])
        self.assertFalse(result["shutdown"]["dispatcher_stopped"])

class EntryResultStructureConsistencyTests(unittest.TestCase):
    def test_search_success_payload_is_passthrough_across_cli_sdk_and_api(self):
        expected = {
            "status": "ok",
            "source": "douyin",
            "keyword": "kw",
            "save_dir": "downloads",
            "items": [{"id": "v1", "title": "Demo", "status": "✅ 完成", "progress": 100}],
            "logs": ["done"],
            "elapsed": 1.23,
            "selection_count": 0,
        }

        from shared.search_command_runtime import SearchCommandEnv, run_search_command

        cli_runner = Mock()
        cli_runner.return_value.run.return_value = expected
        cli_args = argparse.Namespace(
            source="douyin",
            keyword="kw",
            save_dir="downloads",
            config=None,
            max_items=None,
            max_pages=None,
            timeout=None,
            individual_only=False,
            priority=None,
            proxy=None,
            cookie=None,
            download_strategy=None,
            referer=None,
            ua=None,
            folder_name=None,
            use_subdir=None,
            file_name=None,
            content_type=None,
            quiet=True,
            pretty=False,
            run_timeout=None,
            no_download=False,
            select=None,
            exclude=None,
            select_all=False,
            first=False,
            last=False,
            interactive=False,
            pipe=False,
            preload_choices=None,
        )
        cli_env = SearchCommandEnv(
            CLIRunner_cls=cli_runner,
            selection_factory=SimpleNamespace(from_cli_args=lambda args, default_strategy=None: "selection"),
            get_platform_defaults=lambda source: {},
            get_default_save_dir=lambda: "downloads",
            build_missav_proxy_url=lambda proxy: proxy,
            validate_config_types=lambda config: None,
        )
        exit_code, cli_result = run_search_command(cli_args, env=cli_env)
        self.assertEqual(exit_code, 0)

        import cli.sdk as sdk_module

        sdk_runner = Mock()
        sdk_runner.__module__ = "unittest.mock"
        sdk_runner.return_value.run.return_value = expected
        with patch.object(sdk_module, "CLIRunner", sdk_runner), patch(
            "shared.sdk_runtime.get_platform_defaults",
            return_value={},
        ), patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="douyin")],
        ):
            sdk_result = sdk_module.UcrawlSDK(save_dir="downloads").search("douyin", "kw")

        with patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="douyin")],
        ), patch(
            "app.web.server.run_cli_search",
            return_value=expected,
        ):
            client = _create_test_client()
            api_result = client.post("/api/search", json={"source": "douyin", "keyword": "kw"}, headers=_auth_headers(client)).json()

        self.assertEqual(cli_result, expected)
        self.assertEqual(sdk_result, expected)
        self.assertEqual(api_result, expected)

    def test_download_error_payload_keeps_contract_across_cli_sdk_facade_and_api(self):
        expected = {
            "status": "error",
            "video_id": "v1",
            "url": "https://example.com/video.mp4",
            "source": "douyin",
            "title": "Demo",
            "error": "下载失败: boom",
            "save_dir": "downloads",
            "local_path": "",
            "content_type": "video",
            "meta": {"download_error": "下载失败: boom"},
            "elapsed": 0.1,
        }

        from shared.download_command_runtime import DownloadCommandEnv, run_download_command

        sdk = Mock()
        sdk.download_video.return_value = expected
        cli_env = DownloadCommandEnv(
            UcrawlSDK_cls=lambda save_dir: sdk,
            get_default_save_dir=lambda: "downloads",
            build_missav_proxy_url=lambda proxy: proxy,
            validate_config_types=lambda config: None,
            get_plugin=lambda source: object(),
            list_platform_ids=lambda: ["douyin"],
        )
        cli_args = argparse.Namespace(
            video_id="Demo",
            save_dir="downloads",
            url="https://example.com/video.mp4",
            source="douyin",
            timeout=30.0,
            config=None,
            cookie=None,
            download_strategy=None,
            referer=None,
            ua=None,
            folder_name=None,
            use_subdir=None,
            file_name=None,
            content_type=None,
            proxy=None,
            individual_only=None,
            priority=None,
            quiet=True,
            pretty=False,
        )
        cli_exit_code, cli_result, cli_error = run_download_command(cli_args, env=cli_env)
        self.assertEqual(cli_exit_code, 1)
        self.assertIsNone(cli_error)

        import cli.sdk as sdk_module

        sdk_instance = Mock()
        sdk_instance.download_video.return_value = expected
        with patch("cli.sdk.UcrawlSDK", return_value=sdk_instance):
            sdk_result = sdk_module.download_video(
                url="https://example.com/video.mp4",
                source="douyin",
                title="Demo",
                save_dir="downloads",
                timeout=30,
            )

        fake_sdk = Mock()
        fake_sdk.download_video.return_value = dict(expected)
        with patch(
            "app.web.workflows.get_platform_defaults",
            return_value={},
        ), patch(
            "app.web.workflows.validate_config_types",
            return_value=None,
        ), patch(
            "app.core.plugin_registry.registry.get_plugin",
            return_value=object(),
        ), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[SimpleNamespace(id="douyin")],
        ), patch(
            "app.web.workflows.build_sdk",
            return_value=fake_sdk,
        ):
            client = _create_test_client()
            api_result = client.post(
                "/api/download",
                json={
                    "url": "https://example.com/video.mp4",
                    "source": "douyin",
                    "title": "Demo",
                    "save_dir": "downloads",
                    "timeout": 30,
                },
                headers=_auth_headers(client),
            ).json()

        self.assertEqual(cli_result, expected)
        self.assertEqual(sdk_result, expected)
        for field in ("status", "url", "source", "title", "error", "save_dir", "local_path", "content_type", "meta"):
            self.assertEqual(api_result[field], expected[field])
        self.assertIn("video_id", api_result)
        self.assertIsInstance(api_result["elapsed"], (int, float))

if __name__ == "__main__":
    unittest.main()
