from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from PyQt6.QtGui import QGuiApplication, QImage, QImageReader

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool import icon_builder
from release_tool.icon_builder import (
    ICON_SIZES,
    build_release_builder_icon,
    release_builder_icon_path,
)


SOURCE_PNG = PROJECT_ROOT / "packaging" / "release_tool" / "assets" / "release-builder.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class IcoEntry:
    width: int
    height: int
    payload: bytes


@pytest.fixture(scope="session")
def qapp():
    return QGuiApplication.instance() or QGuiApplication([])


def read_ico_directory(path: Path) -> tuple[IcoEntry, ...]:
    payload = path.read_bytes()
    reserved, icon_type, count = struct.unpack_from("<HHH", payload)
    assert (reserved, icon_type) == (0, 1)

    entries = []
    for index in range(count):
        width, height, color_count, reserved, planes, bit_count, size, offset = struct.unpack_from(
            "<BBBBHHII", payload, 6 + index * 16
        )
        assert color_count == reserved == 0
        assert (planes, bit_count) == (1, 32)
        entries.append(
            IcoEntry(
                width=width or 256,
                height=height or 256,
                payload=payload[offset : offset + size],
            )
        )
    return tuple(entries)


def test_release_builder_ico_contains_all_standard_sizes(tmp_path, qapp):
    destination = tmp_path / "release-builder.ico"

    assert build_release_builder_icon(SOURCE_PNG, destination) == destination

    entries = read_ico_directory(destination)
    assert ICON_SIZES == (16, 20, 24, 32, 40, 48, 64, 128, 256)
    assert [(entry.width, entry.height) for entry in entries] == [(size, size) for size in ICON_SIZES]
    assert all(entry.payload.startswith(PNG_SIGNATURE) for entry in entries)
    for entry, size in zip(entries, ICON_SIZES):
        image = QImage.fromData(entry.payload, "PNG")
        assert not image.isNull()
        assert image.size().width() == image.size().height() == size
        assert image.hasAlphaChannel()


def test_release_builder_icon_preserves_alpha_source_and_destination(tmp_path, qapp):
    source_bytes = SOURCE_PNG.read_bytes()
    source_image = QImageReader(str(SOURCE_PNG)).read()
    destination = tmp_path / "nested" / "release-builder.ico"

    build_release_builder_icon(SOURCE_PNG, destination)

    assert source_image.hasAlphaChannel()
    assert SOURCE_PNG.read_bytes() == source_bytes
    assert destination.is_file()


def test_release_builder_icon_removes_temporary_file_when_replace_fails(tmp_path, monkeypatch, qapp):
    destination = tmp_path / "release-builder.ico"

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(icon_builder.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        build_release_builder_icon(SOURCE_PNG, destination)

    assert not destination.exists()
    assert list(tmp_path.glob(".release-builder.ico.*.tmp")) == []


def test_release_builder_icon_path_resolves_source_and_frozen_assets(monkeypatch, tmp_path):
    assert release_builder_icon_path() == SOURCE_PNG.with_suffix(".ico")

    bundle_root = tmp_path / "bundle"
    monkeypatch.setattr(icon_builder.sys, "frozen", True, raising=False)
    monkeypatch.setattr(icon_builder.sys, "_MEIPASS", str(bundle_root), raising=False)

    assert release_builder_icon_path() == (
        bundle_root.resolve() / "packaging" / "release_tool" / "assets" / "release-builder.ico"
    )
