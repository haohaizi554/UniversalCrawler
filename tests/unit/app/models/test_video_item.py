"""VideoItem 模型的初始化、序列化与状态行为测试。"""

import unittest

from app.models import VideoItem

class VideoItemTests(unittest.TestCase):
    
    def test_ids_use_unique_uuid_format(self):
        """验证 `test_ids_use_unique_uuid_format` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        first = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")
        second = VideoItem(url="https://example.com/2.mp4", title="demo", source="douyin")

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(first.id), 32)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in first.id))

    def test_defaults_are_initialized_for_queue_usage(self):
        """验证 `test_defaults_are_initialized_for_queue_usage` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        item = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")

        self.assertEqual(item.status, "waiting")
        self.assertEqual(item.progress, 0)
        self.assertEqual(item.local_path, "")
        self.assertEqual(item.meta, {})

    def test_title_is_trimmed_on_creation(self):
        """验证 `test_title_is_trimmed_on_creation` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        item = VideoItem(url="https://example.com/1.mp4", title="  标题两侧有空格  ", source="douyin")

        self.assertEqual(item.title, "标题两侧有空格")

    def test_get_safe_filename_uses_title_and_normalizes_extension(self):
        """验证 `test_get_safe_filename_uses_title_and_normalizes_extension` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        item = VideoItem(url="https://example.com/1.mp4", title='  bad:/name?  ', source="douyin")

        self.assertEqual(item.get_safe_filename("mp4"), "bad__name_.mp4")

    def test_get_safe_filename_uses_source_and_id_when_title_is_empty(self):
        """验证 `test_get_safe_filename_uses_source_and_id_when_title_is_empty` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        item = VideoItem(url="https://example.com/1.mp4", title="", source="kuaishou")

        self.assertEqual(item.get_safe_filename(), f"kuaishou_{item.id}.mp4")

    def test_update_from_dict_only_updates_whitelisted_fields(self):
        """验证 `test_update_from_dict_only_updates_whitelisted_fields` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        item = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")

        item.update_from_dict(
            {
                "status": "done",
                "progress": 100,
                "meta": {"trace_id": "trace-1"},
                "id": "should-not-change",
                "unknown": "ignored",
            }
        )

        self.assertEqual(item.status, "done")
        self.assertEqual(item.progress, 100)
        self.assertEqual(item.meta, {"trace_id": "trace-1"})
        self.assertNotEqual(item.id, "should-not-change")
        self.assertFalse(hasattr(item, "unknown"))

    def test_update_from_dict_rejects_non_dict_meta(self):
        """验证 `test_update_from_dict_rejects_non_dict_meta` 对应场景是否符合预期，供 `VideoItemTests` 使用。"""
        item = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")
        item.meta = {"trace_id": "old"}

        item.update_from_dict({"meta": ["bad-shape"], "local_path": ""})

        self.assertEqual(item.meta, {"trace_id": "old"})
        self.assertEqual(item.local_path, "")

if __name__ == "__main__":
    unittest.main()
