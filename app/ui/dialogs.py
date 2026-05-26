# app/ui/dialogs.py

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QHeaderView, 
                             QLabel, QCheckBox, QFrame)
from PyQt6.QtCore import Qt
from app.ui.styles import DARK_STYLESHEET

class SelectionDialog(QDialog):
    # 通用任务选择弹窗
    # 用于在爬取到链接列表后，让用户勾选需要下载的项目
    def __init__(self, parent, title="任务清单确认", items=None):
        # :param items: list of dict, e.g. [{"title": "视频A", "status": "待下载"}, ...]
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 600)
        self.selected_indices = []
        self.items = items or []
        # 应用暗黑主题
        self.setStyleSheet(DARK_STYLESHEET)
        self.init_ui()
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        # 1. 顶部提示
        header = QLabel(f"📋 共扫描到 {len(self.items)} 个资源，请勾选需要下载的项目：")
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #e0e0e0;")
        layout.addWidget(header)
        # 2. 列表区域
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["选择", "视频标题 / 描述"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("border: 1px solid #333; background-color: #1e1e1e;")
        self.populate_table()
        layout.addWidget(self.table)
        # 3. 底部按钮区
        btn_box = QFrame()
        btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        # 左侧操作
        self.btn_all = QPushButton("全选")
        self.btn_invert = QPushButton("反选")
        self.btn_all.setFixedSize(80, 30)
        self.btn_invert.setFixedSize(80, 30)
        self.btn_all.clicked.connect(self.select_all)
        self.btn_invert.clicked.connect(self.select_invert)
        btn_layout.addWidget(self.btn_all)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()
        # 右侧确认
        self.btn_cancel = QPushButton("取消任务")
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.setFixedSize(100, 35)
        self.btn_cancel.clicked.connect(self.reject) # 关闭并返回 Rejected
        self.btn_confirm = QPushButton("⬇️ 开始下载")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setFixedSize(120, 35)
        self.btn_confirm.clicked.connect(self.confirm_selection)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addWidget(btn_box)
    def populate_table(self):
        self.table.setRowCount(len(self.items))
        for i, item_data in enumerate(self.items):
            # 复选框列 (居中)
            chk_widget = QFrame()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0,0,0,0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(True) # 默认全选
            chk_layout.addWidget(chk)
            self.table.setCellWidget(i, 0, chk_widget)
            # 标题列
            title_item = QTableWidgetItem(item_data.get('title', '未知标题'))
            title_item.setFlags(title_item.flags() ^ Qt.ItemFlag.ItemIsEditable) # 只读
            self.table.setItem(i, 1, title_item)
    def select_all(self):
        for i in range(self.table.rowCount()):
            widget = self.table.cellWidget(i, 0)
            chk = widget.findChild(QCheckBox)
            chk.setChecked(True)
    def select_invert(self):
        for i in range(self.table.rowCount()):
            widget = self.table.cellWidget(i, 0)
            chk = widget.findChild(QCheckBox)
            chk.setChecked(not chk.isChecked())
    def confirm_selection(self):
        self.selected_indices = []
        for i in range(self.table.rowCount()):
            widget = self.table.cellWidget(i, 0)
            chk = widget.findChild(QCheckBox)
            if chk.isChecked():
                self.selected_indices.append(i)
        self.accept() # 关闭并返回 Accepted