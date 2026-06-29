from __future__ import annotations

from typing import Any
from app.debug_logger import debug_logger

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import action_icon_file, platform_icon_file, ui_icon_path
from app.ui.components.combo_popup import ThemedComboBox, apply_themed_combo_box, polish_combo_popup, schedule_combo_popup_repolish
from app.ui.localization import normalize_language, tr
from app.ui.pages.common import PageFrame
from app.ui.styles.themes import resolve_is_dark_theme, theme_colors
from app.utils.qt_runtime import load_qt_icon
from app.utils.safe_slot import safe_slot

GROUP_ICONS = {
    "基础设置": "action_open_directory.png",
    "下载设置": "action_download.png",
    "平台设置": "platform_web.png",
    "播放设置": "action_play.png",
    "日志设置": "nav_log_center.png",
    "外观设置": "action_theme_palette.png",
}

PLATFORM_FALLBACK_LETTERS = {
    "douyin": "D",
    "xiaohongshu": "X",
    "bilibili": "B",
    "kuaishou": "K",
    "missav": "M",
}

FILENAME_TEMPLATES = [
    "{platform}_{title}_{date}_{index}",
    "{platform}_{title}",
    "{title}_{index}",
    "{date}_{platform}_{title}",
]

OPEN_MODE_OPTIONS = [
    "系统默认播放器",
    "内置播放器",
    "打开所在目录",
    "不自动打开",
]

CONCURRENCY_OPTIONS = [
    {"value": "1", "label": "1"},
    {"value": "3", "label": "3（推荐）"},
    {"value": "5", "label": "5"},
]
TIMEOUT_OPTIONS = ["30", "60", "90", "120", "180", "300"]
RETRY_OPTIONS = ["0", "1", "2", "3", "5", "10"]
SPEED_LIMIT_OPTIONS = [
    {"value": "0", "label": "无限制"},
    {"value": "512", "label": "512 KB/s"},
    {"value": "1024", "label": "1 MB/s"},
    {"value": "2048", "label": "2 MB/s"},
    {"value": "5120", "label": "5 MB/s"},
    {"value": "10240", "label": "10 MB/s"},
]
PLATFORM_COUNT_OPTIONS = ["10", "20", "30", "50", "100"]
PROXY_OPTIONS = ["系统代理", "直连", "Clash (7890)", "Clash Verge (7897)", "v2rayN (10809)", "V2Ray / Qv2ray (10808)", "sing-box (2080)", "NekoRay (2080)", "自定义"]
RETENTION_OPTIONS = ["1", "3", "5", "7"]
UI_LOG_MAX_DISPLAY_OPTIONS = ["300", "500", "1000", "2000", "5000"]
PLAYER_OPTIONS = ["内置播放器", "系统默认播放器"]
ACCENT_OPTIONS = ["蓝色", "绿色", "紫色", "橙色", "红色"]
SCALE_OPTIONS = ["90%", "100%（推荐）", "110%", "125%"]
FONT_SIZE_OPTIONS = ["小", "中（推荐）", "大"]

SETTING_DESCRIPTIONS = {
    "下载目录": "保存采集结果和下载文件的位置，支持粘贴路径或手动选择文件夹。",
    "文件命名规则": "控制下载文件的命名格式，只能从预设模板中选择。",
    "下载后自动打开": "任务完成后自动打开文件或所在位置。",
    "默认打开方式": "设置下载完成后的默认打开行为。",
    "并发数": "同时执行的下载任务数量，数值越高对网络和磁盘压力越大。",
    "图片受并发数限制": "开启后图片下载也遵循普通并发数；关闭时图片批量使用轻量快速通道。",
    "请求超时（秒）": "单次网络请求等待时间，网络较慢时可适当调大。",
    "重试次数": "下载失败后的自动重试次数。",
    "断点续传": "任务中断后尽量从已下载位置继续。",
    "下载速度限制（KB/s）": "限制下载速度，选择“不限制”表示使用最大可用带宽。",
    "仅下载视频": "开启后跳过封面、图片等非视频资源。",
    "打开方式": "设置媒体文件使用的播放方式。",
    "记住播放进度": "下次打开同一视频时恢复上次播放位置。",
    "视频播放完自动下一项": "当前视频结束后自动播放列表中的下一项。",
    "图片只手动切换": "图片预览时不自动轮播。",
    "日志保留天数": "应用初始化时自动清理超过保留期的旧日志。",
    "UI日志最大显示数量": "控制日志中心前端最多展示的日志条数，避免大量日志影响界面性能。",
    "错误时自动复制 Trace": "出现异常时自动复制追踪编号，便于排查问题。",
    "语言": "切换配置中心和 WebUI 设置页的显示语言。",
    "跟随系统": "自动跟随操作系统的浅色或深色主题。",
    "浅色 / 深色": "手动切换应用主题外观。",
    "主题色": "选择应用强调色。",
    "界面缩放": "调整界面整体缩放比例。",
    "字体大小": "调整界面文字大小。",
}

SETTING_SHORT_DESCRIPTIONS = {
    "下载目录": "保存下载文件的位置",
    "文件命名规则": "从预设模板中选择",
    "下载后自动打开": "任务完成后自动打开",
    "默认打开方式": "下载完成后的打开行为",
    "并发数": "同时下载的任务数",
    "图片受并发数限制": "图片是否占用普通并发",
    "请求超时（秒）": "单次请求等待时间",
    "重试次数": "失败后的自动重试次数",
    "断点续传": "从已下载位置继续",
    "下载速度限制（KB/s）": "限制最大下载速度",
    "仅下载视频": "跳过封面和图片资源",
    "打开方式": "播放方式",
    "记住播放进度": "下次恢复播放位置",
    "视频播放完自动下一项": "结束后播放下一项",
    "图片只手动切换": "关闭图片自动轮播",
    "日志保留天数": "初始化时自动清理",
    "UI日志最大显示数量": "限制日志中心展示条数",
    "错误时自动复制 Trace": "异常时复制追踪编号",
    "语言": "界面显示语言",
    "跟随系统": "跟随系统外观",
    "浅色 / 深色": "手动切换主题",
    "主题色": "选择强调色",
    "界面缩放": "调整界面比例",
    "字体大小": "调整界面文字大小",
}

GROUP_DESCRIPTIONS = {
    "基础设置": "下载目录、命名规则和打开行为",
    "下载设置": "并发、超时、重试和限速",
    "平台设置": "认证状态、爬取数量和代理入口",
    "播放设置": "播放器、进度和自动播放",
    "日志设置": "保留周期、展示数量和错误追踪",
    "外观设置": "主题、缩放和字体",
}

GROUP_HINTS = {
    "基础设置": "路径支持粘贴和选择；命名规则使用预设模板，避免非法文件名。",
    "下载设置": "并发越高不一定越快，建议根据网络和磁盘性能调整。",
    "平台设置": "认证状态自动检测；代理仅对需要的平台开放。",
    "播放设置": "播放设置只影响本地预览，不影响下载文件。",
    "日志设置": "UI展示数量只影响日志中心显示，不影响日志文件本身。",
    "外观设置": "外观设置只影响界面显示，不影响下载任务。",
}

UI_TEXT: dict[str, dict[str, str]] = {}


PLATFORM_DETAIL_COL_WIDTHS = {
    "name": 122,
    "auth": 112,
    "count": 210,
    "timeout": 132,
    "proxy": 294,
}

FORM_CONTROL_WIDTH = 320
FORM_CONTROL_WIDTH_LARGE = 520
FORM_CONTROL_WIDTH_MEDIUM = 380
FORM_SWITCH_WRAP_WIDTH = 96


