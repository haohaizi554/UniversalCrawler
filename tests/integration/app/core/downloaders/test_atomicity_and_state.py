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
