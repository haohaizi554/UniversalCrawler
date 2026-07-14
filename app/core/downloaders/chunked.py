"""下载器模块，负责 `app/core/downloaders/chunked.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, StreamDownloadError
from app.models import VideoItem
from shared.runtime_options import DomainPolicyViolation

from .base import BaseDownloader, ProgressCallback, StopCheck, TransferRateLimiter

class ChunkedDownloader(BaseDownloader):
    """适用于大文件的 Range 分块下载器，支持每个分片独立续传和重试。"""

    THREAD_COUNT = 8
    CHUNK_SIZE = 8 * 1024 * 1024
    SIZE_THRESHOLD_MB = 200
    DURATION_THRESHOLD_SEC = 600

    @classmethod
    def _effective_thread_count(cls) -> int:
        """把全局下载并发折算到单任务分片数，避免多个大文件一起把连接数打满。"""
        max_concurrent = max(1, int(cfg.get("download", "max_concurrent", 3)))
        return max(1, cls.THREAD_COUNT // max_concurrent)

    @classmethod
    def should_use(cls, video_item: VideoItem) -> bool:
        
        duration_sec = video_item.meta.get("duration", 0)
        size_mb = video_item.meta.get("size_mb", 0)
        return bool(size_mb > cls.SIZE_THRESHOLD_MB or duration_sec > cls.DURATION_THRESHOLD_SEC)

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        
        url = video_item.url
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
        proxy = video_item.meta.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        timeout = cfg.get("download", "request_timeout", 60)
        retry_count = self._coerce_retry_count(cfg.get("download", "max_retries", 3))
        resume_enabled = self._coerce_bool_setting(cfg.get("download", "resume_enabled", True))
        domain_policy = self._domain_policy_for_item(video_item)
        try:
            request_kwargs = self._domain_policy_request_kwargs(domain_policy, url)
            resp = requests.head(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                proxies=proxies,
                **request_kwargs,
            )
            resp.raise_for_status()
        except DomainPolicyViolation as exc:
            raise StreamDownloadError(f"分块下载地址违反公网访问策略: {exc}") from exc
        except requests.RequestException as exc:
            raise StreamDownloadError(f"分块下载预检查失败: {exc}") from exc

        total_size = int(resp.headers.get("content-length", 0))
        if total_size <= 0:
            raise StreamDownloadError("无法获取文件大小，回退到普通下载")
        accept_ranges = resp.headers.get("accept-ranges", "").lower()
        source_etag = resp.headers.get("etag") or resp.headers.get("ETag")
        source_last_modified = resp.headers.get("last-modified") or resp.headers.get("Last-Modified")
        # 这里必须先确认服务端显式支持 Range；否则多线程分块会把整文件重复下载多份。
        if "bytes" not in accept_ranges:
            raise StreamDownloadError("服务器不支持 Range 分块下载")

        chunk_count = max(1, total_size // self.CHUNK_SIZE)
        thread_budget = self._effective_thread_count()
        if chunk_count > thread_budget:
            chunk_count = thread_budget
        chunk_size = total_size // chunk_count

        # 每个分片使用 HTTP Range 的闭区间 [start, end]，最后一片吸收除不尽的尾部字节。
        chunks: list[tuple[int, int]] = []
        for i in range(chunk_count):
            start = i * chunk_size
            end = start + chunk_size - 1
            if i == chunk_count - 1:
                end = total_size - 1
            chunks.append((start, end))

        temp_dir = os.path.dirname(save_path)
        base_name = os.path.basename(save_path)
        # 分片临时文件隐藏在目标目录下，删除媒体时可以按 `.<filename>.partN` 精准清理。
        temp_files = [os.path.join(temp_dir, f".{base_name}.part{i}") for i in range(chunk_count)]
        manifest_file = os.path.join(temp_dir, f".{base_name}.parts.json")
        resume_manifest = {
            "version": 1,
            "url": str(getattr(resp, "url", "") or url),
            "total_size": total_size,
            "etag": str(source_etag or ""),
            "last_modified": str(source_last_modified or ""),
            "chunks": [[start, end] for start, end in chunks],
        }

        downloaded_bytes = [0] * chunk_count
        # 所有 Range 线程共享一个 limiter，配置含义是“单任务总速度”，不是每个分片各自一份额度。
        rate_limiter = TransferRateLimiter(cfg.get("download", "speed_limit_kb", 0))
        lock = threading.Lock()
        error_event = threading.Event()
        stop_event = threading.Event()
        error_holder: list[Exception] = []

        def cleanup_temp_files() -> None:
            """只清理本次分配出的分片文件，避免误删同目录其他下载缓存。"""
            for temp_file in [*temp_files, manifest_file]:
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

        def record_error(exc: Exception) -> None:
            with lock:
                error_holder.append(exc)
            error_event.set()

        def has_matching_resume_manifest() -> bool:
            if not source_etag and not source_last_modified:
                return False
            try:
                with open(manifest_file, encoding="utf-8") as fp:
                    return json.load(fp) == resume_manifest
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return False

        if not resume_enabled or not has_matching_resume_manifest():
            cleanup_temp_files()

        if resume_enabled:
            manifest_parent = temp_dir or "."
            os.makedirs(manifest_parent, exist_ok=True)
            manifest_temp: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    prefix=f".{base_name}.parts.",
                    suffix=".tmp",
                    dir=manifest_parent,
                    delete=False,
                ) as fp:
                    manifest_temp = fp.name
                    json.dump(resume_manifest, fp, separators=(",", ":"), ensure_ascii=True)
                    fp.flush()
                    os.fsync(fp.fileno())
                os.replace(manifest_temp, manifest_file)
                manifest_temp = None
            except OSError as exc:
                cleanup_temp_files()
                raise StreamDownloadError(f"无法创建分片续传清单: {exc}") from exc
            finally:
                if manifest_temp:
                    try:
                        os.remove(manifest_temp)
                    except OSError:
                        pass

        def download_chunk(idx: int, start_byte: int, end_byte: int, temp_file: str) -> bool | None:
            chunk_length = end_byte - start_byte + 1
            last_error: Exception | None = None

            for attempt in range(retry_count + 1):
                if stop_event.is_set() or error_event.is_set():
                    return None
                try:
                    request_kwargs = self._domain_policy_request_kwargs(domain_policy, url)
                    existing_size = 0
                    if resume_enabled and os.path.exists(temp_file):
                        actual_size = os.path.getsize(temp_file)
                        if actual_size > chunk_length:
                            # 旧任务或不同资源留下的超长分片不能直接参与合并。
                            with open(temp_file, "wb"):
                                pass
                            actual_size = 0
                        existing_size = actual_size
                    if existing_size >= chunk_length:
                        with lock:
                            downloaded_bytes[idx] = chunk_length
                        return True

                    request_start = start_byte + existing_size if resume_enabled else start_byte
                    request_headers = headers.copy()
                    # 分块下载强依赖 206；如果服务端回 200，说明 Range 没生效，应立即失败回退。
                    request_headers["Range"] = f"bytes={request_start}-{end_byte}"
                    if source_etag:
                        request_headers["If-Range"] = str(source_etag)
                    with lock:
                        downloaded_bytes[idx] = existing_size if resume_enabled else 0
                    with requests.get(
                        url,
                        headers=request_headers,
                        stream=True,
                        timeout=timeout,
                        proxies=proxies,
                        **request_kwargs,
                    ) as response:
                        if response.status_code != 206:
                            raise StreamDownloadError(f"分块请求未返回 206: {response.status_code}")
                        response.raise_for_status()
                        content_range = response.headers.get("content-range") or response.headers.get("Content-Range")
                        parsed_range = self._parse_content_range_header(content_range)
                        if parsed_range != (request_start, end_byte, total_size):
                            raise StreamDownloadError(
                                "分块响应范围不匹配: "
                                f"expected bytes {request_start}-{end_byte}/{total_size}, got {content_range!r}"
                            )
                        mode = "ab" if resume_enabled and existing_size > 0 else "wb"
                        with open(temp_file, mode) as fp:
                            for chunk_data in response.iter_content(chunk_size=65536):
                                if stop_event.is_set() or error_event.is_set():
                                    return None
                                if check_stop_func():
                                    stop_event.set()
                                    raise DownloaderStoppedError("用户停止下载")
                                if chunk_data:
                                    fp.write(chunk_data)
                                    rate_limiter.throttle(
                                        len(chunk_data),
                                        lambda: stop_event.is_set() or check_stop_func(),
                                    )
                                    with lock:
                                        downloaded_bytes[idx] += len(chunk_data)
                        if os.path.getsize(temp_file) != chunk_length:
                            raise StreamDownloadError(
                                f"分块长度不完整: expected {chunk_length}, got {os.path.getsize(temp_file)}"
                            )
                    return True
                except DownloaderStoppedError:
                    record_error(DownloaderStoppedError("用户停止下载"))
                    return False
                except DomainPolicyViolation as exc:
                    record_error(StreamDownloadError(f"分块下载地址违反公网访问策略: {exc}"))
                    return False
                except (requests.RequestException, OSError, ValueError, RuntimeError, StreamDownloadError) as exc:
                    last_error = exc
                    if attempt < retry_count:
                        debug_logger.log(
                            component="ChunkedDownloader",
                            action="chunk_retry",
                            level="WARN",
                            message=f"分块下载失败，准备重试 ({attempt + 1}/{retry_count})",
                            status_code="DL_CHUNK_RETRY",
                            details={
                                "chunk_index": idx,
                                "attempt": attempt + 1,
                                "max_retries": retry_count,
                                "resume_enabled": resume_enabled,
                                "resume_offset": existing_size,
                                "start_byte": start_byte,
                                "end_byte": end_byte,
                                "error": str(exc),
                            },
                            trace_id=video_item.meta.get("trace_id") if video_item.meta else None,
                        )
                        time.sleep(1 if retry_count <= 3 else 3)
                        continue
                    record_error(exc)
                    return False
                except Exception as exc:
                    debug_logger.log_exception("ChunkedDownloader", "download_chunk", exc)
                    record_error(StreamDownloadError(f"分片线程异常: {type(exc).__name__}: {exc}"))
                    return False
            if last_error is not None:
                record_error(last_error)
            return False

        threads: list[threading.Thread] = []
        completed = False
        try:
            for index, (start, end) in enumerate(chunks):
                thread = threading.Thread(target=download_chunk, args=(index, start, end, temp_files[index]), daemon=True)
                thread.start()
                threads.append(thread)

            last_progress = -1
            while any(thread.is_alive() for thread in threads):
                if stop_event.is_set():
                    for thread in threads:
                        thread.join(timeout=5)
                    raise DownloaderStoppedError("用户停止下载")

                if error_event.is_set():
                    for thread in threads:
                        thread.join(timeout=5)
                    first_error = error_holder[0] if error_holder else StreamDownloadError("分块下载失败")
                    if isinstance(first_error, DownloaderStoppedError):
                        raise first_error
                    raise StreamDownloadError(f"分块下载失败: {first_error}") from first_error

                with lock:
                    total_downloaded = sum(downloaded_bytes)
                percent = int(total_downloaded / total_size * 100) if total_size > 0 else 0
                if percent != last_progress:
                    try:
                        self._emit_progress(progress_callback, percent, bytes_downloaded=total_downloaded, bytes_total=total_size)
                    except Exception as exc:
                        error_event.set()
                        for thread in threads:
                            thread.join(timeout=5)
                        raise StreamDownloadError(f"分块下载进度回调失败: {exc}") from exc
                    last_progress = percent
                time.sleep(0.1)

            for thread in threads:
                thread.join()

            if error_event.is_set():
                first_error = error_holder[0] if error_holder else StreamDownloadError("分块下载失败")
                if isinstance(first_error, DownloaderStoppedError):
                    raise first_error
                raise StreamDownloadError(f"分块下载失败: {first_error}") from first_error

            try:
                self._emit_progress(progress_callback, 98, bytes_downloaded=total_size, bytes_total=total_size)
                for temp_file, (start, end) in zip(temp_files, chunks):
                    expected_size = end - start + 1
                    try:
                        actual_size = os.path.getsize(temp_file)
                    except OSError as exc:
                        raise StreamDownloadError(f"分片文件缺失: {temp_file}") from exc
                    if actual_size != expected_size:
                        raise StreamDownloadError(
                            f"分片合并前校验失败: {temp_file}, expected {expected_size}, got {actual_size}"
                        )
                # 所有分片成功后再串行合并，保证最终文件只在数据完整时出现。
                self._merge_temp_files_atomically(temp_files, save_path)
            except Exception as exc:
                raise StreamDownloadError(f"分块下载合并失败: {exc}") from exc
            self._emit_progress(progress_callback, 100, bytes_downloaded=total_size, bytes_total=total_size)
            completed = True
        finally:
            if not completed:
                stop_event.set()
                for thread in threads:
                    if thread.is_alive():
                        thread.join(timeout=5)
            all_threads_stopped = not any(thread.is_alive() for thread in threads)
            if all_threads_stopped:
                cleanup_temp_files()
            else:
                # 守护线程仍可能持有文件句柄，此时强删容易失败或留下半删状态，交给后续清扫兜底。
                debug_logger.log(
                    component="ChunkedDownloader",
                    action="cleanup_deferred",
                    level="WARN",
                    message="Deferred temp-file cleanup because chunk worker threads are still running",
                    status_code="CHUNK_CLEANUP_DEFERRED",
                    details={"save_path": save_path, "alive_threads": sum(1 for thread in threads if thread.is_alive())},
                    trace_id=video_item.meta.get("trace_id") if video_item.meta else None,
                )
    @staticmethod
    def _merge_temp_files_atomically(temp_files: list[str], save_path: str) -> None:
        """Build a complete sidecar before atomically publishing the final file."""
        merging_path = f"{save_path}.merging"
        try:
            with open(merging_path, "wb") as output_fp:
                for temp_file in temp_files:
                    with open(temp_file, "rb") as input_fp:
                        while True:
                            data = input_fp.read(65536)
                            if not data:
                                break
                            output_fp.write(data)
                output_fp.flush()
                os.fsync(output_fp.fileno())
            os.replace(merging_path, save_path)
        finally:
            try:
                if os.path.exists(merging_path):
                    os.remove(merging_path)
            except OSError:
                pass
