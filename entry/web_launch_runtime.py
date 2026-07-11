"""Web 入口启动期辅助逻辑。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import secrets
import signal
import ssl
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Coroutine
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MIN_ACCESS_TOKEN_LENGTH = 20


def is_loopback_bind_host(host: str) -> bool:
    """Return whether a bind host can only accept local-machine traffic."""
    normalized = str(host or "").strip().strip("[]")
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return normalized.lower() == "localhost"


def _validate_access_token(value: str) -> str:
    token = str(value or "").strip()
    if len(token) < MIN_ACCESS_TOKEN_LENGTH:
        raise ValueError(f"Web access token must contain at least {MIN_ACCESS_TOKEN_LENGTH} characters")
    return token


def resolve_web_access_token(
    host: str,
    configured_token: str | None = None,
    *,
    token_file: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> str | None:
    """Resolve the access secret used by non-loopback Web deployments.

    Local-only launches stay passwordless. Remote launches reuse a protected
    token file so restarting the app does not invalidate bookmarked access.
    """
    environment = os.environ if environ is None else environ
    supplied = configured_token or environment.get("UCRAWL_WEB_ACCESS_TOKEN")
    if supplied:
        return _validate_access_token(supplied)
    if is_loopback_bind_host(host):
        return None

    if token_file is None:
        return _validate_access_token(token_factory())

    path = Path(token_file).expanduser()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = None
    if existing is not None:
        return _wait_for_persisted_access_token(path, initial_value=existing)

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = _validate_access_token(token_factory())
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # A concurrent launcher won creation; its token is the source of truth.
        return _wait_for_persisted_access_token(path)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(generated)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return generated


def _wait_for_persisted_access_token(
    path: Path,
    *,
    initial_value: str | None = None,
    attempts: int = 20,
    delay: float = 0.025,
) -> str:
    """Wait briefly while another launcher finishes its exclusive token write."""
    value = initial_value
    for attempt in range(max(1, attempts)):
        if value:
            try:
                return _validate_access_token(value)
            except ValueError:
                # An exclusive creator may have flushed only part of the line;
                # treat a short value as in-progress until the retry budget ends.
                pass
        if attempt:
            time.sleep(delay)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
    raise ValueError(f"Web access token file is empty or incomplete: {path}")


def build_access_url(base_url: str, access_token: str | None) -> str:
    """Add the one-time HTTP bootstrap query used to establish an access cookie."""
    if not access_token:
        return base_url
    parts = urlsplit(base_url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "access_token"]
    query.append(("access_token", access_token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))


def build_web_url(host: str, port: int, scheme: str) -> str:
    """Build a browser URL from a bind address without using non-routable wildcards."""
    normalized = str(host or "").strip().strip("[]")
    # The wildcard literal is normalized into a browser URL; no socket is bound here.
    if normalized in {"", str(ipaddress.IPv4Address(0)), "127.0.0.1", "localhost"}:
        browser_host = "localhost"
    elif normalized in {"::", "::1"}:
        browser_host = "[::1]"
    else:
        try:
            parsed = ipaddress.ip_address(normalized)
        except ValueError:
            browser_host = normalized
        else:
            browser_host = f"[{normalized}]" if parsed.version == 6 else normalized
    return f"{scheme}://{browser_host}:{int(port)}"


def resolve_existing_web_url(
    host: str,
    port: int,
    scheme: str,
    *,
    ssl_certfile: str | os.PathLike[str] | None = None,
    expected_version: str | None = None,
    timeout: float = 0.6,
    urlopen_func: Callable[..., Any] = urllib.request.urlopen,
) -> str | None:
    """Return the base URL only when the occupied port is this UCrawl version."""
    base_url = build_web_url(host, port, scheme)
    request = urllib.request.Request(
        f"{base_url}/api/ping",
        headers={"Accept": "application/json", "User-Agent": "UCrawl-instance-probe"},
    )
    kwargs: dict[str, Any] = {"timeout": max(0.1, float(timeout))}
    if scheme == "https":
        # HTTPS 探测与服务端复用同一证书信任锚，避免端口占用者伪装成现有实例。
        kwargs["context"] = ssl.create_default_context(cafile=str(ssl_certfile) if ssl_certfile else None)
    try:
        with urlopen_func(request, **kwargs) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            return None
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return None
    version = str(payload.get("version") or "")
    if expected_version is not None and version != str(expected_version):
        return None
    return base_url

def try_reuse_existing_instance(
    *,
    host: str,
    port: int,
    open_browser: bool,
    resolve_existing_url: Callable[[str, int], str | None],
    browser_opener: Callable[[str], Any] = webbrowser.open,
    stderr=None,
) -> bool:
    """检测并复用已运行的 Web 实例。

    启动入口先做端口复用判断，能避免用户双击多次后同时启动多个 Web
    服务和后台下载管理器。
    """
    stderr = stderr or sys.stderr
    existing_url = resolve_existing_url(host, port)
    if not existing_url:
        return False
    stderr.write(f"⚠️  检测到 UCrawl Web 已在运行，直接复用现有实例：{existing_url}\n")
    stderr.flush()
    if open_browser:
        browser_opener(existing_url)
    return True

def print_startup_banner(url: str, *, script: str | None = None, stderr=None) -> None:
    """输出 Web 启动横幅。"""
    stderr = stderr or sys.stderr
    stderr.write("\n  UCrawl Web UI\n")
    stderr.write(f"  {url}\n")
    stderr.write("  保存目录: downloads/\n")
    if script:
        stderr.write(f"  启动时注入脚本: {script}\n")
    stderr.write("\n")
    stderr.flush()

def start_browser_open_thread(
    url: str,
    *,
    delay: float = 1.5,
    browser_opener: Callable[[str], Any] = webbrowser.open,
) -> threading.Thread:
    """后台延迟打开浏览器，避免服务未就绪时抢跑。"""

    def _open_browser() -> None:
        time.sleep(delay)
        browser_opener(url)

    thread = threading.Thread(target=_open_browser, daemon=True)
    thread.start()
    return thread

def install_shutdown_signal_handlers(
    shutdown_event: threading.Event,
    *,
    signal_module=signal,
    stderr=None,
) -> Callable[[int, object], None]:
    """安装 SIGINT/SIGTERM 处理器，统一走 shutdown_event。

    Web 服务、Qt 托盘和浏览器打开线程都观察同一个事件，退出路径就不会
    因入口模式不同而遗漏清理。
    """
    stderr = stderr or sys.stderr

    def _signal_handler(signum, frame) -> None:
        stderr.write("\n  收到终止信号，正在关闭服务...\n")
        shutdown_event.set()

    signal_module.signal(signal_module.SIGINT, _signal_handler)
    signal_module.signal(signal_module.SIGTERM, _signal_handler)
    return _signal_handler

def run_server_with_qt(
    qt_app: Any,
    *,
    url: str,
    shutdown_event: threading.Event,
    serve_async: Callable[[], Coroutine[Any, Any, None]],
    create_tray_icon: Callable[[Any, str, threading.Event], Any],
    request_shutdown: Callable[[], None],
) -> None:
    """Qt 模式下：后台线程跑 Web，主线程跑 Qt 事件循环。

    Qt 要占主线程，FastAPI/uvicorn 只能放到后台线程；QTimer 轮询
    shutdown_event 是为了把信号处理安全切回 Qt 事件循环。
    """

    def _run_server() -> None:
        asyncio.run(serve_async())

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    tray = create_tray_icon(qt_app, url, shutdown_event)

    from PyQt6.QtCore import QTimer

    def _check_shutdown() -> None:
        if shutdown_event.is_set():
            timer.stop()
            request_shutdown()
            if tray:
                tray.hide()
            qt_app.quit()

    timer = QTimer()
    timer.timeout.connect(_check_shutdown)
    timer.start(100)
    qt_app.exec()
    server_thread.join(timeout=5)

def run_server_without_qt(*, serve_async: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """无 Qt 模式下直接在主线程运行 asyncio。"""
    asyncio.run(serve_async())
