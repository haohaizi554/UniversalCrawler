from __future__ import annotations

from pathlib import Path

from app.services.icon_registry import (
    FALLBACK_ICON_FILE,
    PLATFORM_ICON_FILES,
    icon_manifest,
    platform_icon_file,
    safe_icon_file,
    ui_icon_path,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def test_icon_registry_blocks_path_traversal():
    assert safe_icon_file("../secret.png") == FALLBACK_ICON_FILE
    assert safe_icon_file("nested/icon.png") == FALLBACK_ICON_FILE
    assert Path(ui_icon_path("../secret.png")).name == FALLBACK_ICON_FILE

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
