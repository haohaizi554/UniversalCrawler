from types import SimpleNamespace
from unittest.mock import Mock

import json
import time

from app.services.frontend_settings_adapter import (
    build_download_options_snapshot,
    build_settings_snapshot,
    normalize_download_options_payload,
    persist_download_options,
    platform_auth_snapshot,
    platform_count_contract,
    platform_proxy_contract,
    resolve_platform_auth_spec,
)


def test_kuaishou_auth_snapshot_rejects_expired_main_site_cookie(tmp_path):
    cookie_file = tmp_path / "ks_auth.json"
    cookie_file.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "userId",
                        "value": "identity-only",
                        "domain": "id.kuaishou.com",
                        "path": "/",
                        "expires": time.time() + 3600,
                    },
                    {
                        "name": "userId",
                        "value": "expired-main-site",
                        "domain": ".kuaishou.com",
                        "path": "/",
                        "expires": time.time() - 3600,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    snapshot = platform_auth_snapshot(
        "kuaishou",
        {"kuaishou_cookie_file": str(cookie_file)},
    )

    assert snapshot["auth_status"] == "未认证"


def test_platform_auth_requirements_come_from_plugin_metadata():
    kuaishou = resolve_platform_auth_spec("kuaishou")
    missav = resolve_platform_auth_spec("missav")
    unknown = resolve_platform_auth_spec("external-without-metadata")

    assert kuaishou.mode == "cookie"
    assert kuaishou.config_key == "kuaishou_cookie_file"
    assert "userId" in kuaishou.cookie_names
    assert missav.mode == "none"
    assert unknown.mode == "unspecified"


def test_platform_auth_snapshot_distinguishes_none_and_unspecified():
    no_auth = platform_auth_snapshot("missav", {})
    unspecified = platform_auth_snapshot("external-without-metadata", {})

    assert no_auth["auth_status"] == "无需认证"
    assert unspecified["auth_status"] == "未声明"


def test_platform_count_contract_uses_platform_specific_units_and_defaults():
    bili = platform_count_contract("bilibili", {"max_pages": 20})
    xhs = platform_count_contract("xiaohongshu", {"max_items": 100})
    douyin = platform_count_contract("douyin", {"max_items": 100})

    assert bili["key"] == "max_pages"
    assert bili["unit"] == "pages"
    assert bili["value"] == 1
    assert [item["value"] for item in bili["options"]] == ["1", "2", "3", "5", "9999"]
    assert xhs["unit"] == "notes"
    assert xhs["value"] == 20
    assert douyin["unit"] == "videos"
    assert douyin["value"] == 20


def test_missav_proxy_contract_preserves_custom_value():
    contract = platform_proxy_contract("missav", {"proxy_app": "127.0.0.1:7897", "proxy_url": ""})

    assert contract["proxy"] == "\u81ea\u5b9a\u4e49"
    assert contract["proxy_custom_allowed"] is True
    assert contract["proxy_custom_active"] is True
    assert contract["proxy_custom_value"] == "127.0.0.1:7897"


def test_build_settings_snapshot_matches_frontend_contract_shape():
    snapshot = build_settings_snapshot(
        {
            "common": {
                "filename_template": "current",
                "default_open_mode": "builtin_player",
                "last_source": "bilibili",
            },
            "download": {"max_concurrent": 3, "max_retries": 3},
            "playback": {"default_player": "builtin_player"},
            "logging": {"retention_days": 1, "failed_record_retention_days": 7, "ui_log_max_display_count": 300},
            "appearance": {"language": "zh-CN"},
            "bilibili": {"max_pages": 1, "timeout": 60},
        },
        {"max_concurrent": 3, "max_retries": 3, "image_respects_concurrency": False},
        plugins=[SimpleNamespace(id="bilibili", name="Bilibili")],
    )

    assert snapshot["\u57fa\u7840\u8bbe\u7f6e"]["filename_template_label"] == "\u9ed8\u8ba4"
    assert snapshot["\u57fa\u7840\u8bbe\u7f6e"]["last_source"] == "bilibili"
    assert snapshot["\u4e0b\u8f7d\u8bbe\u7f6e"]["max_concurrent"] == 3
    assert snapshot["\u65e5\u5fd7\u8bbe\u7f6e"]["retention_days"] == 1
    assert snapshot["\u65e5\u5fd7\u8bbe\u7f6e"]["failed_record_retention_days"] == 7
    assert "failed_record_retention_days" in snapshot["\u65e5\u5fd7\u8bbe\u7f6e"]["_options"]
    assert snapshot["\u64ad\u653e\u8bbe\u7f6e"]["default_player"] == "builtin_player"
    assert snapshot["\u5e73\u53f0\u8bbe\u7f6e"][0]["id"] == "bilibili"
    assert snapshot["\u5e73\u53f0\u8bbe\u7f6e"][0]["count_unit"] == "pages"


def test_build_settings_snapshot_uses_platform_auth_provider():
    calls = []

    snapshot = build_settings_snapshot(
        {
            "common": {},
            "download": {},
            "playback": {},
            "logging": {},
            "appearance": {},
            "douyin": {"max_items": 20, "timeout": 60},
        },
        {"max_concurrent": 3, "max_retries": 3, "image_respects_concurrency": False},
        plugins=[SimpleNamespace(id="douyin", name="抖音")],
        auth_status_provider=lambda plugin_id, auth_cfg: calls.append((plugin_id, dict(auth_cfg)))
        or {"auth_status": "已认证", "auth_detail": "cached", "auth_cookie_file": "cookie.json"},
    )

    row = snapshot["平台设置"][0]
    assert calls == [("douyin", {})]
    assert row["auth_status"] == "已认证"
    assert row["auth_detail"] == "cached"
    assert row["auth_cookie_file"] == "cookie.json"


def test_build_download_options_snapshot_prefers_runtime_manager_values():
    data = {
        ("download", "max_concurrent"): 3,
        ("download", "max_retries"): 12,
        ("download", "video_only"): False,
        ("download", "image_respects_concurrency"): False,
    }

    def config_get(section, key, default=None):
        return data.get((section, key), default)

    cache_get = Mock(return_value=False)
    manager = SimpleNamespace(max_concurrent=6, video_only=True, image_respects_concurrency=True)

    assert build_download_options_snapshot(config_get, cache_get, manager) == {
        "auto_retry": False,
        "max_retries": 10,
        "max_concurrent": 5,
        "video_only": True,
        "image_respects_concurrency": True,
    }


def test_normalize_and_persist_download_options_caps_user_values():
    data = {
        ("download", "max_concurrent"): 3,
        ("download", "max_retries"): 3,
        ("download", "video_only"): False,
        ("download", "image_respects_concurrency"): False,
    }
    set_calls = []

    def config_get(section, key, default=None):
        return data.get((section, key), default)

    def config_set(section, key, value):
        set_calls.append((section, key, value))

    cache_get = Mock(return_value=True)
    cache_set = Mock()

    options = normalize_download_options_payload(
        {"max_concurrent": 24, "max_retries": 11, "video_only": True},
        config_get,
        cache_get,
    )

    assert options["max_concurrent"] == 5
    assert options["max_retries"] == 10
    assert options["video_only"] is True
    persist_download_options(config_set, cache_set, options)
    cache_set.assert_called_once_with("download.auto_retry", True, persist=False)
    assert ("download", "max_concurrent", 5) in set_calls
    assert ("download", "max_retries", 10) in set_calls
    assert ("download", "video_only", True) in set_calls
