"""Task selection dialog shown after spider scanning completes."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.config import cfg
from app.ui.styles import generate_stylesheet


#任务选择对话框
class SelectionDialog(QDialog):
    """Lets the user choose which scanned items should enter the queue."""

    def __init__(self, parent, title="\u4efb\u52a1\u6e05\u5355\u786e\u8ba4", items=None):
        """初始化当前实例并准备运行所需的状态，供 `SelectionDialog` 使用。"""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 600)
        self.selected_indices = []
        self.items = items or []
        self.setStyleSheet(parent.styleSheet() if parent else generate_stylesheet(cfg.get("common", "dark_theme", True)))
        self.init_ui()

    def init_ui(self):
        """执行 `init_ui` 对应的业务逻辑，供 `SelectionDialog` 使用。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QLabel(
            f"\u5171\u626b\u63cf\u5230 {len(self.items)} \u4e2a\u8d44\u6e90\uff0c\u8bf7\u52fe\u9009\u9700\u8981\u4e0b\u8f7d\u7684\u9879\u76ee\uff1a"
        )
        header.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(header)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(
            ["\u9009\u62e9", "\u89c6\u9891\u6807\u9898 / \u63cf\u8ff0"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.populate_table()
        layout.addWidget(self.table)

        btn_box = QFrame()
        btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_all = QPushButton("\u5168\u9009")
        self.btn_invert = QPushButton("\u53cd\u9009")
        self.btn_all.setFixedSize(80, 30)
        self.btn_invert.setFixedSize(80, 30)
        self.btn_all.clicked.connect(self.select_all)
        self.btn_invert.clicked.connect(self.select_invert)
        btn_layout.addWidget(self.btn_all)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("\u53d6\u6d88\u4efb\u52a1")
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.setFixedSize(100, 35)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("\u5f00\u59cb\u4e0b\u8f7d")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setFixedSize(120, 35)
        self.btn_confirm.clicked.connect(self.confirm_selection)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addWidget(btn_box)

    def populate_table(self):
        """执行 `populate_table` 对应的业务逻辑，供 `SelectionDialog` 使用。"""
        self.table.setRowCount(len(self.items))
        for index, item_data in enumerate(self.items):
            # Keep the checkbox centered by wrapping it in a tiny frame.
            chk_widget = QFrame()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(True)
            chk_layout.addWidget(chk)
            self.table.setCellWidget(index, 0, chk_widget)

            title_item = QTableWidgetItem(
                item_data.get("title", "\u672a\u77e5\u6807\u9898")
            )
            title_item.setFlags(title_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(index, 1, title_item)

    def select_all(self):
        """执行 `select_all` 对应的业务逻辑，供 `SelectionDialog` 使用。"""
        for index in range(self.table.rowCount()):
            widget = self.table.cellWidget(index, 0)
            chk = widget.findChild(QCheckBox)
            chk.setChecked(True)

    def select_invert(self):
        """执行 `select_invert` 对应的业务逻辑，供 `SelectionDialog` 使用。"""
        for index in range(self.table.rowCount()):
            widget = self.table.cellWidget(index, 0)
            chk = widget.findChild(QCheckBox)
            chk.setChecked(not chk.isChecked())

    def confirm_selection(self):
        """执行 `confirm_selection` 对应的业务逻辑，供 `SelectionDialog` 使用。"""
        self.selected_indices = []
        for index in range(self.table.rowCount()):
            widget = self.table.cellWidget(index, 0)
            chk = widget.findChild(QCheckBox)
            if chk.isChecked():
                self.selected_indices.append(index)
        self.accept()
