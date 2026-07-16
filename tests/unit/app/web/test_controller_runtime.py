import unittest
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.exceptions import FileOperationError
from app.models import VideoItem

def _signal():
    return SimpleNamespace(connect=Mock())

class WebControllerRuntimeTests(unittest.TestCase):
    def _controller_with_video(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()
        item = VideoItem(url="https://example.com/a.mp4", title="a", source="douyin")
        controller._store_video_item(item)
        return controller, item

    @staticmethod
    def _video_state_events(controller):
        return [
            call.args[1]
            for call in controller.bridge.emit.call_args_list
            if call.args and call.args[0] == "video_state_changed"
        ]

    def test_init_does_not_create_download_manager_until_needed(self):
        from app.web.controller import WebController

        fake_manager = SimpleNamespace(
            task_started=_signal(),
            task_progress=_signal(),
            task_finished=_signal(),
            task_error=_signal(),
        )

        with patch("app.web.controller.DownloadManager", return_value=fake_manager) as mocked_manager:
            controller = WebController(None, lambda *_args, **_kwargs: None)

            self.assertIsNone(controller._dl_manager)
            mocked_manager.assert_not_called()

            manager = controller.dl_manager

        self.assertIs(manager, fake_manager)
        mocked_manager.assert_called_once()
        fake_manager.task_started.connect.assert_called_once_with(controller._on_task_started)
        fake_manager.task_progress.connect.assert_called_once_with(controller._on_task_progress)
        fake_manager.task_finished.connect.assert_called_once_with(controller._on_task_finished)
        fake_manager.task_error.connect.assert_called_once_with(controller._on_task_error)

    def test_on_spider_item_found_skips_image_when_video_only_enabled(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()
        controller._dl_manager = SimpleNamespace(video_only=True, add_task=Mock())
        item = VideoItem(url="https://example.com/cover.jpg", title="cover", source="xiaohongshu")
        item.meta["content_type"] = "image/jpeg"

        controller._on_spider_item_found(item)

        self.assertEqual(controller._video_count(), 0)
        controller.bridge.emit.assert_not_called()
        controller._dl_manager.add_task.assert_not_called()


    def test_shutdown_does_not_create_download_manager_for_idle_session(self):
        from app.web.controller import WebController

        with patch("app.web.controller.DownloadManager") as mocked_manager:
            controller = WebController(None, lambda *_args, **_kwargs: None)
            controller.shutdown()

        mocked_manager.assert_not_called()

    def test_shutdown_releases_frontend_state_and_cache_resources(self):
        from app.web.controller import WebController

        frontend_state = Mock()
        frontend_state.app_state = Mock()
        frontend_state.cache_service = Mock()

        with patch("app.web.controller.FrontendStateService", return_value=frontend_state):
            controller = WebController(None, lambda *_args, **_kwargs: None)

        controller.shutdown()

        frontend_state.destroy.assert_called_once()
        frontend_state.app_state.shutdown.assert_called_once()
        frontend_state.cache_service.close.assert_called_once()

    def test_start_crawl_waits_for_shutdown_lifecycle_lock(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        entered_shutdown_wait = threading.Event()
        release_shutdown = threading.Event()
        started: list[bool] = []

        class FakeSpider:
            def __init__(self):
                self.running = True
                self.stopped = False

            def isRunning(self):
                return self.running

            def stop(self):
                self.stopped = True

            def wait(self, _timeout_ms):
                entered_shutdown_wait.set()
                release_shutdown.wait(timeout=1)
                self.running = False
                return True

        def fake_start(*_args):
            started.append(True)

        controller.current_spider = FakeSpider()
        controller._start_crawl_unlocked = fake_start

        # 模拟 shutdown 正在等待 spider 退出；新 start_crawl 必须排队等待，
        # 否则 current_spider 会被两个生命周期同时读写。
        shutdown_thread = threading.Thread(target=controller.shutdown)
        shutdown_thread.start()
        self.assertTrue(entered_shutdown_wait.wait(timeout=1))

        start_thread = threading.Thread(target=lambda: controller.start_crawl("douyin", "demo", {}))
        start_thread.start()
        time.sleep(0.05)
        self.assertEqual(started, [])

        release_shutdown.set()
        shutdown_thread.join(timeout=1)
        start_thread.join(timeout=1)

        self.assertEqual(started, [True])

    def test_shutdown_wait_does_not_block_spider_finished_callback(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()
        entered_shutdown_wait = threading.Event()
        release_shutdown = threading.Event()

        class FakeSpider:
            def isRunning(self):
                return True

            def stop(self):
                pass

            def wait(self, _timeout_ms):
                entered_shutdown_wait.set()
                release_shutdown.wait(timeout=1)
                return True

        controller.current_spider = FakeSpider()
        shutdown_thread = threading.Thread(target=controller.shutdown)
        shutdown_thread.start()
        self.assertTrue(entered_shutdown_wait.wait(timeout=1))

        # sig_finished 可能在 shutdown 等待期间抵达；回调不能被同一把锁挡住，
        # 否则退出流程和 spider 线程会互相等待。
        finished_thread = threading.Thread(target=controller._on_spider_finished)
        finished_thread.start()
        finished_thread.join(timeout=0.5)
        self.assertFalse(finished_thread.is_alive())

        release_shutdown.set()
        shutdown_thread.join(timeout=1)

    def test_resume_selection_none_requests_spider_stop(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()

        class FakeSpider:
            def __init__(self):
                self.running = True
                self.interrupt_requested = False
                self.stopped = False
                self.resumed_with = object()

            def isRunning(self):
                return self.running

            def stop(self):
                self.stopped = True
                self.interrupt_requested = True
                self.running = False

            def resume_from_ui(self, value):
                self.resumed_with = value

        spider = FakeSpider()
        controller.current_spider = spider

        controller.resume_spider_selection(None)

        self.assertTrue(spider.stopped)
        self.assertIsNone(spider.resumed_with)
        self.assertIsNone(controller.current_spider)
        controller.bridge.emit.assert_any_call("crawl_state", {"is_running": False})

    def test_video_store_snapshot_and_clear_are_lock_guarded(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        item = VideoItem(url="https://example.com/a.mp4", title="a", source="douyin")

        controller._store_video_item(item)
        controller._on_task_progress(item.id, 55)
        self.assertIn(item.id, controller._last_progress_emit_at)
        snapshot = controller._video_items_snapshot()
        snapshot[item.id].title = "mutated"
        controller._clear_video_items()

        self.assertIsNot(snapshot[item.id], item)
        self.assertEqual(item.title, "a")
        self.assertEqual(controller._video_count(), 0)
        self.assertEqual(controller._last_progress_emit_at, {})
        self.assertEqual(controller._last_progress_emit_value, {})

    def test_async_media_scan_preserves_ids_and_emits_one_delta_per_real_change(self):
        import asyncio
        from app.web.controller import WebController

        sent: list[tuple[str, dict | None]] = []
        controller = WebController(None, lambda event_type, data=None: sent.append((event_type, data)))
        try:
            with TemporaryDirectory() as tmp:
                media_path = Path(tmp) / "demo.mp4"
                media_path.write_bytes(b"video")

                async def run_scans():
                    first = await controller.async_scan_local_dir(tmp, announce=False)
                    second = await controller.async_scan_local_dir(tmp, announce=False)
                    media_path.unlink()
                    third = await controller.async_scan_local_dir(tmp, announce=False)
                    return first, second, third

                first, second, third = asyncio.run(run_scans())

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertIsNotNone(third)
            first_id = first[1].items[0].id
            self.assertEqual(second[1].items[0].id, first_id)
            self.assertEqual(second[1].added_ids, ())
            self.assertEqual(second[1].removed_ids, ())
            self.assertEqual(third[1].removed_ids, (first_id,))

            event_types = [event_type for event_type, _data in sent]
            self.assertEqual(event_types.count("videos.reconcile"), 2)
            self.assertNotIn("clear_videos", event_types)
            self.assertNotIn("item_found", event_types)
        finally:
            controller.shutdown()

    def test_async_change_dir_rescans_when_directory_is_unchanged(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.current_save_dir = "D:/Downloads"
        controller.async_scan_local_dir = AsyncMock(return_value=("result", "outcome"))

        result = asyncio.run(controller.async_change_dir(r"D:\Downloads"))

        self.assertEqual(result, ("result", "outcome"))
        controller.async_scan_local_dir.assert_awaited_once_with(
            r"D:\Downloads",
            require_current=True,
        )
        controller.shutdown()

    def test_async_frontend_delete_action_uses_async_delete_video(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.async_delete_video = AsyncMock()

        result = asyncio.run(controller.async_handle_frontend_action("delete_item", {"id": "video-1"}))

        self.assertEqual(result["status"], "ok")
        controller.async_delete_video.assert_awaited_once_with("video-1")

    def test_async_frontend_delete_action_propagates_delete_failure(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.async_delete_video = AsyncMock(
            return_value={"status": "error", "message": "permission denied", "data": {"video_id": "video-1"}}
        )

        result = asyncio.run(controller.async_handle_frontend_action("delete_item", {"id": "video-1"}))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "permission denied")
        controller.async_delete_video.assert_awaited_once_with("video-1")

    def test_async_frontend_delete_action_forwards_approved_roots(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.async_delete_video = AsyncMock(return_value={"status": "ok"})

        result = asyncio.run(
            controller.async_handle_frontend_action(
                "delete_item",
                {"id": "video-1"},
                approved_roots=("C:/allowed",),
            )
        )

        self.assertEqual(result["status"], "ok")
        controller.async_delete_video.assert_awaited_once_with("video-1", ("C:/allowed",))

    def test_async_frontend_action_runs_sync_handler_off_event_loop_thread(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        worker_threads: list[int] = []

        def fake_handle(action, payload):
            worker_threads.append(threading.get_ident())
            return {"status": "ok", "action": action, "payload": payload}

        async def run_action():
            main_thread = threading.get_ident()
            result = await controller.async_handle_frontend_action(
                "update_setting",
                {"section": "common", "key": "theme", "value": "dark"},
            )
            return main_thread, result

        controller.handle_frontend_action = fake_handle

        # WebSocket/REST 事件循环只负责调度；同步 action 必须进 executor，
        # 避免配置写入或文件操作阻塞所有连接。
        main_thread, result = asyncio.run(run_action())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "update_setting")
        self.assertTrue(worker_threads)
        self.assertNotEqual(worker_threads[0], main_thread)

    def test_async_delete_video_preserves_item_on_file_delete_error(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        controller.file_service.delete_media = Mock(side_effect=FileOperationError("permission denied"))

        # 删除文件失败时不能先从内存表删项，否则 UI 会丢失可重试/诊断信息。
        result = asyncio.run(controller.async_delete_video(item.id))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "permission denied")
        self.assertIs(controller._video_lookup(item.id), item)
        controller.file_service.delete_media.assert_called_once()
        self.assertIn(
            "mutation_plan",
            controller.file_service.delete_media.call_args.kwargs,
        )

    def test_delete_video_does_not_emit_removed_for_superseded_same_id_item(self):
        controller, old = self._controller_with_video()
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = old.id

        class RaceManager:
            def cancel_video_and_wait(self, video):
                controller._store_video_item(replacement)
                return "queued"

        controller._dl_manager = RaceManager()
        controller.file_service.delete_media = Mock(return_value=True)

        result = controller.delete_video(old.id)

        self.assertEqual(result["status"], "superseded")
        self.assertIs(controller._video_lookup(old.id), replacement)
        controller.file_service.delete_media.assert_not_called()
        self.assertNotIn(
            "video_removed",
            [call.args[0] for call in controller.bridge.emit.call_args_list],
        )

    def test_async_delete_video_runs_cancel_wait_and_delete_off_event_loop(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        thread_ids: dict[str, int] = {}
        original_cancel = controller._cancel_delete_context_and_wait
        original_complete = controller._complete_delete_video

        def cancel_delete(context):
            thread_ids["cancel"] = threading.get_ident()
            return original_cancel(context)

        def delete_media(_video, *, mutation_plan):
            self.assertIsNotNone(mutation_plan)
            thread_ids["delete"] = threading.get_ident()
            return True

        def complete_delete(context, *, deleted):
            thread_ids["complete"] = threading.get_ident()
            return original_complete(context, deleted=deleted)

        controller._cancel_delete_context_and_wait = cancel_delete
        controller.file_service.delete_media = delete_media
        controller._complete_delete_video = complete_delete

        async def run_delete():
            loop_thread_id = threading.get_ident()
            result = await controller.async_delete_video(item.id)
            return loop_thread_id, result

        loop_thread_id, result = asyncio.run(run_delete())

        self.assertEqual(result["status"], "ok")
        self.assertNotEqual(thread_ids["cancel"], loop_thread_id)
        self.assertEqual(thread_ids["cancel"], thread_ids["delete"])
        self.assertEqual(thread_ids["complete"], thread_ids["delete"])

    def test_async_delete_video_preserves_same_id_replacement_created_during_cancel(self):
        import asyncio

        controller, old = self._controller_with_video()
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = old.id

        class RaceManager:
            def cancel_video_and_wait(self, video):
                controller._store_video_item(replacement)
                return "queued"

        controller._dl_manager = RaceManager()
        controller.file_service.delete_media = Mock(return_value=True)

        result = asyncio.run(controller.async_delete_video(old.id))

        self.assertEqual(result["status"], "superseded")
        self.assertIs(controller._video_lookup(old.id), replacement)
        controller.file_service.delete_media.assert_not_called()

    def test_async_delete_video_reauthorizes_the_frozen_path_after_cancellation(self):
        import asyncio

        controller, item = self._controller_with_video()
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            allowed_path = Path(allowed_root) / "inside.mp4"
            outside_path = Path(outside_root) / "outside.mp4"
            allowed_path.write_bytes(b"inside")
            outside_path.write_bytes(b"outside")
            item.local_path = str(allowed_path)

            class PathSwapManager:
                def cancel_video_and_wait(self, video):
                    video.local_path = str(outside_path)
                    return None

            controller._dl_manager = PathSwapManager()
            controller.file_service.delete_media = Mock(return_value=True)

            result = asyncio.run(controller.async_delete_video(item.id, (allowed_root,)))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("http_status"), 403)
        self.assertEqual(result["data"]["code"], "directory_not_authorized")
        self.assertIs(controller._video_lookup(item.id), item)
        controller.file_service.delete_media.assert_not_called()

    def test_async_delete_video_keeps_captured_identity_across_initial_authorization(self):
        import asyncio

        from app.web.controller_config_service import WebControllerConfigService

        controller, old = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            allowed_path = Path(allowed_root) / "old.mp4"
            outside_path = Path(outside_root) / "replacement.mp4"
            allowed_path.write_bytes(b"old")
            outside_path.write_bytes(b"replacement")
            old.local_path = str(allowed_path)
            replacement = VideoItem(url="", title="replacement", source="local")
            replacement.id = old.id
            replacement.local_path = str(outside_path)
            controller.file_service.delete_media = Mock(return_value=True)
            original_authorize = WebControllerConfigService.authorize_path
            authorization_calls = 0

            def authorize_then_replace(path, roots):
                nonlocal authorization_calls
                result = original_authorize(path, roots)
                authorization_calls += 1
                if authorization_calls == 1:
                    controller._store_video_item(replacement)
                return result

            with patch.object(
                WebControllerConfigService,
                "authorize_path",
                side_effect=authorize_then_replace,
            ):
                result = asyncio.run(
                    controller.async_delete_video(old.id, (allowed_root,))
                )

        self.assertEqual(result["status"], "superseded")
        self.assertIs(controller._video_lookup(old.id), replacement)
        controller.file_service.delete_media.assert_not_called()

    def test_async_delete_video_rejects_media_outside_approved_roots(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller.file_service.delete_media = Mock(return_value=True)
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            item.local_path = str(Path(outside_root) / "outside.mp4")

            result = asyncio.run(controller.async_delete_video(item.id, (allowed_root,)))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("http_status"), 403)
        self.assertIn("授权", result["message"])
        self.assertIs(controller._video_lookup(item.id), item)
        controller.file_service.delete_media.assert_not_called()

    def test_async_delete_video_allows_media_inside_approved_root(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller.file_service.delete_media = Mock(return_value=True)
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root:
            item.local_path = str(Path(allowed_root) / "inside.mp4")

            result = asyncio.run(controller.async_delete_video(item.id, (allowed_root,)))

        self.assertEqual(result["status"], "ok")
        controller.file_service.delete_media.assert_called_once()
        self.assertIn(
            "mutation_plan",
            controller.file_service.delete_media.call_args.kwargs,
        )

    def test_async_delete_video_authorizes_every_frozen_mutation_target_without_local_path(self):
        import asyncio

        from app.web.controller_config_service import WebControllerConfigService

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        item.local_path = ""
        item.source = "bilibili"
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root:
            allowed = Path(allowed_root)
            video_temp = allowed / "clip_video.m4s"
            audio_temp = allowed / "clip_audio.m4s"
            gallery_dir = allowed / "gallery"
            gallery_dir.mkdir()
            video_temp.write_bytes(b"video")
            audio_temp.write_bytes(b"audio")
            item.meta.update(
                {
                    "bvid": "BV1test",
                    "download_temp_files": [str(video_temp)],
                    "folder_name": "gallery",
                    "use_subdir": True,
                    "save_directory": str(gallery_dir),
                }
            )
            controller.file_service.delete_media = Mock(return_value=True)
            original_authorize = WebControllerConfigService.authorize_path

            with patch.object(
                WebControllerConfigService,
                "authorize_path",
                wraps=original_authorize,
            ) as authorize_path:
                result = asyncio.run(
                    controller.async_delete_video(item.id, (allowed_root,))
                )

        authorized = {
            str(Path(call.args[0]).resolve())
            for call in authorize_path.call_args_list
            if call.args and str(call.args[0] or "")
        }
        self.assertEqual(result["status"], "ok")
        self.assertTrue(
            {str(video_temp.resolve()), str(audio_temp.resolve()), str(gallery_dir.resolve())}
            <= authorized
        )
        mutation_plan = controller.file_service.delete_media.call_args.kwargs[
            "mutation_plan"
        ]
        self.assertTrue(
            {str(video_temp.resolve()), str(audio_temp.resolve()), str(gallery_dir.resolve())}
            <= {str(Path(path).resolve()) for path in mutation_plan.authorization_targets}
        )

    def test_async_delete_video_rejects_unauthorized_temp_before_canceling_download(self):
        import asyncio

        controller, item = self._controller_with_video()
        cancel_task = Mock(return_value=None)
        controller._dl_manager = SimpleNamespace(cancel_task=cancel_task)
        controller.file_service.delete_media = Mock(return_value=True)
        item.local_path = ""
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            outside_temp = Path(outside_root) / "clip.mp4.tmp"
            outside_temp.write_bytes(b"partial")
            item.meta["download_temp_files"] = [str(outside_temp)]

            result = asyncio.run(
                controller.async_delete_video(item.id, (allowed_root,))
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("http_status"), 403)
        cancel_task.assert_not_called()
        controller.file_service.delete_media.assert_not_called()
        self.assertIs(controller._video_lookup(item.id), item)
        self.assertFalse(hasattr(item, "_media_delete_generation"))

    def test_async_delete_video_uses_authorized_paths_in_final_mutation_plan(self):
        import asyncio

        from app.services.file_service import MediaDeleteMutationPlan
        from app.web.controller_config_service import WebControllerConfigService

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        original_plan = MediaDeleteMutationPlan(
            file_path="D:/alias/video.mp4",
            temp_paths=("D:/alias/video.mp4.tmp",),
            owned_directories=("D:/alias/gallery",),
        )
        authorized_plan = MediaDeleteMutationPlan(
            file_path="D:/canonical/video.mp4",
            temp_paths=("D:/canonical/video.mp4.tmp",),
            owned_directories=("D:/canonical/gallery",),
        )
        normalized_by_original = dict(
            zip(original_plan.authorization_targets, authorized_plan.authorization_targets)
        )
        controller.file_service.build_delete_media_plan = Mock(return_value=original_plan)
        controller.file_service.delete_media = Mock(return_value=True)

        with patch.object(
            WebControllerConfigService,
            "authorize_path",
            side_effect=lambda path, _roots: normalized_by_original[path],
        ):
            result = asyncio.run(controller.async_delete_video(item.id))

        self.assertEqual(result["status"], "ok")
        mutation_plan = controller.file_service.delete_media.call_args.kwargs[
            "mutation_plan"
        ]
        self.assertEqual(mutation_plan, authorized_plan)

    def test_async_delete_video_enqueues_removed_before_success_log_can_insert_replacement(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        controller.file_service.delete_media = Mock(return_value=True)
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = item.id
        order: list[str] = []

        def emit(event_type, _payload):
            if event_type == "video_removed":
                order.append("removed")

        async def send_recorded(event_type, _payload):
            if event_type == "log" and "replacement" not in order:
                controller._store_video_item(replacement)
                order.append("replacement")
            elif event_type == "video_removed":
                order.append("removed")

        controller.bridge.emit = Mock(side_effect=emit)
        controller._send_recorded_frontend_event = send_recorded

        result = asyncio.run(controller.async_delete_video(item.id))

        self.assertEqual(result["status"], "ok")
        self.assertIs(controller._video_lookup(item.id), replacement)
        self.assertLess(order.index("removed"), order.index("replacement"))

    def test_async_delete_video_cancellation_still_commits_worker_state_and_cleans_generation(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        delete_started = threading.Event()
        release_delete = threading.Event()
        state_committed = threading.Event()
        original_complete = controller._complete_delete_video

        def delete_media(*_args, **_kwargs):
            delete_started.set()
            release_delete.wait(timeout=2)
            return True

        def complete_delete(context, *, deleted):
            try:
                return original_complete(context, deleted=deleted)
            finally:
                state_committed.set()

        controller.file_service.delete_media = delete_media
        controller._complete_delete_video = complete_delete

        async def cancel_while_worker_is_deleting():
            task = asyncio.create_task(controller.async_delete_video(item.id))
            deadline = asyncio.get_running_loop().time() + 1
            while not delete_started.is_set() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.001)
            self.assertTrue(delete_started.is_set())
            task.cancel()
            release_delete.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            deadline = asyncio.get_running_loop().time() + 1
            while not state_committed.is_set() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.001)

        asyncio.run(cancel_while_worker_is_deleting())

        self.assertTrue(state_committed.is_set())
        self.assertIsNone(controller._video_lookup(item.id))
        self.assertFalse(hasattr(item, "_media_delete_generation"))

    def test_async_rename_video_delegates_file_check_to_executor_service(self):
        import asyncio

        from app.web.controller_config_service import WebControllerConfigService

        controller, item = self._controller_with_video()
        item.local_path = "Z:/definitely-missing/input.mp4"
        controller.file_service.rename_media = Mock(side_effect=FileOperationError("file not found"))

        result = asyncio.run(controller.async_rename_video(item.id, "new title"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "file not found")
        rename_target, title, save_dir = controller.file_service.rename_media.call_args.args
        self.assertEqual(title, "new title")
        self.assertEqual(
            rename_target.local_path,
            WebControllerConfigService.authorize_path(item.local_path, None),
        )
        self.assertEqual(
            save_dir,
            WebControllerConfigService.authorize_path(controller.current_save_dir, None),
        )

    def test_async_rename_video_rejects_media_outside_approved_roots(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller.file_service.rename_media = Mock()
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            item.local_path = str(Path(outside_root) / "outside.mp4")

            result = asyncio.run(controller.async_rename_video(item.id, "new title", (allowed_root,)))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("http_status"), 403)
        self.assertIn("授权", result["message"])
        controller.file_service.rename_media.assert_not_called()

    def test_async_rename_video_reauthorizes_current_path_inside_worker(self):
        import asyncio

        from app.web.controller_config_service import WebControllerConfigService

        controller, item = self._controller_with_video()
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            allowed_path = Path(allowed_root) / "inside.mp4"
            outside_path = Path(outside_root) / "outside.mp4"
            allowed_path.write_bytes(b"inside")
            outside_path.write_bytes(b"outside")
            item.local_path = str(allowed_path)
            controller.current_save_dir = allowed_root
            controller.file_service.rename_media = Mock(
                return_value=(str(outside_path), str(Path(allowed_root) / "renamed.mp4"))
            )
            original_authorize = WebControllerConfigService.authorize_path
            authorization_calls = 0

            def authorize_then_swap(path, roots):
                nonlocal authorization_calls
                result = original_authorize(path, roots)
                authorization_calls += 1
                if authorization_calls == 1:
                    item.local_path = str(outside_path)
                return result

            with patch.object(
                WebControllerConfigService,
                "authorize_path",
                side_effect=authorize_then_swap,
            ):
                result = asyncio.run(
                    controller.async_rename_video(item.id, "renamed", (allowed_root,))
                )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("http_status"), 403)
        self.assertEqual(result["data"]["code"], "directory_not_authorized")
        controller.file_service.rename_media.assert_not_called()

    def test_async_rename_video_allows_media_inside_approved_root(self):
        import asyncio

        controller, item = self._controller_with_video()
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root:
            item.local_path = str(Path(allowed_root) / "inside.mp4")
            controller.current_save_dir = allowed_root
            renamed_path = str(Path(allowed_root) / "renamed.mp4")
            controller.file_service.rename_media = Mock(return_value=(item.local_path, renamed_path))

            result = asyncio.run(controller.async_rename_video(item.id, "new title", (allowed_root,)))

        self.assertEqual(result["status"], "ok")
        controller.file_service.rename_media.assert_called_once()

    def test_async_rename_video_uses_authorized_source_and_save_directory(self):
        import asyncio

        from app.web.controller_config_service import WebControllerConfigService

        controller, item = self._controller_with_video()
        item.local_path = "D:/alias/input.mp4"
        controller.current_save_dir = "D:/alias/output"
        authorized_source = "D:/canonical/input.mp4"
        authorized_save_dir = "D:/canonical/output"
        controller.file_service.rename_media = Mock(
            return_value=(authorized_source, f"{authorized_save_dir}/renamed.mp4")
        )

        def authorize(path, _roots):
            if path == item.local_path:
                return authorized_source
            if path == controller.current_save_dir:
                return authorized_save_dir
            return path

        with patch.object(
            WebControllerConfigService,
            "authorize_path",
            side_effect=authorize,
        ):
            result = asyncio.run(controller.async_rename_video(item.id, "renamed"))

        self.assertEqual(result["status"], "ok")
        rename_target, _title, save_dir = controller.file_service.rename_media.call_args.args
        self.assertEqual(rename_target.local_path, authorized_source)
        self.assertEqual(save_dir, authorized_save_dir)

    def test_async_rename_video_enqueues_event_before_same_id_replacement_after_identity_check(self):
        import asyncio

        controller, item = self._controller_with_video()
        item.local_path = "D:/downloads/original.mp4"
        controller.current_save_dir = "D:/downloads"
        controller.file_service.rename_media = Mock(
            return_value=(item.local_path, "D:/downloads/renamed.mp4")
        )
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = item.id
        replacement.local_path = "D:/downloads/replacement.mp4"
        log_sent = threading.Event()
        commit_check_seen = threading.Event()
        replacement_done = threading.Event()
        order: list[str] = []
        event_loop_thread = threading.get_ident()
        original_lookup = controller._video_lookup

        def lookup(video_id):
            current = original_lookup(video_id)
            if (
                log_sent.is_set()
                and threading.get_ident() == event_loop_thread
                and not commit_check_seen.is_set()
            ):
                commit_check_seen.set()
            return current

        def replace_after_commit_check():
            if commit_check_seen.wait(timeout=2):
                controller._store_video_item(replacement)
                order.append("replacement")
            replacement_done.set()

        def emit(event_type, _payload):
            if event_type == "video_renamed":
                order.append("renamed")

        async def send_recorded(event_type, _payload):
            if event_type == "log":
                log_sent.set()
            elif event_type == "video_renamed":
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    replacement_done.wait,
                    2,
                )
                order.append("renamed")

        controller._video_lookup = lookup
        controller.bridge.emit = Mock(side_effect=emit)
        controller._send_recorded_frontend_event = send_recorded
        replacement_thread = threading.Thread(target=replace_after_commit_check)
        replacement_thread.start()
        try:
            result = asyncio.run(controller.async_rename_video(item.id, "renamed"))
        finally:
            replacement_thread.join(timeout=2)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(commit_check_seen.is_set())
        self.assertTrue(replacement_done.is_set())
        self.assertEqual(order[:2], ["renamed", "replacement"])
        self.assertIs(controller._video_lookup(item.id), replacement)

    def test_async_rename_video_returns_superseded_when_replaced_after_executor_unlock(self):
        import asyncio

        controller, item = self._controller_with_video()
        item.local_path = "D:/downloads/original.mp4"
        controller.current_save_dir = "D:/downloads"
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = item.id
        replacement.local_path = "D:/downloads/replacement.mp4"
        controller.file_service.rename_media = Mock(
            return_value=(item.local_path, "D:/downloads/renamed.mp4")
        )
        controller._send_recorded_frontend_event = AsyncMock()

        async def replace_before_executor_waiter_resumes():
            loop = asyncio.get_running_loop()
            original_run_in_executor = loop.run_in_executor

            def run_then_replace(executor, func, *args):
                future = original_run_in_executor(executor, func, *args)
                future.add_done_callback(
                    lambda _future: controller._store_video_item(replacement)
                )
                return future

            with patch.object(loop, "run_in_executor", side_effect=run_then_replace):
                return await controller.async_rename_video(item.id, "renamed")

        result = asyncio.run(replace_before_executor_waiter_resumes())

        self.assertEqual(result["status"], "superseded")
        self.assertIs(controller._video_lookup(item.id), replacement)
        self.assertNotIn(
            "video_renamed",
            [call.args[0] for call in controller._send_recorded_frontend_event.await_args_list],
        )

    def test_get_media_path_returns_record_path_without_disk_probe(self):
        controller, item = self._controller_with_video()
        item.local_path = "Z:/definitely-missing/input.mp4"

        self.assertEqual(controller.get_media_path(item.id), item.local_path)

    def test_file_response_service_uses_request_range_header_fallback(self):
        import asyncio

        from app.web.file_response_service import WebFileResponseService

        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            media_path = Path(temp_dir) / "sample.mp4"
            media_path.write_bytes(b"0123456789")
            controller = SimpleNamespace(get_media_path=Mock(return_value=str(media_path)))
            context = SimpleNamespace(controller=controller, approved_roots=(temp_dir,))
            request = SimpleNamespace(headers={"range": "bytes=1-3"})
            service = WebFileResponseService(
                get_request_context=Mock(return_value=context),
                has_valid_session_token=Mock(return_value=True),
            )

            response = asyncio.run(
                service.get_media(request, "video-1", None, require_session_token=False)
            )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 1-3/10")
        self.assertEqual(response.headers["content-length"], "3")

    def test_progress_signal_is_throttled_inside_time_window(self):
        controller, item = self._controller_with_video()

        controller._on_task_progress(item.id, 10)
        controller._on_task_progress(item.id, 11)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [10])

        controller._last_progress_emit_at[item.id] -= controller.PROGRESS_EVENT_MIN_INTERVAL_SECONDS
        controller._on_task_progress(item.id, 11)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [10, 11])

    def test_progress_signal_drops_duplicate_value_even_after_interval(self):
        controller, item = self._controller_with_video()

        controller._on_task_progress(item.id, 42)
        controller._last_progress_emit_at[item.id] -= controller.PROGRESS_EVENT_MIN_INTERVAL_SECONDS
        controller._on_task_progress(item.id, 42)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [42])

    def test_terminal_progress_bypasses_throttle(self):
        controller, item = self._controller_with_video()

        controller._on_task_progress(item.id, 20)
        controller._on_task_progress(item.id, 100)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [20, 100])

    def test_progress_emit_state_is_removed_when_task_finishes(self):
        controller, item = self._controller_with_video()
        controller._on_task_progress(item.id, 55)
        self.assertIn(item.id, controller._last_progress_emit_at)

        controller._on_task_finished(item.id)

        self.assertNotIn(item.id, controller._last_progress_emit_at)
        self.assertNotIn(item.id, controller._last_progress_emit_value)

    def test_progress_emit_state_is_removed_when_task_fails_or_is_deleted(self):
        controller, item = self._controller_with_video()
        controller._on_task_progress(item.id, 55)

        controller._on_task_error(item.id, "network timeout")

        self.assertNotIn(item.id, controller._last_progress_emit_at)
        self.assertNotIn(item.id, controller._last_progress_emit_value)

        controller, item = self._controller_with_video()
        controller._on_task_progress(item.id, 55)
        controller._remove_video_item(item.id)

        self.assertNotIn(item.id, controller._last_progress_emit_at)
        self.assertNotIn(item.id, controller._last_progress_emit_value)

if __name__ == "__main__":
    unittest.main()
