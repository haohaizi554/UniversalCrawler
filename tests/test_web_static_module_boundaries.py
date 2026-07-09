from __future__ import annotations

import re
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
MODULES = (
    ("log_i18n.js", "UcpLogI18n"),
    ("frontend_runtime.js", "UcpFrontendRuntime"),
    ("list_pages.js", "UcpListPages"),
    ("log_center.js", "UcpLogCenter"),
    ("settings_controller.js", "UcpSettingsController"),
    ("dialog_controller.js", "UcpDialogController"),
    ("playback_controller.js", "UcpPlaybackController"),
)


def test_responsibility_modules_exist_and_export_namespaces() -> None:
    for filename, namespace in MODULES:
        content = (STATIC_DIR / filename).read_text(encoding="utf-8")
        assert f"window.{namespace} = Object.freeze" in content
        assert "function configure(options = {})" in content
        assert "function dispose()" in content


def test_responsibility_modules_load_before_app_in_dependency_order() -> None:
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    sources = re.findall(r'<script src="([^"]+)" defer></script>', index)
    expected = [f"/static/{name}?v=20260710-app-split" for name, _ in MODULES]
    assert [source for source in sources if source in expected] == expected
    assert sources.index(expected[-1]) < next(
        index for index, source in enumerate(sources) if source.startswith("/static/app.js?")
    )
