import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.mkv_repair_service import MkvPlaybackRepairService

class MkvPlaybackRepairServiceTests(unittest.TestCase):
    def test_repair_remuxes_mkv_to_cache_without_touching_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mkv"
            source.write_bytes(b"source")
            calls: list[list[str]] = []

            def fake_runner(command: list[str]) -> subprocess.CompletedProcess:
                calls.append(command)
                Path(command[-1]).write_bytes(b"repaired")
                return subprocess.CompletedProcess(command, 0, "", "")

            service = MkvPlaybackRepairService(
                cache_root=root / "cache",
                ffmpeg_resolver=lambda: "ffmpeg",
                process_runner=fake_runner,
            )

            result = service.repair_for_playback(source)

            self.assertTrue(result.repaired)
            self.assertNotEqual(result.playable_path, str(source))
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(Path(result.playable_path).read_bytes(), b"repaired")
            self.assertEqual(len(calls), 1)
            command = calls[0]
            self.assertIn("+genpts", command)
            self.assertIn("-c", command)
            self.assertIn("copy", command)
            self.assertIn("-f", command)
            self.assertIn("matroska", command)

    def test_repair_reuses_existing_cache_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mkv"
            source.write_bytes(b"source")
            calls = 0

            def fake_runner(command: list[str]) -> subprocess.CompletedProcess:
                nonlocal calls
                calls += 1
                Path(command[-1]).write_bytes(b"repaired")
                return subprocess.CompletedProcess(command, 0, "", "")

            service = MkvPlaybackRepairService(
                cache_root=root / "cache",
                ffmpeg_resolver=lambda: "ffmpeg",
                process_runner=fake_runner,
            )

            first = service.repair_for_playback(source)
            second = service.repair_for_playback(source)

            self.assertTrue(first.repaired)
            self.assertTrue(second.repaired)
            self.assertEqual(first.playable_path, second.playable_path)
            self.assertEqual(calls, 1)

    def test_repair_reports_start_and_completion_progress(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mkv"
            source.write_bytes(b"source")
            progress: list[int] = []

            def fake_runner(command: list[str]) -> subprocess.CompletedProcess:
                Path(command[-1]).write_bytes(b"repaired")
                return subprocess.CompletedProcess(command, 0, "", "")

            service = MkvPlaybackRepairService(
                cache_root=root / "cache",
                ffmpeg_resolver=lambda: "ffmpeg",
                process_runner=fake_runner,
            )

            result = service.repair_for_playback(source, progress_callback=lambda pct, _msg: progress.append(pct))

            self.assertTrue(result.repaired)
            self.assertEqual(progress[0], 0)
            self.assertEqual(progress[-1], 100)

    def test_cached_playable_path_returns_existing_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mkv"
            source.write_bytes(b"source")
            service = MkvPlaybackRepairService(
                cache_root=root / "cache",
                ffmpeg_resolver=lambda: "ffmpeg",
            )
            service.cache_root.mkdir(parents=True)
            cache_path = service._cache_path_for(source)
            cache_path.write_bytes(b"cached")

            self.assertEqual(service.cached_playable_path(source), str(cache_path))

    def test_repair_falls_back_to_source_when_ffmpeg_is_missing(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "broken.mkv"
            source.write_bytes(b"source")
            service = MkvPlaybackRepairService(
                cache_root=Path(tmp) / "cache",
                ffmpeg_resolver=lambda: None,
            )

            result = service.repair_for_playback(source)

            self.assertFalse(result.repaired)
            self.assertEqual(result.playable_path, str(source))

    def test_unsupported_file_is_not_repaired(self):
        service = MkvPlaybackRepairService(ffmpeg_resolver=lambda: "ffmpeg")

        result = service.repair_for_playback("demo.txt")

        self.assertFalse(result.repaired)
        self.assertEqual(result.playable_path, "demo.txt")

    def test_existing_mp4_can_be_remuxed_to_faststart_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mp4"
            source.write_bytes(b"source")
            calls: list[list[str]] = []

            def fake_runner(command: list[str]) -> subprocess.CompletedProcess:
                calls.append(command)
                Path(command[-1]).write_bytes(b"repaired")
                return subprocess.CompletedProcess(command, 0, "", "")

            service = MkvPlaybackRepairService(
                cache_root=root / "cache",
                ffmpeg_resolver=lambda: "ffmpeg",
                process_runner=fake_runner,
            )

            result = service.repair_for_playback(source)

            self.assertTrue(result.repaired)
            self.assertTrue(result.playable_path.endswith(".mp4"))
            self.assertIn("+faststart", calls[0])
            self.assertIn("mp4", calls[0])

    def test_write_repair_to_source_replaces_original_file_safely(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mkv"
            repaired = root / "cache.mkv"
            source.write_bytes(b"old")
            repaired.write_bytes(b"new-fixed")
            progress: list[int] = []
            service = MkvPlaybackRepairService(cache_root=root / "cache")

            result = service.write_repair_to_source(
                source,
                repaired,
                progress_callback=lambda pct, _msg: progress.append(pct),
            )

            self.assertTrue(result.committed)
            self.assertEqual(source.read_bytes(), b"new-fixed")
            self.assertEqual(progress[-1], 100)
            self.assertFalse(any(root.glob("*.ucp-commit.*.tmp")))

    def test_stale_cache_temp_files_are_removed_on_startup(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            stale = cache / "playback_dead.ucp-repairing.1.tmp.mkv"
            stale.write_bytes(b"partial")
            os.utime(stale, (1, 1))

            MkvPlaybackRepairService(cache_root=cache)

            self.assertFalse(stale.exists())

    def test_stale_source_commit_temp_files_are_removed_before_writeback(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.mkv"
            repaired = root / "cache.mkv"
            stale = root / ".broken.mkv.ucp-commit.1.tmp"
            source.write_bytes(b"old")
            repaired.write_bytes(b"new")
            stale.write_bytes(b"partial")
            os.utime(stale, (1, 1))

            service = MkvPlaybackRepairService(cache_root=root / "cache")
            result = service.write_repair_to_source(source, repaired)

            self.assertTrue(result.committed)
            self.assertFalse(stale.exists())

    def test_discard_cache_file_only_removes_files_under_cache_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            cache_file = cache / "playback_fixed.mkv"
            outside_file = root / "outside.mkv"
            cache_file.write_bytes(b"cache")
            outside_file.write_bytes(b"outside")
            service = MkvPlaybackRepairService(cache_root=cache)

            self.assertTrue(service.discard_cache_file(cache_file))
            self.assertFalse(cache_file.exists())
            self.assertFalse(service.discard_cache_file(outside_file))
            self.assertTrue(outside_file.exists())

if __name__ == "__main__":
    unittest.main()
