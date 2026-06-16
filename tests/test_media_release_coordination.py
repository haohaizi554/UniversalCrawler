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


if __name__ == "__main__":
    unittest.main()
