"""Regression tests for hardened concurrency paths."""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from app.config.settings import ConfigManager, get_platform_runtime_defaults
from app.services.app_state import AppState
from app.services.media_release_coordination import publish_media_release_request

class HardeningRegressionTests(unittest.TestCase):
    def test_snapshot_videos_isolated_from_live_dict(self):
        state = AppState()
        item = state._video_item_from_snapshot(
            {
                "id": "v1",
                "url": "https://example.com",
                "title": "demo",
                "source": "local",
                "status": "",
                "progress": 0,
                "local_path": "",
                "meta": {},
            }
        )
        state.upsert_video(item)
        snapshot = state.snapshot_videos()
        snapshot["v1"].title = "mutated"
        self.assertNotEqual(state.videos["v1"].title, "mutated")

    def test_get_platform_runtime_defaults_under_lock(self):
        manager = ConfigManager()
        results: list[dict] = []

        def reader() -> None:
            for _ in range(20):
                results.append(get_platform_runtime_defaults("douyin", manager))

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(isinstance(item, dict) for item in results))

    def test_publish_media_release_request_cleans_tmp_on_error(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            request_file = Path(tmp_dir) / "media_release.json"
            tmp_file = Path(tmp_dir) / "media_release.tmp"
            with mock.patch(
                "app.services.media_release_coordination._request_file",
                return_value=request_file,
            ):
                with mock.patch.object(Path, "replace", side_effect=OSError("replace failed")):
                    with self.assertRaises(OSError):
                        publish_media_release_request(
                            local_path=str(Path(tmp_dir) / "clip.mp4"),
                            source="test",
                        )
            self.assertFalse(tmp_file.exists())

if __name__ == "__main__":
    unittest.main()
