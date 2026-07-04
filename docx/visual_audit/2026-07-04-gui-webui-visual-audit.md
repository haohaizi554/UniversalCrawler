# GUI 与 WebUI 视觉对齐审查记录

## 截图证据

截图目录：`docx/visual_audit/screenshots/`

核心联系表：
- `gui_web_contact_sheet.png`：队列、下载中、已完成、失败列表、日志中心、配置中心、弹窗的 GUI / WebUI 对比。
- `settings_subpages_contact_sheet.png`：配置中心 6 个子页的 GUI / WebUI 对比。

本轮重点截图：
- `web_settings_platform.png`：平台设置页，覆盖认证状态、爬取数量、超时、代理入口和自定义端口。
- `web_settings_download_dropdown.png`：下载设置页底部下拉框展开状态。
- `web_logs.png`：日志中心表格列宽、详情摘要和详细信息展示。

## 本轮已修复

1. 平台设置页横向溢出
   - 问题：WebUI 为自定义代理端口临时拆出第 6 列，当前面板宽度下会挤掉平台名或让输入框越界。
   - 修复：代理入口改为一个复合单元格，内部同时容纳“代理选择 + 端口输入”，不再增加表格列数。
   - 证据：`web_settings_platform.png` 中平台名、认证状态、爬取数量、超时、代理入口均保持在面板内。

2. 平台认证状态误呈现为禁用选择框
   - 问题：认证状态不可编辑，但 WebUI 之前用 disabled select 展示，视觉和语义都不像 GUI。
   - 修复：改为状态徽标，已认证为绿色，未认证为橙色，跟随主题变量。
   - 证据：`web_settings_platform.png` 中认证状态与 GUI 的状态徽标语义一致。

3. 平台名缺少平台图标
   - 问题：GUI 平台列有平台图标，WebUI 只有文字。
   - 修复：WebUI 平台设置行复用 `iconManifest.platforms`，通过 `/ui-icon/` 路由加载同一套平台图标。
   - 证据：`web_settings_platform.png` 中抖音、小红书、快手、MissAV、Bilibili 均显示图标。

4. 下拉框靠近底部时被滚动容器裁切
   - 问题：自定义下拉菜单一直作为行内绝对定位元素展开，遇到底部空间不足会被设置面板滚动容器裁掉或压到提示卡。
   - 修复：自定义下拉菜单改为视口浮层定位，打开时按视口空间自动选择向上或向下，并实时设置 left/top/width/max-height。
   - 证据：`web_settings_download_dropdown.png` 中“速度限制”下拉框向上展开，未被底部提示卡或滚动容器裁切。

5. 日志中心“级别 / 来源”列宽不协调
   - 问题：来源列过窄时会把“系统 · WebUI”等内容截得过早，级别列和来源列的视觉比例不接近 GUI。
   - 修复：重新分配日志表前四列宽度，并让来源单元格图标、文本同排省略。
   - 证据：`web_logs.png` 中级别徽标、来源图标与文本保持稳定宽度。

6. 日志详情原始信息可读性差
   - 问题：详情 JSON 中的 `\n` 和超长分隔线直接显示在窄框内，形成断裂文本。
   - 修复：复制/导出仍保留原始 JSON；屏幕展示改为可读文本，转义换行显示为真实换行，超长分隔线压缩为短分隔线。
   - 证据：`web_logs.png` 的“详细信息”区域已按多行文本展示。

7. 任务清单确认弹窗内容区与 GUI 不一致
   - 问题：WebUI 将“任务清单确认”作为内容区可见标题展示，而 GUI 中该文字属于窗口标题；同时 WebUI 表格行高、复选框和底部按钮偏小。
   - 修复：WebUI 保留 `selectionTitle` 作为屏幕阅读器标题，但用 `sr-only` 从视觉内容区移除；表格行高、复选框和按钮尺寸调整到 GUI 同级。
   - 证据：`web_modal_selection.png` 与 `gui_web_contact_sheet.png` 中任务清单确认弹窗已从“扫描到资源”提示开始，表格与底部操作区尺寸更接近 GUI。

