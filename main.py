# main.py

import sys
import os
import time
import ctypes

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from PyQt6.QtCore import QUrl, Qt, QTimer
# 引入项目模块
from app.ui.main_window import MainWindow
from app.core.download_manager import DownloadManager
from app.core.registry import registry
from app.models import VideoItem
from app.utils import cfg, sanitize_filename

class ApplicationController:
    def __init__(self):
        if os.name == 'nt':
            try:
                myappid = 'mygeekapp.universalcrawler.pro.v1'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except:
                pass

        # 1. 初始化 Qt 应用
        self.app = QApplication(sys.argv)
        if os.path.exists("favicon.ico"):
            self.app.setWindowIcon(QIcon("favicon.ico"))
        # 2. 初始化主窗口
        self.window = MainWindow()
        # 3. 内部状态
        self.videos = {}  # {id: VideoItem} 内存中持有视频对象
        self.current_spider = None
        self.current_playing_id = None  # 记录当前正在播放的视频ID
        # 4. 初始化下载管理器 (默认3并发)
        self.dl_manager = DownloadManager(max_concurrent=3)
        # ================= 信号连接：UI -> Controller =================
        self.window.sig_start_crawl.connect(self.start_crawl)
        self.window.sig_stop_crawl.connect(self.stop_crawl)
        self.window.sig_change_dir.connect(self.on_dir_changed)
        self.window.sig_play_video.connect(self.play_video)
        self.window.sig_delete_video.connect(self.delete_video)
        # 连接表格重命名信号
        self.window.table.itemChanged.connect(self.on_rename_video)
        # ================= 信号连接：DownloadManager -> Controller =================
        self.dl_manager.task_started.connect(self.on_dl_start)
        self.dl_manager.task_progress.connect(self.on_dl_progress)
        self.dl_manager.task_finished.connect(self.on_dl_finish)
        self.dl_manager.task_error.connect(self.on_dl_error)
        # 5. 显示窗口
        self.window.show()
        # 延迟执行本地扫描，防止启动时 UI 尚未就绪导致崩溃 (0xC0000409)
        QTimer.singleShot(200, self.scan_local_dir)




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
            # 1. 获取所有mp4文件
            all_files = [f for f in os.listdir(directory) if f.lower().endswith('.mp4')]
            # 2. 按修改时间倒序排列 (最新的在前)
            all_files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)
            # 3. [防崩溃] 限制最大加载数量
            MAX_SCAN_COUNT = 1000
            if len(all_files) > MAX_SCAN_COUNT:
                self.window.append_log(f"⚠️ 视频过多 ({len(all_files)}个)，仅加载最新的 {MAX_SCAN_COUNT} 个以防卡顿。")
                all_files = all_files[:MAX_SCAN_COUNT]
            count = 0
            for f in all_files:
                title = os.path.splitext(f)[0]
                item = VideoItem(url="", title=title, source="local")
                item.status = "✅ 本地"
                item.progress = 100
                item.local_path = os.path.join(directory, f)
                self.videos[item.id] = item
                self.window.add_video_row(item)
                count += 1
            if count > 0:
                self.window.append_log(f"✅ 已加载 {count} 个本地视频")
            else:
                self.window.append_log("ℹ️ 该目录下没有找到 MP4 视频")
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
        if new_title == video.title: return
        if not os.path.exists(video.local_path):
            # 回滚 UI
            self.window.table.blockSignals(True)
            item.setText(video.title)
            self.window.table.blockSignals(False)
            return
        # 执行文件重命名
        try:
            old_path = video.local_path
            dir_name = os.path.dirname(old_path)
            # 确保新文件名合法
            safe_name = sanitize_filename(new_title) + ".mp4"
            new_path = os.path.join(dir_name, safe_name)
            if new_path != old_path:
                # [关键] 如果正在播放该视频，先释放句柄
                if self.current_playing_id == vid:
                    self.window.player.setSource(QUrl())
                os.rename(old_path, new_path)
                # 更新内存对象
                video.title = new_title
                video.local_path = new_path
                self.window.append_log(f"📝 重命名成功: {safe_name}")
                # 如果刚才被迫停止了播放，重新加载新路径
                if self.current_playing_id == vid:
                    self.play_video(vid)
        except OSError as e:
            # 失败回滚
            self.window.table.blockSignals(True)
            item.setText(video.title)
            self.window.table.blockSignals(False)
            self.window.append_log(f"❌ 重命名失败: {e}")
            QMessageBox.warning(self.window, "错误", f"重命名文件失败:\n{e}")
    def delete_video(self, row, vid):
        """删除视频 (UI -> Controller -> FileSystem)"""
        video = self.videos.get(vid)
        if not video: return
        reply = QMessageBox.question(
            self.window, '确认删除',
            f"确定要删除 '{video.title}' 吗？\n本地文件将被永久移除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.No: return
        # 1. 释放文件占用
        # 如果当前正在播放这个视频，必须先让播放器停止并加载空源
        if self.current_playing_id == vid:
            self.window.player.stop()
            self.window.player.setSource(QUrl())  # 释放文件锁
            self.current_playing_id = None
            self.window.vid_w.update()  # 刷新黑屏
            time.sleep(0.1)  # 给系统一点时间释放句柄
        # 2. 尝试物理删除
        if video.local_path and os.path.exists(video.local_path):
            try:
                os.remove(video.local_path)
                self.window.append_log(f"🗑️ 已删除文件: {os.path.basename(video.local_path)}")
            except OSError as e:
                self.window.append_log(f"❌ 删除文件失败: {e}")
                QMessageBox.critical(self.window, "删除失败", f"无法删除文件 (可能被占用):\n{e}")
                return  # 删除失败则不更新 UI
        # 3. 只有文件删除了，才更新 UI 和内存
        self.window.table.removeRow(row)
        if vid in self.videos:
            del self.videos[vid]
        # 4. 按钮错位问题
        self.window.refresh_table_bindings()
    # ---------------- 爬虫控制 ----------------
    def start_crawl(self, keyword, plugin_id, options):
        plugin = registry.get_plugin(plugin_id)
        if not plugin: return
        self.window.append_log(f"🟢 启动任务 | 模式: {plugin.name}")
        # MissAV 依赖检查
        if plugin_id == "missav" and not os.path.exists("N_m3u8DL-RE.exe"):
            QMessageBox.critical(self.window, "缺失依赖", "未找到 N_m3u8DL-RE.exe")
            self.reset_ui_state()
            return
        # 停止旧任务
        if self.current_spider and self.current_spider.isRunning():
            self.current_spider.stop()
            self.current_spider.wait()
        # 创建新爬虫
        SpiderClass = plugin.get_spider_class()
        self.current_spider = SpiderClass(keyword, options)
        # 连接信号
        self.current_spider.sig_log.connect(self.window.append_log)
        self.current_spider.sig_item_found.connect(self.on_video_found)
        self.current_spider.sig_finished.connect(self.on_spider_finished)
        # [核心] 连接弹窗请求信号
        self.current_spider.sig_select_tasks.connect(self.on_spider_select_tasks)
        self.current_spider.start()
    def on_spider_select_tasks(self, items):
        # 响应爬虫发来的“请让用户选择”请求
        # 弹出 UI 对话框 (阻塞主线程，直到用户关闭弹窗)
        selected_indices = self.window.show_selection_dialog(items)
        # 将结果传回给爬虫线程 (解除爬虫的阻塞)
        if self.current_spider:
            self.current_spider.resume_from_ui(selected_indices)
    def stop_crawl(self):
        if self.current_spider:
            self.current_spider.stop()
            self.window.append_log("🛑 正在停止爬虫...")
    def on_spider_finished(self):
        self.window.append_log("🏁 爬虫任务结束")
        self.reset_ui_state()
        self.current_spider = None
    def reset_ui_state(self):
        self.window.btn_start.setEnabled(True)
        self.window.btn_stop.setEnabled(False)
        self.window.inp_search.setEnabled(True)
        self.window.combo_source.setEnabled(True)
        if self.window.plugin_widget: self.window.plugin_widget.setEnabled(True)

    def on_video_found(self, video_item):
        save_path = self.window.current_save_dir
        if "folder_name" in video_item.meta:
            folder_name = video_item.meta["folder_name"]
            # 确保 folder_name 有效
            if folder_name and folder_name.strip():
                sub_dir = os.path.join(save_path, folder_name)
                if not os.path.exists(sub_dir):
                    try:
                        os.makedirs(sub_dir)
                    except:
                        pass
                save_path = sub_dir
                # 更新 UI 提示
                self.window.lbl_full_path.setText(save_path)
                self.window.lbl_full_path.setToolTip(save_path)
        self.videos[video_item.id] = video_item
        self.window.add_video_row(video_item)
        self.dl_manager.add_task(video_item, save_path)
    # ---------------- 下载回调 ----------------
    def on_dl_start(self, vid):
        if vid in self.videos:
            self.videos[vid].status = "downloading"
            self.window.update_video_status(vid, "⬇️ 下载中")
    def on_dl_progress(self, vid, percent):
        if vid in self.videos:
            self.videos[vid].progress = percent
            self.window.update_video_status(vid, "⬇️ 下载中", percent)
    def on_dl_finish(self, vid):
        if vid in self.videos:
            self.videos[vid].status = "finished"
            self.videos[vid].progress = 100
            self.window.update_video_status(vid, "✅ 完成", 100)
            self.window.append_log(f"🎉 下载完成: {self.videos[vid].title}")
    def on_dl_error(self, vid, msg):
        if vid in self.videos:
            self.videos[vid].status = "error"
            self.window.update_video_status(vid, "❌ 失败")
            self.window.append_log(f"❌ 下载出错 [{self.videos[vid].title}]: {msg}")
    def play_video(self, vid):
        video = self.videos.get(vid)
        if not video or not os.path.exists(video.local_path):
            self.window.append_log("❌ 文件不存在或已被删除")
            return
        self.current_playing_id = vid
        self.window.append_log(f"▶️ 播放: {video.title}")
        self.window.player.setSource(QUrl.fromLocalFile(video.local_path))
        self.window.player.play()
        # 切换图标
        self.window.btn_play.setIcon(self.window.style().standardIcon(self.window.style().StandardPixmap.SP_MediaPause))
    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    controller = ApplicationController()
    controller.run()