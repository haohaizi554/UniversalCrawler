"""Build and locate the release builder's dedicated multi-size icon."""

from __future__ import annotations

import os
import struct
import sys
import uuid
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QImageReader, QPainter


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
_ASSET_DIRECTORY = Path("packaging") / "release_tool" / "assets"
_ICON_NAME = "release-builder.ico"


def build_release_builder_icon(source: Path, destination: Path) -> Path:
    """Encode a transparent PNG layer for every required ICO size."""
    source = Path(source)
    destination = Path(destination)
    layers = tuple(_png_layer(source, size) for size in ICON_SIZES)
    payload = _encode_ico(layers)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def release_builder_icon_path() -> Path:
    """Return the source or PyInstaller-bundled release builder ICO path."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root).resolve() / _ASSET_DIRECTORY / _ICON_NAME
    return Path(__file__).resolve().parent / "assets" / _ICON_NAME


def _png_layer(source: Path, size: int) -> bytes:
    reader = QImageReader(str(source))
    image = reader.read()
    if image.isNull():
        raise ValueError(f"cannot read icon source {source}: {reader.errorString()}")

    scaled = image.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not canvas.save(buffer, "PNG"):
        raise ValueError(f"cannot encode {size}px icon layer")
    return bytes(buffer.data())


def _encode_ico(layers: tuple[bytes, ...]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(layers))
    offset = len(header) + len(layers) * 16
    directory = []
    for size, layer in zip(ICON_SIZES, layers):
        encoded_size = 0 if size == 256 else size
        directory.append(
            struct.pack(
                "<BBBBHHII",
                encoded_size,
                encoded_size,
                0,
                0,
                1,
                32,
                len(layer),
                offset,
            )
        )
        offset += len(layer)
    return header + b"".join(directory) + b"".join(layers)


def main() -> int:
    assets = Path(__file__).resolve().parent / "assets"
    build_release_builder_icon(assets / "release-builder.png", assets / _ICON_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