8. 默认打开方式弹窗密度与 GUI 不一致
   - 问题：WebUI 状态说明只是普通段落，按钮和选项行偏薄，初始聚焦时主按钮还会出现与 GUI 不一致的描边。
   - 修复：WebUI 关联弹窗改用更接近 GUI `DialogStatus` 的状态卡；标题、说明、选项行、复选框和底部按钮按 GUI 截图比例加厚；弹窗操作按钮移除初始聚焦描边。
   - 证据：`web_modal_association.png` 与 `gui_web_contact_sheet.png` 中默认打开方式弹窗的状态卡、按钮厚度和整体密度已接近 GUI。

9. 下载设置项顺序与 GUI 不一致
   - 问题：GUI 中“断点续传”位于“下载速度限制（KB/s）”之前；WebUI 之前反过来展示，破坏配置中心子页的逐控件顺序一致性。
   - 修复：WebUI 下载设置渲染顺序改为 `最大重试 -> 断点续传 -> 下载速度限制 -> 仅下载视频`，与 GUI 构建顺序一致。
   - 证据：`web_settings_download.png` 与 `settings_subpages_contact_sheet.png` 中下载设置页顺序已对齐。

10. 基础设置“默认打开方式”动作按钮可见文案过短
    - 问题：GUI 按钮使用完整“绑定默认打开方式”文案并由控件宽度自然裁切；WebUI 之前只显示“绑定”，语义与 GUI 不一致。
    - 修复：WebUI 保留完整可见文案，继续用现有窄按钮宽度和 `text-overflow` 控制裁切，避免挤压默认打开方式选择框。
    - 证据：`web_settings_basic.png` 与 `settings_subpages_contact_sheet.png` 中基础设置页已显示与 GUI 同类的裁切动作文案。

11. 基础设置“下载目录”缺少 GUI 同位文件夹选择按钮
    - 问题：GUI 下载目录输入框右侧有文件夹按钮；WebUI 之前只能编辑路径或使用顶部“更改目录”，同一设置行缺少对应交互入口。
    - 修复：WebUI 下载目录行新增图标按钮，复用现有 `showDirDialog()` 目录选择器，并保留路径输入框宽度与省略显示。
    - 证据：`web_settings_basic.png` 与 `settings_subpages_contact_sheet.png` 中基础设置页已出现同位文件夹按钮，`test_11l_download_directory_browse_button_opens_dir_dialog` 覆盖真实点击。

12. 外观设置主题控件仍是下拉框
    - 问题：GUI 使用“浅色 / 深色”分段控件，点击主题会立即关闭“跟随系统”；WebUI 之前是主题下拉框，且没有同步关闭 `follow_system`。
    - 修复：WebUI 外观页新增 `setting-theme-segment` 分段控件，选中态使用当前主题色；点击浅色/深色复用 `common/theme` 更新链路，并即时把 `follow_system` 置为 `false`。
    - 证据：`web_settings_appearance.png` 与 `settings_subpages_contact_sheet.png` 中外观设置页已改为分段按钮，`test_07b_appearance_theme_segment_disables_follow_system` 覆盖真实点击。

13. 播放设置标签与 GUI 文案不一致
    - 问题：GUI 使用“记住播放进度”“视频播放完自动下一项”“图片只手动切换”；WebUI 之前分别显示为“记住播放位置”“自动播放下一项”“手动切换图片”。
    - 修复：WebUI 播放设置标签与短说明映射改为 GUI 同名文案，并补充英文/繁中文案兜底。
    - 证据：`web_settings_playback.png` 与 `settings_subpages_contact_sheet.png` 中播放设置页文案已对齐，`test_11m_playback_setting_labels_match_gui` 覆盖真实渲染。

14. 下载设置标签与 GUI 文案不一致
    - 问题：GUI 使用“重试次数”“下载速度限制（KB/s）”；WebUI 之前显示为“最大重试”“速度限制 KB/s”。
    - 修复：WebUI 下载设置标签与短说明映射改为 GUI 同名文案，并补充英文/繁中文案兜底。
    - 证据：`web_settings_download.png` 与 `settings_subpages_contact_sheet.png` 中下载设置页文案已对齐，`test_11ka_download_setting_labels_match_gui` 覆盖真实渲染。

