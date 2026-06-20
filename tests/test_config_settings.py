"""测试模块，覆盖 `tests/test_config_settings.py` 对应功能的行为与回归场景。"""

import tempfile
import threading
import unittest
from pathlib import Path

from PyQt6.QtCore import QByteArray

from app.config import DEFAULT_USER_AGENT
from app.config.constants import DEFAULT_DOWNLOAD_DIR
from app.config.settings import ConfigManager
from app.utils.runtime_paths import resolve_user_file

class ConfigManagerTests(unittest.TestCase):
    
    def test_legacy_theme_value_is_normalized(self):
        """验证 `test_legacy_theme_value_is_normalized` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                fp.write('{"common":{"theme":"light","dark_theme":true}}')

            manager = ConfigManager(config_path)

            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))

    def test_legacy_dark_default_migrates_to_light(self):
        """旧版本默认 dark 配置应迁移为新版浅色默认。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                fp.write('{"common":{"theme":"dark","dark_theme":true}}')

            manager = ConfigManager(config_path)

            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))
            self.assertEqual(manager.get("common", "theme_schema_version"), 2)

    def test_set_validates_and_persists(self):
        """验证 `test_set_validates_and_persists` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("missav", "proxy_url", "http://127.0.0.1:10809")

            reloaded = ConfigManager(config_path)
            self.assertEqual(reloaded.get("missav", "proxy_url"), "http://127.0.0.1:10809")

    def test_auth_section_defaults_and_persistence(self):
        """验证 `test_auth_section_defaults_and_persistence` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("auth", "kuaishou_cookie_file", "custom_ks_auth.json")

            reloaded = ConfigManager(config_path)
            self.assertEqual(
                reloaded.get("auth", "kuaishou_cookie_file"),
                str(resolve_user_file("custom_ks_auth.json")),
            )

    def test_user_agent_defaults_share_single_constant(self):
        """验证 `test_user_agent_defaults_share_single_constant` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            self.assertEqual(manager.settings.douyin.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(manager.settings.xiaohongshu.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(manager.settings.bilibili.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(manager.settings.kuaishou.user_agent, DEFAULT_USER_AGENT)

    def test_short_video_platform_limits_default_to_twenty(self):
        """验证 `test_short_video_platform_limits_default_to_twenty` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.douyin.max_items, 20)
            self.assertEqual(manager.settings.xiaohongshu.max_items, 20)
            self.assertEqual(manager.settings.kuaishou.max_items, 20)

    def test_platform_runtime_defaults_are_declared_in_config_models(self):
        """平台运行参数默认值应由配置模型统一声明，而非调用方各自硬编码。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.douyin.timeout, 10)
            self.assertEqual(manager.settings.bilibili.max_items, 30)
            self.assertEqual(manager.settings.bilibili.timeout, 10)
            self.assertEqual(manager.settings.xiaohongshu.timeout, 30)
            self.assertEqual(manager.settings.xiaohongshu.request_interval, 1.5)
            self.assertEqual(manager.settings.xiaohongshu.detail_request_interval, 0.5)
            self.assertEqual(manager.settings.kuaishou.timeout, 10)

    def test_set_coerces_float_runtime_settings(self):
        """float 类型的平台运行参数应支持通过配置管理器持久化。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("xiaohongshu", "request_interval", "2.5")
            manager.set("xiaohongshu", "detail_request_interval", "0.8")

            reloaded = ConfigManager(config_path)

            self.assertEqual(reloaded.get("xiaohongshu", "request_interval"), 2.5)
            self.assertEqual(reloaded.get("xiaohongshu", "detail_request_interval"), 0.8)

    def test_invalid_config_file_is_backed_up_and_reset(self):
        """验证 `test_invalid_config_file_is_backed_up_and_reset` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{bad json", encoding="utf-8")

            manager = ConfigManager(str(config_path))

            backups = list(Path(temp_dir).glob("config.json.bak.*"))
            self.assertTrue(backups)
            self.assertIsNotNone(manager.last_load_error)
            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))

    def test_set_and_get_keep_integer_values_consistent_after_reload(self):
        """验证 `test_set_and_get_keep_integer_values_consistent_after_reload` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("download", "max_concurrent", "6")

            reloaded = ConfigManager(config_path)

        self.assertEqual(reloaded.get("download", "max_concurrent"), 6)

    def test_get_set_are_safe_under_concurrent_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            errors: list[Exception] = []

            def worker(value: int) -> None:
                try:
                    for _ in range(10):
                        manager.set("download", "max_concurrent", value)
                        self.assertIsInstance(manager.get("download", "max_concurrent"), int)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(value,)) for value in (2, 3, 4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

            self.assertEqual(errors, [])
            self.assertIn(manager.get("download", "max_concurrent"), {2, 3, 4})

    def test_temp_save_directory_is_normalized_back_to_default_download_dir(self):
        """被临时目录污染的保存路径在加载配置时应自动回落到规范目录。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            polluted_save_dir = Path(temp_dir) / "tmp-persisted-downloads"
            config_path.write_text(
                (
                    "{"
                    f"\"common\":{{\"save_directory\":\"{str(polluted_save_dir).replace('\\', '\\\\')}\"}}"
                    "}"
                ),
                encoding="utf-8",
            )

            manager = ConfigManager(str(config_path))

            self.assertEqual(manager.get("common", "save_directory"), DEFAULT_DOWNLOAD_DIR)

    def test_save_ui_state_accepts_non_qt_buffers(self):
        """验证配置层保存 UI 状态时不再依赖 Qt 类型。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            manager.save_ui_state(
                geometry=b"\xaa\x55",
                state=bytearray(b"\x10\x20"),
                main_splitter=memoryview(b"\x01\x02"),
                right_splitter="beef",
                is_fs=True,
            )

            self.assertEqual(manager.get("ui", "geometry"), "aa55")
            self.assertEqual(manager.get("ui", "window_state"), "1020")
            self.assertEqual(manager.get("ui", "main_splitter_state"), "0102")
            self.assertEqual(manager.get("ui", "right_splitter_state"), "beef")
            self.assertTrue(manager.get("ui", "is_fullscreen_mode"))

    def test_save_ui_state_accepts_qbytearray_without_recursive_crash(self):
        """验证 GUI 退出场景下，QByteArray 编码不会递归崩溃。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            manager.save_ui_state(
                geometry=QByteArray(b"\x01\x02"),
                state=QByteArray(b"\x03\x04"),
                main_splitter=QByteArray(b"\x05\x06"),
                right_splitter=QByteArray(b"\x07\x08"),
                is_fs=False,
            )

            self.assertEqual(manager.get("ui", "geometry"), "0102")
            self.assertEqual(manager.get("ui", "window_state"), "0304")
            self.assertEqual(manager.get("ui", "main_splitter_state"), "0506")
            self.assertEqual(manager.get("ui", "right_splitter_state"), "0708")

if __name__ == "__main__":
    unittest.main()
