from __future__ import annotations

import unittest
from pathlib import Path

from app.services.completed_metadata_rules import (
    apply_completed_metadata,
    has_media_metadata,
    metadata_failure_key,
    normalize_completed_metadata_payload,
    same_local_path,
)


class CompletedMetadataRulesTests(unittest.TestCase):
    def test_normalize_payload_accepts_duration_ms_and_dimensions(self):
        payload = normalize_completed_metadata_payload(
            {"duration_ms": 208000, "width": 1920, "height": 1080, "format": "MP4"}
        )

        self.assertEqual(payload["duration"], "00:03:28")
        self.assertEqual(payload["resolution"], "1920 x 1080")
        self.assertEqual(payload["format"], "MP4")

    def test_normalize_payload_rejects_quality_label_as_resolution(self):
        payload = normalize_completed_metadata_payload({"duration": "00:00:22", "resolution": "1080p"})

        self.assertEqual(payload["duration"], "00:00:22")
        self.assertEqual(payload["resolution"], "")

    def test_apply_metadata_only_backfills_missing_values(self):
        meta = {"duration": "--", "resolution": "1080p", "format": "MP4"}

        changed = apply_completed_metadata(
            meta,
            {"duration": "00:01:05", "resolution": "720 x 1280", "format": "WEBM"},
        )

        self.assertTrue(changed)
        self.assertEqual(meta["duration"], "00:01:05")
        self.assertEqual(meta["resolution"], "720 x 1280")
        self.assertEqual(meta["format"], "MP4")

    def test_has_media_metadata_distinguishes_video_and_image_requirements(self):
        self.assertTrue(has_media_metadata({"resolution": "1080 x 1620"}, Path("demo.webp")))
        self.assertFalse(has_media_metadata({"duration": "00:00:16"}, Path("demo.mp4")))
        self.assertTrue(has_media_metadata({"duration": "00:00:16", "resolution": "1080 x 1920"}, Path("demo.mp4")))

    def test_path_helpers_treat_slashes_as_equivalent(self):
        left = r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads\a.mp4"
        right = "D:/desktop/project/UniversalCrawlerProplus/user_data/Downloads/a.mp4"

        self.assertTrue(same_local_path(left, right))
        self.assertEqual(metadata_failure_key("v1", left), metadata_failure_key("v1", right))


if __name__ == "__main__":
    unittest.main()
