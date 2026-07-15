"""提供文件关联选择对话框。"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.components.theme_checkbox import ThemeCheckBox
from app.ui.dialogs.chromed_dialog import ChromedDialog
from shared.localization import normalize_language, tr


@dataclass(frozen=True, slots=True)
class FileAssociationChoice:
    include_video: bool
    include_image: bool


class FileAssociationOption(QWidget):
    def __init__(self, text: str, *, checked: bool, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DialogOptionRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox = ThemeCheckBox(checked=checked, colors=colors, parent=self)
        self.label = QLabel(text, self)
        self.label.setObjectName("DialogOptionLabel")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.label, 1)

    def isChecked(self) -> bool:  # noqa: N802
        return self.checkbox.isChecked()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        self.checkbox.setChecked(checked)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)


class FileAssociationDialog(ChromedDialog):
    """选择要注册到 Windows 默认应用的媒体类型组。"""

    def __init__(self, parent=None, *, language: str = "zh-CN"):
        self._language = normalize_language(language)
        super().__init__(
            parent,
            title=self._tr("默认打开方式"),
            object_name="FileAssociationDialog",
            body_margins=(18, 18, 18, 18),
            body_spacing=12,
        )
        self.setMinimumWidth(460)

        layout = self.content_layout

        title = QLabel(self._tr("绑定默认打开方式"))
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        label = QLabel(self._tr("选择要注册到 Windows 默认应用的资源类型。Windows 可能会要求在系统默认应用页面再次确认。"))
        label.setObjectName("DialogDescription")
        label.setWordWrap(True)
        layout.addWidget(label)

        surface = QFrame()
        surface.setObjectName("DialogSurface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(14, 12, 14, 12)
        surface_layout.setSpacing(10)

        self.chk_video = FileAssociationOption(
            self._tr("视频资源（mp4、mkv、avi、mov、webm 等）"),
            checked=True,
            colors=self._colors,
        )
        surface_layout.addWidget(self.chk_video)

        self.chk_image = FileAssociationOption(
            self._tr("图片资源（jpg、png、gif、webp、bmp 等）"),
            checked=True,
            colors=self._colors,
        )
        surface_layout.addWidget(self.chk_image)
        layout.addWidget(surface)

        status = QLabel(self._tr("生效方式：注册成功后会立即影响之后的系统打开行为；若 Windows 拦截，程序会打开默认应用设置页供你确认。"))
        status.setObjectName("DialogStatus")
        status.setWordWrap(True)
        layout.addWidget(status)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch(1)
        self.btn_cancel = QPushButton(self._tr("取消"))
        self.btn_cancel.setObjectName("DialogNeutralButton")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_bind = QPushButton(self._tr("绑定"))
        self.btn_bind.setObjectName("DialogPrimaryButton")
        self.btn_bind.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bind.clicked.connect(self.accept)
        button_row.addWidget(self.btn_cancel)
        button_row.addWidget(self.btn_bind)
        layout.addLayout(button_row)

    def choice(self) -> FileAssociationChoice:
        return FileAssociationChoice(
            include_video=self.chk_video.isChecked(),
            include_image=self.chk_image.isChecked(),
        )

    def _tr(self, text: str) -> str:
        return tr(text, self._language)
