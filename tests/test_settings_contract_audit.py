"""Cross-frontend settings wiring and dynamic localization regressions."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config.settings import AppSettings
from app.services.frontend_settings_adapter import platform_settings_rows
from app.ui.localization import tr
from app.web.controller_config_service import WebControllerConfigService


class SettingsContractAuditTests(unittest.TestCase):
    def test_gui_preserves_explicit_zero_retry_setting(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "pages"
            / "active_downloads_page.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("self.retry_combo.currentData() or 3", source)
        self.assertNotIn("options.get(\"max_retries\") or 3", source)

    def test_dynamic_day_options_translate_without_exact_catalog_entries(self) -> None:
        self.assertEqual(tr("7 天（推荐）", "en-US"), "7 days (Recommended)")
        self.assertEqual(tr("30 天", "en-US"), "30 days")
        self.assertEqual(tr("7 天（推荐）", "zh-TW"), "7 天（推薦）")

    def test_every_editable_platform_snapshot_field_is_allowed_by_config_api(self) -> None:
        plugins = [
            SimpleNamespace(id=plugin_id, name=plugin_id)
            for plugin_id in ("douyin", "xiaohongshu", "kuaishou", "bilibili", "missav")
        ]
        rows = platform_settings_rows(
            AppSettings().to_dict(),
            plugins=plugins,
            auth_status_provider=lambda _plugin_id, _auth: {
                "auth_status": "未认证",
                "auth_detail": "",
                "auth_cookie_file": "",
            },
        )

        for row in rows:
            editable_keys = []
            if row["count_editable"]:
                editable_keys.append(row["count_config_key"])
            if row["timeout_editable"]:
                editable_keys.append(row["timeout_config_key"])
            if row["proxy_editable"]:
                editable_keys.append(row["proxy_config_key"])
            if row["proxy_custom_allowed"]:
                editable_keys.append("proxy_url")

            for key in editable_keys:
                with self.subTest(platform=row["id"], key=key):
                    self.assertTrue(
                        WebControllerConfigService.is_web_config_allowed(row["id"], key),
                        f"settings snapshot exposes {row['id']}.{key}, but PUT /api/config rejects it",
                    )


if __name__ == "__main__":
    unittest.main()
