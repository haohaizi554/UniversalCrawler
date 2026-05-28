"""测试模块，覆盖 `tests/test_config_settings.py` 对应功能的行为与回归场景。"""

import tempfile
import unittest
from pathlib import Path

from app.config import DEFAULT_USER_AGENT
from app.config.settings import ConfigManager
from app.utils.runtime_paths import resolve_user_file


class ConfigManagerTests(unittest.TestCase):
    """封装 `ConfigManagerTests` 在 `tests/test_config_settings.py` 中承担的核心逻辑。"""
    def test_legacy_theme_value_is_normalized(self):
        """验证 `test_legacy_theme_value_is_normalized` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                fp.write('{"common":{"theme":"light","dark_theme":true}}')

            manager = ConfigManager(config_path)

            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))

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
            self.assertEqual(manager.settings.bilibili.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(manager.settings.kuaishou.user_agent, DEFAULT_USER_AGENT)

    def test_short_video_platform_limits_default_to_twenty(self):
        """验证 `test_short_video_platform_limits_default_to_twenty` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.douyin.max_items, 20)
            self.assertEqual(manager.settings.kuaishou.max_items, 20)

    def test_invalid_config_file_is_backed_up_and_reset(self):
        """验证 `test_invalid_config_file_is_backed_up_and_reset` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{bad json", encoding="utf-8")

            manager = ConfigManager(str(config_path))

            backups = list(Path(temp_dir).glob("config.json.bak.*"))
            self.assertTrue(backups)
            self.assertIsNotNone(manager.last_load_error)
            self.assertEqual(manager.get("common", "theme"), "dark")

    def test_set_and_get_keep_integer_values_consistent_after_reload(self):
        """验证 `test_set_and_get_keep_integer_values_consistent_after_reload` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("download", "max_concurrent", "6")

            reloaded = ConfigManager(config_path)

        self.assertEqual(reloaded.get("download", "max_concurrent"), 6)


if __name__ == "__main__":
    unittest.main()
