# 配置中心主题同步与代理契约修复

## 背景

配置中心外观页、平台页同时由 GUI 与 WebUI 使用。用户截图暴露了几个同源问题：顶部主题按钮切换后外观页 Light/Dark 控件不同步；平台默认数量没有区分页数和视频数；MissAV 代理把“预设选择”和“自定义端点输入”混在一个可编辑下拉框里。

## 现象

- 顶部主题按钮只更新全局主题和图标，设置页的 Light/Dark 分段控件仍停留在旧值。
- Bilibili、MissAV、短视频平台共用同一组“作品数”选项，导致页数和视频数语义混淆。
- MissAV 自定义代理会把 URL 写进下拉框文本，后续快照可能出现一个非预设选项。
- WebUI 语言切换只覆盖配置中心局部文案，顶栏、侧栏和状态栏仍保留中文。

## 根因

- `SegmentedControl.set_value()` 会触发普通 toggle 信号，缺少“外部同步但不回写配置”的静默路径。
- `settings_snapshot()` 只输出 `count_config_key/count_options`，没有输出 `count_unit`，前端只能猜测数量单位。
- MissAV 的 `proxy_app` 和 `proxy_url` 没有被拆成两个前端控件，导致选择态和输入态互相污染。
- WebUI 静态文案没有统一经过 `t()`，平台 placeholder 也优先使用了后端中文字符串。

## 修复

- GUI 设置页新增 `sync_external_theme(is_dark)`，顶部主题按钮应用样式后同步外观页分段控件，并通过 signal blocking 避免二次写配置。
- `FrontendStateService.settings_snapshot()` 输出 `count_unit`、平台特定 `count_options`、`proxy_custom_value`、`proxy_custom_active`。
- Bilibili 使用 `max_pages/pages`，MissAV 与短视频平台使用 `max_items/videos`；MissAV `max_items` 加入配置模型，默认数量可选。
- MissAV 代理改为“预设下拉 + 自定义端点输入”。下拉写 `proxy_app`，输入框写规范化后的 `proxy_url`。
- WebUI 顶栏、侧栏、状态栏和配置中心统一走语言映射；主题按钮切换后立即重绘外观页主题 select。

## 验证

- Focused tests: `python -m pytest tests/test_frontend_state_service.py tests/test_unified_frontend_contract.py tests/test_web_browser.py tests/test_main_window.py -q`
- 截图验证：`.codex/verification/gui-theme-segment-synced.png`、`.codex/verification/gui-platform-units-proxy-fixed.png`、`.codex/verification/gui-dark-combo-popup-accent.png`、`.codex/verification/web-global-language-en.png`、`.codex/verification/web-platform-units-proxy-fixed.png`。
