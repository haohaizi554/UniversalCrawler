"""File association selection dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

@dataclass(frozen=True, slots=True)
class FileAssociationChoice:
    include_video: bool
    include_image: bool

from app.ui.styles import apply_dialog_theme

class FileAssociationDialog(QDialog):
    """Ask which media groups should be registered for Windows default apps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("默认打开方式")
        self.setModal(True)
        apply_dialog_theme(self, parent=parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        label = QLabel("选择要注册到 Windows 默认应用的资源类型。")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.chk_video = QCheckBox("视频资源（mp4、mkv、avi、mov、webm 等）")
        self.chk_video.setChecked(True)
        layout.addWidget(self.chk_video)

        self.chk_image = QCheckBox("图片资源（jpg、png、gif、webp、bmp 等）")
        self.chk_image.setChecked(False)
        layout.addWidget(self.chk_image)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choice(self) -> FileAssociationChoice:
        return FileAssociationChoice(
            include_video=self.chk_video.isChecked(),
            include_image=self.chk_image.isChecked(),
        )