class UiSwitch(QCheckBox):
    """Pill toggle switch without native checkbox chrome."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = theme_colors(False)
        self.setObjectName("SettingsUiSwitch")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setText("")
        self.setFixedSize(48, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(48, 28)

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._palette = colors
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event

        if self.width() <= 0 or self.height() <= 0:
            return

        colors = self._palette
        checked = self.isChecked()
        enabled = self.isEnabled()

        track_on = QColor(colors["accent"])
        track_off = QColor("#cbd5e1" if colors["panel"].lower() == "#ffffff" else "#4b5563")
        knob = QColor("#ffffff")

        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if not enabled:
                painter.setOpacity(0.45)

            rect = QRectF(1, 3, 46, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track_on if checked else track_off)
            painter.drawRoundedRect(rect, 11, 11)

            knob_x = 25 if checked else 4
            painter.setBrush(knob)
            painter.drawEllipse(QRectF(knob_x, 5, 18, 18))
        finally:
            painter.end()


class SegmentedControl(QWidget):
  selection_changed = pyqtSignal(str)

  def __init__(
      self,
      options: list[tuple[str, str]],
      *,
      parent: QWidget | None = None,
  ) -> None:
      super().__init__(parent)
      self._options = list(options)
      self._colors = theme_colors(False)
      self.setObjectName("SettingsSegmented")
      self.setFixedHeight(38)

      layout = QHBoxLayout(self)
      layout.setContentsMargins(0, 0, 0, 0)
      layout.setSpacing(0)

      self._group = QButtonGroup(self)
      self._group.setExclusive(True)
      self._buttons: dict[str, QPushButton] = {}

      for index, (value, label) in enumerate(self._options):
          button = QPushButton(label)
          button.setObjectName("SettingsSegmentButton")
          button.setCheckable(True)
          button.setProperty("segment_value", value)
          button.setCursor(Qt.CursorShape.PointingHandCursor)
          button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
          button.setMinimumHeight(36)
          if index == 0:
              button.setProperty("segment_pos", "left")
          elif index == len(self._options) - 1:
              button.setProperty("segment_pos", "right")
          else:
              button.setProperty("segment_pos", "middle")
          self._group.addButton(button)
          self._buttons[value] = button
          layout.addWidget(button, 1)
          button.toggled.connect(lambda checked, key=value: self._on_toggled(key, checked))

      if self._options:
          self._buttons[self._options[0][0]].setChecked(True)

  def _on_toggled(self, value: str, checked: bool) -> None:
      if checked:
          self.selection_changed.emit(value)

  def set_theme_colors(self, colors: dict[str, str]) -> None:
      self._colors = colors
      self.update()

  def set_value(self, value: str) -> None:
      button = self._buttons.get(str(value))
      if button is not None:
          blocked = button.blockSignals(True)
          try:
              button.setChecked(True)
          finally:
              button.blockSignals(blocked)

  def value(self) -> str:
      for key, button in self._buttons.items():
          if button.isChecked():
              return key
      return self._options[0][0] if self._options else ""


class SettingsComboBox(ThemedComboBox):
    """Stable settings combo that keeps the active accent while the popup is open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The settings stylesheet owns the control chrome; the shared helper owns popup behavior.
        self.setStyleSheet("")
        self.setProperty("themedComboControlStyle", "false")
        self.setProperty("comboPopupClampToControl", "true")
        self.setProperty("popupOpen", "false")

    def _set_popup_open(self, open_: bool) -> None:
        self.setProperty("popupOpen", "true" if open_ else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def showPopup(self) -> None:  # noqa: N802
        self._set_popup_open(True)
        if self.width() > 0:
            self.setProperty("comboPopupMaxWidth", int(self.width()))
        polish_combo_popup(self, row_height=self.property("comboPopupRowHeight") or 38)
        QComboBox.showPopup(self)
        if self.width() > 0:
            self.setProperty("comboPopupMaxWidth", int(self.width()))
        polish_combo_popup(self, row_height=self.property("comboPopupRowHeight") or 38)
        schedule_combo_popup_repolish(self)

    def hidePopup(self) -> None:  # noqa: N802
        QComboBox.hidePopup(self)
        self._set_popup_open(False)


class SettingsPage(PageFrame):
    """Configuration center with master-detail production UI."""

    file_association_requested = pyqtSignal(bool, bool)
    setting_changed = pyqtSignal(str, str, object)

    GROUP_ORDER = ("基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置")

    def __init__(self) -> None:
        super().__init__("", "", use_island=True)
        self.setObjectName("SettingsPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._render_signature: tuple | None = None
        self._switches: list[UiSwitch] = []
        self._segmented_controls: list[SegmentedControl] = []
        self._theme_refresh_pending = False
        self._applying_style = False
        self._last_settings_stylesheet = ""
        self._last_theme_dark: bool | None = None
        self._relayout_pending = False
        self._rendering = False
        self._settings_snapshot: dict[str, Any] = {}
        self._group_order: list[str] = list(self.GROUP_ORDER)
        self._group_descriptions: dict[str, str] = dict(GROUP_DESCRIPTIONS)
        self._current_group = "基础设置"
        self._current_language = "zh-CN"
        self._nav_buttons: dict[str, QPushButton] = {}
        self._last_proxy_emit: tuple[str, str, str] | None = None
        self._directory_dialogs: list[QFileDialog] = []

        self.scroll = None

        self.content = QWidget()
        self.content.setObjectName("SettingsContent")

        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 8, 18, 16)
        self.content_layout.setSpacing(12)

        title_box = QWidget()
        title_box.setObjectName("SettingsPageHeader")

        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        self.page_title = QLabel("配置中心")
        self.page_title.setObjectName("SettingsPageTitle")
        self.page_title.setFixedHeight(28)

        self.page_subtitle = QLabel("集中管理下载行为、平台状态、播放体验、日志策略与界面外观")
        self.page_subtitle.setObjectName("SettingsPageSubtitle")
        self.page_subtitle.setFixedHeight(20)
        self.page_subtitle.setWordWrap(False)

        self.action_feedback = QLabel("")
        self.action_feedback.setObjectName("SettingsActionFeedback")
        self.action_feedback.setFixedHeight(24)
        self.action_feedback.setVisible(False)
        self.action_feedback.setWordWrap(False)

        title_layout.addWidget(self.page_title)
        title_layout.addWidget(self.page_subtitle)
        title_layout.addWidget(self.action_feedback)

        self.content_layout.addWidget(title_box)

        self.main_panel = QFrame()
        self.main_panel.setObjectName("SettingsMainPanel")
        self.main_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        panel_layout = QHBoxLayout(self.main_panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(12)

        self.nav_panel = QFrame()
        self.nav_panel.setObjectName("SettingsSideNav")
        self.nav_panel.setFixedWidth(180)
        self.nav_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.nav_layout = QVBoxLayout(self.nav_panel)
        self.nav_layout.setContentsMargins(10, 10, 10, 10)
        self.nav_layout.setSpacing(4)

        self.nav_title = QLabel("设置分类")
        self.nav_title.setObjectName("SettingsNavTitle")
        self.nav_title.setFixedHeight(26)
        self.nav_layout.addWidget(self.nav_title)
        self._rebuild_group_navigation()

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("SettingsDetailPanel")
        self.detail_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(24, 22, 24, 20)
        self.detail_layout.setSpacing(12)

        panel_layout.addWidget(self.nav_panel)
        panel_layout.addWidget(self.detail_panel, 1)

        self.content_layout.addWidget(self.main_panel, 1)
        self.root_layout.addWidget(self.content, 1)

        self._apply_settings_page_style()
        self._refresh_language_texts()
        self._sync_nav_buttons()
        self._last_theme_dark = self._is_dark()

    def _language(self) -> str:
        appearance = self._settings_snapshot.get("外观设置") if isinstance(self._settings_snapshot, dict) else {}
        value = str(self._dict_value(appearance, "language", self._current_language or "zh-CN") or "zh-CN")
        return normalize_language(value)

    def _t(self, text: str) -> str:
        value = str(text or "")
        return tr(value, self._language())

    def _refresh_language_texts(self) -> None:
        self._current_language = self._language()
        self.page_title.setText(self._t("配置中心"))
        self.page_title.setFixedHeight(self._scaled_px(28, minimum=28))
        self.page_subtitle.setText(self._t("集中管理下载行为、平台状态、播放体验、日志策略与界面外观"))
        self.page_subtitle.setFixedHeight(self._scaled_px(20, minimum=20))
        self.action_feedback.setFixedHeight(self._scaled_px(24, minimum=24))
        self.nav_title.setText(self._t("设置分类"))
        self.nav_title.setFixedHeight(self._scaled_px(26, minimum=26))
        for group_name, button in self._nav_buttons.items():
            button.setText(self._t(group_name))

    def _is_dark(self) -> bool:
        window = self.window()
        value = getattr(window, "is_dark_theme", None) if window is not None else None

        if isinstance(value, bool):
            return value

        if callable(value):
            try:
                return bool(value())
            except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
                debug_logger.log_exception("SettingsPage", "resolve_dark_callable", exc)

        return resolve_is_dark_theme(self)

    def _colors(self) -> dict[str, str]:
        return theme_colors(self._is_dark())

    def _schedule_theme_refresh(self) -> None:
        if getattr(self, "_theme_refresh_pending", False):
            return
        self._theme_refresh_pending = True
        QTimer.singleShot(0, self._refresh_theme_widgets)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)

        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        }:
            self._schedule_theme_refresh()

    def _schedule_relayout_cards(self) -> None:
        if getattr(self, "_rendering", False):
            return
        if getattr(self, "_relayout_pending", False):
            return

        self._relayout_pending = True
        QTimer.singleShot(0, self._run_pending_relayout)

    @safe_slot
    def _run_pending_relayout(self) -> None:
        self._relayout_pending = False
        if getattr(self, "_rendering", False):
            return
        self._sync_content_card_widths()

    def _content_card_width(self) -> int:
        detail_width = self.detail_panel.width() if hasattr(self, "detail_panel") else 1000
        margins = self.detail_layout.contentsMargins() if hasattr(self, "detail_layout") else None
        horizontal_margins = (margins.left() + margins.right()) if margins is not None else 48
        available = max(320, detail_width - horizontal_margins - 4)

        if getattr(self, "_current_group", "") == self.GROUP_ORDER[2]:
            desired = min(1120, max(min(available, 720), int(available * 0.96)))
        else:
            desired = min(1080, max(min(available, 520), int(available * 0.82)))

        return max(320, min(available, desired))

    def _form_inner_width(self) -> int:
        return max(300, self._content_card_width() - 20)

    def _effective_control_width(self, control_width: int) -> int:
        return min(int(control_width), max(150, self._content_card_width() - 260))

    def _combo_label_min_width(self, options: list[Any], current: Any, *, floor: int) -> int:
        font = self.font()
        font.setPixelSize(self._scaled_px(13, minimum=12))
        metrics = QFontMetrics(font)
        labels = [self._t(label) for _value, label in self._normalize_combo_options(options, current)]
        widest = max((metrics.horizontalAdvance(label) for label in labels), default=0)
        return max(int(floor), widest + self._scaled_px(38, minimum=34))

    def _platform_option_min_width(
        self,
        rows: list[dict[str, Any]] | None,
        option_key: str,
        default_options: list[Any],
        current_key: str,
        default_current: Any,
        *,
        floor: int,
    ) -> int:
        width = self._combo_label_min_width(default_options, default_current, floor=floor)
        for row in rows or []:
            width = max(
                width,
                self._combo_label_min_width(
                    list(row.get(option_key) or default_options),
                    row.get(current_key, default_current),
                    floor=floor,
                ),
            )
        return width

    def _platform_col_widths(self, rows: list[dict[str, Any]] | None = None) -> dict[str, int]:
        base = dict(PLATFORM_DETAIL_COL_WIDTHS)
        base["count"] = max(
            base["count"],
            self._platform_option_min_width(
                rows,
                "count_options",
                PLATFORM_COUNT_OPTIONS,
                "default_count",
                20,
                floor=180,
            ),
        )
        base["timeout"] = max(
            base["timeout"],
            self._platform_option_min_width(
                rows,
                "timeout_options",
                TIMEOUT_OPTIONS,
                "default_timeout",
                60,
                floor=132,
            ),
        )
        content_width = max(280, self._form_inner_width() - 28 - 40)
        base_total = sum(base.values())
        if content_width >= base_total:
            return base

        minimums = {
            "name": 70,
            "auth": 78,
            "count": min(base["count"], max(160, base["count"] - 28)),
            "timeout": min(base["timeout"], max(132, base["timeout"] - 12)),
            "proxy": 112,
        }
        min_total = sum(minimums.values())
        if content_width <= min_total:
            name_width = 58
            auth_width = 64
            proxy_floor = 72
            count_floor = 100
            timeout_width = min(
                base["timeout"],
                max(108, content_width - name_width - auth_width - proxy_floor - count_floor),
            )
            count_width = max(
                count_floor,
                min(base["count"], content_width - name_width - auth_width - proxy_floor - timeout_width),
            )
            proxy_width = max(
                52,
                content_width - name_width - auth_width - timeout_width - count_width,
            )
            if proxy_width < proxy_floor and count_width > count_floor:
                borrow = min(proxy_floor - proxy_width, count_width - count_floor)
                count_width -= borrow
                proxy_width += borrow
            widths = {
                "name": name_width,
                "auth": auth_width,
                "count": count_width,
                "timeout": timeout_width,
                "proxy": proxy_width,
            }
        else:
            extra = content_width - min_total
            base_extra = base_total - min_total
            widths = {
                key: minimums[key] + int(extra * (base[key] - minimums[key]) / max(1, base_extra))
                for key in base
            }

        used_without_proxy = widths["name"] + widths["auth"] + widths["count"] + widths["timeout"]
        proxy_floor = 80 if content_width - used_without_proxy >= 80 else 52
        widths["proxy"] = max(proxy_floor, content_width - used_without_proxy)
        return widths

    def _scale_factor(self) -> float:
        app = QApplication.instance()
        raw = app.property("ui_scale") if app is not None else "100%"
        text = str(raw or "100%").strip()
        if text.endswith("%"):
            try:
                return max(0.85, min(1.35, float(text[:-1]) / 100.0))
            except ValueError:
                return 1.0
        try:
            return max(0.85, min(1.35, float(text)))
        except ValueError:
            return 1.0

    def _font_factor(self) -> float:
        app = QApplication.instance()
        raw = app.property("ui_font_size") if app is not None else "medium"
        return {"small": 0.92, "medium": 1.0, "large": 1.12}.get(str(raw or "medium").strip().lower(), 1.0)

    def _scaled_px(self, value: int, *, minimum: int | None = None) -> int:
        scaled = round(int(value) * self._scale_factor() * self._font_factor())
        if minimum is not None:
            return max(minimum, scaled)
        return scaled

    def _sync_content_card_widths(self) -> None:
        if not hasattr(self, "detail_panel"):
            return
        width = self._content_card_width()
        inner_width = self._form_inner_width()
        for widget in self.detail_panel.findChildren(QFrame):
            object_name = widget.objectName()
            if object_name in {"SettingsFormCard", "SettingsHintCard"}:
                widget.setFixedWidth(width)
            elif object_name in {"SettingsPlatformTablePanel", "SettingsPlatformSummaryBar"}:
                widget.setFixedWidth(inner_width)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_relayout_cards()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._settings_snapshot:
            QTimer.singleShot(0, self._repair_empty_view_if_needed)

    def _view_needs_rebuild(self) -> bool:
        if not hasattr(self, "detail_layout") or not hasattr(self, "nav_layout"):
            return False
        expected_groups = len(self._group_order)
        if expected_groups and len(self._nav_buttons) < expected_groups:
            return True
        if self.detail_layout.count() < 3:
            return True
        seen = set()
        for index in range(self.detail_layout.count()):
            item = self.detail_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                seen.add(widget.objectName())
        return not {"SettingsDetailHeader", "SettingsFormCard"}.issubset(seen)

    @safe_slot
    def _repair_empty_view_if_needed(self) -> None:
        if not self.isVisible() or self._rendering or not self._settings_snapshot:
            return
        if not self._view_needs_rebuild():
            return
        self._rebuild_group_navigation()
        self._refresh_language_texts()
        self._render_current_group()

    @safe_slot
    def _refresh_theme_widgets(self) -> None:
        self._theme_refresh_pending = False

        is_dark = self._is_dark()
        colors = self._colors()

        self._last_theme_dark = is_dark
        self._apply_settings_page_style()

        for switch in list(self._switches):
            if switch is not None:
                switch.set_theme_colors(colors)

        for control in list(self._segmented_controls):
            if control is not None:
                control.set_theme_colors(colors)

        for combo in self.findChildren(QComboBox):
            self._style_combo_popup(combo)

    def sync_external_theme(self, is_dark: bool, *, follow_system: bool | None = None) -> None:
        theme_value = "dark" if is_dark else "light"
        settings = self._settings_snapshot if isinstance(self._settings_snapshot, dict) else {}
        appearance = settings.get("外观设置")
        if isinstance(appearance, dict):
            appearance["theme"] = theme_value
            if follow_system is not None:
                appearance["follow_system"] = bool(follow_system)
            self._render_signature = None

        for control in list(self._segmented_controls):
            if control is not None and control.property("settingsRole") == "theme":
                control.set_value(theme_value)
                control.set_theme_colors(self._colors())
                control.style().unpolish(control)
                control.style().polish(control)
                control.update()

        if follow_system is not None:
            for switch in list(self._switches):
                if switch is not None and switch.property("settingsRole") == "follow_system":
                    blocked = switch.blockSignals(True)
                    try:
                        switch.setChecked(bool(follow_system))
                    finally:
                        switch.blockSignals(blocked)
                    switch.update()

    def render(self, snapshot: dict) -> None:
        settings = snapshot.get("settings_snapshot") or {}
        contract = snapshot.get("settings_contract") if isinstance(snapshot.get("settings_contract"), dict) else {}
        self._update_group_contract(settings, contract)
        signature = self._settings_signature(settings, contract)
        needs_rebuild = self._view_needs_rebuild()
        if signature == self._render_signature and not needs_rebuild:
            return
        if self._render_signature is not None and self._has_editor_focus() and not needs_rebuild:
            return

        if getattr(self, "_rendering", False):
            return

        self._rendering = True
        try:
            updates_enabled = self.updatesEnabled()
            self.setUpdatesEnabled(False)
            try:
                self._settings_snapshot = settings
                if self._current_group not in self._group_order and self._group_order:
                    self._current_group = self._group_order[0]
                self._rebuild_group_navigation()
                self._refresh_language_texts()
                self._render_signature = signature
                self._render_current_group()
                self._refresh_theme_widgets()
            finally:
                self.setUpdatesEnabled(updates_enabled)
                if updates_enabled:
                    self.update()
        except Exception as exc:
            self._render_settings_error(exc)
        finally:
            self._rendering = False

    def _render_settings_error(self, exc: Exception) -> None:
        self._clear_detail_panel()

        error_card = QFrame()
        error_card.setObjectName("SettingsCard")
        error_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(error_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("配置中心渲染失败")
        title.setObjectName("SettingsDetailTitle")
        layout.addWidget(title)

        detail = QLabel(str(exc))
        detail.setWordWrap(True)
        detail.setObjectName("SettingsRowLabel")
        layout.addWidget(detail)

        self.detail_layout.addWidget(error_card, 0, Qt.AlignmentFlag.AlignTop)
        self._apply_settings_page_style()

    def _build_nav_button(self, group_name: str) -> QPushButton:
        button = QPushButton(self._t(group_name))
        button.setObjectName("SettingsNavButton")
        button.setProperty("groupName", group_name)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(38)

        pixmap = self._safe_icon_pixmap(GROUP_ICONS.get(group_name, "nav_settings.png"), 16)
        if pixmap is not None and not pixmap.isNull():
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(16, 16))

        button.clicked.connect(lambda _checked=False, name=group_name: self._set_current_group(name))
        return button

    def _set_current_group(self, group_name: str) -> None:
        if group_name not in self._group_order:
            return
        if self._current_group == group_name:
            self._sync_nav_buttons()
            if self._view_needs_rebuild():
                self._render_current_group()
            return

        self._current_group = group_name
        self._sync_nav_buttons()
        self._render_current_group()

    def _update_group_contract(self, settings_snapshot: dict, settings_contract: dict) -> None:
        raw_order = settings_contract.get("group_order") if isinstance(settings_contract, dict) else None
        raw_descriptions = settings_contract.get("group_descriptions") if isinstance(settings_contract, dict) else None

        if isinstance(raw_order, (list, tuple)):
            ordered = []
            seen_order = set()
            for group in raw_order:
                name = str(group).strip()
                if not name or name in seen_order:
                    continue
                ordered.append(name)
                seen_order.add(name)
        else:
            ordered = list(self.GROUP_ORDER)

        seen = set(ordered)
        for group in settings_snapshot.keys():
            name = str(group).strip()
            if not name or name in seen:
                continue
            ordered.append(name)
            seen.add(name)

        descriptions: dict[str, str] = dict(GROUP_DESCRIPTIONS)
        if isinstance(raw_descriptions, dict):
            for key, value in raw_descriptions.items():
                descriptions[str(key)] = str(value)

        self._group_order = ordered
        self._group_descriptions = {name: str(descriptions.get(name, "")) for name in self._group_order}

    def _rebuild_group_navigation(self) -> None:
        while self.nav_layout.count() > 1:
            item = self.nav_layout.takeAt(1)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        self._nav_buttons = {}
        for group_name in self._group_order:
            button = self._build_nav_button(group_name)
            self.nav_layout.addWidget(button)
            self._nav_buttons[group_name] = button
        self.nav_layout.addStretch(1)
        self._sync_nav_buttons()

    def _sync_nav_buttons(self) -> None:
        for name, button in self._nav_buttons.items():
            active = name == self._current_group
            button.setChecked(active)
            button.setProperty("active", "true" if active else "false")
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _clear_detail_panel(self) -> None:
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _render_current_group(self) -> None:
        if not hasattr(self, "detail_layout"):
            return

        self.detail_panel.setUpdatesEnabled(False)
        try:
            try:
                self._clear_detail_panel()
                self._switches.clear()
                self._segmented_controls.clear()

                group_name = self._current_group
                value = self._settings_snapshot.get(group_name, {})

                header = self._build_detail_header(group_name)
                self.detail_layout.addWidget(header, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

                form_card, form_layout = self._build_form_card()

                if group_name == "基础设置":
                    self._build_basic_settings(form_layout, value)
                elif group_name == "下载设置":
                    self._build_download_settings(form_layout, value)
                elif group_name == "平台设置":
                    self._build_platform_settings(form_layout, value)
                elif group_name == "播放设置":
                    self._build_playback_settings(form_layout, value)
                elif group_name == "日志设置":
                    self._build_log_settings(form_layout, value)
                elif group_name == "外观设置":
                    self._build_appearance_settings(form_layout, value)

                hint_card = self._build_group_hint_card(group_name)

                self.detail_layout.addWidget(
                    form_card,
                    0,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                )
                self.detail_layout.addSpacing(2)
                self.detail_layout.addWidget(
                    hint_card,
                    0,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                )
                self.detail_layout.addStretch(1)
            except Exception as exc:
                debug_logger.log_exception(
                    "SettingsPage",
                    "render_current_group",
                    exc,
                    details={"group": str(getattr(self, "_current_group", ""))},
                )
                self._render_settings_error(exc)
        finally:
            self.detail_panel.setUpdatesEnabled(True)
            self.detail_panel.update()

        self._refresh_theme_widgets()

    def _build_form_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SettingsFormCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedWidth(self._content_card_width())

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        return card, layout

    def _build_group_hint_card(self, group_name: str) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingsHintCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedWidth(self._content_card_width())
        card.setFixedHeight(40)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        icon = QLabel("i")
        icon.setObjectName("SettingsHintIcon")
        icon.setFixedSize(20, 20)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        raw_text = GROUP_HINTS.get(group_name, "")
        text = QLabel(self._t(raw_text))
        text.setObjectName("SettingsHintText")
        text.setWordWrap(False)
        text.setToolTip(self._t(raw_text))
        text.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(icon)
        layout.addWidget(text, 1)

        return card

    def _build_detail_header(self, group_name: str) -> QWidget:
        row = QWidget()
        row.setObjectName("SettingsDetailHeader")
        row.setFixedHeight(58)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setObjectName("SettingsDetailIcon")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_file = GROUP_ICONS.get(group_name, "nav_settings.png")
        pixmap = self._safe_icon_pixmap(icon_file, 22)
        if pixmap is not None and not pixmap.isNull():
            icon.setPixmap(pixmap)
        else:
            icon.setText(self._fallback_group_icon_text(group_name))
            icon.setStyleSheet(self._fallback_detail_icon_style())

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel(self._t(group_name))
        title.setObjectName("SettingsDetailTitle")

        subtitle_text = self._group_descriptions.get(group_name, "") or GROUP_DESCRIPTIONS.get(group_name, "")
        subtitle = QLabel(self._t(subtitle_text))
        subtitle.setObjectName("SettingsDetailSubtitle")
        subtitle.setWordWrap(False)
        subtitle.setToolTip(self._t(subtitle_text))
        subtitle.setMinimumWidth(0)

        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)

        layout.addWidget(icon)
        layout.addWidget(text_box, 1)
        return row

    def _has_editor_focus(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit):
            if focused is self or self.isAncestorOf(focused):
                return not focused.isReadOnly()
        for editor in self.findChildren(QLineEdit):
            if editor.hasFocus() and not editor.isReadOnly():
                return True
            original = editor.property("settingsOriginalText")
            if original is not None and not editor.isReadOnly() and editor.text() != str(original):
                return True
        return False

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if isinstance(watched, QLineEdit) and watched.objectName() == "SettingsLineEdit":
            if event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
                field = watched.parentWidget()
                if isinstance(field, QFrame) and field.objectName() == "SettingsPathField":
                    focused = event.type() == QEvent.Type.FocusIn
                    field.setProperty("focused", "true" if focused else "false")
                    field.style().unpolish(field)
                    field.style().polish(field)
                    field.update()
        return super().eventFilter(watched, event)

    @staticmethod
    def _settings_signature(settings: dict, contract: dict | None) -> tuple:
        def freeze(value: Any):
            if isinstance(value, dict):
                return tuple(sorted((str(key), freeze(item)) for key, item in value.items()))
            if isinstance(value, list):
                return tuple(freeze(item) for item in value)
            return str(value)

        return freeze((settings, contract or {}))

    @staticmethod
    def _dict_value(value: Any, key: str, default: Any = "") -> Any:
        return value.get(key, default) if isinstance(value, dict) else default

    def _safe_icon_pixmap(self, icon_file: str, size: int = 20) -> QPixmap | None:
        """Load icon safely. Never crash SettingsPage when icon resource is missing."""
        candidates = [
            ui_icon_path(icon_file),
            f"UI/icon/{icon_file}",
            icon_file,
            ui_icon_path("nav_settings.png"),
        ]

        icon = load_qt_icon(candidates)

        if icon is None:
            return None

        if icon.isNull():
            return None

        return icon.pixmap(size, size)

    def _fallback_group_icon_text(self, group_name: str) -> str:
        mapping = {
            "基础设置": "基",
            "下载设置": "下",
            "平台设置": "平",
            "播放设置": "播",
            "日志设置": "志",
            "外观设置": "观",
        }
        return mapping.get(group_name, "设")

    def _fallback_group_icon_style(self) -> str:
        c = self._colors()
        return f"""
        QLabel#SettingsCardIcon {{
            background: {c["accent_soft"]};
            color: {c["accent"]};
            border-radius: 11px;
            font-size: {self._scaled_px(11, minimum=10)}px;
            font-weight: 800;
        }}
        """

    def _fallback_detail_icon_style(self) -> str:
        c = self._colors()
        return f"""
        QLabel#SettingsDetailIcon {{
            background: {c["accent_soft"]};
            color: {c["accent"]};
            border-radius: 16px;
            font-size: {self._scaled_px(12, minimum=10)}px;
            font-weight: 800;
        }}
        """

    def _build_setting_row(
        self,
        label: str,
        control: QWidget,
        *,
        control_width: int = FORM_CONTROL_WIDTH,
        compact: bool = False,
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("SettingsSettingRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setFixedHeight(self._scaled_px(56 if compact else 60, minimum=56 if compact else 60))

        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(18)

        text_box = QWidget()
        text_box.setObjectName("SettingsItemTextBox")
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel(self._t(label))
        title.setObjectName("SettingsItemTitle")
        title.setWordWrap(False)
        title.setFixedHeight(20)

        short_desc = SETTING_SHORT_DESCRIPTIONS.get(label, "")
        long_desc = SETTING_DESCRIPTIONS.get(label, short_desc)
        title.setToolTip(self._t(long_desc))
        row.setToolTip(self._t(long_desc))

        text_layout.addWidget(title)
        if short_desc:
            desc = QLabel(self._t(short_desc))
            desc.setObjectName("SettingsItemDescription")
            desc.setWordWrap(False)
            desc.setFixedHeight(18)
            desc.setToolTip(self._t(long_desc))
            text_layout.addWidget(desc)

        control_wrap = QWidget()
        control_wrap.setObjectName("SettingsControlWrap")
        control_layout = QHBoxLayout(control_wrap)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)

        custom_control_height = control.property("settingsControlHeight")
        try:
            control_height = int(custom_control_height) if custom_control_height is not None else 0
        except (TypeError, ValueError):
            control_height = 0
        if control_height > 0:
            control.setMinimumHeight(control_height)
            control.setMaximumHeight(control_height)
        else:
            control.setMinimumHeight(36)
            control.setMaximumHeight(38)

        if isinstance(control, UiSwitch):
            control_layout.addStretch(1)
            control_layout.addWidget(control)
            control_wrap.setFixedWidth(FORM_SWITCH_WRAP_WIDTH)
        else:
            effective_width = self._effective_control_width(control_width)
            control.setFixedWidth(effective_width)
            control_layout.addWidget(control)
            control_wrap.setFixedWidth(effective_width)

        layout.addWidget(text_box, 1)
        layout.addWidget(control_wrap, 0, Qt.AlignmentFlag.AlignVCenter)

        return row

    def _build_combo(self, options: list[Any], current: Any, *, width: int = 0) -> QComboBox:
        combo = SettingsComboBox()
        combo.setObjectName("SettingsCombo")
        combo.setEditable(False)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setFixedHeight(self._scaled_px(38, minimum=38))
        combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(160)
        combo.setMaximumWidth(520)
        combo.setToolTip(str(current or ""))
        if width > 0:
            combo.setFixedWidth(width)
            combo.setProperty("comboPopupMaxWidth", int(width))

        normalized_options = self._normalize_combo_options(options, current)
        combo.setMaxVisibleItems(max(1, min(len(normalized_options), 12)))
        for value, label in normalized_options:
            combo.addItem(self._t(label), value)

        text = str(current or "")
        index = combo.findData(text)
        if index < 0:
            index = combo.findText(text)
        if index < 0:
            for option_value, option_label in normalized_options:
                if text and (text in option_label or text in option_value):
                    index = combo.findData(option_value)
                    break
        combo.setCurrentIndex(index if index >= 0 else 0)

        view = combo.view()
        if view is not None and combo.width() > 0:
            view.setObjectName("SettingsComboPopup")
            view.setMinimumWidth(combo.width())
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            if hasattr(view, "setUniformItemSizes"):
                view.setUniformItemSizes(True)
            self._style_combo_popup(combo)
        else:
            polish_combo_popup(combo)

        return combo

    def _style_combo_popup(self, combo: QComboBox) -> None:
        view = combo.view()
        if view is None:
            return
        view.setObjectName("SettingsComboPopup")
        visible_rows = max(1, min(combo.count(), 12))
        apply_themed_combo_box(
            combo,
            visible_rows=visible_rows,
            row_height=self._scaled_px(38, minimum=38),
            control_style=False,
        )
        view.setObjectName("SettingsComboPopup")
        width = combo.width() or combo.minimumWidth()
        if width > 0:
            target_width = int(width)
            combo.setProperty("comboPopupMaxWidth", target_width)
            combo.setProperty("comboPopupClampToControl", "true")
            view.setProperty("comboPopupTargetWidth", target_width)
            view.setMinimumWidth(target_width)
            view.setMaximumWidth(target_width)

    @staticmethod
    def _normalize_combo_options(options: list[Any], current: Any = "") -> list[tuple[str, str]]:
        normalized: list[tuple[str, str]] = []
        for option in list(options or []):
            if isinstance(option, dict):
                value = str(option.get("value") or option.get("id") or option.get("label") or "")
                label = str(option.get("label") or value)
            elif isinstance(option, (tuple, list)) and option:
                value = str(option[0])
                label = str(option[1] if len(option) > 1 else option[0])
            else:
                value = str(option)
                label = value
            if value:
                normalized.append((value, label))
        current_text = str(current or "")
        if current_text and not any(value == current_text for value, _label in normalized):
            normalized.insert(0, (current_text, current_text))
        if not normalized:
            normalized.append((current_text, current_text))
        return normalized

    def _compact_proxy_options(self, options: list[Any], current: Any = "") -> list[dict[str, str]]:
        compact: list[dict[str, str]] = []
        for value, label in self._normalize_combo_options(options, current):
            display = label
            port = self._proxy_port_text(label)
            if port and "(" in display:
                display = display.rsplit("(", 1)[0].strip()
            if "HTTP/SOCKS5" in display:
                display = value
            if value in {"直连", "自定义"}:
                display = value
            compact.append({"value": value, "label": display})
        return compact

    def _current_combo_value(self, combo: QComboBox) -> str:
        if combo.isEditable():
            current_index = combo.currentIndex()
            current_text = str(combo.currentText())
            if current_index >= 0 and current_text == str(combo.itemText(current_index)):
                data = combo.itemData(current_index)
                return str(data if data is not None else current_text)
            return current_text
        data = combo.currentData()
        return str(data if data is not None else combo.currentText())

    def _current_combo_int_value(self, combo: QComboBox, fallback: int = 0) -> int:
        try:
            return int(self._current_combo_value(combo))
        except (TypeError, ValueError):
            return int(fallback)

    def _emit_setting_changed(self, section: str, key: str, value: Any) -> None:
        if self._rendering:
            return
        if not section or not key:
            return
        self.setting_changed.emit(section, key, value)

    def _emit_basic_setting_changed(self, key: str, value: Any) -> None:
        self._emit_setting_changed("common", key, value)

    def _emit_theme_setting_changed(self, value: str) -> None:
        for switch in list(self._switches):
            if switch is not None and switch.property("settingsRole") == "follow_system":
                blocked = switch.blockSignals(True)
                try:
                    switch.setChecked(False)
                finally:
                    switch.blockSignals(blocked)
                switch.update()
        appearance = self._settings_snapshot.get("外观设置") if isinstance(self._settings_snapshot, dict) else None
        if isinstance(appearance, dict):
            appearance["follow_system"] = False
            appearance["theme"] = str(value)
            self._render_signature = None
        self._emit_setting_changed("common", "theme", value)

    def _build_switch(self, checked: bool) -> UiSwitch:
        switch = UiSwitch(self)
        switch.setChecked(bool(checked))
        switch.set_theme_colors(self._colors())
        self._switches.append(switch)
        return switch

    def _build_path_picker(self, value: Any, *, setting_key: str = "") -> QWidget:
        container = QFrame()
        container.setObjectName("SettingsPathField")
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        container.setFixedHeight(38)
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(4)

        path_text = str(value or "")
        editor = QLineEdit(path_text)
        editor.setObjectName("SettingsLineEdit")
        editor.setFrame(False)
        editor.setMinimumHeight(34)
        editor.setMaximumHeight(36)
        editor.setTextMargins(0, 0, 0, 0)
        editor.setMinimumWidth(0)
        editor.setPlaceholderText(self._t("选择或粘贴下载目录"))
        editor.setToolTip(path_text)
        editor.setProperty("settingsOriginalText", path_text)
        editor.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        editor.setCursorPosition(0)
        editor.installEventFilter(self)
        QTimer.singleShot(0, lambda e=editor: self._scroll_path_editor_start(e))
        if setting_key:
            editor.editingFinished.connect(lambda e=editor, key=setting_key: self._commit_path_editor(e, setting_key=key))
        layout.addWidget(editor, 1)

        browse = QToolButton()
        browse.setObjectName("SettingsPathBrowse")
        browse.setIcon(load_qt_icon([ui_icon_path(action_icon_file("open_directory"))]))
        browse.setIconSize(QSize(18, 18))
        browse.setToolTip(self._t("选择下载目录"))
        browse.setAccessibleName(self._t("选择下载目录"))
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.setFixedSize(34, 30)
        browse.clicked.connect(lambda: self._browse_download_directory(editor, setting_key=setting_key))
        layout.addWidget(browse)
        return container

    def _commit_path_editor(self, editor: QLineEdit, *, setting_key: str = "") -> None:
        text = editor.text()
        editor.setToolTip(text)
        editor.setProperty("settingsOriginalText", text)
        if setting_key:
            self._emit_basic_setting_changed(setting_key, text)

    @staticmethod
    def _scroll_path_editor_start(editor: QLineEdit) -> None:
        editor.setCursorPosition(0)
        try:
            editor.home(False)
        except (RuntimeError, AttributeError, TypeError) as exc:
            debug_logger.log_exception("SettingsPage", "scroll_path_editor_start", exc)

    def _browse_download_directory(self, editor: QLineEdit, *, setting_key: str = "") -> None:
        self._open_download_directory_dialog(editor, setting_key=setting_key)

    def _open_download_directory_dialog(self, editor: QLineEdit, *, setting_key: str = "") -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            self._t("选择下载目录"),
            editor.text() or "",
            QFileDialog.Option.ShowDirsOnly,
        )
        self._apply_browsed_download_directory(editor, directory, setting_key=setting_key)

    def _clear_directory_dialog(self, dialog: QFileDialog) -> None:
        try:
            self._directory_dialogs = [item for item in self._directory_dialogs if item is not dialog]
        except RuntimeError as exc:
            debug_logger.log_exception("SettingsPage", "clear_directory_dialog", exc)

    def _apply_browsed_download_directory(self, editor: QLineEdit, directory: str, *, setting_key: str = "") -> None:
        if not directory:
            return
        try:
            editor.setText(directory)
            editor.setToolTip(directory)
            editor.setProperty("settingsOriginalText", directory)
            self._scroll_path_editor_start(editor)
        except RuntimeError as exc:
            debug_logger.log_exception("SettingsPage", "apply_browsed_download_directory", exc)
            return
        if setting_key:
            self._emit_basic_setting_changed(setting_key, directory)

    def _build_basic_settings(self, layout: QVBoxLayout, value: Any) -> None:
        large_w = self._effective_control_width(FORM_CONTROL_WIDTH_LARGE)
        options = self._dict_value(value, "_options", {})
        filename_options = self._dict_value(options, "filename_template", [])
        open_mode_options = self._dict_value(options, "default_open_mode", [])

        layout.addWidget(
            self._build_setting_row(
                "\u4e0b\u8f7d\u76ee\u5f55",
                self._build_path_picker(
                    self._dict_value(value, "download_directory"),
                    setting_key="download_directory",
                ),
                control_width=large_w,
            )
        )

        naming_row = QWidget()
        naming_row.setFixedWidth(large_w)
        naming_row.setFixedHeight(38)
        naming_layout = QHBoxLayout(naming_row)
        naming_layout.setContentsMargins(0, 0, 0, 0)
        naming_layout.setSpacing(6)
        naming_combo = self._build_combo(
            filename_options,
            self._dict_value(value, "filename_template", "current"),
            width=large_w,
        )
        naming_combo.currentIndexChanged.connect(
            lambda *_args, combo=naming_combo: self._emit_basic_setting_changed(
                "filename_template",
                self._current_combo_value(combo),
            )
        )
        naming_layout.addWidget(naming_combo)
        layout.addWidget(
            self._build_setting_row("\u6587\u4ef6\u547d\u540d\u89c4\u5219", naming_row, control_width=large_w),
        )

        auto_open_switch = self._build_switch(bool(self._dict_value(value, "open_after_download", False)))
        auto_open_switch.toggled.connect(
            lambda checked: self._emit_basic_setting_changed("open_after_download", bool(checked))
        )
        layout.addWidget(
            self._build_setting_row(
                "\u4e0b\u8f7d\u540e\u81ea\u52a8\u6253\u5f00",
                auto_open_switch,
            )
        )

        open_mode_row = QWidget()
        open_mode_row.setObjectName("SettingsOpenBehaviorControl")
        open_mode_row.setFixedWidth(large_w)
        open_mode_height = self._scaled_px(44, minimum=44)
        open_mode_row.setFixedHeight(open_mode_height)
        open_mode_row.setProperty("settingsControlHeight", open_mode_height)
        open_mode_layout = QHBoxLayout(open_mode_row)
        open_mode_layout.setContentsMargins(0, 3, 0, 3)
        open_mode_spacing = 8
        open_mode_layout.setSpacing(open_mode_spacing)
        bind_button = QPushButton(self._t("\u7ed1\u5b9a\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f"))
        bind_button.setObjectName("SettingsActionButton")
        bind_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_width = min(self._scaled_px(118, minimum=108), max(96, large_w - 180))
        bind_button.setFixedWidth(bind_width)
        bind_button.setFixedHeight(self._scaled_px(38, minimum=38))
        bind_button.clicked.connect(lambda: self.file_association_requested.emit(True, True))
        open_mode_combo = self._build_combo(
            open_mode_options,
            self._dict_value(value, "default_open_mode", "builtin_player"),
            width=max(96, large_w - bind_width - open_mode_spacing),
        )
        open_mode_combo.currentIndexChanged.connect(
            lambda *_args, combo=open_mode_combo: self._emit_basic_setting_changed(
                "default_open_mode",
                self._current_combo_value(combo),
            )
        )
        open_mode_layout.addWidget(open_mode_combo)
        open_mode_layout.addWidget(bind_button)
        layout.addWidget(
            self._build_setting_row("\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f", open_mode_row, control_width=large_w),
        )

    def _build_download_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})

        max_concurrent = self._build_combo(
            self._dict_value(options, "max_concurrent", CONCURRENCY_OPTIONS),
            self._dict_value(value, "max_concurrent", 3),
            width=FORM_CONTROL_WIDTH,
        )
        max_concurrent.currentIndexChanged.connect(
            lambda *_args, combo=max_concurrent: self._emit_setting_changed(
                "download",
                "max_concurrent",
                self._current_combo_int_value(combo, 3),
            )
        )
        layout.addWidget(self._build_setting_row("并发数", max_concurrent))

        image_concurrency_switch = self._build_switch(
            self._dict_value(value, "image_respects_concurrency", False)
        )
        image_concurrency_switch.toggled.connect(
            lambda checked: self._emit_setting_changed(
                "download",
                "image_respects_concurrency",
                bool(checked),
            )
        )
        layout.addWidget(self._build_setting_row("图片受并发数限制", image_concurrency_switch))

        request_timeout = self._build_combo(
            self._dict_value(options, "request_timeout", TIMEOUT_OPTIONS),
            self._dict_value(value, "request_timeout", 60),
            width=FORM_CONTROL_WIDTH,
        )
        request_timeout.currentIndexChanged.connect(
            lambda *_args, combo=request_timeout: self._emit_setting_changed(
                "download",
                "request_timeout",
                self._current_combo_int_value(combo, 60),
            )
        )
        layout.addWidget(self._build_setting_row("请求超时（秒）", request_timeout))

        max_retries = self._build_combo(
            self._dict_value(options, "max_retries", RETRY_OPTIONS),
            self._dict_value(value, "max_retries", 3),
            width=FORM_CONTROL_WIDTH,
        )
        max_retries.currentIndexChanged.connect(
            lambda *_args, combo=max_retries: self._emit_setting_changed(
                "download",
                "max_retries",
                self._current_combo_int_value(combo, 3),
            )
        )
        layout.addWidget(self._build_setting_row("重试次数", max_retries))

        resume_switch = self._build_switch(self._dict_value(value, "resume_enabled", True))
        resume_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("download", "resume_enabled", bool(checked))
        )
        layout.addWidget(self._build_setting_row("断点续传", resume_switch))

        speed_limit = self._build_combo(
            self._dict_value(options, "speed_limit_kb", SPEED_LIMIT_OPTIONS),
            self._dict_value(value, "speed_limit_kb", 0),
            width=FORM_CONTROL_WIDTH,
        )
        speed_limit.currentIndexChanged.connect(
            lambda *_args, combo=speed_limit: self._emit_setting_changed(
                "download",
                "speed_limit_kb",
                self._current_combo_int_value(combo, 0),
            )
        )
        layout.addWidget(self._build_setting_row("下载速度限制（KB/s）", speed_limit))

        video_only_switch = self._build_switch(self._dict_value(value, "video_only", False))
        video_only_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("download", "video_only", bool(checked))
        )
        layout.addWidget(self._build_setting_row("仅下载视频", video_only_switch))

    def _platform_proxy_policy(self, platform_id: str, platform_name: str) -> dict[str, Any]:
        pid = str(platform_id or "").strip().lower()
        pname = str(platform_name or "").strip().lower()
        editable = pid == "missav" or "missav" in pname
        return {
            "editable": editable,
            "tooltip": "" if editable else "该平台默认使用系统代理，无需单独设置",
        }

    def _platform_icon_label(self, platform_id: str, platform_name: str) -> QLabel:
        label = QLabel()
        label.setObjectName("SettingsPlatformIcon")
        label.setFixedSize(24, 24)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pid = str(platform_id or "").strip().lower()
        icon_file = platform_icon_file(pid) if pid else "platform_web.png"
        pixmap = self._safe_icon_pixmap(icon_file, 20)

        if pixmap is not None and not pixmap.isNull():
            label.setPixmap(pixmap)
            return label

        letter = PLATFORM_FALLBACK_LETTERS.get(pid, (platform_name or "?")[:1].upper())
        label.setText(letter)
        colors = self._colors()
        label.setStyleSheet(
            f"""
            QLabel#SettingsPlatformIcon {{
                background: {colors["accent_soft"]};
                color: {colors["accent"]};
                border-radius: 12px;
                font-size: {self._scaled_px(11, minimum=10)}px;
                font-weight: 700;
            }}
            """
        )
        return label

    def _auth_badge(self, auth_status: str, *, fixed_width: int | None = None) -> QWidget:
        authenticated = str(auth_status or "").strip() == "已认证"
        badge = QLabel(self._t("已认证" if authenticated else "未认证"))
        badge.setObjectName("SettingsAuthBadge")
        badge.setProperty("authenticated", "true" if authenticated else "false")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(28)
        if fixed_width is not None:
            badge.setFixedWidth(fixed_width)
        badge.style().unpolish(badge)
        badge.style().polish(badge)
        return badge

    def _platform_header_cell(self, text: str, width: int) -> QLabel:
        label = QLabel(self._t(text))
        label.setObjectName("SettingsPlatformHeaderCell")
        label.setFixedWidth(width)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _platform_count_combo(self, row: dict[str, Any], *, width: int | None = None) -> QComboBox:
        platform_id = str(row.get("id") or "")
        config_key = str(row.get("count_config_key") or "")
        combo = self._build_combo(
            list(row.get("count_options") or PLATFORM_COUNT_OPTIONS),
            str(row.get("default_count") or 20),
            width=int(width or PLATFORM_DETAIL_COL_WIDTHS["count"]),
        )
        combo.setEnabled(bool(row.get("count_editable", True) and platform_id and config_key))
        if combo.isEnabled():
            combo.currentIndexChanged.connect(
                lambda *_args, control=combo, pid=platform_id, key=config_key: self._emit_setting_changed(
                    pid,
                    key,
                    int(self._current_combo_value(control)),
                )
            )
        else:
            combo.setToolTip(self._t("该平台暂无可热加载的爬取数量配置"))
        return combo

    def _platform_timeout_combo(self, row: dict[str, Any], *, width: int | None = None) -> QComboBox:
        platform_id = str(row.get("id") or "")
        config_key = str(row.get("timeout_config_key") or "")
        combo = self._build_combo(
            list(row.get("timeout_options") or TIMEOUT_OPTIONS),
            str(row.get("default_timeout") or row.get("timeout") or 60),
            width=int(width or PLATFORM_DETAIL_COL_WIDTHS["timeout"]),
        )
        combo.setEnabled(bool(row.get("timeout_editable", False) and platform_id and config_key))
        if combo.isEnabled():
            combo.currentIndexChanged.connect(
                lambda *_args, control=combo, pid=platform_id, key=config_key: self._emit_setting_changed(
                    pid,
                    key,
                    int(self._current_combo_value(control)),
                )
            )
        else:
            combo.setToolTip(self._t("该平台暂无可热加载的超时配置"))
        return combo

    def _platform_proxy_widget(
        self,
        row: dict[str, Any],
        policy: dict[str, Any],
        *,
        row_container: QWidget | None = None,
        width: int | None = None,
    ) -> QWidget:
        platform_id = str(row.get("id") or "")
        config_key = str(row.get("proxy_config_key") or "")
        editable = bool(row.get("proxy_editable", policy.get("editable")) and platform_id and config_key)
        proxy_value = str(row.get("proxy") or "系统代理")
        options = self._compact_proxy_options(list(row.get("proxy_options") or PROXY_OPTIONS), proxy_value)
        option_values = {value for value, _label in self._normalize_combo_options(options, proxy_value)}
        if editable and proxy_value not in option_values:
            proxy_value = "自定义"
        if not editable:
            proxy_value = "系统代理"

        custom_allowed = bool(row.get("proxy_custom_allowed"))
        proxy_width = int(width or PLATFORM_DETAIL_COL_WIDTHS["proxy"])
        collapsed_combo_width = proxy_width
        active_combo_width = max(72, min(206, int(proxy_width * 0.58))) if custom_allowed else proxy_width
        active_input_min_width = 0
        if custom_allowed:
            active_input_min_width = max(54, min(112, proxy_width - active_combo_width - 8))
            if active_combo_width + active_input_min_width + 8 > proxy_width:
                active_combo_width = max(72, proxy_width - active_input_min_width - 8)
        proxy_combo = self._build_combo(options, proxy_value, width=collapsed_combo_width)
        proxy_combo.setEnabled(editable)
        proxy_combo.setProperty("proxyCustomAllowed", "true" if custom_allowed else "false")
        proxy_combo.setEditable(False)

        if not custom_allowed:
            if policy["tooltip"]:
                proxy_combo.setToolTip(str(policy["tooltip"]))
            return proxy_combo

        container = QWidget()
        container.setObjectName("SettingsProxyControl")
        container.setFixedWidth(proxy_width)
        container.setFixedHeight(self._scaled_px(38, minimum=38))
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        line_edit = QLineEdit()
        line_edit.setObjectName("SettingsProxyCustomEdit")
        line_edit.setFixedHeight(self._scaled_px(38, minimum=38))
        line_edit.setMinimumWidth(active_input_min_width or 92)
        line_edit.setPlaceholderText(self._t("端口"))
        line_edit.setClearButtonEnabled(False)
        line_edit.setEnabled(False)
        existing_custom = str(row.get("proxy_custom_value") or "").strip()
        if existing_custom:
            line_edit.setText(self._proxy_port_text(existing_custom))
        elif proxy_value not in {"系统代理", "直连", "自定义"}:
            line_edit.setText(self._proxy_port_text(proxy_value))

        container_layout.addWidget(proxy_combo, 0)
        container_layout.addWidget(line_edit, 1)

        def _sync_custom_state(active: bool, *, focus: bool = False) -> None:
            proxy_combo.setProperty("customProxy", "true" if active else "false")
            proxy_combo.setFixedWidth(active_combo_width if active else collapsed_combo_width)
            line_edit.setVisible(bool(active))
            line_edit.setEnabled(bool(active and editable))
            line_edit.setClearButtonEnabled(bool(active and editable))
            line_edit.setProperty("customProxyActive", "true" if active else "false")
            line_edit.setToolTip(existing_custom if existing_custom else line_edit.placeholderText())
            container.setProperty("customProxyActive", "true" if active else "false")
            if active and focus:
                line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
                line_edit.selectAll()
            container.updateGeometry()
            proxy_combo.style().unpolish(proxy_combo)
            proxy_combo.style().polish(proxy_combo)
            line_edit.style().unpolish(line_edit)
            line_edit.style().polish(line_edit)

        custom_active = bool(editable and (row.get("proxy_custom_active") or proxy_value == "自定义"))
        if custom_active:
            custom_index = proxy_combo.findData("自定义")
            if custom_index < 0:
                custom_index = proxy_combo.findText(self._t("自定义 HTTP/SOCKS5 端点"))
            if custom_index >= 0:
                proxy_combo.setCurrentIndex(custom_index)
            proxy_combo.setToolTip(existing_custom or self._t("端口"))
        _sync_custom_state(custom_active)
        if editable:
            def _on_proxy_changed(*_args, control=proxy_combo, pid=platform_id, key=config_key) -> None:
                value = self._current_combo_value(control)
                is_custom = value == "自定义"
                _sync_custom_state(is_custom, focus=is_custom)
                self._emit_proxy_setting_changed(pid, key, value)

            proxy_combo.currentIndexChanged.connect(_on_proxy_changed)

            def _commit_custom_proxy(edit=line_edit, control=proxy_combo, pid=platform_id, key=config_key) -> None:
                if control.property("customProxy") != "true":
                    return
                value = edit.text().strip()
                if not value or value in {"自定义", self._t("自定义 HTTP/SOCKS5 端点")}:
                    return
                self._emit_proxy_setting_changed(pid, key, "自定义")
                self._emit_proxy_setting_changed(pid, "proxy_url", self._proxy_endpoint_from_port(value))

            line_edit.editingFinished.connect(_commit_custom_proxy)
        elif policy["tooltip"]:
            container.setToolTip(str(policy["tooltip"]))
            line_edit.setToolTip(str(policy["tooltip"]))
        return container

    @staticmethod
    def _proxy_port_text(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        if "://" in text:
            text = text.split("://", 1)[1]
        if "@" in text:
            text = text.rsplit("@", 1)[-1]
        if "/" in text:
            text = text.split("/", 1)[0]
        if ":" in text:
            candidate = text.rsplit(":", 1)[-1].strip()
            if candidate.isdigit():
                return candidate
        if "(" in text and ")" in text:
            candidate = text.rsplit("(", 1)[-1].split(")", 1)[0].strip()
            if candidate.isdigit():
                return candidate
        if lowered.startswith(("clash", "v2ray", "sing-box", "nekoray")):
            digits = "".join(ch if ch.isdigit() else " " for ch in text).split()
            return digits[-1] if digits else ""
        return text if text.isdigit() else ""

    @staticmethod
    def _proxy_endpoint_from_port(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
            return text
        if text.isdigit():
            return f"http://127.0.0.1:{text}"
        if ":" in text:
            return f"http://{text}"
        return text

    def _emit_proxy_setting_changed(self, platform_id: str, key: str, value: str) -> None:
        signature = (str(platform_id), str(key), str(value))
        if self._last_proxy_emit == signature:
            return
        self._last_proxy_emit = signature
        self._emit_setting_changed(platform_id, key, value)

    def _elided_platform_name(self, platform_name: str, max_width: int) -> str:
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(platform_name, Qt.TextElideMode.ElideRight, max(24, max_width))

    def _build_platform_summary_chip(self, label: str, value: str, kind: str) -> QFrame:
        chip = QFrame()
        chip.setObjectName("SettingsPlatformSummaryChip")
        chip.setProperty("kind", kind)
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedHeight(30)

        layout = QHBoxLayout(chip)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        label_widget = QLabel(self._t(label))
        label_widget.setObjectName("SettingsPlatformSummaryLabel")

        value_widget = QLabel(value)
        value_widget.setObjectName("SettingsPlatformSummaryValue")
        value_widget.setProperty("kind", kind)

        layout.addWidget(label_widget)
        layout.addWidget(value_widget)

        chip.style().unpolish(chip)
        chip.style().polish(chip)
        value_widget.style().unpolish(value_widget)
        value_widget.style().polish(value_widget)

        return chip

    def _build_platform_summary_bar(self, rows: list[dict[str, Any]]) -> QFrame:
        total = len(rows)
        authed = sum(1 for row in rows if str(row.get("auth_status") or "") == "已认证")
        unauth = max(0, total - authed)
        proxy_editable = sum(
            1
            for row in rows
            if self._platform_proxy_policy(
                str(row.get("id") or ""),
                str(row.get("name") or row.get("id") or ""),
            ).get("editable")
        )

        bar = QFrame()
        bar.setObjectName("SettingsPlatformSummaryBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedWidth(self._form_inner_width())
        bar.setFixedHeight(48)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_platform_summary_chip("平台总数", str(total), "neutral"))
        layout.addWidget(self._build_platform_summary_chip("已认证", str(authed), "success"))
        layout.addWidget(self._build_platform_summary_chip("未认证", str(unauth), "warning"))
        layout.addWidget(self._build_platform_summary_chip("可配置代理", str(proxy_editable), "accent"))
        layout.addStretch(1)

        return bar

    def _build_platform_table_header(self, rows: list[dict[str, Any]]) -> QWidget:
        col_widths = self._platform_col_widths(rows)

        header = QWidget()
        header.setObjectName("SettingsPlatformHeader")
        header.setFixedHeight(38)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(self._platform_header_cell("平台", col_widths["name"]))
        header_layout.addWidget(self._platform_header_cell("认证状态", col_widths["auth"]))
        header_layout.addWidget(self._platform_header_cell("爬取数量", col_widths["count"]))
        header_layout.addWidget(self._platform_header_cell("超时", col_widths["timeout"]))
        header_layout.addWidget(self._platform_header_cell("代理入口", col_widths["proxy"]))
        header_layout.addStretch(1)
        return header

    def _build_platform_table_body(self, rows: list[dict[str, Any]], col_widths: dict[str, int]) -> QWidget:
        body = QWidget()
        body.setObjectName("SettingsPlatformTable")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        for row in rows:
            body_layout.addWidget(self._build_platform_row(row, col_widths))

        return body

    @staticmethod
    def _platform_row_height(row: dict[str, Any]) -> int:
        return 48

    def _build_platform_settings(self, layout: QVBoxLayout, value: Any) -> None:
        rows = value if isinstance(value, list) else []

        layout.addWidget(self._build_platform_summary_bar(rows), 0, Qt.AlignmentFlag.AlignTop)
        layout.addSpacing(8)

        table = QFrame()
        table.setObjectName("SettingsPlatformTablePanel")
        table.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        table.setFixedWidth(self._form_inner_width())

        table_layout = QVBoxLayout(table)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        col_widths = self._platform_col_widths(rows)
        table_layout.addWidget(self._build_platform_table_header(rows))

        header_divider = QFrame()
        header_divider.setObjectName("SettingsCardDivider")
        header_divider.setFixedHeight(1)
        table_layout.addWidget(header_divider)

        table_body = self._build_platform_table_body(rows, col_widths)
        body_height = sum(self._platform_row_height(row) for row in rows) or 48

        if len(rows) > 6 or body_height > 340:
            scroll = QScrollArea()
            scroll.setObjectName("SettingsPlatformScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFixedHeight(min(360, body_height))
            scroll.setWidget(table_body)
            table_layout.addWidget(scroll, 0, Qt.AlignmentFlag.AlignTop)
            table.setFixedHeight(38 + 1 + scroll.height())
        else:
            table_layout.addWidget(table_body, 0, Qt.AlignmentFlag.AlignTop)
            table.setFixedHeight(38 + 1 + body_height)

        layout.addWidget(table, 0, Qt.AlignmentFlag.AlignTop)

    def _build_platform_row(self, row: dict[str, Any], col_widths: dict[str, int] | None = None) -> QWidget:
        platform_id = str(row.get("id") or "")
        platform_name = str(row.get("name") or row.get("id") or "平台")
        policy = self._platform_proxy_policy(platform_id, platform_name)
        col_widths = col_widths or self._platform_col_widths([row])

        line = QWidget()
        line.setObjectName("SettingsPlatformRow")
        line.setFixedHeight(self._platform_row_height(row))
        line_layout = QHBoxLayout(line)
        line_layout.setContentsMargins(14, 4, 14, 4)
        line_layout.setSpacing(10)

        name_cell = QWidget()
        name_cell.setFixedWidth(col_widths["name"])
        name_layout = QHBoxLayout(name_cell)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(7)
        name_layout.addWidget(self._platform_icon_label(platform_id, platform_name))
        name_label = QLabel(self._elided_platform_name(platform_name, col_widths["name"] - 34))
        name_label.setObjectName("SettingsPlatformName")
        name_label.setToolTip(platform_name)
        name_layout.addWidget(name_label, 1)
        line_layout.addWidget(name_cell, 0)

        auth_badge = self._auth_badge(str(row.get("auth_status") or "未认证"), fixed_width=col_widths["auth"])
        line_layout.addWidget(auth_badge, 0)

        line_layout.addWidget(self._platform_count_combo(row, width=col_widths["count"]), 0)
        line_layout.addWidget(self._platform_timeout_combo(row, width=col_widths["timeout"]), 0)
        line_layout.addWidget(self._platform_proxy_widget(row, policy, row_container=line, width=col_widths["proxy"]), 0)
        line_layout.addStretch(1)

        return line

    def _build_playback_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})
        player_combo = self._build_combo(
            self._dict_value(options, "default_player", []),
            self._dict_value(value, "default_player", "builtin_player"),
            width=FORM_CONTROL_WIDTH,
        )
        player_combo.currentIndexChanged.connect(
            lambda *_args, combo=player_combo: self._emit_setting_changed(
                "playback",
                "default_player",
                self._current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("打开方式", player_combo))

        remember_switch = self._build_switch(self._dict_value(value, "remember_position", True))
        remember_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("playback", "remember_position", bool(checked))
        )
        layout.addWidget(self._build_setting_row("记住播放进度", remember_switch))

        autoplay_switch = self._build_switch(self._dict_value(value, "autoplay_next", True))
        autoplay_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("playback", "autoplay_next", bool(checked))
        )
        layout.addWidget(self._build_setting_row("视频播放完自动下一项", autoplay_switch))

        image_controls = QWidget()
        image_controls.setObjectName("ImageAutoAdvanceControls")
        image_controls.setProperty("settingsControlHeight", 38)
        image_layout = QHBoxLayout(image_controls)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(10)

        interval_combo = self._build_combo(
            self._dict_value(options, "image_auto_advance_interval_seconds", []),
            self._dict_value(value, "image_auto_advance_interval_seconds", 5),
            width=self._scaled_px(126, minimum=112),
        )
        interval_combo.setObjectName("ImageAutoAdvanceIntervalCombo")
        interval_combo.setToolTip(self._t("\u56fe\u7247\u81ea\u52a8\u8f6e\u64ad\u7684\u5207\u6362\u95f4\u9694"))
        interval_combo.currentIndexChanged.connect(
            lambda *_args, combo=interval_combo: self._emit_setting_changed(
                "playback",
                "image_auto_advance_interval_seconds",
                self._current_combo_int_value(combo, 5),
            )
        )

        image_switch = self._build_switch(self._dict_value(value, "manual_image_switch", True))
        image_switch.setObjectName("ImageManualSwitch")

        def sync_interval_visibility(checked: bool) -> None:
            show_interval = not bool(checked)
            interval_combo.setVisible(show_interval)
            interval_combo.setEnabled(show_interval)
            image_controls.setProperty("autoAdvanceEnabled", "true" if show_interval else "false")
            image_controls.style().unpolish(image_controls)
            image_controls.style().polish(image_controls)
            image_controls.updateGeometry()

        image_switch.toggled.connect(sync_interval_visibility)
        image_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("playback", "manual_image_switch", bool(checked))
        )
        image_layout.addStretch(1)
        image_layout.addWidget(interval_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        image_layout.addWidget(image_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        sync_interval_visibility(image_switch.isChecked())
        layout.addWidget(self._build_setting_row("\u56fe\u7247\u53ea\u624b\u52a8\u5207\u6362", image_controls))

    def _build_log_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})

        retention = self._build_combo(
            self._dict_value(options, "retention_days", RETENTION_OPTIONS),
            self._dict_value(value, "retention_days", 1),
            width=FORM_CONTROL_WIDTH,
        )
        retention.currentIndexChanged.connect(
            lambda *_args, combo=retention: self._emit_setting_changed(
                "logging",
                "retention_days",
                self._current_combo_int_value(combo, 1),
            )
        )
        layout.addWidget(self._build_setting_row("日志保留天数", retention))

        display_count = self._build_combo(
            self._dict_value(options, "ui_log_max_display_count", UI_LOG_MAX_DISPLAY_OPTIONS),
            self._dict_value(value, "ui_log_max_display_count", 300),
            width=FORM_CONTROL_WIDTH,
        )
        display_count.currentIndexChanged.connect(
            lambda *_args, combo=display_count: self._emit_setting_changed(
                "logging",
                "ui_log_max_display_count",
                self._current_combo_int_value(combo, 300),
            )
        )
        layout.addWidget(self._build_setting_row("UI日志最大显示数量", display_count))

        trace_switch = self._build_switch(self._dict_value(value, "auto_copy_trace_on_error", True))
        trace_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("logging", "auto_copy_trace_on_error", bool(checked))
        )
        layout.addWidget(self._build_setting_row("错误时自动复制 Trace", trace_switch))

    def _build_appearance_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})

        language_combo = self._build_combo(
            self._dict_value(options, "language", []),
            self._dict_value(value, "language", "zh-CN"),
            width=FORM_CONTROL_WIDTH,
        )
        language_combo.currentIndexChanged.connect(
            lambda *_args, combo=language_combo: self._emit_setting_changed(
                "appearance",
                "language",
                self._current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("语言", language_combo))

        follow_switch = self._build_switch(self._dict_value(value, "follow_system", False))
        follow_switch.setProperty("settingsRole", "follow_system")
        follow_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("appearance", "follow_system", bool(checked))
        )
        layout.addWidget(self._build_setting_row("跟随系统", follow_switch))

        theme_segment = SegmentedControl([("light", self._t("浅色")), ("dark", self._t("深色"))], parent=self)
        theme_segment.setProperty("settingsRole", "theme")
        theme_segment.set_theme_colors(self._colors())
        theme_value = str(self._dict_value(value, "theme", "light")).lower()
        theme_segment.set_value("dark" if theme_value == "dark" else "light")
        theme_segment.setFixedWidth(260)
        theme_segment.selection_changed.connect(self._emit_theme_setting_changed)
        self._segmented_controls.append(theme_segment)
        layout.addWidget(self._build_setting_row("浅色 / 深色", theme_segment, control_width=260))

        accent_combo = self._build_combo(
            self._dict_value(options, "accent", []),
            self._dict_value(value, "accent", "blue"),
            width=FORM_CONTROL_WIDTH,
        )
        accent_combo.currentIndexChanged.connect(
            lambda *_args, combo=accent_combo: self._emit_setting_changed(
                "appearance",
                "accent",
                self._current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("主题色", accent_combo))

        scale_combo = self._build_combo(
            self._dict_value(options, "scale", []),
            self._dict_value(value, "scale", "100%"),
            width=FORM_CONTROL_WIDTH,
        )
        scale_combo.currentIndexChanged.connect(
            lambda *_args, combo=scale_combo: self._emit_setting_changed(
                "appearance",
                "scale",
                self._current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("界面缩放", scale_combo))

        font_combo = self._build_combo(
            self._dict_value(options, "font_size", []),
            self._dict_value(value, "font_size", "medium"),
            width=FORM_CONTROL_WIDTH,
        )
        font_combo.currentIndexChanged.connect(
            lambda *_args, combo=font_combo: self._emit_setting_changed(
                "appearance",
                "font_size",
                self._current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("字体大小", font_combo))

    def show_action_feedback(self, message: str, *, ok: bool = True) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.action_feedback.setText(text)
        self.action_feedback.setProperty("status", "ok" if ok else "error")
        self.action_feedback.setVisible(True)
        self.action_feedback.style().unpolish(self.action_feedback)
        self.action_feedback.style().polish(self.action_feedback)
        QTimer.singleShot(6000, lambda label=self.action_feedback: label.setVisible(False))

    def _apply_settings_page_style(self) -> None:
        if getattr(self, "_applying_style", False):
            return

        c = self._colors()
        page_title_px = self._scaled_px(22, minimum=20)
        detail_title_px = self._scaled_px(19, minimum=17)
        card_title_px = self._scaled_px(16, minimum=15)
        body_px = self._scaled_px(13, minimum=12)
        small_px = self._scaled_px(12, minimum=11)
        tiny_px = self._scaled_px(11, minimum=10)
        combo_px = self._scaled_px(13, minimum=12)

        qss = f"""
            QWidget#SettingsPage {{
                background: transparent;
            }}

            QLabel#SettingsPageTitle {{
                color: {c["text"]};
                font-size: {page_title_px}px;
                font-weight: 800;
                padding: 0px;
            }}

            QLabel#SettingsPageSubtitle {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 500;
            }}

            QLabel#SettingsActionFeedback {{
                color: {c["success"]};
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                padding: 3px 10px;
                font-size: {small_px}px;
                font-weight: 600;
            }}

            QLabel#SettingsActionFeedback[status="error"] {{
                color: {c["danger"]};
            }}

            QFrame#SettingsMainPanel {{
                background: transparent;
                border: none;
            }}

            QFrame#SettingsSideNav {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 14px;
            }}

            QFrame#SettingsDetailPanel {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 14px;
            }}

            QPushButton#SettingsNavButton {{
                text-align: left;
                padding-left: 10px;
                padding-right: 10px;
                border: 1px solid transparent;
                border-radius: 9px;
                background: transparent;
                color: {c["text"]};
                font-size: {body_px}px;
                font-weight: 600;
            }}

            QPushButton#SettingsNavButton:hover {{
                background: {c["panel_soft"]};
                border-color: {c["border"]};
            }}

            QPushButton#SettingsNavButton:checked,
            QPushButton#SettingsNavButton[active="true"] {{
                background: {c["accent_soft"]};
                color: {c["accent"]};
                border-left: 3px solid {c["accent"]};
                font-weight: 800;
            }}

            QLabel#SettingsNavTitle {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 700;
                padding-left: 8px;
            }}

            QLabel#SettingsDetailTitle {{
                color: {c["text"]};
                font-size: {detail_title_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsDetailSubtitle {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 500;
            }}

            QLabel#SettingsDetailIcon {{
                background: {c["accent_soft"]};
                border-radius: 16px;
            }}

            QFrame#SettingsFormCard {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 12px;
            }}

            QFrame#SettingsSettingRow {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QFrame#SettingsSettingRow:hover {{
                border-color: {c["border_strong"]};
                background: {c["input"]};
            }}

            QLabel#SettingsItemTitle {{
                color: {c["text"]};
                font-size: {body_px}px;
                font-weight: 700;
            }}

            QLabel#SettingsItemDescription {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 400;
            }}

            QFrame#SettingsHintCard {{
                background: {c["accent_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QLabel#SettingsHintIcon {{
                background: {c["accent"]};
                color: #ffffff;
                border-radius: 10px;
                font-size: {small_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsHintText {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 500;
            }}

            QFrame#SettingsPlatformTablePanel {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 11px;
            }}

            QFrame#SettingsPlatformSummaryBar {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 11px;
            }}

            QFrame#SettingsPlatformSummaryChip {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 15px;
            }}

            QFrame#SettingsPlatformSummaryChip[kind="success"] {{
                background: rgba(34, 197, 94, 0.10);
                border: 1px solid rgba(34, 197, 94, 0.24);
            }}

            QFrame#SettingsPlatformSummaryChip[kind="warning"] {{
                background: rgba(245, 158, 11, 0.10);
                border: 1px solid rgba(245, 158, 11, 0.24);
            }}

            QFrame#SettingsPlatformSummaryChip[kind="accent"] {{
                background: {c["accent_soft"]};
                border: 1px solid {c["border"]};
            }}

            QLabel#SettingsPlatformSummaryLabel {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 600;
            }}

            QLabel#SettingsPlatformSummaryValue {{
                color: {c["text"]};
                font-size: {body_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsPlatformSummaryValue[kind="success"] {{
                color: {c["success"]};
            }}

            QLabel#SettingsPlatformSummaryValue[kind="warning"] {{
                color: {c["warning"]};
            }}

            QLabel#SettingsPlatformSummaryValue[kind="accent"] {{
                color: {c["accent"]};
            }}

            QFrame#SettingsCard {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                border-radius: 14px;
            }}

            QFrame#SettingsCardDivider {{
                background: {c["border"]};
                border: none;
                margin-top: 2px;
                margin-bottom: 8px;
            }}

            QLabel#SettingsCardTitle {{
                color: {c["text"]};
                font-size: {card_title_px}px;
                font-weight: 800;
            }}

            QLabel#SettingsCardIcon {{
                background: transparent;
            }}

            QLabel#SettingsRowLabel {{
                color: {c["muted"]};
                font-size: {body_px}px;
                font-weight: 500;
            }}

            QLabel#SettingsPlatformHeaderCell {{
                color: {c["muted"]};
                font-size: {small_px}px;
                font-weight: 800;
            }}

            QWidget#SettingsPlatformHeader {{
                background: {c["panel_soft"]};
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }}

            QLabel#SettingsPlatformName {{
                color: {c["text"]};
                font-size: {body_px}px;
            }}

            QLabel#SettingsAuthBadge[authenticated="true"] {{
                color: {c["success"]};
                background: rgba(34, 197, 94, 0.14);
                border: 1px solid rgba(34, 197, 94, 0.32);
                border-radius: 14px;
                font-size: {small_px}px;
                font-weight: 800;
                padding: 0px 8px;
            }}

            QLabel#SettingsAuthBadge[authenticated="false"] {{
                color: {c["warning"]};
                background: rgba(245, 158, 11, 0.14);
                border: 1px solid rgba(245, 158, 11, 0.32);
                border-radius: 14px;
                font-size: {small_px}px;
                font-weight: 800;
                padding: 0px 8px;
            }}

            QFrame#SettingsPathField {{
                background: {c["input"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QLineEdit#SettingsLineEdit {{
                background: transparent;
                border: none;
                color: {c["text"]};
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
                font-size: {body_px}px;
                padding: 0px;
            }}

            QLineEdit#SettingsProxyCustomEdit {{
                background: {c["input"]};
                border: 1px solid {c["border_strong"]};
                border-radius: 8px;
                color: {c["text"]};
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
                font-size: {combo_px}px;
                padding: 0px 10px;
            }}

            QLineEdit#SettingsProxyCustomEdit[customProxyActive="true"] {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
            }}

            QLineEdit#SettingsProxyCustomEdit:disabled {{
                color: {c["muted"]};
                background: {c["panel_soft"]};
                border-color: {c["border"]};
            }}

            QToolButton#SettingsPathBrowse {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                padding: 5px;
            }}

            QToolButton#SettingsPathBrowse:hover {{
                background: {c["accent_soft"]};
                border-color: {c["accent"]};
            }}

            QToolButton#SettingsPathBrowse:pressed {{
                background: {c["row_selected"]};
                border-color: {c["accent_hover"]};
            }}

            QToolButton#SettingsInlineButton {{
                background: transparent;
                border: none;
                color: {c["muted"]};
                font-size: {self._scaled_px(14, minimum=12)}px;
                font-weight: 700;
            }}

            QToolButton#SettingsInlineButton:hover {{
                color: {c["accent"]};
            }}

            QComboBox#SettingsCombo {{
                background: {c["input"]};
                border: 1px solid {c["border_strong"]};
                border-radius: 8px;
                color: {c["text"]};
                font-size: {combo_px}px;
                padding: 0px 10px 0px 12px;
                min-height: 36px;
                max-height: 38px;
            }}

            QComboBox#SettingsCombo:hover {{
                border-color: {c["accent"]};
                background: {c["input"]};
            }}

            QFrame#SettingsPathField:hover {{
                border-color: {c["border_strong"]};
            }}

            QFrame#SettingsPathField[focused="true"] {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
            }}

            QComboBox#SettingsCombo:focus {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
            }}

            QComboBox#SettingsCombo:on,
            QComboBox#SettingsCombo[popupOpen="true"],
            QComboBox#SettingsCombo[customProxy="true"] {{
                border-color: {c["accent"]};
                border-width: 2px;
                background: {c["input"]};
                color: {c["text"]};
            }}

            QComboBox#SettingsCombo QLineEdit {{
                background: transparent;
                border: none;
                color: {c["text"]};
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
                padding: 0px 4px 0px 0px;
            }}

            QComboBox#SettingsCombo QLineEdit:read-only {{
                color: {c["text"]};
            }}

            QComboBox#SettingsCombo:disabled {{
                color: {c["muted"]};
                background: {c["panel_soft"]};
            }}

            QComboBox#SettingsCombo::drop-down {{
                border: none;
                width: 0px;
            }}

            QComboBox#SettingsCombo::down-arrow {{
                image: none;
                width: 0px;
                height: 0px;
            }}

            QComboBox#SettingsCombo QAbstractItemView {{
                background: {c["panel"]};
                color: {c["text"]};
                border: 2px solid {c["accent"]};
                border-radius: 8px;
                selection-background-color: {c["accent"]};
                selection-color: #ffffff;
            }}

            QPushButton#SettingsActionButton {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                color: {c["text"]};
                font-size: {small_px}px;
                min-height: 36px;
                max-height: 38px;
                padding: 0px 10px;
            }}

            QPushButton#SettingsActionButton:hover {{
                border-color: {c["accent"]};
                color: {c["accent"]};
            }}

            QWidget#SettingsSegmented {{
                background: {c["panel_soft"]};
                border: 1px solid {c["border"]};
                border-radius: 9px;
            }}

            QPushButton#SettingsSegmentButton {{
                background: transparent;
                border: none;
                color: {c["muted"]};
                font-size: {body_px}px;
                font-weight: 700;
                padding: 0px;
                min-height: 36px;
            }}

            QPushButton#SettingsSegmentButton:checked {{
                background: {c["accent"]};
                color: #ffffff;
                border-radius: 8px;
            }}

            QScrollArea#SettingsPlatformScroll {{
                background: transparent;
                border: none;
            }}

            QScrollArea#SettingsPlatformScroll > QWidget > QWidget {{
                background: transparent;
            }}

            QWidget#SettingsPlatformRow {{
                border-bottom: 1px solid {c["border"]};
                background: {c["panel"]};
            }}

            QWidget#SettingsPlatformRow:hover {{
                background: {c["panel_soft"]};
            }}

            QCheckBox#SettingsUiSwitch {{
                spacing: 0;
                background: transparent;
            }}

            QCheckBox#SettingsUiSwitch::indicator {{
                width: 0px;
                height: 0px;
                border: none;
                background: transparent;
            }}
            """

        if qss == getattr(self, "_last_settings_stylesheet", ""):
            return

        self._applying_style = True
        try:
            self._last_settings_stylesheet = qss
            self.setStyleSheet(qss)
        finally:
            self._applying_style = False
