"""视频表面双击契约测试。"""

from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.gui


def test_video_surface_emits_double_click_signal() -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QSignalSpy, QTest
    from PyQt6.QtWidgets import QApplication

    from app.ui.widgets.video import ClickableVideoWidget

    app = QApplication.instance() or QApplication([])
    widget = ClickableVideoWidget()
    widget.resize(160, 90)
    widget.show()
    spy = QSignalSpy(widget.sig_double_click)

    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton)
    app.processEvents()

    assert widget.objectName() == "VideoSurface"
    assert len(spy) == 1
    widget.close()
    widget.deleteLater()
