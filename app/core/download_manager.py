# app/core/download_manager.py
import os
import re
import threading
import queue
from PyQt6.QtCore import QThread, pyqtSignal, QObject, QSemaphore
from app.models import VideoItem
from app.core.downloaders import KuaishouDownloader, MissAVDownloader, BilibiliDownloader, DouyinDownloader

class DownloadWorker(QThread):
    sig_start = pyqtSignal(str)
    sig_progress = pyqtSignal(str, int)
    sig_finished = pyqtSignal(str)
    sig_error = pyqtSignal(str, str)

    # 文件类型签名映射
    FILE_SIGNATURES = {
        b'\x89PNG': '.png',
        b'\xff\xd8\xff': '.jpg',
        b'GIF89a': '.gif',
        b'GIF87a': '.gif',
        b'RIFF': '.webp',  # webp 以 RIFF 开头
        b'\x00\x00\x00 ftyp': '.mp4',
        b'\x00\x00\x00\x1cftyp': '.mp4',
        b'\x00\x00\x00\x20ftyp': '.mp4',
        b'ID3': '.mp3',
        b'\xff\xfb': '.mp3',  # MPEG audio
        b'\xff\xf3': '.mp3',
        b'\xff\xf2': '.mp3',
        b'OggS': '.ogg',
        b'fLaC': '.flac',
        b'RIFF....AVI': '.avi',
    }

    def __init__(self, video: VideoItem, save_dir: str, semaphore: QSemaphore):
        super().__init__()
        self.video = video
        self.save_dir = save_dir
        self.semaphore = semaphore
        self.is_running = True
        self._final_ext = ".mp4"

    def run(self):
        self.semaphore.acquire()
        try:
            if not self.is_running: return
            self.sig_start.emit(self.video.id)

            # 构建保存路径：基础目录 + 文件夹（合集/图集时创建）
            save_dir = self.save_dir
            content_type = self.video.meta.get("content_type", "")
            is_gallery = self.video.meta.get("is_gallery", False)
            is_mix = self.video.meta.get("is_mix", False)
            # 合集或图集（多文件）才创建子文件夹，单个视频/图片直接保存到根目录
            if is_gallery or content_type == "gallery" or is_mix:
                folder_name = self.video.meta.get("folder_name", "")
                if folder_name:
                    save_dir = os.path.join(save_dir, folder_name)

            if not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            # 获取文件名 - 根据内容类型智能判断扩展名
            ext = ".mp4"  # 默认视频

            # 1. 优先根据 meta 中的内容类型判断
            content_type = self.video.meta.get("content_type", "")
            if content_type == "gallery":
                # 图集/实况 - 由下载器内部生成文件名，这里只生成占位路径
                ext = ".jpeg"
            elif content_type == "video":
                ext = ".mp4"
            else:
                # 2. 根据 URL 特征判断
                url_lower = self.video.url.lower()
                if ".gif" in url_lower:
                    ext = ".gif"
                elif ".webp" in url_lower:
                    ext = ".webp"
                elif ".png" in url_lower:
                    ext = ".png"
                elif ".jpeg" in url_lower or ".jpg" in url_lower:
                    ext = ".jpg"

            # 生成文件名（使用统一的命名格式）
            filename = self._generate_filename(ext)
            filepath = os.path.join(save_dir, filename)
            self.video.local_path = filepath
            self._final_ext = ext  # 保存扩展名供后续使用
            # 策略选择
            downloader = None
            if self.video.source == "kuaishou":
                downloader = KuaishouDownloader()
            elif self.video.source == "missav":
                downloader = MissAVDownloader()
            elif self.video.source == "bilibili":
                downloader = BilibiliDownloader()
            elif self.video.source == "douyin":
                downloader = DouyinDownloader()
            else:
                raise ValueError(f"Unknown source: {self.video.source}")
            # 执行下载 (传入回调和停止检查)
            downloader.download(
                video_item=self.video,
                save_path=filepath,
                progress_callback=lambda p: self.sig_progress.emit(self.video.id, p),
                check_stop_func=lambda: not self.is_running
            )
            
            # 下载完成后，根据实际文件内容修正扩展名
            if self.is_running and os.path.exists(filepath):
                actual_ext = self._detect_actual_file_type(filepath)
                if actual_ext and actual_ext != self._final_ext:
                    # 需要重命名文件
                    new_filepath = filepath.rsplit('.', 1)[0] + actual_ext
                    try:
                        os.rename(filepath, new_filepath)
                        self.video.local_path = new_filepath
                        print(f"[DownloadManager] 修正文件扩展名: {os.path.basename(filepath)} -> {os.path.basename(new_filepath)}")
                    except Exception as e:
                        print(f"[DownloadManager] 修正扩展名失败: {e}")
            
            if self.is_running:
                self.sig_finished.emit(self.video.id)
        except InterruptedError:
            self.sig_error.emit(self.video.id, "用户已停止")
        except Exception as e:
            self.sig_error.emit(self.video.id, str(e))
        finally:
            self.semaphore.release()

    def stop(self):
        self.is_running = False

    def _generate_filename(self, ext):
        """生成文件名: 只保留描述"""
        desc = self.video.title

        # 清理非法字符
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', desc).strip()
        if len(safe_name) > 200:
            safe_name = safe_name[:200]

        return f"{safe_name}{ext}"

    def _detect_actual_file_type(self, filepath: str) -> str:
        """根据文件头检测实际文件类型"""
        try:
            with open(filepath, 'rb') as f:
                header = f.read(32)  # 读取前32字节

            # 检查各种文件签名
            if header.startswith(b'\x89PNG'):
                return '.png'
            elif header.startswith(b'\xff\xd8\xff'):
                return '.jpg'
            elif header.startswith(b'GIF89a') or header.startswith(b'GIF87a'):
                return '.gif'
            elif header.startswith(b'RIFF'):
                # RIFF 可能是 WEBP 或 AVI
                if b'WEBP' in header[:12]:
                    return '.webp'
                elif b'AVI ' in header[:12]:
                    return '.avi'
            elif header.startswith(b'ID3') or header.startswith(b'\xff\xfb') or header.startswith(b'\xff\xf3') or header.startswith(b'\xff\xf2'):
                return '.mp3'
            elif b'ftyp' in header[:12]:
                # MP4/MOV 文件
                if b'mp4' in header[:12] or b'M4V' in header[:12] or b'M4A' in header[:12]:
                    return '.mp4'
                elif b'moov' in header[:12] or b'mdat' in header[:12]:
                    return '.mp4'
                else:
                    return '.mp4'  # 默认 mp4
            elif header.startswith(b'OggS'):
                return '.ogg'
            elif header.startswith(b'fLaC'):
                return '.flac'
            elif header.startswith(b'Matroska') or header.startswith(b'\x1aE\xdf\xa3'):
                return '.mkv'
            elif b'FLV' in header[:5]:
                return '.flv'

            # 如果无法识别，返回 None
            return None
        except Exception as e:
            print(f"[DownloadManager] 检测文件类型失败: {e}")
            return None

