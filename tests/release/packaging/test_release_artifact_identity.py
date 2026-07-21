"""Release revision identity must survive portable and installer packaging."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from tests.support.paths import PROJECT_ROOT


def _load_tool(filename: str, module_name: str):
    path = PROJECT_ROOT / "packaging" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_portable_build_writes_atomic_runtime_release_identity(tmp_path, monkeypatch):
    tool = _load_tool("build_portable.py", "ucrawl_revision_build_portable")
    monkeypatch.setattr(tool, "DIST_DIR", tmp_path)
    monkeypatch.setenv("UCRAWL_RELEASE_REVISION", "3")
    monkeypatch.setenv("UCRAWL_RELEASE_TAG", f"v{tool.PACKAGE_VERSION}-r3")
    monkeypatch.setenv("UCRAWL_SOURCE_COMMIT", "a" * 40)

    identity, source_commit = tool._release_identity_from_environment()
    tool.write_release_identity(identity, source_commit)

    payload = json.loads((tmp_path / "release_identity.json").read_text(encoding="utf-8"))
    assert payload == {
        "version": tool.PACKAGE_VERSION,
        "revision": 3,
        "tag": f"v{tool.PACKAGE_VERSION}-r3",
        "sourceCommit": "a" * 40,
    }
    assert not (tmp_path / ".release_identity.json.tmp").exists()


def test_installer_uses_display_revision_numeric_file_version_and_unique_name(
    tmp_path,
    monkeypatch,
):
    tool = _load_tool("build_installer.py", "ucrawl_revision_build_installer")
    monkeypatch.setenv("UCRAWL_RELEASE_REVISION", "3")
    monkeypatch.setenv("UCRAWL_RELEASE_TAG", f"v{tool.PACKAGE_VERSION}-r3")
    identity = tool._release_identity_from_environment()

    command = tool._build_iscc_command("ISCC.exe", output_dir=tmp_path, identity=identity)

    assert f"/DAppVersion={tool.PACKAGE_VERSION}-r3" in command
    assert f"/DVersionInfoVersion={tool.PACKAGE_VERSION}.3" in command
    assert f"/DOutputBaseFilename={tool.INSTALLER_BASENAME}-r3" in command
    assert tool.get_setup_exe_path(identity).name == f"{tool.INSTALLER_BASENAME}-r3.exe"
