"""Host-neutral plugin manifest contracts."""

from __future__ import annotations

import json

import pytest

from app.core.plugins.base import BasePlugin


def test_external_plugin_gets_safe_generic_interactive_manifest():
    class ExternalPlugin(BasePlugin):
        id = "test_external_manifest"
        name = "External"

        def get_search_placeholder(self) -> str:
            return "输入外部资源"

    try:
        manifest = ExternalPlugin().get_manifest()

        assert manifest["id"] == "test_external_manifest"
        assert manifest["search_placeholder"] == "输入外部资源"
        assert manifest["interactive"]["input_label"] == "输入外部资源"
        assert manifest["interactive"]["fields"] == []
        assert manifest["interactive"]["auth"]["mode"] == "unspecified"
        json.dumps(manifest)
    finally:
        BasePlugin._subclasses.pop(ExternalPlugin.id, None)


def test_declared_interactive_manifest_is_json_safe():
    from app.core.plugins.metadata import (
        InteractiveChoice,
        InteractiveField,
        PlatformAuthSpec,
        PlatformInteractiveSpec,
    )

    class GuidedPlugin(BasePlugin):
        id = "test_guided_manifest"
        name = "Guided"
        interactive_spec = PlatformInteractiveSpec(
            input_label="输入作品链接",
            examples=("https://example.test/item/1",),
            empty_tip="检查插件连接",
            result_tip="使用插件解析器",
            fields=(
                InteractiveField(
                    key="max_items",
                    prompt="资源数量",
                    summary_label="数量",
                    choices=(
                        InteractiveChoice("1", 1),
                        InteractiveChoice("5", 5),
                    ),
                ),
            ),
            auth=PlatformAuthSpec(
                mode="cookie",
                config_key="guided_cookie_file",
                default_file="guided_auth.json",
                cookie_names=("session",),
                login_url="https://example.test/",
                login_description="打开浏览器登录",
                summary="浏览器登录",
            ),
        )

    try:
        manifest = GuidedPlugin().get_manifest()

        assert manifest["interactive"]["fields"][0] == {
            "key": "max_items",
            "prompt": "资源数量",
            "summary_label": "数量",
            "choices": [
                {"label": "1", "value": 1, "custom": False},
                {"label": "5", "value": 5, "custom": False},
            ],
            "custom_prompt": "",
        }
        assert manifest["interactive"]["auth"]["cookie_names"] == ["session"]
        json.dumps(manifest)
    finally:
        BasePlugin._subclasses.pop(GuidedPlugin.id, None)


def test_cookie_auth_requires_file_and_cookie_names():
    from app.core.plugins.metadata import PlatformAuthSpec

    with pytest.raises(ValueError, match="default_file and cookie_names"):
        PlatformAuthSpec(mode="cookie")


def test_every_builtin_declares_non_generic_interactive_metadata():
    from app.core.plugin_registry import registry

    manifests = {
        plugin.id: plugin.get_manifest()
        for plugin in registry.get_all_plugins()
    }

    assert manifests["douyin"]["interactive"]["fields"][0]["key"] == "max_items"
    assert (
        manifests["xiaohongshu"]["interactive"]["fields"][0]["summary_label"]
        == "笔记数"
    )
    assert manifests["bilibili"]["interactive"]["fields"][0]["key"] == "max_pages"
    assert [
        field["key"]
        for field in manifests["missav"]["interactive"]["fields"]
    ] == ["individual_only", "priority", "proxy"]
    assert manifests["kuaishou"]["interactive"]["auth"]["mode"] == "cookie"
    assert manifests["missav"]["interactive"]["auth"]["mode"] == "none"
