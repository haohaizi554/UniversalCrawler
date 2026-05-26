import unittest
from unittest.mock import Mock

from app.core.plugin_registry import PluginRegistry, registry
from app.core.plugins.settings_builders import build_missav_proxy_url


class PluginRegistryTests(unittest.TestCase):
    def test_registry_exports_expected_plugins(self):
        plugin_ids = [plugin.id for plugin in registry.get_all_plugins()]
        self.assertEqual(plugin_ids, ["douyin", "kuaishou", "missav", "bilibili"])

    def test_registry_exports_plugin_registry_type(self):
        self.assertIsInstance(registry, PluginRegistry)
        self.assertIsNotNone(registry.get_plugin("missav"))

    def test_get_plugin_returns_none_for_unknown_id(self):
        self.assertIsNone(registry.get_plugin("unknown"))

    def test_custom_registry_preserves_explicit_empty_plugin_list(self):
        custom_registry = PluginRegistry([])

        self.assertEqual(custom_registry.get_all_plugins(), [])

    def test_register_adds_custom_plugin(self):
        plugin = Mock()
        plugin.id = "custom"
        custom_registry = PluginRegistry([])

        custom_registry.register(plugin)

        self.assertIs(custom_registry.get_plugin("custom"), plugin)

    def test_register_rejects_duplicate_plugin_id(self):
        plugin = Mock()
        plugin.id = "custom"
        custom_registry = PluginRegistry([])
        custom_registry.register(plugin)

        with self.assertRaises(ValueError):
            custom_registry.register(plugin)

    def test_build_missav_proxy_url_prefers_exact_preset_match(self):
        self.assertEqual(build_missav_proxy_url("Clash (7890)"), "http://127.0.0.1:7890")
        self.assertEqual(build_missav_proxy_url("v2rayN (10809)"), "http://127.0.0.1:10809")

    def test_build_missav_proxy_url_keeps_custom_endpoint_without_false_port_match(self):
        self.assertEqual(build_missav_proxy_url("proxy7890.local:9000"), "http://proxy7890.local:9000")


if __name__ == "__main__":
    unittest.main()
