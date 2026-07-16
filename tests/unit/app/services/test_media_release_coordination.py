import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.media_release_coordination import (
    normalize_media_path,
    poll_media_release_request,
    publish_media_release_request,
    read_media_release_request,
)

class MediaReleaseCoordinationTests(unittest.TestCase):
    def test_publish_and_read_media_release_request_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.services.media_release_coordination.user_data_root", return_value=Path(temp_dir)):
                request = publish_media_release_request(
                    local_path=r"C:\Temp\demo.mp4",
                    source="gui",
                    reason="delete",
                )
                loaded = read_media_release_request()

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.request_id, request.request_id)
        self.assertEqual(loaded.local_path, normalize_media_path(r"C:\Temp\demo.mp4"))
        self.assertEqual(loaded.source, "gui")

    def test_poll_media_release_request_skips_same_request_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.services.media_release_coordination.user_data_root", return_value=Path(temp_dir)):
                request = publish_media_release_request(
                    local_path=r"C:\Temp\demo.mp4",
                    source="web",
                    reason="delete",
                )
                same_id, loaded = poll_media_release_request(request.request_id)

        self.assertEqual(same_id, request.request_id)
        self.assertIsNone(loaded)

    def test_publish_uses_unique_atomic_temp_file_per_request(self):
        written_temp_paths: list[Path] = []
        original_replace = Path.replace

        def recording_replace(source: Path, target: Path):
            written_temp_paths.append(source)
            return original_replace(source, target)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.services.media_release_coordination.user_data_root",
            return_value=Path(temp_dir),
        ), patch.object(Path, "replace", recording_replace):
            publish_media_release_request(local_path="first.mp4", source="gui")
            publish_media_release_request(local_path="second.mp4", source="web")

        self.assertEqual(len(written_temp_paths), 2)
        self.assertEqual(len(set(written_temp_paths)), 2)
        self.assertTrue(all(path.suffix == ".tmp" for path in written_temp_paths))

if __name__ == "__main__":
    unittest.main()
