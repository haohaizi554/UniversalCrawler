# GUI 与 WebUI 视觉对齐审查记录

## 本轮截图证据

截图目录：`docx/visual_audit/screenshots/`

最新总览图：`docx/visual_audit/screenshots/gui_web_contact_sheet.png`

本轮追加截图：

- `gui_queue.png` / `web_queue.png`：下载队列同一份 mock 状态对比。
- `gui_active.png` / `web_active.png`：正在下载页同一份 mock 状态对比。
- `gui_failed.png` / `web_failed.png`：失败列表同一份 mock 状态对比。

- `gui_logs.png` / `web_logs.png`：日志中心同一份 mock 状态对比。
- `gui_completed.png` / `web_completed.png`：已完成页同一份 mock 状态对比。
- `gui_settings.png` / `web_settings.png`：配置中心基础设置对比。
- `gui_toolbox.png` / `web_toolbox.png`：工具箱对比。

说明：GUI 离屏渲染无法加载系统字体，最初截图会出现中文方块。本轮已改用 Qt 正常 Windows 平台渲染控件自身截图；WebUI 使用 Playwright，并注入同一份 `FrontendStateService.mock_snapshot()`，避免 GUI/Web 数据状态不一致导致误判。

## 已确认并修复的问题

1. 已完成页右侧详情栏默认过宽。
   - 现象：WebUI 在 1270px 视口下右栏约 520px，左表格被压到约 481px，标题列明显比 GUI 更早截断。
   - 修复：完成页右栏改为 `minmax(400px, clamp(400px, 28vw, 620px))`，窄桌面优先保留左表格可读宽度，宽屏继续自然扩展。

2. 已完成页媒体播放按钮在有选中项时仍被禁用。
   - 现象：WebUI 自定义播放条存在，但首次进入完成页时播放按钮 disabled，用户无法像 GUI 一样从当前选中项启动播放。
   - 修复：`renderCompleted()` 末尾同步调用 `updateMediaControls()`；`updateMediaControls()` 允许 `currentPlayingId / selected.completed / selectedVideoId` 任一存在时启用播放按钮。

3. 已完成页媒体控制条横向溢出。
   - 现象：右栏收窄后，全屏按钮被裁切。
   - 修复：保持 GUI 同款 50px 控制条高度和 32x32 控制按钮，横向间距收敛到 10px，进度条和时间文本允许在 400px 右栏内自适应。

4. 日志中心筛选区桌面端换行。
   - 现象：WebUI 在同宽截图下将五个筛选项折成两行，GUI 为一行五项。
   - 修复：桌面端 `#page-logs .log-filters` 改为五列网格；小屏仍保留 `auto-fit` 兜底。

5. 工具箱右侧动作按钮位置不一致。
   - 现象：GUI 的“打开工具”按钮位于右侧详情面板底部，WebUI 按钮跟随详情内容流动，停在中部。
   - 修复：`#toolDetail` 增加 `toolbox-detail` 专用布局，右侧面板改为纵向 flex；最近使用区限制高度，详情区内容顶部对齐，“打开工具”按钮用 `margin-top: auto` 固定到底部内边距处。
6. 日志中心标签、详情空态和分页细节与 GUI 不一致。
   - 现象：WebUI 使用下划线标签，空态只显示一个“暂无日志”小卡片；窄视口下页码被挤成竖排。
   - 修复：日志分类改为 92x34 的连体按钮式标签；筛选区恢复边框卡片；右侧详情栏始终保留“日志详情 + 详细信息”两段结构；底部分页增加 `white-space: nowrap` 和可收缩统计区。
7. 配置中心基础设置仍是表单列表，不像 GUI 的行级卡片。
   - 现象：WebUI 设置项缺少标题/短说明层级、行卡片边界、主题色开关和底部提示卡；“绑定默认打开方式”按钮单独占一行。
   - 修复：`settings_render.js` 输出统一的 `setting-label` 与 `setting-control-cluster`；基础设置改为行级卡片，自绘主题色开关；“默认打开方式”选择与“绑定默认打开方式”按钮同排；后端 `settings_contract` 增加 `group_hints`，WebUI 用同源提示卡渲染。
8. 任务选择弹窗按钮尺寸与首列宽度细节对齐。
   - 现象：直接套 GUI 48px 首列会因 Web 的 border-box/padding 模型截断“选择”表头。
   - 修复：首列保留 Web 可读的 58px；批量按钮收紧到 80x30，主按钮收紧到 100/120x35，并用截图确认没有截断。
9. 失败列表 GUI 右侧详情偶发文字重影。
   - 现象：连续 render 或截图时，右侧“错误详情 / Trace / 解决方案”会出现旧控件与新控件叠在一起。
   - 原因：旧详情控件只调用 `deleteLater()`，在下一轮事件处理前仍保留在父容器中，快速重绘时可见。
   - 修复：清理布局时先 `setParent(None)` 让旧控件立即脱离界面，再 `deleteLater()` 异步销毁；同时将失败详情右栏最小宽度提高到 420px，并为详情值、日志消息、解决方案文本补齐 `minimumWidth=0` 和可换行策略。
10. 正在下载 WebUI 底部控制区被通用 `.controls-panel` 规则覆盖。
   - 现象：WebUI 的“队列控制”标题和控件行更像横向居中面板，不像 GUI 的 96px“标题 + 一行控件”结构。
   - 原因：后置通用 `.controls-panel` 规则覆盖了 `.active-controls` 的纵向结构。
   - 修复：增加 `#page-active .controls-panel.active-controls` 页级规则，固定 96px 高度、纵向布局、左对齐标题，并让“当前运行”统计靠右。

## 本轮验证

- `node --check app/web/static/app.js`
- `node --check app/web/static/settings_render.js`
- `node --check app/web/static/i18n.js`
- `python -m pytest tests/test_frontend_state_service.py -q`
- `python -m pytest tests/test_unified_frontend_contract.py -q`
- `python -m pytest tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_completed_page_uses_three_cards_short_time_and_media_fullscreen -q`
- `python -m pytest tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_log_center_matches_gui_tabs_actions_and_filters -q`
- `python -m pytest tests/test_web_browser.py::StaticAssetsTests::test_completed_preview_controls_are_visible_not_compat_hidden -q`
- `python -m pytest tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_basic_settings_use_backend_options_and_update_action -q`

## 后续仍需逐页细查

- 配置中心：逐组检查控件行高、右侧输入框宽度、开关和按钮位置。
- 工具箱：检查工具卡尺寸、右侧最近使用和详情区高度。
- 弹窗：任务选择、目录选择、默认打开方式绑定，需要补截图和键盘路径验证。
- 深浅主题与主题色：逐页检查自定义选择框、表格选中态、详情卡片和滚动条。
- 全量测试：最终收口前必须执行完整 `python -m pytest -q`。
