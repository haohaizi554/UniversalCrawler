"""Tests for m3u8 downloader lifecycle and callback safety."""

from __future__ import annotations

import http.client
import os
import socket
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

from app.core.downloaders.hls_proxy import _LocalHlsProxy
from app.core.downloaders.m3u8 import N_m3u8DL_RE_Downloader
from app.exceptions import ExternalToolError
from app.models import VideoItem
from shared.network.pinned_transport import canonicalize_request_target


class M3u8DownloaderLifecycleTests(unittest.TestCase):
    class _ProxyResponse:
        def __init__(
            self,
            url: str,
            content_type: str,
            content: bytes,
            *,
            status_code: int = 200,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.url = url
            self.status_code = status_code
            self.headers = {"Content-Type": content_type, "Content-Length": str(len(content)), **(headers or {})}
            self.content = content
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _RecordingProxyDownloader:
        def __init__(self, root_url: str, playlist: bytes) -> None:
            self.root_url = canonicalize_request_target(root_url).url
            self.playlist = playlist
            self.calls: list[tuple[str, dict[str, str]]] = []

        @staticmethod
        def _headers_for_hls_proxy_upstream(_upstream_url: str, headers: dict[str, str]) -> dict[str, str]:
            return dict(headers)

        def _hls_proxy_open_upstream(
            self,
            upstream_url: str,
            headers: dict[str, str],
            _upstream_proxy: str | None,
            *,
            domain_policy=None,
        ):
            self.calls.append((upstream_url, dict(headers)))
            if upstream_url == self.root_url:
                return M3u8DownloaderLifecycleTests._ProxyResponse(
                    upstream_url,
                    "application/vnd.apple.mpegurl",
                    self.playlist,
                )
            return M3u8DownloaderLifecycleTests._ProxyResponse(
                upstream_url,
                "video/mp2t",
                b"segment",
            )

    @staticmethod
    def _loopback_get(url: str) -> tuple[int, dict[str, str], bytes]:
        parsed = urllib.parse.urlsplit(url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        path = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
        finally:
            connection.close()

    @staticmethod
    def _replace_query(url: str, query: list[tuple[str, str]]) -> str:
        parsed = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
        )

    @staticmethod
    def _loopback_raw_get(url: str, header_lines: bytes) -> tuple[int, dict[str, str], bytes]:
        parsed = urllib.parse.urlsplit(url)
        path = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\n".encode("ascii")
            + header_lines
            + b"Connection: close\r\n\r\n"
        )
        chunks: list[bytes] = []
        with socket.create_connection((str(parsed.hostname), int(parsed.port or 0)), timeout=2) as connection:
            connection.sendall(request)
            while True:
                chunk = connection.recv(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        head, _separator, body = b"".join(chunks).partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        status = int(lines[0].split()[1])
        headers = {
            key.decode("ascii").lower(): value.decode("latin-1").strip()
            for line in lines[1:]
            if b":" in line
            for key, value in [line.split(b":", 1)]
        }
        return status, headers, body

    @staticmethod
    def _fake_m3u8_module():
        """构造最小 m3u8 模块，隔离真实依赖，只让 fallback 流程走到分片写入阶段。"""
        fake_m3u8 = types.ModuleType("m3u8")

        class FakeSegment:
            absolute_uri = "https://example.com/segment.ts"
            key = None

        class FakePlaylist:
            is_variant = False
            playlists: list[object] = []
            segments = [FakeSegment()]

        fake_m3u8.loads = MagicMock(return_value=FakePlaylist())
        return fake_m3u8

    @staticmethod
    def _fake_curl_cffi_module():
        """构造 curl_cffi 替身，验证临时目录清理而不发起真实网络请求。"""
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_const = types.ModuleType("curl_cffi.const")
        fake_requests = types.ModuleType("curl_cffi.requests")

        class FakeCurlOpt:
            PROXY = object()

        class FakeResponse:
            status_code = 200
            text = "#EXTM3U\n"
            content = b"segment"

        class FakeSession:
            def get(self, *_args, **_kwargs):
                return FakeResponse()

            def close(self):
                return None

        fake_requests.Session = MagicMock(return_value=FakeSession())
        fake_const.CurlOpt = FakeCurlOpt
        fake_curl_cffi.const = fake_const
        fake_curl_cffi.requests = fake_requests
        return fake_curl_cffi, fake_const, fake_requests

    @staticmethod
    def _fake_playwright_modules():
        """构造 Playwright 上下文替身，覆盖浏览器 fallback 的异常清理路径。"""
        fake_playwright = types.ModuleType("playwright")
        fake_sync_api = types.ModuleType("playwright.sync_api")

        class FakePlaywrightError(Exception):
            pass

        class FakePage:
            pass

        class FakeContext:
            def new_page(self):
                return FakePage()

        class FakeBrowser:
            def new_context(self, **_kwargs):
                return FakeContext()

            def close(self):
                return None

        class FakeChromium:
            def launch(self, **_kwargs):
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        fake_sync_api.Error = FakePlaywrightError
        fake_sync_api.sync_playwright = MagicMock(return_value=FakePlaywright())
        return fake_playwright, fake_sync_api

    def test_success_with_failing_final_callback_does_not_delete_output(self):
        """最终 100% 回调失败只是 UI 问题，已经成功的输出文件不能被当失败缓存删除。"""
        save_dir = tempfile.mkdtemp()
        save_path = os.path.join(save_dir, "clip.mp4")
        with open(save_path, "wb") as fp:
            fp.write(b"ok")

        video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="test")
        process = MagicMock()
        process.poll.return_value = 0
        process.returncode = 0

        def progress_callback(_value: int) -> None:
            if _value == 100:
                raise RuntimeError("ui callback failed")

        with patch.object(N_m3u8DL_RE_Downloader, "is_available", return_value=True), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable",
            return_value="tool",
        ), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.build_download_command",
            return_value=["tool"],
        ), patch("app.core.downloaders.m3u8.subprocess.Popen", return_value=process), patch(
            "app.core.downloaders.m3u8.ExternalToolRunner.wait_process",
        ):
            downloader = N_m3u8DL_RE_Downloader()
            downloader.download(video, save_path, progress_callback, lambda: False)

        self.assertTrue(os.path.exists(save_path))

    def test_wait_process_callback_error_does_not_delete_successful_output(self):
        """wait 阶段的进度回调异常不应覆盖外部工具已成功退出的事实。"""
        save_dir = tempfile.mkdtemp()
        save_path = os.path.join(save_dir, "clip.mp4")
        with open(save_path, "wb") as fp:
            fp.write(b"ok")

        video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="test")
        process = subprocess.Popen(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", "exit", "0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=5)

        def progress_callback(value: int) -> None:
            if value == 50:
                raise TypeError("progress ui failed")

        with patch.object(N_m3u8DL_RE_Downloader, "is_available", return_value=True), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable",
            return_value="tool",
        ), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.build_download_command",
            return_value=["tool"],
        ), patch("app.core.downloaders.m3u8.subprocess.Popen", return_value=process):
            downloader = N_m3u8DL_RE_Downloader()
            downloader.download(video, save_path, progress_callback, lambda: False)

        self.assertTrue(os.path.exists(save_path))

    def test_curl_cffi_fallback_cleans_temp_dir_on_failure(self):
        fake_m3u8 = self._fake_m3u8_module()
        fake_curl_cffi, fake_const, fake_requests = self._fake_curl_cffi_module()

        with tempfile.TemporaryDirectory() as save_dir:
            save_path = os.path.join(save_dir, "clip.mp4")
            temp_dir = os.path.join(save_dir, "clip_curl_cffi_hls")
            video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="missav")

            with patch.dict(
                sys.modules,
                {
                    "m3u8": fake_m3u8,
                    "curl_cffi": fake_curl_cffi,
                    "curl_cffi.const": fake_const,
                    "curl_cffi.requests": fake_requests,
                },
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_write_hls_segments",
                side_effect=ExternalToolError("segment write failed"),
            ):
                downloader = N_m3u8DL_RE_Downloader()
                with self.assertRaises(ExternalToolError):
                    downloader._download_with_curl_cffi_hls(
                        video,
                        save_path,
                        {"User-Agent": "test"},
                        None,
                        lambda *_args, **_kwargs: None,
                        lambda: False,
                    )

            self.assertFalse(os.path.exists(temp_dir))
            self.assertFalse(os.path.exists(save_path))

    def test_playwright_fallback_cleans_temp_dir_on_failure(self):
        fake_m3u8 = self._fake_m3u8_module()
        fake_playwright, fake_sync_api = self._fake_playwright_modules()

        with tempfile.TemporaryDirectory() as save_dir:
            save_path = os.path.join(save_dir, "clip.mp4")
            temp_dir = os.path.join(save_dir, "clip_playwright_hls")
            video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="missav")

            with patch.dict(
                sys.modules,
                {"m3u8": fake_m3u8, "playwright": fake_playwright, "playwright.sync_api": fake_sync_api},
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_playwright_fetch_or_goto_bytes",
                return_value=b"#EXTM3U\n",
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_write_hls_segments",
                side_effect=ExternalToolError("segment write failed"),
            ):
                downloader = N_m3u8DL_RE_Downloader()
                with self.assertRaises(ExternalToolError):
                    downloader._download_with_playwright_hls(
                        video,
                        save_path,
                        {"User-Agent": "test"},
                        None,
                        lambda *_args, **_kwargs: None,
                        lambda: False,
                    )

            self.assertFalse(os.path.exists(temp_dir))
            self.assertFalse(os.path.exists(save_path))

    def test_playwright_fallback_installs_public_context_guard_before_requests(self):
        fake_m3u8 = self._fake_m3u8_module()
        fake_playwright, fake_sync_api = self._fake_playwright_modules()
        policy = MagicMock()
        guard_state = {"installed": False}

        def mark_guard_installed(*_args, **_kwargs):
            guard_state["installed"] = True

        def fetch_after_guard(*_args, **_kwargs):
            self.assertTrue(guard_state["installed"])
            return b"#EXTM3U\n"

        with tempfile.TemporaryDirectory() as save_dir:
            save_path = os.path.join(save_dir, "clip.mp4")
            video = VideoItem(
                url="https://example.com/stream.m3u8",
                title="clip",
                source="missav",
                meta={"_network_policy": "public"},
            )

            with patch.dict(
                sys.modules,
                {"m3u8": fake_m3u8, "playwright": fake_playwright, "playwright.sync_api": fake_sync_api},
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_domain_policy_for_item",
                return_value=policy,
            ), patch(
                "shared.playwright_network_guard.install_public_network_guard",
                side_effect=mark_guard_installed,
            ) as install_guard, patch.object(
                N_m3u8DL_RE_Downloader,
                "_playwright_fetch_or_goto_bytes",
                side_effect=fetch_after_guard,
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_write_hls_segments",
                side_effect=ExternalToolError("stop after context setup"),
            ):
                downloader = N_m3u8DL_RE_Downloader()
                with self.assertRaises(ExternalToolError):
                    downloader._download_with_playwright_hls(
                        video,
                        save_path,
                        {"User-Agent": "test"},
                        None,
                        lambda *_args, **_kwargs: None,
                        lambda: False,
                    )

            install_guard.assert_called_once()
            self.assertIs(install_guard.call_args.args[1], policy)

    def test_local_hls_proxy_playlist_urls_are_task_signed(self):
        root_url = "https://media.example/master.m3u8"
        downloader = self._RecordingProxyDownloader(
            root_url,
            b"#EXTM3U\n#EXTINF:4,\nhttps://cdn.example/segment-1.ts\n",
        )
        proxy = _LocalHlsProxy(
            downloader,
            root_url,
            {"User-Agent": "test"},
            None,
            domain_policy=MagicMock(),
            allow_upstream_proxy=False,
        ).start()
        try:
            status, _headers, body = self._loopback_get(proxy.url)
        finally:
            proxy.stop()

        self.assertEqual(status, 200)
        resource_url = next(line for line in body.decode("utf-8").splitlines() if line and not line.startswith("#"))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(resource_url).query)
        self.assertEqual(set(query), {"task", "exp", "u", "sig"})
        self.assertTrue(all(len(values) == 1 and values[0] for values in query.values()))

    def test_local_hls_proxy_handler_does_not_emit_wildcard_cors(self):
        root_url = "https://media.example/master.m3u8"
        downloader = self._RecordingProxyDownloader(root_url, b"#EXTM3U\n")
        proxy = _LocalHlsProxy(
            downloader,
            root_url,
            {"User-Agent": "test"},
            None,
            domain_policy=MagicMock(),
            allow_upstream_proxy=False,
        ).start()
        try:
            status, headers, _body = self._loopback_get(proxy.url)
        finally:
            proxy.stop()

        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_local_hls_proxy_rejects_unsigned_and_tampered_paths_before_upstream_fetch(self):
        root_url = "https://media.example/master.m3u8"
        downloader = self._RecordingProxyDownloader(root_url, b"#EXTM3U\n")
        proxy = _LocalHlsProxy(
            downloader,
            root_url,
            {"User-Agent": "test"},
            None,
            domain_policy=MagicMock(),
            allow_upstream_proxy=False,
        ).start()
        try:
            signed_query = urllib.parse.parse_qsl(urllib.parse.urlsplit(proxy.url).query, keep_blank_values=True)
            unsigned_url = self._replace_query(proxy.url, [(key, value) for key, value in signed_query if key != "sig"])
            tampered_query = [(key, "0" * 64 if key == "sig" else value) for key, value in signed_query]
            if not any(key == "sig" for key, _value in tampered_query):
                tampered_query.append(("sig", "0" * 64))
            tampered_url = self._replace_query(proxy.url, tampered_query)

            unsigned_status, _headers, _body = self._loopback_get(unsigned_url)
            tampered_status, _headers, _body = self._loopback_get(tampered_url)
        finally:
            proxy.stop()

        self.assertEqual(unsigned_status, 403)
        self.assertEqual(tampered_status, 403)
        self.assertEqual(downloader.calls, [])

    def test_public_hls_proxy_keeps_credentials_only_for_root_origin(self):
        root_url = "https://media.example/master.m3u8"
        downloader = self._RecordingProxyDownloader(
            root_url,
            b"#EXTM3U\n#EXTINF:4,\nhttps://cdn.example/segment-1.ts\n",
        )
        proxy = _LocalHlsProxy(
            downloader,
            root_url,
            {
                "Authorization": "Bearer root-secret",
                "Cookie": "session=root-secret",
                "Host": "media.example",
                "Proxy-Authorization": "Basic root-secret",
                "User-Agent": "test",
            },
            None,
            domain_policy=MagicMock(),
            allow_upstream_proxy=False,
        ).start()
        try:
            root_status, _headers, body = self._loopback_get(proxy.url)
            resource_url = next(
                line for line in body.decode("utf-8").splitlines() if line and not line.startswith("#")
            )
            resource_status, _headers, _body = self._loopback_get(resource_url)
        finally:
            proxy.stop()

        self.assertEqual((root_status, resource_status), (200, 200))
        self.assertEqual(len(downloader.calls), 2)
        root_headers = {key.lower(): value for key, value in downloader.calls[0][1].items()}
        resource_headers = {key.lower(): value for key, value in downloader.calls[1][1].items()}
        self.assertEqual(root_headers["authorization"], "Bearer root-secret")
        self.assertEqual(root_headers["cookie"], "session=root-secret")
        for header_name in ("authorization", "cookie", "host", "proxy-authorization"):
            self.assertNotIn(header_name, resource_headers)

    def test_local_hls_proxy_start_and_command_logs_never_disclose_capability_url(self):
        root_url = "https://media.example/master.m3u8"
        video = VideoItem(
            url=root_url,
            title="clip",
            source="test",
            meta={"_network_policy": "public", "trace_id": "trace-test"},
        )
        captured: dict[str, str] = {}
        process = MagicMock(returncode=0)
        process.poll.return_value = 0

        def build_command(executable, source_url, *_args, **_kwargs):
            captured["url"] = source_url
            return [executable, source_url]

        with tempfile.TemporaryDirectory() as save_dir, patch.object(
            N_m3u8DL_RE_Downloader,
            "_domain_policy_for_item",
            return_value=MagicMock(),
        ), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.build_download_command",
            side_effect=build_command,
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_popen_nm3u8_process",
            return_value=process,
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_start_nm3u8_output_reader",
            return_value=None,
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_wait_external_process_with_file_progress",
        ), patch(
            "app.core.downloaders.m3u8.debug_logger.log",
        ) as log, patch(
            "app.core.downloaders.m3u8.debug_logger.log_command",
        ) as log_command:
            N_m3u8DL_RE_Downloader()._download_with_nm3u8_external(
                video,
                os.path.join(save_dir, "clip.mp4"),
                "tool",
                "test-agent",
                "",
                None,
                {"User-Agent": "test-agent"},
                4,
                lambda _value: None,
                lambda: False,
            )

        capability_url = captured["url"]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(capability_url).query)
        logged_text = repr(log.call_args_list) + repr(log_command.call_args_list)
        self.assertNotIn(capability_url, logged_text)
        self.assertNotIn("sig=", logged_text.lower())
        self.assertNotIn("u=", logged_text.lower())
        for key in ("sig", "u"):
            for token in query.get(key, []):
                self.assertNotIn(token, logged_text)

    def test_local_hls_proxy_rejects_multi_range_and_folded_range_before_upstream_fetch(self):
        root_url = "https://media.example/segment.ts"
        downloader = self._RecordingProxyDownloader(root_url, b"")
        proxy = _LocalHlsProxy(
            downloader,
            root_url,
            {"User-Agent": "test"},
            None,
            domain_policy=MagicMock(),
            allow_upstream_proxy=False,
        ).start()
        try:
            multi_status, _headers, _body = self._loopback_raw_get(
                proxy.url,
                b"Range: bytes=0-1,3-4\r\n",
            )
            folded_status, _headers, _body = self._loopback_raw_get(
                proxy.url,
                b"Range: bytes=0-1\r\n bytes=2-3\r\n",
            )
        finally:
            proxy.stop()

        self.assertIn(multi_status, {400, 416})
        self.assertIn(folded_status, {400, 416})
        self.assertEqual(downloader.calls, [])

    def test_local_hls_proxy_preserves_upstream_416_and_content_range(self):
        root_url = "https://media.example/segment.ts"
        downloader = N_m3u8DL_RE_Downloader()
        upstream_response = self._ProxyResponse(
            root_url,
            "video/mp2t",
            b"",
            status_code=416,
            headers={"Content-Range": "bytes */4096"},
        )
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_requests = types.ModuleType("curl_cffi.requests")
        fake_curl_cffi.requests = fake_requests
        proxy = _LocalHlsProxy(downloader, root_url, {"User-Agent": "test"}, None).start()
        try:
            with patch.dict(
                sys.modules,
                {"curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_requests},
            ), patch.object(
                downloader,
                "_hls_proxy_request_response",
                return_value=upstream_response,
            ):
                status, headers, _body = self._loopback_get(proxy.url)
        finally:
            proxy.stop()

        self.assertEqual(status, 416)
        self.assertEqual(headers.get("content-range"), "bytes */4096")

    def test_local_hls_proxy_does_not_rewrite_playlist_shaped_416_as_success(self):
        root_url = "https://media.example/master.m3u8"
        downloader = N_m3u8DL_RE_Downloader()
        upstream_response = self._ProxyResponse(
            root_url,
            "application/vnd.apple.mpegurl",
            b"",
            status_code=416,
            headers={"Content-Range": "bytes */1024"},
        )
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_requests = types.ModuleType("curl_cffi.requests")
        fake_curl_cffi.requests = fake_requests
        proxy = _LocalHlsProxy(downloader, root_url, {"User-Agent": "test"}, None).start()
        try:
            with patch.dict(
                sys.modules,
                {"curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_requests},
            ), patch.object(
                downloader,
                "_hls_proxy_request_response",
                return_value=upstream_response,
            ):
                status, headers, _body = self._loopback_get(proxy.url)
        finally:
            proxy.stop()

        self.assertEqual(status, 416)
        self.assertEqual(headers.get("content-range"), "bytes */1024")

    def test_manual_hls_redirect_response_exposes_complete_chain(self):
        downloader = N_m3u8DL_RE_Downloader()
        requested_url = "https://media.example/start.ts"
        redirected_url = "https://cdn.example/final.ts"
        first = self._ProxyResponse(
            requested_url,
            "text/plain",
            b"",
            status_code=302,
            headers={"Location": redirected_url},
        )
        final = self._ProxyResponse(redirected_url, "video/mp2t", b"segment")

        with patch.object(
            downloader,
            "_curl_cffi_get_response",
            side_effect=[first, final],
        ):
            response = downloader._hls_proxy_request_response(
                MagicMock(),
                requested_url,
                {"User-Agent": "test"},
                "http://proxy.example:8080",
                domain_policy=MagicMock(),
            )

        expected_chain = (
            canonicalize_request_target(requested_url).url,
            canonicalize_request_target(redirected_url).url,
        )
        self.assertIs(response, final)
        self.assertEqual(canonicalize_request_target(response.url).url, expected_chain[-1])
        self.assertEqual(response.redirect_chain, expected_chain)
        self.assertTrue(first.closed)

    def test_manual_hls_redirect_closes_response_when_location_is_invalid(self):
        downloader = N_m3u8DL_RE_Downloader()
        response = self._ProxyResponse(
            "https://media.example/start.ts",
            "text/plain",
            b"",
            status_code=302,
            headers={"Location": "http://[::1"},
        )

        with patch.object(
            downloader,
            "_curl_cffi_get_response",
            return_value=response,
        ), self.assertRaises(ValueError):
            downloader._hls_proxy_request_response(
                MagicMock(),
                "https://media.example/start.ts",
                {"User-Agent": "test"},
                "http://proxy.example:8080",
                domain_policy=MagicMock(),
            )

        self.assertTrue(response.closed)

    def test_hls_fetch_returns_resolved_url_and_chain_and_closes_response(self):
        downloader = N_m3u8DL_RE_Downloader()
        requested_url = canonicalize_request_target("https://media.example/start.ts").url
        resolved_url = canonicalize_request_target("https://cdn.example/final.ts").url
        response = self._ProxyResponse(resolved_url, "video/mp2t", b"segment")
        response.redirect_chain = (requested_url, resolved_url)
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_requests = types.ModuleType("curl_cffi.requests")
        fake_curl_cffi.requests = fake_requests

        with patch.dict(
            sys.modules,
            {"curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_requests},
        ), patch.object(
            downloader,
            "_hls_proxy_request_response",
            return_value=response,
        ):
            result = downloader._hls_proxy_fetch_upstream(
                requested_url,
                {"User-Agent": "test"},
                None,
            )

        self.assertEqual(
            result,
            (200, "video/mp2t", b"segment", resolved_url, (requested_url, resolved_url)),
        )
        self.assertTrue(response.closed)

    def test_hls_fetch_closes_failed_response_before_raising(self):
        downloader = N_m3u8DL_RE_Downloader()
        response = self._ProxyResponse(
            "https://media.example/segment.ts",
            "text/plain",
            b"failed",
            status_code=500,
        )
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_requests = types.ModuleType("curl_cffi.requests")
        fake_curl_cffi.requests = fake_requests

        with patch.dict(
            sys.modules,
            {"curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_requests},
        ), patch.object(
            downloader,
            "_hls_proxy_request_response",
            return_value=response,
        ), self.assertRaises(ExternalToolError):
            downloader._hls_proxy_fetch_upstream(
                "https://media.example/segment.ts",
                {"User-Agent": "test"},
                None,
            )

        self.assertTrue(response.closed)

    def test_hls_proxy_does_not_invent_range_for_unranged_client_request(self):
        headers = N_m3u8DL_RE_Downloader._headers_for_hls_proxy_upstream(
            "https://media.example/segment.ts",
            {"User-Agent": "test"},
        )

        self.assertNotIn("Range", headers)

    def test_local_hls_proxy_rejects_replay_after_stop_before_upstream_fetch(self):
        root_url = "https://media.example/master.m3u8"
        downloader = self._RecordingProxyDownloader(root_url, b"#EXTM3U\n")
        proxy = _LocalHlsProxy(
            downloader,
            root_url,
            {"User-Agent": "test"},
            None,
            domain_policy=MagicMock(),
            allow_upstream_proxy=False,
        ).start()
        old_url = proxy.url
        proxy.stop()
        old = urllib.parse.urlsplit(old_url)
        replay_path = urllib.parse.urlunsplit(("", "", old.path, old.query, ""))

        self.assertIsNone(proxy.verify_path(replay_path))
        self.assertEqual(downloader.calls, [])

    def test_sweep_orphaned_workspaces_removes_stale_dirs(self):
        """启动清扫同时覆盖新版统一工作目录和旧版 fallback 目录。"""
        with tempfile.TemporaryDirectory() as save_dir:
            nm3u8_workspace = os.path.join(save_dir, N_m3u8DL_RE_Downloader.NM3U8_TEMP_ROOT_NAME, "ucp-foo")
            curl_workspace = os.path.join(save_dir, "xxx_curl_cffi_hls")
            playwright_workspace = os.path.join(save_dir, "yyy_playwright_hls")
            for path in (nm3u8_workspace, curl_workspace, playwright_workspace):
                os.makedirs(path, exist_ok=True)

            cleaned = N_m3u8DL_RE_Downloader.sweep_orphaned_workspaces([save_dir])

            self.assertEqual(cleaned, 3)
            self.assertFalse(os.path.exists(os.path.join(save_dir, N_m3u8DL_RE_Downloader.NM3U8_TEMP_ROOT_NAME)))
            self.assertFalse(os.path.exists(curl_workspace))
            self.assertFalse(os.path.exists(playwright_workspace))


if __name__ == "__main__":
    unittest.main()
