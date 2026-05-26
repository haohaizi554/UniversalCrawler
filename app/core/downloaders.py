# app/core/downloaders.py

import os
import time
import requests
import subprocess
import threading


class BaseDownloader:
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        raise NotImplementedError


# ============================================================
#  多线程分块下载器（大文件 MP4 专用，进度实时同步）
# ============================================================

class ChunkedDownloader:
    """多线程分块下载器

    - 将文件分成 N 个块，每块一个线程
    - 每个块写入独立临时文件
    - 全部完成后合并为最终文件
    - 进度通过 progress_callback 实时上报
    """

    THREAD_COUNT = 8          # 线程数
    CHUNK_SIZE = 8 * 1024 * 1024  # 每块 8MB
    SIZE_THRESHOLD_MB = 200   # 大小阈值
    DURATION_THRESHOLD_SEC = 600  # 时长阈值

    @classmethod
    def should_use(cls, video_item):
        """判断是否应该使用多线程分块下载"""
        duration_sec = video_item.meta.get("duration", 0)
        size_mb = video_item.meta.get("size_mb", 0)
        if size_mb > cls.SIZE_THRESHOLD_MB or duration_sec > cls.DURATION_THRESHOLD_SEC:
            return True
        return False

    @classmethod
    def download(cls, url, save_path, headers, progress_callback, check_stop_func):
        """执行多线程分块下载"""
        # 1. 获取文件大小
        resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        total_size = int(resp.headers.get('content-length', 0))
        if total_size <= 0:
            raise Exception("无法获取文件大小，回退到普通下载")

        size_mb = total_size / (1024 * 1024)
        print(f"[Chunked] 文件大小: {size_mb:.1f}MB, 线程数: {cls.THREAD_COUNT}")

        # 2. 计算分块
        chunk_count = max(1, total_size // cls.CHUNK_SIZE)
        if chunk_count > cls.THREAD_COUNT:
            chunk_count = cls.THREAD_COUNT
        chunk_size = total_size // chunk_count

        chunks = []
        for i in range(chunk_count):
            start = i * chunk_size
            end = start + chunk_size - 1
            if i == chunk_count - 1:
                end = total_size - 1
            chunks.append((start, end))

        # 3. 创建临时文件
        temp_dir = os.path.dirname(save_path)
        base_name = os.path.basename(save_path)
        temp_files = []
        for i in range(chunk_count):
            temp_files.append(os.path.join(temp_dir, f".{base_name}.part{i}"))

        # 4. 下载状态
        downloaded_bytes = [0] * chunk_count
        lock = threading.Lock()
        error_event = threading.Event()
        stop_event = threading.Event()

        def download_chunk(idx, start_byte, end_byte, temp_file):
            """下载单个分块"""
            try:
                h = headers.copy()
                h["Range"] = f"bytes={start_byte}-{end_byte}"
                with requests.get(url, headers=h, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(temp_file, 'wb') as f:
                        for chunk_data in r.iter_content(chunk_size=65536):
                            if stop_event.is_set():
                                return
                            if error_event.is_set():
                                return
                            if check_stop_func():
                                stop_event.set()
                                return
                            if chunk_data:
                                f.write(chunk_data)
                                with lock:
                                    downloaded_bytes[idx] += len(chunk_data)
                return True
            except Exception as e:
                print(f"[Chunked] 分块 {idx} 下载失败: {e}")
                error_event.set()
                return False

        # 5. 启动线程
        threads = []
        for i, (start, end) in enumerate(chunks):
            t = threading.Thread(target=download_chunk, args=(i, start, end, temp_files[i]))
            t.start()
            threads.append(t)

        # 6. 监控进度
        last_progress = -1
        while any(t.is_alive() for t in threads):
            if stop_event.is_set():
                for t in threads:
                    t.join(timeout=2)
                # 清理临时文件
                for tf in temp_files:
                    try: os.remove(tf)
                    except: pass
                raise InterruptedError("用户停止下载")

            if error_event.is_set():
                for t in threads:
                    t.join(timeout=2)
                for tf in temp_files:
                    try: os.remove(tf)
                    except: pass
                raise Exception("分块下载失败")

            with lock:
                total_downloaded = sum(downloaded_bytes)
            if total_size > 0:
                percent = int(total_downloaded / total_size * 100)
                if percent != last_progress:
                    progress_callback(percent)
                    last_progress = percent
            time.sleep(0.1)

        # 等待所有线程结束
        for t in threads:
            t.join()

        if error_event.is_set():
            for tf in temp_files:
                try: os.remove(tf)
                except: pass
            raise Exception("分块下载失败")

        # 7. 合并文件
        progress_callback(98)
        with open(save_path, 'wb') as outf:
            for tf in temp_files:
                with open(tf, 'rb') as inf:
                    while True:
                        data = inf.read(65536)
                        if not data:
                            break
                        outf.write(data)

        # 8. 清理临时文件
        for tf in temp_files:
            try: os.remove(tf)
            except: pass

        progress_callback(100)
        print(f"[Chunked] 下载完成: {os.path.basename(save_path)}")


# ============================================================
#  N_m3u8DL-RE 下载器（仅用于 M3U8/HLS 流）
# ============================================================

class N_m3u8DL_RE_Downloader(BaseDownloader):
    """使用 N_m3u8DL-RE.exe 下载 M3U8/HLS 流视频"""

    EXE_PATH = "N_m3u8DL-RE.exe"

    @classmethod
    def is_available(cls):
        return os.path.exists(cls.EXE_PATH)

    @classmethod
    def is_m3u8_url(cls, url):
        """判断是否是 M3U8 链接"""
        url_lower = url.lower()
        return ".m3u8" in url_lower or "m3u8" in url_lower

    def download(self, video_item, save_path, progress_callback, check_stop_func):
        if not self.is_available():
            raise FileNotFoundError(f"未找到 {self.EXE_PATH}")

        url = video_item.url
        ua = video_item.meta.get("ua", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        referer = video_item.meta.get("referer", "https://www.douyin.com/")

        save_dir = os.path.dirname(save_path)
        save_name_no_ext = os.path.splitext(os.path.basename(save_path))[0]

        cmd = [
            self.EXE_PATH,
            url,
            "--save-dir", save_dir,
            "--save-name", save_name_no_ext,
            "--thread-count", "16",
            "--download-retry-count", "10",
            "--auto-select", "true",
            "--header", f"User-Agent: {ua}",
            "--header", f"Referer: {referer}",
            "--mux-after-done", "format=mp4"
        ]

        creation_flags = 0
        if os.name == 'nt':
            creation_flags = subprocess.CREATE_NEW_CONSOLE

        progress_callback(10)

        try:
            process = subprocess.Popen(cmd, creationflags=creation_flags)
            while process.poll() is None:
                if check_stop_func():
                    process.kill()
                    raise InterruptedError("用户停止下载")
                time.sleep(1)
                progress_callback(50)

            if process.returncode != 0:
                raise Exception(f"N_m3u8DL-RE 异常退出 (Code: {process.returncode})")

            progress_callback(100)
        except InterruptedError:
            raise
        except Exception as e:
            raise Exception(f"N_m3u8DL-RE 下载失败: {e}")


# ============================================================
#  快手下载器
# ============================================================

class KuaishouDownloader(BaseDownloader):
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": video_item.meta.get("referer", "https://www.kuaishou.com/")
        }
        if "cookies" in video_item.meta:
            cookie_dict = video_item.meta["cookies"]
            if isinstance(cookie_dict, dict):
                headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        temp_path = save_path + ".downloading"
        max_retries = 3
        success = False
        for attempt in range(max_retries):
            if check_stop_func(): break
            try:
                with requests.get(video_item.url, headers=headers, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if check_stop_func(): raise InterruptedError("用户停止下载")
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    percent = int((downloaded / total_size) * 100)
                                    if downloaded % (8192 * 100) == 0 or percent == 100:
                                        progress_callback(percent)
                success = True
                break
            except InterruptedError:
                break
            except Exception as e:
                print(f"⚠️ [Kuaishou] 下载中断: {e}")
                time.sleep(3)
        if success:
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except: pass
            os.rename(temp_path, save_path)
            progress_callback(100)
        else:
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass
            if not check_stop_func():
                raise Exception("下载失败")


# ============================================================
#  MissAV 下载器
# ============================================================

class MissAVDownloader(BaseDownloader):
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        downloader = N_m3u8DL_RE_Downloader()
        video_item.meta.setdefault("referer", video_item.meta.get("referer", "https://missav.ai/"))
        return downloader.download(video_item, save_path, progress_callback, check_stop_func)


# ============================================================
#  Bilibili 下载器
# ============================================================

class BilibiliDownloader(BaseDownloader):
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        ffmpeg_path = "ffmpeg.exe"
        if not os.path.exists(ffmpeg_path):
            try:
                subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ffmpeg_path = "ffmpeg"
            except:
                raise FileNotFoundError("未找到 ffmpeg.exe，无法合并音视频")
        video_url = video_item.url
        audio_url = video_item.meta.get("audio_url")
        headers = {
            "User-Agent": video_item.meta.get("ua", "Mozilla/5.0"),
            "Referer": video_item.meta.get("referer", "https://www.bilibili.com")
        }
        save_dir = os.path.dirname(save_path)
        base_name = os.path.splitext(os.path.basename(save_path))[0]
        temp_v = os.path.join(save_dir, f"{base_name}_video.m4s")
        temp_a = os.path.join(save_dir, f"{base_name}_audio.m4s")

        def download_stream(url, path):
            if not url: return False
            try:
                with requests.get(url, headers=headers, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    with open(path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if check_stop_func(): raise InterruptedError
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if ".m4s" in path and total > 0:
                                    progress_callback(int((downloaded / total) * 80))
                return True
            except Exception as e:
                if os.path.exists(path): os.remove(path)
                raise e

        progress_callback(10)
        try:
            download_stream(video_url, temp_v)
            has_audio = False
            if audio_url:
                progress_callback(85)
                download_stream(audio_url, temp_a)
                has_audio = True
            progress_callback(90)
            cmd_merge = [ffmpeg_path, "-y", "-i", temp_v]
            if has_audio:
                cmd_merge.extend(["-i", temp_a])
            cmd_merge.extend(["-c", "copy", save_path])
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(
                cmd_merge, check=True, startupinfo=startupinfo,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            try:
                if os.path.exists(temp_v): os.remove(temp_v)
                if os.path.exists(temp_a): os.remove(temp_a)
            except: pass
            progress_callback(100)
        except InterruptedError:
            if os.path.exists(temp_v): os.remove(temp_v)
            if os.path.exists(temp_a): os.remove(temp_a)
            raise InterruptedError("用户停止下载")
        except Exception as e:
            if os.path.exists(temp_v): os.remove(temp_v)
            if os.path.exists(temp_a): os.remove(temp_a)
            raise Exception(f"B站下载失败: {e}")

# ============================================================
#  ffmpeg 下载器（大文件 MP4 专用，单流稳定下载）
# ============================================================

class FFmpegDownloader:
    """使用 ffmpeg 下载大文件 MP4

    ffmpeg 优势：
    - 单流下载，不会被 CDN 拒绝
    - 内置重试和超时处理
    - 支持断点续传
    - 自动处理重定向
    """

    EXE_PATH = "ffmpeg.exe"
    SIZE_THRESHOLD_MB = 200
    DURATION_THRESHOLD_SEC = 600

    @classmethod
    def is_available(cls):
        if os.path.exists(cls.EXE_PATH):
            return True
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except:
            return False

    @classmethod
    def should_use(cls, video_item):
        duration_sec = video_item.meta.get("duration", 0)
        size_mb = video_item.meta.get("size_mb", 0)
        return size_mb > cls.SIZE_THRESHOLD_MB or duration_sec > cls.DURATION_THRESHOLD_SEC

    @classmethod
    def download(cls, url, save_path, headers, progress_callback, check_stop_func):
        """使用 ffmpeg 下载文件，带重试机制"""
        if not cls.is_available():
            raise FileNotFoundError("未找到 ffmpeg.exe")

        ffmpeg = cls.EXE_PATH if os.path.exists(cls.EXE_PATH) else "ffmpeg"

        # 先尝试获取重定向后的真实 URL
        try:
            resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
            real_url = resp.url
            if real_url != url:
                print(f"[FFmpeg] URL 重定向: {url[:50]}... -> {real_url[:50]}...")
                url = real_url
        except Exception as e:
            print(f"[FFmpeg] URL 重定向获取失败，使用原 URL: {e}")

        # 构建 ffmpeg 命令，添加重试参数
        cmd = [
            ffmpeg, "-y",
            "-user_agent", headers.get("User-Agent", "Mozilla/5.0"),
            "-headers", f"Referer: {headers.get('Referer', '')}\r\n",
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-timeout", "60000000",  # 60秒
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-bufsize", "10M",
            save_path
        ]

        # 隐藏 ffmpeg 控制台窗口
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        progress_callback(5)
        import re

        max_retries = 3
        for attempt in range(max_retries):
            try:
                process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                )

                duration_match = None
                last_progress_time = time.time()

                while True:
                    if check_stop_func():
                        process.kill()
                        raise InterruptedError("用户停止下载")

                    # 设置非阻塞读取
                    import select
                    if os.name != 'nt':
                        ready, _, _ = select.select([process.stderr], [], [], 1.0)
                        if not ready:
                            # 检查是否超时无进度
                            if time.time() - last_progress_time > 30:
                                print(f"[FFmpeg] 30秒无进度，终止重试...")
                                process.kill()
                                break
                            continue

                    line = process.stderr.readline()
                    if not line:
                        break

                    last_progress_time = time.time()
                    line_str = line.decode('utf-8', errors='ignore').strip()

                    # 解析总时长
                    if duration_match is None:
                        dm = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})', line_str)
                        if dm:
                            duration_match = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + int(dm.group(3))

                    # 解析当前时间
                    if duration_match and duration_match > 0:
                        tm = re.search(r'time=(\d{2}):(\d{2}):(\d{2})', line_str)
                        if tm:
                            current = int(tm.group(1)) * 3600 + int(tm.group(2)) * 60 + int(tm.group(3))
                            percent = min(99, int(current / duration_match * 100))
                            progress_callback(percent)

                process.wait()

                if process.returncode == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    progress_callback(100)
                    print(f"[FFmpeg] 下载完成: {os.path.basename(save_path)}")
                    return

                # 失败，尝试重试
                if attempt < max_retries - 1:
                    print(f"[FFmpeg] 下载失败，{3 - attempt}秒后重试...")
                    time.sleep(3)
                else:
                    raise Exception(f"ffmpeg 下载失败 (Code: {process.returncode})")

            except InterruptedError:
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[FFmpeg] 错误: {e}，{3 - attempt}秒后重试...")
                    time.sleep(3)
                else:
                    raise Exception(f"ffmpeg 下载失败: {e}")


# ============================================================
#  抖音下载器
# ============================================================
class DouyinDownloader(BaseDownloader):
    """抖音下载器 - 自动选择最佳下载方式

    下载策略：
    1. 图集/实况 → 逐文件下载
    2. M3U8 链接 → N_m3u8DL-RE
    3. 所有 MP4 → Python 下载（自动重试）
    """
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/"
        }

        is_gallery = video_item.meta.get("is_gallery", False)
        images_data = video_item.meta.get("images_data", [])

        if is_gallery and images_data:
            return self._download_gallery(video_item, images_data, save_path, progress_callback, check_stop_func, headers)

        url = video_item.url

        # M3U8 链接 → N_m3u8DL-RE
        if N_m3u8DL_RE_Downloader.is_m3u8_url(url) and N_m3u8DL_RE_Downloader.is_available():
            print(f"[Douyin] M3U8 链接，使用 N_m3u8DL-RE: {video_item.title}")
            downloader = N_m3u8DL_RE_Downloader()
            video_item.meta.setdefault("referer", "https://www.douyin.com/")
            return downloader.download(video_item, save_path, progress_callback, check_stop_func)

        # 检测文件大小（用于日志）
        try:
            head_resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
            content_length = int(head_resp.headers.get('content-length', 0))
            size_mb = content_length / (1024 * 1024)
            video_item.meta["size_mb"] = size_mb
            print(f"[Douyin] 文件大小: {size_mb:.1f}MB")
        except Exception as e:
            print(f"[Douyin] HEAD 请求失败，直接下载: {e}")

        # 所有 MP4 统一使用 Python 下载
        return self._download_single(video_item, save_path, progress_callback, check_stop_func, headers)

    def _download_single(self, video_item, save_path, progress_callback, check_stop_func, headers):
        """下载单个文件（视频或单张图片），支持断点续传"""
        temp_path = save_path + ".downloading"
        max_retries = 5  # 增加重试次数
        success = False

        for attempt in range(max_retries):
            if check_stop_func(): break
            try:
                # 断点续传：检查已有临时文件大小
                existing_size = 0
                if os.path.exists(temp_path):
                    existing_size = os.path.getsize(temp_path)

                h = headers.copy()
                if existing_size > 0:
                    h["Range"] = f"bytes={existing_size}-"
                    print(f"[Douyin] 断点续传: 已有 {existing_size / (1024*1024):.1f}MB")

                with requests.get(video_item.url, headers=h, stream=True, timeout=120) as r:
                    r.raise_for_status()

                    # 获取总大小
                    total_size = int(r.headers.get('content-length', 0))
                    if existing_size > 0 and r.status_code == 206:
                        # 服务器支持断点续传，content-length 是剩余部分
                        total_size = existing_size + total_size
                    elif existing_size > 0 and r.status_code == 200:
                        # 服务器不支持断点续传，重新下载
                        existing_size = 0

                    mode = 'ab' if existing_size > 0 and r.status_code == 206 else 'wb'
                    downloaded = existing_size

                    with open(temp_path, mode) as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if check_stop_func(): raise InterruptedError("用户停止下载")
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    percent = int((downloaded / total_size) * 100)
                                    progress_callback(percent)

                success = True
                break
            except InterruptedError:
                break
            except Exception as e:
                print(f"[Douyin] 下载中断 ({attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)  # 等待 3 秒后重试

        if success:
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except: pass
            os.rename(temp_path, save_path)
            progress_callback(100)
        else:
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass
            if not check_stop_func():
                raise Exception("下载失败，请检查网络或链接是否失效")

    def _download_gallery(self, video_item, images_data, save_path, progress_callback, check_stop_func, headers):
        """下载图集/实况照片"""
        save_dir = os.path.dirname(save_path)
        total_files = len(images_data)
        completed = 0

        for idx, img_info in enumerate(images_data):
            if check_stop_func():
                raise InterruptedError("用户停止下载")

            img_url = img_info.get('image_url', '')
            live_url = img_info.get('live_video_url', '')
            seq = idx + 1

            if live_url:
                live_filename = f"{video_item.title}_{seq}.mp4"
                live_save_path = os.path.join(save_dir, live_filename)
                self._download_file(live_url, live_save_path, headers, check_stop_func)
                completed += 1
                progress_callback(int(completed / total_files * 100))
            elif img_url:
                img_ext = ".jpeg"
                url_lower = img_url.lower()
                if ".png" in url_lower:
                    img_ext = ".png"
                elif ".webp" in url_lower:
                    img_ext = ".webp"

                img_filename = f"{video_item.title}_{seq}{img_ext}"
                img_save_path = os.path.join(save_dir, img_filename)
                self._download_file(img_url, img_save_path, headers, check_stop_func)
                completed += 1
                progress_callback(int(completed / total_files * 100))

        progress_callback(100)

    def _download_file(self, url, save_path, headers, check_stop_func):
        """下载单个文件到指定路径"""
        temp_path = save_path + ".downloading"
        max_retries = 3

        for attempt in range(max_retries):
            if check_stop_func():
                raise InterruptedError("用户停止下载")
            try:
                with requests.get(url, headers=headers, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if check_stop_func():
                                raise InterruptedError("用户停止下载")
                            if chunk:
                                f.write(chunk)
                if os.path.exists(save_path):
                    try: os.remove(save_path)
                    except: pass
                os.rename(temp_path, save_path)
                return
            except InterruptedError:
                raise
            except Exception as e:
                print(f"[Douyin] 文件下载失败 ({attempt + 1}/{max_retries}): {e}")
                time.sleep(1)

        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        raise Exception(f"文件下载失败: {os.path.basename(save_path)}")
