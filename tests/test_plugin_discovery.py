import types
import unittest
from unittest.mock import patch

from app.core.plugins.base import BasePlugin


class PluginDiscoveryTests(unittest.TestCase):
    def _build_modules(self):
        alpha = types.ModuleType("app.core.plugins.alpha")
        beta = types.ModuleType("app.core.plugins.beta")
        package = types.SimpleNamespace(__path__=["plugins"])

        AlphaPlugin = type(
            "AlphaPlugin",
            (BasePlugin,),
            {"id": "alpha", "name": "Alpha", "sort_order": 20, "__module__": alpha.__name__},
        )
        BetterAlphaPlugin = type(
            "BetterAlphaPlugin",
            (BasePlugin,),
            {"id": "alpha", "name": "Alpha Better", "sort_order": 10, "__module__": beta.__name__},
        )
        BetaPlugin = type(
            "BetaPlugin",
            (BasePlugin,),
            {"id": "beta", "name": "Beta", "sort_order": 5, "__module__": beta.__name__},
        )
        ImportedPlugin = type(
            "ImportedPlugin",
            (BasePlugin,),
            {"id": "imported", "name": "Imported", "sort_order": 1, "__module__": "external.module"},
        )
        MissingIdPlugin = type(
            "MissingIdPlugin",
            (BasePlugin,),
            {"id": "", "name": "NoId", "__module__": alpha.__name__},
        )

        alpha.AlphaPlugin = AlphaPlugin
        alpha.ImportedPlugin = ImportedPlugin
        alpha.MissingIdPlugin = MissingIdPlugin
        beta.BetaPlugin = BetaPlugin
        beta.BetterAlphaPlugin = BetterAlphaPlugin

        modules = {
            "app.core.plugins": package,
            "app.core.plugins.alpha": alpha,
            "app.core.plugins.beta": beta,
        }
        return modules, AlphaPlugin, BetterAlphaPlugin, BetaPlugin

    def test_iter_plugin_classes_filters_infra_and_sorts(self):
        from app.core.plugins.discovery import iter_plugin_classes

        modules, _alpha, better_alpha, beta = self._build_modules()
        module_infos = [
            types.SimpleNamespace(name="_private"),
            types.SimpleNamespace(name="base"),
            types.SimpleNamespace(name="alpha"),
            types.SimpleNamespace(name="beta"),
        ]

        def fake_import(name):
            return modules[name]

        with (
            patch("app.core.plugins.discovery.pkgutil.iter_modules", return_value=module_infos),
            patch("app.core.plugins.discovery.importlib.import_module", side_effect=fake_import),
        ):
            discovered = iter_plugin_classes()

        self.assertEqual(discovered, [beta, better_alpha])

    def test_discover_builtin_plugins_instantiates_classes(self):
        from app.core.plugins.discovery import discover_builtin_plugins

        PluginA = type("PluginA", (BasePlugin,), {"id": "a", "name": "A", "__module__": "m"})
        PluginB = type("PluginB", (BasePlugin,), {"id": "b", "name": "B", "__module__": "m"})

        with patch("app.core.plugins.discovery.iter_plugin_classes", return_value=[PluginA, PluginB]):
            plugins = discover_builtin_plugins()

        self.assertEqual([plugin.id for plugin in plugins], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
