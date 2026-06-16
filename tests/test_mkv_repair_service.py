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

    def test_non_mkv_is_not_repaired(self):
        service = MkvPlaybackRepairService(ffmpeg_resolver=lambda: "ffmpeg")

        result = service.repair_for_playback("demo.mp4")

        self.assertFalse(result.repaired)
        self.assertEqual(result.playable_path, "demo.mp4")


if __name__ == "__main__":
    unittest.main()
