import json
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config import ConfigManager
from app.core.state import VideoStatus
from app.debug_logger import debug_logger
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.failed_record_store import FailedRecordStore
from app.services.frontend_state_service import FrontendStateService, QUEUE_STATUSES
from app.services.media_metadata_service import MediaMetadata

class FrontendStateServiceTests(unittest.TestCase):
    def test_external_config_change_refreshes_service_snapshot_and_delta(self):
        with TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.json")
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)
            service = FrontendStateService(config_manager=gui_manager)
            seen = threading.Event()
            emitted: list[tuple[str, dict]] = []

            def emit(topic, payload):
                emitted.append((str(topic), dict(payload)))
                service.record_event(topic, payload)

            service.set_frontend_event_emitter(emit)

            def on_change(payload):
                if payload.get("external"):
                    seen.set()

            gui_manager.subscribe("config.changed", on_change)
            before_version = service.get_snapshot()["version"]
            try:
                web_manager.set_batch(
                    {
                        "common": {"theme": "dark"},
                        "appearance": {"accent": "purple"},
                    }
                )
                self.assertTrue(seen.wait(timeout=2))

                snapshot = service.get_snapshot(sections=frozenset({"settings_snapshot"}))
                appearance = snapshot["settings_snapshot"]["外观设置"]
                self.assertEqual("dark", appearance["theme"])
                self.assertEqual("purple", appearance["accent"])
                delta = service.get_delta(before_version)
                self.assertIn("settings_snapshot", delta["changed_sections"])
                self.assertIn("settings.update", {topic for topic, _payload in emitted})
            finally:
                service.destroy()

    def test_external_config_change_notifies_bound_gui_window(self):
        with TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.json")
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)
            window = SimpleNamespace(_on_external_config_changed=Mock())
            service = FrontendStateService(
                controller=SimpleNamespace(window=window),
                config_manager=gui_manager,
            )
            service._gui_runtime_invoker = Mock()

            try:
                web_manager.set("appearance", "accent", "purple")
                deadline = time.monotonic() + 2
                while not window._on_external_config_changed.called and time.monotonic() < deadline:
                    time.sleep(0.02)

                window._on_external_config_changed.assert_called()
                service._gui_runtime_invoker.invoke_and_wait.assert_not_called()
                payload = window._on_external_config_changed.call_args.args[0]
                self.assertEqual("appearance", payload["section"])
                self.assertEqual("accent", payload["key"])
            finally:
                service.destroy()

    def test_gui_and_web_services_sync_all_setting_groups_without_exit_overwrite(self):
        with TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.json")
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)
            gui_service = FrontendStateService(config_manager=gui_manager)
            web_service = FrontendStateService(config_manager=web_manager)
            gui_seen = threading.Event()
            web_seen = threading.Event()

            gui_manager.subscribe(
                "config.changed",
                lambda payload: gui_seen.set() if payload.get("external") else None,
            )
            web_manager.subscribe(
                "config.changed",
                lambda payload: web_seen.set() if payload.get("external") else None,
            )

            try:
                gui_updates = (
                    ("update_basic_setting", {"key": "theme", "value": "dark"}),
                    ("update_setting", {"section": "appearance", "key": "accent", "value": "purple"}),
                    ("update_setting", {"section": "download", "key": "request_timeout", "value": 90}),
                    ("update_setting", {"section": "playback", "key": "default_player", "value": "system_default"}),
                    ("update_setting", {"section": "logging", "key": "retention_days", "value": 3}),
                    ("update_setting", {"section": "bilibili", "key": "max_pages", "value": 2}),
                )
                for action, payload in gui_updates:
                    self.assertEqual("ok", gui_service.handle_action(action, payload)["status"])

                self.assertTrue(web_seen.wait(timeout=2))
                deadline = time.monotonic() + 2
                while web_manager.get("bilibili", "max_pages") != 2 and time.monotonic() < deadline:
                    time.sleep(0.02)

                self.assertEqual("dark", web_manager.get("common", "theme"))
                self.assertEqual("purple", web_manager.get("appearance", "accent"))
                self.assertEqual(90, web_manager.get("download", "request_timeout"))
                self.assertEqual("system_default", web_manager.get("playback", "default_player"))
                self.assertEqual(3, web_manager.get("logging", "retention_days"))
                self.assertEqual(2, web_manager.get("bilibili", "max_pages"))

                gui_seen.clear()
                web_updates = (
                    ("update_basic_setting", {"key": "theme", "value": "light"}),
                    ("update_setting", {"section": "appearance", "key": "scale", "value": "110%"}),
                    ("update_setting", {"section": "download", "key": "request_timeout", "value": 120}),
                    ("update_setting", {"section": "playback", "key": "autoplay_next", "value": False}),
                    ("update_setting", {"section": "logging", "key": "retention_days", "value": 7}),
                    ("update_setting", {"section": "bilibili", "key": "max_pages", "value": 3}),
                )
                for action, payload in web_updates:
                    self.assertEqual("ok", web_service.handle_action(action, payload)["status"])

                self.assertTrue(gui_seen.wait(timeout=2))
                deadline = time.monotonic() + 2
                while gui_manager.get("bilibili", "max_pages") != 3 and time.monotonic() < deadline:
                    time.sleep(0.02)

                self.assertEqual("light", gui_manager.get("common", "theme"))
                self.assertEqual("110%", gui_manager.get("appearance", "scale"))
                self.assertEqual(120, gui_manager.get("download", "request_timeout"))
                self.assertFalse(gui_manager.get("playback", "autoplay_next"))
                self.assertEqual(7, gui_manager.get("logging", "retention_days"))
                self.assertEqual(3, gui_manager.get("bilibili", "max_pages"))

                gui_manager.save_ui_state(b"geometry", b"state", b"main", b"right", False)
                reloaded = ConfigManager(config_path)
                self.assertEqual("light", reloaded.get("common", "theme"))
                self.assertEqual("110%", reloaded.get("appearance", "scale"))
                self.assertEqual(120, reloaded.get("download", "request_timeout"))
                self.assertFalse(reloaded.get("playback", "autoplay_next"))
                self.assertEqual(7, reloaded.get("logging", "retention_days"))
                self.assertEqual(3, reloaded.get("bilibili", "max_pages"))
            finally:
                gui_service.destroy()
                web_service.destroy()

    def test_snapshot_exposes_all_required_sections(self):
        service = FrontendStateService()
        snapshot = service.get_snapshot(mock=True)

        for key in (
            "queue_items",
            "active_downloads",
            "completed_items",
            "failed_items",
            "log_items",
            "settings_snapshot",
            "settings_contract",
            "download_options",
            "toolbox_items",
            "toolbox_recent_items",
            "app_status",
        ):
            self.assertIn(key, snapshot)

    def test_settings_contract_exposes_group_order(self):
        service = FrontendStateService()
        contract = service.get_snapshot(mock=True)["settings_contract"]

        self.assertIsInstance(contract.get("group_order"), list)
        self.assertGreater(len(contract["group_order"]), 0)
        self.assertIn("group_descriptions", contract)
        self.assertIsInstance(contract["group_descriptions"], dict)
        self.assertIn("group_hints", contract)
        self.assertIsInstance(contract["group_hints"], dict)
        self.assertIn("\u57fa\u7840\u8bbe\u7f6e", contract["group_order"])
        self.assertIn("\u57fa\u7840\u8bbe\u7f6e", contract["group_descriptions"])
        self.assertIn("\u57fa\u7840\u8bbe\u7f6e", contract["group_hints"])
        self.assertIsInstance(contract["group_descriptions"]["\u57fa\u7840\u8bbe\u7f6e"], str)
        self.assertIsInstance(contract["group_hints"]["\u57fa\u7840\u8bbe\u7f6e"], str)
        self.assertIn("\u5916\u89c2\u8bbe\u7f6e", contract["group_order"])
    def test_toolbox_items_include_shared_detail_contract(self):
        snapshot = FrontendStateService().get_snapshot(mock=True)

        first_tool = snapshot["toolbox_items"][0]

        self.assertIn("icon_file", first_tool)
        self.assertIn("input_example", first_tool)
        self.assertIn("output_example", first_tool)
        self.assertIn("toolbox_recent_items", snapshot)

    def test_basic_settings_snapshot_uses_persisted_defaults_and_backend_options(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            basic = service.settings_snapshot()["\u57fa\u7840\u8bbe\u7f6e"]

            self.assertEqual(basic["filename_template"], "current")
            self.assertEqual(basic["filename_template_label"], "\u9ed8\u8ba4")
            self.assertFalse(basic["open_after_download"])
            self.assertTrue(basic["show_browser_window"])
            self.assertEqual(basic["default_open_mode"], "builtin_player")
            self.assertEqual(basic["default_open_mode_label"], "\u5185\u7f6e\u64ad\u653e\u5668")
            self.assertIn("filename_template", basic["_options"])
            self.assertIn("default_open_mode", basic["_options"])
            open_mode_values = {option["value"] for option in basic["_options"]["default_open_mode"]}
            self.assertEqual(open_mode_values, {"builtin_player", "system_default"})
            self.assertNotIn("open_directory", open_mode_values)

    def test_settings_snapshot_exposes_option_contracts(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            snapshot = service.settings_snapshot()

            download_options = snapshot["下载设置"]["_options"]
            logging_options = snapshot["日志设置"]["_options"]
            appearance_options = snapshot["外观设置"]["_options"]
            playback = snapshot["播放设置"]
            platforms = snapshot["平台设置"]
            self.assertIn("max_concurrent", download_options)
            self.assertEqual(snapshot["下载设置"]["max_concurrent"], 3)
            self.assertFalse(snapshot["下载设置"]["image_respects_concurrency"])
            self.assertIn({"value": "3", "label": "3（推荐）"}, download_options["max_concurrent"])
            self.assertIn({"value": "0", "label": "无限制"}, download_options["speed_limit_kb"])
            self.assertIn("retention_days", logging_options)
            self.assertIn("failed_record_retention_days", logging_options)
            self.assertEqual(snapshot["日志设置"]["retention_days"], 1)
            self.assertEqual(snapshot["日志设置"]["failed_record_retention_days"], 7)
            self.assertNotIn("level", snapshot["日志设置"])
            self.assertNotIn("cleanup_old_logs_on_start", snapshot["日志设置"])
            self.assertIn({"value": "1", "label": "1 天（推荐）"}, logging_options["retention_days"])
            self.assertIn(
                {"value": "7", "label": "7 天（推荐）"},
                logging_options["failed_record_retention_days"],
            )
            self.assertNotIn("hardware_acceleration", playback)
            self.assertNotIn("builtin_player_enabled", playback)
            self.assertEqual(playback["image_auto_advance_interval_seconds"], 5)
            self.assertIn("image_auto_advance_interval_seconds", playback["_options"])
            self.assertIn(
                {"value": "5", "label": "5 秒（推荐）"},
                playback["_options"]["image_auto_advance_interval_seconds"],
            )
            self.assertIn({"value": "zh-CN", "label": "简体中文（推荐）"}, appearance_options["language"])
            self.assertTrue(all("count_options" in row for row in platforms))
            self.assertTrue(all("timeout_config_key" in row for row in platforms))
            self.assertTrue(all("timeout_options" in row for row in platforms))
            self.assertTrue(
                any(
                    option["value"] == "20" and option["label"]
                    for row in platforms
                    for option in row["count_options"]
                )
            )
            self.assertTrue(any("v2rayN (10809)" == option["value"] for row in platforms for option in row["proxy_options"]))

    def test_platform_settings_distinguish_pages_videos_and_custom_proxy(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            platforms = service.settings_snapshot()["平台设置"]
            bilibili = next(row for row in platforms if row["id"] == "bilibili")
            xiaohongshu = next(row for row in platforms if row["id"] == "xiaohongshu")
            missav = next(row for row in platforms if row["id"] == "missav")

            self.assertEqual(bilibili["count_config_key"], "max_pages")
            self.assertEqual(bilibili["count_unit"], "pages")
            self.assertEqual(bilibili["default_count"], 1)
            self.assertEqual([option["value"] for option in bilibili["count_options"]], ["1", "2", "3", "5", "9999"])
            self.assertTrue(any("页" in option["label"] for option in bilibili["count_options"]))
            self.assertEqual(xiaohongshu["count_config_key"], "max_items")
            self.assertEqual(xiaohongshu["count_unit"], "notes")
            self.assertEqual([option["value"] for option in xiaohongshu["count_options"]], ["10", "20", "30", "50", "9999"])
            self.assertTrue(any("篇笔记" in option["label"] for option in xiaohongshu["count_options"]))
            self.assertEqual(missav["count_config_key"], "max_items")
            self.assertEqual(missav["count_unit"], "videos")
            self.assertEqual([option["value"] for option in missav["count_options"]], ["10", "20", "30", "50", "9999"])
            self.assertTrue(missav["count_editable"])
            stale_video = FrontendStateService._platform_count_contract("douyin", {"max_items": 100})
            stale_note = FrontendStateService._platform_count_contract("xiaohongshu", {"max_items": 100})
            stale_page = FrontendStateService._platform_count_contract("bilibili", {"max_pages": 20})
            self.assertEqual(stale_video["value"], 20)
            self.assertEqual(stale_note["value"], 20)
            self.assertEqual(stale_page["value"], 1)
            self.assertNotIn("100", [option["value"] for option in stale_video["options"]])
            self.assertTrue(any("个视频" in option["label"] for option in missav["count_options"]))
            self.assertEqual(missav["timeout_config_key"], "timeout")
            self.assertEqual(missav["default_timeout"], 60)
            self.assertTrue(missav["timeout_editable"])
            self.assertTrue(any(option["value"] == "120" for option in missav["timeout_options"]))
            self.assertEqual(missav["proxy_config_key"], "proxy_app")
            self.assertTrue(missav["proxy_custom_allowed"])

    def test_mock_snapshot_uses_deterministic_missav_custom_proxy(self):
        snapshot = FrontendStateService.mock_snapshot()
        missav = next(row for row in snapshot["settings_snapshot"]["平台设置"] if row["id"] == "missav")

        self.assertEqual(missav["proxy"], "自定义")
        self.assertTrue(missav["proxy_custom_active"])
        self.assertEqual(missav["proxy_custom_value"], "http://127.0.0.1:7890")

    def test_missav_custom_proxy_keeps_select_value_and_normalizes_url(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            select_result = service.handle_action(
                "update_setting",
                {"section": "missav", "key": "proxy_app", "value": "自定义"},
            )
            url_result = service.handle_action(
                "update_setting",
                {"section": "missav", "key": "proxy_url", "value": "7897"},
            )

            self.assertEqual(select_result["status"], "ok")
            self.assertEqual(url_result["status"], "ok")
            self.assertEqual(manager.get("missav", "proxy_app"), "自定义")
            self.assertEqual(manager.get("missav", "proxy_url"), "http://127.0.0.1:7897")
            missav = next(row for row in service.settings_snapshot()["平台设置"] if row["id"] == "missav")
            self.assertEqual(missav["proxy"], "自定义")
            self.assertEqual(missav["proxy_custom_value"], "http://127.0.0.1:7897")

    def test_platform_auth_status_reads_cookie_files(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            cookie_file = Path(temp_dir) / "dy_auth.json"
            cookie_file.write_text(json.dumps({"cookies": [{"name": "sessionid_ss", "value": "ok"}]}), encoding="utf-8")
            manager.set("auth", "douyin_cookie_file", str(cookie_file))
            service = FrontendStateService(config_manager=manager)

            douyin = next(row for row in service.settings_snapshot()["平台设置"] if row["id"] == "douyin")

            self.assertEqual(douyin["auth_status"], "已认证")
            self.assertIn("sessionid_ss", douyin["auth_detail"])

    def test_refresh_platform_auth_status_emits_settings_delta(self):
        service = FrontendStateService()
        service.get_snapshot(sections={"settings_snapshot", "settings_contract"})
        base_version = service.frontend_version

        result = service.handle_action("refresh_platform_auth_status", {"force": True})
        delta = service.get_delta(base_version, sections={"settings_snapshot", "settings_contract"})

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["refreshed"])
        self.assertIn("settings_snapshot", delta["changed_sections"])
        self.assertIn("settings_contract", delta["changed_sections"])
        self.assertTrue(any(event["topic"] == "settings.platform_auth" for event in delta["events"]))

    def test_refresh_platform_auth_status_rejects_string_boolean(self):
        service = FrontendStateService()

        result = service.handle_action("refresh_platform_auth_status", {"force": "false"})

        self.assertEqual(result["status"], "error")
        self.assertIn("boolean", result["message"])


    def test_update_basic_directory_accepts_quoted_file_path_and_persists_json(self):
        with TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(str(config_file))
            service = FrontendStateService(config_manager=manager)
            target_file = Path(temp_dir) / "nested" / "safe-target.png"

            result = service.handle_action(
                "update_basic_setting",
                {"key": "download_directory", "value": f'"{target_file}"'},
            )

            expected_dir = str(target_file.parent.resolve(strict=False))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["directory"], expected_dir)
            self.assertTrue(target_file.parent.is_dir())
            self.assertEqual(manager.get("common", "save_directory"), expected_dir)
            self.assertEqual(ConfigManager(str(config_file)).get("common", "save_directory"), expected_dir)
            delta = service.get_delta(0, sections={"settings_snapshot"})
            self.assertIn("settings.update", {event.get("topic") for event in delta.get("events", [])})

    def test_update_basic_settings_rejects_invalid_open_mode(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            result = service.handle_action(
                "update_basic_setting",
                {"key": "default_open_mode", "value": "external_magic"},
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(manager.get("common", "default_open_mode"), "builtin_player")

    def test_update_basic_theme_disables_follow_system_in_backend_action(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("appearance", "follow_system", True)
            service = FrontendStateService(config_manager=manager)

            result = service.handle_action("update_basic_setting", {"key": "theme", "value": "dark"})

            self.assertEqual(result["status"], "ok")
            self.assertEqual(manager.get("common", "theme"), "dark")
            self.assertFalse(manager.get("appearance", "follow_system"))

    def test_update_basic_theme_from_system_palette_keeps_follow_system(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("appearance", "follow_system", True)
            service = FrontendStateService(config_manager=manager)

            result = service.handle_action("update_basic_setting", {"key": "theme", "value": "dark", "manual": False})

            self.assertEqual(result["status"], "ok")
            self.assertEqual(manager.get("common", "theme"), "dark")
            self.assertTrue(manager.get("appearance", "follow_system"))

    def test_manual_theme_update_is_one_cross_section_config_commit(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("appearance", "follow_system", True)
            service = FrontendStateService(config_manager=manager)
            record_event = Mock(wraps=service.record_event)
            service.record_event = record_event  # type: ignore[method-assign]

            result = service.handle_action(
                "update_basic_setting",
                {"key": "theme", "value": "dark", "manual": True},
            )

            self.assertEqual(result["status"], "ok")
            self.assertFalse(manager.get("appearance", "follow_system"))
            self.assertEqual(manager.get("common", "theme"), "dark")
            settings_events = [
                call
                for call in record_event.call_args_list
                if call.args and call.args[0] == "settings.update"
            ]
            self.assertEqual(len(settings_events), 1)
            self.assertEqual(len(settings_events[0].args[1]["changes"]), 2)

    def test_update_basic_last_source_persists_from_backend_action(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            result = service.handle_action("update_basic_setting", {"key": "last_source", "value": "douyin"})

            self.assertEqual(result["status"], "ok")
            self.assertEqual(manager.get("common", "last_source"), "douyin")
            self.assertEqual(ConfigManager(str(Path(temp_dir) / "config.json")).get("common", "last_source"), "douyin")

    def test_update_setting_hot_loads_extended_sections_and_persists(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            updates = [
                {"section": "download", "key": "max_retries", "value": 0},
                {"section": "download", "key": "speed_limit_kb", "value": "2048"},
                {"section": "playback", "key": "default_player", "value": "system_default"},
                {"section": "playback", "key": "image_auto_advance_interval_seconds", "value": 10},
                {"section": "logging", "key": "retention_days", "value": 3},
                {"section": "logging", "key": "failed_record_retention_days", "value": 14},
                {"section": "appearance", "key": "accent", "value": "green"},
                {"section": "appearance", "key": "language", "value": "zh-TW"},
                {"section": "appearance", "key": "theme", "value": "dark"},
            ]

            for payload in updates:
                result = service.handle_action("update_setting", payload)
                self.assertEqual(result["status"], "ok", payload)

            snapshot = service.settings_snapshot()
            reloaded = ConfigManager(str(Path(temp_dir) / "config.json"))

            self.assertEqual(snapshot["下载设置"]["max_retries"], 0)
            self.assertEqual(snapshot["下载设置"]["speed_limit_kb"], 2048)
            self.assertEqual(snapshot["播放设置"]["default_player"], "system_default")
            self.assertEqual(snapshot["播放设置"]["image_auto_advance_interval_seconds"], 10)
            self.assertEqual(snapshot["日志设置"]["retention_days"], 3)
            self.assertEqual(snapshot["日志设置"]["failed_record_retention_days"], 14)
            self.assertEqual(snapshot["外观设置"]["accent"], "green")
            self.assertEqual(snapshot["外观设置"]["language"], "zh-TW")
            self.assertEqual(snapshot["外观设置"]["theme"], "dark")
            self.assertEqual(reloaded.get("download", "max_retries"), 0)
            self.assertEqual(reloaded.get("playback", "default_player"), "system_default")
            self.assertEqual(reloaded.get("playback", "image_auto_advance_interval_seconds"), 10)
            self.assertEqual(reloaded.get("logging", "retention_days"), 3)
            self.assertEqual(reloaded.get("logging", "failed_record_retention_days"), 14)
            self.assertEqual(reloaded.get("appearance", "accent"), "green")
            self.assertEqual(reloaded.get("appearance", "language"), "zh-TW")
            self.assertEqual(reloaded.get("common", "theme"), "dark")

    def test_all_settings_controls_round_trip_through_backend_contract(self):
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(str(config_file))
            service = FrontendStateService(config_manager=manager)

            download_dir = Path(temp_dir) / "downloads-target"
            common_updates = [
                ("update_basic_setting", {"key": "download_directory", "value": str(download_dir)}),
                ("update_basic_setting", {"key": "filename_template", "value": "{platform}_{title}"}),
                ("update_basic_setting", {"key": "open_after_download", "value": True}),
                ("update_basic_setting", {"key": "show_browser_window", "value": False}),
                ("update_basic_setting", {"key": "default_open_mode", "value": "system_default"}),
                ("update_setting", {"section": "common", "key": "theme", "value": "dark"}),
            ]
            download_updates = [
                {"section": "download", "key": "max_concurrent", "value": 5},
                {"section": "download", "key": "image_respects_concurrency", "value": True},
                {"section": "download", "key": "request_timeout", "value": 120},
                {"section": "download", "key": "max_retries", "value": 5},
                {"section": "download", "key": "resume_enabled", "value": False},
                {"section": "download", "key": "speed_limit_kb", "value": "2048"},
                {"section": "download", "key": "video_only", "value": True},
            ]
            playback_updates = [
                {"section": "playback", "key": "default_player", "value": "system_default"},
                {"section": "playback", "key": "remember_position", "value": False},
                {"section": "playback", "key": "autoplay_next", "value": False},
                {"section": "playback", "key": "manual_image_switch", "value": True},
                {"section": "playback", "key": "image_auto_advance_interval_seconds", "value": 10},
            ]
            logging_updates = [
                {"section": "logging", "key": "retention_days", "value": 3},
                {"section": "logging", "key": "failed_record_retention_days", "value": 14},
                {"section": "logging", "key": "ui_log_max_display_count", "value": 500},
                {"section": "logging", "key": "auto_copy_trace_on_error", "value": False},
            ]
            appearance_updates = [
                {"section": "appearance", "key": "follow_system", "value": True},
                {"section": "appearance", "key": "accent", "value": "green"},
                {"section": "appearance", "key": "scale", "value": "110%"},
                {"section": "appearance", "key": "font_size", "value": "large"},
                {"section": "appearance", "key": "language", "value": "zh-TW"},
            ]

            for action, payload in common_updates:
                result = service.handle_action(action, payload)
                self.assertEqual(result["status"], "ok", payload)
            for payload in download_updates + playback_updates + logging_updates + appearance_updates:
                result = service.handle_action("update_setting", payload)
                self.assertEqual(result["status"], "ok", payload)

            platform_snapshot = service.settings_snapshot()["\u5e73\u53f0\u8bbe\u7f6e"]
            expected_platform_values: dict[tuple[str, str], object] = {}
            for row in platform_snapshot:
                section = row["id"]
                count_key = row.get("count_config_key")
                count_options = row.get("count_options") or []
                if count_key and count_options:
                    current = str(row.get("default_count"))
                    candidate = next(
                        (str(option["value"]) for option in count_options if str(option.get("value")) != current),
                        str(count_options[0]["value"]),
                    )
                    result = service.handle_action(
                        "update_setting",
                        {"section": section, "key": count_key, "value": candidate},
                    )
                    self.assertEqual(result["status"], "ok", (section, count_key, candidate))
                    expected_platform_values[(section, count_key)] = int(candidate)

                timeout_key = row.get("timeout_config_key")
                if timeout_key:
                    result = service.handle_action(
                        "update_setting",
                        {"section": section, "key": timeout_key, "value": "90"},
                    )
                    self.assertEqual(result["status"], "ok", (section, timeout_key))
                    expected_platform_values[(section, timeout_key)] = 90

            result = service.handle_action(
                "update_setting",
                {"section": "missav", "key": "proxy_app", "value": "自定义"},
            )
            self.assertEqual(result["status"], "ok")
            result = service.handle_action(
                "update_setting",
                {"section": "missav", "key": "proxy_url", "value": "7897"},
            )
            self.assertEqual(result["status"], "ok")

            snapshot = service.settings_snapshot()
            basic = snapshot["\u57fa\u7840\u8bbe\u7f6e"]
            self.assertEqual(basic["download_directory"], str(download_dir.resolve(strict=False)))
            self.assertEqual(basic["filename_template"], "{platform}_{title}")
            self.assertTrue(basic["open_after_download"])
            self.assertFalse(basic["show_browser_window"])
            self.assertEqual(basic["default_open_mode"], "system_default")

            download = snapshot["\u4e0b\u8f7d\u8bbe\u7f6e"]
            self.assertEqual(download["max_concurrent"], 5)
            self.assertTrue(download["image_respects_concurrency"])
            self.assertEqual(download["request_timeout"], 120)
            self.assertEqual(download["max_retries"], 5)
            self.assertFalse(download["resume_enabled"])
            self.assertEqual(download["speed_limit_kb"], 2048)
            self.assertTrue(download["video_only"])

            playback = snapshot["\u64ad\u653e\u8bbe\u7f6e"]
            self.assertEqual(playback["default_player"], "system_default")
            self.assertFalse(playback["remember_position"])
            self.assertFalse(playback["autoplay_next"])
            self.assertTrue(playback["manual_image_switch"])
            self.assertEqual(playback["image_auto_advance_interval_seconds"], 10)

            logging_cfg = snapshot["\u65e5\u5fd7\u8bbe\u7f6e"]
            self.assertEqual(logging_cfg["retention_days"], 3)
            self.assertEqual(logging_cfg["failed_record_retention_days"], 14)
            self.assertEqual(logging_cfg["ui_log_max_display_count"], 500)
            self.assertFalse(logging_cfg["auto_copy_trace_on_error"])

            appearance = snapshot["\u5916\u89c2\u8bbe\u7f6e"]
            self.assertTrue(appearance["follow_system"])
            self.assertEqual(appearance["theme"], "dark")
            self.assertEqual(appearance["accent"], "green")
            self.assertEqual(appearance["scale"], "110%")
            self.assertEqual(appearance["font_size"], "large")
            self.assertEqual(appearance["language"], "zh-TW")

            platform_rows = {row["id"]: row for row in snapshot["\u5e73\u53f0\u8bbe\u7f6e"]}
            for (section, key), expected in expected_platform_values.items():
                row = platform_rows[section]
                if key == row.get("count_config_key"):
                    self.assertEqual(int(row["default_count"]), expected)
                elif key == row.get("timeout_config_key"):
                    self.assertEqual(int(row["timeout"]), expected)
            missav = platform_rows["missav"]
            self.assertEqual(missav["proxy"], "自定义")
            self.assertEqual(missav["proxy_custom_value"], "http://127.0.0.1:7897")
            self.assertTrue(missav["proxy_custom_active"])

            reloaded = ConfigManager(str(config_file))
            self.assertEqual(reloaded.get("common", "filename_template"), "{platform}_{title}")
            self.assertFalse(reloaded.get("common", "show_browser_window"))
            self.assertEqual(reloaded.get("download", "request_timeout"), 120)
            self.assertEqual(reloaded.get("playback", "manual_image_switch"), True)
            self.assertEqual(reloaded.get("logging", "failed_record_retention_days"), 14)
            self.assertEqual(reloaded.get("logging", "ui_log_max_display_count"), 500)
            self.assertEqual(reloaded.get("appearance", "language"), "zh-TW")
            self.assertEqual(reloaded.get("missav", "proxy_url"), "http://127.0.0.1:7897")

    def test_update_setting_applies_runtime_hooks(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            download_manager = SimpleNamespace(set_runtime_options=Mock())
            controller = SimpleNamespace(_dl_manager=download_manager)
            service = FrontendStateService(controller=controller, config_manager=manager)

            with patch("app.services.frontend_state_service.debug_logger.configure") as configure_logger:
                result = service.handle_action(
                    "update_setting",
                    {"section": "download", "key": "request_timeout", "value": 120},
                )
                self.assertEqual(result["status"], "ok")
                download_manager.set_runtime_options.assert_called()
                runtime_payload = download_manager.set_runtime_options.call_args.kwargs
                self.assertEqual(runtime_payload["request_timeout"], 120)

                download_manager.set_runtime_options.reset_mock()
                result = service.handle_action(
                    "update_setting",
                    {"section": "download", "key": "video_only", "value": True},
                )
                self.assertEqual(result["status"], "ok")
                download_manager.set_runtime_options.assert_called()
                runtime_payload = download_manager.set_runtime_options.call_args.kwargs
                self.assertTrue(runtime_payload["video_only"])
                self.assertTrue(manager.get("download", "video_only"))

                result = service.handle_action(
                    "update_setting",
                    {"section": "logging", "key": "ui_log_max_display_count", "value": 500},
                )
                self.assertEqual(result["status"], "ok")
                configure_logger.assert_called()
                self.assertFalse(configure_logger.call_args.kwargs["cleanup_old_logs"])
                self.assertEqual(service.app_state.log_buffer.maxlen, 500)

                result = service.handle_action(
                    "update_setting",
                    {"section": "logging", "key": "retention_days", "value": 3},
                )
                self.assertEqual(result["status"], "ok")
                self.assertTrue(configure_logger.call_args.kwargs["cleanup_old_logs"])
                self.assertEqual(configure_logger.call_args.kwargs["retention_days"], 3)

                request_prune = Mock()
                service.failed_record_store.request_prune = request_prune  # type: ignore[method-assign]
                result = service.handle_action(
                    "update_setting",
                    {"section": "logging", "key": "failed_record_retention_days", "value": 14},
                )
                self.assertEqual(result["status"], "ok")
                request_prune.assert_called_with(14)

    def test_update_setting_applies_runtime_and_records_change_exactly_once(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            download_manager = SimpleNamespace(set_runtime_options=Mock())
            controller = SimpleNamespace(_dl_manager=download_manager)
            service = FrontendStateService(controller=controller, config_manager=manager)
            runtime_apply = Mock(wraps=service._apply_runtime_setting)
            record_event = Mock(wraps=service.record_event)
            service._apply_runtime_setting = runtime_apply  # type: ignore[method-assign]
            service.record_event = record_event  # type: ignore[method-assign]

            result = service.handle_action(
                "update_setting",
                {"section": "download", "key": "request_timeout", "value": 120},
            )
            self.assertTrue(manager.event_bus.wait_for_async_idle(timeout=1.0))

            self.assertEqual(result["status"], "ok")
            runtime_apply.assert_called_once_with("download", "request_timeout", 120)
            settings_events = [
                call
                for call in record_event.call_args_list
                if call.args and call.args[0] == "settings.update"
            ]
            self.assertEqual(len(settings_events), 1)

    def test_update_setting_reports_observer_runtime_failure_after_persisting(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            download_manager = SimpleNamespace(
                set_runtime_options=Mock(side_effect=RuntimeError("runtime apply exploded")),
            )
            controller = SimpleNamespace(_dl_manager=download_manager)
            service = FrontendStateService(controller=controller, config_manager=manager)

            result = service.handle_action(
                "update_setting",
                {"section": "download", "key": "request_timeout", "value": 120},
            )

            self.assertEqual(result["status"], "error")
            self.assertIn("persisted but runtime apply failed", result["message"])
            self.assertIn("runtime apply exploded", result["message"])
            self.assertEqual(manager.get("download", "request_timeout"), 120)
            download_manager.set_runtime_options.assert_called_once()

    def test_update_download_options_reports_observer_runtime_failure_after_persisting(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            download_manager = SimpleNamespace(
                set_runtime_options=Mock(side_effect=RuntimeError("runtime apply exploded")),
            )
            controller = SimpleNamespace(_dl_manager=download_manager)
            service = FrontendStateService(controller=controller, config_manager=manager)

            result = service.handle_action(
                "update_download_options",
                {"max_concurrent": 4, "max_retries": 3},
            )

            self.assertEqual(result["status"], "error")
            self.assertIn("persisted but runtime apply failed", result["message"])
            self.assertIn("runtime apply exploded", result["message"])
            self.assertEqual(
                manager.get("download", "max_concurrent"),
                result["data"]["max_concurrent"],
            )
            download_manager.set_runtime_options.assert_called_once()

    def test_update_setting_waits_for_gui_runtime_failure_after_persisting(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            window = SimpleNamespace(
                _apply_playback_runtime_settings=Mock(
                    side_effect=RuntimeError("GUI runtime apply exploded"),
                ),
            )
            controller = SimpleNamespace(window=window)
            service = FrontendStateService(controller=controller, config_manager=manager)
            service._gui_runtime_invoker = SimpleNamespace(
                invoke=lambda callback: callback(),
                invoke_and_wait=lambda callback, **_kwargs: callback(),
            )

            with patch.object(service, "_is_qt_gui_thread", return_value=False):
                result = service.handle_action(
                    "update_setting",
                    {"section": "playback", "key": "autoplay_next", "value": False},
                )

            self.assertEqual(result["status"], "error")
            self.assertIn("persisted but runtime apply failed", result["message"])
            self.assertIn("GUI runtime apply exploded", result["message"])
            self.assertFalse(manager.get("playback", "autoplay_next"))
            window._apply_playback_runtime_settings.assert_called_once_with()

    def test_update_setting_reports_gui_runtime_ack_timeout_after_persisting(self):
        from PyQt6.QtCore import QObject
        from app.ui.gui_runtime_adapter import QtGuiRuntimeAdapter

        class RuntimeWindow(QObject):
            def __init__(self):
                super().__init__()
                self.apply_playback = Mock()

            def _apply_playback_runtime_settings(self):
                self.apply_playback()

        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            window = RuntimeWindow()
            service = FrontendStateService(
                controller=SimpleNamespace(window=window),
                config_manager=manager,
                gui_runtime_adapter=QtGuiRuntimeAdapter(),
            )
            service._gui_runtime_invoker = SimpleNamespace(
                invoke_and_wait=Mock(
                    side_effect=TimeoutError("GUI runtime apply acknowledgement timed out")
                ),
            )

            with patch.object(service, "_is_qt_gui_thread", return_value=False):
                result = service.handle_action(
                    "update_setting",
                    {"section": "playback", "key": "autoplay_next", "value": False},
                )

            self.assertEqual(result["status"], "error")
            self.assertIn("acknowledgement timed out", result["message"])
            self.assertFalse(manager.get("playback", "autoplay_next"))
            window.apply_playback.assert_not_called()

    def test_config_runtime_failure_capture_is_thread_local(self):
        service = FrontendStateService()
        barrier = threading.Barrier(2)
        captured: dict[str, list[tuple[str, str, Exception]]] = {}

        def _capture(name: str, *, fail: bool) -> None:
            with service._capture_config_runtime_failures() as failures:
                barrier.wait(timeout=2)
                if fail:
                    service._record_config_runtime_failure(
                        "playback",
                        "autoplay_next",
                        RuntimeError(f"{name} failed"),
                    )
                barrier.wait(timeout=2)
                captured[name] = list(failures)

        failed_thread = threading.Thread(target=_capture, args=("failed",), kwargs={"fail": True})
        healthy_thread = threading.Thread(target=_capture, args=("healthy",), kwargs={"fail": False})
        failed_thread.start()
        healthy_thread.start()
        failed_thread.join(timeout=3)
        healthy_thread.join(timeout=3)

        self.assertFalse(failed_thread.is_alive())
        self.assertFalse(healthy_thread.is_alive())
        self.assertEqual(len(captured["failed"]), 1)
        self.assertEqual(str(captured["failed"][0][2]), "failed failed")
        self.assertEqual(captured["healthy"], [])

    def test_config_commit_dispatches_gui_playback_and_platform_runtime_once(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            window = SimpleNamespace(
                _apply_playback_runtime_settings=Mock(),
                _apply_platform_runtime_setting=Mock(),
            )
            controller = SimpleNamespace(window=window)
            service = FrontendStateService(controller=controller, config_manager=manager)

            playback_result = service.handle_action(
                "update_setting",
                {"section": "playback", "key": "autoplay_next", "value": False},
            )
            platform_result = service.handle_action(
                "update_setting",
                {"section": "bilibili", "key": "max_pages", "value": 2},
            )

            self.assertEqual(playback_result["status"], "ok")
            self.assertEqual(platform_result["status"], "ok")
            window._apply_playback_runtime_settings.assert_called_once_with()
            window._apply_platform_runtime_setting.assert_called_once_with("bilibili", "max_pages", 2)

    def test_logging_retention_cleanup_runs_on_frontend_service_initialization(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("logging", "retention_days", 3)

            with patch("app.services.frontend_state_service.debug_logger.configure") as configure_logger:
                FrontendStateService(config_manager=manager)

            configure_logger.assert_called()
            self.assertEqual(configure_logger.call_args.kwargs["retention_days"], 3)
            self.assertTrue(configure_logger.call_args.kwargs["cleanup_old_logs"])

    def test_update_setting_rejects_invalid_extended_option(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            result = service.handle_action(
                "update_setting",
                {"section": "playback", "key": "default_player", "value": "external_magic"},
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(manager.get("playback", "default_player"), "builtin_player")

    def test_video_items_are_bucketed_for_seven_page_contract(self):
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = "⏳ 等待中"
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = "⏳ 下载中..."
        active.progress = 42
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "✅ 本地"
        completed.progress = 100
        completed.local_path = __file__
        failed = VideoItem(url="https://example.com/f", title="failed", source="douyin")
        failed.status = "❌ 失败"
        failed.meta["trace_id"] = "trace-123"
        failed.meta["download_error"] = "网络超时"
        controller = SimpleNamespace(videos={item.id: item for item in (queued, active, completed, failed)}, _dl_manager=None, current_spider=None)

        snapshot = FrontendStateService(controller).get_snapshot()

        self.assertEqual([item["id"] for item in snapshot["queue_items"]], [queued.id])
        self.assertEqual(snapshot["queue_items"][0]["status"], "待下载")
        self.assertIn(snapshot["queue_items"][0]["status"], QUEUE_STATUSES)
        self.assertEqual([item["id"] for item in snapshot["active_downloads"]], [active.id])
        self.assertEqual([item["id"] for item in snapshot["completed_items"]], [completed.id])
        self.assertEqual([item["id"] for item in snapshot["failed_items"]], [failed.id])
        self.assertEqual(snapshot["failed_items"][0]["trace_id"], "trace-123")

    def test_active_item_synthesizes_rich_events_when_downloader_events_are_sparse(self):
        item = VideoItem(url="https://example.com/a.mp4", title="active", source="douyin")
        item.progress = 67
        item.meta.update(
            {
                "speed": "1.4 MB/s",
                "chunks_done": 67,
                "chunks_total": 100,
                "remaining_time": "00:13",
                "write_status": "\u6b63\u5728\u5199\u5165",
                "merge_status": "\u7b49\u5f85\u5408\u5e76",
                "trace_id": "trace-active",
                "events": [{"time": "10:00:00", "message": "started"}],
            }
        )

        payload = FrontendStateService()._active_item(item)
        messages = [event["message"] for event in payload["events"]]

        self.assertEqual(payload["chunk_progress_label"], "67% (67/100)")
        self.assertEqual(payload["speed_trend_label"], "1.4 MB/s")
        detail_fields = {field["label"]: field["value"] for field in payload["detail_fields"]}
        self.assertEqual(detail_fields["标题"], "active")
        self.assertEqual(detail_fields["平台"], "抖音")
        self.assertIn("保存目录", detail_fields)
        self.assertEqual(detail_fields["输出文件名"], "active")
        self.assertEqual(detail_fields["来源链接"], "https://example.com/a.mp4")
        self.assertEqual(detail_fields["Trace ID"], "trace-active")
        self.assertGreaterEqual(len(messages), 4)
        self.assertEqual(messages[0], "started")
        self.assertTrue(all(event["time"] == "10:00:00" for event in payload["events"]))
        self.assertTrue(any("1.4 MB/s" in message for message in messages))
        self.assertTrue(any("Trace ID" in message for message in messages))

    def test_active_item_uses_stable_metadata_time_for_derived_events(self):
        item = VideoItem(url="https://example.com/a.mp4", title="active", source="douyin")
        item.progress = 10
        item.meta.update({"created_at": "2026-06-21 20:12:35"})

        payload = FrontendStateService()._active_item(item)

        self.assertTrue(payload["events"])
        self.assertTrue(all(event["time"] == "20:12:35" for event in payload["events"]))

    def test_active_item_caches_generated_event_time_when_metadata_is_missing(self):
        item = VideoItem(url="https://example.com/a.mp4", title="active", source="douyin")
        item.progress = 10
        service = FrontendStateService()

        first = service._active_item(item)
        item.progress = 20
        second = service._active_item(item)

        first_times = {event["time"] for event in first["events"]}
        second_times = {event["time"] for event in second["events"]}
        self.assertEqual(len(first_times), 1)
        self.assertEqual(first_times, second_times)
        self.assertNotIn("--:--:--", first_times)

    def test_completed_terminal_state_wins_over_stale_active_worker_id(self):
        item = VideoItem(url="https://example.com/bili.m4s", title="bili done", source="bilibili")
        item.status = VideoStatus.COMPLETED.label
        item.progress = 100
        item.local_path = __file__
        item.meta.update({"speed": "940.9 KB/s", "speed_bps": 963482})
        manager = SimpleNamespace(workers=[SimpleNamespace(video=item)], _workers_lock=threading.RLock())
        controller = SimpleNamespace(videos={item.id: item}, _dl_manager=manager, current_spider=None)

        snapshot = FrontendStateService(controller).get_snapshot()

        self.assertEqual(snapshot["active_downloads"], [])
        self.assertEqual([row["id"] for row in snapshot["completed_items"]], [item.id])
        self.assertEqual(snapshot["completed_items"][0]["download_speed"], "940.9 KB/s")

    def test_completed_item_uses_cached_local_media_metadata(self):
        class FakeMetadataService:
            def cached(self, _path):
                return MediaMetadata(duration="00:01:23", resolution="1920 x 1080", format="MP4", content_type="video")

            def ensure_probe(self, *_args, **_kwargs):
                raise AssertionError("cache hit should not schedule probe")

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "done.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            item.meta["completed_at"] = "2026-06-21 04:49:33"
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["completed_at"], "2026-06-21 04:49:33")
        self.assertEqual(payload["completed_at_table"], "06-21 04:49")
        self.assertEqual(payload["duration"], "00:01:23")
        self.assertEqual(payload["resolution"], "1920 x 1080")
        self.assertEqual(payload["format"], "MP4")
        self.assertEqual(payload["filename"], "done.mp4")
        self.assertEqual(payload["save_dir"], str(path.parent))
        self.assertEqual(payload["content_type"], "video")
        self.assertFalse(payload["metadata_pending"])

    def test_completed_item_marks_metadata_pending_without_blocking(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, _callback):
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pending.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="pending", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["duration"], "--")
        self.assertEqual(payload["resolution"], "--")
        self.assertTrue(payload["metadata_pending"])

    def test_completed_item_keeps_metadata_pending_during_probe_cooldown(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, _callback):
                return False

            def is_probe_deferred(self, _path):
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cooldown.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="cooldown", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["duration"], "--")
        self.assertEqual(payload["resolution"], "--")
        self.assertTrue(payload["metadata_pending"])

    def test_completed_snapshot_limits_metadata_probe_fanout(self):
        class FakeMetadataService:
            def __init__(self):
                self.calls = 0

            def cached(self, _path):
                return None

            def is_probe_deferred(self, _path):
                return False

            def ensure_probe(self, _path, _callback):
                self.calls += 1
                return True

        with TemporaryDirectory() as temp_dir:
            videos = {}
            for index in range(8):
                path = Path(temp_dir) / f"{index}.mp4"
                path.write_bytes(b"media")
                item = VideoItem(url="", title=f"done-{index}", source="local")
                item.status = VideoStatus.COMPLETED.label
                item.progress = 100
                item.local_path = str(path)
                videos[item.id] = item
            metadata = FakeMetadataService()
            service = FrontendStateService(SimpleNamespace(videos=videos), media_metadata_service=metadata)
            service.METADATA_PROBES_PER_SNAPSHOT = 3

            snapshot = service.get_snapshot(sections=frozenset({"completed_items"}))

        self.assertEqual(metadata.calls, 3)
        self.assertEqual(len(snapshot["completed_items"]), 8)
        self.assertTrue(all(item["metadata_pending"] for item in snapshot["completed_items"]))

    def test_completed_snapshot_queues_metadata_probes_over_budget(self):
        class FakeMetadataService:
            def __init__(self):
                self.calls: list[str] = []

            def cached(self, _path):
                return None

            def is_probe_deferred(self, _path):
                return False

            def ensure_probe(self, path, _callback):
                self.calls.append(Path(path).name)
                return True

        class FakeTimer:
            def __init__(self, _delay, callback):
                self.callback = callback
                self.daemon = False
                self.started = False
                self.cancelled = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

        with TemporaryDirectory() as temp_dir, patch("app.services.frontend_state_service.threading.Timer", FakeTimer):
            videos = {}
            for index in range(3):
                path = Path(temp_dir) / f"{index}.mp4"
                path.write_bytes(b"media")
                item = VideoItem(url="", title=f"done-{index}", source="local")
                item.status = VideoStatus.COMPLETED.label
                item.progress = 100
                item.local_path = str(path)
                videos[item.id] = item
            metadata = FakeMetadataService()
            service = FrontendStateService(SimpleNamespace(videos=videos), media_metadata_service=metadata)
            service.METADATA_PROBES_PER_SNAPSHOT = 1

            snapshot = service.get_snapshot(sections=frozenset({"completed_items"}))

            self.assertEqual(metadata.calls, ["0.mp4"])
            self.assertEqual(len(snapshot["completed_items"]), 3)
            self.assertEqual(len(service._metadata_probe_queue), 2)

            service._drain_queued_metadata_probes()
            self.assertEqual(metadata.calls, ["0.mp4", "1.mp4"])
            self.assertEqual(len(service._metadata_probe_queue), 1)

            service._drain_queued_metadata_probes()
            self.assertEqual(metadata.calls, ["0.mp4", "1.mp4", "2.mp4"])
            self.assertEqual(service._metadata_probe_queue, {})

    def test_cancel_metadata_probe_queue_invalidates_started_timer(self):
        class FakeTimer:
            def __init__(self, _delay, callback):
                self.callback = callback
                self.daemon = False
                self.started = False
                self.cancelled = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

        with patch("app.services.frontend_state_service.threading.Timer", FakeTimer):
            service = FrontendStateService()
            retry = Mock(return_value=False)
            service._retry_completed_metadata_probe = retry

            service._queue_completed_metadata_probe("video-1", "D:/media.mp4")
            timer = service._metadata_probe_queue_timer
            self.assertIsNotNone(timer)

            service._cancel_metadata_probe_queue()
            timer.callback()

        self.assertTrue(timer.cancelled)
        self.assertEqual(service._metadata_probe_queue, {})
        self.assertIsNone(service._metadata_probe_queue_timer)
        retry.assert_not_called()

    def test_destroy_closes_metadata_probe_queue_and_suppresses_late_callbacks(self):
        class FakeTimer:
            def __init__(self, _delay, callback):
                self.callback = callback
                self.daemon = False
                self.started = False
                self.cancelled = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

        with patch("app.services.frontend_state_service.threading.Timer", FakeTimer):
            events: list[tuple[str, dict]] = []
            service = FrontendStateService(frontend_event_emitter=lambda topic, payload: events.append((topic, payload)))
            retry = Mock(return_value=False)
            service._retry_completed_metadata_probe = retry

            service._queue_completed_metadata_probe("video-1", "D:/media.mp4")
            timer = service._metadata_probe_queue_timer
            self.assertIsNotNone(timer)

            service.destroy()
            service._queue_completed_metadata_probe("video-2", "D:/later.mp4")
            service._emit_frontend_event("videos.metadata", {"video_id": "video-1"})
            timer.callback()

        self.assertTrue(timer.cancelled)
        self.assertTrue(service._metadata_probe_queue_closed)
        self.assertEqual(service._metadata_probe_queue, {})
        self.assertIsNone(service._metadata_probe_queue_timer)
        self.assertEqual(events, [])
        retry.assert_not_called()

    def test_destroy_shuts_down_owned_media_metadata_service(self):
        class FakeMetadataService:
            def __init__(self) -> None:
                self.shutdown_called = False

            def shutdown(self) -> None:
                self.shutdown_called = True

        with patch("app.services.frontend_state_service.MediaMetadataService", FakeMetadataService):
            service = FrontendStateService()
            metadata_service = service.media_metadata_service
            service.destroy()

        self.assertTrue(metadata_service.shutdown_called)

    def test_frontend_event_emitter_keeps_shared_app_state_refresh(self):
        app_state = AppState()
        local_events: list[dict] = []
        app_state.event_bus.subscribe("app_state.changed", lambda payload: local_events.append(payload))
        emitted: list[tuple[str, dict]] = []
        service = FrontendStateService(
            app_state=app_state,
            frontend_event_emitter=lambda topic, payload: emitted.append((topic, dict(payload))),
        )

        service._emit_frontend_event("videos.metadata", {"video_id": "video-1", "metadata": True})
        delta = service.get_delta(0)

        self.assertEqual(emitted, [("videos.metadata", {"video_id": "video-1", "metadata": True})])
        self.assertIn({"topic": "videos.metadata", "video_id": "video-1", "metadata": True}, local_events)
        self.assertIn("completed_items", delta["changed_sections"])

    def test_destroy_cancels_owned_app_state_log_timer(self):
        class FakeTimer:
            def __init__(self, _delay, callback):
                self.callback = callback
                self.daemon = False
                self.started = False
                self.cancelled = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

            def is_alive(self):
                return True

        with patch("app.services.app_state.threading.Timer", FakeTimer):
            service = FrontendStateService()
            service.record_log("batched log")
            timer = service.app_state._log_publish_timer
            self.assertIsNotNone(timer)

            service.destroy()

        self.assertTrue(timer.cancelled)
        self.assertIsNone(service.app_state._log_publish_timer)

    def test_destroyed_service_ignores_late_mutating_calls(self):
        service = FrontendStateService()
        service.destroy()
        version = service.frontend_version
        item = VideoItem(url="https://example.com", title="late", source="local")

        service.record_log("late log")
        service.record_event("videos.update", {"video_id": item.id, "progress": 42})
        service.upsert_video(item)
        service.set_running(True)
        action_result = service.handle_action("run_tool", {"tool_id": "metadata_viewer"})
        metadata_result = service.update_completed_metadata(item.id, {"duration": "00:00:01"})

        self.assertEqual(service.frontend_version, version)
        self.assertEqual(service.app_state.get_log_buffer(), [])
        self.assertEqual(service.app_state.snapshot_videos(), {})
        self.assertIsNone(service.app_state._log_publish_timer)
        self.assertEqual(action_result["status"], "error")
        self.assertEqual(metadata_result["status"], "error")

    def test_completed_item_quality_label_does_not_block_real_resolution_probe(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, _callback):
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quality-only.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="quality only", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            item.meta.update({"duration": "00:00:22", "quality": "1080p"})
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["resolution"], "--")
        self.assertTrue(payload["metadata_pending"])

    def test_completed_metadata_probe_emits_completed_refresh_event(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, callback):
                callback(MediaMetadata(duration="00:01:05", resolution="720 x 1280", format="MP4", content_type="video"))
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "done.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            events: list[tuple[str, dict]] = []
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                media_metadata_service=FakeMetadataService(),
                frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
            )

            service._completed_item(item)
            refreshed = service._completed_item(item)

        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": True})])
        self.assertEqual(refreshed["duration"], "00:01:05")
        self.assertEqual(refreshed["resolution"], "720 x 1280")

    def test_empty_completed_metadata_probe_is_not_marked_useful(self):
        class FakeMetadataService:
            EMPTY_RETRY_SECONDS = 60.0

            def cached(self, _path):
                return None

            def ensure_probe(self, _path, callback):
                callback(MediaMetadata(format="MP4", content_type="video"))
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            events: list[tuple[str, dict]] = []
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                media_metadata_service=FakeMetadataService(),
                frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
            )

            payload = service._completed_item(item)
            service.invalidate_refresh_caches()

        self.assertEqual(payload["duration"], "--")
        self.assertEqual(payload["resolution"], "--")
        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": False})])

    def test_empty_completed_metadata_probe_eventually_stops_pending_state(self):
        class FakeMetadataService:
            EMPTY_RETRY_SECONDS = 60.0

            def __init__(self):
                self.calls = 0

            def cached(self, _path):
                return None

            def is_probe_deferred(self, _path):
                return False

            def ensure_probe(self, _path, callback):
                self.calls += 1
                callback(MediaMetadata(format="MP4", content_type="video"))
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            events: list[tuple[str, dict]] = []
            metadata = FakeMetadataService()
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                media_metadata_service=metadata,
                frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
            )
            service.METADATA_EMPTY_MAX_RETRIES = 1

            payload = service._completed_item(item)
            second_payload = service._completed_item(item)

        self.assertEqual(payload["duration"], "--")
        self.assertEqual(payload["resolution"], "--")
        self.assertFalse(payload["metadata_pending"])
        self.assertEqual(second_payload["duration"], "--")
        self.assertEqual(second_payload["resolution"], "--")
        self.assertFalse(second_payload["metadata_pending"])
        self.assertEqual(metadata.calls, 1)
        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": False, "exhausted": True})])

    def test_completed_metadata_path_compare_treats_slashes_as_equivalent(self):
        self.assertTrue(
            FrontendStateService._same_local_path(
                r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads\a.mp4",
                "D:/desktop/project/UniversalCrawlerProplus/user_data/Downloads/a.mp4",
            )
        )

    def test_update_completed_metadata_backfills_missing_values_only(self):
        item = VideoItem(url="", title="done", source="local")
        item.status = VideoStatus.COMPLETED.label
        item.progress = 100
        item.meta.update({"duration": "--", "resolution": "1080p", "format": "MP4"})
        events: list[tuple[str, dict]] = []
        service = FrontendStateService(
            SimpleNamespace(videos={item.id: item}),
            frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
        )

        result = service.update_completed_metadata(
            item.id,
            {"duration_ms": 208000, "width": 1920, "height": 1080, "format": "WEBM"},
            source="test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["changed"])
        self.assertEqual(item.meta["duration"], "00:03:28")
        self.assertEqual(item.meta["resolution"], "1920 x 1080")
        self.assertEqual(item.meta["format"], "MP4")
        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": True, "source": "test"})])

    def test_log_items_use_trace_id_without_task_id_column(self):
        service = FrontendStateService()
        service.record_log("download failed", level="ERROR", source="Downloader", trace_id="trace-1")

        item = service.get_snapshot()["log_items"][-1]

        self.assertIn("trace_id", item)
        self.assertNotIn("task_id", item)

    def test_log_event_payload_is_persisted_with_trace_id(self):
        service = FrontendStateService()

        service.record_event(
            "log",
            {
                "message": "解析完成",
                "level": "INFO",
                "source": "bilibili",
                "trace_id": "bilibili-crawl-1",
            },
        )

        item = service.get_snapshot()["log_items"][-1]
        self.assertEqual(item["message_summary"], "解析完成")
        self.assertEqual(item["trace_id"], "bilibili-crawl-1")
        self.assertEqual(item["source"], "bilibili")
        self.assertEqual(item["platform_id"], "bilibili")
        self.assertEqual(item["level_display"], "INFO")
        self.assertIn("source_display", item)

    def test_log_items_respect_ui_max_display_count_for_memory_buffer(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("logging", "ui_log_max_display_count", 500)
            service = FrontendStateService(config_manager=manager)

            for index in range(700):
                service.record_log(f"log-{index:03d}", source="Test")

            items = service.get_snapshot(sections=frozenset({"log_items"}))["log_items"]

        self.assertEqual(len(items), 500)
        self.assertEqual(items[0]["message_summary"], "log-200")
        self.assertEqual(items[-1]["message_summary"], "log-699")

    def test_log_items_respect_ui_max_display_count_for_file_cache(self):
        original_latest_file = debug_logger.latest_file
        original_is_main_process = debug_logger._is_main_process
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("logging", "ui_log_max_display_count", 500)
            latest_file = Path(temp_dir) / "latest_debug.log"
            latest_file.write_text(
                "\n".join(
                    f"[2026-06-30 10:{index // 60:02d}:{index % 60:02d}] [INFO] Test / file-log-{index:03d}"
                    for index in range(700)
                ),
                encoding="utf-8",
            )
            debug_logger.latest_file = latest_file
            debug_logger._is_main_process = False
            try:
                service = FrontendStateService(config_manager=manager)
                service.refresh_file_log_cache()
                items = service.get_snapshot(sections=frozenset({"log_items"}))["log_items"]
            finally:
                debug_logger.latest_file = original_latest_file
                debug_logger._is_main_process = original_is_main_process

        self.assertEqual(len(items), 500)
        self.assertEqual(items[0]["message_summary"], "file-log-200")
        self.assertEqual(items[-1]["message_summary"], "file-log-699")

    def test_max_log_display_limit_does_not_backfill_entire_file_cache(self):
        original_latest_file = debug_logger.latest_file
        original_is_main_process = debug_logger._is_main_process
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("logging", "ui_log_max_display_count", 500)
            latest_file = Path(temp_dir) / "latest_debug.log"
            latest_file.write_text(
                "\n".join(
                    f"[2026-06-30 10:{index // 60:02d}:{index % 60:02d}] [INFO] Test / file-log-{index:04d}"
                    for index in range(2000)
                ),
                encoding="utf-8",
            )
            debug_logger.latest_file = latest_file
            debug_logger._is_main_process = False
            try:
                service = FrontendStateService(config_manager=manager)
                service.refresh_file_log_cache()
                items = service.get_snapshot(sections=frozenset({"log_items"}))["log_items"]
            finally:
                debug_logger.latest_file = original_latest_file
                debug_logger._is_main_process = original_is_main_process

        self.assertEqual(len(items), FrontendStateService.FILE_LOG_BACKFILL_LIMIT)
        self.assertEqual(items[0]["message_summary"], "file-log-1500")
        self.assertEqual(items[-1]["message_summary"], "file-log-1999")

    def test_log_display_limit_increase_keeps_existing_window_without_backfill(self):
        original_latest_file = debug_logger.latest_file
        original_is_main_process = debug_logger._is_main_process
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("logging", "ui_log_max_display_count", 100)
            latest_file = Path(temp_dir) / "latest_debug.log"
            latest_file.write_text(
                "\n".join(
                    f"[2026-06-30 10:{index // 60:02d}:{index % 60:02d}] [INFO] Test / file-log-{index:04d}"
                    for index in range(1000)
                ),
                encoding="utf-8",
            )
            debug_logger.latest_file = latest_file
            debug_logger._is_main_process = False
            try:
                service = FrontendStateService(config_manager=manager)
                service.refresh_file_log_cache()
                initial_items = service.get_snapshot(sections=frozenset({"log_items"}))["log_items"]
                service.handle_action(
                    "update_setting",
                    {"section": "logging", "key": "ui_log_max_display_count", "value": 500},
                )
                expanded_items = service.get_snapshot(sections=frozenset({"log_items"}))["log_items"]
            finally:
                debug_logger.latest_file = original_latest_file
                debug_logger._is_main_process = original_is_main_process

        self.assertEqual(len(initial_items), 100)
        self.assertEqual(len(expanded_items), 100)
        self.assertEqual(expanded_items[0]["message_summary"], "file-log-0900")
        self.assertEqual(expanded_items[-1]["message_summary"], "file-log-0999")

    def test_log_display_limit_update_trims_existing_items(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("logging", "ui_log_max_display_count", 500)
            service = FrontendStateService(config_manager=manager)
            for index in range(500):
                service.record_log(f"log-{index:03d}", source="Test")

            result = service.handle_action(
                "update_setting",
                {"section": "logging", "key": "ui_log_max_display_count", "value": 100},
            )
            items = service.get_snapshot(sections=frozenset({"log_items"}))["log_items"]

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(items), 100)
        self.assertEqual(items[0]["message_summary"], "log-400")
        self.assertEqual(items[-1]["message_summary"], "log-499")

    def test_snapshot_reuses_log_rows_for_failed_and_log_sections(self):
        item = VideoItem(url="https://example.com", title="failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        item.meta["trace_id"] = "trace-failed"
        rows = [
            {
                "time": "2026-07-08 10:00:00",
                "level": "ERROR",
                "source": "Downloader",
                "trace_id": "trace-failed",
                "message": "download failed",
                "message_summary": "download failed",
            }
        ]
        calls = 0
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))

        def log_items() -> list[dict[str, str]]:
            nonlocal calls
            calls += 1
            return list(rows)

        service.log_items = log_items  # type: ignore[method-assign]
        try:
            snapshot = service.get_snapshot(sections=frozenset({"failed_items", "log_items"}))
        finally:
            service.destroy()

        self.assertEqual(calls, 1)
        self.assertEqual(snapshot["log_items"], rows)
        self.assertEqual(snapshot["failed_items"][0]["log_excerpt"], ["download failed"])

    def test_full_snapshot_reuses_log_rows_for_failed_excerpt(self):
        item = VideoItem(url="https://example.com", title="failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        item.meta["trace_id"] = "trace-failed"
        rows = [
            {
                "time": "2026-07-08 10:00:00",
                "level": "ERROR",
                "source": "Downloader",
                "trace_id": "trace-failed",
                "message": "download failed",
                "message_summary": "download failed",
            }
        ]
        calls = 0
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))

        def log_items() -> list[dict[str, str]]:
            nonlocal calls
            calls += 1
            return list(rows)

        service.log_items = log_items  # type: ignore[method-assign]
        try:
            snapshot = service.get_snapshot()
        finally:
            service.destroy()

        self.assertEqual(calls, 1)
        self.assertEqual(snapshot["log_items"], rows)
        self.assertEqual(snapshot["failed_items"][0]["log_excerpt"], ["download failed"])

    def test_failed_item_actions_exclude_retry(self):
        item = VideoItem(url="https://example.com", title="failed", source="douyin")
        item.status = VideoStatus.FAILED.label
        item.meta["error"] = "403"
        item.meta["trace_id"] = "trace-failed"
        item.meta["failed_at"] = "2026-06-22 16:32:23"
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))
        service.record_log("download failed with 403", level="ERROR", source="Downloader", trace_id="trace-failed")

        failed = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]

        self.assertEqual(failed["actions"], ["copy_diagnostics", "delete"])
        self.assertEqual(failed["reason_label"], "链接失败")
        self.assertEqual(failed["reason_icon_file"], "action_trace_link.png")
        self.assertEqual(failed["failed_at_table"], "06-22 16:32")
        self.assertEqual(failed["status_label"], "失败")
        self.assertEqual(failed["status_icon_file"], "status_failed.png")
        self.assertEqual(failed["log_excerpt"], ["download failed with 403"])
        self.assertEqual(failed["log_excerpt_items"][0]["icon_file"], "log_level_error.png")
        self.assertTrue(all(solution.get("icon_file") for solution in failed["solutions"]))

    def test_failed_snapshot_exposes_shared_language_display_projection(self):
        item = VideoItem(url="https://example.com", title="failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        item.meta["error"] = "下载任务失败"
        item.meta["trace_id"] = "trace-failed-projection"
        item.meta["failed_at"] = "2026-07-12 18:34:48"
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            manager.set("appearance", "language", "en-US")
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                config_manager=manager,
            )
            service.record_log(
                "Bilibili 流请求建立成功",
                level="ERROR",
                source="Downloader",
                trace_id="trace-failed-projection",
            )
            try:
                failed = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
            finally:
                service.destroy()

        self.assertEqual(failed["display_language"], "en-US")
        self.assertEqual(failed["reason_detail_display"], "Download task failed")
        self.assertEqual(
            failed["log_excerpt_display_items"][0]["message_display"],
            "Bilibili stream request established",
        )
        self.assertTrue(all("title_display" in solution for solution in failed["solutions_display"]))

    def test_failed_snapshot_keeps_richer_trace_excerpt_when_log_refresh_is_shorter(self):
        # 失败页详情不能因为后续日志缓存短暂只返回最后一条，就把已保存的
        # 完整 trace 摘要覆盖成更短版本。
        item = VideoItem(url="https://example.com", title="failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        item.meta["trace_id"] = "trace-failed"
        item.meta["failed_at"] = "2026-07-09 07:23:34"
        full_rows = [
            {
                "time": "2026-07-09 07:22:01",
                "level": "INFO",
                "source": "BilibiliDownloader",
                "trace_id": "trace-failed",
                "message": "Bilibili 流请求建立成功",
                "message_summary": "Bilibili 流请求建立成功",
            },
            {
                "time": "2026-07-09 07:22:20",
                "level": "WARN",
                "source": "BilibiliDownloader",
                "trace_id": "trace-failed",
                "message": "B站 video 流连接断开，准备断点续传重试",
                "message_summary": "B站 video 流连接断开，准备断点续传重试",
            },
            {
                "time": "2026-07-09 07:23:34",
                "level": "ERROR",
                "source": "Downloader",
                "trace_id": "trace-failed",
                "message": "下载失败: Connection broken",
                "message_summary": "下载失败: Connection broken",
            },
        ]
        short_rows = [full_rows[-1]]
        batches = [full_rows, short_rows]
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))
        service.log_items = lambda: list(batches.pop(0) if batches else short_rows)  # type: ignore[method-assign]
        try:
            first = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
            second = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
        finally:
            service.destroy()

        self.assertEqual(first["log_excerpt"], [row["message"] for row in full_rows])
        self.assertEqual(second["log_excerpt"], [row["message"] for row in full_rows])

    def test_failed_snapshot_queues_structured_sqlite_record(self):
        with TemporaryDirectory() as temp_dir:
            store = FailedRecordStore(db_path=Path(temp_dir) / "failed.sqlite3")
            item = VideoItem(url="https://example.com", title="failed", source="bilibili")
            item.status = VideoStatus.FAILED.label
            item.meta["error"] = "403"
            item.meta["trace_id"] = "trace-failed"
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                failed_record_store=store,
            )
            try:
                failed = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
                self.assertTrue(store.flush(timeout=2))
                rows = store.query(limit=10)
            finally:
                service.destroy()

        self.assertEqual(rows[0]["id"], failed["id"])
        self.assertEqual(rows[0]["title"], failed["title"])
        self.assertEqual(rows[0]["trace_id"], "trace-failed")

    def test_failed_snapshot_deduplicates_unchanged_sqlite_upserts(self):
        class CollectingFailedRecordStore:
            def __init__(self) -> None:
                self.calls: list[list[dict[str, object]]] = []

            def queue_upsert(self, records):
                self.calls.append([dict(record) for record in records])

            def shutdown(self) -> None:
                return None

        store = CollectingFailedRecordStore()
        item = VideoItem(url="https://example.com", title="failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        item.meta["error"] = "403"
        item.meta["trace_id"] = "trace-failed"
        service = FrontendStateService(
            SimpleNamespace(videos={item.id: item}),
            failed_record_store=store,
        )
        try:
            service.get_snapshot(sections=frozenset({"failed_items"}))
            service.get_snapshot(sections=frozenset({"failed_items"}))
        finally:
            service.destroy()

        self.assertEqual(len(store.calls), 1)
        self.assertEqual(store.calls[0][0]["trace_id"], "trace-failed")

    def test_failed_snapshot_requeues_sqlite_upsert_when_failure_changes(self):
        class CollectingFailedRecordStore:
            def __init__(self) -> None:
                self.calls: list[list[dict[str, object]]] = []

            def queue_upsert(self, records):
                self.calls.append([dict(record) for record in records])

            def shutdown(self) -> None:
                return None

        store = CollectingFailedRecordStore()
        item = VideoItem(url="https://example.com", title="failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        item.meta["error"] = "403"
        item.meta["trace_id"] = "trace-failed"
        service = FrontendStateService(
            SimpleNamespace(videos={item.id: item}),
            failed_record_store=store,
        )
        try:
            service.get_snapshot(sections=frozenset({"failed_items"}))
            item.meta["error"] = "500"
            service.get_snapshot(sections=frozenset({"failed_items"}))
        finally:
            service.destroy()

        self.assertEqual(len(store.calls), 2)
        self.assertEqual(store.calls[1][0]["reason"], "500")

    def test_failed_snapshot_uses_persisted_worker_snapshot_when_live_page_empty(self):
        # 当前 AppState 没有失败项时，失败列表仍要显示 SQLite worker 快照；
        # 这是应用重启后失败记录可见性的回归保护。
        with TemporaryDirectory() as temp_dir:
            store = FailedRecordStore(db_path=Path(temp_dir) / "failed.sqlite3")
            store.queue_upsert(
                [
                    {
                        "id": "persisted-failed",
                        "title": "persisted failed",
                        "reason": "network",
                        "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "Failed",
                        "platform": "Bilibili",
                        "trace_id": "trace-persisted",
                    }
                ]
            )
            self.assertTrue(store.flush(timeout=2))
            self.assertEqual(store.records_snapshot()[0]["id"], "persisted-failed")
            service = FrontendStateService(SimpleNamespace(videos={}), failed_record_store=store)
            try:
                with patch.object(store, "query", side_effect=AssertionError("UI must not query SQLite")) as query_mock:
                    snapshot = service.get_snapshot(sections=frozenset({"failed_items", "app_status"}))
            finally:
                service.destroy()

        query_mock.assert_not_called()
        self.assertEqual([item["id"] for item in snapshot["failed_items"]], ["persisted-failed"])
        self.assertEqual(snapshot["failed_items"][0]["trace_id"], "trace-persisted")
        self.assertEqual(snapshot["app_status"]["failed_count"], 1)

    def test_failed_record_refresh_marks_failed_sections_dirty(self):
        class SnapshotFailedRecordStore:
            def __init__(self) -> None:
                self.refresh_callback = None
                self.refresh_requests: list[dict[str, object]] = []
                self._rows = [
                    {
                        "id": "persisted-failed",
                        "title": "persisted failed",
                        "reason": "network",
                        "failed_at": "2026-07-06 12:00:00",
                        "status": "Failed",
                        "platform": "Bilibili",
                        "trace_id": "trace-persisted",
                    }
                ]

            def set_refresh_callback(self, callback):
                self.refresh_callback = callback

            def request_refresh(self, **kwargs):
                self.refresh_requests.append(dict(kwargs))

            def records_snapshot(self, *, limit=None):
                if limit is None:
                    return [dict(row) for row in self._rows]
                return [dict(row) for row in self._rows[:limit]]

            @property
            def snapshot_total_count(self):
                return len(self._rows)

            def shutdown(self) -> None:
                return None

        store = SnapshotFailedRecordStore()
        service = FrontendStateService(SimpleNamespace(videos={}), failed_record_store=store)
        try:
            self.assertEqual(store.refresh_requests, [{"limit": service.FAILED_RECORD_SNAPSHOT_LIMIT}])
            self.assertIsNotNone(store.refresh_callback)
            base_version = service.frontend_version
            store.refresh_callback(1)
            delta = service.get_delta(base_version)
        finally:
            service.destroy()

        self.assertEqual(set(delta["changed_sections"]), {"failed_items", "app_status"})
        self.assertEqual([item["id"] for item in delta["sections"]["failed_items"]], ["persisted-failed"])
        self.assertEqual(delta["sections"]["app_status"]["failed_count"], 1)

    def test_failed_snapshot_keeps_persisted_records_out_when_current_failures_exist(self):
        with TemporaryDirectory() as temp_dir:
            store = FailedRecordStore(db_path=Path(temp_dir) / "failed.sqlite3")
            store.queue_upsert(
                [
                    {
                        "id": "persisted-demo",
                        "title": "Demo",
                        "reason": "network",
                        "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "Failed",
                        "platform": "Bilibili",
                        "trace_id": "trace-123",
                    }
                ]
            )
            self.assertTrue(store.flush(timeout=2))
            current = VideoItem(url="https://example.com/current", title="Current failure", source="bilibili")
            current.status = VideoStatus.FAILED.label
            current.meta["trace_id"] = "trace-current"
            service = FrontendStateService(SimpleNamespace(videos={current.id: current}), failed_record_store=store)
            try:
                snapshot = service.get_snapshot(sections=frozenset({"failed_items", "app_status"}))
            finally:
                service.destroy()

        self.assertEqual([item["title"] for item in snapshot["failed_items"]], ["Current failure"])
        self.assertEqual(snapshot["app_status"]["failed_count"], 1)

    def test_copy_diagnostics_action_returns_trace_id_only(self):
        item = VideoItem(url="https://example.com", title="failed", source="douyin")
        item.meta["trace_id"] = "trace-copy"
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))

        result = service.handle_action("copy_diagnostics", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["text"], "trace-copy")
        self.assertEqual(result["data"]["trace_id"], "trace-copy")

    def test_copy_diagnostics_action_uses_persisted_failed_record_trace(self):
        with TemporaryDirectory() as temp_dir:
            store = FailedRecordStore(db_path=Path(temp_dir) / "failed.sqlite3")
            store.queue_upsert(
                [
                    {
                        "id": "persisted-copy",
                        "title": "Persisted failure",
                        "reason": "network",
                        "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "Failed",
                        "platform": "Bilibili",
                        "trace_id": "trace-persisted-copy",
                    }
                ]
            )
            self.assertTrue(store.flush(timeout=2))
            service = FrontendStateService(SimpleNamespace(videos={}), failed_record_store=store)
            try:
                result = service.handle_action("copy_diagnostics", {"id": "persisted-copy"})
            finally:
                service.destroy()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["text"], "trace-persisted-copy")
        self.assertEqual(result["data"]["trace_id"], "trace-persisted-copy")

    def test_delete_failed_record_action_removes_persisted_record(self):
        with TemporaryDirectory() as temp_dir:
            store = FailedRecordStore(db_path=Path(temp_dir) / "failed.sqlite3")
            store.queue_upsert(
                [
                    {
                        "id": "persisted-delete",
                        "title": "Persisted failure",
                        "reason": "network",
                        "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "Failed",
                        "platform": "Bilibili",
                        "trace_id": "trace-delete",
                    }
                ]
            )
            self.assertTrue(store.flush(timeout=2))
            service = FrontendStateService(SimpleNamespace(videos={}), failed_record_store=store)
            try:
                result = service.handle_action("delete_failed_record", {"id": "persisted-delete"})
                self.assertTrue(store.flush(timeout=2))
                remaining = store.query(limit=10)
            finally:
                service.destroy()

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["deleted"])
        self.assertEqual(remaining, [])

    def test_delete_failed_record_also_removes_the_live_failed_task(self):
        item = VideoItem(url="https://example.com/failed", title="Failed", source="bilibili")
        item.status = VideoStatus.FAILED.label
        controller = SimpleNamespace(
            videos={item.id: item},
            _dl_manager=None,
            _delete_video_sync=Mock(
                return_value=SimpleNamespace(status="ok", deleted=False, error=None)
            ),
        )
        store = Mock()
        store.delete_record.return_value = True
        store.records_snapshot.return_value = []
        store.snapshot_total_count = 0
        service = FrontendStateService(controller, failed_record_store=store)
        try:
            result = service.handle_action("delete_failed_record", {"id": item.id})
        finally:
            service.destroy()

        self.assertEqual(result["status"], "ok")
        controller._delete_video_sync.assert_called_once_with(item.id)
        store.delete_record.assert_called_once_with(item.id)

    def test_clear_failed_records_action_removes_all_persisted_records(self):
        with TemporaryDirectory() as temp_dir:
            store = FailedRecordStore(db_path=Path(temp_dir) / "failed.sqlite3")
            failed_at = datetime.now()
            store.queue_upsert(
                [
                    {
                        "id": "persisted-a",
                        "title": "A",
                        "reason": "network",
                        "failed_at": (failed_at - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    {
                        "id": "persisted-b",
                        "title": "B",
                        "reason": "network",
                        "failed_at": failed_at.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                ]
            )
            self.assertTrue(store.flush(timeout=2))
            service = FrontendStateService(SimpleNamespace(videos={}), failed_record_store=store)
            try:
                result = service.handle_action("clear_failed_records", {})
                self.assertTrue(store.flush(timeout=2))
                remaining = store.query(limit=10)
            finally:
                service.destroy()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["count"], 2)
        self.assertEqual(remaining, [])

    def test_clear_failed_records_also_removes_live_failed_tasks(self):
        failed_items = [
            VideoItem(url=f"https://example.com/{index}", title=f"Failed {index}", source="bilibili")
            for index in range(2)
        ]
        for item in failed_items:
            item.status = VideoStatus.FAILED.label
        controller = SimpleNamespace(
            videos={item.id: item for item in failed_items},
            _dl_manager=None,
            _delete_video_sync=Mock(
                return_value=SimpleNamespace(status="ok", deleted=False, error=None)
            ),
        )
        store = Mock()
        store.clear_records.return_value = 2
        store.records_snapshot.return_value = []
        store.snapshot_total_count = 0
        service = FrontendStateService(controller, failed_record_store=store)
        try:
            result = service.handle_action("clear_failed_records", {})
        finally:
            service.destroy()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            {call.args[0] for call in controller._delete_video_sync.call_args_list},
            {item.id for item in failed_items},
        )

    def test_delete_item_action_reports_controller_delete_error(self):
        controller = SimpleNamespace(
            _delete_video_sync=Mock(
                return_value=SimpleNamespace(
                    status="error",
                    error="permission denied",
                    deleted=False,
                )
            )
        )
        service = FrontendStateService(controller)

        result = service.handle_action("delete_item", {"id": "video-1"})

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "permission denied")
        controller._delete_video_sync.assert_called_once_with("video-1")

    def test_delete_item_action_treats_missing_item_as_idempotent_success(self):
        controller = SimpleNamespace(
            _delete_video_sync=Mock(return_value=SimpleNamespace(status="missing", deleted=False))
        )
        service = FrontendStateService(controller)

        result = service.handle_action("delete_item", {"id": "video-1"})

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["missing"])

    def test_clear_queue_action_uses_controller_queue_handler(self):
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = VideoStatus.PENDING.label
        completed = VideoItem(url="https://example.com/done", title="done", source="douyin")
        completed.status = VideoStatus.COMPLETED.label
        controller = SimpleNamespace(
            videos={queued.id: queued, completed.id: completed},
            _dl_manager=None,
            on_clear_queue=Mock(),
        )
        service = FrontendStateService(controller)

        result = service.handle_action("clear_queue", {})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["video_ids"], [queued.id])
        controller.on_clear_queue.assert_called_once_with()

    def test_clear_queue_action_fallback_removes_only_queue_items(self):
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = VideoStatus.PENDING.label
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = VideoStatus.DOWNLOADING.label
        completed = VideoItem(url="https://example.com/done", title="done", source="douyin")
        completed.status = VideoStatus.COMPLETED.label
        controller = SimpleNamespace(
            videos={queued.id: queued, active.id: active, completed.id: completed},
            _dl_manager=None,
        )
        service = FrontendStateService(controller)

        result = service.handle_action("clear_queue", {})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["count"], 1)
        self.assertNotIn(queued.id, controller.videos)
        self.assertIn(active.id, controller.videos)
        self.assertIn(completed.id, controller.videos)

    def test_open_directory_action_uses_injected_service_boundary(self):
        with TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "done.mp4"
            media_path.write_text("mock", encoding="utf-8")
            item = VideoItem(url="", title="done", source="local")
            item.local_path = str(media_path)
            opener = Mock()
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                directory_opener=opener,
            )

            result = service.handle_action("open_directory", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        opener.assert_called_once_with(str(media_path.parent))

    def test_open_file_action_uses_system_default_file_opener(self):
        with TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "done.mp4"
            media_path.write_text("mock", encoding="utf-8")
            item = VideoItem(url="", title="done", source="local")
            item.local_path = str(media_path)
            service = FrontendStateService(SimpleNamespace(videos={item.id: item}))

            with patch.object(FrontendStateService, "_open_file_path") as opener:
                result = service.handle_action("open_file", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        opener.assert_called_once_with(media_path)

    def test_register_file_associations_action_uses_service_boundary(self):
        association_service = SimpleNamespace(
            register_current_user=Mock(return_value=SimpleNamespace(registered=True, message="")),
            set_current_user_defaults=Mock(
                return_value=SimpleNamespace(
                    defaulted_extensions=(".mp4",),
                    failed_extensions=(),
                    message="",
                )
            ),
            diagnose_current_user=Mock(return_value=SimpleNamespace(available=True, pending_extensions=())),
            open_default_apps_settings=Mock(return_value=True),
        )
        service = FrontendStateService(
            association_service_factory=lambda: association_service,
            executable_path_provider=lambda: r"C:\App\UniversalCrawlerPro.exe",
        )

        result = service.handle_action("register_file_associations", {"include_video": True, "include_image": False})

        self.assertEqual(result["status"], "ok")
        association_service.register_current_user.assert_called_once_with(
            r"C:\App\UniversalCrawlerPro.exe",
            include_video=True,
            include_image=False,
        )
        association_service.set_current_user_defaults.assert_called_once_with(include_video=True, include_image=False)
        association_service.diagnose_current_user.assert_called_once_with(include_video=True, include_image=False)
        association_service.open_default_apps_settings.assert_not_called()
        self.assertEqual(result["data"]["defaulted_extensions"], [".mp4"])

    def test_register_file_associations_defaults_to_video_and_image(self):
        association_service = SimpleNamespace(
            register_current_user=Mock(return_value=SimpleNamespace(registered=True, message="")),
            set_current_user_defaults=Mock(
                return_value=SimpleNamespace(defaulted_extensions=(".mp4",), failed_extensions=(), message="")
            ),
            diagnose_current_user=Mock(return_value=SimpleNamespace(available=True, pending_extensions=())),
            open_default_apps_settings=Mock(return_value=True),
        )
        service = FrontendStateService(
            association_service_factory=lambda: association_service,
            executable_path_provider=lambda: r"C:\App\UniversalCrawlerPro.exe",
        )

        result = service.handle_action("register_file_associations", {"include_video": True})

        self.assertEqual(result["status"], "ok")
        association_service.register_current_user.assert_called_once_with(
            r"C:\App\UniversalCrawlerPro.exe",
            include_video=True,
            include_image=True,
        )
        association_service.set_current_user_defaults.assert_called_once_with(include_video=True, include_image=True)
        association_service.diagnose_current_user.assert_called_once_with(include_video=True, include_image=True)

    def test_register_file_associations_rejects_string_boolean(self):
        association_factory = Mock()
        service = FrontendStateService(association_service_factory=association_factory)

        result = service.handle_action(
            "register_file_associations",
            {"include_video": "false", "include_image": True},
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("boolean", result["message"])
        association_factory.assert_not_called()

    def test_run_tool_rejects_unknown_tool_id(self):
        result = FrontendStateService().handle_action("run_tool", {"tool_id": "not_real"})

        self.assertEqual(result["status"], "error")

    def test_pause_download_action_cancels_manager_task_and_marks_item_pending(self):
        item = VideoItem(url="https://example.com/video.mp4", title="active", source="douyin")
        manager = SimpleNamespace(cancel_task=Mock(return_value="running"))
        controller = SimpleNamespace(videos={item.id: item}, _dl_manager=manager)
        service = FrontendStateService(controller)

        result = service.handle_action("pause_download", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        manager.cancel_task.assert_called_once_with(item.id)
        self.assertTrue(item.meta["user_cancel_requested"])
        self.assertEqual(item.meta["frontend_status"], "待下载")

    def test_update_download_options_applies_live_manager_concurrency(self):
        class FakeConfig:
            def __init__(self):
                self.values = {
                    ("download", "max_concurrent"): 3,
                    ("download", "max_retries"): 3,
                    ("download", "video_only"): False,
                    ("download", "image_respects_concurrency"): False,
                }
                self.set_calls = []

            def get(self, section, key, default=None):
                return self.values.get((section, key), default)

            def set(self, section, key, value):
                self.values[(section, key)] = value
                self.set_calls.append((section, key, value))

        manager = SimpleNamespace(set_max_concurrent=Mock(return_value=5))
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        config = FakeConfig()
        service = FrontendStateService(controller, config_manager=config, cache_service=cache)

        result = service.handle_action(
            "update_download_options",
            {"auto_retry": True, "max_retries": 5, "max_concurrent": 6},
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["data"],
            {
                "auto_retry": True,
                "max_retries": 5,
                "max_concurrent": 5,
                "video_only": False,
                "image_respects_concurrency": False,
            },
        )
        self.assertIn(("download", "max_concurrent", 5), config.set_calls)
        self.assertIn(("download", "max_retries", 5), config.set_calls)
        self.assertIn(("download", "video_only", False), config.set_calls)
        self.assertIn(("download", "image_respects_concurrency", False), config.set_calls)
        manager.set_max_concurrent.assert_called_once_with(5)
        cache.set.assert_called_once_with("download.auto_retry", True, persist=False)

    def test_update_download_options_rejects_string_boolean(self):
        with TemporaryDirectory() as temp_dir:
            manager = ConfigManager(str(Path(temp_dir) / "config.json"))
            service = FrontendStateService(config_manager=manager)

            result = service.handle_action(
                "update_download_options",
                {"video_only": "false"},
            )

            self.assertEqual(result["status"], "error")
            self.assertIn("boolean", result["message"])
            self.assertFalse(manager.get("download", "video_only"))

    def test_update_download_options_caps_regular_concurrency_for_image_fast_lane(self):
        class FakeConfig:
            def __init__(self):
                self.values = {
                    ("download", "max_concurrent"): 3,
                    ("download", "max_retries"): 3,
                    ("download", "video_only"): False,
                    ("download", "image_respects_concurrency"): False,
                }
                self.set_calls = []

            def get(self, section, key, default=None):
                return self.values.get((section, key), default)

            def set(self, section, key, value):
                self.values[(section, key)] = value
                self.set_calls.append((section, key, value))

        manager = SimpleNamespace(set_max_concurrent=Mock(return_value=5))
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        config = FakeConfig()
        service = FrontendStateService(controller, config_manager=config, cache_service=cache)

        result = service.handle_action("update_download_options", {"max_retries": 3, "max_concurrent": 24})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["max_concurrent"], 5)
        manager.set_max_concurrent.assert_called_once_with(5)
        self.assertIn(("download", "max_concurrent", 5), config.set_calls)

    def test_update_download_options_applies_image_concurrency_switch(self):
        class FakeConfig:
            def __init__(self):
                self.values = {
                    ("download", "max_concurrent"): 3,
                    ("download", "max_retries"): 3,
                    ("download", "video_only"): False,
                    ("download", "image_respects_concurrency"): False,
                }
                self.set_calls = []

            def get(self, section, key, default=None):
                return self.values.get((section, key), default)

            def set(self, section, key, value):
                self.values[(section, key)] = value
                self.set_calls.append((section, key, value))

        manager = SimpleNamespace(
            set_max_concurrent=Mock(return_value=3),
            set_runtime_options=Mock(),
        )
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        config = FakeConfig()
        service = FrontendStateService(controller, config_manager=config, cache_service=cache)

        result = service.handle_action(
            "update_download_options",
            {"max_retries": 3, "max_concurrent": 3, "image_respects_concurrency": True},
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["image_respects_concurrency"])
        self.assertIn(("download", "image_respects_concurrency", True), config.set_calls)
        manager.set_runtime_options.assert_called_once()
        self.assertTrue(manager.set_runtime_options.call_args.kwargs["image_respects_concurrency"])

    def test_download_options_snapshot_uses_effective_manager_values(self):
        class FakeConfig:
            data = {"download": {"max_concurrent": 3, "max_retries": 7, "video_only": False, "image_respects_concurrency": True}}

            def get(self, section, key, default=None):
                return self.data.get(section, {}).get(key, default)

        manager = SimpleNamespace(max_concurrent=6, video_only=True, image_respects_concurrency=True)
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        cache.get.return_value = False
        service = FrontendStateService(controller, config_manager=FakeConfig(), cache_service=cache)

        snapshot = service.get_snapshot(sections=frozenset({"download_options"}))

        self.assertEqual(
            snapshot["download_options"],
            {
                "auto_retry": False,
                "max_retries": 7,
                "max_concurrent": 5,
                "video_only": True,
                "image_respects_concurrency": True,
            },
        )

    def test_download_options_snapshot_uses_runtime_memory_without_cache_reads(self):
        class FakeConfig:
            data = {
                "common": {},
                "download": {
                    "max_concurrent": 3,
                    "max_retries": 7,
                    "video_only": False,
                    "image_respects_concurrency": True,
                },
                "playback": {},
                "logging": {},
                "appearance": {},
            }

            def get(self, section, key, default=None):
                return self.data.get(section, {}).get(key, default)

        manager = SimpleNamespace(max_concurrent=6, video_only=True, image_respects_concurrency=True)
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        cache.get.return_value = False
        service = FrontendStateService(controller, config_manager=FakeConfig(), cache_service=cache)
        cache.get.reset_mock()

        download_snapshot = service.get_snapshot(sections=frozenset({"download_options"}))
        settings_snapshot = service.get_snapshot(sections=frozenset({"settings_snapshot"}))

        self.assertFalse(download_snapshot["download_options"]["auto_retry"])
        self.assertEqual(settings_snapshot["settings_snapshot"]["下载设置"]["max_concurrent"], 5)
        cache.get.assert_not_called()

    def test_partial_snapshot_returns_requested_sections_only(self):
        service = FrontendStateService()
        service._static_snapshot_cache = {
            "pages": [],
            "settings_snapshot": {},
            "toolbox_items": [],
            "toolbox_recent_items": [],
            "icon_manifest": {},
        }
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = "⏳ 下载中..."
        active.progress = 10
        controller = SimpleNamespace(videos={active.id: active}, _dl_manager=None)
        service.controller = controller

        snapshot = service.get_snapshot(sections=frozenset({"active_downloads", "app_status"}))

        self.assertIn("active_downloads", snapshot)
        self.assertIn("save_dir", snapshot["active_downloads"][0])
        self.assertIn("output_filename", snapshot["active_downloads"][0])
        self.assertIn("detail_fields", snapshot["active_downloads"][0])
        self.assertIn("chunk_progress_label", snapshot["active_downloads"][0])
        self.assertIn("speed_trend_label", snapshot["active_downloads"][0])
        self.assertIn("app_status", snapshot)
        self.assertNotIn("queue_items", snapshot)
        self.assertNotIn("log_items", snapshot)

    def test_stage_title_snapshots_lock_within_bucket_and_refresh_on_status_change(self):
        class MutableConfig:
            template = "current"

            def get(self, section, key, default=None):
                if section == "common" and key == "filename_template":
                    return self.template
                return default

        config = MutableConfig()
        item = VideoItem(url="https://example.com/video", title="Demo", source="bilibili")
        item.meta["index"] = 7
        controller = SimpleNamespace(videos={item.id: item}, _dl_manager=None)
        service = FrontendStateService(controller, config_manager=config)

        queue = service.get_snapshot(sections=frozenset({"queue_items"}))["queue_items"][0]
        self.assertEqual(queue["title"], "Demo")

        config.template = "{platform}_{title}_{index}"
        queue_after_setting_change = service.get_snapshot(sections=frozenset({"queue_items"}))["queue_items"][0]
        self.assertEqual(queue_after_setting_change["title"], "Demo")

        item.status = VideoStatus.DOWNLOADING.value
        active = service.get_snapshot(sections=frozenset({"active_downloads"}))["active_downloads"][0]
        self.assertEqual(active["title"], "bilibili_Demo_7")

        config.template = "{platform}_{title}"
        active_after_setting_change = service.get_snapshot(sections=frozenset({"active_downloads"}))["active_downloads"][0]
        self.assertEqual(active_after_setting_change["title"], "bilibili_Demo_7")

        item.status = VideoStatus.COMPLETED.value
        item.progress = 100
        item.local_path = "D:/Downloads/bilibili_Demo_7.mp4"
        completed = service.get_snapshot(sections=frozenset({"completed_items"}))["completed_items"][0]
        self.assertEqual(completed["title"], "bilibili_Demo")

        config.template = "{title}"
        completed_after_setting_change = service.get_snapshot(sections=frozenset({"completed_items"}))["completed_items"][0]
        self.assertEqual(completed_after_setting_change["title"], "bilibili_Demo")

        item.status = VideoStatus.FAILED.value
        failed = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
        self.assertEqual(failed["title"], "Demo")

        config.template = "{platform}_{title}_{index}"
        failed_after_setting_change = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
        self.assertEqual(failed_after_setting_change["title"], "Demo")

    def test_stage_title_snapshots_materialize_on_status_events_before_page_render(self):
        class MutableConfig:
            template = "current"

            def get(self, section, key, default=None):
                if section == "common" and key == "filename_template":
                    return self.template
                return default

        config = MutableConfig()
        item = VideoItem(url="https://example.com/video", title="Clip", source="bilibili")
        item.meta["index"] = 7
        controller = SimpleNamespace(videos={item.id: item}, _dl_manager=None)
        service = FrontendStateService(controller, config_manager=config)

        queue = service.get_snapshot(sections=frozenset({"queue_items"}))["queue_items"][0]
        self.assertEqual(queue["title"], "Clip")

        config.template = "{platform}_{title}_{index}"
        item.status = VideoStatus.DOWNLOADING.value
        service.record_event("video_state_changed", {"video_id": item.id, "status": item.status, "progress": 0})

        config.template = "{title}"
        active = service.get_snapshot(sections=frozenset({"active_downloads"}))["active_downloads"][0]
        self.assertEqual(active["title"], "bilibili_Clip_7")

        config.template = "{platform}_{title}"
        item.status = VideoStatus.COMPLETED.value
        item.progress = 100
        item.local_path = "D:/Downloads/bilibili_Clip_7.mp4"
        service.record_event("video_state_changed", {"video_id": item.id, "status": item.status, "progress": 100})

        config.template = "{title}_{index}"
        completed = service.get_snapshot(sections=frozenset({"completed_items"}))["completed_items"][0]
        self.assertEqual(completed["title"], "bilibili_Clip")

        item.status = VideoStatus.FAILED.value
        service.record_event("video_state_changed", {"video_id": item.id, "status": item.status, "progress": 0})

        config.template = "current"
        failed = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]
        self.assertEqual(failed["title"], "Clip_7")

    def test_partial_app_status_keeps_completed_count_when_bucket_not_requested(self):
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = "⏳ 等待中"
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "✅ 本地"
        completed.progress = 100
        completed.local_path = __file__
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = "⏳ 下载中..."
        active.progress = 25
        active.meta["speed_bps"] = 2048
        active.meta["speed"] = "2.0 KB/s"
        controller = SimpleNamespace(
            videos={item.id: item for item in (queued, completed, active)},
            _dl_manager=None,
        )
        service = FrontendStateService(controller)

        snapshot = service.get_snapshot(sections=frozenset({"active_downloads", "app_status"}))

        self.assertEqual(snapshot["app_status"]["completed_count"], 1)
        self.assertEqual(snapshot["app_status"]["failed_count"], 0)
        self.assertEqual(snapshot["app_status"]["queue_count"], 1)
        self.assertEqual(snapshot["app_status"]["active_count"], 1)
        self.assertIn("2.0 KB/s", snapshot["app_status"]["download_speed"])

    def test_app_status_parses_compact_speed_strings_when_bps_missing(self):
        active_items = [
            {"speed": "1.50MBps", "speed_bps": 0},
            {"speed": "512 KiB/s", "speed_bps": 0},
        ]

        status = FrontendStateService().app_status(
            completed_count=0,
            failed_count=0,
            active_downloads=active_items,
        )

        self.assertEqual(status["download_speed_bps"], 2 * 1024 * 1024)
        self.assertEqual(status["download_speed"], "2.0 MB/s")

    def test_log_excerpt_index_builds_trace_lookup_once(self):
        service = FrontendStateService()
        service.record_log("line-1", level="ERROR", source="Downloader", trace_id="trace-a")
        service.record_log("line-2", level="ERROR", source="Downloader", trace_id="trace-a")

        index = service._log_excerpt_index()

        self.assertEqual([entry["message"] for entry in index["trace-a"]], ["line-1", "line-2"])
        self.assertEqual(index["trace-a"][0]["icon_file"], "log_level_error.png")
        self.assertEqual(service._log_excerpt("trace-a"), ["line-1", "line-2"])

    def test_get_delta_returns_versioned_dirty_sections(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("video_state_changed", {"video_id": "v1", "progress": 10})
        delta = service.get_delta(base_version)

        self.assertGreater(delta["version"], base_version)
        self.assertFalse(delta["full"])
        self.assertIn("active_downloads", delta["changed_sections"])
        self.assertIn("app_status", delta["sections"])

    def test_get_delta_serializes_version_and_snapshot_projection(self):
        service = FrontendStateService()
        base_version = service.frontend_version
        service.record_event("videos.update", {"video_id": "v1", "progress": 10})
        projected_version = service.frontend_version
        worker_started = threading.Event()
        worker_finished = threading.Event()

        def publish_newer_state() -> None:
            worker_started.set()
            service.record_event("videos.update", {"video_id": "v1", "progress": 20})
            worker_finished.set()

        worker = threading.Thread(target=publish_newer_state)

        def build_racing_snapshot(*, sections=None, **_kwargs):
            worker.start()
            self.assertTrue(worker_started.wait(timeout=1))
            concurrent_finished = worker_finished.wait(timeout=0.1)
            return {
                "active_downloads": [],
                "app_status": {
                    "observed_version": service.frontend_version,
                    "concurrent_finished": concurrent_finished,
                },
                "version": service.frontend_version,
            }

        with patch.object(service, "get_snapshot", side_effect=build_racing_snapshot):
            delta = service.get_delta(base_version)

        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(delta["version"], projected_version)
        self.assertEqual(delta["sections"]["app_status"]["observed_version"], delta["version"])
        self.assertFalse(delta["sections"]["app_status"]["concurrent_finished"])
        self.assertGreater(service.get_delta(delta["version"])["version"], delta["version"])

    def test_app_state_changed_is_queued_until_delta_flush(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.app_state.set_running_state("busy")

        self.assertEqual(service.frontend_version, base_version)
        self.assertEqual(service.frontend_metrics()["pending_app_state_event_count"], 1)

        delta = service.get_delta(base_version)

        self.assertGreater(delta["version"], base_version)
        self.assertEqual(service.frontend_metrics()["pending_app_state_event_count"], 0)
        self.assertIn("app_status", delta["changed_sections"])
        self.assertTrue(any(event["topic"] == "app.running_state" for event in delta["events"]))

    def test_app_state_changed_is_queued_until_snapshot_flush(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.app_state.set_running_state("busy")
        snapshot = service.get_snapshot(sections=frozenset({"app_status"}))

        self.assertGreater(snapshot["version"], base_version)
        self.assertEqual(service.frontend_metrics()["pending_app_state_event_count"], 0)
        self.assertIn("app_status", snapshot)

    def test_app_state_changed_queue_is_bounded_and_requests_resync(self):
        service = FrontendStateService()
        service.APP_STATE_PENDING_EVENTS_LIMIT = 2
        base_version = service.frontend_version

        for index in range(3):
            service.app_state.set_running_state(f"busy-{index}")

        self.assertEqual(service.frontend_version, base_version)
        self.assertEqual(service.frontend_metrics()["pending_app_state_event_count"], 2)
        self.assertTrue(service.frontend_metrics()["pending_app_state_event_overflowed"])

        delta = service.get_delta(base_version)

        self.assertGreater(delta["version"], base_version)
        self.assertFalse(service.frontend_metrics()["pending_app_state_event_overflowed"])
        self.assertIn("settings_snapshot", delta["changed_sections"])
        self.assertTrue(any(event["topic"] == "app_state.resync_required" for event in delta["events"]))

    def test_get_delta_keeps_regular_progress_narrow(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("videos.update", {"video_id": "v1", "progress": 42})
        delta = service.get_delta(base_version)

        self.assertEqual(set(delta["changed_sections"]), {"active_downloads", "app_status"})

    def test_get_delta_promotes_terminal_progress_to_video_sections(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("videos.update", {"video_id": "v1", "progress": 100})
        delta = service.get_delta(base_version)

        for section in ("queue_items", "active_downloads", "completed_items", "failed_items", "app_status"):
            self.assertIn(section, delta["changed_sections"])

    def test_get_delta_routes_metadata_event_to_completed_items(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("videos.metadata", {"video_id": "v1", "metadata": True})
        delta = service.get_delta(base_version)

        self.assertEqual(set(delta["changed_sections"]), {"completed_items", "app_status"})

    def test_log_append_delta_stays_narrow(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_log("解析完成", source="bilibili", trace_id="trace-log")
        delta = service.get_delta(base_version)

        self.assertEqual(set(delta["changed_sections"]), {"log_items", "app_status"})
        self.assertIn("log_items", delta["sections"])
        self.assertNotIn("queue_items", delta["sections"])

    def test_get_delta_reports_deleted_ids(self):
        service = FrontendStateService()
        service.record_event("video_removed", {"video_id": "v1"})

        delta = service.get_delta(0)

        self.assertFalse(delta["full"])
        self.assertIn("v1", delta["deleted_ids"])

    def test_get_delta_uses_versioned_sections_instead_of_stale_dirty_set(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        first_delta = service.get_delta(base_version)
        self.assertEqual(first_delta["changed_sections"], [])

        service.record_event("settings.update", {"section": "download"})
        settings_delta = service.get_delta(base_version)
        self.assertIn("settings_snapshot", settings_delta["changed_sections"])

        service.record_event("video_state_changed", {"video_id": "v1", "progress": 20})
        progress_delta = service.get_delta(settings_delta["version"])

        self.assertEqual(set(progress_delta["changed_sections"]), {"active_downloads", "app_status"})
        self.assertNotIn("settings_snapshot", progress_delta["sections"])

    def test_get_delta_with_requested_sections_does_not_ack_unreturned_dirty_sections(self):
        # 局部 delta 请求不能把未返回的脏 section 误标为已消费，否则下一轮
        # 页面切换会漏掉 settings/download_options 等更新。
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("settings.update", {"section": "download"})
        service.record_event("video_state_changed", {"video_id": "v1", "progress": 20})

        delta = service.get_delta(base_version, sections={"active_downloads", "app_status"})

        self.assertIn("active_downloads", delta["changed_sections"])
        self.assertIn("app_status", delta["changed_sections"])
        self.assertIn("settings_snapshot", delta["changed_sections"])
        self.assertIn("settings_contract", delta["changed_sections"])
        self.assertIn("download_options", delta["changed_sections"])
        self.assertIn("settings_snapshot", delta["sections"])

    def test_get_delta_deleted_ids_are_versioned(self):
        service = FrontendStateService()

        service.record_event("video_removed", {"video_id": "old"})
        acknowledged = service.get_delta(0)["version"]
        service.record_event("logs.append", {"message": "tick"})

        delta = service.get_delta(acknowledged)

        self.assertEqual(delta["deleted_ids"], [])

    def test_file_log_worker_refresh_marks_failed_items_dirty(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("logs.append", {"count": 3, "source": "frontend_log_worker", "batched": True})
        delta = service.get_delta(base_version)

        self.assertIn("log_items", delta["changed_sections"])
        self.assertIn("failed_items", delta["changed_sections"])

    def test_regular_log_append_keeps_failed_items_lazy(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("logs.append", {"message": "tick"})
        delta = service.get_delta(base_version)

        self.assertIn("log_items", delta["changed_sections"])
        self.assertNotIn("failed_items", delta["changed_sections"])

    def test_log_refresh_action_does_not_publish_log_append_event(self):
        service = FrontendStateService()
        service.record_log("existing", source="Test")
        before = service.app_state.get_log_buffer()

        result = service.handle_action("log_operation", {"operation": "refresh"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["message"], "日志缓存已刷新")
        self.assertEqual(service.app_state.get_log_buffer(), before)

if __name__ == "__main__":
    unittest.main()
