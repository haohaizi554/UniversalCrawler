from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.download_manager_core import DownloadManagerCore, PendingDownloadQueue
from app.core.downloaders.bilibili import BilibiliDownloader
from app.core.downloaders.chunked import ChunkedDownloader
from app.exceptions import DownloaderStoppedError
from app.models import VideoItem
from app.services.media_library_runtime import MediaLibraryMixin


class _ControlledWorker:
    def __init__(self, video: VideoItem) -> None:
        self.video = video
        self.stop_called = threading.Event()
        self.wait_entered = threading.Event()
        self.release = threading.Event()

    def stop(self) -> None:
        self.stop_called.set()

    def wait(self, timeout_ms: int) -> bool:
        self.wait_entered.set()
        return self.release.wait(max(0, timeout_ms) / 1000)


class _MediaController(MediaLibraryMixin):
    def __init__(self, manager: DownloadManagerCore, item: VideoItem) -> None:
        self.dl_manager = manager
        self.file_service = Mock()
        self.videos = {item.id: item}


class _StreamResponse:
    status_code = 200
    headers = {"content-length": "5", "content-type": "video/mp4"}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, *, chunk_size: int):
        del chunk_size
        yield b"video"


class DownloadPublishRaceTests(unittest.TestCase):
    @staticmethod
    def _manager_with_worker(worker: _ControlledWorker, *, timeout_ms: int) -> DownloadManagerCore:
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager._workers_lock = threading.RLock()
        manager._dispatching_tasks = []
        manager.workers = [worker]
        manager.WORKER_STOP_TIMEOUT_MS = timeout_ms
        return manager

    def test_delete_waits_for_running_worker_before_touching_file(self) -> None:
        item = VideoItem(url="https://example.com/video.mp4", title="video", source="test")
        worker = _ControlledWorker(item)
        manager = self._manager_with_worker(worker, timeout_ms=1000)
        controller = _MediaController(manager, item)
        controller.file_service.delete_media.return_value = True
        outcomes = []

        delete_thread = threading.Thread(
            target=lambda: outcomes.append(controller._delete_video_sync(item.id)),
            daemon=True,
        )
        delete_thread.start()
        try:
            self.assertTrue(worker.stop_called.wait(1))
            self.assertTrue(worker.wait_entered.wait(1))
            controller.file_service.delete_media.assert_not_called()
        finally:
            worker.release.set()
            delete_thread.join(timeout=1)

        self.assertFalse(delete_thread.is_alive())
        controller.file_service.delete_media.assert_called_once_with(item)
        self.assertEqual(outcomes[0].status, "ok")

    def test_delete_declines_when_running_worker_does_not_stop_in_time(self) -> None:
        item = VideoItem(url="https://example.com/video.mp4", title="video", source="test")
        worker = _ControlledWorker(item)
        manager = self._manager_with_worker(worker, timeout_ms=1)
        controller = _MediaController(manager, item)

        outcome = controller._delete_video_sync(item.id)

        self.assertEqual(outcome.status, "error")
        self.assertEqual(outcome.cancel_result, "timeout")
        self.assertIn(item.id, controller.videos)
        controller.file_service.delete_media.assert_not_called()

    def test_chunk_merge_stops_during_copy_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir, "source.part")
            destination = Path(temp_dir, "video.mp4")
            source.write_bytes(b"x" * (ChunkedDownloader.CHUNK_SIZE // 64))
            destination.write_bytes(b"old")
            checks = 0

            def stop_during_copy() -> bool:
                nonlocal checks
                checks += 1
                return checks >= 2

            with self.assertRaises(DownloaderStoppedError):
                ChunkedDownloader._merge_temp_files_atomically(
                    [os.fspath(source)],
                    os.fspath(destination),
                    check_stop_func=stop_during_copy,
                )

            self.assertEqual(destination.read_bytes(), b"old")
            self.assertFalse(Path(f"{destination}.merging").exists())

    def test_chunk_merge_checks_stop_immediately_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir, "source.part")
            destination = Path(temp_dir, "video.mp4")
            source.write_bytes(b"new")
            destination.write_bytes(b"old")
            cancelled = threading.Event()

            def cancel_after_flush(_fd: int) -> None:
                cancelled.set()

            with patch("app.core.downloaders.chunked.os.fsync", side_effect=cancel_after_flush), patch(
                "app.core.downloaders.chunked.os.replace"
            ) as replace:
                with self.assertRaises(DownloaderStoppedError):
                    ChunkedDownloader._merge_temp_files_atomically(
                        [os.fspath(source)],
                        os.fspath(destination),
                        check_stop_func=cancelled.is_set,
                    )

            replace.assert_not_called()
            self.assertEqual(destination.read_bytes(), b"old")
            self.assertFalse(Path(f"{destination}.merging").exists())

    def test_bilibili_cancel_after_merge_cleans_sidecar_without_publishing(self) -> None:
        item = VideoItem(url="https://cdn.example.com/video.m4s", title="video", source="bilibili")
        item.meta["audio_url"] = None
        cancelled = threading.Event()

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir, "video.mp4")
            destination.write_bytes(b"old")
            merging = Path(f"{destination}.merging")
            video_stream = Path(temp_dir, "video_video.m4s")

            def finish_merge(*_args, **kwargs) -> None:
                Path(kwargs["save_path"]).write_bytes(b"new")
                cancelled.set()

            with patch(
                "app.core.downloaders.bilibili.FFmpegExternalTool.resolve_executable",
                return_value="ffmpeg.exe",
            ), patch(
                "app.core.downloaders.bilibili.FFmpegExternalTool.build_merge_command",
                return_value=["ffmpeg", "output"],
            ), patch(
                "app.core.downloaders.bilibili.requests.get",
                return_value=_StreamResponse(),
            ), patch.object(
                BilibiliDownloader,
                "_run_merge_process",
                side_effect=finish_merge,
            ):
                with self.assertRaises(DownloaderStoppedError):
                    BilibiliDownloader().download(
                        item,
                        os.fspath(destination),
                        lambda *_args, **_kwargs: None,
                        cancelled.is_set,
                    )

            self.assertEqual(destination.read_bytes(), b"old")
            self.assertFalse(merging.exists())
            self.assertFalse(video_stream.exists())


if __name__ == "__main__":
    unittest.main()
