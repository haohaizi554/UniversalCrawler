"""配置加载、规范化与持久化测试。"""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QByteArray

from app.config import DEFAULT_USER_AGENT
from app.config.constants import DEFAULT_DOWNLOAD_DIR
from app.config.settings import (
    ConfigManager,
    ConfigValidationError,
    download_concurrency_options,
    failed_record_retention_options,
    font_size_options,
    get_platform_runtime_defaults,
    language_options,
    log_retention_options,
    platform_count_options,
    platform_note_count_options,
    platform_page_count_options,
    request_timeout_options,
    retry_options,
    scale_options,
    speed_limit_options,
    ui_log_max_display_options,
)
from app.exceptions import ConfigWriteError
from app.utils.runtime_paths import resolve_user_file

class ConfigManagerTests(unittest.TestCase):

    def test_failed_set_keeps_state_imported_by_forced_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            stale_manager = ConfigManager(config_path)
            external_manager = ConfigManager(config_path)

            external_manager.set("common", "theme", "dark")

            with self.assertRaises(ConfigValidationError):
                stale_manager.set("appearance", "language", "invalid-locale")

            self.assertEqual("dark", stale_manager.get("common", "theme"))
            self.assertEqual(stale_manager._current_disk_signature(), stale_manager._disk_signature)
            self.assertFalse(stale_manager.reload_if_changed())

    def test_failed_set_batch_keeps_state_imported_by_forced_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            stale_manager = ConfigManager(config_path)
            external_manager = ConfigManager(config_path)

            external_manager.set("appearance", "accent", "green")

            with self.assertRaises(ConfigValidationError):
                stale_manager.set_batch(
                    {"common": {"last_source": "douyin", "theme": "invalid-theme"}}
                )

            self.assertEqual("green", stale_manager.get("appearance", "accent"))
            self.assertEqual("kuaishou", stale_manager.get("common", "last_source"))
            self.assertEqual(stale_manager._current_disk_signature(), stale_manager._disk_signature)
            self.assertFalse(stale_manager.reload_if_changed())

    def test_failed_save_ui_state_keeps_state_imported_by_forced_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            stale_manager = ConfigManager(config_path)
            external_manager = ConfigManager(config_path)

            external_manager.set("common", "theme", "dark")

            with mock.patch.object(
                stale_manager,
                "save",
                side_effect=ConfigWriteError("save failed"),
            ):
                with self.assertRaises(ConfigWriteError):
                    stale_manager.save_ui_state(
                        geometry=b"geometry",
                        state=b"state",
                        main_splitter=b"main",
                        right_splitter=b"right",
                        is_fs=True,
                    )

            self.assertEqual("dark", stale_manager.get("common", "theme"))
            self.assertEqual("", stale_manager.get("ui", "geometry"))
            self.assertEqual(stale_manager._current_disk_signature(), stale_manager._disk_signature)
            self.assertFalse(stale_manager.reload_if_changed())

    def test_exclusive_file_lock_cleans_up_when_metadata_write_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(f"{temp_dir}/config.json")

            with mock.patch("app.config.settings.os.close", wraps=os.close) as close_mock:
                with mock.patch(
                    "app.config.settings.os.write",
                    side_effect=OSError("metadata write failed"),
                ):
                    with self.assertRaises(ConfigWriteError):
                        with manager._exclusive_file_lock():
                            self.fail("lock body should not run")

            close_mock.assert_called_once()
            self.assertFalse(manager._file_lock_path.exists())

    def test_restarted_external_sync_does_not_revive_timed_out_watcher(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(f"{temp_dir}/config.json")
            old_watcher_entered = threading.Event()
            release_old_watcher = threading.Event()
            old_watcher_reentered = threading.Event()
            old_thread_holder: dict[str, threading.Thread] = {}

            def controlled_reload() -> None:
                if threading.current_thread() is not old_thread_holder.get("thread"):
                    return
                if old_watcher_entered.is_set():
                    old_watcher_reentered.set()
                    return
                old_watcher_entered.set()
                release_old_watcher.wait(timeout=2)

            with mock.patch.object(manager, "reload_if_changed", side_effect=controlled_reload):
                manager.start_external_sync(interval_seconds=0.05)
                old_thread = manager._external_sync_thread
                self.assertIsNotNone(old_thread)
                old_thread_holder["thread"] = old_thread
                try:
                    self.assertTrue(old_watcher_entered.wait(timeout=2))
                    with mock.patch.object(old_thread, "join", return_value=None) as join_mock:
                        manager.stop_external_sync()
                    join_mock.assert_called_once_with(timeout=1.0)
                    self.assertTrue(old_thread.is_alive())

                    manager.start_external_sync(interval_seconds=0.05)
                    self.assertIsNot(old_thread, manager._external_sync_thread)
                    release_old_watcher.set()
                    self.assertFalse(old_watcher_reentered.wait(timeout=0.25))
                finally:
                    release_old_watcher.set()
                    manager.stop_external_sync()
                    old_thread.join(timeout=1.0)

    def test_external_sync_stays_alive_until_all_frontend_owners_release_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(f"{temp_dir}/config.json")

            manager.start_external_sync(interval_seconds=0.02)
            manager.start_external_sync(interval_seconds=0.02)
            self.assertTrue(manager.external_sync_running)
            self.assertEqual(2, manager._external_sync_refcount)

            manager.stop_external_sync()
            self.assertTrue(manager.external_sync_running)
            self.assertEqual(1, manager._external_sync_refcount)

            manager.stop_external_sync()
            self.assertFalse(manager.external_sync_running)
            self.assertEqual(0, manager._external_sync_refcount)

    def test_stale_manager_update_preserves_newer_values_from_another_process(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)

            gui_manager.set("common", "theme", "dark")
            web_manager.set("appearance", "accent", "red")

            reloaded = ConfigManager(config_path)
            self.assertEqual("dark", reloaded.get("common", "theme"))
            self.assertEqual("red", reloaded.get("appearance", "accent"))

    def test_stale_gui_exit_state_does_not_overwrite_web_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)

            web_manager.set_batch(
                {
                    "common": {"theme": "dark"},
                    "appearance": {"accent": "green", "language": "en-US"},
                }
            )
            gui_manager.save_ui_state(
                geometry=b"geometry",
                state=b"state",
                main_splitter=b"main",
                right_splitter=b"right",
                is_fs=False,
            )

            reloaded = ConfigManager(config_path)
            self.assertEqual("dark", reloaded.get("common", "theme"))
            self.assertEqual("green", reloaded.get("appearance", "accent"))
            self.assertEqual("en-US", reloaded.get("appearance", "language"))
            self.assertEqual(b"geometry".hex(), reloaded.get("ui", "geometry"))

    def test_reload_if_changed_emits_normalized_external_change_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)
            events: list[dict] = []
            gui_manager.subscribe("config.changed", events.append)

            web_manager.set_batch(
                {
                    "common": {"theme": "dark"},
                    "appearance": {"accent": "orange"},
                }
            )

            self.assertTrue(gui_manager.reload_if_changed())
            self.assertEqual("dark", gui_manager.get("common", "theme"))
            self.assertEqual("orange", gui_manager.get("appearance", "accent"))
            self.assertEqual(1, len(events))
            self.assertTrue(events[0]["external"])
            changed = {(item["section"], item["key"]) for item in events[0]["changes"]}
            self.assertIn(("common", "theme"), changed)
            self.assertIn(("appearance", "accent"), changed)

    def test_external_sync_observes_another_manager_without_manual_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            gui_manager = ConfigManager(config_path)
            web_manager = ConfigManager(config_path)
            changed = threading.Event()

            def on_change(payload):
                changes = payload.get("changes") or [payload]
                if payload.get("external") and any(item.get("key") == "theme" for item in changes):
                    changed.set()

            gui_manager.subscribe("config.changed", on_change)
            gui_manager.start_external_sync(interval_seconds=0.02)
            try:
                web_manager.set("common", "theme", "dark")
                self.assertTrue(changed.wait(timeout=2))
                self.assertEqual("dark", gui_manager.get("common", "theme"))
            finally:
                gui_manager.stop_external_sync()

            time.sleep(0.04)
            self.assertFalse(gui_manager.external_sync_running)
    
    def test_legacy_theme_value_is_normalized(self):
        """验证 `test_legacy_theme_value_is_normalized` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                fp.write('{"common":{"theme":"light","dark_theme":true}}')

            manager = ConfigManager(config_path)

            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))

    def test_legacy_dark_default_migrates_to_light(self):
        """旧版本默认 dark 配置应迁移为新版浅色默认。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                fp.write('{"common":{"theme":"dark","dark_theme":true}}')

            manager = ConfigManager(config_path)

            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))
            self.assertEqual(manager.get("common", "theme_schema_version"), 2)

    def test_set_validates_and_persists(self):
        """验证 `test_set_validates_and_persists` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("missav", "proxy_url", "http://127.0.0.1:10809")

            reloaded = ConfigManager(config_path)
            self.assertEqual(reloaded.get("missav", "proxy_url"), "http://127.0.0.1:10809")

    def test_set_many_saves_once_and_publishes_one_combined_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            events = []
            manager.subscribe("config.changed", events.append)

            with mock.patch.object(manager, "save", wraps=manager.save) as save_mock:
                manager.set_many("common", {"theme": "dark", "last_source": "douyin"})

            self.assertEqual(1, save_mock.call_count)
            self.assertEqual(1, len(events))
            self.assertEqual("common", events[0]["section"])
            self.assertEqual("last_source", events[0]["key"])
            self.assertEqual(2, len(events[0]["changes"]))
            reloaded = ConfigManager(config_path)
            self.assertEqual("dark", reloaded.get("common", "theme"))
            self.assertTrue(reloaded.get("common", "dark_theme"))
            self.assertEqual("douyin", reloaded.get("common", "last_source"))

    def test_set_batch_commits_cross_section_changes_with_one_save_and_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("appearance", "follow_system", True)
            events = []
            manager.subscribe("config.changed", events.append)

            with mock.patch.object(manager, "save", wraps=manager.save) as save_mock:
                manager.set_batch(
                    {
                        "appearance": {"follow_system": False},
                        "common": {"theme": "dark"},
                    }
                )

            save_mock.assert_called_once_with()
            self.assertEqual(len(events), 1)
            self.assertEqual(len(events[0]["changes"]), 2)
            self.assertFalse(manager.get("appearance", "follow_system"))
            self.assertEqual(manager.get("common", "theme"), "dark")
            reloaded = ConfigManager(config_path)
            self.assertFalse(reloaded.get("appearance", "follow_system"))
            self.assertEqual(reloaded.get("common", "theme"), "dark")

    def test_subscribe_async_does_not_block_config_writer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            started = threading.Event()
            release = threading.Event()
            seen: list[str] = []

            def slow_handler(payload):
                started.set()
                release.wait(timeout=2)
                seen.append(str(payload.get("key") or ""))

            manager.subscribe_async("config.changed", slow_handler)
            try:
                manager.set("common", "last_source", "douyin")
                self.assertTrue(started.wait(timeout=2))
                self.assertEqual(seen, [])
            finally:
                release.set()
                manager.event_bus.shutdown()

        self.assertEqual(seen, ["last_source"])

    def test_set_many_rolls_back_memory_when_later_value_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            with self.assertRaises(ConfigValidationError):
                manager.set_many("common", {"last_source": "douyin", "theme": "invalid-theme"})

            self.assertEqual("kuaishou", manager.get("common", "last_source"))
            self.assertEqual("light", manager.get("common", "theme"))

    def test_save_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            original_replace = Path.replace
            calls = {"count": 0}

            def flaky_replace(path: Path, target) -> Path:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise PermissionError("locked by another process")
                return original_replace(path, target)

            with mock.patch("app.config.settings.time_module.sleep") as sleep_mock:
                with mock.patch.object(Path, "replace", flaky_replace):
                    manager.set("common", "theme", "dark")

            self.assertGreaterEqual(calls["count"], 2)
            sleep_mock.assert_called_once()
            reloaded = ConfigManager(config_path)
            self.assertEqual(reloaded.get("common", "theme"), "dark")

    def test_save_uses_a_unique_same_directory_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            manager = ConfigManager(str(config_path))

            with mock.patch(
                "app.config.settings.tempfile.NamedTemporaryFile",
                wraps=tempfile.NamedTemporaryFile,
            ) as named_temporary_file:
                manager.set("common", "theme", "dark")

            kwargs = named_temporary_file.call_args.kwargs
            self.assertFalse(kwargs["delete"])
            self.assertEqual(Path(kwargs["dir"]), config_path.parent)
            self.assertTrue(kwargs["prefix"].startswith(f".{config_path.name}."))
            self.assertEqual(kwargs["suffix"], ".tmp")

    def test_set_rolls_back_memory_and_skips_event_when_atomic_replace_never_succeeds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            events = []
            manager.subscribe("config.changed", events.append)

            with mock.patch("app.config.settings.time_module.sleep"):
                with mock.patch.object(Path, "replace", side_effect=PermissionError("locked forever")):
                    with self.assertRaises(ConfigWriteError):
                        manager.set("common", "theme", "dark")

            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertEqual(events, [])
            self.assertFalse(Path(config_path + ".tmp").exists())
            reloaded = ConfigManager(config_path)
            self.assertEqual(reloaded.get("common", "theme"), "light")

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
            self.assertEqual(manager.settings.xiaohongshu.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(manager.settings.bilibili.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(manager.settings.kuaishou.user_agent, DEFAULT_USER_AGENT)

    def test_short_video_platform_limits_default_to_twenty(self):
        """验证 `test_short_video_platform_limits_default_to_twenty` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.douyin.max_items, 20)
            self.assertEqual(manager.settings.xiaohongshu.max_items, 20)
            self.assertEqual(manager.settings.kuaishou.max_items, 20)

    def test_platform_runtime_defaults_are_declared_in_config_models(self):
        """平台运行参数默认值应由配置模型统一声明，而非调用方各自硬编码。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.douyin.timeout, 60)
            self.assertEqual(manager.settings.bilibili.max_items, 9999)
            self.assertEqual(manager.settings.bilibili.timeout, 60)
            self.assertEqual(manager.settings.xiaohongshu.timeout, 30)
            self.assertEqual(manager.settings.xiaohongshu.request_interval, 0.15)
            self.assertEqual(manager.settings.xiaohongshu.detail_request_interval, 0.0)
            self.assertEqual(manager.settings.kuaishou.timeout, 60)
            self.assertEqual(manager.settings.missav.timeout, 60)

    def test_legacy_xiaohongshu_parse_intervals_are_migrated_to_fast_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                json.dump({"xiaohongshu": {"request_interval": 1.5, "detail_request_interval": 0.5}}, fp)

            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.xiaohongshu.request_interval, 0.15)
            self.assertEqual(manager.settings.xiaohongshu.detail_request_interval, 0.0)

    def test_missav_runtime_defaults_include_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            defaults = get_platform_runtime_defaults("missav", manager)

        self.assertEqual(defaults["timeout"], 60)

    def test_legacy_short_platform_timeouts_are_raised_to_runtime_floor(self):
        """历史默认 10 秒太短，加载旧配置时应归一化到可用下限。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            with open(config_path, "w", encoding="utf-8") as fp:
                json.dump(
                    {
                        "douyin": {"timeout": 10},
                        "bilibili": {"timeout": 10},
                        "kuaishou": {"timeout": 10},
                        "missav": {"timeout": 10},
                    },
                    fp,
                )

            manager = ConfigManager(config_path)

            self.assertEqual(manager.settings.douyin.timeout, 60)
            self.assertEqual(manager.settings.bilibili.timeout, 60)
            self.assertEqual(manager.settings.kuaishou.timeout, 60)
            self.assertEqual(manager.settings.missav.timeout, 60)

    def test_set_coerces_float_runtime_settings(self):
        """float 类型的平台运行参数应支持通过配置管理器持久化。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("xiaohongshu", "request_interval", "2.5")
            manager.set("xiaohongshu", "detail_request_interval", "0.8")

            reloaded = ConfigManager(config_path)

            self.assertEqual(reloaded.get("xiaohongshu", "request_interval"), 2.5)
            self.assertEqual(reloaded.get("xiaohongshu", "detail_request_interval"), 0.8)

    def test_invalid_config_file_is_backed_up_and_reset(self):
        """验证 `test_invalid_config_file_is_backed_up_and_reset` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{bad json", encoding="utf-8")

            manager = ConfigManager(str(config_path))

            backups = list(Path(temp_dir).glob("config.json.bak.*"))
            self.assertTrue(backups)
            self.assertIsNotNone(manager.last_load_error)
            self.assertEqual(manager.get("common", "theme"), "light")
            self.assertFalse(manager.get("common", "dark_theme"))

    def test_set_and_get_keep_integer_values_consistent_after_reload(self):
        """验证 `test_set_and_get_keep_integer_values_consistent_after_reload` 对应场景是否符合预期，供 `ConfigManagerTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("download", "max_concurrent", "6")

            reloaded = ConfigManager(config_path)

        self.assertEqual(reloaded.get("download", "max_concurrent"), 5)

    def test_recommended_options_match_default_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(f"{temp_dir}/config.json")

            self.assertEqual(manager.get("download", "max_concurrent"), 3)
            self.assertEqual(manager.get("download", "request_timeout"), 60)
            self.assertEqual(manager.get("download", "max_retries"), 3)
            self.assertEqual(manager.get("logging", "retention_days"), 1)
            self.assertEqual(manager.get("logging", "failed_record_retention_days"), 7)
            self.assertEqual(manager.get("logging", "ui_log_max_display_count"), 300)
            self.assertEqual(manager.get("appearance", "scale"), "100%")
            self.assertEqual(manager.get("appearance", "font_size"), "medium")
            self.assertEqual(manager.get("appearance", "language"), "zh-CN")
            self.assertFalse(manager.get("download", "image_respects_concurrency"))
            self.assertIn({"value": "3", "label": "3（推荐）"}, download_concurrency_options())
            self.assertNotIn({"value": "12", "label": "12（推荐）"}, download_concurrency_options())
            self.assertIn({"value": "60", "label": "60 秒（推荐）"}, request_timeout_options())
            self.assertIn({"value": "3", "label": "3（推荐）"}, retry_options())
            self.assertIn({"value": "0", "label": "无限制"}, speed_limit_options())
            self.assertNotIn({"value": "0", "label": "无限制（0 KB/s）"}, speed_limit_options())
            self.assertIn({"value": "1", "label": "1 天（推荐）"}, log_retention_options())
            self.assertNotIn({"value": "30", "label": "30 天（推荐）"}, log_retention_options())
            self.assertIn({"value": "7", "label": "7 天（推荐）"}, failed_record_retention_options())
            self.assertNotIn({"value": "1", "label": "1 天（推荐）"}, failed_record_retention_options())
            self.assertEqual(
                ui_log_max_display_options(),
                [
                    {"value": "100", "label": "100 条"},
                    {"value": "300", "label": "300 条（推荐）"},
                    {"value": "500", "label": "500 条"},
                ],
            )
            self.assertIn({"value": "100%", "label": "100%（推荐）"}, scale_options())
            self.assertIn({"value": "medium", "label": "中（推荐）"}, font_size_options())
            self.assertIn({"value": "zh-CN", "label": "简体中文（推荐）"}, language_options())
            self.assertIn({"value": "20", "label": "20 个视频（推荐）"}, platform_count_options())
            self.assertIn({"value": "20", "label": "20 篇笔记（推荐）"}, platform_note_count_options())
            self.assertIn({"value": "1", "label": "1 页（推荐）"}, platform_page_count_options())

    def test_log_retention_days_are_limited_to_short_policy_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"logging": {"retention_days": 30}}, ensure_ascii=False),
                encoding="utf-8",
            )

            manager = ConfigManager(str(config_path))

            self.assertEqual(manager.get("logging", "retention_days"), 1)
            with self.assertRaises(ConfigValidationError):
                manager.set("logging", "retention_days", 30)

    def test_failed_record_retention_days_are_limited_to_history_policy_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"logging": {"failed_record_retention_days": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )

            manager = ConfigManager(str(config_path))

            self.assertEqual(manager.get("logging", "failed_record_retention_days"), 7)
            with self.assertRaises(ConfigValidationError):
                manager.set("logging", "failed_record_retention_days", 1)

    def test_download_concurrency_caps_regular_workers_while_images_use_fast_lane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            manager.set("download", "max_concurrent", "24")
            manager.set("download", "image_fast_lane_limit", "99")

            reloaded = ConfigManager(config_path)

        self.assertEqual(reloaded.get("download", "max_concurrent"), 5)
        self.assertEqual(reloaded.get("download", "image_fast_lane_limit"), 10)

    def test_get_set_are_safe_under_concurrent_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)
            errors: list[Exception] = []

            def worker(value: int) -> None:
                try:
                    for _ in range(10):
                        manager.set("download", "max_concurrent", value)
                        self.assertIsInstance(manager.get("download", "max_concurrent"), int)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(value,)) for value in (1, 3, 5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertIn(manager.get("download", "max_concurrent"), {1, 3, 5})

    def test_temp_save_directory_is_normalized_back_to_default_download_dir(self):
        """被临时目录污染的保存路径在加载配置时应自动回落到规范目录。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            polluted_save_dir = Path(temp_dir) / "tmp-persisted-downloads"
            config_path.write_text(
                json.dumps({"common": {"save_directory": str(polluted_save_dir)}}),
                encoding="utf-8",
            )

            manager = ConfigManager(str(config_path))

            self.assertEqual(
                os.path.normcase(
                    os.path.normpath(
                        manager.get("common", "save_directory")
                    )
                ),
                os.path.normcase(
                    os.path.normpath(DEFAULT_DOWNLOAD_DIR)
                ),
            )

    def test_extended_ui_sections_persist_with_normalized_types(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            manager.set("download", "max_retries", "0")
            manager.set("download", "resume_enabled", "false")
            manager.set("playback", "remember_position", "false")
            manager.set("logging", "ui_log_max_display_count", "600")
            manager.set("appearance", "scale", "125%")
            manager.set("appearance", "language", "en-US")

            reloaded = ConfigManager(config_path)

            self.assertEqual(reloaded.get("download", "max_retries"), 0)
            self.assertFalse(reloaded.get("download", "resume_enabled"))
            self.assertFalse(reloaded.get("playback", "remember_position"))
            self.assertEqual(reloaded.get("logging", "ui_log_max_display_count"), 300)
            self.assertEqual(reloaded.get("appearance", "scale"), "125%")
            self.assertEqual(reloaded.get("appearance", "language"), "en-US")

    def test_appearance_language_rejects_unknown_locale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(f"{temp_dir}/config.json")

            with self.assertRaises(ConfigValidationError):
                manager.set("appearance", "language", "xx-TEST")

            self.assertEqual(manager.get("appearance", "language"), "zh-CN")

    def test_save_ui_state_accepts_non_qt_buffers(self):
        """验证配置层保存 UI 状态时不再依赖 Qt 类型。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            manager.save_ui_state(
                geometry=b"\xaa\x55",
                state=bytearray(b"\x10\x20"),
                main_splitter=memoryview(b"\x01\x02"),
                right_splitter="beef",
                is_fs=True,
            )

            self.assertEqual(manager.get("ui", "geometry"), "aa55")
            self.assertEqual(manager.get("ui", "window_state"), "1020")
            self.assertEqual(manager.get("ui", "main_splitter_state"), "0102")
            self.assertEqual(manager.get("ui", "right_splitter_state"), "beef")
            self.assertTrue(manager.get("ui", "is_fullscreen_mode"))

    def test_save_ui_state_accepts_qbytearray_without_recursive_crash(self):
        """验证 GUI 退出场景下，QByteArray 编码不会递归崩溃。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/config.json"
            manager = ConfigManager(config_path)

            manager.save_ui_state(
                geometry=QByteArray(b"\x01\x02"),
                state=QByteArray(b"\x03\x04"),
                main_splitter=QByteArray(b"\x05\x06"),
                right_splitter=QByteArray(b"\x07\x08"),
                is_fs=False,
            )

            self.assertEqual(manager.get("ui", "geometry"), "0102")
            self.assertEqual(manager.get("ui", "window_state"), "0304")
            self.assertEqual(manager.get("ui", "main_splitter_state"), "0506")
            self.assertEqual(manager.get("ui", "right_splitter_state"), "0708")

if __name__ == "__main__":
    unittest.main()
