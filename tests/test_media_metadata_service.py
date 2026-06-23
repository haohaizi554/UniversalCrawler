import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from app.services.media_metadata_service import MediaMetadata, MediaMetadataService


class MediaMetadataServiceTests(unittest.TestCase):
    def test_ffprobe_json_extracts_duration_and_resolution(self):
        payload = {
            "format": {"duration": "83.2", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
        }

        metadata = MediaMetadataService.from_ffprobe_payload(payload, path="demo.mp4")

        self.assertEqual(metadata.duration, "00:01:23")
        self.assertEqual(metadata.resolution, "1920 x 1080")
        self.assertEqual(metadata.format, "MP4")
        self.assertEqual(metadata.content_type, "video")

    def test_ffmpeg_output_fallback_extracts_duration_and_resolution(self):
        output = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'demo.mp4':
  Duration: 00:01:23.45, start: 0.000000, bitrate: 1200 kb/s
  Stream #0:0: Video: h264, yuv420p, 1280x720 [SAR 1:1 DAR 16:9], 30 fps
"""

        metadata = MediaMetadataService.from_ffmpeg_output(output, path="demo.mp4")

        self.assertEqual(metadata.duration, "00:01:23")
        self.assertEqual(metadata.resolution, "1280 x 720")
        self.assertEqual(metadata.format, "MP4")

    def test_ffprobe_ignores_attached_picture_streams(self):
        payload = {
            "format": {"duration": "22.1", "format_name": "mov,mp4"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 600,
                    "height": 600,
                    "disposition": {"attached_pic": 1},
                },
                {"codec_type": "video", "width": 1080, "height": 1440},
            ],
        }

        metadata = MediaMetadataService.from_ffprobe_payload(payload, path="demo.mp4")

        self.assertEqual(metadata.duration, "00:00:22")
        self.assertEqual(metadata.resolution, "1080 x 1440")

    def test_ffprobe_rotation_reports_display_resolution(self):
        payload = {
            "format": {"duration": "22", "format_name": "mov,mp4"},
            "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "tags": {"rotate": "90"}}],
        }

        metadata = MediaMetadataService.from_ffprobe_payload(payload, path="demo.mp4")

        self.assertEqual(metadata.resolution, "1920 x 1080")

    def test_image_header_fallback_extracts_png_resolution(self):
        service = MediaMetadataService(ffprobe_resolver=lambda: None, ffmpeg_resolver=lambda: None)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cover.png"
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + (13).to_bytes(4, "big")
                + b"IHDR"
                + (640).to_bytes(4, "big")
                + (360).to_bytes(4, "big")
                + b"\x08\x02\x00\x00\x00"
            )

            metadata = service.probe(path)

        self.assertEqual(metadata.resolution, "640 x 360")
        self.assertEqual(metadata.format, "PNG")
        self.assertEqual(metadata.content_type, "image")

    def test_probe_keeps_partial_duration_when_resolution_is_missing(self):
        def runner(args, **_kwargs):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"format":{"duration":"65","format_name":"mp4"},"streams":[]}',
                stderr="",
            )

        service = MediaMetadataService(ffprobe_resolver=lambda: "ffprobe", ffmpeg_resolver=lambda: None, runner=runner)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "duration-only.mp4"
            path.write_bytes(b"media")

            metadata = service.probe(path)

        self.assertEqual(metadata.duration, "00:01:05")
        self.assertEqual(metadata.resolution, "")

    def test_probe_uses_shell_fallback_to_complete_partial_video_metadata(self):
        def runner(args, **_kwargs):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"format":{"duration":"65","format_name":"mp4"},"streams":[]}',
                stderr="",
            )

        service = MediaMetadataService(ffprobe_resolver=lambda: "ffprobe", ffmpeg_resolver=lambda: None, runner=runner)
        service._probe_windows_shell = lambda _path: MediaMetadata(resolution="640 x 360", content_type="video")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "duration-shell-resolution.mp4"
            path.write_bytes(b"media")

            metadata = service.probe(path)

        self.assertEqual(metadata.duration, "00:01:05")
        self.assertEqual(metadata.resolution, "640 x 360")

    def test_probe_merges_ffprobe_duration_with_ffmpeg_resolution(self):
        def runner(args, **_kwargs):
            command = list(args)
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout='{"format":{"duration":"65","format_name":"mp4"},"streams":[]}',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="",
                stderr="Duration: 00:00:00.00, start: 0.000000\nStream #0:0: Video: h264, yuv420p, 720x1280 [SAR 1:1 DAR 9:16]",
            )

        service = MediaMetadataService(ffprobe_resolver=lambda: "ffprobe", ffmpeg_resolver=lambda: "ffmpeg", runner=runner)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "merged.mp4"
            path.write_bytes(b"media")

            metadata = service.probe(path)

        self.assertEqual(metadata.duration, "00:01:05")
        self.assertEqual(metadata.resolution, "720 x 1280")

    def test_cache_hit_does_not_repeat_probe_until_file_changes(self):
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"format":{"duration":"12","format_name":"mp4"},"streams":[{"codec_type":"video","width":640,"height":360}]}',
                stderr="",
            )

        service = MediaMetadataService(ffprobe_resolver=lambda: "ffprobe", runner=runner)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            path.write_bytes(b"one")
            done = threading.Event()

            self.assertTrue(service.ensure_probe(path, lambda _metadata: done.set()))
            self.assertTrue(done.wait(2))
            self.assertIsNotNone(service.cached(path))
            self.assertFalse(service.ensure_probe(path, lambda _metadata: None))
            self.assertEqual(len(calls), 1)

            path.write_bytes(b"changed-size")
            done_again = threading.Event()
            self.assertTrue(service.ensure_probe(path, lambda _metadata: done_again.set()))
            self.assertTrue(done_again.wait(2))
            self.assertEqual(len(calls), 2)

    def test_empty_probe_result_is_not_exposed_as_cache_and_can_retry(self):
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

        service = MediaMetadataService(ffprobe_resolver=lambda: "ffprobe", ffmpeg_resolver=lambda: None, runner=runner)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.mp4"
            path.write_bytes(b"media")
            first_done = threading.Event()

            self.assertTrue(service.ensure_probe(path, lambda _metadata: first_done.set()))
            self.assertTrue(first_done.wait(2))
            self.assertIsNone(service.cached(path))
            first_probe_calls = len(calls)
            self.assertFalse(service.ensure_probe(path, lambda _metadata: None))
            self.assertTrue(service.is_probe_deferred(path))
            self.assertEqual(len(calls), first_probe_calls)

            service.EMPTY_RETRY_SECONDS = 0
            second_done = threading.Event()
            self.assertTrue(service.ensure_probe(path, lambda _metadata: second_done.set()))
            self.assertTrue(second_done.wait(2))
            self.assertGreater(len(calls), first_probe_calls)

    def test_probe_worker_exception_still_invokes_callback(self):
        service = MediaMetadataService(ffprobe_resolver=lambda: None, ffmpeg_resolver=lambda: None)
        service.probe = Mock(side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte"))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-output.mp4"
            path.write_bytes(b"media")
            done = threading.Event()
            results = []

            self.assertTrue(service.ensure_probe(path, lambda metadata: (results.append(metadata), done.set())))
            self.assertTrue(done.wait(2))

        self.assertEqual(results[0].format, "MP4")
        self.assertEqual(results[0].content_type, "video")

    def test_windows_shell_payload_extracts_duration_and_resolution(self):
        metadata = MediaMetadataService.from_windows_shell_payload(
            {"Duration": 2080000000, "Width": 1920, "Height": 1080},
            path="demo.mp4",
        )

        self.assertEqual(metadata.duration, "00:03:28")
        self.assertEqual(metadata.resolution, "1920 x 1080")
        self.assertEqual(metadata.format, "MP4")


if __name__ == "__main__":
    unittest.main()
