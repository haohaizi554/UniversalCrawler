from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "packaging" / "assets"
WIZARD_IMAGE = ASSETS_DIR / "installer_wizard.bmp"
SMALL_IMAGE = ASSETS_DIR / "installer_small.bmp"


def _rounded_card_path(x: float, y: float, width: float, height: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, width, height), radius, radius)
    return path


def _paint_background(painter: QPainter, width: int, height: int) -> None:
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#0f172a"))
    gradient.setColorAt(0.45, QColor("#1d4ed8"))
    gradient.setColorAt(1.0, QColor("#38bdf8"))
    painter.fillRect(0, 0, width, height, gradient)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 28))
    painter.drawEllipse(QRectF(-40, height - 130, 180, 180))
    painter.drawEllipse(QRectF(width - 95, -20, 130, 130))
    painter.setBrush(QColor(255, 255, 255, 18))
    painter.drawEllipse(QRectF(width - 40, height - 90, 110, 110))


def _paint_logo_badge(painter: QPainter, x: float, y: float, size: float) -> None:
    badge = _rounded_card_path(x, y, size, size, 22)
    painter.fillPath(badge, QColor(255, 255, 255, 230))

    inner = _rounded_card_path(x + 10, y + 10, size - 20, size - 20, 16)
    painter.fillPath(inner, QColor("#1d4ed8"))

    pen = QPen(QColor("#bfdbfe"))
    pen.setWidth(3)
    painter.setPen(pen)
    painter.drawArc(QRectF(x + 18, y + 18, size - 36, size - 36), 25 * 16, 290 * 16)

    painter.setPen(QColor("white"))
    font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(x, y + 6, size, size), Qt.AlignmentFlag.AlignCenter, "U")


def _paint_wizard_image(path: Path) -> None:
    width, height = 202, 386
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_background(painter, width, height)
    _paint_logo_badge(painter, 34, 30, 96)

    painter.setPen(QColor("white"))
    title_font = QFont("Segoe UI", 19, QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.drawText(QRectF(24, 148, width - 30, 84), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "Universal\nCrawler Pro")

    painter.setPen(QColor(226, 232, 240))
    subtitle_font = QFont("Segoe UI", 10)
    painter.setFont(subtitle_font)
    painter.drawText(
        QRectF(26, 240, width - 36, 78),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        "多平台视频采集与下载\nWindows 安装程序",
    )

    painter.setPen(QColor(255, 255, 255, 120))
    painter.drawLine(26, 224, width - 28, 224)

    feature_card = _rounded_card_path(22, 286, width - 44, 72, 16)
    painter.fillPath(feature_card, QColor(15, 23, 42, 72))
    painter.setPen(QColor(248, 250, 252))
    painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
    painter.drawText(
        QRectF(34, 300, width - 68, 46),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        "• 内置 Chromium 浏览器内核\n• ffmpeg / m3u8 工具即装即用",
    )
    painter.end()
    image.save(str(path), "BMP")


def _paint_small_image(path: Path) -> None:
    width, height = 64, 64
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(QPointF(0, 0), QPointF(width, height))
    gradient.setColorAt(0.0, QColor("#1d4ed8"))
    gradient.setColorAt(1.0, QColor("#38bdf8"))
    painter.fillRect(0, 0, width, height, QColor("#f8fafc"))

    outer = _rounded_card_path(painter.viewport().x() + 6, painter.viewport().y() + 6, 43, 43, 12)
    painter.fillPath(outer, gradient)

    painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
    painter.drawRoundedRect(QRectF(6.5, 6.5, 42, 42), 12, 12)

    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    painter.drawText(QRectF(6, 6, 43, 43), Qt.AlignmentFlag.AlignCenter, "U")
    painter.end()
    image.save(str(path), "BMP")


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _paint_wizard_image(WIZARD_IMAGE)
    _paint_small_image(SMALL_IMAGE)
    app.quit()
    print(f"已生成安装资源: {WIZARD_IMAGE} | {SMALL_IMAGE}")


if __name__ == "__main__":
    main()
