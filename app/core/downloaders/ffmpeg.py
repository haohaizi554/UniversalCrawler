"""通过 FFmpeg 拉取媒体流，并把子进程进度转换为统一下载事件。"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from collections import deque

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, ExternalToolError, ExternalToolNotFoundError
from app.models import VideoItem
from shared.runtime_options import DomainPolicyViolation
from shared.network_proxy import requests_proxy_mapping

from .base import BaseDownloader, ProgressCallback, StopCheck
from .external import FFmpegExternalTool, build_hidden_startupinfo

# 基于 external.py 封装命令构建和可执行文件解析，这里只负责进程生命周期与进度解析。
class FFmpegDownloader(BaseDownloader):
    """通过 ffmpeg 下载/转封装大媒体文件，并把外部进程状态映射成内部进度。"""
    SIZE_THRESHOLD_MB = 200
    DURATION_THRESHOLD_SEC = 600
    PROGRESS_TIMEOUT_SEC = 30
    STDERR_POLL_INTERVAL_SEC = 0.2

    @staticmethod
    def _parse_clock_to_seconds(raw: str) -> float | None:
        match = re.match(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})(?:\.(?P<ms>\d+))?", raw.strip())
        if not match:
            return None
        seconds = float(int(match.group("h")) * 3600 + int(match.group("m")) * 60 + int(match.group("s")))
        fraction = match.group("ms")
        if fraction:
            seconds += float(f"0.{fraction}")
        return seconds

    @classmethod
    def _extract_expected_duration(cls, line_str: str, fallback_duration: float | None) -> float | None:
        if fallback_duration and fallback_duration > 0:
            return fallback_duration
        duration_info = re.search(r"Duration:\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
        if not duration_info:
            return fallback_duration
        return cls._parse_clock_to_seconds(duration_info.group(1)) or fallback_duration

    @classmethod
    def _estimate_progress(
        cls,
        *,
        out_time_seconds: float | None,
        total_size_bytes: int | None,
        expected_duration: float | None,
        expected_size_bytes: int | None,
    ) -> int | None:
        if expected_duration and expected_duration > 0 and out_time_seconds is not None:
            return min(99, max(1, int((out_time_seconds / expected_duration) * 100)))
        if expected_size_bytes and expected_size_bytes > 0 and total_size_bytes is not None:
            return min(99, max(1, int((total_size_bytes / expected_size_bytes) * 100)))
        return None

    @classmethod
    def _parse_progress_line(
        cls,
        line_str: str,
        *,
        expected_duration: float | None,
        expected_size_bytes: int | None,
    ) -> tuple[float | None, int | None, int | None]:
        next_duration = cls._extract_expected_duration(line_str, expected_duration)
        total_size_bytes: int | None = None
        out_time_seconds: float | None = None
        progress_value: int | None = None

        # build_download_command 优先使用 -progress pipe:2，但部分 ffmpeg 版本仍会输出传统 stderr 行。
        if "=" in line_str:
            key, value = line_str.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in {"out_time", "out_time_ms", "out_time_us"}:
                if key == "out_time":
                    out_time_seconds = cls._parse_clock_to_seconds(value)
                else:
                    try:
                        raw_out_time = int(value)
            # 新版 FFmpeg 可能在 out_time_us 与 out_time_ms 中都输出微秒值；
            # 默认按微秒换算，仅对旧版本产生的较小数值回退到毫秒尺度。
                        if key == "out_time_ms" and raw_out_time < 1_000_000:
                            out_time_seconds = raw_out_time / 1000
                        else:
                            out_time_seconds = raw_out_time / 1_000_000
                    except ValueError:
                        out_time_seconds = None
            elif key == "total_size":
                try:
                    total_size_bytes = int(value)
                except ValueError:
                    total_size_bytes = None
        else:
            current_time = re.search(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
            if current_time:
                out_time_seconds = cls._parse_clock_to_seconds(current_time.group(1))

        progress_value = cls._estimate_progress(
            out_time_seconds=out_time_seconds,
            total_size_bytes=total_size_bytes,
            expected_duration=next_duration,
            expected_size_bytes=expected_size_bytes,
        )
        return next_duration, total_size_bytes, progress_value

    @classmethod
    def is_available(cls) -> bool:
        
        return FFmpegExternalTool.is_available()

    @classmethod
    def should_use(cls, video_item: VideoItem) -> bool:
        # ffmpeg 的 -readrate 按媒体时长限速，并不是 KB/s 带宽上限。用户启用限速时
        # 让策略链继续回退到受 TransferRateLimiter 控制的 HTTP 下载，避免设置假生效。
        try:
            if int(cfg.get("download", "speed_limit_kb", 0) or 0) > 0:
                return False
        except (TypeError, ValueError):
            pass
        duration_sec = video_item.meta.get("duration", 0)
        size_mb = video_item.meta.get("size_mb", 0)
        return bool(size_mb > cls.SIZE_THRESHOLD_MB or duration_sec > cls.DURATION_THRESHOLD_SEC)

    @staticmethod
    def _start_validated_media_proxy(
        video_item: VideoItem,
        headers: dict[str, str],
        upstream_proxy: str | None,
    ):
        """通过本地受控代理隔离 ffmpeg，禁止其直接访问未经校验的上游地址。"""
        # HLS 下载器已依赖 FFmpegExternalTool 做封装转换；此处延迟导入协议无关的
        # 本地代理，避免两个模块在初始化阶段形成循环依赖。
        from .m3u8 import N_m3u8DL_RE_Downloader

        return N_m3u8DL_RE_Downloader()._start_local_hls_proxy(
            video_item,
            headers,
            upstream_proxy,
        )

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        
        original_url = video_item.url
        url = original_url
        user_agent_source = video_item.source or "douyin"
        user_agent = self._resolve_runtime_user_agent(
            video_item,
            source=user_agent_source,
            configured_user_agent=cfg.get(
                user_agent_source,
                "user_agent",
                cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT),
            ),
        )
        headers = {
            "User-Agent": user_agent,
            "Referer": video_item.meta.get("referer", "https://www.douyin.com/"),
        }
        trace_id = video_item.meta.get("trace_id")
        ffmpeg = FFmpegExternalTool.resolve_executable()
        if not ffmpeg:
            raise ExternalToolNotFoundError("未找到 ffmpeg.exe")
        proxy = video_item.meta.get("proxy")
        proxies = requests_proxy_mapping(proxy)
        request_timeout = cfg.get("download", "request_timeout", 60)
        domain_policy = self._domain_policy_for_item(video_item)
        if domain_policy is not None:
            domain_policy.require_public_url(original_url)
        expected_duration = None
        raw_duration = video_item.meta.get("duration")
        if isinstance(raw_duration, (int, float)) and raw_duration > 0:
            expected_duration = float(raw_duration)
        expected_size_bytes = None
        def _resolve_stream_url(source_url: str) -> tuple[str, int | None]:
            """跟随一次重定向并读取 content-length，给 ffmpeg 进度估算提供基准。"""
            resolved_url = source_url
            resolved_size = expected_size_bytes
            try:
                request_kwargs = self._domain_policy_request_kwargs(domain_policy, source_url)
                resp = requests.head(
                    source_url,
                    headers=headers,
                    timeout=request_timeout,
                    allow_redirects=True,
                    proxies=proxies,
                    **request_kwargs,
                )
                real_url = resp.url
                content_length = resp.headers.get("content-length")
                if content_length:
                    try:
                        resolved_size = int(content_length)
                    except ValueError:
                        resolved_size = None
                debug_logger.log_api(
                    component="FFmpegDownloader",
                    api_name="head_redirect",
                    request={"url": source_url},
                    response_summary={"real_url": real_url, "content_length": resp.headers.get("content-length")},
                    message="ffmpeg 下载前检查真实地址",
                    status_code=resp.status_code,
                    trace_id=trace_id,
                )
                if real_url != source_url:
                    resolved_url = real_url
            except requests.RequestException as exc:
                debug_logger.log_exception(
                    "FFmpegDownloader",
                    "head_redirect",
                    exc,
                    context={"url": source_url},
                    trace_id=trace_id,
                )
            return resolved_url, resolved_size

        startupinfo = build_hidden_startupinfo()

        max_retries = self._coerce_retry_count(cfg.get("download", "max_retries", 3))
        temp_path = save_path + ".downloading"
        if isinstance(getattr(video_item, "meta", None), dict):
            # 记录给文件服务删除失败项时使用，避免只删最终文件而漏掉 ffmpeg 半成品。
            temp_files = list(video_item.meta.get("download_temp_files") or [])
            if temp_path not in temp_files:
                temp_files.append(temp_path)
            video_item.meta["download_temp_files"] = temp_files
        for attempt in range(max_retries + 1):
            attempt_completed = False
            local_proxy = None
            stderr_tail: deque[str] = deque(maxlen=12)
            if domain_policy is None:
                current_url, current_expected_size = _resolve_stream_url(original_url)
            else:
            # 额外的 HEAD 预检会在受控代理之外重新打开 DNS 与重定向链路，
            # 既破坏已完成的地址校验，也不会增加安全性，因此直接省略。
                current_url, current_expected_size = original_url, None
            url = current_url
            if current_expected_size:
                expected_size_bytes = current_expected_size
            command_headers = headers
            command_proxy = proxy
            if domain_policy is not None:
                local_proxy = self._start_validated_media_proxy(video_item, headers, proxy)
                url = local_proxy.url
                command_headers = {"User-Agent": user_agent}
                command_proxy = None
            cmd = FFmpegExternalTool.build_download_command(
                ffmpeg,
                url,
                temp_path,
                command_headers,
                proxy=command_proxy,
                timeout_seconds=request_timeout,
            )
            debug_logger.log_command(
                component="FFmpegDownloader",
                tool_name="ffmpeg",
                command_args=cmd,
                message="准备调用 ffmpeg 执行下载",
                context={
                    "save_path": save_path,
                    "temp_path": temp_path,
                    "source_url": url,
                    "title": video_item.title,
                    "attempt": attempt + 1,
                },
                trace_id=trace_id,
            )
            process = None
            stderr_thread = None
            try:
                process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                )
                last_progress_time = time.time()
                last_progress = 0
                stderr_queue: queue.Queue[bytes | None] = queue.Queue()
                stderr_closed = False
                stderr_pipe = process.stderr

                def _pump_stderr(
                    stderr=stderr_pipe,
                    target_queue: queue.Queue[bytes | None] = stderr_queue,
                ) -> None:
                    """持续读取 stderr，避免操作系统管道阻塞子进程。

                    ``stderr_queue`` 没有容量上限；主线程消费滞后时，已读取的数据仍
                    可能在内存中积压。
                    """
                    if stderr is None:
                        target_queue.put(None)
                        return
                    try:
                        while True:
                            line = stderr.readline()
                            if not line:
                                break
                            target_queue.put(line)
                    except (OSError, RuntimeError, ValueError) as exc:
                        debug_logger.log_exception("FFmpegDownloader", "stderr_pump", exc)
                    finally:
                        target_queue.put(None)

                stderr_thread = threading.Thread(
                    target=_pump_stderr,
                    name="ffmpeg-stderr-pump",
                    daemon=True,
                )
                stderr_thread.start()

                while True:
                    if check_stop_func():
                        process.kill()
                        raise DownloaderStoppedError("用户停止下载")

                    try:
                        line = stderr_queue.get(timeout=self.STDERR_POLL_INTERVAL_SEC)
                    except queue.Empty:
                        line = b""
                    if line is None:
                        stderr_closed = True
                        line = b""
                    if not line:
                        if time.time() - last_progress_time > self.PROGRESS_TIMEOUT_SEC:
                            # 长时间没有任何输出时认为外部工具卡住；杀进程后进入重试/失败路径。
                            process.kill()
                            break
                        if process.poll() is not None and stderr_closed:
                            break
                        continue

                    last_progress_time = time.time()
                    line_str = line.decode("utf-8", errors="ignore").strip()
                    if line_str:
                        stderr_tail.append(line_str)
                    expected_duration, _observed_size_bytes, parsed_progress = self._parse_progress_line(
                        line_str,
                        expected_duration=expected_duration,
                        expected_size_bytes=expected_size_bytes,
                    )
                    if parsed_progress is not None and parsed_progress > last_progress:
                        last_progress = parsed_progress
                        self._emit_progress(progress_callback, parsed_progress)

                process.wait()
                if process.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    self._finalize_download(temp_path, save_path)
                    attempt_completed = True
                    self._emit_progress(progress_callback, 100)
                    debug_logger.log(
                        component="FFmpegDownloader",
                        action="download_finished",
                        message="ffmpeg 下载完成",
                        status_code="FFMPEG_OK",
                        details={"save_path": save_path, "source_url": url, "title": video_item.title},
                        trace_id=trace_id,
                    )
                    return
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    raise ExternalToolError(f"ffmpeg 下载失败 (Code: {process.returncode})")
            except DownloaderStoppedError:
                raise
            except DomainPolicyViolation as exc:
                raise ExternalToolError(f"ffmpeg 下载地址违反公网访问策略: {exc}") from exc
            except (OSError, RuntimeError, ValueError, ExternalToolError) as exc:
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    debug_logger.log_exception(
                        "FFmpegDownloader",
                        "download_error",
                        exc,
                        context={"save_path": save_path, "source_url": url, "title": video_item.title, "stderr_tail": list(stderr_tail)},
                        trace_id=trace_id,
                    )
                    raise ExternalToolError(f"ffmpeg 下载失败: {exc}") from exc
            finally:
                if process is not None:
                    # 外部工具失败时必须先收掉进程和管道，再清理临时文件，Windows 上尤其容易被句柄占用。
                    returncode = getattr(process, "returncode", None)
                    if returncode is None:
                        try:
                            returncode = process.poll()
                        except Exception:
                            returncode = None
                    if returncode is None:
                        try:
                            process.kill()
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            debug_logger.log_exception("FFmpegDownloader", "kill_process", exc)
                    stderr = getattr(process, "stderr", None)
                    close_stderr = getattr(stderr, "close", None)
                    if callable(close_stderr):
                        try:
                            close_stderr()
                        except (OSError, RuntimeError, ValueError) as exc:
                            debug_logger.log_exception("FFmpegDownloader", "close_stderr", exc)
                    if returncode is None:
                        try:
                            process.wait(timeout=2)
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            debug_logger.log_exception("FFmpegDownloader", "wait_process_after_kill", exc)
                if stderr_thread is not None:
                    try:
                        stderr_thread.join(timeout=1)
                    except RuntimeError as exc:
                        debug_logger.log_exception("FFmpegDownloader", "join_stderr_thread", exc)
                if local_proxy is not None:
                    local_proxy.stop()
                if not attempt_completed:
                    try:
                        for cleanup_path in (temp_path, save_path):
                            if os.path.exists(cleanup_path):
                                os.remove(cleanup_path)
                    except OSError:
                        pass
