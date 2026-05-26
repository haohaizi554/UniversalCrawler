#!/usr/bin/env python3
"""
Universal Crawler Pro - 入口文件
职责: 组装UI、爬虫、下载器，处理信号交互
"""
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtMultimedia import QMediaPlayer
from app.ui.main_window import MainWindow
from app.models import VideoItem
from app.core.download_manager import DownloadManager
from app.utils import cfg, sanitize_filename


class ApplicationController:
    """应用控制器，协调各组件"""

    # 支持的视频和图片格式
    VIDEO_EXTENSIONS = ('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv', '.m4v', '.webm')
    IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    ALL_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS + IMAGE_EXTENSIONS

    def __init__(self):
        self.app = QApplication(sys.argv)

        # 设置应用程序ID（Windows任务栏图标需要）
        self.app.setApplicationName("Universal Crawler Pro")
        self.app.setOrganizationName("UCP")
        try:
            # Windows 任务栏图标需要设置 AppUserModelID
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ucp.crawler.v1")
        except:
            pass

        # 设置应用程序图标（任务栏图标）
        icon_path = os.path.join(project_root, "favicon.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.app.setWindowIcon(app_icon)

        self.window = MainWindow()
        self.window.show()

        # 状态
        self.videos = {}  # id -> VideoItem
        self.current_playing_id = None

        # 下载管理器
        self.dl_manager = DownloadManager(max_concurrent=3)
        self._connect_download_signals()

        # 绑定UI信号
        self.window.sig_start_crawl.connect(self.on_start_crawl)
        self.window.sig_stop_crawl.connect(self.on_stop_crawl)
        self.window.sig_change_dir.connect(self.on_dir_changed)
        self.window.sig_play_video.connect(self.play_video)
        self.window.sig_delete_video.connect(self.on_delete_video)
        self.window.table.itemChanged.connect(self.on_rename_video)

        # 延迟扫描本地文件 (避免启动卡顿)
        QTimer.singleShot(200, self.scan_local_dir)

    def _connect_download_signals(self):
        self.dl_manager.task_started.connect(
            lambda vid: self._update_video_status(vid, "⏳ 下载中...", 0)
        )
        self.dl_manager.task_progress.connect(
            lambda vid, p: self._update_video_progress(vid, p)
        )
        self.dl_manager.task_finished.connect(
            lambda vid: self._on_download_finished(vid)
        )
        self.dl_manager.task_error.connect(
            lambda vid, e: self._on_download_error(vid, e)
        )

    def _update_video_status(self, vid, status, progress=None):
        if vid in self.videos:
            self.videos[vid].status = status
            self.window.update_video_status(vid, status, progress)

    def _update_video_progress(self, vid, progress):
        if vid in self.videos:
            self.videos[vid].progress = progress
            self.window.update_video_status(vid, self.videos[vid].status, progress)

    def _on_download_finished(self, vid):
        if vid in self.videos:
            self.videos[vid].status = "✅ 完成"
            self.videos[vid].progress = 100
            self.window.update_video_status(vid, "✅ 完成", 100)
            self.window.append_log(f"✅ 下载完成: {self.videos[vid].title}")

    def _on_download_error(self, vid, error):
        if vid in self.videos:
            self.videos[vid].status = f"❌ 失败"
            self.window.update_video_status(vid, f"❌ 失败")
            self.window.append_log(f"❌ 下载失败 [{self.videos[vid].title}]: {error}")

    # ---------------- 本地文件管理 ----------------
    def scan_local_dir(self):
        """扫描本地文件 (限制数量防止崩溃)"""
        directory = self.window.current_save_dir
        self.window.append_log(f"📂 正在扫描目录: {directory}")
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except:
                pass
            return
        self.window.table.setRowCount(0)
        self.videos.clear()
        try:
            # 1. 获取所有视频和图片文件
            all_files = [f for f in os.listdir(directory) if f.lower().endswith(self.ALL_MEDIA_EXTENSIONS)]
            # 2. 按修改时间倒序排列 (最新的在前)
            all_files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)
            # 3. [防崩溃] 限制最大加载数量
            MAX_SCAN_COUNT = 1000
            if len(all_files) > MAX_SCAN_COUNT:
                self.window.append_log(f"⚠️ 文件过多 ({len(all_files)}个)，仅加载最新的 {MAX_SCAN_COUNT} 个以防卡顿。")
                all_files = all_files[:MAX_SCAN_COUNT]
            count = 0
            for f in all_files:
                title = os.path.splitext(f)[0]
                ext = os.path.splitext(f)[1].lower()
                item = VideoItem(url="", title=title, source="local")
                item.status = "✅ 本地"
                item.progress = 100
                item.local_path = os.path.join(directory, f)
                # 标记内容类型
                if ext in self.VIDEO_EXTENSIONS:
                    item.meta["content_type"] = "video"
                elif ext in self.IMAGE_EXTENSIONS:
                    item.meta["content_type"] = "image"
                self.videos[item.id] = item
                self.window.add_video_row(item)
                count += 1
            if count > 0:
                video_count = sum(1 for v in self.videos.values() if v.meta.get("content_type") == "video")
                image_count = sum(1 for v in self.videos.values() if v.meta.get("content_type") == "image")
                self.window.append_log(f"✅ 已加载 {count} 个本地文件 (视频: {video_count}, 图片: {image_count})")
            else:
                self.window.append_log("ℹ️ 该目录下没有找到视频或图片")
        except Exception as e:
            self.window.append_log(f"❌ 扫描目录出错: {e}")

    def on_dir_changed(self):
        self.window.append_log(f"📂 目录已变更: {self.window.current_save_dir}")
        self.dl_manager.save_dir = self.window.current_save_dir
        self.window.table.setRowCount(0)
        self.videos.clear()
        self.scan_local_dir()

    def on_rename_video(self, item):
        """处理表格重命名"""
        # 只有第一列(标题)变化才处理
        if item.column() != 0: return
        vid = item.data(Qt.ItemDataRole.UserRole)
        if not vid or vid not in self.videos: return
        video = self.videos[vid]
        new_title = item.text().strip()
        # 如果标题没变，或者文件不存在，忽略
        if new_title == video.title or not os.path.exists(video.local_path):
            item.setText(video.title)  # 恢复原名称
            return
        # 生成新路径 (保持原扩展名)
        old_path = video.local_path
        ext = os.path.splitext(old_path)[1]
        safe_name = sanitize_filename(new_title) + ext
        new_path = os.path.join(self.window.current_save_dir, safe_name)
        # 如果新文件名已存在，阻止重命名
        if os.path.exists(new_path) and new_path.lower() != old_path.lower():
            self.window.append_log(f"⚠️ 重命名失败: 文件名 '{safe_name}' 已存在")
            item.setText(video.title)
            return
        try:
            os.rename(old_path, new_path)
            video.title = new_title
            video.local_path = new_path
            item.setToolTip(new_title)
            self.window.append_log(f"📝 重命名: {os.path.basename(old_path)} -> {safe_name}")
        except Exception as e:
            self.window.append_log(f"❌ 重命名失败: {e}")
            item.setText(video.title)

    def on_delete_video(self, row_idx, vid):
        """删除视频 (文件+表格行)"""
        if vid not in self.videos:
            self.window.table.removeRow(row_idx)
            return
        video = self.videos[vid]
        file_path = video.local_path
        # 删除文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                self.window.append_log(f"🗑️ 已删除: {os.path.basename(file_path)}")
            except Exception as e:
                self.window.append_log(f"❌ 删除文件失败: {e}")
                return
        else:
            self.window.append_log(f"ℹ️ 文件不存在，仅从列表移除: {video.title}")
        # 删除内存对象和表格行
        del self.videos[vid]
        self.window.table.removeRow(row_idx)
        self.window.refresh_table_bindings()

    # ---------------- 爬虫任务 ----------------
    def on_start_crawl(self, keyword, source_id, config):
        """启动爬虫任务"""
        from app.core.registry import registry
        plugin = registry.get_plugin(source_id)
        if not plugin:
            self.window.append_log("❌ 未知的爬虫源")
            return
        self.window.append_log(f"🟢 启动任务 | 模式: {plugin.name}")
        self.window.btn_start.setEnabled(False)
        self.window.btn_stop.setEnabled(True)
        # 实例化爬虫 (BaseSpider 只接受 keyword 和 config)
        spider_cls = plugin.get_spider_class()
        self.current_spider = spider_cls(
            keyword=keyword,
            config=config,
        )
        # 连接爬虫信号
        self.current_spider.sig_log.connect(self.window.append_log)
        self.current_spider.sig_item_found.connect(self._on_spider_item_found)
        self.current_spider.sig_select_tasks.connect(self._on_spider_select_tasks)
        self.current_spider.sig_finished.connect(self._on_spider_finished)
        self.current_spider.start()

    def _on_spider_item_found(self, item):
        """爬虫发现一个视频"""
        item.status = "⏳ 等待中"
        item.progress = 0
        self.videos[item.id] = item
        self.window.add_video_row(item)
        # 加入下载队列
        self.dl_manager.add_task(item, self.window.current_save_dir)

    def _on_spider_select_tasks(self, items):
        """爬虫请求用户选择任务（在主线程弹窗）"""
        selected = self.window.show_selection_dialog(items)
        # 唤醒爬虫线程，传入用户选择结果
        if hasattr(self, 'current_spider') and self.current_spider:
            self.current_spider.resume_from_ui(selected)

    def _on_spider_finished(self):
        """爬虫完成"""
        self.window.append_log("✅ 爬虫任务结束")
        self.window.btn_start.setEnabled(True)
        self.window.btn_stop.setEnabled(False)
        self.window.inp_search.setEnabled(True)
        self.window.combo_source.setEnabled(True)
        if self.window.plugin_widget:
            self.window.plugin_widget.setEnabled(True)

    def on_stop_crawl(self):
        """停止爬虫任务"""
        if hasattr(self, 'current_spider') and self.current_spider:
            self.current_spider.stop()
            self.window.append_log("🛑 正在停止任务...")

    # ---------------- 播放器 ----------------
    def play_video(self, vid):
        video = self.videos.get(vid)
        if not video or not os.path.exists(video.local_path):
            self.window.append_log("❌ 文件不存在或已被删除")
            return
        self.current_playing_id = vid
        self.window.append_log(f"▶️ 播放: {video.title}")

        # 判断文件类型
        ext = os.path.splitext(video.local_path)[1].lower()
        image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')

        if ext in image_exts:
            # 图片类型
            self.window.show_image(video.local_path)
        else:
            # 视频类型
            self.window.play_video(video.local_path)
            # 切换图标
            self.window.btn_play.setIcon(self.window.style().standardIcon(self.window.style().StandardPixmap.SP_MediaPause))

    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    controller = ApplicationController()
    controller.run()
