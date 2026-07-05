from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget

from app.ui.viewmodels.settings_catalog import PLATFORM_COUNT_OPTIONS, PROXY_OPTIONS, TIMEOUT_OPTIONS
from app.ui.viewmodels.settings_options import (
    compact_proxy_options,
    current_combo_value,
    normalize_combo_options,
    proxy_endpoint_from_port,
    proxy_port_text,
)
from app.ui.viewmodels.settings_platform_layout import PLATFORM_DETAIL_COL_WIDTHS


BuildCombo = Callable[[list[Any], Any], QComboBox]
Translate = Callable[[str], str]
ScaledPx = Callable[..., int]
EmitSetting = Callable[[str, str, Any], None]


def build_platform_count_combo(
    row: Mapping[str, Any],
    *,
    build_combo: BuildCombo,
    emit_setting_changed: EmitSetting,
    translate: Translate,
    width: int | None = None,
) -> QComboBox:
    platform_id = str(row.get("id") or "")
    config_key = str(row.get("count_config_key") or "")
    combo = build_combo(
        list(row.get("count_options") or PLATFORM_COUNT_OPTIONS),
        str(row.get("default_count") or 20),
        width=int(width or PLATFORM_DETAIL_COL_WIDTHS["count"]),
    )
    combo.setEnabled(bool(row.get("count_editable", True) and platform_id and config_key))
    if combo.isEnabled():
        combo.currentIndexChanged.connect(
            lambda *_args, control=combo, pid=platform_id, key=config_key: emit_setting_changed(
                pid,
                key,
                int(current_combo_value(control)),
            )
        )
    else:
        combo.setToolTip(translate("该平台暂无可热加载的爬取数量配置"))
    return combo


def build_platform_timeout_combo(
    row: Mapping[str, Any],
    *,
    build_combo: BuildCombo,
    emit_setting_changed: EmitSetting,
    translate: Translate,
    width: int | None = None,
) -> QComboBox:
    platform_id = str(row.get("id") or "")
    config_key = str(row.get("timeout_config_key") or "")
    combo = build_combo(
        list(row.get("timeout_options") or TIMEOUT_OPTIONS),
        str(row.get("default_timeout") or row.get("timeout") or 60),
        width=int(width or PLATFORM_DETAIL_COL_WIDTHS["timeout"]),
    )
    combo.setEnabled(bool(row.get("timeout_editable", False) and platform_id and config_key))
    if combo.isEnabled():
        combo.currentIndexChanged.connect(
            lambda *_args, control=combo, pid=platform_id, key=config_key: emit_setting_changed(
                pid,
                key,
                int(current_combo_value(control)),
            )
        )
    else:
        combo.setToolTip(translate("该平台暂无可热加载的超时配置"))
    return combo


def build_platform_proxy_widget(
    row: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    build_combo: BuildCombo,
    emit_proxy_setting_changed: Callable[[str, str, str], None],
    translate: Translate,
    scaled_px: ScaledPx,
    row_container: QWidget | None = None,
    width: int | None = None,
) -> QWidget:
    platform_id = str(row.get("id") or "")
    config_key = str(row.get("proxy_config_key") or "")
    editable = bool(row.get("proxy_editable", policy.get("editable")) and platform_id and config_key)
    proxy_value = str(row.get("proxy") or "系统代理")
    options = compact_proxy_options(list(row.get("proxy_options") or PROXY_OPTIONS), proxy_value)
    option_values = {value for value, _label in normalize_combo_options(options, proxy_value)}
    if editable and proxy_value not in option_values:
        proxy_value = "自定义"
    if not editable:
        proxy_value = "系统代理"

    custom_allowed = bool(row.get("proxy_custom_allowed"))
    proxy_width = int(width or PLATFORM_DETAIL_COL_WIDTHS["proxy"])
    active_container_width = max(proxy_width, 190) if custom_allowed else proxy_width
    collapsed_combo_width = proxy_width
    active_combo_width = max(72, min(206, int(active_container_width * 0.48))) if custom_allowed else proxy_width
    active_input_min_width = max(86, active_container_width - active_combo_width - 8) if custom_allowed else 0
    proxy_combo = build_combo(options, proxy_value, width=collapsed_combo_width)
    proxy_combo.setEnabled(editable)
    proxy_combo.setProperty("proxyCustomAllowed", "true" if custom_allowed else "false")
    proxy_combo.setEditable(False)

    if not custom_allowed:
        if policy.get("tooltip"):
            proxy_combo.setToolTip(str(policy["tooltip"]))
        return proxy_combo

    control_height = scaled_px(40, minimum=40)

    container = QWidget()
    container.setObjectName("SettingsProxyControl")
    container.setFixedWidth(proxy_width)
    container.setFixedHeight(control_height)
    container_layout = QHBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(8)

    line_edit = QLineEdit()
    line_edit.setObjectName("SettingsProxyCustomEdit")
    line_edit.setFixedHeight(control_height)
    line_edit.setMinimumWidth(active_input_min_width or 92)
    line_edit.setPlaceholderText(translate("端口"))
    line_edit.setClearButtonEnabled(False)
    line_edit.setEnabled(False)
    existing_custom = str(row.get("proxy_custom_value") or "").strip()
    if existing_custom:
        line_edit.setText(proxy_port_text(existing_custom))
    elif proxy_value not in {"系统代理", "直连", "自定义"}:
        line_edit.setText(proxy_port_text(proxy_value))

    container_layout.addWidget(proxy_combo, 0)
    container_layout.addWidget(line_edit, 1)
    proxy_combo.setFixedHeight(control_height)

    def sync_custom_state(active: bool, *, focus: bool = False) -> None:
        proxy_combo.setProperty("customProxy", "true" if active else "false")
        container.setFixedWidth(active_container_width if active else proxy_width)
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
        if row_container is not None:
            row_container.updateGeometry()
        proxy_combo.style().unpolish(proxy_combo)
        proxy_combo.style().polish(proxy_combo)
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)

    custom_active = bool(editable and (row.get("proxy_custom_active") or proxy_value == "自定义"))
    if custom_active:
        custom_index = proxy_combo.findData("自定义")
        if custom_index < 0:
            custom_index = proxy_combo.findText(translate("自定义 HTTP/SOCKS5 端点"))
        if custom_index >= 0:
            proxy_combo.setCurrentIndex(custom_index)
        proxy_combo.setToolTip(existing_custom or translate("端口"))
    sync_custom_state(custom_active)

    if editable:
        def on_proxy_changed(*_args, control=proxy_combo, pid=platform_id, key=config_key) -> None:
            value = current_combo_value(control)
            is_custom = value == "自定义"
            sync_custom_state(is_custom, focus=is_custom)
            emit_proxy_setting_changed(pid, key, value)

        proxy_combo.currentIndexChanged.connect(on_proxy_changed)

        def commit_custom_proxy(edit=line_edit, control=proxy_combo, pid=platform_id, key=config_key) -> None:
            if control.property("customProxy") != "true":
                return
            value = edit.text().strip()
            if not value or value in {"自定义", translate("自定义 HTTP/SOCKS5 端点")}:
                return
            emit_proxy_setting_changed(pid, key, "自定义")
            emit_proxy_setting_changed(pid, "proxy_url", proxy_endpoint_from_port(value))

        line_edit.editingFinished.connect(commit_custom_proxy)
    elif policy.get("tooltip"):
        container.setToolTip(str(policy["tooltip"]))
        line_edit.setToolTip(str(policy["tooltip"]))
    return container
