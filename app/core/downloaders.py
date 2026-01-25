# app/core/downloaders.py

import os
import time
import requests
import subprocess
import signal

class BaseDownloader:
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        raise NotImplementedError

class KuaishouDownloader(BaseDownloader):
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        # 保持快手下载逻辑不变，因为它用的是 requests，且需要 cookie
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
                try:
                    os.remove(save_path)
                except:
                    pass
            os.rename(temp_path, save_path)
            progress_callback(100)
        else:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            if not check_stop_func():
                raise Exception("下载失败")

class MissAVDownloader(BaseDownloader):
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        exe_path = "N_m3u8DL-RE.exe"
        if not os.path.exists(exe_path):
            raise FileNotFoundError("未找到 N_m3u8DL-RE.exe")

        m3u8_url = video_item.url
        ua = video_item.meta.get("ua", "Mozilla/5.0")
        referer = video_item.meta.get("referer", "https://missav.ai/")

        save_dir = os.path.dirname(save_path)
        save_name_no_ext = os.path.splitext(os.path.basename(save_path))[0]

        cmd = [
            exe_path,
            m3u8_url,
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
            # 启动外部进程
            process = subprocess.Popen(cmd, creationflags=creation_flags)
            # 循环检查进程状态
            while process.poll() is None:
                if check_stop_func():
                    process.kill()
                    raise InterruptedError("用户停止下载")
                time.sleep(1)
                # 保持在50%直到完成，用户看弹窗进度
                progress_callback(50)
            if process.returncode != 0:
                raise Exception(f"外部下载器异常退出 (Code: {process.returncode})")
            progress_callback(100)
        except Exception as e:
            raise e


class BilibiliDownloader(BaseDownloader):
    def download(self, video_item, save_path, progress_callback, check_stop_func):
        # 1. 检查 ffmpeg
        ffmpeg_path = "ffmpeg.exe"
        if not os.path.exists(ffmpeg_path):
            # 尝试系统路径
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
        # 临时文件路径
        temp_v = os.path.join(save_dir, f"{base_name}_video.m4s")
        temp_a = os.path.join(save_dir, f"{base_name}_audio.m4s")
        # 2. 下载函数
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
                                # 简单估算进度 (只汇报视频流的)
                                if ".m4s" in path and total > 0:
                                    progress_callback(int((downloaded / total) * 80))  # 预留20%给合并
                return True
            except Exception as e:
                if os.path.exists(path): os.remove(path)
                raise e
        # 3. 执行下载
        progress_callback(10)
        try:
            # 下载视频
            download_stream(video_url, temp_v)
            # 下载音频 (如果有)
            has_audio = False
            if audio_url:
                progress_callback(85)
                download_stream(audio_url, temp_a)
                has_audio = True
            # 4. 合并 (Merge)
            progress_callback(90)
            cmd_merge = [ffmpeg_path, "-y", "-i", temp_v]
            if has_audio:
                cmd_merge.extend(["-i", temp_a])
            # copy流，无需转码，速度极快
            cmd_merge.extend(["-c", "copy", save_path])
            # 隐藏黑框执行
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(
                cmd_merge,
                check=True,
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # 清理临时文件
            try:
                if os.path.exists(temp_v): os.remove(temp_v)
                if os.path.exists(temp_a): os.remove(temp_a)
            except:
                pass
            progress_callback(100)
        except InterruptedError:
            # 清理垃圾
            if os.path.exists(temp_v): os.remove(temp_v)
            if os.path.exists(temp_a): os.remove(temp_a)
            raise InterruptedError("用户停止下载")
        except Exception as e:
            # 清理垃圾
            if os.path.exists(temp_v): os.remove(temp_v)
            if os.path.exists(temp_a): os.remove(temp_a)
            raise Exception(f"B站下载失败: {e}")