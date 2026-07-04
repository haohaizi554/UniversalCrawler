# WebUI 刷新态下的选中语义与日志详情动作

## 背景

GUI 的表格和工具卡片由 Qt 控件维护当前选中项。数据刷新、删除或分页后，如果原选中项已经不存在，GUI 会自然落到当前可见的第一项，并让右侧详情同步展示这一项。

WebUI 之前只在 `selected.*` 为空时才默认选择第一项。如果 `selected.active`、`selected.completed`、`selected.failed` 或 `selected.tool` 指向已经不存在的 id，表格可能没有高亮行，详情区却显示全局第一条或空详情，形成“幽灵选中态”。

## 修复原则

1. 渲染列表前先校验当前 selected id 是否仍存在于当前可见数据。
2. 已完成页有分页时，失效选中态落到当前页第一条，而不是全局第一条。
3. 详情区只读取有效选中项；没有有效项时显示空态。
4. 删除事件继续由 `removeDeletedFromFrontendState()` 清理显式删除态；普通快照刷新由 `reconcileSelectedTask()` 在渲染层兜底。

## 日志详情动作

GUI 日志中心右侧 Inspector 有三个独立动作：

- 详情头“复制”：复制完整日志详情负载。
- 详情头“导出”：保存日志详情 JSON。
- JSON 卡片“复制”：只复制 detail JSON。

WebUI 不能用顶部“复制 TraceID / 导出日志”替代这些动作，因为它们的对象和粒度不同。当前 WebUI 已补齐：

- `copyCurrentLogDetail()`
- `copyCurrentLogJson()`
- `exportCurrentLogDetail()`

## 失败页动作与模拟态

失败列表的可见动作已经收敛为“复制 Trace ID”和“删除”。真实快照由 `frontend_video_adapter` 输出 `["copy_diagnostics", "delete"]`，GUI 表格和 WebUI 表格也都只绘制这两个动作。

模拟快照同样属于用户可见体验：WebUI 初始 mock、开发预览和部分契约测试都会消费它。如果 mock 里继续保留 `retry`，即使真实运行页不显示重试，也会让后续维护误以为失败页仍有可见重试入口。因此 `frontend_mock_snapshot.py` 和 WebUI `buildMockState()` 也必须同步移除失败项里的 `retry` 动作。

## 默认打开方式弹窗

GUI 点击“绑定默认打开方式”时不会直接执行系统注册，而是先打开确认弹窗，让用户选择视频资源、图片资源或两者都选。WebUI 如果从设置按钮直接发送固定参数，会造成两类问题：

1. 用户看不到即将影响哪些资源类型。
2. WebUI 与 GUI 的真实交互路径不同，后续键盘确认、取消和主题样式都会失去统一合同。

当前 WebUI 已补齐 `fileAssociationModal`：

- 默认勾选视频资源和图片资源。
- Enter 触发绑定，Escape 取消。
- 复选框、主按钮、说明文字跟随主题色、深浅主题和语言切换。
- 确认后才调用 `register_file_associations`，并按当前勾选态传递 `include_video/include_image`。

生效语义沿用后端服务边界：注册成功后会影响之后的系统打开行为；若 Windows 拦截默认应用写入，程序会打开系统默认应用设置页，用户需要在系统侧完成确认。

## 平台选择器图标

GUI 的平台选择框由 `PlatformSourceCombo` 渲染，每个选项带平台图标。WebUI 不能只显示文字，否则侧栏第一眼识别能力和 GUI 不一致。

当前 WebUI 的处理方式：

- `renderPlatforms()` 从 `icon_manifest.platforms` 读取平台图标文件。
- 原生 `option` 通过 `data-icon` 保存图标 URL。
- 自定义选择器在按钮和菜单项中统一渲染 `.custom-select-icon` 与 `.custom-select-label`。
- 图标仍走 `/ui-icon` 路由，不在 CSS 中硬编码平台资源。

## 下载队列状态列

GUI 下载队列的 `SnapshotActionTable` 将 `platform` 和 `status` 都声明为 `icon_columns`。平台列显示平台图标，状态列通过 `queue_status_icon_file(status)` 显示状态图标。

WebUI 原先用 `.status-pill` 小圆点胶囊表达状态，虽然醒目，但和 GUI 的图标文本列不一致。当前修正为：

- `icon_manifest` 暴露 `queue_status` 映射。
- `queueStatusHtml()` 优先使用 `icon_manifest.queue_status[label]`。
- 无精确状态映射时，再按成功、失败、运行、待处理语义回退到通用状态图标。
- 删除 `.status-pill` 死样式，避免后续误用。

