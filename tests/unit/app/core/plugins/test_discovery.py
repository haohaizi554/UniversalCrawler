"""Tests for SPI-based plugin discovery."""

import types
import unittest
from unittest.mock import patch

from app.core.plugins.base import BasePlugin

class PluginDiscoveryTests(unittest.TestCase):
    def _make_plugin_class(self, pid, name, sort_order=1000):
        return type(
            f"{name}Plugin",
            (BasePlugin,),
            {"id": pid, "name": name, "sort_order": sort_order, "__module__": "test_module"},
        )

    def setUp(self):
        # Save clean SPI registry
        self._saved = dict(BasePlugin._subclasses)
        BasePlugin._subclasses = {}

    def tearDown(self):
        BasePlugin._subclasses = self._saved

    def test_iter_plugin_classes_filters_infra_and_sorts(self):
        """SPI-based discovery replaces old pkgutil-based discovery."""
        from app.core.plugins.discovery import iter_plugin_classes
        from app.core.plugins.base import BasePlugin as BP

        # Create test plugin classes
        alpha = self._make_plugin_class("alpha", "Alpha", 20)
        beta = self._make_plugin_class("beta", "Beta", 15)
        gamma = self._make_plugin_class("gamma", "Gamma", 10)

        # Manually register in SPI (simulates what __init_subclass__ does)
        BP._subclasses = {"alpha": alpha, "beta": beta, "gamma": gamma}

        # Also add a few builtin-like entries (will be ignored by mock)
        BP._subclasses["douyin"] = self._make_plugin_class("douyin", "抖音", 10)
        BP._subclasses["bilibili"] = self._make_plugin_class("bilibili", "Bilibili", 40)

        # Patch discovery sub-functions to return empty lists so only
        # our test classes come through.
        with (
            patch("app.core.plugins.discovery.discover_builtin_plugins", return_value=[alpha, beta, gamma]),
            patch("app.core.plugins.discovery.discover_entry_point_plugins", return_value=[]),
            patch("app.core.plugins.discovery.discover_external_plugins", return_value=[]),
        ):
            discovered = iter_plugin_classes()

        # Sort order: gamma(10), beta(15), alpha(20)
        self.assertEqual([c.id for c in discovered], ["gamma", "beta", "alpha"])

    def test_discover_builtin_plugins_instantiates_classes(self):
        from app.core.plugins.discovery import discover_builtin_plugins

        PluginA = self._make_plugin_class("a", "A", 10)
        PluginB = self._make_plugin_class("b", "B", 20)

        with patch("app.core.plugins.discovery.iter_plugin_classes", return_value=[PluginA, PluginB]):
            plugins = discover_builtin_plugins()

        self.assertEqual([plugin.id for plugin in plugins], ["a", "b"])

    def test_spi_auto_registers_subclass(self):
        """Creating a new BasePlugin subclass auto-registers it."""
        # Clean SPI registry for this test
        saved = dict(BasePlugin._subclasses)
        BasePlugin._subclasses = {}
        try:
            plugin_cls = self._make_plugin_class("test_spi", "TestSPI", 5)
            self.assertIn("test_spi", BasePlugin.get_subclasses())
            self.assertIs(BasePlugin.get_subclass("test_spi"), plugin_cls)
        finally:
            BasePlugin._subclasses = saved

    def test_iter_excludes_abstract_base(self):
        """BasePlugin itself is NOT in the SPI registry."""
        self.assertNotIn("base", BasePlugin.get_subclasses())

    def test_discover_builtin_plugin_instances_aggregates(self):
        """discover_builtin_plugin_instances covers all sources."""
        from app.core.plugins.discovery import discover_builtin_plugin_instances

        PluginA = self._make_plugin_class("ext_a", "ExtA", 5)
        PluginB = self._make_plugin_class("ext_b", "ExtB", 10)

        with (
            patch("app.core.plugins.discovery.iter_plugin_classes", return_value=[PluginA, PluginB]),
        ):
            instances = discover_builtin_plugin_instances()

        self.assertEqual(len(instances), 2)
        ids = [p.id for p in instances]
        self.assertIn("ext_a", ids)
        self.assertIn("ext_b", ids)

    def test_entry_point_discovery(self):
        """Entry-point discovery loads plugins from the ucrawl.plugins group."""
        from app.core.plugins.discovery import discover_entry_point_plugins

        PluginEp = self._make_plugin_class("ep_plugin", "EPPlugin", 10)

        class FakeEntryPoint:
            name = "test-ep"
            value = "test_module:PluginEp"

            def load(self):
                return PluginEp

        with patch(
            "app.core.plugins.discovery.importlib.metadata.entry_points",
            return_value=[FakeEntryPoint()],
        ):
            result = discover_entry_point_plugins()

        self.assertEqual(len(result), 1)
        self.assertIs(result[0], PluginEp)

    def test_external_plugin_discovery(self):
        """External directory discovery loads .py plugin files."""
        from app.core.plugins.discovery import discover_external_plugins

        MOD_NAME = "ucrawl_ext_plugin_my_plugin"
        PluginExt = type(
            "ExtFilePlugin",
            (BasePlugin,),
            {"id": "ext_file", "name": "ExtFile", "sort_order": 10, "__module__": MOD_NAME},
        )

        def _fake_import(mod_name):
            m = types.ModuleType(mod_name)
            m.ExtFilePlugin = PluginExt
            return m

        with (
            patch("app.core.plugins.discovery.os.path.isdir", return_value=True),
            patch("app.core.plugins.discovery.os.listdir", return_value=["my_plugin.py"]),
            patch("app.core.plugins.discovery.os.path.getmtime", return_value=100.0),
            patch("app.core.plugins.discovery.importlib.import_module", side_effect=_fake_import),
        ):
            result = discover_external_plugins("/fake/plugins", force=True)

        self.assertEqual(len(result), 1)
        self.assertIs(result[0], PluginExt)

if __name__ == "__main__":
    unittest.main()
