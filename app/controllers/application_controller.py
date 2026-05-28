#!/usr/bin/env python3
"""
应用控制器
职责: 组装 UI、服务层、爬虫、下载器，处理信号交互
"""
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.config import cfg
from app.core.download_manager import DownloadManager
from app.core.plugin_registry import registry
from app.debug_logger import debug_logger
from app.exceptions import DebugActionError, FileOperationError, MediaScanError
from app.models import VideoItem
from app.services.debug_service import DebugArtifactsService
from app.services.file_service import MediaLibraryService
from app.ui.main_window import MainWindow
from app.utils.runtime_paths import install_root, resolve_resource_file


class ApplicationController:
    """应用控制器，协调各组件。"""

    VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm")
    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    def __init__(self):
        self.project_root = install_root()
        self.app = QApplication(sys.argv)
        self.file_service = MediaLibraryService(self.VIDEO_EXTENSIONS, self.IMAGE_EXTENSIONS)
        self.debug_service = DebugArtifactsService()

        debug_logger.log(
            component="ApplicationController",
            action="app_init",
            message="应用开始初始化",
            status_code="APP_INIT",
            details={"project_root": str(self.project_root)},
        )

        self.app.setApplicationName("Universal Crawler Pro")
        self.app.setOrganizationName("UCP")
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ucp.crawler.v1")
        except (ImportError, AttributeError, OSError) as exc:
            debug_logger.log_exception("ApplicationController", "set_app_user_model_id", exc)

        icon_path = resolve_resource_file("favicon.ico")
        if icon_path.exists():
            self.app.setWindowIcon(QIcon(str(icon_path)))

        self.window = MainWindow()
        self.window.show()
        self.app.aboutToQuit.connect(self.shutdown)

        self.videos: dict[str, VideoItem] = {}
        self.current_playing_id: str | None = None
        self.current_spider = None

        self.dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))
        self._connect_download_signals()
        self._connect_window_signals()

        QTimer.singleShot(200, self.scan_local_dir)
        debug_logger.log(
            component="ApplicationController",
            action="app_ready",
            message="主窗口初始化完成",
            status_code="APP_READY",
            details={"save_dir": self.window.current_save_dir},
        )

    def _connect_window_signals(self):
        """集中绑定 UI 发出的业务信号。"""
        self.window.sig_start_crawl.connect(self.on_start_crawl)
        self.window.sig_stop_crawl.connect(self.on_stop_crawl)
        self.window.sig_change_dir.connect(self.on_dir_changed)
        self.window.sig_play_video.connect(self.play_video)
        self.window.sig_delete_video.connect(self.on_delete_video)
        self.window.sig_open_latest_log.connect(self.open_latest_log)
        self.window.sig_open_error_summary.connect(self.open_latest_error_summary)
        self.window.sig_copy_trace_id.connect(self.copy_trace_id_for_video)
        self.window.bind_video_rename(self.on_rename_video)

    def _connect_download_signals(self):
        """下载管理器回调只在这里接入一次，避免散落在构造流程里。"""
        self.dl_manager.task_started.connect(self._on_task_started)
        self.dl_manager.task_progress.connect(self._on_task_progress)
        self.dl_manager.task_finished.connect(self._on_task_finished)
        self.dl_manager.task_error.connect(self._on_task_error)

    def _on_task_started(self, video_id: str) -> None:
        self._update_video_status(video_id, "⏳ 下载中...", 0)

    def _on_task_progress(self, video_id: str, progress: int) -> None:
        self._update_video_progress(video_id, progress)

    def _on_task_finished(self, video_id: str) -> None:
        self._on_download_finished(video_id)

    def _on_task_error(self, video_id: str, error: str) -> None:
        self._on_download_error(video_id, error)

    def _has_active_spider(self) -> bool:
        return bool(self.current_spider and self.current_spider.isRunning())

    def _item_trace_id(self, item: VideoItem | None) -> str | None:
        return item.meta.get("trace_id") if item else None

    def _item_context(self, item: VideoItem | None) -> dict:
        if not item:
            return {}
        return {
            "trace_id": self._item_trace_id(item),
            "video_id": item.id,
            "source": item.source,
        }

    def _item_details(self, item: VideoItem | None) -> dict:
        if not item:
            return {}
        return debug_logger.pick_used(
            {
                "title": item.title,
                "url": item.url,
                "local_path": item.local_path,
                "content_type": item.meta.get("content_type"),
                "media_label": item.meta.get("media_label"),
                "folder_name": item.meta.get("folder_name"),
                "aweme_id": item.meta.get("aweme_id"),
                "audio_url": item.meta.get("audio_url"),
                "download_strategy": item.meta.get("download_strategy"),
                "referer": item.meta.get("referer"),
            },
            "title",
            "url",
            "local_path",
            "content_type",
            "media_label",
            "folder_name",
            "aweme_id",
            "audio_url",
            "download_strategy",
            "referer",
        )

    def _summarize_active_config(self, config: dict) -> dict:
        return {k: v for k, v in config.items() if v not in (None, "", [], {})}

    def _report_debug_action_error(self, action: str, exc: Exception):
        self.window.append_log(f"❌ {action}失败: {exc}")
        debug_logger.log_exception("ApplicationController", action, exc)

    def _run_debug_action(self, success_message: str, action_name: str, func) -> None:
        try:
            func()
            self.window.append_log(success_message)
        except DebugActionError as exc:
            self._report_debug_action_error(action_name, exc)

    def _log_crawl_start(self, plugin_name: str, keyword: str, source_id: str, config: dict) -> None:
        debug_logger.log(
            component="ApplicationController",
            action="start_crawl",
            message="用户启动爬虫任务",
            status_code="APP_CRAWL_START",
            details={
                "keyword": keyword,
                "source_id": source_id,
                "plugin_name": plugin_name,
                "active_config": self._summarize_active_config(config),
            },
        )

    def _apply_video_state(self, vid: str, *, status: str | None = None, progress: int | None = None) -> VideoItem | None:
        """统一维护内存状态和表格状态，避免多个回调各写一遍。"""
        item = self.videos.get(vid)
        if not item:
            return None
        if status is not None:
            item.status = status
        if progress is not None:
            item.progress = progress
        self.window.update_video_status(vid, item.status, item.progress if progress is not None else progress)
        return item

    def _update_video_status(self, vid, status, progress=None):
        self._apply_video_state(vid, status=status, progress=progress)

    def _update_video_progress(self, vid, progress):
        self._apply_video_state(vid, progress=progress)

    def _on_download_finished(self, vid):
        item = self._apply_video_state(vid, status="✅ 完成", progress=100)
        if not item:
            return
        self.window.append_log(f"✅ 下载完成: {item.title}")
        debug_logger.log(
            component="ApplicationController",
            action="download_finished",
            message="下载任务完成",
            status_code="APP_DL_FINISH",
            context=self._item_context(item),
            details=self._item_details(item),
            trace_id=self._item_trace_id(item),
        )

    def _on_download_error(self, vid, error):
        item = self._apply_video_state(vid, status="❌ 失败")
        if not item:
            return
        self.window.append_log(f"❌ 下载失败 [{item.title}]: {error}")
        debug_logger.log(
            component="ApplicationController",
            action="download_error",
            level="ERROR",
            message="下载任务失败",
            status_code="APP_DL_ERROR",
            context=self._item_context(item),
            details={**self._item_details(item), "error": error},
            trace_id=self._item_trace_id(item),
        )

    def _create_spider(self, source_id: str, keyword: str, config: dict):
        """根据插件定义创建 spider，控制器不感知各平台具体类。"""
        plugin = registry.get_plugin(source_id)
        if not plugin:
            self.window.append_log("❌ 未知的爬虫源")
            return None, None
        spider_cls = plugin.get_spider_class()
        return plugin, spider_cls(keyword=keyword, config=config)

    def _bind_spider_signals(self, spider) -> None:
        """spider 生命周期信号统一在这里接入。"""
        spider.sig_log.connect(self.window.append_log)
        spider.sig_item_found.connect(self._on_spider_item_found)
        spider.sig_select_tasks.connect(self._on_spider_select_tasks)
        spider.sig_finished.connect(self._on_spider_finished)

    def _clear_local_items(self) -> None:
        self.window.clear_video_rows()
        self.videos.clear()

    def _append_scanned_items(self, result) -> None:
        for item in result.items:
            self.videos[item.id] = item
            self.window.add_video_row(item)

    def scan_local_dir(self):
        directory = self.window.current_save_dir
        self.window.append_log(f"📂 正在扫描目录: {directory}")
        debug_logger.log(
            component="ApplicationController",
            action="scan_local_dir",
            message="开始扫描本地媒体目录",
            status_code="APP_SCAN_START",
            details={"directory": directory},
        )

        self._clear_local_items()
        try:
            result = self.file_service.scan_directory(
                directory,
                max_scan_count=cfg.get("download", "local_scan_limit", 1000),
            )
            if result.truncated:
                self.window.append_log(
                    f"⚠️ 文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个以防卡顿。"
                )
            self._append_scanned_items(result)

            if result.total_count > 0:
                self.window.append_log(
                    f"✅ 已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
                )
                debug_logger.log(
                    component="ApplicationController",
                    action="scan_local_dir_finished",
                    message="本地媒体目录扫描完成",
                    status_code="APP_SCAN_OK",
                    details={
                        "directory": directory,
                        "count": result.total_count,
                        "video_count": result.video_count,
                        "image_count": result.image_count,
                    },
                )
            else:
                self.window.append_log("ℹ️ 该目录下没有找到视频或图片")
        except MediaScanError as exc:
            self.window.append_log(f"❌ 扫描目录出错: {exc}")
            debug_logger.log_exception("ApplicationController", "scan_local_dir", exc, context={"directory": directory})

    def on_dir_changed(self):
        self.window.append_log(f"📂 目录已变更: {self.window.current_save_dir}")
        debug_logger.log(
            component="ApplicationController",
            action="change_save_dir",
            message="保存目录已变更",
            status_code="APP_DIR_CHANGED",
            details={"save_dir": self.window.current_save_dir},
        )
        self.scan_local_dir()

    def on_rename_video(self, item):
        if item.column() != 0:
            return
        vid = item.data(Qt.ItemDataRole.UserRole)
        if not vid or vid not in self.videos:
            return

        video = self.videos[vid]
        new_title = item.text().strip()
        if new_title == video.title or not os.path.exists(video.local_path):
            item.setText(video.title)
            return

        try:
            old_path, new_path = self.file_service.rename_media(video, new_title, self.window.current_save_dir)
            video.title = new_title
            video.local_path = new_path
            item.setToolTip(new_title)
            self.window.append_log(f"📝 重命名: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
        except FileOperationError as exc:
            self.window.append_log(f"❌ 重命名失败: {exc}")
            item.setText(video.title)

    def on_delete_video(self, row_idx, vid):
        if vid not in self.videos:
            self.window.remove_video_row(row_idx)
            return

        video = self.videos[vid]
        cancel_result = self.dl_manager.cancel_task(vid)
        if self.current_playing_id == vid:
            self.window.stop_media_playback()
            self.current_playing_id = None
        try:
            deleted = self.file_service.delete_media(video)
            if deleted:
                self.window.append_log(f"🗑️ 已删除: {os.path.basename(video.local_path)}")
            else:
                self.window.append_log(f"ℹ️ 文件不存在，仅从列表移除: {video.title}")
        except FileOperationError as exc:
            self.window.append_log(f"❌ 删除文件失败: {exc}")
            return

        if cancel_result == "queued":
            self.window.append_log(f"🛑 已取消队列任务: {video.title}")
        elif cancel_result == "running":
            self.window.append_log(f"🛑 已请求停止下载: {video.title}")

        del self.videos[vid]
        self.window.remove_video_row(row_idx)
        self.window.refresh_table_bindings()

    def on_start_crawl(self, keyword, source_id, config):
        # 爬虫线程未退出前拒绝重复启动，避免 current_spider 被覆盖后出现状态串线。
        if self._has_active_spider():
            self.window.append_log("⚠️ 当前已有任务在运行，请先停止或等待结束")
            return
        plugin, spider = self._create_spider(source_id, keyword, config)
        if not plugin or not spider:
            return
        self.window.append_log(f"🟢 启动任务 | 模式: {plugin.name}")
        self._log_crawl_start(plugin.name, keyword, source_id, config)

        self.window.set_crawl_running_state(True)
        self.current_spider = spider
        self._bind_spider_signals(self.current_spider)
        self.current_spider.start()

    def _on_spider_item_found(self, item):
        item.status = "⏳ 等待中"
        item.progress = 0
        self.videos[item.id] = item
        self.window.add_video_row(item)
        debug_logger.log(
            component="ApplicationController",
            action="item_found",
            message="爬虫发现可下载资源",
            status_code="APP_ITEM_FOUND",
            context=self._item_context(item),
            details=self._item_details(item),
            trace_id=self._item_trace_id(item),
        )
        self.dl_manager.add_task(item, self.window.current_save_dir)

    def _on_spider_select_tasks(self, items):
        selected = self.window.show_selection_dialog(items)
        if self.current_spider:
            self.current_spider.resume_from_ui(selected)

    def _on_spider_finished(self):
        self.window.append_log("✅ 爬虫任务结束")
        debug_logger.log(
            component="ApplicationController",
            action="crawl_finished",
            message="爬虫任务结束",
            status_code="APP_CRAWL_FINISH",
        )
        self.window.set_crawl_running_state(False)
        self.current_spider = None

    def on_stop_crawl(self):
        if self.current_spider:
            self.current_spider.stop()
            self.window.append_log("🛑 正在停止任务...")
            debug_logger.log(
                component="ApplicationController",
                action="stop_crawl",
                level="WARN",
                message="用户请求停止爬虫任务",
                status_code="APP_CRAWL_STOP",
            )

    def open_latest_log(self):
        self._run_debug_action("📄 已打开最新调试日志", "打开最新日志", self.debug_service.open_latest_log)

    def open_latest_error_summary(self):
        self._run_debug_action("🚨 已打开最近错误摘要", "打开错误摘要", self.debug_service.open_latest_error_summary)

    def copy_trace_id_for_video(self, video_id: str):
        item = self.videos.get(video_id)
        trace_id = self._item_trace_id(item)
        self._run_debug_action(
            f"📋 已复制 trace_id: {trace_id}",
            "复制 trace_id",
            lambda: self.debug_service.copy_trace_id(self.app.clipboard(), trace_id),
        )

    def shutdown(self):
        debug_logger.log(
            component="ApplicationController",
            action="shutdown",
            level="WARN",
            message="应用开始退出清理",
            status_code="APP_SHUTDOWN",
        )
        self.window.cleanup_media()
        if self.current_spider and self.current_spider.isRunning():
            self.current_spider.stop()
            self.current_spider.wait(2000)
        self.dl_manager.stop_all()

    def play_video(self, vid):
        video = self.videos.get(vid)
        if not video or not os.path.exists(video.local_path):
            self.window.append_log("❌ 文件不存在或已被删除")
            return
        self.current_playing_id = vid
        self.window.append_log(f"▶️ 播放: {video.title}")

        if self._is_image_file(video.local_path):
            self.window.show_image(video.local_path)
        else:
            self.window.play_video(video.local_path)

    def _is_image_file(self, file_path: str) -> bool:
        return os.path.splitext(file_path)[1].lower() in self.IMAGE_EXTENSIONS

    def run(self):
        sys.exit(self.app.exec())