## 表格密度与操作列

GUI 的 `SnapshotActionTable` 不是“表格统一一个操作列宽”，而是按页面列模型和动作数量计算：

- 队列页：平台 96、状态 112、操作 44，行高 52。
- 正在下载页：平台 82、进度 118、速度 92、剩余时间 100、操作 72，数据行高 74。
- 已完成页：完成时间 142、时长 108、格式 76、操作 100，行高 56。
- 失败页：失败时间 112、失败原因 150、状态 82、操作 72，行高 56。
- 日志页：行高 32，底部分页栏高 48。

WebUI 必须按页面级 CSS 固定这些宽度，操作单元格去掉左右 padding；操作图标使用 24x28 的透明点击区，内部 18px 图标。不要再给操作图标套普通按钮框，否则选中行里会出现二层控件感。

## 状态栏指标布局

本轮发现一个静默布局 bug：`.status-metric:first-of-type` 并不会命中第一组指标，因为状态栏前面已经有 `statusIndicator` 和 `statusState` 两个 `span`。这种伪类写法不会报错，但会导致 GUI 式左右弹性分布失效。

修复原则：

- 第一组指标显式加 `.status-metric-main`。
- 由 `.status-metric-main { margin-left: auto; }` 负责把指标区推向中部。
- 版本号继续 `margin-left: auto`，对应 GUI 状态栏中指标区两侧的 stretch。
- 状态栏标题和值分离，标题跟随语言切换，数值刷新不重绘整句。

## 启动按钮运行态

GUI 的 `StartTaskButton` 在任务运行中不是普通灰色禁用按钮，而是保持主题色并显示运行反馈。WebUI 也必须保持同一语义：

- `setCrawlUiState(true)` 给 `startBtn` 添加 `.is-running` 与 `aria-busy="true"`。
- `.btn-primary.is-running:disabled` 覆盖普通 disabled 透明度，保持主题色。
- 使用轻量 `start-button-sweep` 动画表达运行中，不重建顶栏。

## 页面右侧详情栏宽度

GUI 每个页面的右侧详情栏宽度范围不同，WebUI 不能共用一个 `--detail-width` 默认值直接套所有页面：

- 正在下载：360-500px。
- 已完成：430-620px。
- 失败列表：380-520px。
- 日志中心：400-460px。

WebUI 仍可复用 `--detail-width` 记忆用户拖动宽度，但页面级 CSS 必须用 `clamp()` 限制在对应 GUI 范围内。

## 工具箱预览态图标

真实前端快照通过 `frontend_toolbox_adapter.toolbox_items()` 给每个工具补充独立 `icon_file`。WebUI 的本地 mock 也会在服务端状态返回前短暂参与首屏渲染，因此 mock 不能全靠 `nav_toolbox.png` 兜底。

当前 WebUI mock 已按真实适配器补齐：

- 链接解析：`tool_link_parser.png`
- 批量重命名：`tool_batch_rename.png`
- 封面提取：`tool_cover_extract.png`
- 视频转音频：`tool_video_to_audio.png`
- 本地去重扫描：`tool_duplicate_scan.png`
- 元数据查看：`tool_metadata_view.png`
- 格式转换：`tool_format_convert.png`
- 文件校验：`tool_file_verify.png`

## 验证

- `tests/test_web_browser.py::WebUIBrowserTests::test_11c_file_association_modal_esc_and_enter_match_gui`
- `tests/test_web_browser.py::WebUIBrowserTests::test_06b_source_select_uses_platform_icons_like_gui`
- `tests/test_web_browser.py::WebUIBrowserTests::test_11f_stale_selection_reconciles_to_visible_first_row`
- `tests/test_web_browser.py::WebUIBrowserTests::test_13c_log_detail_copy_export_actions_match_gui`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_file_association_modal_matches_gui_confirmation_interaction`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_log_center_matches_gui_tabs_actions_and_filters`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_queue_page_matches_gui_toolbar_and_status_icons`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_basic_settings_use_backend_options_and_update_action`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_failed_page_uses_split_cards_without_retry`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_failed_page_uses_cards_and_removes_retry`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_shell_matches_gui_island_structure`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_active_controls_and_detail_values_are_wrap_ready`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_completed_page_uses_three_cards_short_time_and_media_fullscreen`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_rendering_uses_stable_dom_update_guards`
