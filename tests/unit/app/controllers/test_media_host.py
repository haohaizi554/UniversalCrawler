import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.controllers.media_host_controller_mixin import MediaHostControllerMixin
from app.exceptions import MediaScanError
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.file_service import ScanResult

class _DummyMediaHostController(MediaHostControllerMixin):
    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    def __init__(self):
        self.host = Mock()
        self.videos = {}
        self.current_playing_id = None

    def _host(self):
        return self.host

    def _cache_scanned_items(self, result):
        for item in result.items:
            self.videos[item.id] = item
        return list(result.items)

    @staticmethod
    def _build_scan_messages(result):
        return [f"loaded {result.total_count}"]

    def _scan_media_directory(self, directory):
        return self._scan_result

    def _rename_video_sync(self, vid, title, save_dir):
        return self._rename_outcome

    def _rename_outcome_message(self, outcome):
        return f"renamed:{outcome.new_title}" if getattr(outcome, "new_title", None) else ""

    def _delete_video_sync(self, vid):
        return self._delete_outcome

    @staticmethod
    def _delete_outcome_messages(outcome):
        return getattr(outcome, "messages", [])

class MediaHostControllerMixinTests(unittest.TestCase):
    def test_current_playing_id_prefers_app_state_over_stale_controller_mirror(self):
        controller = _DummyMediaHostController()
        controller.current_playing_id = "stale"
        controller.app_state = Mock()
        controller.app_state.current_playing_id = "fresh"
        controller.app_state.get_current_playing_id.side_effect = lambda: controller.app_state.current_playing_id

        def set_current_playing_id(video_id):
            controller.app_state.current_playing_id = video_id

        controller.app_state.set_current_playing_id.side_effect = set_current_playing_id

        self.assertEqual(controller._get_current_playing_id(), "fresh")
        self.assertEqual(controller.current_playing_id, "fresh")

        controller._set_current_playing_id("next")

        controller.app_state.set_current_playing_id.assert_called_once_with("next")
        self.assertEqual(controller.current_playing_id, "next")

    def test_scan_local_dir_announces_scan_and_populates_rows(self):
        controller = _DummyMediaHostController()
        controller.host.current_save_dir = "downloads"
        item = VideoItem(url="", title="demo", source="local")
        controller._scan_result = ScanResult(items=[item], total_count=1, video_count=1, image_count=0)

        with patch("app.controllers.media_host_controller_mixin.debug_logger", Mock()):
            controller.scan_local_dir()

        controller.host.announce_scan_start.assert_called_once_with("downloads")
        controller.host.clear_video_rows.assert_called_once()
        controller.host.add_video_row.assert_called_once_with(item)
        controller.host.append_log.assert_called_once_with("loaded 1")

    def test_scan_local_dir_reports_media_scan_error(self):
        controller = _DummyMediaHostController()
        controller.host.current_save_dir = "downloads"

        def _raise(_directory):
            raise MediaScanError("权限不足")

        controller._scan_media_directory = _raise

        with patch("app.controllers.media_host_controller_mixin.debug_logger", Mock()):
            controller.scan_local_dir()

        controller.host.report_scan_error.assert_called_once()

    def test_background_scan_requires_controller_qt_app_identity(self):
        controller = _DummyMediaHostController()
        controller.app = Mock()
        fake_app = Mock()

        with patch("app.controllers.media_host_controller_mixin.QCoreApplication.instance", return_value=fake_app):
            self.assertFalse(controller._should_scan_local_dir_in_background())

    def test_background_scan_runs_only_on_matching_qt_main_thread(self):
        controller = _DummyMediaHostController()
        fake_thread = object()
        fake_app = Mock()
        fake_app.thread.return_value = fake_thread
        controller.app = fake_app

        with (
            patch("app.controllers.media_host_controller_mixin.QCoreApplication.instance", return_value=fake_app),
            patch("app.controllers.media_host_controller_mixin.QThread.currentThread", return_value=fake_thread),
        ):
            self.assertTrue(controller._should_scan_local_dir_in_background())

    def test_on_dir_changed_announces_and_rescans(self):
        controller = _DummyMediaHostController()
        controller.host.current_save_dir = "D:/downloads"
        controller.scan_local_dir = Mock()

        with patch("app.controllers.media_host_controller_mixin.debug_logger", Mock()):
            controller.on_dir_changed()

        controller.host.announce_directory_changed.assert_called_once_with("D:/downloads")
        controller.scan_local_dir.assert_called_once()

    def test_on_rename_video_reports_error_and_resets_text(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"
        controller._rename_outcome = type("Outcome", (), {"status": "error", "error": "权限不足", "new_title": None})()

        controller.on_rename_video(table_item)

        controller.host.report_rename_error.assert_called_once_with("权限不足")
        table_item.setText.assert_called_once_with("旧标题")

    def test_on_rename_video_reorders_row_after_success(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"
        controller._rename_outcome = type("Outcome", (), {"status": "ok", "error": None, "new_title": "新标题"})()

        controller.on_rename_video(table_item)

        controller.host.reorder_video_row.assert_called_once_with(item)

    def test_on_rename_video_submits_file_transaction_on_qt_thread(self):
        controller = _DummyMediaHostController()
        fake_thread = object()
        fake_app = Mock()
        fake_app.thread.return_value = fake_thread
        controller.app = fake_app
        item = VideoItem(url="", title="old", source="local")
        item.local_path = "D:/media/old.mp4"
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "new"
        submitted: list[str] = []

        class ImmediateRunner:
            def submit(self, *, name, fn):
                submitted.append(name)
                token = SimpleNamespace(is_cancelled=lambda: False)
                fn(token)
                return token

        controller._ensure_short_task_runner = Mock(return_value=ImmediateRunner())
        controller._ensure_ui_callback_invoker = Mock(return_value=SimpleNamespace(invoke=lambda callback: callback()))
        controller._rename_video_io = Mock(
            return_value=SimpleNamespace(
                status="ok",
                video_id=item.id,
                video=item,
                old_path=item.local_path,
                new_path="D:/media/new.mp4",
                new_title="new",
                error=None,
            )
        )

        with (
            patch("app.controllers.media_host_controller_mixin.QCoreApplication.instance", return_value=fake_app),
            patch("app.controllers.media_host_controller_mixin.QThread.currentThread", return_value=fake_thread),
        ):
            controller.on_rename_video(table_item)

        self.assertEqual(submitted, [f"rename-video-{item.id}"])
        controller._rename_video_io.assert_called_once_with(item.id, "new", controller.host.current_save_dir)
        self.assertEqual(item.title, "new")
        self.assertEqual(item.local_path, "D:/media/new.mp4")
        table_item.setToolTip.assert_called_once_with("new")
        controller.host.reorder_video_row.assert_called_once_with(item)

    def test_on_delete_video_missing_entry_removes_row_only(self):
        controller = _DummyMediaHostController()

        controller.on_delete_video(3, "missing")

        controller.host.remove_video_row.assert_called_once_with(3, "missing")
        controller.host.refresh_table_bindings.assert_not_called()

    def test_on_delete_video_async_submits_background_delete_without_idle_delay(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        context = SimpleNamespace(video_id=item.id, video=item, cancel_result="queued")
        outcome = SimpleNamespace(
            status="ok",
            video_id=item.id,
            video=item,
            cancel_result="queued",
            deleted=True,
            error=None,
        )
        submitted: list[tuple[str, object]] = []

        class ImmediateRunner:
            def submit(self, *, name, fn):
                submitted.append((name, fn))
                token = SimpleNamespace(is_cancelled=lambda: False, wait_cancelled=Mock(return_value=False))
                fn(token)
                return token

        controller._should_delete_media_asynchronously = Mock(return_value=True)
        controller._prepare_delete_video = Mock(return_value=context)
        controller._before_media_delete = Mock()
        controller._delete_video_context_sync = Mock(return_value=outcome)
        controller._ensure_short_task_runner = Mock(return_value=ImmediateRunner())
        controller._ensure_ui_callback_invoker = Mock(return_value=SimpleNamespace(invoke=lambda callback: callback()))

        controller.on_delete_video(5, item.id)

        controller._prepare_delete_video.assert_called_once_with(item.id)
        controller._before_media_delete.assert_called_once_with(context)
        controller._delete_video_context_sync.assert_called_once_with(context)
        self.assertEqual(submitted[0][0], f"delete-video-{item.id}")
        controller.host.remove_video_row.assert_called_once_with(5, item.id)
        controller.host.refresh_table_bindings.assert_called_once()
        self.assertNotIn(item.id, controller.videos)

    def test_on_delete_video_does_not_wait_for_download_worker_on_ui_thread(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        context = SimpleNamespace(video_id=item.id, video=item, cancel_result=None)
        outcome = SimpleNamespace(
            status="ok",
            video_id=item.id,
            video=item,
            cancel_result=None,
            deleted=True,
            error=None,
        )
        submitted = []

        class DeferredRunner:
            def submit(self, *, name, fn):
                submitted.append((name, fn))
                return SimpleNamespace(is_cancelled=lambda: False)

        controller._should_delete_media_asynchronously = Mock(return_value=True)
        controller._prepare_delete_video = Mock(return_value=context)
        controller._begin_delete_video = Mock(side_effect=AssertionError("UI thread waited for cancellation"))
        controller._before_media_delete = Mock()
        controller._delete_video_context_sync = Mock(return_value=outcome)
        controller._ensure_short_task_runner = Mock(return_value=DeferredRunner())
        controller._ensure_ui_callback_invoker = Mock(return_value=SimpleNamespace(invoke=lambda callback: callback()))

        controller.on_delete_video(5, item.id)

        controller._prepare_delete_video.assert_called_once_with(item.id)
        controller._begin_delete_video.assert_not_called()
        controller._delete_video_context_sync.assert_not_called()
        self.assertEqual(submitted[0][0], f"delete-video-{item.id}")

        token = SimpleNamespace(is_cancelled=lambda: False, wait_cancelled=Mock(return_value=False))
        submitted[0][1](token)
        controller._delete_video_context_sync.assert_called_once_with(context)

    def test_background_delete_waits_for_cancellation_before_file_io(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="demo", source="local")
        context = SimpleNamespace(video_id=item.id, video=item, cancel_result=None)
        events = []
        controller.file_service = Mock()
        controller.file_service.delete_media.side_effect = lambda _video: events.append("delete") or True
        controller._cancel_delete_context_and_wait = Mock(
            side_effect=lambda prepared: events.append("cancel") or prepared
        )

        outcome = controller._delete_video_context_sync(context)

        self.assertEqual(outcome.status, "ok")
        self.assertEqual(events, ["cancel", "delete"])

    def test_on_delete_video_async_restores_row_when_background_delete_fails(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        context = SimpleNamespace(video_id=item.id, video=item, cancel_result="queued")
        outcome = SimpleNamespace(
            status="error",
            video_id=item.id,
            video=item,
            cancel_result="queued",
            deleted=False,
            error="locked",
        )

        class ImmediateRunner:
            def submit(self, *, name, fn):
                token = SimpleNamespace(is_cancelled=lambda: False)
                fn(token)
                return token

        controller._should_delete_media_asynchronously = Mock(return_value=True)
        controller._prepare_delete_video = Mock(return_value=context)
        controller._delete_video_context_sync = Mock(return_value=outcome)
        controller._ensure_short_task_runner = Mock(return_value=ImmediateRunner())
        controller._ensure_ui_callback_invoker = Mock(return_value=SimpleNamespace(invoke=lambda callback: callback()))

        controller.on_delete_video(5, item.id)

        controller.host.remove_video_row.assert_called_once_with(5, item.id)
        controller.host.add_video_row.assert_called_once_with(item)
        controller.host.report_delete_error.assert_called_once_with("locked")
        self.assertIn(item.id, controller.videos)

    def test_delete_coordination_delay_only_applies_to_released_media(self):
        controller = _DummyMediaHostController()
        controller.MEDIA_DELETE_COORDINATION_DELAY_SEC = 0.18

        self.assertEqual(controller._delete_coordination_delay(False), 0.0)
        self.assertEqual(controller._delete_coordination_delay(True), 0.18)

    def test_delete_coordination_delay_waits_on_cancel_token(self):
        token = SimpleNamespace(is_cancelled=lambda: False, wait_cancelled=Mock(return_value=False))

        result = MediaHostControllerMixin._sleep_before_delete(0.25, token)

        self.assertTrue(result)
        token.wait_cancelled.assert_called_once_with(0.25)

    def test_delete_coordination_delay_stops_when_cancelled(self):
        token = SimpleNamespace(is_cancelled=lambda: False, wait_cancelled=Mock(return_value=True))

        result = MediaHostControllerMixin._sleep_before_delete(0.25, token)

        self.assertFalse(result)
        token.wait_cancelled.assert_called_once_with(0.25)

    def test_play_video_reports_missing_media(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = "Z:/missing.mp4"
        controller.videos[item.id] = item

        controller.play_video(item.id)

        controller.host.report_missing_media.assert_called_once()

    def test_play_video_checks_file_exists_via_short_task_on_qt_thread(self):
        controller = _DummyMediaHostController()
        fake_thread = object()
        fake_app = Mock()
        fake_app.thread.return_value = fake_thread
        controller.app = fake_app
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = "D:/media/demo.mp4"
        controller.videos[item.id] = item
        submitted: list[str] = []

        class ImmediateRunner:
            def submit(self, *, name, fn):
                submitted.append(name)
                token = SimpleNamespace(cancel=Mock(), is_cancelled=lambda: False)
                fn(token)
                return token

        controller._ensure_short_task_runner = Mock(return_value=ImmediateRunner())
        controller._ensure_ui_callback_invoker = Mock(return_value=SimpleNamespace(invoke=lambda callback: callback()))
        controller._playback_file_exists = Mock(return_value=True)

        with (
            patch("app.controllers.media_host_controller_mixin.QCoreApplication.instance", return_value=fake_app),
            patch("app.controllers.media_host_controller_mixin.QThread.currentThread", return_value=fake_thread),
            patch("app.controllers.media_host_controller_mixin.cfg.get") as cfg_get,
        ):
            cfg_get.side_effect = lambda section, key, default=None: (
                "builtin_player" if (section, key) == ("playback", "default_player")
                else True if (section, key) == ("playback", "builtin_player_enabled")
                else default
            )
            controller.play_video(item.id)

        self.assertEqual(submitted, [f"check-playback-file-{item.id}"])
        controller._playback_file_exists.assert_called_once_with(item.local_path)
        controller.host.play_video.assert_called_once_with(item.local_path)

    def test_play_video_routes_image_and_video_to_correct_host_action(self):
        controller = _DummyMediaHostController()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "demo.jpg")
            video_path = os.path.join(temp_dir, "demo.mp4")
            with open(image_path, "wb") as handle:
                handle.write(b"image")
            with open(video_path, "wb") as handle:
                handle.write(b"video")

            image_item = VideoItem(url="", title="image", source="local")
            image_item.local_path = image_path
            video_item = VideoItem(url="", title="video", source="local")
            video_item.local_path = video_path
            controller.videos[image_item.id] = image_item
            controller.videos[video_item.id] = video_item

            with patch("app.controllers.media_host_controller_mixin.cfg.get") as cfg_get:
                cfg_get.side_effect = lambda section, key, default=None: (
                    "builtin_player" if (section, key) == ("playback", "default_player")
                    else True if (section, key) == ("playback", "builtin_player_enabled")
                    else default
                )
                controller.play_video(image_item.id)
                controller.play_video(video_item.id)

        controller.host.show_image.assert_called_once_with(image_path)
        controller.host.play_video.assert_called_once_with(video_path)

    def test_play_video_uses_system_default_when_playback_setting_requests_it(self):
        controller = _DummyMediaHostController()
        controller._open_path_with_system_default = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "demo.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"video")
            item = VideoItem(url="", title="video", source="local")
            item.local_path = video_path
            controller.videos[item.id] = item

            with patch("app.controllers.media_host_controller_mixin.cfg.get") as cfg_get:
                cfg_get.side_effect = lambda section, key, default=None: (
                    "system_default" if (section, key) == ("playback", "default_player")
                    else True if (section, key) == ("playback", "builtin_player_enabled")
                    else default
                )
                controller.play_video(item.id)

        controller._open_path_with_system_default.assert_called_once_with(video_path)
        controller.host.release_media_playback.assert_called_once()
        controller.host.play_video.assert_not_called()
        controller.host.show_image.assert_not_called()

    def test_autoplay_next_preview_respects_playback_setting(self):
        controller = _DummyMediaHostController()
        current = VideoItem(url="", title="one", source="local")
        controller.current_playing_id = current.id
        controller.host.get_adjacent_video_id.return_value = "next"
        controller.play_video = Mock()

        with patch("app.controllers.media_host_controller_mixin.cfg.get", return_value=False):
            controller.autoplay_next_preview()

        controller.host.get_adjacent_video_id.assert_not_called()
        controller.play_video.assert_not_called()

    def test_switch_preview_selects_adjacent_video_in_host_order(self):
        controller = _DummyMediaHostController()
        first = VideoItem(url="", title="one", source="local")
        second = VideoItem(url="", title="two", source="local")
        controller.current_playing_id = first.id
        controller.host.get_adjacent_video_id.return_value = second.id
        controller.play_video = Mock()

        controller.switch_preview(1)

        controller.host.get_adjacent_video_id.assert_called_once_with(first.id, 1, wrap=True)
        controller.host.select_video_by_id.assert_called_once_with(second.id)
        controller.play_video.assert_called_once_with(second.id)

    def test_image_slideshow_selects_next_image_in_host_order(self):
        controller = _DummyMediaHostController()
        first = VideoItem(url="", title="one", source="local")
        second = VideoItem(url="", title="two", source="local")
        controller.current_playing_id = first.id
        controller.host.get_adjacent_image_id.return_value = second.id
        controller.play_video = Mock()

        controller.autoplay_next_image_preview()

        controller.host.get_adjacent_image_id.assert_called_once_with(first.id, 1, wrap=True)
        controller.host.select_video_by_id.assert_called_once_with(second.id)
        controller.play_video.assert_called_once_with(second.id)

    def test_autoplay_next_preview_stops_at_end_without_wrap(self):
        controller = _DummyMediaHostController()
        current = VideoItem(url="", title="one", source="local")
        controller.current_playing_id = current.id
        controller.host.get_adjacent_video_id.return_value = None
        controller.play_video = Mock()

        with patch("app.controllers.media_host_controller_mixin.cfg.get", return_value=True):
            controller.autoplay_next_preview()

        controller.host.get_adjacent_video_id.assert_called_once_with(current.id, 1, wrap=False)
        controller.host.append_log.assert_called_once_with("ℹ️ 已播放到最后一项")
        controller.play_video.assert_not_called()

    def test_on_clear_queue_removes_queue_items_and_keeps_completed(self):
        controller = _DummyMediaHostController()
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = "\u23f3 \u7b49\u5f85\u4e2d"
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "\u2705 \u672c\u5730"
        completed.progress = 100
        completed.local_path = __file__
        controller.app_state = Mock()
        controller.app_state.videos = {queued.id: queued, completed.id: completed}
        controller.app_state.task_state = {queued.id: {"progress": 0}}
        controller.app_state._last_progress_emit_at = {queued.id: 1.0}
        controller.app_state._lock = threading.RLock()
        controller.app_state._publish_change = Mock()
        controller.videos = controller.app_state.videos
        controller.dl_manager = Mock()
        controller.dl_manager.cancel_task.return_value = "queued"
        controller.frontend_state_service = Mock()
        controller.frontend_state_service.queue_item_ids = Mock(return_value={queued.id})
        controller.frontend_state_service.get_snapshot.side_effect = AssertionError("full snapshot should not be used")

        controller.on_clear_queue()

        self.assertNotIn(queued.id, controller.app_state.videos)
        self.assertIn(completed.id, controller.app_state.videos)
        self.assertNotIn(queued.id, controller.app_state.task_state)
        self.assertNotIn(queued.id, controller.app_state._last_progress_emit_at)
        controller.dl_manager.cancel_task.assert_called_once_with(queued.id)
        controller.app_state._publish_change.assert_called_once_with(
            "videos.remove_many",
            {"video_ids": [queued.id], "count": 1},
        )
        controller.host.append_log.assert_any_call(f"\U0001f5d1\ufe0f \u5df2\u5220\u9664: {queued.title}")
        controller.host.append_log.assert_any_call("\U0001f5d1\ufe0f \u5df2\u6e05\u7a7a\u4e0b\u8f7d\u961f\u5217 (1 \u9879)")
        controller.host.refresh_frontend_state.assert_called_once_with(force=False, topics={"videos.remove_many"})

    def test_on_clear_queue_batches_large_queue_without_snapshot(self):
        controller = _DummyMediaHostController()
        controller.app_state = AppState()
        items = [VideoItem(url=f"https://example.com/{index}.mp4", title=f"queued-{index}", source="douyin") for index in range(10000)]
        for item in items:
            item.status = "\u23f3 \u7b49\u5f85\u4e2d"
        ids = {item.id for item in items}
        with controller.app_state._lock:
            controller.app_state.videos = {item.id: item for item in items}
            controller.app_state.task_state = {item.id: {"progress": 0} for item in items}
        controller.videos = controller.app_state.videos
        controller.dl_manager = SimpleNamespace(cancel_tasks=Mock(return_value={video_id: "queued" for video_id in ids}))
        controller.frontend_state_service = SimpleNamespace(
            queue_item_ids=Mock(return_value=ids),
            get_snapshot=Mock(side_effect=AssertionError("full snapshot should not be used")),
        )

        controller.on_clear_queue()

        self.assertEqual(controller.app_state.videos, {})
        self.assertEqual(controller.app_state.task_state, {})
        controller.frontend_state_service.queue_item_ids.assert_called_once()
        controller.frontend_state_service.get_snapshot.assert_not_called()
        controller.dl_manager.cancel_tasks.assert_called_once()
        self.assertEqual(len(next(iter(controller.dl_manager.cancel_tasks.call_args.args))), 10000)
        controller.host.refresh_frontend_state.assert_called_once_with(force=False, topics={"videos.remove_many"})

    def test_queue_item_ids_fallback_uses_memory_state_without_snapshot(self):
        controller = _DummyMediaHostController()
        controller.app_state = AppState()
        queued = VideoItem(url="https://example.com/queued.mp4", title="queued", source="douyin")
        queued.status = "\u23f3 \u7b49\u5f85\u4e2d"
        active = VideoItem(url="https://example.com/active.mp4", title="active", source="douyin")
        active.status = "\u23f3 \u7b49\u5f85\u4e2d"
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "\u2705 \u672c\u5730"
        completed.progress = 100
        with controller.app_state._lock:
            controller.app_state.videos = {
                queued.id: queued,
                active.id: active,
                completed.id: completed,
            }
        controller.videos = controller.app_state.videos
        controller.dl_manager = SimpleNamespace(
            queue=SimpleNamespace(snapshot_video_ids=Mock(return_value={queued.id, active.id})),
            workers=[SimpleNamespace(video=active)],
            prune_finished_workers=Mock(),
        )
        controller.frontend_state_service = SimpleNamespace(
            get_snapshot=Mock(side_effect=AssertionError("full snapshot should not be used")),
        )

        self.assertEqual(controller._queue_item_ids_for_clear(), {queued.id})
        controller.frontend_state_service.get_snapshot.assert_not_called()

if __name__ == "__main__":
    unittest.main()
