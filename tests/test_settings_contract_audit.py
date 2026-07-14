"""Cross-frontend settings wiring and dynamic localization regressions."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config.settings import AppSettings
from app.exceptions import ConfigValidationError
from app.services.frontend_settings_adapter import platform_settings_rows
from shared.localization import tr
from app.web.controller_config_service import WebControllerConfigService


class SettingsContractAuditTests(unittest.TestCase):
    def test_every_visible_non_platform_setting_is_allowed_by_web_config_api(self) -> None:
        visible_settings = {
            "common": {
                "save_directory",
                "filename_template",
                "open_after_download",
                "show_browser_window",
                "default_open_mode",
                "theme",
            },
            "download": {
                "max_concurrent",
                "image_respects_concurrency",
                "request_timeout",
                "max_retries",
                "resume_enabled",
                "speed_limit_kb",
                "video_only",
            },
            "playback": {
                "default_player",
                "remember_position",
                "autoplay_next",
                "image_auto_advance_interval_seconds",
                "manual_image_switch",
            },
            "logging": {
                "retention_days",
                "failed_record_retention_days",
                "ui_log_max_display_count",
                "auto_copy_trace_on_error",
            },
            "appearance": {"language", "follow_system", "accent", "scale", "font_size"},
        }

        for section, keys in visible_settings.items():
            for key in keys:
                with self.subTest(section=section, key=key):
                    self.assertTrue(WebControllerConfigService.is_web_config_allowed(section, key))

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

    def test_frontend_setting_action_rejects_hidden_config_fields(self) -> None:
        with self.assertRaises(ConfigValidationError):
            WebControllerConfigService.authorize_frontend_action_payload(
                "update_setting",
                {"section": "douyin", "key": "user_agent", "value": "unsafe"},
                approved_roots=None,
            )


if __name__ == "__main__":
    unittest.main()
