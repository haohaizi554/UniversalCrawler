import sys

from app.ui.viewmodels.log_platforms import (
    PlatformUiMeta,
    builtin_platform_metas,
    load_platform_options,
    platform_icon_file_for_id,
)


def test_builtin_log_platforms_cover_supported_sources():
    metas = builtin_platform_metas()

    for platform_id in ("douyin", "bilibili", "kuaishou", "missav", "xiaohongshu", "system"):
        assert platform_id in metas
        assert isinstance(metas[platform_id], PlatformUiMeta)

    assert "bv" in tuple(alias.lower() for alias in metas["bilibili"].aliases)
    assert platform_icon_file_for_id("system", metas["system"]) == ""


def test_log_platform_icons_resolve_from_pyinstaller_bundle(tmp_path, monkeypatch):
    bundle_icon = tmp_path / "bundle" / "UI" / "icon" / "platform_bilibili.png"
    bundle_icon.parent.mkdir(parents=True)
    bundle_icon.write_bytes(b"fake-icon")
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    monkeypatch.chdir(work_dir)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    metas = builtin_platform_metas()

    assert metas["bilibili"].icon_path == str(bundle_icon)
    assert platform_icon_file_for_id("bilibili", metas["bilibili"]) == "platform_bilibili.png"


def test_load_platform_options_prefers_snapshot_entries_and_keeps_builtins():
    options = load_platform_options(
        {
            "platforms": [
                {"id": "bilibili", "name": "B站"},
                {"id": "custom_site", "name": "Custom Site"},
            ]
        }
    )
    by_id = {item.id: item for item in options}

    assert options[0].id == "all"
    assert by_id["bilibili"].label == "B站"
    assert by_id["custom_site"].label == "Custom Site"
    assert by_id["custom_site"].aliases == ("custom_site",)
    for platform_id in ("douyin", "kuaishou", "missav", "xiaohongshu", "system"):
        assert platform_id in by_id


def test_load_platform_options_can_read_settings_snapshot_platform_rows():
    options = load_platform_options(
        {
            "settings_snapshot": {
                "平台设置": [
                    {"platform_id": "xiaohongshu", "label": "小红书"},
                    {"id": "local_plugin", "label": "本地插件"},
                ]
            }
        }
    )
    by_id = {item.id: item for item in options}

    assert by_id["xiaohongshu"].label == "小红书"
    assert by_id["local_plugin"].label == "本地插件"
