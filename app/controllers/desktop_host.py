from __future__ import annotations

from app.models import VideoItem

class DesktopHostAdapter:
    """Thin adapter that isolates direct MainWindow side effects from controllers."""

    def __init__(self, window) -> None:
        self.window = window

    @property
    def current_save_dir(self) -> str:
        return self.window.current_save_dir

    def set_current_save_dir(self, save_dir: str, *, persist: bool = False) -> None:
        self.window.set_current_save_dir(save_dir, persist=persist)

    def append_log(self, message: str) -> None:
        self.window.append_log(message)

    def set_crawl_running_state(self, is_running: bool) -> None:
        self.window.set_crawl_running_state(is_running)

    def notify_crawl_already_running(self) -> None:
        self.append_log("⚠️ 当前已有任务在运行，请先停止或等待结束")

    def notify_unknown_source(self) -> None:
        self.append_log("❌ 未知的爬虫源")

    def notify_spider_create_failed(self, error: Exception) -> None:
        self.append_log(f"❌ 创建爬虫失败: {error}")

    def begin_crawl(self, plugin_name: str) -> None:
        self.append_log(f"🟢 启动任务 | 模式: {plugin_name}")
        self.set_crawl_running_state(True)

    def fail_crawl_start(self, error: Exception) -> None:
        self.append_log(f"❌ 启动爬虫失败: {error}")
        self.set_crawl_running_state(False)

    def finish_crawl(self) -> None:
        self.append_log("✅ 爬虫任务结束")
        self.set_crawl_running_state(False)

    def notify_crawl_stop_requested(self) -> None:
        self.append_log("🛑 正在停止任务...")

    def announce_scan_start(self, directory: str) -> None:
        self.append_log(f"📂 正在扫描目录: {directory}")

    def report_scan_error(self, error: Exception) -> None:
        self.append_log(f"❌ 扫描目录出错: {error}")

    def announce_directory_changed(self, directory: str) -> None:
        self.append_log(f"📂 目录已变更: {directory}")

    def report_rename_error(self, error: str) -> None:
        self.append_log(f"❌ 重命名失败: {error}")

    def report_delete_error(self, error: str) -> None:
        self.append_log(f"❌ 删除文件失败: {error}")

    def report_missing_media(self) -> None:
        self.append_log("❌ 文件不存在或已被删除")

    def announce_playback(self, title: str) -> None:
        self.append_log(f"▶️ 播放: {title}")

    def add_video_row(self, item: VideoItem) -> None:
        self.window.add_video_row(item)

    def update_video_status(self, video_id: str, status: str, progress: int | None = None) -> None:
        self.window.update_video_status(video_id, status, progress)

    def clear_video_rows(self) -> None:
        self.window.clear_video_rows()

    def remove_video_row(self, row_idx: int) -> None:
        self.window.remove_video_row(row_idx)

    def refresh_table_bindings(self) -> None:
        self.window.refresh_table_bindings()

    def refresh_frontend_state(self, *, force: bool = False, topics: set[str] | None = None) -> None:
        self.window.refresh_frontend_state(force=force, topics=topics)

    def reorder_video_row(self, item: VideoItem) -> int:
        return self.window.reorder_video_row(item)

    def show_selection_dialog(self, items):
        return self.window.show_selection_dialog(items)

    def release_media_playback(self) -> None:
        self.window.release_media_playback()

    def cleanup_media(self) -> None:
        self.window.cleanup_media()

    def show_image(self, file_path: str) -> None:
        self.window.show_image(file_path)

    def play_video(self, file_path: str) -> None:
        self.window.play_video(file_path)

    def get_selected_video_id(self) -> str | None:
        return self.window.get_selected_video_id()

    def get_adjacent_video_id(self, current_video_id: str | None, direction: int, *, wrap: bool = True) -> str | None:
        return self.window.get_adjacent_video_id(current_video_id, direction, wrap=wrap)

    def select_video_by_id(self, video_id: str) -> bool:
        return self.window.select_video_by_id(video_id)
