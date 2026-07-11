import os
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.services.playback_position_service import PlaybackPositionService
from app.ui.components.media_preview_panel import MediaPreviewPanel

class MediaPreviewPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in list(self.app.allWidgets()):
            if isinstance(widget, MediaPreviewPanel):
                widget.cleanup()
                widget.deleteLater()
        for widget in list(self.app.topLevelWidgets()):
            widget.deleteLater()
        self.app.processEvents()

    def _wait_until(self, predicate, *, timeout_ms: int = 1000, message: str = "condition was not met") -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.app.processEvents()
        self.assertTrue(predicate(), message)

    def test_play_button_uses_icon(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)

        self.assertEqual(panel.btn_play.text(), "")
        self.assertFalse(panel.btn_play.icon().isNull())

    def test_preview_navigation_buttons_emit_direction(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        emitted: list[int] = []
        panel.sig_switch_preview.connect(emitted.append)

        panel.btn_prev.click()
        panel.btn_next.click()

        self.assertEqual(emitted, [-1, 1])

    def test_video_end_emits_auto_next_once(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        emitted: list[str] = []
        panel.sig_auto_next_preview.connect(lambda: emitted.append("next"))
        panel._active_video_source = panel._normalize_path("movie.mp4")

        panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
        panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        self.assertEqual(emitted, ["next"])

    def test_image_preview_does_not_emit_auto_next_on_stale_media_end(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        emitted: list[str] = []
        panel.sig_auto_next_preview.connect(lambda: emitted.append("next"))

        panel.show_image("picture.jpg")
        panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        self.assertEqual(emitted, [])

    def test_format_time_formats_minutes_and_seconds(self):
        self.assertEqual(MediaPreviewPanel.format_time(65_000), "01:05")
        self.assertEqual(MediaPreviewPanel.format_time(0), "00:00")
        self.assertEqual(MediaPreviewPanel.format_time(3_599_000), "59:59")

    def test_duration_changed_updates_slider_range(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)

        panel.player.durationChanged.emit(65000)

        self.assertEqual(panel.slider.maximum(), 65000)

    def test_duration_changed_emits_completed_metadata_backfill(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        emitted: list[tuple[str, dict]] = []
        panel.sig_media_metadata_detected.connect(lambda path, metadata: emitted.append((path, metadata)))
        panel._active_source_path = r"D:\media\done.mp4"

        panel.on_player_duration_changed(208000)

        self.assertEqual(emitted, [(r"D:\media\done.mp4", {"duration": "00:03:28"})])

    def test_format_clock_time_uses_hours_minutes_seconds(self):
        self.assertEqual(MediaPreviewPanel.format_clock_time(208000), "00:03:28")
        self.assertEqual(MediaPreviewPanel.format_clock_time(3_725_000), "01:02:05")

    def test_position_changed_updates_time_label(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        panel.player.duration = lambda: 65000
        panel.player.position = lambda: 30000

        panel.player.positionChanged.emit(30000)

        self.assertIn("00:30", panel.lbl_time.text())
        self.assertIn("01:05", panel.lbl_time.text())

    def test_play_video_does_not_repair_before_seek_problem_is_observed(self):
        class FakeRepairService:
            repair_called = False

            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def cached_playable_path(path):
                return str(path)

            @classmethod
            def repair_for_playback(cls, *_args, **_kwargs):
                cls.repair_called = True
                raise AssertionError("repair should not start until seek failure is observed")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        with TemporaryDirectory() as tmp:
            source = str(Path(tmp) / "normal.mkv")
            panel.play_video(source)

        self.assertEqual(
            os.path.normcase(os.path.normpath(panel.player.source().toLocalFile())),
            os.path.normcase(os.path.normpath(source)),
        )
        self.assertTrue(panel.repair_panel.isHidden())
        self.assertFalse(FakeRepairService.repair_called)

    def test_seek_problem_repair_switches_current_playback_to_cache(self):
        class FakeRepairService:
            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def cached_playable_path(path):
                return str(path)

            @staticmethod
            def repair_for_playback(path, *, progress_callback=None, cancel_check=None):
                if progress_callback:
                    progress_callback(35, "repairing 35%")
                return SimpleNamespace(playable_path=f"{path}.cache.mkv", repaired=True, message="done")

            @staticmethod
            def write_repair_to_source(path, repaired_path, *, progress_callback=None, cancel_check=None):
                return SimpleNamespace(committed=True, message="done")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        with TemporaryDirectory() as tmp, patch.object(
            panel,
            "_start_worker_thread",
            side_effect=lambda *, name, target, args: (target(*args), True)[1],
        ):
            source = str(Path(tmp) / "broken.mkv")
            panel.play_video(source)
            panel.player.duration = lambda: 0
            panel._start_repair_if_seek_unavailable(force=True)
            self.app.processEvents()

        self.assertEqual(
            os.path.normcase(os.path.normpath(panel.player.source().toLocalFile())),
            os.path.normcase(os.path.normpath(f"{source}.cache.mkv")),
        )
        self.assertFalse(panel.repair_panel.isHidden())
        self.assertEqual(panel.repair_progress.value(), 100)

    def test_cached_media_is_used_directly_without_starting_repair(self):
        class FakeRepairService:
            repair_called = False

            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def cached_playable_path(path):
                return f"{path}.cache.mkv"

            @classmethod
            def repair_for_playback(cls, *_args, **_kwargs):
                cls.repair_called = True
                raise AssertionError("cached playback should not start repair")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source = "broken.mkv"

        panel.play_video(source)

        self._wait_until(
            lambda: panel.player.source().toLocalFile() == f"{source}.cache.mkv",
            timeout_ms=1500,
            message="cached media was not applied after background lookup",
        )
        self.assertFalse(panel.repair_panel.isHidden())
        self.assertIn("cache", panel.player.source().toLocalFile())
        self.assertFalse(FakeRepairService.repair_called)

    def test_cached_playable_path_lookup_runs_off_ui_thread(self):
        class FakeRepairService:
            thread_ids: list[int] = []

            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mkv")

            @classmethod
            def cached_playable_path(cls, path):
                cls.thread_ids.append(threading.get_ident())
                return str(path)

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())

        panel.play_video("normal.mkv")

        self._wait_until(lambda: bool(FakeRepairService.thread_ids), message="cache lookup did not run")
        self.assertNotEqual(FakeRepairService.thread_ids[0], threading.get_ident())

    def test_unknown_duration_non_mkv_can_repair_and_switch_to_cache(self):
        class FakeRepairService:
            @staticmethod
            def is_mkv_path(_path):
                return False

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mp4")

            @staticmethod
            def cached_playable_path(path):
                return str(path)

            @staticmethod
            def repair_for_playback(path, *, progress_callback=None, cancel_check=None):
                if progress_callback:
                    progress_callback(64, "repairing 64%")
                return SimpleNamespace(playable_path=f"{path}.cache.mp4", repaired=True, message="done")

            @staticmethod
            def write_repair_to_source(path, repaired_path, *, progress_callback=None, cancel_check=None):
                return SimpleNamespace(committed=True, message="done")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source = "broken.mp4"
        panel.play_video(source)
        panel.player.duration = lambda: 0

        with patch.object(
            panel,
            "_start_worker_thread",
            side_effect=lambda *, name, target, args: (target(*args), True)[1],
        ):
            panel._start_repair_if_seek_unavailable(force=True)
            self.app.processEvents()

        self.assertEqual(panel.player.source().toLocalFile(), f"{source}.cache.mp4")
        self.assertFalse(panel.repair_panel.isHidden())
        self.assertEqual(panel.repair_progress.value(), 100)

    def test_loaded_seekable_media_does_not_schedule_repair(self):
        class FakeRepairService:
            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def cached_playable_path(path):
                return str(path)

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        panel.play_video("normal.mkv")
        panel.player.duration = lambda: 120000
        panel.slider.setRange(0, 120000)

        panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)

        self.assertFalse(panel._duration_probe_timer.isActive())

    def test_commit_success_schedules_repair_panel_hide(self):
        class FakeRepairService:
            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def cached_playable_path(path):
                return str(path)

            @staticmethod
            def write_repair_to_source(path, repaired_path, *, progress_callback=None, cancel_check=None):
                if progress_callback:
                    progress_callback(100, "committed")
                return SimpleNamespace(committed=True, message="done")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source_key = panel._normalize_path("broken.mkv")
        panel._active_video_source = source_key
        panel._repair_candidate_path = "broken.mkv"

        with patch.object(
            panel,
            "_start_worker_thread",
            side_effect=lambda *, name, target, args: (target(*args), True)[1],
        ):
            panel._start_commit_to_source(source_key, "broken.mkv", "broken.cache.mkv")
            self.app.processEvents()

        self.assertEqual(panel.repair_progress.value(), 100)
        self.assertTrue(panel._repair_hide_timer.isActive())

    def test_repair_worker_does_not_cancel_when_video_is_not_active(self):
        observed_cancel_checks: list[bool] = []

        class FakeRepairService:
            @staticmethod
            def repair_for_playback(path, *, progress_callback=None, cancel_check=None):
                observed_cancel_checks.append(bool(cancel_check and cancel_check()))
                return SimpleNamespace(playable_path=f"{path}.cache.mkv", repaired=False, message="done")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source_key = panel._normalize_path("broken.mkv")
        panel._active_video_source = "other"

        panel._repair_video_worker("broken.mkv", source_key)

        self.assertEqual(observed_cancel_checks, [False])

    def test_cleanup_requests_repair_and_commit_cancellation(self):
        cancel_checks = []

        class FakeRepairService:
            @staticmethod
            def repair_for_playback(path, *, progress_callback=None, cancel_check=None):
                cancel_checks.append(cancel_check)
                return SimpleNamespace(playable_path=f"{path}.cache.mkv", repaired=False, message="done")

            @staticmethod
            def write_repair_to_source(path, repaired_path, *, progress_callback=None, cancel_check=None):
                cancel_checks.append(cancel_check)
                return SimpleNamespace(committed=False, message="done")

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source_key = panel._normalize_path("broken.mkv")

        panel._repair_video_worker("broken.mkv", source_key)
        panel._commit_repair_worker(source_key, "broken.mkv", "broken.cache.mkv")

        self.assertEqual([check() for check in cancel_checks], [False, False])

        panel.cleanup()

        self.assertEqual([check() for check in cancel_checks], [True, True])
        self.assertEqual(panel._repair_states, {})

    def test_switching_back_restores_running_repair_progress(self):
        class FakeRepairService:
            @staticmethod
            def is_mkv_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def is_repairable_path(path):
                return str(path).lower().endswith(".mkv")

            @staticmethod
            def cached_playable_path(path):
                return str(path)

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source = "broken.mkv"
        source_key = panel._normalize_path(source)
        panel._set_repair_state(source_key, source, "repairing", 42, "repairing 42%")
        panel._active_video_source = None
        panel._hide_repair_status()

        panel.play_video(source)

        self.assertFalse(panel.repair_panel.isHidden())
        self.assertEqual(panel.repair_progress.value(), 42)
        self.assertEqual(panel.lbl_repair.text(), "repairing 42%")

    def test_commit_success_defers_cache_delete_until_player_releases_cache(self):
        class FakeRepairService:
            deleted: list[str] = []

            @staticmethod
            def cached_playable_path(path):
                return str(path)

            @classmethod
            def discard_cache_file(cls, path):
                cls.deleted.append(path)
                return True

        host = QWidget()
        panel = MediaPreviewPanel(host, repair_service=FakeRepairService())
        source = "broken.mkv"
        cache = "broken.cache.mkv"
        source_key = panel._normalize_path(source)
        panel._active_video_source = source_key
        panel.player.setSource(QUrl.fromLocalFile(cache))

        panel._on_repair_commit_finished(source_key, cache, True, "done")

        self.assertIn(cache, panel._pending_cache_cleanup)
        self.assertEqual(FakeRepairService.deleted, [])

        panel.player.setSource(QUrl())
        panel._cleanup_pending_cache_files()

        self.assertEqual(FakeRepairService.deleted, [cache])
        self.assertNotIn(cache, panel._pending_cache_cleanup)

    def test_fullscreen_button_uses_media_window_not_main_window_signal(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        panel = MediaPreviewPanel(host)
        layout.addWidget(panel)
        emitted: list[str] = []
        panel.sig_toggle_fullscreen.connect(lambda: emitted.append("main"))

        panel.btn_fullscreen.click()
        self.app.processEvents()

        self.assertEqual(emitted, [])
        self.assertIsNotNone(panel._fullscreen_window)
        self.assertEqual(panel.btn_fullscreen.text(), "[ 退出 ]")

        panel.exit_media_fullscreen()
        self.app.processEvents()

        self.assertIs(panel.parentWidget(), host)
        self.assertEqual(panel.btn_fullscreen.text(), "[ 全屏 ]")

    def test_release_media_exits_media_fullscreen_window(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        panel = MediaPreviewPanel(host)
        layout.addWidget(panel)

        panel.enter_media_fullscreen()
        self.app.processEvents()
        fullscreen_window = panel._fullscreen_window
        self.assertIsNotNone(fullscreen_window)

        panel.release_media()
        self.app.processEvents()

        self.assertIsNone(panel._fullscreen_window)
        self.assertIs(panel.parentWidget(), host)
        self.assertEqual(panel.btn_fullscreen.text(), "[ 全屏 ]")
        try:
            self.assertFalse(fullscreen_window.isVisible())
        except RuntimeError:
            pass

    def test_image_preview_uses_same_media_fullscreen_window(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        panel = MediaPreviewPanel(host)
        layout.addWidget(panel)
        with TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            image.write_bytes(b"not-a-real-png")
            panel.show_image(str(image))

            panel.enter_media_fullscreen()
            self.app.processEvents()

            self.assertIsNotNone(panel._fullscreen_window)
            self.assertFalse(panel.img_lbl.isHidden())

            panel.exit_media_fullscreen()
            self.app.processEvents()

        self.assertIs(panel.parentWidget(), host)

    def test_playback_settings_control_autoplay_next_signal(self):
        panel = MediaPreviewPanel(QWidget())
        emitted: list[str] = []
        panel.sig_auto_next_preview.connect(lambda: emitted.append("next"))
        panel._active_video_source = "video-key"

        panel.apply_playback_settings({"autoplay_next": False})
        panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        self.assertEqual(emitted, [])

        panel._end_emitted_for_source = False
        panel._active_video_source = "video-key"
        panel.apply_playback_settings({"autoplay_next": True})
        panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        self.assertEqual(emitted, ["next"])

    def test_playback_settings_remember_and_restore_position(self):
        panel = MediaPreviewPanel(QWidget())
        panel._active_video_source = "video-key"
        panel.player.duration = lambda: 100_000

        panel.on_player_position_changed(30_000)

        self.assertEqual(panel._saved_positions["video-key"], 30_000)

        panel.player.setPosition = Mock()
        panel._restore_playback_position("video-key", 30_000)
        panel.player.setPosition.assert_called_once_with(30_000)

        panel.apply_playback_settings({"remember_position": False})
        self.assertEqual(panel._saved_positions, {})

    def test_playback_position_service_restores_across_panel_instances(self):
        with TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "demo.mp4"
            media.write_bytes(b"video")
            service = PlaybackPositionService(Path(temp_dir) / "positions.json")
            service.save(media, 30_000, duration_ms=100_000)

            panel = MediaPreviewPanel(QWidget(), playback_position_service=service)
            source_key = panel._normalize_path(str(media))
            panel._active_video_source = source_key
            panel.player.setPosition = Mock()

            panel._restore_playback_position_later(source_key)
            for _ in range(80):
                if panel.player.setPosition.called:
                    break
                QTest.qWait(25)
                self.app.processEvents()

            panel.player.setPosition.assert_called_once_with(30_000)
            panel.cleanup()

    def test_playback_position_is_deleted_when_media_ends_or_memory_disabled(self):
        with TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "demo.mp4"
            media.write_bytes(b"video")
            service = PlaybackPositionService(Path(temp_dir) / "positions.json")
            panel = MediaPreviewPanel(QWidget(), playback_position_service=service)
            source_key = panel._normalize_path(str(media))

            service.save(media, 20_000, duration_ms=100_000)
            panel._active_video_source = source_key
            panel.on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
            self._wait_until(lambda: service.get(media) == 0, message="playback position was not deleted")

            service.save(media, 25_000, duration_ms=100_000)
            panel.apply_playback_settings({"remember_position": False})
            self._wait_until(lambda: service.snapshot() == {}, message="playback positions were not cleared")
            panel.cleanup()

    def test_playback_position_restore_runs_off_ui_thread(self):
        class RecordingPlaybackPositionService:
            def __init__(self) -> None:
                self.thread_ids: list[int] = []

            def get(self, _path):
                self.thread_ids.append(threading.get_ident())
                return 30_000

            def save(self, *_args, **_kwargs):
                raise AssertionError("save should not be called")

            def delete(self, *_args, **_kwargs):
                raise AssertionError("delete should not be called")

            def clear(self):
                raise AssertionError("clear should not be called")

        service = RecordingPlaybackPositionService()
        panel = MediaPreviewPanel(QWidget(), playback_position_service=service)
        source_key = "video-key"
        panel._active_video_source = source_key
        panel.player.setPosition = Mock()

        panel._restore_playback_position_later(source_key)

        self._wait_until(lambda: bool(service.thread_ids), message="restore did not query the service")
        self.assertNotEqual(service.thread_ids[0], threading.get_ident())
        self._wait_until(
            lambda: panel.player.setPosition.call_count == 1,
            timeout_ms=1500,
            message="restore did not seek after the background result",
        )
        panel.player.setPosition.assert_called_once_with(30_000)
        panel.cleanup()

    def test_image_auto_advance_respects_manual_switch_setting(self):
        panel = MediaPreviewPanel(QWidget())
        emitted: list[int] = []
        panel.sig_switch_preview.connect(lambda direction: emitted.append(direction))
        panel.current_image_path = "image.webp"

        panel.apply_playback_settings({"manual_image_switch": True})
        panel._on_image_auto_advance_timeout()
        self.assertEqual(emitted, [])

        panel.apply_playback_settings({"manual_image_switch": False, "image_auto_advance_interval_seconds": 3})
        self.assertEqual(panel._image_auto_advance_timer.interval(), 3000)
        panel._on_image_auto_advance_timeout()
        self.assertEqual(emitted, [1])

        panel.apply_playback_settings({"manual_image_switch": False, "image_auto_advance_interval_seconds": 99})
        self.assertEqual(panel._image_auto_advance_timer.interval(), 5000)

if __name__ == "__main__":
    unittest.main()
