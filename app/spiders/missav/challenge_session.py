"""MissAV 挑战页使用的独立系统浏览器会话。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.runtime_paths import user_cache_root


class SystemBrowserUnavailable(RuntimeError):
    """当前系统没有可供人工验证使用的稳定版 Chromium 浏览器。"""


class ChallengeWaitTimeout(TimeoutError):
    """独立浏览器中的挑战页在限定时间内没有恢复为业务页面。"""


class ChallengeWaitCancelled(RuntimeError):
    """用户停止任务，中断独立浏览器等待。"""


@dataclass(frozen=True)
class BrowserTarget:
    """CDP 元数据接口返回的一个页面目标。"""

    target_id: str
    url: str
    title: str


@dataclass(frozen=True)
class BrowserAttachment:
    """挑战完成后才创建的 Playwright 接管对象集合。"""

    browser: Any
    context: Any
    page: Any


class ExternalChromeChallengeSession:
    """让系统 Chrome 在没有活动 CDP 客户端时独立完成 Cloudflare 挑战。"""

    CDP_CONNECT_TIMEOUT_MS = 30_000
    CHALLENGE_TITLE_MARKERS = (
        "just a moment",
        "请稍候",
        "正在进行安全验证",
        "checking your browser",
        "security verification",
        "attention required",
        "浏览器不支持",
        "browser not supported",
        "unsupported browser",
    )

    def __init__(
        self,
        *,
        proxy_server: str | None = None,
        browser_executable: str | Path | None = None,
        profile_dir: str | Path | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.proxy_server = str(proxy_server or "").strip() or None
        self.browser_executable = (
            Path(browser_executable)
            if browser_executable is not None
            else self.find_system_browser_executable()
        )
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds))
        self.debug_port = self._allocate_loopback_port()
        self.cdp_endpoint = f"http://127.0.0.1:{self.debug_port}"
        self._process: subprocess.Popen | None = None
        self._temporary_profile: tempfile.TemporaryDirectory[str] | None = None
        if profile_dir is None:
            profile_root = user_cache_root() / "browser_profiles"
            profile_root.mkdir(parents=True, exist_ok=True)
            self._temporary_profile = tempfile.TemporaryDirectory(
                prefix="missav-",
                dir=profile_root,
                ignore_cleanup_errors=True,
            )
            self.profile_dir = Path(self._temporary_profile.name)
        else:
            self.profile_dir = Path(profile_dir)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._local_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    @staticmethod
    def _allocate_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @classmethod
    def find_system_browser_executable(cls) -> Path:
        """按稳定版 Chrome、Edge 的顺序定位系统浏览器。"""
        candidates: list[Path] = []
        for executable_name in (
            "chrome.exe",
            "msedge.exe",
            "google-chrome",
            "chromium",
        ):
            located = shutil.which(executable_name)
            if located:
                candidates.append(Path(located))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("PROGRAMFILES", ""))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", ""))
        candidates.extend(
            (
                program_files / "Google/Chrome/Application/chrome.exe",
                program_files_x86 / "Google/Chrome/Application/chrome.exe",
                local_app_data / "Google/Chrome/Application/chrome.exe",
                program_files / "Microsoft/Edge/Application/msedge.exe",
                program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
                local_app_data / "Microsoft/Edge/Application/msedge.exe",
            )
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise SystemBrowserUnavailable("未找到系统 Chrome 或 Edge")

    def _common_command(self) -> list[str]:
        command = [
            str(self.browser_executable),
            f"--remote-debugging-port={self.debug_port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self.proxy_server:
            command.append(f"--proxy-server={self.proxy_server}")
        return command

    @staticmethod
    def _spawn(command: list[str]) -> subprocess.Popen:
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

    def start(self, url: str) -> None:
        """首次打开页面；此时没有 Playwright 客户端连接 CDP。"""
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("独立浏览器会话已经启动")
        self._process = self._spawn([*self._common_command(), str(url)])

    def open_url(self, url: str) -> None:
        """复用同一用户目录打开新页，让站点在未接管状态下执行挑战。"""
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("独立浏览器会话尚未启动或已经退出")
        self._spawn([*self._common_command(), "--new-tab", str(url)])

    def _read_targets(self) -> list[dict[str, Any]]:
        with self._local_opener.open(
            f"{self.cdp_endpoint}/json/list", timeout=1.0
        ) as response:
            payload = json.load(response)
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _query_pairs(url: str) -> set[tuple[str, str]]:
        parsed = urllib.parse.urlsplit(str(url or ""))
        return set(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))

    @classmethod
    def _urls_match(cls, candidate_url: str, target_url: str) -> bool:
        try:
            candidate = urllib.parse.urlsplit(str(candidate_url or ""))
            target = urllib.parse.urlsplit(str(target_url or ""))
        except (TypeError, ValueError):
            return False
        if (candidate.hostname or "").lower() != (target.hostname or "").lower():
            return False
        if candidate.path.rstrip("/") != target.path.rstrip("/"):
            return False
        return cls._query_pairs(target_url).issubset(cls._query_pairs(candidate_url))

    @classmethod
    def _find_target(
        cls,
        targets: list[dict[str, Any]],
        target_url: str,
    ) -> BrowserTarget | None:
        matches: list[tuple[bool, BrowserTarget]] = []
        target_query = cls._query_pairs(target_url)
        for raw_target in targets:
            if str(raw_target.get("type") or "") != "page":
                continue
            candidate_url = str(raw_target.get("url") or "")
            if not cls._urls_match(candidate_url, target_url):
                continue
            target = BrowserTarget(
                target_id=str(raw_target.get("id") or ""),
                url=candidate_url,
                title=str(raw_target.get("title") or ""),
            )
            matches.append((cls._query_pairs(candidate_url) == target_query, target))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    @classmethod
    def _is_challenge_title(cls, title: str) -> bool:
        normalized = str(title or "").strip().lower()
        if not normalized:
            return True
        return any(marker in normalized for marker in cls.CHALLENGE_TITLE_MARKERS)

    def wait_for_ready_page(
        self,
        target_url: str,
        *,
        timeout_seconds: float,
        cancelled: Callable[[], bool],
        on_challenge: Callable[[str], None] | None = None,
    ) -> BrowserTarget:
        """只轮询本地目标元数据，不建立 WebSocket/CDP 控制会话。"""
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        last_target: BrowserTarget | None = None
        challenge_reported = False
        while time.monotonic() < deadline:
            if cancelled():
                raise ChallengeWaitCancelled("用户已停止任务")
            try:
                last_target = self._find_target(self._read_targets(), target_url)
            except (OSError, ValueError, json.JSONDecodeError):
                last_target = None
            if last_target is not None:
                if not self._is_challenge_title(last_target.title):
                    return last_target
                if on_challenge is not None and not challenge_reported:
                    on_challenge(last_target.title)
                    challenge_reported = True
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError("独立浏览器在挑战完成前异常退出")
            time.sleep(self.poll_interval_seconds)
        last_title = last_target.title if last_target is not None else ""
        raise ChallengeWaitTimeout(
            f"等待独立浏览器完成安全验证超时，最后标题: {last_title or '未加载'}"
        )

    def attach(self, playwright, target_url: str) -> BrowserAttachment:
        """挑战页清除后才连接 CDP，并选择与目标 URL 对应的标签页。"""
        browser = playwright.chromium.connect_over_cdp(
            self.cdp_endpoint,
            timeout=self.CDP_CONNECT_TIMEOUT_MS,
        )
        exact_match: tuple[Any, Any] | None = None
        fallback_match: tuple[Any, Any] | None = None
        target_query = self._query_pairs(target_url)
        for context in browser.contexts:
            for page in context.pages:
                page_url = str(getattr(page, "url", "") or "")
                if not self._urls_match(page_url, target_url):
                    continue
                pair = (context, page)
                if self._query_pairs(page_url) == target_query:
                    exact_match = pair
                    break
                fallback_match = pair
            if exact_match is not None:
                break
        match = exact_match or fallback_match
        if match is None:
            raise RuntimeError(f"CDP 接管后未找到目标标签页: {target_url}")
        context, page = match
        return BrowserAttachment(browser=browser, context=context, page=page)

    def close(self) -> None:
        """仅终止本会话启动的浏览器进程树，并清理临时用户目录。"""
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                    )
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except OSError:
                pass
        if self._temporary_profile is not None:
            self._temporary_profile.cleanup()
            self._temporary_profile = None

    def __enter__(self) -> "ExternalChromeChallengeSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
