"""插件注册表的注册、查询与冲突处理测试。"""

import importlib
import sys
import unittest
from unittest.mock import Mock

from app.core.plugin_registry import PluginRegistry, registry
from app.core.plugins.run_options import build_missav_proxy_url

class PluginRegistryTests(unittest.TestCase):
    
    def test_registry_exports_expected_plugins(self):
        """验证 `test_registry_exports_expected_plugins` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        plugin_ids = [plugin.id for plugin in registry.get_all_plugins()]
        self.assertEqual(plugin_ids, ["douyin", "xiaohongshu", "kuaishou", "missav", "bilibili"])

    def test_registry_exports_plugin_registry_type(self):
        """验证 `test_registry_exports_plugin_registry_type` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        self.assertIsInstance(registry, PluginRegistry)
        self.assertIsNotNone(registry.get_plugin("missav"))

    def test_get_plugin_returns_none_for_unknown_id(self):
        """验证 `test_get_plugin_returns_none_for_unknown_id` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        self.assertIsNone(registry.get_plugin("unknown"))

    def test_custom_registry_preserves_explicit_empty_plugin_list(self):
        """验证 `test_custom_registry_preserves_explicit_empty_plugin_list` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        custom_registry = PluginRegistry([])

        self.assertEqual(custom_registry.get_all_plugins(), [])

    def test_register_adds_custom_plugin(self):
        """验证 `test_register_adds_custom_plugin` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        plugin = Mock()
        plugin.id = "custom"
        custom_registry = PluginRegistry([])

        custom_registry.register(plugin)

        self.assertIs(custom_registry.get_plugin("custom"), plugin)

    def test_register_rejects_duplicate_plugin_id(self):
        """验证 `test_register_rejects_duplicate_plugin_id` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        plugin = Mock()
        plugin.id = "custom"
        custom_registry = PluginRegistry([])
        custom_registry.register(plugin)

        with self.assertRaises(ValueError):
            custom_registry.register(plugin)

    def test_build_missav_proxy_url_prefers_exact_preset_match(self):
        """验证 `test_build_missav_proxy_url_prefers_exact_preset_match` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        self.assertEqual(build_missav_proxy_url("Clash (7890)"), "http://127.0.0.1:7890")
        self.assertEqual(build_missav_proxy_url("v2rayN (10809)"), "http://127.0.0.1:10809")
        self.assertEqual(build_missav_proxy_url("Clash Verge (7897)"), "http://127.0.0.1:7897")
        self.assertEqual(build_missav_proxy_url("NekoRay (2080)"), "socks5://127.0.0.1:2080")
        self.assertEqual(build_missav_proxy_url("直连"), "")
        self.assertEqual(build_missav_proxy_url("系统代理"), "")

    def test_build_missav_proxy_url_keeps_custom_endpoint_without_false_port_match(self):
        """验证 `test_build_missav_proxy_url_keeps_custom_endpoint_without_false_port_match` 对应场景是否符合预期，供 `PluginRegistryTests` 使用。"""
        self.assertEqual(build_missav_proxy_url("proxy7890.local:9000"), "http://proxy7890.local:9000")

    def test_build_missav_proxy_url_accepts_port_like_custom_inputs(self):
        self.assertEqual(build_missav_proxy_url("7897"), "http://127.0.0.1:7897")
        self.assertEqual(build_missav_proxy_url(":10809"), "http://127.0.0.1:10809")
        self.assertEqual(build_missav_proxy_url("端口 2080"), "http://127.0.0.1:2080")
        self.assertEqual(build_missav_proxy_url("port=7890"), "http://127.0.0.1:7890")
        self.assertEqual(build_missav_proxy_url("Clash 7897"), "http://127.0.0.1:7897")
        self.assertEqual(build_missav_proxy_url("http://127.0.0.1:7890"), "http://127.0.0.1:7890")
        self.assertEqual(build_missav_proxy_url("socks5://127.0.0.1:2080"), "socks5://127.0.0.1:2080")

    def test_plugin_registry_import_does_not_eagerly_load_qt_settings_builders(self):
        """验证核心插件注册链在 import 阶段不主动加载 Qt 设置构建器。"""
        plugin_registry_mod = "app.core.plugin_registry"
        plugins_pkg_mod = "app.core.plugins"
        definitions_mod = "app.core.plugins.definitions"
        settings_builders_mod = "app.core.plugins.settings_builders"
        snapshots = {
            name: sys.modules.get(name)
            for name in (plugin_registry_mod, plugins_pkg_mod, definitions_mod, settings_builders_mod)
        }
        try:
            for name in (settings_builders_mod, definitions_mod, plugins_pkg_mod, plugin_registry_mod):
                sys.modules.pop(name, None)
            importlib.import_module(plugin_registry_mod)
            self.assertNotIn(settings_builders_mod, sys.modules)
        finally:
            for name in (plugin_registry_mod, plugins_pkg_mod, definitions_mod, settings_builders_mod):
                sys.modules.pop(name, None)
            for name, module in snapshots.items():
                if module is not None:
                    sys.modules[name] = module

if __name__ == "__main__":
    unittest.main()
