"""测试模块，覆盖 `tests/test_utils_filenames.py` 对应功能的行为与回归场景。"""

import unittest

from app.utils import build_media_filename, sanitize_filename

class FilenameUtilsTests(unittest.TestCase):
    
    def test_sanitize_filename_replaces_invalid_characters_and_trims_suffix(self):
        """验证 `test_sanitize_filename_replaces_invalid_characters_and_trims_suffix` 对应场景是否符合预期，供 `FilenameUtilsTests` 使用。"""
        result = sanitize_filename('  bad:/name?*.mp4.  ')

        self.assertEqual(result, "bad__name__.mp4")

    def test_sanitize_filename_replaces_control_characters(self):
        result = sanitize_filename("line1\nline2\tclip.mp4")

        self.assertEqual(result, "line1_line2_clip.mp4")

    def test_sanitize_filename_truncates_overlong_names(self):
        """验证 `test_sanitize_filename_truncates_overlong_names` 对应场景是否符合预期，供 `FilenameUtilsTests` 使用。"""
        result = sanitize_filename("a" * 260)

        self.assertEqual(len(result), 200)
        self.assertTrue(result.startswith("a" * 50))

    def test_sanitize_filename_falls_back_to_untitled_for_blank_values(self):
        """验证 `test_sanitize_filename_falls_back_to_untitled_for_blank_values` 对应场景是否符合预期，供 `FilenameUtilsTests` 使用。"""
        self.assertEqual(sanitize_filename("   "), "untitled")
        self.assertEqual(sanitize_filename(None), "None")

    def test_build_media_filename_appends_missav_subtitle_tag(self):
        """验证 `test_build_media_filename_appends_missav_subtitle_tag` 对应场景是否符合预期，供 `FilenameUtilsTests` 使用。"""
        result = build_media_filename(
            "IPX-001",
            "missav",
            "mp4",
            {"tags": ["中文字幕"]},
        )

        self.assertEqual(result, "IPX-001 [中文字幕].mp4")

    def test_build_media_filename_normalizes_extension_and_uses_untitled_when_empty(self):
        """验证 `test_build_media_filename_normalizes_extension_and_uses_untitled_when_empty` 对应场景是否符合预期，供 `FilenameUtilsTests` 使用。"""
        result = build_media_filename("", "douyin", "jpg")

        self.assertEqual(result, "untitled.jpg")

if __name__ == "__main__":
    unittest.main()
