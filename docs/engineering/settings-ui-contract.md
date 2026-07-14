# 设置、下拉框与国际化契约

本文是 GUI 配置中心、WebUI 设置页、下拉框弹层和语言目录的当前工程契约。历史修复记录只解释问题来源；新增设置或改控件时，以本文为准。

## 范围

GUI 配置中心和 WebUI 设置页必须消费同一份 `FrontendStateService.settings_snapshot()` 契约。设置控件的选项、默认值、当前值、禁用状态和热加载行为都应来自后端快照；可见文字通过共享语言目录解析。

## 下拉框契约

- GUI 下拉框统一使用 `app.ui.components.combo_popup.polish_combo_popup()` 或 `ThemedComboBox`。
- 短列表应完整展开，不出现横向或纵向滚动条；内部纵向滚动范围应保持为零。
- 弹出视图必须使用主题化无边框视图和 `NoFocusItemDelegate`，原生焦点框、白色弹层和右侧箭头留白都属于回归。
- 调用方传入弹层行高或可见行数时，应把这些值保存到 combo 实例上，避免 `showPopup()` 回退到默认几何。
- 设置页下拉框可以保留页面自己的外层样式，但弹层行为必须集中在统一组件里。
- 日志中心、正在下载、已完成、下载队列、插件设置、平台侧栏和顶部数量控件都应被统一前端契约测试覆盖。

### 窄列下拉框

平台设置里的页数、笔记数、视频数、超时和代理入口都属于窄列控件。它们不能依赖 Qt 原生箭头保留区，否则会出现右侧空白或文字截断。

- 控件宽度按最长 label 预算，例如“60 秒（推荐）”。
- `value` 和 `label` 分离；“推荐”只出现在 label，不写入后端值。
- 页面级 QSS 不应重新引入 `QComboBox::drop-down` 宽度。
- 表格列宽计算必须扣除外边距和列间距。

### 平台代理自定义输入

代理入口的正常态是一个下拉框；只有选择“自定义”时，才在同一个代理单元格里拆成两个独立框：左侧代理模式下拉框，右侧端口输入框。这里不是单外框复合输入，也不能把右侧输入框当成额外表格列。

- 拆分态必须由 `SettingsProxyControl` 统一预算：`左框宽度 + 间距 + 右框宽度 == 代理列宽度`。
- 有自定义代理能力的平台表格，紧凑宽度下也要优先保留代理列宽，不能把代理列压到只能显示半个输入框。
- 折叠态必须隐藏并禁用右侧输入框，左侧下拉框回到整列宽度。
- QSS 不要用 `min-height` / `max-height` 重新撑大 `SettingsProxyCustomEdit`；高度以控件固定高度为准，否则 2px 焦点边框会造成视觉截断。
- 回归测试必须同时覆盖默认行数和滚动行数，避免只在宽面板里通过。

## 外观更新契约

- 切换语言时，应立即重译外壳和当前可见页面；隐藏页面可标记为待刷新。
- 同语言设置刷新不应重译所有页面，也不应重建顶部数量控件。
- 主题、字体和缩放更新应批量处理顶层重绘，避免页面白屏式闪烁。
- 受管理的 `ThemedComboBox` 在主题变化后必须刷新内联控件样式，否则深色主题页面可能残留浅色下拉框。
- GUI 与 WebUI 的主题和强调色必须与外观设置保持同步。

## 语言目录契约

- 源语言为 `zh-CN`。
- 派生语言目录位于 `app/ui/i18n/en-US.json` 和 `app/ui/i18n/zh-TW.json`。
- GUI 与 WebUI 的 Python 投影统一通过 `shared.localization.tr()` 翻译；表示层不得保留同名转发模块。
- WebUI 首屏可以保留本地兜底词典，但启动后必须通过 `/api/i18n/{language}` 加载共享语言目录并覆盖兜底值。
- `app.web.server.create_app()` 和 `app.web.rest_router.build_rest_router()` 都必须暴露 `/api/i18n/{language}`。

## 回归命令

```bash
python -m pytest tests/test_unified_frontend_contract.py -q
python -m pytest tests/test_fastapi_endpoints.py::StateEndpointTests::test_i18n_catalog_endpoint_serves_shared_language_files tests/test_fastapi_endpoints.py::StateEndpointTests::test_i18n_catalog_endpoint_returns_empty_for_source_language -q
node --check app/web/static/app.js
```

## 相关复盘

- [配置中心下拉框右侧空白复盘](../postmortems/settings-combo-native-arrow-gutter.md)
