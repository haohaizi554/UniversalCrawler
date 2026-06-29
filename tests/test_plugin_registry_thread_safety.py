import threading
import unittest

from app.core.plugins.base import BasePlugin
from app.core.plugins.registry import PluginRegistry

class _Plugin(BasePlugin):
    def __init__(self, plugin_id: str) -> None:
        self.id = plugin_id
        self.name = plugin_id

class PluginRegistryThreadSafetyTests(unittest.TestCase):
    def test_register_and_read_are_locked(self):
        registry = PluginRegistry(plugins=[])
        errors: list[Exception] = []

        def register(index: int) -> None:
            try:
                registry.register(_Plugin(f"plugin-{index}"))
                registry.get_all_plugins()
                registry.get_plugin(f"plugin-{index}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(len(registry.get_all_plugins()), 20)

if __name__ == "__main__":
    unittest.main()
