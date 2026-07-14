import argparse
import unittest
from unittest.mock import AsyncMock, Mock, patch

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
    return client

def _auth_headers(client):
    return {client._ucrawl_token_header: client._ucrawl_session_token}

def _get_session_context(client):
    return client._ucrawl_session_context

class CliSearchFacadeContractTests(unittest.TestCase):
    def test_handle_search_command_delegates_to_shared_runtime_and_emits_result(self):
        from cli.commands.search import handle_search_command
        from shared.cli_runner_runtime import CLIRunner

        args = argparse.Namespace(pretty=True)

        with patch("cli.commands.search.runtime.run_search_command", return_value=(0, {"status": "ok"})) as run_cmd, patch(
            "cli.commands.search.runtime.emit_result"
        ) as emit_result:
            exit_code = handle_search_command(args)

        self.assertEqual(exit_code, 0)
        run_cmd.assert_called_once()
        self.assertIs(run_cmd.call_args.kwargs["env"].CLIRunner_cls, CLIRunner)
        emit_result.assert_called_once_with({"status": "ok"}, pretty=True)

    def test_build_selection_strategy_delegates_with_runtime_env(self):
        from cli.commands.search import _build_selection_strategy

        args = argparse.Namespace(source="douyin", keyword="kw")

        with patch("cli.commands.search.runtime.build_selection_strategy", return_value="sel") as build_selection:
            strategy = _build_selection_strategy(args)

        self.assertEqual(strategy, "sel")
        build_selection.assert_called_once()
        self.assertEqual(build_selection.call_args.kwargs["env"].selection_factory.__name__, "SelectionStrategyFactory")

class CliDownloadFacadeContractTests(unittest.TestCase):
    def test_handle_download_command_delegates_to_shared_runtime_and_stderr(self):
        from cli.commands.download import handle_download_command

        args = argparse.Namespace(pretty=False)

        with patch(
            "cli.commands.download.runtime.run_download_command",
            return_value=(1, {"status": "error"}, "bad timeout"),
        ) as run_cmd, patch("cli.commands.download.runtime.emit_result") as emit_result, patch(
            "cli.commands.download.sys.stderr.write"
        ) as stderr:
            exit_code = handle_download_command(args)

        self.assertEqual(exit_code, 1)
        run_cmd.assert_called_once()
        self.assertEqual(run_cmd.call_args.kwargs["env"].UcrawlSDK_cls.__name__, "UcrawlSDK")
        stderr.assert_called_once_with("bad timeout\n")
        emit_result.assert_called_once_with({"status": "error"}, pretty=False)

    def test_build_download_config_delegates_with_source(self):
        from cli.commands.download import _build_config

        args = argparse.Namespace()
        with patch("cli.commands.download.runtime.build_config", return_value=({"timeout": 10}, None)) as build_config:
            result = _build_config(args, source="douyin")

        self.assertEqual(result, ({"timeout": 10}, None))
        build_config.assert_called_once()
        self.assertEqual(build_config.call_args.kwargs["source"], "douyin")

