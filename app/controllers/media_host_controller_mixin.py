from __future__ import annotations

import os

from PyQt6.QtCore import Qt

from app.debug_logger import debug_logger
from app.exceptions import MediaScanError


class MediaHostControllerMixin:
    """Host-backed media library and playback orchestration."""

    def _clear_local_items(self) -> None:
        """Clear cached local media and host rows before a rescan."""
        self._host().clear_video_rows()
        self.videos.clear()

    def _append_scanned_items(self, result) -> None:
        """Populate scanned media rows through the host adapter."""
        for item in self._cache_scanned_items(result):
            self._host().add_video_row(item)

    def scan_local_dir(self):
        """Scan the current save directory and restore local media into the host."""
        host = self._host()
        directory = host.current_save_dir
        host.announce_scan_start(directory)
        debug_logger.log(
            component="ApplicationController",
            action="scan_local_dir",
            message="开始扫描本地媒体目录",
            status_code="APP_SCAN_START",
            details={"directory": directory},
        )

        self._clear_local_items()
        try:
            result = self._scan_media_directory(directory)
            self._append_scanned_items(result)
            for message in self._build_scan_messages(result):
                host.append_log(message)
            if result.total_count > 0:
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
        except MediaScanError as exc:
            host.report_scan_error(exc)
            debug_logger.log_exception("ApplicationController", "scan_local_dir", exc, context={"directory": directory})

    def on_dir_changed(self):
        """React to directory changes and refresh the host media list."""
        host = self._host()
        host.announce_directory_changed(host.current_save_dir)
        debug_logger.log(
            component="ApplicationController",
            action="change_save_dir",
            message="保存目录已变更",
            status_code="APP_DIR_CHANGED",
            details={"save_dir": host.current_save_dir},
        )
        self.scan_local_dir()

    def on_rename_video(self, item):
        """Rename a media item and keep host state in sync."""
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
        if self.current_playing_id == vid:
            self._host().release_media_playback()
            self.current_playing_id = None

        outcome = self._rename_video_sync(vid, new_title, self._host().current_save_dir)
        if outcome.status == "ok":
            item.setToolTip(new_title)
            self._host().reorder_video_row(video)
            message = self._rename_outcome_message(outcome)
            if message:
                self._host().append_log(message)
        else:
            self._host().report_rename_error(outcome.error or "未知错误")
            item.setText(video.title)

    def on_delete_video(self, row_idx, vid):
        """Delete a media item and reconcile host/download queue state."""
        if vid not in self.videos:
            self._host().remove_video_row(row_idx)
            return

        if self.current_playing_id == vid:
            self._host().release_media_playback()
            self.current_playing_id = None
        outcome = self._delete_video_sync(vid)
        if outcome.status == "error":
            self._host().report_delete_error(outcome.error or "未知错误")
            return
        for message in self._delete_outcome_messages(outcome):
            self._host().append_log(message)
        self._host().remove_video_row(row_idx)
        self._host().refresh_table_bindings()

    def play_video(self, vid):
        """Preview a local media item through the host adapter."""
        video = self.videos.get(vid)
        if not video or not os.path.exists(video.local_path):
            self._host().report_missing_media()
            return
        self.current_playing_id = vid
        self._host().announce_playback(video.title)

        if self._is_image_file(video.local_path):
            self._host().show_image(video.local_path)
        else:
            self._host().play_video(video.local_path)

    def switch_preview(self, direction: int) -> None:
        """按当前表格顺序切换到上一项或下一项，支持首尾环绕。"""
        self._switch_preview(direction, wrap=True)

    def autoplay_next_preview(self) -> None:
        """当前视频播放完成后自动切到下一项，不在末尾环绕。"""
        self._switch_preview(1, wrap=False, auto_advance=True)

    def _switch_preview(self, direction: int, *, wrap: bool, auto_advance: bool = False) -> None:
        host = self._host()
        anchor_id = self.current_playing_id or host.get_selected_video_id()
        next_video_id = host.get_adjacent_video_id(anchor_id, direction, wrap=wrap)
        if not next_video_id:
            if auto_advance:
                host.append_log("ℹ️ 已播放到最后一项")
            elif not self.videos:
                host.append_log("⚠️ 队列为空，没有可切换的资源")
            return
        host.select_video_by_id(next_video_id)
        self.play_video(next_video_id)

    def _is_image_file(self, file_path: str) -> bool:
        """Return whether the given local path should be previewed as an image."""
        return os.path.splitext(file_path)[1].lower() in self.IMAGE_EXTENSIONS
