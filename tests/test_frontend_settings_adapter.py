from types import SimpleNamespace

from app.services.frontend_settings_adapter import (
    build_settings_snapshot,
    platform_count_contract,
    platform_proxy_contract,
)


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
            "common": {"filename_template": "current", "default_open_mode": "builtin_player"},
            "download": {"max_concurrent": 3, "max_retries": 3},
            "playback": {"default_player": "builtin_player"},
            "logging": {"retention_days": 1, "ui_log_max_display_count": 300},
            "appearance": {"language": "zh-CN"},
            "bilibili": {"max_pages": 1, "timeout": 60},
        },
        {"max_concurrent": 3, "max_retries": 3, "image_respects_concurrency": False},
        plugins=[SimpleNamespace(id="bilibili", name="Bilibili")],
    )

    assert snapshot["\u57fa\u7840\u8bbe\u7f6e"]["filename_template_label"] == "\u9ed8\u8ba4"
    assert snapshot["\u4e0b\u8f7d\u8bbe\u7f6e"]["max_concurrent"] == 3
    assert snapshot["\u65e5\u5fd7\u8bbe\u7f6e"]["retention_days"] == 1
    assert snapshot["\u64ad\u653e\u8bbe\u7f6e"]["default_player"] == "builtin_player"
    assert snapshot["\u5e73\u53f0\u8bbe\u7f6e"][0]["id"] == "bilibili"
    assert snapshot["\u5e73\u53f0\u8bbe\u7f6e"][0]["count_unit"] == "pages"