class CliSdkFacadeContractTests(unittest.TestCase):
    def test_module_search_delegates_and_closes_sdk(self):
        import shared.sdk_runtime as sdk_module

        sdk = Mock()
        sdk.search.return_value = {"status": "ok"}

        with patch("shared.sdk_runtime.UcrawlSDK", return_value=sdk) as sdk_cls:
            result = sdk_module.search("douyin", "kw", save_dir="downloads", download=False, timeout=12)

        self.assertEqual(result, {"status": "ok"})
        sdk_cls.assert_called_once_with(save_dir="downloads")
        sdk.search.assert_called_once_with(
            "douyin",
            "kw",
            save_dir="downloads",
            selection=None,
            timeout=12,
            download=False,
            run_timeout=None,
        )
        sdk.close.assert_called_once()

    def test_module_download_video_delegates_and_closes_sdk(self):
        import shared.sdk_runtime as sdk_module

        sdk = Mock()
        sdk.download_video.return_value = {"status": "ok", "local_path": "demo.mp4"}
        progress_cb = Mock()

        with patch("shared.sdk_runtime.UcrawlSDK", return_value=sdk) as sdk_cls:
            result = sdk_module.download_video(
                url="https://example.com/video",
                source="douyin",
                title="demo",
                save_dir="downloads",
                timeout=30,
                verbose=True,
                config={"max_items": 1},
                progress_callback=progress_cb,
            )

        self.assertEqual(result["status"], "ok")
        sdk_cls.assert_called_once_with(save_dir="downloads")
        sdk.download_video.assert_called_once_with(
            url="https://example.com/video",
            source="douyin",
            title="demo",
            save_dir="downloads",
            timeout=30,
            verbose=True,
            config={"max_items": 1},
            progress_callback=progress_cb,
        )
        sdk.close.assert_called_once()

    def test_module_scan_and_list_platforms_delegate_and_close_sdk(self):
        import shared.sdk_runtime as sdk_module

        scan_sdk = Mock()
        scan_sdk.scan_directory.return_value = {"status": "ok", "items": []}
        list_sdk = Mock()
        list_sdk.list_platforms.return_value = [{"id": "douyin"}]

        with patch("shared.sdk_runtime.UcrawlSDK", side_effect=[scan_sdk, list_sdk]):
            scan_result = sdk_module.scan_directory("downloads", scan_limit=10)
            platform_result = sdk_module.list_platforms()

        self.assertEqual(scan_result["status"], "ok")
        self.assertEqual(platform_result, [{"id": "douyin"}])
        scan_sdk.scan_directory.assert_called_once_with("downloads", 10)
        scan_sdk.close.assert_called_once()
        list_sdk.list_platforms.assert_called_once_with()
        list_sdk.close.assert_called_once()

    def test_get_runner_class_uses_cli_sdk_patch_seam(self):
        import shared.sdk_runtime as sdk_module

        runner_sentinel = Mock()
        runner_sentinel.__module__ = "unittest.mock"

        with patch.object(sdk_module, "CLIRunner", runner_sentinel):
            runner_cls = sdk_module.UcrawlSDK()._get_runner_class()

        self.assertIs(runner_cls, runner_sentinel)

    def test_cli_package_exports_the_shared_runner(self):
        from cli import CLIRunner
        from shared.cli_runner_runtime import CLIRunner as SharedCLIRunner

        self.assertIs(CLIRunner, SharedCLIRunner)

class FastApiWorkflowRouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = _create_test_client()

    def test_search_route_delegates_to_shared_search_runtime(self):
        with patch("app.core.plugin_registry.registry.get_plugin", return_value=object()), patch(
            "app.core.plugin_registry.registry.get_all_plugins",
            return_value=[Mock(id="douyin")],
        ), patch("app.web.server.run_cli_search", return_value={"status": "ok", "items": []}) as run_search:
            response = self.client.post("/api/search", json={"source": "douyin", "keyword": "kw"}, headers=_auth_headers(self.client))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "items": []})
        run_search.assert_called_once()
        self.assertEqual(run_search.call_args.kwargs["source"], "douyin")
        self.assertEqual(run_search.call_args.kwargs["keyword"], "kw")

    def test_crawl_select_route_delegates_to_session_workflow(self):
        context = _get_session_context(self.client)
        context.workflow.select_tasks = AsyncMock(return_value={"status": "ok"})

        response = self.client.post("/api/crawl/select", json={"indices": [0, 2]}, headers=_auth_headers(self.client))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        context.workflow.select_tasks.assert_awaited_once_with({"indices": [0, 2]}, log_error=False)

    def test_download_route_delegates_to_session_workflow(self):
        context = _get_session_context(self.client)
        context.workflow.direct_download = AsyncMock(return_value={"status": "ok", "video_id": "v1"})

        response = self.client.post(
            "/api/download",
            json={"url": "https://example.com/video", "source": "douyin"},
            headers=_auth_headers(self.client),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "video_id": "v1"})
        context.workflow.direct_download.assert_awaited_once_with(
            {"url": "https://example.com/video", "source": "douyin"},
            log_error=False,
        )

if __name__ == "__main__":
    unittest.main()
