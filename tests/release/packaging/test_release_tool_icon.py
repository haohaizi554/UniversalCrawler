from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QImageReader

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
COMMITTED_ICO = SOURCE_PNG.with_suffix(".ico")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class IcoEntry:
    width: int
    height: int
    offset: int
    size: int
    payload: bytes


@pytest.fixture(scope="session")
def qapp():
    return QGuiApplication.instance() or QGuiApplication([])


def read_ico_directory(path: Path) -> tuple[IcoEntry, ...]:
    payload = path.read_bytes()
    reserved, icon_type, count = struct.unpack_from("<HHH", payload)
    assert (reserved, icon_type) == (0, 1)

    entries = []
    directory_end = 6 + count * 16
    previous_end = directory_end
    for index in range(count):
        width, height, color_count, reserved_byte, planes, bit_count, size, offset = struct.unpack_from(
            "<BBBBHHII", payload, 6 + index * 16
        )
        assert color_count == reserved_byte == 0
        assert (planes, bit_count) == (1, 32)
        assert size > 0
        assert offset >= directory_end
        assert offset == previous_end
        end = offset + size
        assert end <= len(payload)
        entries.append(
            IcoEntry(
                width=width or 256,
                height=height or 256,
                offset=offset,
                size=size,
                payload=payload[offset:end],
            )
        )
        previous_end = end
    assert previous_end == len(payload)
    return tuple(entries)


def assert_standard_release_builder_ico(path: Path) -> None:
    entries = read_ico_directory(path)
    assert ICON_SIZES == (16, 20, 24, 32, 40, 48, 64, 128, 256)
    assert [(entry.width, entry.height) for entry in entries] == [(size, size) for size in ICON_SIZES]
    assert all(entry.payload.startswith(PNG_SIGNATURE) for entry in entries)
    for entry, size in zip(entries, ICON_SIZES):
        image = QImage.fromData(entry.payload, "PNG")
        assert not image.isNull()
        assert image.size().width() == image.size().height() == size
        assert image.hasAlphaChannel()
        alphas = {
            image.pixelColor(x, y).alpha()
            for y in range(image.height())
            for x in range(image.width())
        }
        assert 0 in alphas
        assert any(alpha > 0 for alpha in alphas)


def alpha_bounds(image: QImage) -> tuple[int, int, int, int]:
    visible = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    ]
    assert visible
    return (
        min(x for x, _y in visible),
        min(y for _x, y in visible),
        max(x for x, _y in visible),
        max(y for _x, y in visible),
    )


def test_release_builder_ico_contains_all_standard_sizes(tmp_path, qapp):
    destination = tmp_path / "release-builder.ico"

    assert build_release_builder_icon(SOURCE_PNG, destination) == destination

    assert_standard_release_builder_ico(destination)


def test_committed_release_builder_ico_has_complete_contiguous_layers(qapp):
    assert_standard_release_builder_ico(COMMITTED_ICO)


@pytest.mark.parametrize(("source_width", "source_height"), ((80, 40), (40, 80)))
def test_release_builder_layers_aspect_fit_and_center_rectangular_source(
    tmp_path,
    qapp,
    source_width,
    source_height,
):
    source = tmp_path / f"source-{source_width}x{source_height}.png"
    source_image = QImage(source_width, source_height, QImage.Format.Format_ARGB32)
    source_image.fill(QColor(28, 96, 180, 255))
    assert source_image.save(str(source), "PNG")
    destination = tmp_path / f"source-{source_width}x{source_height}.ico"

    build_release_builder_icon(source, destination)

    for entry, size in zip(read_ico_directory(destination), ICON_SIZES):
        layer = QImage.fromData(entry.payload, "PNG")
        scaled_width = size if source_width > source_height else size // 2
        scaled_height = size if source_height > source_width else size // 2
        left = (size - scaled_width) // 2
        top = (size - scaled_height) // 2
        assert alpha_bounds(layer) == (
            left,
            top,
            left + scaled_width - 1,
            top + scaled_height - 1,
        )


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
    original_bytes = b"existing destination"
    destination.write_bytes(original_bytes)

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(icon_builder.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        build_release_builder_icon(SOURCE_PNG, destination)

    assert destination.read_bytes() == original_bytes
    assert list(tmp_path.glob(".release-builder.ico.*.tmp")) == []


def test_release_builder_icon_path_resolves_source_and_frozen_assets(monkeypatch, tmp_path):
    assert release_builder_icon_path() == COMMITTED_ICO

    bundle_root = tmp_path / "bundle"
    packaged_icon = (
        bundle_root.resolve() / "packaging" / "release_tool" / "assets" / "release-builder.ico"
    )
    packaged_icon.parent.mkdir(parents=True)
    packaged_icon.write_bytes(COMMITTED_ICO.read_bytes())
    monkeypatch.setattr(icon_builder.sys, "frozen", True, raising=False)
    monkeypatch.setattr(icon_builder.sys, "_MEIPASS", str(bundle_root), raising=False)

    resolved = release_builder_icon_path()
    assert resolved == packaged_icon
    assert resolved.read_bytes() == COMMITTED_ICO.read_bytes()
