"""用于规划和执行发布构建的主题化 Qt 面板。"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PyQt6.QtCore import (
    QObject,
    QRect,
    QSignalBlocker,
    QThread,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.combo_popup import (
    ThemedComboBox,
    refresh_themed_combo_boxes,
)
from app.ui.components.log_panel import LogPanel
from app.ui.dialogs.chromed_dialog import ChromedDialog
from app.ui.layout.window_chrome import WindowChromeFrame
from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
from app.ui.styles import (
    apply_application_theme,
    build_palette,
    resolve_is_dark_theme,
    theme_colors,
)
from app.utils.qt_runtime import (
    RELEASE_BUILDER_APP_USER_MODEL_ID,
    ensure_windows_app_user_model_id,
)
from scripts.update_bootstrap import default_manifest_private_key_path

from .events import redact_release_text
from .icon_builder import release_builder_icon_path
from .models import (
    BuildRequest,
    ReleaseMode,
    ReleaseResult,
    ReleaseStage,
    RemoteReleaseInfo,
)
from .modes import resolve_release_mode, validate_build_request
from .panel_policy import (
    PanelBuildIntent,
    available_intents,
    option_defaults,
    recommended_intent,
    resolve_panel_intent,
)
from .process_controller import ReleaseProcessController
from .proxy import ProxySelection, build_proxy_environment, project_proxy_options
from .remote import fetch_latest_release
from .versioning import format_release_tag, normalize_version, read_project_version
from .workspace_paths import (
    default_release_notes_directory,
    find_release_notes_for_version,
    installer_output_directory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPOSITORY = "haohaizi554/UniversalCrawler"
_ACTIVE_REMOTE_THREADS: set[QThread] = set()

_MODE_OPTION_BINDINGS = {
    "apply_version": "check_apply_version",
    "build_portable": "check_build_portable",
    "build_installer": "check_build_installer",
    "run_smoke_tests": "check_smoke_tests",
    "generate_manifest_key": "check_generate_key",
    "rotate_trust_anchor": "check_rotate_trust_anchor",
    "sign_manifest": "check_sign_manifest",
    "commit_version_changes": "check_commit_version",
    "push_main": "check_push_main",
    "create_or_reuse_tag": "check_create_tag",
    "create_or_update_release": "check_create_release",
    "upload_release_assets": "check_upload_assets",
    "upload_public_key": "check_upload_public_key",
    "verify_remote_assets": "check_verify_remote",
}

_MODE_LABELS = {
    ReleaseMode.LOCAL_DEBUG.value: "本地调试",
    ReleaseMode.LOCAL_REBUILD.value: "本地重新构建",
    ReleaseMode.SAME_RELEASE_REPAIR.value: "同版本修复",
    ReleaseMode.NEW_RELEASE.value: "新版本发布",
    ReleaseMode.OFFLINE_DEBUG.value: "离线本地调试",
    "remote_unknown": "远端版本未知",
    "invalid": "配置无效",
}
_STAGE_LABELS = {
    ReleaseStage.IDLE.value: "就绪",
    ReleaseStage.CHECKING_REMOTE.value: "检查远端版本",
    ReleaseStage.PREFLIGHT.value: "发布前检查",
    ReleaseStage.VERSION_SYNC.value: "同步版本号",
    ReleaseStage.SOURCE_IDENTITY.value: "确认源码身份",
    ReleaseStage.BUILDING_PORTABLE.value: "构建便携版",
    ReleaseStage.BUILDING_INSTALLER.value: "构建安装包",
    ReleaseStage.SIGNING.value: "签署更新清单",
    ReleaseStage.SMOKE_TESTING.value: "执行冒烟测试",
    ReleaseStage.GIT.value: "提交 Git 变更",
    ReleaseStage.PUBLISHING.value: "创建 GitHub Release",
    ReleaseStage.UPLOADING.value: "上传发布资产",
    ReleaseStage.VERIFYING.value: "校验远端资产",
    ReleaseStage.SUCCEEDED.value: "构建成功",
    ReleaseStage.FAILED.value: "构建失败",
    ReleaseStage.CANCELLED.value: "已取消",
}
_ACTION_LABELS = {
    "apply version changes": "应用版本变更",
    "applying version changes": "应用版本变更",
    "build portable artifacts": "构建便携版",
    "building portable artifacts": "构建便携版",
    "build installer artifacts": "构建安装包",
    "building installer artifacts": "构建安装包",
    "run smoke tests": "执行冒烟测试",
    "smoke testing": "执行冒烟测试",
    "generate manifest keys": "生成更新清单密钥",
    "rotate trust anchors": "轮换信任锚",
    "sign manifests": "签署更新清单",
    "signing the manifest": "签署更新清单",
    "commit version changes": "提交版本变更",
    "committing version changes": "提交版本变更",
    "push main": "推送 main 分支",
    "pushing main": "推送 main 分支",
    "create or reuse tags": "创建或复用标签",
    "creating or reusing the release tag": "创建或复用发布标签",
    "create or update releases": "创建或更新 Release",
    "upload release assets": "上传发布资产",
    "uploading release assets": "上传发布资产",
    "upload public keys": "上传公钥",
    "remote asset verification": "校验远端资产",
    "creating or updating the release": "创建或更新 Release",
    "building the installer": "构建安装包",
    "a private key": "提供私钥",
    "committing source identity": "提交源码身份",
    "generating a manifest key": "生成更新清单密钥",
    "a new release version": "使用新的发布版本号",
}
_EXACT_MESSAGE_LABELS = {
    "remote release state is unknown": "尚未取得远端发布版本，无法确定构建模式",
    "same release repair requires target version to equal remote version": (
        "同版本修复要求目标版本与远端版本一致"
    ),
    "creating or updating a release requires release notes": (
        "创建或更新 Release 时必须提供发布说明"
    ),
    "smoke tests require building portable artifacts": (
        "执行冒烟测试前必须构建便携版"
    ),
    "version must use MAJOR.MINOR.PATCH": "版本号必须使用 主版本.次版本.修订号 格式",
    "invalid proxy selection": "代理选项无效",
    "invalid custom proxy endpoint": "自定义代理端点无效",
    "Building": "正在构建",
    "Release build succeeded": "发布构建成功",
    "Release build failed": "发布构建失败",
    "Waiting for background work to stop": "正在等待后台任务安全停止",
}


def _localize_release_message(message: str) -> str:
    """将发布协议中的稳定英文状态投影为中文界面文案。"""

    text = str(message or "").strip()
    if not text:
        return ""
    exact = _EXACT_MESSAGE_LABELS.get(text)
    if exact is not None:
        return exact

    for mode_value, mode_label in _MODE_LABELS.items():
        prefix = f"{mode_value} mode cannot "
        if text.startswith(prefix):
            action = text.removeprefix(prefix)
            return f"{mode_label}模式不允许{_ACTION_LABELS.get(action, action)}"

    prefixes = (
        ("new release publication requires ", "发布新版本必须"),
        ("upload release assets requires ", "上传发布资产前必须"),
        ("upload public key requires ", "上传公钥前必须"),
        ("new release tag requires ", "创建新版本标签前必须"),
        ("new release signing requires ", "签署新版本前必须"),
        ("rotating the trust anchor requires ", "轮换信任锚前必须"),
        ("dry run cannot ", "试运行模式不允许"),
    )
    for prefix, localized_prefix in prefixes:
        if text.startswith(prefix):
            action = text.removeprefix(prefix)
            return f"{localized_prefix}{_ACTION_LABELS.get(action, action)}"

    if text == (
        "new release tag for an applied version commit requires pushing main"
    ):
        return "基于版本变更提交创建新标签前，必须推送 main 分支"
    return text


class _ReleaseSectionCard(QGroupBox):
    """Numbered release-builder card with a stable content owner."""

    def __init__(
        self,
        number: int,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setProperty("releaseSection", True)
        self.setProperty("releaseSectionNumber", number)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 12, 8)
        root.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(7)
        number_label = QLabel(str(number), self)
        number_label.setObjectName("ReleaseSectionNumber")
        number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number_label.setFixedSize(18, 18)
        title_label = QLabel(title, self)
        title_label.setObjectName("ReleaseSectionTitle")
        header.addWidget(number_label)
        header.addWidget(title_label, 1)
        root.addLayout(header)

        self.body = QWidget(self)
        self.body.setObjectName("ReleaseSectionBody")
        self.body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        root.addWidget(self.body, 1)


class _RemoteLoaderWorker(QObject):
    completed = pyqtSignal(int, object)

    def __init__(
        self,
        generation: int,
        loader: Callable[[str, Mapping[str, str]], RemoteReleaseInfo],
        repository: str,
        environment: Mapping[str, str],
    ) -> None:
        super().__init__()
        self._generation = generation
        self._loader = loader
        self._repository = repository
        self._environment = dict(environment)

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._loader(self._repository, self._environment)
            if not isinstance(result, RemoteReleaseInfo):
                raise TypeError("remote loader returned an invalid result")
        except Exception as error:
            result = RemoteReleaseInfo.unavailable(redact_release_text(str(error)))
        self.completed.emit(self._generation, result)


class _ConfirmationDialog(ChromedDialog):
    def __init__(self, parent: QWidget, summary: str) -> None:
        super().__init__(
            parent,
            title="确认远端发布操作",
            object_name="ReleaseRemoteConfirmation",
            body_margins=(20, 18, 20, 18),
            body_spacing=14,
        )
        label = QLabel(summary, self)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content_layout.addWidget(label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("开始发布")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.content_layout.addWidget(buttons)
        self.setMinimumWidth(560)


def build_confirmation_summary(
    request: BuildRequest,
    mode: ReleaseMode,
    *,
    asset_names: Iterable[str],
) -> str:
    """Build a redacted summary containing only approved confirmation fields."""

    repository = _safe_repository_label(request.repository)
    notes_path = redact_release_text(str(request.release_notes_path or "").strip())
    assets = tuple(
        redact_release_text(Path(str(name)).name)
        for name in asset_names
        if str(name).strip()
    )
    version = normalize_version(request.target_version)
    values = (
        ("版本", redact_release_text(version)),
        ("发布模式", _MODE_LABELS.get(mode.value, mode.value)),
        ("Git 标签", redact_release_text(format_release_tag(version))),
        ("代码仓库", repository),
        ("代理", redact_release_text(request.proxy_label)),
        ("发布说明", notes_path or "无"),
        ("发布资产", ", ".join(assets) if assets else "无"),
    )
    return "\n".join(f"{label}：{value}" for label, value in values)


def _safe_repository_label(repository: str) -> str:
    value = redact_release_text(str(repository or "").strip())
    if "://" not in value:
        return value
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


class ReleaseBuilderWindow(QWidget):
    """复用项目标题栏与主题体系的顶层发布构建面板。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        project_version: str | None = None,
        project_root: Path | None = None,
        remote_loader: Callable[[str, Mapping[str, str]], RemoteReleaseInfo]
        | None = None,
        process_controller: ReleaseProcessController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReleaseBuilderWindow")
        self.setProperty("ucpThemeRoot", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("UniversalCrawler 发布构建工具")
        self.icon_path = str(release_builder_icon_path())
        self.setWindowIcon(QIcon(self.icon_path))
        self._is_dark = resolve_is_dark_theme(self)
        self._colors = theme_colors(self._is_dark)
        self.setPalette(build_palette(self._is_dark))
        self.remote_info = RemoteReleaseInfo.unknown()
        self._remote_loader = remote_loader or (
            lambda repository, environment: fetch_latest_release(
                repository,
                environment=environment,
            )
        )
        self._remote_generation = 0
        self._remote_thread: QThread | None = None
        self._remote_worker: _RemoteLoaderWorker | None = None
        self._remote_lookup_pending = False
        self._accept_remote_results = True
        self._close_pending = False
        self._shutting_down = False
        self._mode: ReleaseMode | None = None
        self._panel_intent: PanelBuildIntent | None = None
        self._local_mode_forced = False
        self._projecting_panel_mode = False
        self._mode_form_states: dict[
            PanelBuildIntent,
            dict[str, bool],
        ] = {}
        inferred_project_root = (
            process_controller.project_root
            if project_root is None and process_controller is not None
            else project_root
        )
        self._project_root = Path(inferred_project_root or PROJECT_ROOT).resolve()
        self._project_version = project_version or read_project_version(
            self._project_root
        )

        self.chrome_frame = WindowChromeFrame(
            title="UniversalCrawler 发布构建工具",
            icon=QIcon(self.icon_path),
            is_dark_theme=self._is_dark,
            show_minimize=True,
            show_maximize=True,
            show_close=True,
            parent=self,
        )
        self.window_title_bar = self.chrome_frame.title_bar
        self._window_chrome_controller = FramelessWindowChromeController(
            self,
            title_bar_getter=lambda: self.window_title_bar,
            resizable=True,
            minimizable=True,
            maximizable=True,
        )
        self._window_chrome_controller.set_window_flags()
        self._window_chrome_controller.bind_title_bar_controls()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.chrome_frame)
        self._build_body()

        self.process_controller = process_controller or ReleaseProcessController(
            self,
            project_root=self._project_root,
        )
        self._connect_controller()
        self._connect_form()
        self._sync_release_notes_for_target_version()
        self._apply_compact_control_heights()
        self._apply_theme()
        self._apply_compact_control_heights()
        self._apply_initial_geometry()
        self._stabilize_configuration_sections()
        self.refresh_mode()
        self.start_remote_lookup()

    @property
    def remote_lookup_active(self) -> bool:
        thread = self._remote_thread
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            return False

    @property
    def panel_intent(self) -> PanelBuildIntent:
        """Return the currently projected user-facing build intent."""

        return self._panel_intent or PanelBuildIntent.LOCAL

    @staticmethod
    def constrained_geometry(available: QRect) -> QRect:
        width = min(1480, max(1, available.width()))
        height = min(860, max(1, available.height()))
        x = available.x() + (available.width() - width) // 2
        y = available.y() + (available.height() - height) // 2
        return QRect(x, y, width, height)

    def refresh_mode(self) -> None:
        self._reconcile_panel_intent()
        request = self._request_from_controls()
        try:
            resolution = resolve_panel_intent(
                self.panel_intent,
                request.target_version,
                request.remote,
            )
        except ValueError as error:
            self._mode = None
            mode_name = (
                "remote_unknown"
                if str(error) == "remote release state is unknown"
                else "invalid"
            )
            self._set_mode_badge(mode_name)
        else:
            self._mode = resolution.release_mode
            self._set_mode_badge(resolution.release_mode.value)
            self._project_mode_controls(resolution.release_mode)
            request = self._request_from_controls()

        errors = validate_build_request(request)
        self.validation_label.setText(
            "\n".join(_localize_release_message(error) for error in errors)
        )
        can_start = (
            self._mode is not None
            and not errors
            and not self.process_controller.running
            and not self._remote_lookup_pending
        )
        self.start_button.setEnabled(can_start)
        self.cancel_button.setEnabled(self.process_controller.running)

    def _reconcile_panel_intent(self) -> None:
        available = available_intents(
            self.target_version_edit.text().strip(),
            self.remote_info,
        )
        running = self.process_controller.running
        for intent, button in self._panel_intent_buttons().items():
            button.setEnabled(intent in available and not running)

        desired = (
            PanelBuildIntent.LOCAL
            if self._local_mode_forced
            else recommended_intent(
                self.target_version_edit.text().strip(),
                self.remote_info,
            )
        )
        if desired not in available:
            desired = PanelBuildIntent.LOCAL
            self._local_mode_forced = False
        if self._panel_intent is not desired:
            self._switch_panel_intent(desired)
        else:
            self._sync_mode_button_checks(desired)

    def _on_panel_intent_selected(
        self,
        intent: PanelBuildIntent,
    ) -> None:
        if self._projecting_panel_mode:
            return
        available = available_intents(
            self.target_version_edit.text().strip(),
            self.remote_info,
        )
        if intent not in available:
            self._sync_mode_button_checks(self.panel_intent)
            return
        self._local_mode_forced = intent is PanelBuildIntent.LOCAL
        self._switch_panel_intent(intent)
        self.refresh_mode()

    def _on_target_version_changed(self) -> None:
        self._sync_release_notes_for_target_version()
        self.refresh_mode()

    def _sync_release_notes_for_target_version(self) -> None:
        matched_path = find_release_notes_for_version(
            self._project_root,
            self.target_version_edit.text(),
        )
        matched_text = str(matched_path) if matched_path is not None else ""
        if self.notes_edit.text() == matched_text:
            return
        blocker = QSignalBlocker(self.notes_edit)
        self.notes_edit.setText(matched_text)
        del blocker

    def _switch_panel_intent(
        self,
        intent: PanelBuildIntent,
    ) -> None:
        if self._panel_intent is intent:
            self._sync_mode_button_checks(intent)
            return
        if self._panel_intent is not None:
            self._mode_form_states[self._panel_intent] = (
                self._capture_mode_form_state()
            )
        state = self._mode_form_states.get(intent)
        if state is None:
            defaults = option_defaults(intent)
            state = {
                field_name: bool(getattr(defaults, field_name))
                for field_name in _MODE_OPTION_BINDINGS
            }
            self._mode_form_states[intent] = dict(state)

        controls = self._mode_option_controls()
        blockers = [QSignalBlocker(control) for control in controls]
        self._projecting_panel_mode = True
        try:
            for field_name, control_name in _MODE_OPTION_BINDINGS.items():
                getattr(self, control_name).setChecked(state[field_name])
            self._panel_intent = intent
            self._sync_mode_button_checks(intent)
        finally:
            self._projecting_panel_mode = False
            blockers.clear()

    def _capture_mode_form_state(self) -> dict[str, bool]:
        return {
            field_name: bool(getattr(self, control_name).isChecked())
            for field_name, control_name in _MODE_OPTION_BINDINGS.items()
        }

    def _mode_option_controls(self) -> tuple[QWidget, ...]:
        return tuple(
            getattr(self, control_name)
            for control_name in _MODE_OPTION_BINDINGS.values()
        )

    def _panel_intent_buttons(
        self,
    ) -> dict[PanelBuildIntent, QPushButton]:
        return {
            PanelBuildIntent.LOCAL: self.mode_local_button,
            PanelBuildIntent.SAME_RELEASE: self.mode_same_button,
            PanelBuildIntent.NEW_RELEASE: self.mode_release_button,
        }

    def _sync_mode_button_checks(
        self,
        intent: PanelBuildIntent,
    ) -> None:
        buttons = self._panel_intent_buttons()
        blockers = [QSignalBlocker(button) for button in buttons.values()]
        try:
            for candidate, button in buttons.items():
                button.setChecked(candidate is intent)
        finally:
            blockers.clear()

    def start_remote_lookup(self) -> None:
        if self.remote_lookup_active or self._shutting_down:
            return
        self._remote_generation += 1
        generation = self._remote_generation
        self._remote_lookup_pending = True
        if self.remote_info.is_available:
            self.remote_version_label.setText(
                f"正在检查…（当前 {self.remote_info.version}）"
            )
        else:
            self.remote_info = RemoteReleaseInfo.unknown()
            self.remote_version_label.setText("正在检查…")
        self.refresh_remote_button.setEnabled(False)
        self.refresh_mode()
        try:
            environment = build_proxy_environment(
                self._proxy_selection(),
                os.environ,
            )
        except ValueError as error:
            self._on_remote_result(
                generation,
                RemoteReleaseInfo.unavailable(str(error)),
            )
            return

        thread = QThread()
        worker = _RemoteLoaderWorker(
            generation,
            self._remote_loader,
            self.repository_edit.text().strip(),
            environment,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_remote_result)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_remote_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        _ACTIVE_REMOTE_THREADS.add(thread)
        self._remote_thread = thread
        self._remote_worker = worker
        thread.start()

    def create_confirmation_dialog(self, summary: str) -> ChromedDialog:
        return _ConfirmationDialog(self, summary)

    def start_build(self) -> None:
        request = self._request_from_controls()
        errors = validate_build_request(request)
        if errors:
            self.validation_label.setText(
                "\n".join(_localize_release_message(error) for error in errors)
            )
            self.refresh_mode()
            return
        try:
            mode = resolve_release_mode(
                request.target_version,
                request.remote,
                same_release_repair=request.same_release_repair,
                offline_debug=request.offline_debug,
            )
        except ValueError as error:
            self.validation_label.setText(_localize_release_message(str(error)))
            self.refresh_mode()
            return
        if self._has_remote_writes(request):
            summary = build_confirmation_summary(
                request,
                mode,
                asset_names=self._asset_names(request),
            )
            dialog = self.create_confirmation_dialog(summary)
            if dialog.exec() != int(ChromedDialog.DialogCode.Accepted):
                return
        try:
            self.process_controller.start(request, self._proxy_selection())
        except (OSError, RuntimeError, ValueError) as error:
            self._on_process_error(redact_release_text(str(error)))

    def shutdown(self) -> bool:
        if not self._shutting_down:
            self._shutting_down = True
            self._accept_remote_results = False
            self._remote_generation += 1
        thread = self._remote_thread
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass
        process_stopped = self.process_controller.shutdown()
        remote_stopped = not self.remote_lookup_active
        if process_stopped and remote_stopped:
            self._window_chrome_controller.uninstall()
            return True
        return False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._window_chrome_controller.install()
        self._window_chrome_controller.on_show_event()
        if self._sync_release_option_columns():
            self._stabilize_configuration_sections()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._sync_release_option_columns():
            self._stabilize_configuration_sections()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._close_pending = True
        if not self.shutdown():
            self.status_label.setText("正在等待后台任务安全停止")
            event.ignore()
            return
        self._close_pending = False
        event.accept()

    def nativeEvent(self, event_type, message):  # noqa: N802
        hit_test = self._window_chrome_controller.handle_native_event(
            event_type,
            message,
        )
        if hit_test is not None:
            return True, hit_test
        return False, 0

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._window_chrome_controller.mouse_press_event(event):
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if self._window_chrome_controller.event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    def _build_body(self) -> None:
        content = QWidget(self.chrome_frame.body)
        content.setObjectName("ReleaseBuilderContent")
        workbench = QHBoxLayout(content)
        workbench.setContentsMargins(16, 14, 16, 16)
        workbench.setSpacing(12)
        self.section_widgets: list[QGroupBox] = []

        self.left_configuration_column = QWidget(content)
        self.left_configuration_column.setObjectName(
            "ReleaseConfigurationColumn"
        )
        configuration_layout = QVBoxLayout(
            self.left_configuration_column
        )
        configuration_layout.setContentsMargins(0, 0, 0, 0)
        configuration_layout.setSpacing(6)
        self._configuration_layout = configuration_layout
        self._build_version_section(configuration_layout)
        self._build_build_section(configuration_layout)
        self._build_signing_section(configuration_layout)
        self._build_release_section(configuration_layout)
        self._build_network_section(configuration_layout)
        self.configuration_sections = list(self.section_widgets)
        for index, stretch in enumerate((3, 1, 2, 3, 1)):
            configuration_layout.setStretch(index, stretch)

        self.execution_column = QWidget(content)
        self.execution_column.setObjectName("ReleaseExecutionColumn")
        execution_layout = QVBoxLayout(self.execution_column)
        execution_layout.setContentsMargins(0, 0, 0, 0)
        execution_layout.setSpacing(0)
        self._build_execution_section(execution_layout)
        self.execution_section = self.section_widgets[-1]

        workbench.addWidget(self.left_configuration_column, 10)
        workbench.addWidget(self.execution_column, 11)
        self.chrome_frame.body_layout.addWidget(content)

    def _stabilize_configuration_sections(self) -> None:
        for section in self.configuration_sections:
            section.setMinimumHeight(0)
            body_layout = section.body.layout()
            if body_layout is not None:
                body_layout.activate()
            section.layout().activate()
            section.setMinimumHeight(section.minimumSizeHint().height())

    def _apply_compact_control_heights(self) -> None:
        for control in (
            self.target_version_edit,
            self.refresh_remote_button,
            self.private_key_edit,
            self.private_key_button,
            self.repository_edit,
            self.notes_edit,
            self.notes_button,
            self.proxy_combo,
            self.custom_proxy_edit,
        ):
            control.setProperty("releaseCompactControl", "true")
            control.setFixedHeight(34)
        for control in (
            self.mode_local_button,
            self.mode_same_button,
            self.mode_release_button,
        ):
            control.setFixedHeight(44)
        for control in (
            self.check_apply_version,
            self.check_build_portable,
            self.check_build_installer,
            self.check_smoke_tests,
        ):
            control.setFixedHeight(42)

    def _sync_release_option_columns(self) -> bool:
        if not hasattr(self, "release_options_host"):
            return False
        available_width = self.release_options_host.width()
        if available_width <= 0:
            return False
        spacing = self._release_option_grid.horizontalSpacing()
        for columns in range(4, 0, -1):
            column_widths = [0] * columns
            for index, control in enumerate(self._release_option_controls):
                column = index % columns
                column_widths[column] = max(
                    column_widths[column],
                    control.sizeHint().width(),
                )
            required_width = sum(column_widths) + spacing * (columns - 1)
            if required_width <= available_width:
                return self._reflow_release_options(columns=columns)
        return self._reflow_release_options(columns=1)

    def _reflow_release_options(self, *, columns: int) -> bool:
        normalized_columns = max(1, int(columns))
        if self._release_option_columns == normalized_columns:
            return False
        while self._release_option_grid.count():
            self._release_option_grid.takeAt(0)
        for index, control in enumerate(self._release_option_controls):
            self._release_option_grid.addWidget(
                control,
                index // normalized_columns,
                index % normalized_columns,
            )
        for column in range(normalized_columns):
            self._release_option_grid.setColumnStretch(column, 1)
        self._release_option_columns = normalized_columns
        self._release_option_grid.activate()
        return True

    def _new_section(
        self,
        title: str,
        sections: QVBoxLayout,
        *,
        stretch: int = 0,
    ) -> _ReleaseSectionCard:
        group = _ReleaseSectionCard(
            len(self.section_widgets) + 1,
            title,
        )
        self.section_widgets.append(group)
        sections.addWidget(group, stretch)
        return group

    def _build_version_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("版本信息", sections)
        layout = QGridLayout(group.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        layout.setColumnStretch(1, 1)
        self.target_version_edit = QLineEdit(self._project_version)
        self.target_version_edit.setMinimumWidth(180)
        self.target_version_edit.setFixedHeight(34)
        self.remote_version_label = QLabel("尚未检查")
        self.remote_version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_remote_button = QPushButton("刷新")
        self.refresh_remote_button.setFixedHeight(34)
        remote_row = QHBoxLayout()
        remote_row.addWidget(self.remote_version_label, 1)
        remote_row.addWidget(self.refresh_remote_button)
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        self.mode_local_button = self._new_mode_button(
            "本地构建\n仅构建不发布",
            PanelBuildIntent.LOCAL,
        )
        self.mode_local_button.setToolTip("任意版本仅在本地构建，不发布远端资源")
        self.mode_same_button = self._new_mode_button(
            "同版本修复\n修复现有发布",
            PanelBuildIntent.SAME_RELEASE,
        )
        self.mode_same_button.setToolTip("修复远端同版本 Release 及其发布资产")
        self.mode_release_button = self._new_mode_button(
            "高版本发布\n创建正式发布",
            PanelBuildIntent.NEW_RELEASE,
        )
        self.mode_release_button.setToolTip("构建并发布高于远端版本的新 Release")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        for button in (
            self.mode_local_button,
            self.mode_same_button,
            self.mode_release_button,
        ):
            self.mode_button_group.addButton(button)
            mode_row.addWidget(button, 1)
        self.mode_local_button.setChecked(True)
        layout.addWidget(QLabel("目标版本"), 0, 0)
        layout.addWidget(self.target_version_edit, 0, 1)
        layout.addWidget(QLabel("远端最新版本"), 1, 0)
        layout.addLayout(remote_row, 1, 1)
        layout.addWidget(QLabel("构建模式"), 2, 0)
        layout.addLayout(mode_row, 2, 1)

    def _new_mode_button(
        self,
        text: str,
        intent: PanelBuildIntent,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ReleaseModeChoice")
        button.setProperty("releaseModeChoice", intent.value)
        button.setCheckable(True)
        button.setFixedHeight(44)
        button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        return button

    def _build_build_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("构建选项", sections)
        layout = QHBoxLayout(group.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.check_apply_version = self._new_option_card(
            "应用版本号",
            QStyle.StandardPixmap.SP_BrowserReload,
        )
        self.check_build_portable = self._new_option_card(
            "便携版",
            QStyle.StandardPixmap.SP_DirIcon,
        )
        self.check_build_installer = self._new_option_card(
            "安装包",
            QStyle.StandardPixmap.SP_ComputerIcon,
        )
        self.check_smoke_tests = self._new_option_card(
            "冒烟测试",
            QStyle.StandardPixmap.SP_DialogApplyButton,
        )
        for control in (
            self.check_apply_version,
            self.check_build_portable,
            self.check_build_installer,
            self.check_smoke_tests,
        ):
            layout.addWidget(control, 1)

    def _new_option_card(
        self,
        text: str,
        standard_icon: QStyle.StandardPixmap,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ReleaseOptionCard")
        button.setProperty("releaseOptionCard", True)
        button.setCheckable(True)
        button.setChecked(True)
        button.setIcon(self.style().standardIcon(standard_icon))
        button.setFixedHeight(42)
        button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        return button

    def _build_signing_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("签名与信任", sections)
        layout = QGridLayout(group.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        layout.setColumnStretch(1, 1)
        self.private_key_edit = QLineEdit(
            str(default_manifest_private_key_path(project_root=PROJECT_ROOT))
        )
        self.private_key_edit.setPlaceholderText("私钥路径或 env:环境变量名")
        self.private_key_edit.setCursorPosition(0)
        self.private_key_edit.setFixedHeight(34)
        self.private_key_button = QPushButton("选择")
        self.private_key_button.setFixedHeight(34)
        key_row = QHBoxLayout()
        key_row.addWidget(self.private_key_edit, 1)
        key_row.addWidget(self.private_key_button)
        self.check_generate_key = QCheckBox("生成清单密钥")
        self.check_rotate_trust_anchor = QCheckBox("轮换信任锚")
        self.check_sign_manifest = QCheckBox("签署更新清单")
        layout.addWidget(QLabel("私钥"), 0, 0)
        layout.addLayout(key_row, 0, 1)
        options = QHBoxLayout()
        options.setSpacing(6)
        options.addWidget(self.check_generate_key)
        options.addWidget(self.check_rotate_trust_anchor)
        options.addWidget(self.check_sign_manifest)
        options.addStretch(1)
        layout.addLayout(options, 1, 1)

    def _build_release_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("代码仓库与发布", sections)
        layout = QGridLayout(group.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        layout.setColumnStretch(1, 1)
        self.repository_edit = QLineEdit(DEFAULT_REPOSITORY)
        self.repository_edit.setFixedHeight(34)
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("发布说明 Markdown 文件路径")
        self.notes_edit.setFixedHeight(34)
        self.notes_button = QPushButton("选择")
        self.notes_button.setFixedHeight(34)
        notes_row = QHBoxLayout()
        notes_row.addWidget(self.notes_edit, 1)
        notes_row.addWidget(self.notes_button)
        layout.addWidget(QLabel("GitHub 仓库"), 0, 0)
        layout.addWidget(self.repository_edit, 0, 1)
        layout.addWidget(QLabel("发布说明"), 1, 0)
        layout.addLayout(notes_row, 1, 1)
        self.check_commit_version = QCheckBox("提交版本")
        self.check_push_main = QCheckBox("推送 main")
        self.check_create_tag = QCheckBox("创建/复用标签")
        self.check_create_release = QCheckBox("创建/更新 Release")
        self.check_upload_assets = QCheckBox("上传资产")
        self.check_upload_public_key = QCheckBox("上传公钥")
        self.check_verify_remote = QCheckBox("校验远端")
        self._release_option_controls = (
            self.check_commit_version,
            self.check_push_main,
            self.check_create_tag,
            self.check_create_release,
            self.check_upload_assets,
            self.check_upload_public_key,
            self.check_verify_remote,
        )
        self.release_options_host = QWidget(group.body)
        self.release_options_host.setObjectName("ReleaseOptionsHost")
        self._release_option_grid = QGridLayout(self.release_options_host)
        self._release_option_grid.setContentsMargins(0, 0, 0, 0)
        self._release_option_grid.setHorizontalSpacing(4)
        self._release_option_grid.setVerticalSpacing(2)
        layout.addWidget(self.release_options_host, 2, 1)
        self._release_option_columns = 0
        self._reflow_release_options(columns=4)
        self._remote_controls = self._release_option_controls

    def _build_network_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("网络与代理", sections)
        layout = QGridLayout(group.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(0)
        layout.setColumnStretch(1, 1)
        self.proxy_control = QWidget(group.body)
        self.proxy_control.setObjectName("SettingsProxyControl")
        self.proxy_control.setProperty("customProxySurface", "split")
        proxy_layout = QHBoxLayout(self.proxy_control)
        proxy_layout.setContentsMargins(0, 0, 0, 0)
        proxy_layout.setSpacing(0)
        self._proxy_control_layout = proxy_layout
        self.proxy_combo = ThemedComboBox(row_height=34)
        self.proxy_combo.setObjectName("ReleaseProxyCombo")
        self.proxy_combo.setProperty("comboPopupClampToControl", True)
        self.proxy_combo.setFixedHeight(34)
        self.proxy_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        for option in project_proxy_options():
            label = str(option.get("label") or option.get("value") or "")
            value = str(option.get("value") or label)
            self.proxy_combo.addItem(label, value)
        if self.proxy_combo.count() == 0:
            self.proxy_combo.addItem("系统代理", "System proxy")
            self.proxy_combo.addItem("直连（不使用代理）", "Direct")
            self.proxy_combo.addItem("自定义 HTTP/SOCKS5 端点", "Custom")
        self.custom_proxy_edit = QLineEdit()
        self.custom_proxy_edit.setObjectName("SettingsProxyCustomEdit")
        self.custom_proxy_edit.setPlaceholderText("代理端点或 env:环境变量名")
        self.custom_proxy_edit.setFixedHeight(34)
        self.custom_proxy_edit.setMinimumWidth(0)
        self.custom_proxy_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.custom_proxy_edit.setClearButtonEnabled(False)
        proxy_layout.addWidget(self.proxy_combo, 1)
        proxy_layout.addWidget(self.custom_proxy_edit, 1)
        layout.addWidget(QLabel("上传代理"), 0, 0)
        layout.addWidget(self.proxy_control, 0, 1)

    def _build_execution_section(self, sections: QVBoxLayout) -> None:
        group = self._new_section("执行进度与日志", sections, stretch=1)
        group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        layout = QVBoxLayout(group.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        status_row = QHBoxLayout()
        self.mode_badge = QLabel("远端版本未知")
        self.mode_badge.setObjectName("ReleaseModeBadge")
        self.status_label = QLabel("就绪")
        self.status_label.setWordWrap(True)
        self.start_button = QPushButton("开始构建")
        self.start_button.setObjectName("PrimaryBtn")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        status_row.addWidget(self.mode_badge)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.start_button)
        status_row.addWidget(self.cancel_button)
        layout.addLayout(status_row)
        self.validation_label = QLabel()
        self.validation_label.setObjectName("ReleaseValidation")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        tools = QHBoxLayout()
        self.copy_log_button = QPushButton("复制选中内容")
        self.export_log_button = QPushButton("导出日志副本")
        self.clear_log_button = QPushButton("清空显示")
        self.open_log_directory_button = QPushButton("打开日志目录")
        self.open_installer_directory_button = QPushButton("打开安装包目录")
        self.open_installer_directory_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.open_installer_directory_button.setToolTip(
            "打开 dist/installer 安装包输出目录"
        )
        for button in (
            self.copy_log_button,
            self.export_log_button,
            self.clear_log_button,
            self.open_log_directory_button,
            self.open_installer_directory_button,
        ):
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.log_panel = LogPanel()
        self.log_panel.setPlaceholderText("日志将在这里显示")
        self.log_panel.setMinimumHeight(190)
        layout.addWidget(self.log_panel, 1)

    def _connect_form(self) -> None:
        for control in (
            self.check_apply_version,
            self.check_build_portable,
            self.check_build_installer,
            self.check_smoke_tests,
            self.check_generate_key,
            self.check_rotate_trust_anchor,
            self.check_sign_manifest,
            self.check_commit_version,
            self.check_push_main,
            self.check_create_tag,
            self.check_create_release,
            self.check_upload_assets,
            self.check_upload_public_key,
            self.check_verify_remote,
        ):
            control.toggled.connect(self.refresh_mode)
        self.target_version_edit.textChanged.connect(
            self._on_target_version_changed
        )
        for edit in (
            self.private_key_edit,
            self.repository_edit,
            self.notes_edit,
            self.custom_proxy_edit,
        ):
            edit.textChanged.connect(self.refresh_mode)
        self.proxy_combo.currentIndexChanged.connect(self._on_proxy_changed)
        self.mode_local_button.clicked.connect(
            lambda: self._on_panel_intent_selected(PanelBuildIntent.LOCAL)
        )
        self.mode_same_button.clicked.connect(
            lambda: self._on_panel_intent_selected(
                PanelBuildIntent.SAME_RELEASE
            )
        )
        self.mode_release_button.clicked.connect(
            lambda: self._on_panel_intent_selected(
                PanelBuildIntent.NEW_RELEASE
            )
        )
        self.refresh_remote_button.clicked.connect(self.start_remote_lookup)
        self.private_key_button.clicked.connect(self._choose_private_key)
        self.notes_button.clicked.connect(self._choose_release_notes)
        self.start_button.clicked.connect(self.start_build)
        self.cancel_button.clicked.connect(self.process_controller.cancel)
        self.copy_log_button.clicked.connect(self.log_panel.copy)
        self.export_log_button.clicked.connect(self._export_log_copy)
        self.clear_log_button.clicked.connect(self.log_panel.clear)
        self.open_log_directory_button.clicked.connect(self._open_log_directory)
        self.open_installer_directory_button.clicked.connect(
            self._open_installer_directory
        )
        self._sync_custom_proxy_enabled()

    def _connect_controller(self) -> None:
        self.process_controller.log_lines_ready.connect(self.log_panel.append_logs)
        self.process_controller.stage_changed.connect(self._on_stage_changed)
        self.process_controller.error_reported.connect(self._on_process_error)
        self.process_controller.running_changed.connect(self._on_running_changed)
        self.process_controller.completed.connect(self._on_process_completed)

    def _apply_theme(self) -> None:
        apply_application_theme(self._is_dark)
        self.setPalette(build_palette(self._is_dark))
        self.chrome_frame.apply_theme(self._is_dark)
        self._colors = theme_colors(self._is_dark)
        base = self.styleSheet()
        semantic = f"""
        QWidget#ReleaseBuilderContent {{
            background: {self._colors["bg"]};
        }}
        QWidget#ReleaseConfigurationColumn,
        QWidget#ReleaseExecutionColumn,
        QWidget#ReleaseSectionBody,
        QWidget#ReleaseOptionsHost {{
            background: transparent;
        }}
        QGroupBox[releaseSection="true"] {{
            background: {self._colors["panel"]};
            border: 1px solid {self._colors["border"]};
            border-radius: 6px;
            margin: 0px;
            padding: 0px;
        }}
        QGroupBox[releaseSection="true"]::title {{
            subcontrol-origin: margin;
            color: transparent;
            padding: 0px;
            width: 0px;
            height: 0px;
        }}
        QLabel#ReleaseSectionNumber {{
            color: {self._colors["accent"]};
            background: {self._colors["accent_soft"]};
            border: 1px solid {self._colors["accent"]};
            border-radius: 9px;
            font-weight: 700;
        }}
        QLabel#ReleaseSectionTitle {{
            color: {self._colors["text"]};
            font-weight: 700;
        }}
        QLineEdit[releaseCompactControl="true"] {{
            min-height: 30px;
            padding-top: 0px;
            padding-bottom: 0px;
        }}
        QPushButton[releaseCompactControl="true"] {{
            min-height: 32px;
            padding-top: 0px;
            padding-bottom: 0px;
        }}
        QPushButton#ReleaseModeChoice {{
            min-height: 36px;
            color: {self._colors["muted"]};
            background: {self._colors["panel_soft"]};
            border: 1px solid {self._colors["border"]};
            border-radius: 6px;
            padding: 3px 8px;
            text-align: left;
        }}
        QPushButton#ReleaseModeChoice:hover:enabled {{
            color: {self._colors["text"]};
            border-color: {self._colors["border_strong"]};
        }}
        QPushButton#ReleaseModeChoice:checked {{
            color: {self._colors["accent"]};
            background: {self._colors["accent_soft"]};
            border: 1px solid {self._colors["accent"]};
            font-weight: 700;
        }}
        QPushButton#ReleaseModeChoice:disabled {{
            color: {self._colors["muted"]};
            background: {self._colors["panel_soft"]};
            border-color: {self._colors["border"]};
        }}
        QPushButton#ReleaseOptionCard {{
            min-height: 40px;
            color: {self._colors["muted"]};
            background: {self._colors["panel_soft"]};
            border: 1px solid {self._colors["border"]};
            border-radius: 6px;
            padding: 0px 8px;
        }}
        QPushButton#ReleaseOptionCard:hover:enabled {{
            color: {self._colors["text"]};
            border-color: {self._colors["border_strong"]};
        }}
        QPushButton#ReleaseOptionCard:checked {{
            color: {self._colors["accent"]};
            background: {self._colors["accent_soft"]};
            border: 1px solid {self._colors["accent"]};
            font-weight: 700;
        }}
        QPushButton#PrimaryBtn:disabled {{
            color: {self._colors["muted"]};
            background: {self._colors["panel_soft"]};
            border-color: {self._colors["border"]};
        }}
        QWidget#SettingsProxyControl {{
            background: transparent;
        }}
        QLineEdit#SettingsProxyCustomEdit[customProxyActive="true"] {{
            border-color: {self._colors["accent"]};
        }}
        QLabel#ReleaseModeBadge {{
            color: {self._colors["accent"]};
            background: {self._colors["accent_soft"]};
            border: 1px solid {self._colors["border_strong"]};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QLabel#ReleaseValidation {{
            color: {self._colors["danger"]};
        }}
        """
        self.setStyleSheet(f"{base}\n{semantic}")
        refresh_themed_combo_boxes(self)

    def _apply_initial_geometry(self) -> None:
        app = QApplication.instance()
        screen = self.screen() or (app.primaryScreen() if app is not None else None)
        if screen is None:
            self.resize(1480, 860)
            self.setMinimumSize(980, 680)
            return
        available = screen.availableGeometry()
        geometry = self.constrained_geometry(available)
        self.setMinimumSize(
            min(980, geometry.width()),
            min(680, geometry.height()),
        )
        self.setGeometry(geometry)

    def _request_from_controls(self) -> BuildRequest:
        raw_target_version = self.target_version_edit.text().strip()
        try:
            target_version = normalize_version(raw_target_version)
        except ValueError:
            target_version = raw_target_version
        try:
            resolution = resolve_panel_intent(
                self.panel_intent,
                target_version,
                self.remote_info,
            )
            same_release_repair = resolution.same_release_repair
            offline_debug = resolution.offline_debug
        except ValueError:
            same_release_repair = (
                self.panel_intent is PanelBuildIntent.SAME_RELEASE
            )
            offline_debug = self.panel_intent is PanelBuildIntent.LOCAL
        return BuildRequest(
            target_version=target_version,
            repository=self.repository_edit.text().strip(),
            release_notes_path=self.notes_edit.text().strip(),
            build_portable=self.check_build_portable.isChecked(),
            build_installer=self.check_build_installer.isChecked(),
            run_smoke_tests=self.check_smoke_tests.isChecked(),
            same_release_repair=same_release_repair,
            offline_debug=offline_debug,
            apply_version=self.check_apply_version.isChecked(),
            generate_manifest_key=self.check_generate_key.isChecked(),
            rotate_trust_anchor=self.check_rotate_trust_anchor.isChecked(),
            private_key_path=self.private_key_edit.text().strip(),
            sign_manifest=self.check_sign_manifest.isChecked(),
            commit_version_changes=self.check_commit_version.isChecked(),
            push_main=self.check_push_main.isChecked(),
            create_or_reuse_tag=self.check_create_tag.isChecked(),
            create_or_update_release=self.check_create_release.isChecked(),
            upload_release_assets=self.check_upload_assets.isChecked(),
            upload_public_key=self.check_upload_public_key.isChecked(),
            verify_remote_assets=self.check_verify_remote.isChecked(),
            proxy_label=self._proxy_label(),
            custom_proxy=self.custom_proxy_edit.text().strip(),
            remote=self.remote_info,
        )

    def _proxy_label(self) -> str:
        data = self.proxy_combo.currentData()
        return str(data if data is not None else self.proxy_combo.currentText())

    def _proxy_selection(self) -> ProxySelection:
        return ProxySelection(
            label=self._proxy_label(),
            endpoint=self.custom_proxy_edit.text().strip(),
        )

    def _project_mode_controls(self, mode: ReleaseMode) -> None:
        local_mode = mode in {
            ReleaseMode.LOCAL_DEBUG,
            ReleaseMode.LOCAL_REBUILD,
            ReleaseMode.OFFLINE_DEBUG,
        }
        restricted_controls = self._remote_controls + (
            self.check_generate_key,
            self.check_rotate_trust_anchor,
            self.check_sign_manifest,
        )
        for control in restricted_controls:
            if local_mode and control.isChecked():
                blocker = QSignalBlocker(control)
                control.setChecked(False)
                del blocker
            control.setEnabled(not local_mode and not self.process_controller.running)
        signing_enabled = not local_mode and not self.process_controller.running
        self.private_key_edit.setEnabled(signing_enabled)
        self.private_key_button.setEnabled(signing_enabled)

    def _set_mode_badge(self, mode_name: str) -> None:
        self.mode_badge.setText(_MODE_LABELS.get(mode_name, mode_name))
        self.mode_badge.setProperty("releaseMode", mode_name)
        self.mode_badge.style().unpolish(self.mode_badge)
        self.mode_badge.style().polish(self.mode_badge)

    @pyqtSlot(int, object)
    def _on_remote_result(
        self,
        generation: int,
        result: RemoteReleaseInfo,
    ) -> None:
        if (
            not self._accept_remote_results
            or generation != self._remote_generation
        ):
            return
        self.remote_info = result
        self._remote_lookup_pending = False
        if result.is_available:
            self.remote_version_label.setText(result.version)
        else:
            self.remote_version_label.setText(
                _localize_release_message(result.error) or "远端发布版本未知"
            )
        self.refresh_mode()

    def _on_remote_thread_finished(self, thread: QThread) -> None:
        _ACTIVE_REMOTE_THREADS.discard(thread)
        if self._remote_thread is thread:
            self._remote_thread = None
            self._remote_worker = None
            self._remote_lookup_pending = False
            self.refresh_remote_button.setEnabled(not self._shutting_down)
            self.refresh_mode()
        self._continue_pending_close()

    @pyqtSlot(str, int, str)
    def _on_stage_changed(
        self,
        stage: str,
        progress: int,
        message: str,
    ) -> None:
        self.progress_bar.setValue(progress)
        self.status_label.setText(
            _localize_release_message(message)
            or _STAGE_LABELS.get(stage, stage)
        )

    @pyqtSlot(str)
    def _on_process_error(self, message: str) -> None:
        self.status_label.setText(
            _localize_release_message(redact_release_text(message))
        )

    @pyqtSlot(bool)
    def _on_running_changed(self, running: bool) -> None:
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(running)
        if not running:
            self.refresh_mode()

    @pyqtSlot(object)
    def _on_process_completed(self, result: ReleaseResult) -> None:
        if result.succeeded:
            message = "发布构建成功"
            if self.process_controller.audit_log_warning:
                message += "；审计日志可能不完整"
            self.status_label.setText(message)
            self.progress_bar.setValue(100)
        else:
            self.status_label.setText(
                _localize_release_message(
                    redact_release_text(result.error or "Release build failed")
                )
            )
        self._continue_pending_close()

    def _continue_pending_close(self) -> None:
        if (
            self._close_pending
            and not self.remote_lookup_active
            and self.process_controller.shutdown_complete
        ):
            QTimer.singleShot(0, self.close)

    def _on_proxy_changed(self) -> None:
        self._sync_custom_proxy_enabled()
        self.refresh_mode()

    def _sync_custom_proxy_enabled(self) -> None:
        active = self._proxy_label() in {
            "自定义",
            "Custom",
            "custom",
            "Custom proxy",
        }
        self.proxy_control.setProperty(
            "customProxyActive",
            "true" if active else "false",
        )
        self.proxy_combo.setProperty(
            "customProxy",
            "true" if active else "false",
        )
        self.custom_proxy_edit.setProperty(
            "customProxyActive",
            "true" if active else "false",
        )
        self._proxy_control_layout.setSpacing(6 if active else 0)
        self._proxy_control_layout.setStretch(0, 1)
        self._proxy_control_layout.setStretch(1, 1 if active else 0)
        self.custom_proxy_edit.setVisible(active)
        self.custom_proxy_edit.setEnabled(active)
        self.proxy_control.updateGeometry()

    def _choose_private_key(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择私钥",
            "",
            "密钥文件 (*.pem *.key);;所有文件 (*)",
        )
        if path:
            self.private_key_edit.setText(path)

    def _choose_release_notes(self) -> None:
        current_path = Path(self.notes_edit.text().strip())
        start_path = (
            current_path
            if current_path.is_file()
            else default_release_notes_directory(self._project_root)
        )
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择发布说明",
            str(start_path),
            "Markdown (*.md *.markdown);;文本文件 (*.txt);;所有文件 (*)",
        )
        if path:
            self.notes_edit.setText(path)

    def _export_log_copy(self) -> None:
        source = self.process_controller.persistent_log_path
        default_name = source.name if source is not None else "release-build.log"
        destination, _filter = QFileDialog.getSaveFileName(
            self,
            "导出发布日志",
            default_name,
            "日志文件 (*.log);;所有文件 (*)",
        )
        if not destination:
            return
        try:
            if source is not None and source.is_file():
                Path(destination).write_bytes(source.read_bytes())
            else:
                Path(destination).write_text(
                    self.log_panel.toPlainText(),
                    encoding="utf-8",
                )
        except OSError:
            QMessageBox.warning(self, "导出失败", "无法导出发布日志。")

    def _open_log_directory(self) -> None:
        directory = self.process_controller.log_directory
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _open_installer_directory(self) -> None:
        directory = installer_output_directory(self._project_root)
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    @staticmethod
    def _has_remote_writes(request: BuildRequest) -> bool:
        return any(
            (
                request.push_main,
                request.create_or_reuse_tag,
                request.create_or_update_release,
                request.upload_release_assets,
                request.upload_public_key,
            )
        )

    @staticmethod
    def _asset_names(request: BuildRequest) -> tuple[str, ...]:
        assets: list[str] = []
        if request.upload_release_assets:
            assets.extend(
                (
                    "UniversalCrawler-Setup.exe",
                    "latest.json",
                    "latest.json.sig",
                )
            )
        if request.upload_public_key:
            assets.append("manifest-public-key.pem")
        return tuple(assets)

_LAUNCHED_WINDOWS: dict[int, QWidget] = {}


def launch_release_builder_panel() -> int:
    """启动独立的发布构建工具。"""

    # Windows resolves taskbar grouping before the first top-level HWND is
    # created. Rebind even when the launcher already owns QApplication.
    ensure_windows_app_user_model_id(RELEASE_BUILDER_APP_USER_MODEL_ID)
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(sys.argv)
    icon = QIcon(str(release_builder_icon_path()))
    app.setWindowIcon(icon)
    window = ReleaseBuilderWindow()
    window.show()
    if owns_application:
        return int(app.exec())
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window_key = id(window)
    _LAUNCHED_WINDOWS[window_key] = window
    destroyed = getattr(window, "destroyed", None)
    if destroyed is not None:
        destroyed.connect(
            lambda _object=None, key=window_key: _LAUNCHED_WINDOWS.pop(key, None)
        )
    return 0


__all__ = [
    "ReleaseBuilderWindow",
    "build_confirmation_summary",
    "launch_release_builder_panel",
]
