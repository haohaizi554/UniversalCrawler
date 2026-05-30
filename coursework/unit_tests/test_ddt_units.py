"""Use ddt to satisfy coursework unit-test requirements."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from ddt import data, ddt, unpack


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.video_item import VideoItem
from app.utils.filenames import build_media_filename, sanitize_filename


@ddt
class FilenameUtilityDdtTests(unittest.TestCase):
    """Core unit 1: filename normalization helpers."""

    @data(
        ("bad:/name?*.mp4.  ", "bad__name__.mp4"),
        ("   ", "untitled"),
        ("a" * 260, "a" * 200),
        ("safe_name", "safe_name"),
    )
    @unpack
    def test_sanitize_filename_data_driven(self, raw_name: str, expected: str):
        """验证 `test_sanitize_filename_data_driven` 对应场景是否符合预期，供 `FilenameUtilityDdtTests` 使用。"""
        self.assertEqual(sanitize_filename(raw_name), expected)

    @data(
        {"title": "CAWD-377", "source": "missav", "extension": "mp4", "meta": {"tags": ["中文字幕"]}, "expected": "CAWD-377 [中文字幕].mp4"},
        {"title": "", "source": "douyin", "extension": ".jpg", "meta": {}, "expected": "untitled.jpg"},
        {"title": "demo", "source": "bilibili", "extension": "m4a", "meta": {}, "expected": "demo.m4a"},
    )
    def test_build_media_filename_data_driven(self, case: dict):
        """验证 `test_build_media_filename_data_driven` 对应场景是否符合预期，供 `FilenameUtilityDdtTests` 使用。"""
        result = build_media_filename(case["title"], case["source"], case["extension"], case["meta"])
        self.assertEqual(result, case["expected"])


@ddt
class VideoItemDdtTests(unittest.TestCase):
    """Core unit 2: shared media model behavior."""

    @data(
        {"title": "  demo-one  ", "extension": ".mp4", "updates": {"status": "done", "progress": 100}, "expected_title": "demo-one", "expected_status": "done", "expected_progress": 100},
        {"title": "  ", "extension": ".jpg", "updates": {"local_path": "downloads/demo.jpg"}, "expected_title": "", "expected_status": "waiting", "expected_progress": 0},
    )
    def test_video_item_defaults_and_updates(self, case: dict):
        """验证 `test_video_item_defaults_and_updates` 对应场景是否符合预期，供 `VideoItemDdtTests` 使用。"""
        item = VideoItem(url="https://example.com/item", title=case["title"], source="douyin")
        item.update_from_dict(case["updates"])

        self.assertEqual(item.title, case["expected_title"])
        self.assertEqual(item.status, case["expected_status"])
        self.assertEqual(item.progress, case["expected_progress"])
        self.assertTrue(item.get_safe_filename(case["extension"]).endswith(case["extension"]))

    @data(
        ({"meta": {"trace_id": "trace-1"}}, True),
        ({"meta": "bad-meta"}, False),
    )
    @unpack
    def test_video_item_meta_update_guard(self, payload: dict, should_update: bool):
        """验证 `test_video_item_meta_update_guard` 对应场景是否符合预期，供 `VideoItemDdtTests` 使用。"""
        item = VideoItem(url="https://example.com/item", title="demo", source="bilibili")
        item.update_from_dict(payload)

        if should_update:
            self.assertEqual(item.meta, {"trace_id": "trace-1"})
        else:
            self.assertEqual(item.meta, {})


if __name__ == "__main__":
    unittest.main()
