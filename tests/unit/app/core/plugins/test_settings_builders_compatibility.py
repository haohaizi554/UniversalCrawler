"""插件设置兼容导出必须保持惰性，不能让 core 导入时拉起 Qt。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.plugins import settings_builders
from app.core.plugins.run_options import build_missav_proxy_url


def test_proxy_builder_is_reexported_without_loading_ui() -> None:
    assert settings_builders.build_missav_proxy_url is build_missav_proxy_url


def test_ui_export_is_loaded_lazily_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    export_name = "build_douyin_settings_widget"
    sentinel = object()
    imported: list[str] = []
    settings_builders.__dict__.pop(export_name, None)

    def fake_import(name: str) -> SimpleNamespace:
        imported.append(name)
        return SimpleNamespace(**{export_name: sentinel})

    monkeypatch.setattr(settings_builders, "import_module", fake_import)
    try:
        assert settings_builders.__getattr__(export_name) is sentinel
        assert settings_builders.__dict__[export_name] is sentinel
        assert imported == ["app.ui.plugin_settings"]
    finally:
        settings_builders.__dict__.pop(export_name, None)


def test_unknown_compatibility_export_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="missing_export"):
        settings_builders.__getattr__("missing_export")
