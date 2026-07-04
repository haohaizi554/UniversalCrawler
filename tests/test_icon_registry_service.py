from __future__ import annotations

import sys
from pathlib import Path

from app.services.icon_registry import (
    FALLBACK_ICON_FILE,
    PLATFORM_ICON_FILES,
    icon_manifest,
    platform_icon_file,
    resolve_ui_icon_path,
    safe_icon_file,
    ui_icon_path,
)
from app.utils.qt_runtime import resolve_icon_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def test_icon_registry_blocks_path_traversal():
    assert safe_icon_file("../secret.png") == FALLBACK_ICON_FILE
    assert safe_icon_file("nested/icon.png") == FALLBACK_ICON_FILE
    assert Path(ui_icon_path("../secret.png")).name == FALLBACK_ICON_FILE

def test_icon_registry_resolves_bundle_icons_from_meipass(tmp_path, monkeypatch):
    bundle_icon = tmp_path / "UI" / "icon" / "bundle_only.png"
    bundle_icon.parent.mkdir(parents=True)
    bundle_icon.write_bytes(b"fake-icon")

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resolve_ui_icon_path("bundle_only.png") == bundle_icon

def test_qss_check_icon_resolves_from_bundle_meipass(tmp_path, monkeypatch):
    bundle_icon = tmp_path / "UI" / "icon" / "status_success.png"
    bundle_icon.parent.mkdir(parents=True)
    bundle_icon.write_bytes(b"fake-icon")

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    from app.ui.dialogs.dialog_styles import themed_dialog_stylesheet
    from app.ui.styles.themes import generate_stylesheet, theme_colors

    expected_url = bundle_icon.as_posix()
    assert expected_url in themed_dialog_stylesheet(theme_colors(False))
    assert expected_url in generate_stylesheet(False)

def test_qt_icon_loader_resolves_logical_ui_icon_from_bundle_meipass(tmp_path, monkeypatch):
    bundle_icon = tmp_path / "UI" / "icon" / "nav_settings.png"
    bundle_icon.parent.mkdir(parents=True)
    bundle_icon.write_bytes(b"fake-icon")

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resolve_icon_path([ui_icon_path("nav_settings.png")]) == bundle_icon

def test_platform_icons_use_managed_platform_prefix():
    for platform_id, file_name in PLATFORM_ICON_FILES.items():
        assert file_name.startswith("platform_")
        assert platform_icon_file(platform_id) == file_name

def test_icon_manifest_files_exist():
    manifest = icon_manifest()
    icon_dir = PROJECT_ROOT / "UI" / "icon"
    files: set[str] = {str(manifest["fallback"])}
    for section in ("actions", "nav", "platforms", "queue_status", "tools", "status", "log_levels"):
        files.update(str(value) for value in manifest[section].values())

    missing = sorted(file_name for file_name in files if not (icon_dir / file_name).is_file())
    assert missing == []
