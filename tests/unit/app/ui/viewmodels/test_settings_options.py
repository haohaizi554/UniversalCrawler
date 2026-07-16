import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QComboBox

from app.ui.viewmodels.settings_options import (
    compact_proxy_options,
    current_combo_int_value,
    current_combo_value,
    normalize_combo_options,
    platform_proxy_policy,
    proxy_endpoint_from_port,
    proxy_port_text,
)


class SettingsOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_normalize_combo_options_keeps_value_label_and_current(self):
        options = [{"value": "1", "label": "1 day"}, ("3", "3 days"), "7"]

        self.assertEqual(
            normalize_combo_options(options, current="5"),
            [("5", "5"), ("1", "1 day"), ("3", "3 days"), ("7", "7")],
        )

    def test_proxy_port_text_accepts_common_endpoint_forms(self):
        self.assertEqual(proxy_port_text("http://127.0.0.1:7890"), "7890")
        self.assertEqual(proxy_port_text("user:pass@127.0.0.1:7891/path"), "7891")
        self.assertEqual(proxy_port_text("Clash Verge (7897)"), "7897")
        self.assertEqual(proxy_port_text("7899"), "7899")

    def test_proxy_endpoint_from_port_normalizes_short_inputs(self):
        self.assertEqual(proxy_endpoint_from_port("7890"), "http://127.0.0.1:7890")
        self.assertEqual(proxy_endpoint_from_port("127.0.0.1:7890"), "http://127.0.0.1:7890")
        self.assertEqual(proxy_endpoint_from_port("socks5://127.0.0.1:7891"), "socks5://127.0.0.1:7891")

    def test_compact_proxy_options_uses_short_labels_without_losing_values(self):
        options = [
            {"value": "系统代理", "label": "系统代理"},
            {"value": "自定义", "label": "自定义 HTTP/SOCKS5 端点"},
            {"value": "http://127.0.0.1:7890", "label": "Clash (7890)"},
        ]

        self.assertEqual(
            compact_proxy_options(options),
            [
                {"value": "系统代理", "label": "系统代理"},
                {"value": "自定义", "label": "自定义"},
                {"value": "http://127.0.0.1:7890", "label": "Clash"},
            ],
        )

    def test_current_combo_value_reads_data_and_edit_text(self):
        combo = QComboBox()
        self.addCleanup(combo.deleteLater)
        combo.addItem("Three", 3)
        combo.setCurrentIndex(0)
        self.assertEqual(current_combo_value(combo), "3")
        self.assertEqual(current_combo_int_value(combo), 3)

        combo.setEditable(True)
        combo.setEditText("custom")
        self.assertEqual(current_combo_value(combo), "custom")
        self.assertEqual(current_combo_int_value(combo, fallback=9), 9)

    def test_platform_proxy_policy_only_allows_known_custom_platforms(self):
        self.assertTrue(platform_proxy_policy("missav", "MissAV")["editable"])
        policy = platform_proxy_policy("bilibili", "Bilibili")
        self.assertFalse(policy["editable"])
        self.assertIn("系统代理", policy["tooltip"])
