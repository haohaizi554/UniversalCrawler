# app/ui/main_window.py

import os
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QProgressBar,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QFrame, QSplitter, QPlainTextEdit, QComboBox,
                             QFileDialog, QStyle, QSlider, QSizePolicy, QDialog, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QSettings, QSize, QByteArray
from PyQt6.QtGui import QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from app.ui.styles import DARK_STYLESHEET
from app.utils import cfg
from app.core.registry import registry
from app.ui.dialogs import SelectionDialog
from app.ui.widgets import ClickableVideoWidget

class MainWindow(QMainWindow):
    # 信号定义
    sig_start_crawl = pyqtSignal(str, str, dict)
    sig_stop_crawl = pyqtSignal()
    sig_change_dir = pyqtSignal()
    sig_play_video = pyqtSignal(str)
    sig_delete_video = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Crawler Pro")
        self.resize(1300, 850)
        self.setStyleSheet(DARK_STYLESHEET)

        if os.path.exists("favicon.ico"):
            self.setWindowIcon(QIcon("favicon.ico"))

        self.current_save_dir = cfg.get("common", "save_directory") or os.getcwd()
        self.current_plugin = None
        self.plugin_widget = None
        self.is_fullscreen_mode = False
        self.init_ui()
        self.load_initial_state()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # === [A] TopBar ===
        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        self.top_bar.setFixedHeight(50)

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 5, 10, 5)
        top_layout.setSpacing(10)
        top_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.combo_source = QComboBox()
        self.plugins_list = registry.get_all_plugins()
        for p in self.plugins_list:
            self.combo_source.addItem(p.name, p.id)
        self.combo_source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_source.setMinimumWidth(120)
        self.combo_source.setFixedHeight(30)
        self.combo_source.currentIndexChanged.connect(self.on_source_changed)
        top_layout.addWidget(self.combo_source)

        self.inp_search = QLineEdit()
        self.inp_search.setMinimumWidth(200)
        self.inp_search.setFixedHeight(30)
        self.inp_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_layout.addWidget(self.inp_search)

        self.container_dynamic = QWidget()
        self.layout_dynamic = QHBoxLayout(self.container_dynamic)
        self.layout_dynamic.setContentsMargins(0, 0, 0, 0)
        self.layout_dynamic.setSpacing(10)
        top_layout.addWidget(self.container_dynamic)

        self.btn_start = QPushButton("🚀 启动任务")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setFixedHeight(30)
        self.btn_start.setMinimumWidth(100)
        self.btn_start.clicked.connect(self.on_btn_start_clicked)
        top_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("🛑 停止")
        self.btn_stop.setObjectName("DangerBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setMinimumWidth(80)
        self.btn_stop.clicked.connect(lambda: self.sig_stop_crawl.emit())
        top_layout.addWidget(self.btn_stop)

        self.btn_dir = QPushButton("📂 更改目录")
        self.btn_dir.setObjectName("DirBtn")
        self.btn_dir.setFixedHeight(30)
        self.btn_dir.setMinimumWidth(100)
        self.btn_dir.clicked.connect(self.on_btn_dir_clicked)
        top_layout.addWidget(self.btn_dir)

        main_layout.addWidget(self.top_bar)

        # === [B] Splitter (主分割线: 左右) ===
        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.setHandleWidth(4)

        # --- Left Panel ---
        self.left_panel = QFrame()
        self.left_panel.setObjectName("ContentPanel")
        ll = QVBoxLayout(self.left_panel)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        header_bar = QFrame()
        header_bar.setObjectName("HeaderBar")
        header_bar.setFixedHeight(35)
        hl = QHBoxLayout(header_bar)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(QLabel("📋 下载队列"))
        hl.addWidget(QLabel(" | 保存至: ", styleSheet="color: #888;"))
        self.lbl_full_path = QLabel(self.current_save_dir)
        self.lbl_full_path.setObjectName("PathLabel")
        self.lbl_full_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(self.lbl_full_path)
        ll.addWidget(header_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["视频标题", "状态", "进度", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 80)
        ll.addWidget(self.table)

        self.main_split.addWidget(self.left_panel)

        # --- Right Panel ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.right_split = QSplitter(Qt.Orientation.Vertical)
        self.right_split.setHandleWidth(4)

        # 1. 上半部分：视频 + 控制条
        video_container = QFrame()
        video_container.setObjectName("ContentPanel")
        vl = QVBoxLayout(video_container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # [使用导入的控件]
        self.vid_w = ClickableVideoWidget()
        self.vid_w.sig_double_click.connect(self.toggle_fullscreen_mode)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.vid_w)

        self.ctrls = QFrame()
        self.ctrls.setFixedHeight(50)
        self.ctrls.setStyleSheet("background:#252526; border-top: 1px solid #333;")
        cl = QHBoxLayout(self.ctrls)
        cl.setContentsMargins(15, 0, 15, 0)
        cl.setSpacing(15)

        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_play.setStyleSheet("border-radius: 16px; background-color: #333; border: 1px solid #444;")
        self.btn_play.clicked.connect(self.toggle_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(lambda: setattr(self, 'is_slider_pressed', True))
        self.slider.sliderReleased.connect(self.on_slider_released)
        self.player.positionChanged.connect(self.on_player_position_changed)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))

        self.lbl_time = QLabel("00:00")
        self.lbl_time.setStyleSheet("color: #aaa; font-family: Consolas;")

        self.btn_fullscreen = QPushButton("[ 全屏 ]")
        self.btn_fullscreen.setFixedSize(60, 32)
        self.btn_fullscreen.setStyleSheet(
            "border-radius: 4px; background-color: #333; border: 1px solid #444; color: #eee; font-size: 12px;")
        self.btn_fullscreen.setToolTip("沉浸模式 (双击画面)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen_mode)

        cl.addWidget(self.btn_play)
        cl.addWidget(self.slider)
        cl.addWidget(self.lbl_time)
        cl.addWidget(self.btn_fullscreen)

        vl.addWidget(self.vid_w)
        vl.addWidget(self.ctrls)

        # 2. 下半部分：日志
        self.log_txt = QPlainTextEdit()
        self.log_txt.setReadOnly(True)
        self.log_txt.setStyleSheet("border-top: 1px solid #333; background-color: #111; color: #eee;")
        self.log_txt.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.right_split.addWidget(video_container)
        self.right_split.addWidget(self.log_txt)

        right_layout.addWidget(self.right_split)
        self.main_split.addWidget(right_container)
        main_layout.addWidget(self.main_split)

    # --- Logic ---

    def toggle_fullscreen_mode(self):
        if not self.is_fullscreen_mode:
            self.top_bar.hide()
            self.left_panel.hide()
            self.log_txt.hide()
            self.showFullScreen()
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.is_fullscreen_mode = True
            self.btn_fullscreen.setText("[ 退出 ]")
        else:
            self.top_bar.show()
            self.left_panel.show()
            self.log_txt.show()
            self.showNormal()
            self.layout().setContentsMargins(10, 10, 10, 10)
            self.is_fullscreen_mode = False
            self.btn_fullscreen.setText("[ 全屏 ]")

            state_hex = cfg.get("ui", "window_state")
            if state_hex: self.restoreState(QByteArray.fromHex(state_hex.encode()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen_mode:
            self.toggle_fullscreen_mode()
            event.accept()
        else:
            super().keyPressEvent(event)

    def load_initial_state(self):
        last_source_id = cfg.get("common", "last_source", "kuaishou")
        idx = self.combo_source.findData(last_source_id)
        if idx != -1:
            self.combo_source.setCurrentIndex(idx)
        else:
            self.combo_source.setCurrentIndex(0)
        self.on_source_changed(self.combo_source.currentIndex())

        self.lbl_full_path.setText(self.current_save_dir)
        self.lbl_full_path.setToolTip(self.current_save_dir)

        geo_hex = cfg.get("ui", "geometry")
        if geo_hex: self.restoreGeometry(QByteArray.fromHex(geo_hex.encode()))

        state_hex = cfg.get("ui", "window_state")
        if state_hex: self.restoreState(QByteArray.fromHex(state_hex.encode()))

        main_split_hex = cfg.get("ui", "main_splitter_state")
        if main_split_hex:
            self.main_split.restoreState(QByteArray.fromHex(main_split_hex.encode()))
        else:
            self.main_split.setSizes([400, 900])

        right_split_hex = cfg.get("ui", "right_splitter_state")
        if right_split_hex:
            self.right_split.restoreState(QByteArray.fromHex(right_split_hex.encode()))
        else:
            self.right_split.setSizes([600, 200])

    def closeEvent(self, e):
        cfg.save_ui_state(
            geometry=self.saveGeometry(),
            state=self.saveState(),
            main_splitter=self.main_split.saveState(),
            right_splitter=self.right_split.saveState(),
            is_fs=self.is_fullscreen_mode
        )
        e.accept()

    def on_btn_start_clicked(self):
        if not self.current_plugin:
            self.append_log("❌ 未选择有效模式")
            return

        keyword = self.inp_search.text().strip()
        if not keyword:
            self.append_log("⚠️ 请输入搜索内容！")
            return

        run_options = {}
        if self.plugin_widget:
            try:
                run_options = self.current_plugin.get_run_options(self.plugin_widget)
            except Exception as e:
                self.append_log(f"❌ 配置读取错误: {e}")
                return

        self.sig_start_crawl.emit(keyword, self.current_plugin.id, run_options)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.inp_search.setEnabled(False)
        self.combo_source.setEnabled(False)
        if self.plugin_widget: self.plugin_widget.setEnabled(False)

    def on_source_changed(self, index):
        plugin_id = self.combo_source.currentData()
        if not plugin_id: return

        self.current_plugin = registry.get_plugin(plugin_id)
        if not self.current_plugin: return

        self.inp_search.setPlaceholderText(self.current_plugin.get_search_placeholder())

        while self.layout_dynamic.count():
            item = self.layout_dynamic.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.plugin_widget = self.current_plugin.get_settings_widget(self.container_dynamic)
        if self.plugin_widget:
            self.layout_dynamic.addWidget(self.plugin_widget)
            self.plugin_widget.show()

        cfg.set("common", "last_source", plugin_id)

    def on_btn_dir_clicked(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.current_save_dir)
        if d:
            self.current_save_dir = d
            self.lbl_full_path.setText(d)
            self.lbl_full_path.setToolTip(d)
            cfg.set("common", "save_directory", d)
            self.sig_change_dir.emit()

    def add_video_row(self, video_item):
        row = self.table.rowCount()
        self.table.insertRow(row)
        t_item = QTableWidgetItem(video_item.title)
        t_item.setData(Qt.ItemDataRole.UserRole, video_item.id)
        t_item.setToolTip(video_item.title)
        self.table.setItem(row, 0, t_item)
        s_item = QTableWidgetItem(video_item.status)
        s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 1, s_item)
        pb = QProgressBar()
        pb.setValue(video_item.progress)
        self.table.setCellWidget(row, 2, pb)
        op_widget = QWidget()
        op_layout = QHBoxLayout(op_widget)
        op_layout.setContentsMargins(0, 0, 0, 0)
        op_layout.setSpacing(5)
        op_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_p = QPushButton()
        btn_p.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        btn_p.setFixedSize(26, 24)
        btn_p.clicked.connect(lambda: self.sig_play_video.emit(video_item.id))
        btn_d = QPushButton()
        btn_d.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        btn_d.setFixedSize(26, 24)
        btn_d.clicked.connect(lambda: self.sig_delete_video.emit(row, video_item.id))
        op_layout.addWidget(btn_p)
        op_layout.addWidget(btn_d)
        self.table.setCellWidget(row, 3, op_widget)

    def update_video_status(self, video_id, status, progress=None):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == video_id:
                self.table.item(r, 1).setText(status)
                if progress is not None: self.table.cellWidget(r, 2).setValue(progress)
                break

    def refresh_table_bindings(self):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if not item: continue
            vid = item.data(Qt.ItemDataRole.UserRole)
            widget = self.table.cellWidget(r, 3)
            if widget:
                layout = widget.layout()
                for i in range(layout.count()):
                    widget_item = layout.itemAt(i).widget()
                    if isinstance(widget_item, QPushButton):
                        if i == 1:
                            try:
                                widget_item.clicked.disconnect()
                            except:
                                pass
                            widget_item.clicked.connect(
                                lambda checked, row=r, v=vid: self.sig_delete_video.emit(row, v))

    def show_selection_dialog(self, items):
        dlg = SelectionDialog(self, items=items)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.append_log(f"✅ 用户确认了 {len(dlg.selected_indices)} 个任务")
            return dlg.selected_indices
        else:
            self.append_log("❌ 用户取消了任务")
            return None

    def append_log(self, msg):
        self.log_txt.appendHtml(f'<span style="color:#aaa;">{msg}</span>')
        self.log_txt.moveCursor(QTextCursor.MoveOperation.End)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def on_slider_released(self):
        self.is_slider_pressed = False
        self.player.setPosition(self.slider.value())

    def on_player_position_changed(self, pos):
        if not getattr(self, 'is_slider_pressed', False):
            self.slider.setValue(pos)
        self.lbl_time.setText(f"{self.format_time(pos)} / {self.format_time(self.player.duration())}")

    def format_time(self, ms):
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000)
        return f"{minutes:02}:{seconds:02}"