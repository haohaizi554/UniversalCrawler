from __future__ import annotations

import os
import threading
import time

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.exceptions import DownloaderStoppedError, StreamDownloadError
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck


class ChunkedDownloader(BaseDownloader):
    """多线程分块下载器。"""

    THREAD_COUNT = 8
    CHUNK_SIZE = 8 * 1024 * 1024
    SIZE_THRESHOLD_MB = 200
    DURATION_THRESHOLD_SEC = 600

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
        headers = {
            "User-Agent": video_item.meta.get("ua", cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT)),
            "Referer": video_item.meta.get("referer", "https://www.douyin.com/"),
        }
        timeout = cfg.get("download", "request_timeout", 60)
        try:
            resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise StreamDownloadError(f"分块下载预检查失败: {exc}") from exc

        total_size = int(resp.headers.get("content-length", 0))
        if total_size <= 0:
            raise StreamDownloadError("无法获取文件大小，回退到普通下载")
        accept_ranges = resp.headers.get("accept-ranges", "").lower()
        # 这里必须先确认服务端显式支持 Range；否则多线程分块会把整文件重复下载多份。
        if "bytes" not in accept_ranges:
            raise StreamDownloadError("服务器不支持 Range 分块下载")

        chunk_count = max(1, total_size // self.CHUNK_SIZE)
        if chunk_count > self.THREAD_COUNT:
            chunk_count = self.THREAD_COUNT
        chunk_size = total_size // chunk_count

        chunks: list[tuple[int, int]] = []
        for i in range(chunk_count):
            start = i * chunk_size
            end = start + chunk_size - 1
            if i == chunk_count - 1:
                end = total_size - 1
            chunks.append((start, end))

        temp_dir = os.path.dirname(save_path)
        base_name = os.path.basename(save_path)
        temp_files = [os.path.join(temp_dir, f".{base_name}.part{i}") for i in range(chunk_count)]

        downloaded_bytes = [0] * chunk_count
        lock = threading.Lock()
        error_event = threading.Event()
        stop_event = threading.Event()
        error_holder: list[Exception] = []

        def cleanup_temp_files() -> None:
            for temp_file in temp_files:
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

        def download_chunk(idx: int, start_byte: int, end_byte: int, temp_file: str) -> bool | None:
            try:
                request_headers = headers.copy()
                request_headers["Range"] = f"bytes={start_byte}-{end_byte}"
                with requests.get(url, headers=request_headers, stream=True, timeout=timeout) as response:
                    if response.status_code != 206:
                        raise StreamDownloadError(f"分块请求未返回 206: {response.status_code}")
                    response.raise_for_status()
                    with open(temp_file, "wb") as fp:
                        for chunk_data in response.iter_content(chunk_size=65536):
                            if stop_event.is_set() or error_event.is_set():
                                return None
                            if check_stop_func():
                                stop_event.set()
                                raise DownloaderStoppedError("用户停止下载")
                            if chunk_data:
                                fp.write(chunk_data)
                                with lock:
                                    downloaded_bytes[idx] += len(chunk_data)
                return True
            except DownloaderStoppedError:
                error_event.set()
                error_holder.append(DownloaderStoppedError("用户停止下载"))
                return False
            except (requests.RequestException, OSError, ValueError, RuntimeError, StreamDownloadError) as exc:
                error_event.set()
                error_holder.append(exc)
                return False

        threads: list[threading.Thread] = []
        for index, (start, end) in enumerate(chunks):
            thread = threading.Thread(target=download_chunk, args=(index, start, end, temp_files[index]), daemon=True)
            thread.start()
            threads.append(thread)

        last_progress = -1
        while any(thread.is_alive() for thread in threads):
            if stop_event.is_set():
                for thread in threads:
                    thread.join(timeout=2)
                cleanup_temp_files()
                raise DownloaderStoppedError("用户停止下载")

            if error_event.is_set():
                for thread in threads:
                    thread.join(timeout=2)
                cleanup_temp_files()
                first_error = error_holder[0] if error_holder else StreamDownloadError("分块下载失败")
                if isinstance(first_error, DownloaderStoppedError):
                    raise first_error
                raise StreamDownloadError(f"分块下载失败: {first_error}") from first_error

            with lock:
                total_downloaded = sum(downloaded_bytes)
            percent = int(total_downloaded / total_size * 100) if total_size > 0 else 0
            if percent != last_progress:
                progress_callback(percent)
                last_progress = percent
            time.sleep(0.1)

        for thread in threads:
            thread.join()

        if error_event.is_set():
            cleanup_temp_files()
            first_error = error_holder[0] if error_holder else StreamDownloadError("分块下载失败")
            if isinstance(first_error, DownloaderStoppedError):
                raise first_error
            raise StreamDownloadError(f"分块下载失败: {first_error}") from first_error

        progress_callback(98)
        with open(save_path, "wb") as output_fp:
            for temp_file in temp_files:
                with open(temp_file, "rb") as input_fp:
                    while True:
                        data = input_fp.read(65536)
                        if not data:
                            break
                        output_fp.write(data)

        cleanup_temp_files()
        progress_callback(100)
