"""测试模块，覆盖 `tests/test_runtime_paths.py` 对应功能的行为与回归场景。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils import runtime_paths


class RuntimePathsTests(unittest.TestCase):
    """封装 `RuntimePathsTests` 在 `tests/test_runtime_paths.py` 中承担的核心逻辑。"""
    def test_install_root_uses_executable_parent_when_frozen(self):
        """验证 `test_install_root_uses_executable_parent_when_frozen` 对应场景是否符合预期，供 `RuntimePathsTests` 使用。"""
        with patch("app.utils.runtime_paths.is_frozen", return_value=True), patch(
            "app.utils.runtime_paths.sys.executable",
            r"D:\Portable\UniversalCrawlerPro\UniversalCrawlerPro.exe",
        ):
            result = runtime_paths.install_root()

        self.assertEqual(result, Path(r"D:\Portable\UniversalCrawlerPro"))

    def test_resource_root_uses_meipass_when_present(self):
        """验证 `test_resource_root_uses_meipass_when_present` 对应场景是否符合预期，供 `RuntimePathsTests` 使用。"""
        with patch("app.utils.runtime_paths.is_frozen", return_value=True), patch(
            "app.utils.runtime_paths.sys._MEIPASS",
            r"D:\Temp\_MEI12345",
            create=True,
        ):
            result = runtime_paths.resource_root()

        self.assertEqual(result, Path(r"D:\Temp\_MEI12345"))

    def test_user_data_root_creates_directory_under_local_appdata(self):
        """验证 `test_user_data_root_creates_directory_under_local_appdata` 对应场景是否符合预期，供 `RuntimePathsTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "app.utils.runtime_paths.os.environ",
            {"LOCALAPPDATA": temp_dir},
            clear=False,
        ):
            result = runtime_paths.user_data_root()
            self.assertEqual(result, Path(temp_dir) / runtime_paths.APP_DIR_NAME)
            self.assertTrue(result.exists())

    def test_resolve_user_file_keeps_absolute_and_expands_relative_path(self):
        """验证 `test_resolve_user_file_keeps_absolute_and_expands_relative_path` 对应场景是否符合预期，供 `RuntimePathsTests` 使用。"""
        absolute_path = Path(r"D:\Data\demo.txt")

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "app.utils.runtime_paths.os.environ",
            {"LOCALAPPDATA": temp_dir},
            clear=False,
        ):
            relative_result = runtime_paths.resolve_user_file("logs/demo.log")

        self.assertEqual(runtime_paths.resolve_user_file(absolute_path), absolute_path)
        self.assertEqual(
            relative_result,
            Path(temp_dir) / runtime_paths.APP_DIR_NAME / "logs" / "demo.log",
        )

    def test_resolve_tool_file_prefers_install_root_then_resource_root(self):
        """验证 `test_resolve_tool_file_prefers_install_root_then_resource_root` 对应场景是否符合预期，供 `RuntimePathsTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "install"
            resource_dir = Path(temp_dir) / "resource"
            install_dir.mkdir()
            resource_dir.mkdir()
            tool_name = "ffmpeg.exe"
            resource_tool = resource_dir / tool_name
            resource_tool.write_bytes(b"binary")

            with patch("app.utils.runtime_paths.install_root", return_value=install_dir), patch(
                "app.utils.runtime_paths.resource_root",
                return_value=resource_dir,
            ):
                result = runtime_paths.resolve_tool_file(tool_name)

        self.assertEqual(result, resource_tool)

    def test_resolve_tool_file_falls_back_to_executable_name_when_missing(self):
        """验证 `test_resolve_tool_file_falls_back_to_executable_name_when_missing` 对应场景是否符合预期，供 `RuntimePathsTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_dir = Path(temp_dir)
            with patch("app.utils.runtime_paths.install_root", return_value=empty_dir), patch(
                "app.utils.runtime_paths.resource_root",
                return_value=empty_dir,
            ):
                result = runtime_paths.resolve_tool_file("N_m3u8DL-RE.exe")

        self.assertEqual(result, Path("N_m3u8DL-RE.exe"))


if __name__ == "__main__":
    unittest.main()
