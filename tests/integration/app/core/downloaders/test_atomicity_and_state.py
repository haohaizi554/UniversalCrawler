import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.download_manager import DownloadWorker
from app.core.downloaders import ChunkedDownloader
from app.core.downloaders.bilibili import BilibiliDownloader
from app.models import VideoItem


class DownloadAtomicityAndStateTests(unittest.TestCase):
    def test_video_item_serialization_uses_shared_metadata_lock(self):
        item = VideoItem(url="https://example.com/a", title="a", source="test")
        serialized = threading.Event()

        with item.meta_guard():
            thread = threading.Thread(target=lambda: (item.to_dict(), serialized.set()))
            thread.start()
            self.assertFalse(serialized.wait(0.05))

        thread.join(timeout=1)
        self.assertTrue(serialized.is_set())

    def test_download_worker_running_state_is_event_backed(self):
        item = VideoItem(url="https://example.com/a", title="a", source="test")
        worker = DownloadWorker(item, ".")

        self.assertTrue(worker.is_running)
        self.assertIsInstance(worker._running_event, threading.Event)
        worker.stop()
        self.assertFalse(worker.is_running)

    def test_download_worker_reports_error_when_downloader_returns_without_output(self):
        class SilentDownloader:
            @staticmethod
            def download(**_kwargs):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            stale_path = Path(temp_dir, "stale.mp4")
            stale_path.write_bytes(b"old")
            item = VideoItem(url="https://example.com/a.mp4", title="a", source="test")
            item.local_path = os.fspath(stale_path)
            worker = DownloadWorker(item, temp_dir)
            finished: list[str] = []
            errors: list[tuple[str, str]] = []
            worker.sig_finished.connect(finished.append)
            worker.sig_error.connect(lambda video_id, error: errors.append((video_id, error)))

            with patch.object(worker, "_select_downloader", return_value=SilentDownloader()):
                worker.run()

            self.assertEqual(finished, [])
            self.assertEqual(len(errors), 1)
            self.assertIn("下载完成但文件不存在", errors[0][1])
            self.assertEqual(item.local_path, "")

    def test_download_worker_publishes_local_path_only_after_file_exists(self):
        observed_paths: list[str] = []

        class WritingDownloader:
            @staticmethod
            def download(*, video_item, save_path, **_kwargs):
                observed_paths.append(video_item.local_path)
                Path(save_path).write_bytes(b"video")
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            item = VideoItem(url="https://example.com/a.mp4", title="a", source="test")
            worker = DownloadWorker(item, temp_dir)
            started_paths: list[str] = []
            finished: list[str] = []
            worker.sig_start.connect(lambda _video_id: started_paths.append(item.local_path))
            worker.sig_finished.connect(finished.append)

            with patch.object(worker, "_select_downloader", return_value=WritingDownloader()):
                worker.run()

            self.assertEqual(started_paths, [""])
            self.assertEqual(observed_paths, [""])
            self.assertEqual(finished, [item.id])
            self.assertTrue(Path(item.local_path).is_file())

    def test_download_worker_accepts_existing_alternate_output_reported_by_downloader(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            alternate_path = Path(temp_dir, "gallery_1.jpeg")

            class GalleryDownloader:
                @staticmethod
                def download(**_kwargs):
                    alternate_path.write_bytes(b"image")
                    return os.fspath(alternate_path)

            item = VideoItem(url="https://example.com/gallery", title="gallery", source="test")
            worker = DownloadWorker(item, temp_dir)
            finished: list[str] = []
            worker.sig_finished.connect(finished.append)

            with patch.object(worker, "_select_downloader", return_value=GalleryDownloader()):
                worker.run()

            self.assertEqual(finished, [item.id])
            self.assertEqual(item.local_path, os.fspath(alternate_path))

    def test_chunk_merge_replaces_destination_only_after_complete_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir, "first.part")
            second = Path(temp_dir, "second.part")
            destination = Path(temp_dir, "video.mp4")
            first.write_bytes(b"abc")
            second.write_bytes(b"def")
            destination.write_bytes(b"old")

            ChunkedDownloader._merge_temp_files_atomically(
                [os.fspath(first), os.fspath(second)],
                os.fspath(destination),
            )

            self.assertEqual(destination.read_bytes(), b"abcdef")
            self.assertFalse(Path(f"{destination}.merging").exists())

    def test_chunk_merge_failure_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            part = Path(temp_dir, "first.part")
            destination = Path(temp_dir, "video.mp4")
            part.write_bytes(b"new")
            destination.write_bytes(b"old")

            with patch("app.core.downloaders.chunked.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    ChunkedDownloader._merge_temp_files_atomically(
                        [os.fspath(part)],
                        os.fspath(destination),
                    )

            self.assertEqual(destination.read_bytes(), b"old")
            self.assertFalse(Path(f"{destination}.merging").exists())

    def test_bilibili_publish_is_atomic_and_preserves_destination_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            merging = Path(temp_dir, "video.mp4.merging")
            destination = Path(temp_dir, "video.mp4")
            merging.write_bytes(b"new")
            destination.write_bytes(b"old")

            with patch("app.core.downloaders.bilibili.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    BilibiliDownloader._publish_merged_file(
                        os.fspath(merging),
                        os.fspath(destination),
                    )

            self.assertEqual(destination.read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