class DownloadManager(QObject):
    task_started = pyqtSignal(str)
    task_progress = pyqtSignal(str, int)
    task_finished = pyqtSignal(str)
    task_error = pyqtSignal(str, str)

    def __init__(self, max_concurrent=3):
        super().__init__()
        self.queue = queue.Queue()
        self.workers = []
        self.max_concurrent = max_concurrent
        self.semaphore = QSemaphore(max_concurrent)
        self.is_running = True
        self.dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatcher_thread.start()
    def add_task(self, video: VideoItem, save_dir: str):
        self.queue.put((video, save_dir))

    def _dispatch_loop(self):
        while self.is_running:
            try:
                video, save_dir = self.queue.get(timeout=1)
                self.workers = [w for w in self.workers if w.isRunning()]
                worker = DownloadWorker(video, save_dir, self.semaphore)
                worker.sig_start.connect(self.task_started)
                worker.sig_progress.connect(self.task_progress)
                worker.sig_finished.connect(self.task_finished)
                worker.sig_error.connect(self.task_error)
                self.workers.append(worker)
                worker.start()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Dispatcher Error: {e}")

    def stop_all(self):
        self.is_running = False
        # 清空队列
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                pass
        # 停止所有正在运行的工兵
        for w in self.workers:
            w.stop()
            w.wait()