"""界面模块，封装 `app/ui/components/top_bar.py` 对应的窗口、对话框或界面组件逻辑。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QWidget

from app.core.plugin_registry import registry


#应用顶部操作栏，整合插件选择、任务启停、目录修改、日志查看等核心操作入口
class TopBarWidget(QFrame):
    """主界面顶栏，保持单行布局以减少视觉分裂。"""

    def __init__(self, is_dark_theme: bool):
        """初始化当前实例并准备运行所需的状态，供 `TopBarWidget` 使用。"""
        super().__init__()
        self.setObjectName("TopBar")
        self.setFixedHeight(50)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)
        self.layout.setSpacing(10)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.combo_source = QComboBox()
        self.plugins_list = registry.get_all_plugins()
        for plugin in self.plugins_list:
            self.combo_source.addItem(plugin.name, plugin.id)
        self.combo_source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_source.setFixedHeight(30)
        self.layout.addWidget(self.combo_source)

        self.inp_search = QLineEdit()
        self.inp_search.setFixedHeight(30)
        self.inp_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout.addWidget(self.inp_search, 1)

        self.container_dynamic = QWidget()
        self.layout_dynamic = QHBoxLayout(self.container_dynamic)
        self.layout_dynamic.setContentsMargins(0, 0, 0, 0)
        self.layout_dynamic.setSpacing(8)
        self.layout.addWidget(self.container_dynamic)

        self.btn_start = QPushButton("🚀 启动任务")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setFixedHeight(30)
        self.layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("🛑 停止")
        self.btn_stop.setObjectName("DangerBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setFixedHeight(30)
        self.layout.addWidget(self.btn_stop)

        self.btn_dir = QPushButton("📂 更改目录")
        self.btn_dir.setObjectName("DirBtn")
        self.btn_dir.setFixedHeight(30)
        self.layout.addWidget(self.btn_dir)

        self.btn_latest_log = QPushButton("📄 最新日志")
        self.btn_latest_log.setFixedHeight(30)
        self.layout.addWidget(self.btn_latest_log)

        self.btn_error_summary = QPushButton("🚨 错误摘要")
        self.btn_error_summary.setFixedHeight(30)
        self.layout.addWidget(self.btn_error_summary)

        self.btn_copy_trace = QPushButton("📋 复制Trace")
        self.btn_copy_trace.setFixedHeight(30)
        self.layout.addWidget(self.btn_copy_trace)

        self.btn_theme = QPushButton("🌙" if is_dark_theme else "☀️")
        self.btn_theme.setObjectName("ThemeBtn")
        self.btn_theme.setFixedHeight(30)
        self.btn_theme.setFixedWidth(40)
        self.btn_theme.setToolTip("切换主题")
        self.layout.addWidget(self.btn_theme)



    def set_theme_icon(self, is_dark_theme: bool) -> None:
        """设置 `theme_icon` 对应的值或运行状态，供 `TopBarWidget` 使用。"""
        self.btn_theme.setText("🌙" if is_dark_theme else "☀️")

    def set_crawl_running_state(self, is_running: bool, plugin_widget: QWidget | None) -> None:
        """设置 `crawl_running_state` 对应的值或运行状态，供 `TopBarWidget` 使用。"""
        self.btn_start.setEnabled(not is_running)
        self.btn_stop.setEnabled(is_running)
        self.inp_search.setEnabled(not is_running)
        self.combo_source.setEnabled(not is_running)
        if plugin_widget:
            plugin_widget.setEnabled(not is_running)
