"""Main window assembly layer."""

from PyQt6.QtCore import QByteArray, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QFileDialog, QDialog, QMainWindow, QSplitter, QVBoxLayout, QWidget

from app.config import cfg
from app.core.plugin_registry import registry
from app.ui.components.download_queue_panel import DownloadQueuePanel
from app.ui.components.log_panel import LogPanel
from app.ui.components.media_preview_panel import MediaPreviewPanel
from app.ui.components.top_bar import TopBarWidget
from app.ui.dialogs import SelectionDialog
from app.ui.plugin_settings import build_plugin_settings_widget, read_plugin_run_options
from app.ui.styles import generate_stylesheet
from app.utils.runtime_paths import resolve_resource_file, user_data_root


#所有 UI 组件的 “总容器” 和 “信号转发中枢”，只负责界面拼装、UI 交互和信号转发
class MainWindow(QMainWindow):
    """主窗口只负责拼装组件、转发 UI 信号，不承载业务逻辑。"""

    sig_start_crawl = pyqtSignal(str, str, dict)
    sig_stop_crawl = pyqtSignal()
    sig_theme_changed = pyqtSignal(bool)
    sig_change_dir = pyqtSignal()
    sig_play_video = pyqtSignal(str)
    sig_delete_video = pyqtSignal(int, str)
    sig_open_latest_log = pyqtSignal()
    sig_open_error_summary = pyqtSignal()
    sig_copy_trace_id = pyqtSignal(str)

    def __init__(self):
        """初始化当前实例并准备运行所需的状态，供 `MainWindow` 使用。"""
        super().__init__()
        self.setWindowTitle("Universal Crawler Pro")
        self.resize(1300, 850)
        self.is_dark_theme = cfg.get("common", "dark_theme", True)
        self.setStyleSheet(generate_stylesheet(self.is_dark_theme))

        icon_path = resolve_resource_file("favicon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.current_save_dir = cfg.get("common", "save_directory") or str(user_data_root())
        self.current_plugin = None
        self.plugin_widget = None
        self.is_fullscreen_mode = False

        self._build_ui()
        self._expose_component_refs()
        self._bind_component_signals()
        self.load_initial_state()

    def _build_ui(self) -> None:
        # 主窗口只负责拼装 UI，不在这里写下载/爬虫业务。
        """提供 `_build_ui` 对应的内部辅助逻辑，供 `MainWindow` 使用。"""
        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        self.top_bar = TopBarWidget(self.is_dark_theme)
        self.main_layout.addWidget(self.top_bar)

        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.setHandleWidth(4)

        self.left_panel = DownloadQueuePanel(self.current_save_dir, self)
        self.main_split.addWidget(self.left_panel)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.right_split = QSplitter(Qt.Orientation.Vertical)
        self.right_split.setHandleWidth(4)

        self.media_panel = MediaPreviewPanel(self)
        self.log_txt = LogPanel()

        self.right_split.addWidget(self.media_panel)
        self.right_split.addWidget(self.log_txt)
        right_layout.addWidget(self.right_split)
        self.main_split.addWidget(right_container)
        self.main_layout.addWidget(self.main_split)

        self.main_split.splitterMoved.connect(lambda: self.media_panel.scale_image_to_fit())
        self.right_split.splitterMoved.connect(lambda: self.media_panel.scale_image_to_fit())

    def _expose_component_refs(self) -> None:
        # 仅暴露主窗口自身仍直接使用的少量控件引用，避免继续把子组件内部实现泄漏出去。
        """提供 `_expose_component_refs` 对应的内部辅助逻辑，供 `MainWindow` 使用。"""
        self.combo_source = self.top_bar.combo_source
        self.inp_search = self.top_bar.inp_search
        self.container_dynamic = self.top_bar.container_dynamic
        self.layout_dynamic = self.top_bar.layout_dynamic
        self.btn_start = self.top_bar.btn_start
        self.btn_stop = self.top_bar.btn_stop
        self.btn_dir = self.top_bar.btn_dir
        self.btn_latest_log = self.top_bar.btn_latest_log
        self.btn_error_summary = self.top_bar.btn_error_summary
        self.btn_copy_trace = self.top_bar.btn_copy_trace
        self.btn_theme = self.top_bar.btn_theme
        self.btn_fullscreen = self.media_panel.btn_fullscreen

    def _bind_component_signals(self) -> None:
        """组件内部事件统一转成主窗口信号，方便控制器集中接管。"""
        self.combo_source.currentIndexChanged.connect(self.on_source_changed)
        self.btn_start.clicked.connect(self.on_btn_start_clicked)
        self.btn_stop.clicked.connect(lambda: self.sig_stop_crawl.emit())
        self.btn_dir.clicked.connect(self.on_btn_dir_clicked)
        self.btn_latest_log.clicked.connect(lambda: self.sig_open_latest_log.emit())
        self.btn_error_summary.clicked.connect(lambda: self.sig_open_error_summary.emit())
        self.btn_copy_trace.clicked.connect(self._on_copy_trace_clicked)
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.media_panel.sig_toggle_fullscreen.connect(self.toggle_fullscreen_mode)

    def bind_video_rename(self, on_rename) -> None:
        """执行 `bind_video_rename` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.left_panel.bind_title_rename(on_rename)

    def toggle_theme(self) -> None:
        """执行 `toggle_theme` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.is_dark_theme = not self.is_dark_theme
        self.setStyleSheet(generate_stylesheet(self.is_dark_theme))
        self.top_bar.set_theme_icon(self.is_dark_theme)
        cfg.set("common", "dark_theme", self.is_dark_theme)
        cfg.set("common", "theme", "dark" if self.is_dark_theme else "light")
        self.append_log(f"🎨 已切换到{'深色' if self.is_dark_theme else '浅色'}主题")
        self.sig_theme_changed.emit(self.is_dark_theme)

    def toggle_fullscreen_mode(self) -> None:
        """执行 `toggle_fullscreen_mode` 对应的业务逻辑，供 `MainWindow` 使用。"""
        if not self.is_fullscreen_mode:
            self.top_bar.hide()
            self.left_panel.hide()
            self.log_txt.hide()
            self.showFullScreen()
            self._set_main_margins(0)
            self.is_fullscreen_mode = True
            self.btn_fullscreen.setText("[ 退出 ]")
            return

        self.top_bar.show()
        self.left_panel.show()
        self.log_txt.show()
        self.showNormal()
        self._set_main_margins(10)
        self.is_fullscreen_mode = False
        self.btn_fullscreen.setText("[ 全屏 ]")
        state_hex = cfg.get("ui", "window_state")
        if state_hex:
            self.restoreState(QByteArray.fromHex(state_hex.encode()))

    def keyPressEvent(self, event) -> None:
        """执行 `keyPressEvent` 对应的业务逻辑，供 `MainWindow` 使用。"""
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen_mode:
            self.toggle_fullscreen_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def load_initial_state(self) -> None:
        """恢复主题、来源选择和 splitter 状态。"""
        last_source_id = cfg.get("common", "last_source", "kuaishou")
        index = self.combo_source.findData(last_source_id)
        self.combo_source.setCurrentIndex(index if index != -1 else 0)
        self.on_source_changed(self.combo_source.currentIndex())
        self.left_panel.set_current_save_dir(self.current_save_dir)

        geometry_hex = cfg.get("ui", "geometry")
        if geometry_hex:
            self.restoreGeometry(QByteArray.fromHex(geometry_hex.encode()))

        state_hex = cfg.get("ui", "window_state")
        if state_hex:
            self.restoreState(QByteArray.fromHex(state_hex.encode()))

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

    def closeEvent(self, event) -> None:
        """执行 `closeEvent` 对应的业务逻辑，供 `MainWindow` 使用。"""
        _geometry = self.saveGeometry()
        _state = self.saveState()
        _main_splitter = self.main_split.saveState()
        _right_splitter = self.right_split.saveState()
        cfg.save_ui_state(
            geometry=_geometry,
            state=_state,
            main_splitter=_main_splitter,
            right_splitter=_right_splitter,
            is_fs=self.is_fullscreen_mode,
        )
        event.accept()

    def on_btn_start_clicked(self) -> None:
        """执行 `on_btn_start_clicked` 对应的业务逻辑，供 `MainWindow` 使用。"""
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
                run_options = read_plugin_run_options(self.current_plugin.id, self.plugin_widget)
            except (AttributeError, TypeError, ValueError) as exc:
                self.append_log(f"❌ 配置读取错误: {exc}")
                return
        self.sig_start_crawl.emit(keyword, self.current_plugin.id, run_options)

    def on_source_changed(self, _index: int) -> None:
        # 切换平台时重建动态配置区域，避免把各平台差异写死在主窗口里。
        """执行 `on_source_changed` 对应的业务逻辑，供 `MainWindow` 使用。"""
        plugin_id = self.combo_source.currentData()
        if not plugin_id:
            return
        self.current_plugin = registry.get_plugin(plugin_id)
        if not self.current_plugin:
            return

        placeholder = self.current_plugin.get_search_placeholder()
        self.inp_search.setPlaceholderText(placeholder)
        while self.layout_dynamic.count():
            item = self.layout_dynamic.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.plugin_widget = build_plugin_settings_widget(self.current_plugin.id, self.container_dynamic)
        if self.plugin_widget:
            self.layout_dynamic.addWidget(self.plugin_widget)
            self.plugin_widget.show()
        cfg.set("common", "last_source", plugin_id)

    def set_crawl_running_state(self, is_running: bool) -> None:
        """设置 `crawl_running_state` 对应的值或运行状态，供 `MainWindow` 使用。"""
        self.top_bar.set_crawl_running_state(is_running, self.plugin_widget)

    def on_btn_dir_clicked(self) -> None:
        """执行 `on_btn_dir_clicked` 对应的业务逻辑，供 `MainWindow` 使用。"""
        selected_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", self.current_save_dir)
        if selected_dir:
            self.current_save_dir = selected_dir
            self.left_panel.set_current_save_dir(selected_dir)
            cfg.set("common", "save_directory", selected_dir)
            self.sig_change_dir.emit()

    def add_video_row(self, video_item) -> None:
        """执行 `add_video_row` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.left_panel.add_video_row(
            video_item,
            on_play=lambda video_id: self.sig_play_video.emit(video_id),
            on_delete=self._emit_delete_for_video,
        )

    def update_video_status(self, video_id, status, progress=None) -> None:
        """更新 `video_status` 对应的状态或数据内容，供 `MainWindow` 使用。"""
        self.left_panel.update_video_status(video_id, status, progress)

    def refresh_table_bindings(self) -> None:
        """执行 `refresh_table_bindings` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.left_panel.refresh_delete_bindings(self._emit_delete_for_video)

    def clear_video_rows(self) -> None:
        """执行 `clear_video_rows` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.left_panel.clear_rows()

    def remove_video_row(self, row: int) -> None:
        """执行 `remove_video_row` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.left_panel.remove_row(row)

    def show_selection_dialog(self, items):
        # 选择弹窗必须由 UI 线程创建和持有，爬虫线程只等待结果。
        """执行 `show_selection_dialog` 对应的业务逻辑，供 `MainWindow` 使用。"""
        dialog = SelectionDialog(self, items=items)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.append_log(f"✅ 用户确认了 {len(dialog.selected_indices)} 个任务")
            return dialog.selected_indices
        self.append_log("❌ 用户取消了任务")
        return None

    def append_log(self, msg) -> None:
        """执行 `append_log` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.log_txt.append_log(str(msg))

    def _set_main_margins(self, margin: int) -> None:
        """提供 `_set_main_margins` 对应的内部辅助逻辑，供 `MainWindow` 使用。"""
        self.main_layout.setContentsMargins(margin, margin, margin, margin)

    def _emit_delete_for_video(self, video_id: str) -> None:
        """提供 `_emit_delete_for_video` 对应的内部辅助逻辑，供 `MainWindow` 使用。"""
        row = self.left_panel.find_row_by_video_id(video_id)
        if row != -1:
            self.sig_delete_video.emit(row, video_id)

    def get_selected_video_id(self) -> str | None:
        """获取 `selected_video_id` 对应的数据或状态，供 `MainWindow` 使用。"""
        return self.left_panel.get_selected_video_id()

    def _on_copy_trace_clicked(self) -> None:
        """处理 `copy_trace_clicked` 触发后的回调逻辑，供 `MainWindow` 使用。"""
        video_id = self.get_selected_video_id()
        if not video_id:
            self.append_log("⚠️ 请先在下载队列表中选中一个任务")
            return
        self.sig_copy_trace_id.emit(video_id)

    def show_image(self, image_path: str) -> None:
        """执行 `show_image` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.media_panel.show_image(image_path)

    def resizeEvent(self, event) -> None:
        """执行 `resizeEvent` 对应的业务逻辑，供 `MainWindow` 使用。"""
        super().resizeEvent(event)
        self.media_panel.resize_media()

    def play_video(self, video_path: str) -> None:
        """执行 `play_video` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.media_panel.play_video(video_path)

    def stop_media_playback(self) -> None:
        """执行 `stop_media_playback` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.media_panel.stop_playback()

    def release_media_playback(self) -> None:
        """删除或切换媒体前显式释放播放器 source，避免本地文件仍被占用。"""
        self.media_panel.release_media()

    def cleanup_media(self) -> None:
        """执行 `cleanup_media` 对应的业务逻辑，供 `MainWindow` 使用。"""
        self.media_panel.cleanup()