15. 日志设置标签与 GUI 文案不一致
    - 问题：GUI 使用“日志保留天数”“UI日志最大显示数量”；WebUI 之前显示为“保留天数”“UI最大显示数”。
    - 修复：WebUI 日志设置标签与短说明映射改为 GUI 同名文案，并补充英文/繁中文案兜底。
    - 证据：`web_settings_logs.png` 与 `settings_subpages_contact_sheet.png` 中日志设置页文案已对齐，`test_11kb_log_setting_labels_match_gui` 覆盖真实渲染。
16. 配置中心普通设置页卡片切割与 GUI 不一致
    - 问题：GUI 的普通设置页结构是“右侧详情面板 -> 58px 标题头 -> 浅底表单卡片 -> 60px 设置行 -> 40px 提示条”；WebUI 之前仍使用固定 594px 卡宽、较高设置行和较厚提示条，普通设置页与平台设置页的卡片边界也容易混淆。
    - 修复：WebUI 普通设置页按 GUI 的 82% 内容卡宽公式、10px 表单内距、7px 行间距、60px 行高、9px 行圆角和 40px 提示条重切；下载目录、命名规则和默认打开方式行抽出 `setting-wide-control` 长控件结构；平台设置页显式保持满宽表格，不继承普通卡宽。
    - 证据：`settings_subpages_contact_sheet.png` 已重新截图对比普通设置页与平台设置页，`test_11ha_settings_card_slicing_matches_gui` 覆盖真实浏览器几何尺寸。
17. 全部设置项前后端接口复查
    - 范围：基础设置、下载设置、平台设置、播放设置、日志设置、外观设置，以及平台行内的 `count_config_key`、`timeout_config_key`、MissAV `proxy_app/proxy_url` 复合代理入口。
    - 结论：本轮未发现 GUI 或 WebUI 存在“控件已渲染但后端不识别”的断链；普通设置经 `update_basic_setting`，其余设置经 `update_setting`，主题项从 `appearance/theme` 兼容映射到 `common/theme`，平台设置按 snapshot 行契约动态回写。
    - 证据：新增 `test_all_settings_controls_round_trip_through_backend_contract` 逐项写入后端、读取 snapshot 并重载配置文件；新增 `test_11hb_settings_controls_expose_backend_setting_keys` 校验 WebUI 每个设置页真实 DOM 暴露的 `data-setting` key 覆盖后端契约。

## 回归验证

已通过：
- `node --check app/web/static/app.js`
- `node --check app/web/static/settings_render.js`
- `node --check app/web/static/custom_select.js`
- `python -m pytest tests/test_unified_frontend_contract.py -q`：104 passed
- `python -m pytest tests/test_web_browser.py -q`：89 passed
- `python -m pytest tests/test_frontend_state_service.py -q`：75 passed
- `python -m pytest -q`：1834 passed, 1 skipped, 5 warnings
- `git diff --check`：仅提示既有 CRLF/LF 换行提醒，无空白错误

新增/强化的关键用例：
- `test_11h_platform_custom_proxy_stays_inside_settings_panel`
- `test_11ha_settings_card_slicing_matches_gui`
- `test_11hb_settings_controls_expose_backend_setting_keys`
- `test_all_settings_controls_round_trip_through_backend_contract`
- `test_11j_settings_select_opens_up_near_panel_bottom`
- `test_11k_download_settings_order_matches_gui`
- `test_11ka_download_setting_labels_match_gui`
- `test_11kb_log_setting_labels_match_gui`
- `test_11l_download_directory_browse_button_opens_dir_dialog`
- `test_11m_playback_setting_labels_match_gui`
- `test_07b_appearance_theme_segment_disables_follow_system`
- `test_13c_log_table_summary_column_stays_visible_at_gui_width`
- 日志详情复制/导出与可读展示仍由 `test_13c_log_detail_copy_export_actions_match_gui` 覆盖。

## 后续待继续细查

- 配置中心其他子页仍需继续逐控件比对：行高、按钮宽度、开关状态、深浅主题和主题色状态。
- 队列、下载中、已完成、失败列表仍需继续逐页复查 hover/selected 叠加态、分页、右侧详情和底部状态栏。
- 工具箱 GUI 尚未最终定型，按当前目标暂不纳入最终同步验收。
- 后续每轮新增 GUI/WebUI 同步改动后仍必须执行完整 `python -m pytest -q`，并重新检查联系表截图。
