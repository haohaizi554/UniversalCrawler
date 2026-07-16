import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.playback_position_service import PlaybackPositionService


class PlaybackPositionServiceTests(unittest.TestCase):
    def test_position_persists_and_reloads_for_existing_file(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "demo.mp4"
            media.write_bytes(b"video")
            store = root / "positions.json"

            PlaybackPositionService(store).save(media, 30_000, duration_ms=100_000)
            reloaded = PlaybackPositionService(store)

            self.assertEqual(reloaded.get(media), 30_000)

    def test_missing_file_is_pruned_on_load_and_restore(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "demo.mp4"
            media.write_bytes(b"video")
            store = root / "positions.json"
            service = PlaybackPositionService(store, cleanup_on_load=False)
            service.save(media, 10_000, duration_ms=90_000)

            media.unlink()
            reloaded = PlaybackPositionService(store)

            self.assertEqual(reloaded.get(media), 0)
            self.assertEqual(reloaded.snapshot(), {})

    def test_changed_file_invalidates_old_position(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "demo.mp4"
            media.write_bytes(b"video")
            store = root / "positions.json"
            service = PlaybackPositionService(store)
            service.save(media, 20_000, duration_ms=100_000)

            time.sleep(0.01)
            media.write_bytes(b"changed video content")

            self.assertEqual(service.get(media), 0)
            self.assertEqual(service.snapshot(), {})

    def test_near_end_position_is_removed(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "demo.mp4"
            media.write_bytes(b"video")
            service = PlaybackPositionService(root / "positions.json")

            service.save(media, 99_000, duration_ms=100_000)

            self.assertEqual(service.get(media), 0)

    def test_max_entries_keeps_newest_items(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = PlaybackPositionService(root / "positions.json", max_entries=2)
            paths = []
            for index in range(3):
                media = root / f"{index}.mp4"
                media.write_bytes(f"video-{index}".encode())
                paths.append(media)
                service.save(media, 10_000 + index, duration_ms=60_000)

            self.assertEqual(service.get(paths[0]), 0)
            self.assertGreater(service.get(paths[1]), 0)
            self.assertGreater(service.get(paths[2]), 0)


if __name__ == "__main__":
    unittest.main()
